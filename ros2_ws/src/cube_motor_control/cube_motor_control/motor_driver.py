"""Owns the Dynamixel bus connection and the verified quarter-turn jog for
each of the 6 face motors. Extracted out of keyboard_motor_control.py so the
ExecuteSolve action server (motor_action_server.py) can drive the exact same
bus protocol a solved move list needs, without duplicating it.
"""

import time
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

ADDR_OPERATING_MODE = 11
ADDR_PROFILE_ACCELERATION = 108
ADDR_PROFILE_VELOCITY = 112
ADDR_TORQUE_ENABLE = 64
ADDR_GOAL_POSITION = 116
ADDR_MOVING = 122
ADDR_PRESENT_POSITION = 132
EXTENDED_POSITION_CONTROL_MODE = 4

MOVE_TOLERANCE_DEGREES = 20
SETTLE_TIMEOUT_S = 3.0
SETTLE_POLL_S = 0.02


def load_config():
    default_path = Path(get_package_share_directory("cube_motor_control")) / "config" / "motors.yaml"
    with open(default_path) as f:
        return yaml.safe_load(f)


class MoveError(Exception):
    """Raised when a motor doesn't land within tolerance of the commanded turn."""


class MotorDriver:
    def __init__(self, config, logger):
        self.logger = logger
        self.ticks_per_rev = config["ticks_per_rev"]
        self.step_ticks = round(config["step_degrees"] / 360 * self.ticks_per_rev)
        self.tolerance_ticks = round(MOVE_TOLERANCE_DEGREES / 360 * self.ticks_per_rev)
        self.motors = config["motors"]
        # verify_moves=false skips reading position before/after every move
        # and the settle/tolerance checks entirely, commanding turns
        # open-loop from a software-tracked position instead. This means a
        # transient bus read glitch (or a real slipped/stalled motor) can no
        # longer abort a solve - but a real slip also goes undetected and
        # can silently misalign the cube on later moves. Off by default is
        # the safe choice; this rig currently runs with it explicitly
        # disabled because moves are reliable and restarting mid-solve for
        # rare transient read failures was worse in practice.
        self.verify_moves = config.get("verify_moves", True)
        self.unverified_settle_s = config.get("unverified_move_settle_s", 0.4)
        self._assumed_position = {}

        self.port = PortHandler(config["port"])
        self.packet = PacketHandler(str(config["protocol_version"]))
        if not self.port.openPort():
            raise RuntimeError(f"could not open {config['port']}")
        if not self.port.setBaudRate(config["baud_rate"]):
            raise RuntimeError(f"could not set baud rate {config['baud_rate']}")

        for face, motor in self.motors.items():
            dxl_id = motor["id"]
            self._write(dxl_id, ADDR_TORQUE_ENABLE, 0, 1)
            self._write(dxl_id, ADDR_OPERATING_MODE, EXTENDED_POSITION_CONTROL_MODE, 1)
            self._write(dxl_id, ADDR_PROFILE_ACCELERATION, config["profile_acceleration"], 4)
            self._write(dxl_id, ADDR_PROFILE_VELOCITY, config["profile_velocity"], 4)
            self._write(dxl_id, ADDR_TORQUE_ENABLE, 1, 1)
            self.logger.info(f"{face} motor (id {dxl_id}) armed")
            if not self.verify_moves:
                # Open-loop mode never reads position again after this, so
                # get one best-effort baseline now; if even this fails,
                # assume 0 rather than blocking startup on a transient glitch.
                position = self._read_present_position(dxl_id)
                self._assumed_position[dxl_id] = position if position is not None else 0

    def _write(self, dxl_id, address, value, size):
        writers = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}
        result, error = writers[size](self.port, dxl_id, address, value)
        if result != COMM_SUCCESS:
            self.logger.error(f"id {dxl_id} addr {address}: {self.packet.getTxRxResult(result)}")
        elif error != 0:
            self.logger.error(f"id {dxl_id} addr {address}: {self.packet.getRxPacketError(error)}")

    def _read_present_position(self, dxl_id, retries=3):
        # A single dropped status packet on a fast bus shouldn't abort an
        # otherwise-safe solve, so retry a few times before giving up.
        for attempt in range(retries):
            position, result, error = self.packet.read4ByteTxRx(self.port, dxl_id, ADDR_PRESENT_POSITION)
            if result == COMM_SUCCESS and error == 0:
                return position
            if attempt < retries - 1:
                time.sleep(SETTLE_POLL_S)
        self.logger.error(f"id {dxl_id}: failed to read present position after {retries} attempts")
        return None

    def _read_moving(self, dxl_id):
        moving, result, error = self.packet.read1ByteTxRx(self.port, dxl_id, ADDR_MOVING)
        if result != COMM_SUCCESS or error != 0:
            return None
        return bool(moving)

    def _wait_until_settled(self, dxl_id):
        # The Moving bit doesn't flip to 1 the instant the goal write lands, so
        # checking "not moving" before it's ever been seen moving would pass
        # instantly on a motor that hasn't started yet. Wait to see it move first.
        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        seen_moving = False
        while time.monotonic() < deadline:
            moving = self._read_moving(dxl_id)
            if moving:
                seen_moving = True
            elif moving is False and seen_moving:
                return True
            time.sleep(SETTLE_POLL_S)
        return seen_moving is False  # never having moved is caught by the position check

    def jog(self, face, clockwise):
        """Commands a quarter turn. See _jog_verified/_jog_unverified for
        the two modes (self.verify_moves)."""
        if self.verify_moves:
            self._jog_verified(face, clockwise)
        else:
            self._jog_unverified(face, clockwise)

    def _jog_unverified(self, face, clockwise):
        """Commands a quarter turn open-loop: no position reads, no settle
        wait, no tolerance check. Target is computed from a software-tracked
        position updated unconditionally after every move, so a slipped or
        stalled motor is never detected here."""
        motor = self.motors[face]
        dxl_id = motor["id"]

        delta = self.step_ticks if clockwise else -self.step_ticks
        target = self._assumed_position[dxl_id] + delta
        self._write(dxl_id, ADDR_GOAL_POSITION, target, 4)
        time.sleep(self.unverified_settle_s)
        self._assumed_position[dxl_id] = target

        self.logger.info(
            f"{face} motor (id {dxl_id}) -> {'CW' if clockwise else 'CCW'} 90deg (unverified)"
        )

    def _jog_verified(self, face, clockwise):
        """Commands a quarter turn and verifies the motor actually got there.

        Raises MoveError if the motor is off by more than MOVE_TOLERANCE_DEGREES,
        since a silently-undershot/overshot move compounds into a jammed cube
        on every subsequent relative move.
        """
        motor = self.motors[face]
        dxl_id = motor["id"]

        before = self._read_present_position(dxl_id)
        if before is None:
            raise MoveError(f"{face} motor (id {dxl_id}): could not read starting position")

        delta = self.step_ticks if clockwise else -self.step_ticks
        self._write(dxl_id, ADDR_GOAL_POSITION, before + delta, 4)

        if not self._wait_until_settled(dxl_id):
            raise MoveError(f"{face} motor (id {dxl_id}): did not settle within {SETTLE_TIMEOUT_S}s")

        after = self._read_present_position(dxl_id)
        if after is None:
            raise MoveError(f"{face} motor (id {dxl_id}): could not read ending position")

        achieved = after - before
        error_ticks = abs(achieved - delta)
        if error_ticks > self.tolerance_ticks:
            error_degrees = error_ticks / self.ticks_per_rev * 360
            raise MoveError(
                f"{face} motor (id {dxl_id}) landed {error_degrees:.1f}deg off target "
                f"(tolerance {MOVE_TOLERANCE_DEGREES}deg) - stopping to avoid jamming the cube"
            )

        self.logger.info(f"{face} motor (id {dxl_id}) -> {'CW' if clockwise else 'CCW'} 90deg OK")

    def turn(self, move):
        """Executes one move in standard cube notation: a face letter
        (U/R/F/D/L/B) optionally followed by \"'\" (CCW quarter turn) or \"2\"
        (half turn, done as two verified quarter turns rather than a single
        180deg command so a slip is still caught after the first 90deg)."""
        move = move.strip()
        if not move:
            raise MoveError("empty move")
        face, suffix = move[0], move[1:]
        if face not in self.motors:
            raise MoveError(f"unknown face '{face}' in move '{move}'")
        if suffix in ("", "2"):
            self.jog(face, clockwise=True)
            if suffix == "2":
                self.jog(face, clockwise=True)
        elif suffix == "'":
            self.jog(face, clockwise=False)
        else:
            raise MoveError(f"unrecognized move '{move}'")

    def shutdown(self):
        for motor in self.motors.values():
            self._write(motor["id"], ADDR_TORQUE_ENABLE, 0, 1)
        self.port.closePort()
