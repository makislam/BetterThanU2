import random
import sys
import termios
import tty

import rclpy
from rclpy.node import Node

from cube_motor_control.motor_driver import MotorDriver, MoveError, load_config

QUIT_KEYS = ("\x03", "q")  # Ctrl-C, q
DEMO_KEY = "p"


class KeyboardMotorControl(Node):
    def __init__(self):
        super().__init__("keyboard_motor_control")
        self.declare_parameter("demo", False)
        self.declare_parameter("scramble_length", 20)

        config = load_config()
        self.driver = MotorDriver(config, self.get_logger())
        self.motors = config["motors"]
        self.key_to_face = {}
        for face, motor in self.motors.items():
            self.key_to_face[motor["key"].lower()] = face
            self.get_logger().info(f"{face} motor (id {motor['id']}) armed on key '{motor['key']}'")

        self.get_logger().info(
            "Ready. Press a face key for +90 CW, Shift+key for -90 CCW, "
            f"'{DEMO_KEY}' to scramble+solve, Ctrl-C or 'q' to quit."
        )

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
            self.driver.jog(face, clockwise)

        self.get_logger().info("Demo: scramble complete, solving...")
        for face, clockwise in reversed(moves):
            self.driver.jog(face, not clockwise)

        self.get_logger().info("Demo: solve complete, cube back to start state")

    def shutdown(self):
        self.driver.shutdown()


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
                    node.driver.jog(face, clockwise=key.islower())
                except MoveError as exc:
                    node.get_logger().error(str(exc))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
