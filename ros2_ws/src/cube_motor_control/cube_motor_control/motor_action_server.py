"""ROS 2 node that hosts /cube_motor_control/execute_solve — an action any
solver node can send a move list to, so a solve is actually turned into cube
moves. Wraps the same MotorDriver (and MOVE_TOLERANCE_DEGREES verification)
that keyboard_motor_control.py uses, so a slipping/stuck motor aborts the
whole solve instead of jamming the cube.

The move list and how far it got are persisted to disk after every verified
move (see pending_solve.py) so a failed/aborted solve can be resumed rather
than lost — cube_solver_node's solve_and_execute checks for this before
deciding whether to solve fresh from vision or finish the remaining moves.
"""

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node
from std_srvs.srv import Trigger

from cube_motor_control import pending_solve
from cube_motor_control.motor_driver import OPPOSITE_FACE, MoveError, MotorDriver, load_config
from cube_solver_interfaces.action import ExecuteSolve


def _group_moves(moves):
    """Groups adjacent moves whose faces are on opposite sides of the cube
    (U/D, L/R, F/B) so they can be jogged at the same time via turn_group -
    those motors never interact, so grouping them doesn't change the solve's
    effect, only its wall-clock time. Only ever groups *adjacent* moves, so
    move order (and therefore correctness) for anything else is unchanged."""
    groups = []
    i = 0
    while i < len(moves):
        if i + 1 < len(moves) and OPPOSITE_FACE.get(moves[i][0]) == moves[i + 1][0]:
            groups.append([moves[i], moves[i + 1]])
            i += 2
        else:
            groups.append([moves[i]])
            i += 1
    return groups


class MotorActionServer(Node):
    def __init__(self):
        super().__init__("motor_action_server")
        config = load_config()
        self.driver = MotorDriver(config, self.get_logger())
        self._action_server = ActionServer(
            self, ExecuteSolve, "/cube_motor_control/execute_solve", self._execute
        )
        self.create_service(
            Trigger, "/cube_motor_control/clear_pending_solve", self._clear_pending_solve
        )
        self.get_logger().info(
            "motor_action_server ready, hosting /cube_motor_control/execute_solve "
            "and /cube_motor_control/clear_pending_solve"
        )

    def _clear_pending_solve(self, request, response):
        pending_solve.clear_pending()
        response.success = True
        response.message = "cleared any pending partial solve"
        return response

    def _execute(self, goal_handle):
        moves = goal_handle.request.moves
        result = ExecuteSolve.Result()
        pending_solve.save_pending(moves, 0)

        index = 0
        for group in _group_moves(moves):
            errors = self.driver.turn_group(group)

            if any(errors):
                # A group can partially succeed (one face's motor lands fine
                # while its concurrently-jogged opposite-face partner
                # slips). pending_solve's resume logic re-runs everything
                # from `completed` onward as a contiguous block, so rather
                # than track non-contiguous per-move success, treat the
                # whole group as not completed - the cost is at most one
                # already-successful quarter/half turn redone on resume,
                # which is far safer than the bookkeeping needed to skip it.
                exc = next(e for e in errors if e is not None)
                self.get_logger().error(f"move {index} ({group}) failed: {exc}")
                self.get_logger().error(
                    f"{index}/{len(moves)} moves completed before this failure — "
                    "saved to disk, next solve_and_execute call will resume from here"
                )
                result.success = False
                result.message = str(exc)
                result.moves_completed = index
                goal_handle.abort()
                return result

            index += len(group)
            pending_solve.save_pending(moves, index)
            for offset, move in enumerate(group):
                feedback = ExecuteSolve.Feedback()
                feedback.move_index = index - len(group) + offset
                feedback.move = move
                goal_handle.publish_feedback(feedback)

        pending_solve.clear_pending()
        result.success = True
        result.message = f"executed {len(moves)} moves"
        result.moves_completed = len(moves)
        goal_handle.succeed()
        return result

    def shutdown(self):
        self.driver.shutdown()


def main(args=None):
    rclpy.init(args=args)
    node = MotorActionServer()
    try:
        rclpy.spin(node)
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
