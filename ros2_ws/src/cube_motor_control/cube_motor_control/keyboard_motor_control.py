import random
import sys
import termios
import time
import tty
from pathlib import Path

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node

from dynamixel_sdk import (
    COMM_SUCCESS,
    PacketHandler,
    PortHandler,
)

ADDR_OPERATING_MODE = 11
ADDR_PROFILE_ACCELERATION = 108
ADDR_PROFILE_VELOCITY = 112
ADDR_TORQUE_ENABLE = 64
ADDR_GOAL_POSITION = 116
ADDR_MOVING = 122
ADDR_PRESENT_POSITION = 132
EXTENDED_POSITION_CONTROL_MODE = 4

QUIT_KEYS = ("\x03", "q")  # Ctrl-C, q
DEMO_KEY = "p"

MOVE_TOLERANCE_DEGREES = 20
SETTLE_TIMEOUT_S = 3.0
SETTLE_POLL_S = 0.02


def load_config():
    default_path = Path(get_package_share_directory("cube_motor_control")) / "config" / "motors.yaml"
    with open(default_path) as f:
        return yaml.safe_load(f)


class MoveError(Exception):
    """Raised when a motor doesn't land within tolerance of the commanded turn."""


class KeyboardMotorControl(Node):
    def __init__(self):
        super().__init__("keyboard_motor_control")
        self.declare_parameter("demo", False)
        self.declare_parameter("scramble_length", 20)

        config = load_config()
        self.ticks_per_rev = config["ticks_per_rev"]
        self.step_ticks = round(config["step_degrees"] / 360 * self.ticks_per_rev)
        self.tolerance_ticks = round(MOVE_TOLERANCE_DEGREES / 360 * self.ticks_per_rev)
        self.motors = config["motors"]
        self.key_to_face = {}
        for face, motor in self.motors.items():
            self.key_to_face[motor["key"].lower()] = face

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
            self.get_logger().info(f"{face} motor (id {dxl_id}) armed on key '{motor['key']}'")

        self.get_logger().info(
            "Ready. Press a face key for +90 CW, Shift+key for -90 CCW, "
            f"'{DEMO_KEY}' to scramble+solve, Ctrl-C or 'q' to quit."
        )

    def _write(self, dxl_id, address, value, size):
        writers = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}
        result, error = writers[size](self.port, dxl_id, address, value)
        if result != COMM_SUCCESS:
            self.get_logger().error(f"id {dxl_id} addr {address}: {self.packet.getTxRxResult(result)}")
        elif error != 0:
            self.get_logger().error(f"id {dxl_id} addr {address}: {self.packet.getRxPacketError(error)}")

    def _read_present_position(self, dxl_id, retries=3):
        # A single dropped status packet on a fast bus shouldn't abort an
        # otherwise-safe solve, so retry a few times before giving up.
        for attempt in range(retries):
            position, result, error = self.packet.read4ByteTxRx(self.port, dxl_id, ADDR_PRESENT_POSITION)
            if result == COMM_SUCCESS and error == 0:
                return position
            if attempt < retries - 1:
                time.sleep(SETTLE_POLL_S)
        self.get_logger().error(f"id {dxl_id}: failed to read present position after {retries} attempts")
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

        self.get_logger().info(f"{face} motor (id {dxl_id}) -> {'CW' if clockwise else 'CCW'} 90deg OK")

    def scramble_and_solve(self, length):
        faces = list(self.motors.keys())
        moves = []
        last_face = None
        for _ in range(length):
            face = random.choice([f for f in faces if f != last_face] or faces)
            clockwise = random.choice([True, False])
            moves.append((face, clockwise))
            last_face = face

        notation = " ".join(f"{face}{'' if cw else chr(39)}" for face, cw in moves)
        self.get_logger().info(f"Demo: scrambling with {length} moves: {notation}")
        for face, clockwise in moves:
            self.jog(face, clockwise)

        self.get_logger().info("Demo: scramble complete, solving...")
        for face, clockwise in reversed(moves):
            self.jog(face, not clockwise)

        self.get_logger().info("Demo: solve complete, cube back to start state")

    def shutdown(self):
        for motor in self.motors.values():
            self._write(motor["id"], ADDR_TORQUE_ENABLE, 0, 1)
        self.port.closePort()


def read_key(settings):
    tty.setraw(sys.stdin.fileno())
    key = sys.stdin.read(1)
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
    return key


def main():
    rclpy.init()
    node = KeyboardMotorControl()
    settings = termios.tcgetattr(sys.stdin)
    try:
        if node.get_parameter("demo").value:
            length = node.get_parameter("scramble_length").value
            try:
                node.scramble_and_solve(length)
            except MoveError as exc:
                node.get_logger().error(f"Demo aborted: {exc}")

        while rclpy.ok():
            key = read_key(settings)
            if key in QUIT_KEYS:
                break
            if key.lower() == DEMO_KEY:
                length = node.get_parameter("scramble_length").value
                try:
                    node.scramble_and_solve(length)
                except MoveError as exc:
                    node.get_logger().error(f"Demo aborted: {exc}")
                continue
            face = node.key_to_face.get(key.lower())
            if face is not None:
                try:
                    node.jog(face, clockwise=key.islower())
                except MoveError as exc:
                    node.get_logger().error(str(exc))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
