"""CLI to scramble the cube: generates a random N-move scramble in standard
cube notation and sends it to /cube_motor_control/execute_solve, the same
action cube_solver_node uses to execute a solve.
"""

import argparse
import random
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from cube_motor_control.motor_driver import OPPOSITE_FACE
from cube_solver_interfaces.action import ExecuteSolve

FACES = list(OPPOSITE_FACE.keys())
SUFFIXES = ("", "'", "2")


def generate_scramble(length):
    """WCA-style random scramble: never repeats the same face twice in a row,
    and never turns both faces of the same axis back-to-back (which would
    just undo/redo the same axis rather than genuinely mixing the cube)."""
    moves = []
    last_face = None
    last_axis_face = None
    for _ in range(length):
        choices = [f for f in FACES if f != last_face and f != OPPOSITE_FACE.get(last_axis_face)]
        face = random.choice(choices)
        moves.append(face + random.choice(SUFFIXES))
        last_face = face
        last_axis_face = face
    return moves


class ScrambleClient(Node):
    def __init__(self):
        super().__init__("scramble_cube")
        self._client = ActionClient(self, ExecuteSolve, "/cube_motor_control/execute_solve")

    def send(self, moves):
        self.get_logger().info(f"Scrambling with {len(moves)} moves: {' '.join(moves)}")
        if not self._client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("execute_solve action server not available")
            return False

        goal = ExecuteSolve.Goal()
        goal.moves = moves
        future = self._client.send_goal_async(
            goal, feedback_callback=lambda fb: self.get_logger().info(
                f"move {fb.feedback.move_index}: {fb.feedback.move}"
            )
        )
        rclpy.spin_until_future_complete(self, future)
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error("scramble goal rejected")
            return False

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        result = result_future.result().result
        if result.success:
            self.get_logger().info(f"Scramble complete: {result.message}")
        else:
            self.get_logger().error(f"Scramble failed: {result.message}")
        return result.success


def main(args=None):
    parser = argparse.ArgumentParser(description="Scramble the cube with random moves.")
    parser.add_argument("-n", "--length", type=int, default=20, help="number of moves (default 20)")
    parsed = parser.parse_args(args=args)

    rclpy.init(args=args)
    node = ScrambleClient()
    try:
        success = node.send(generate_scramble(parsed.length))
    finally:
        node.destroy_node()
        rclpy.shutdown()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
