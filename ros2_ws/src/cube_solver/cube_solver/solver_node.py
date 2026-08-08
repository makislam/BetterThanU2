"""ROS 2 node that turns a captured cube state into a move list via a
pluggable solver backend (see backends/), then optionally drives those
moves through the motor rig by calling the ExecuteSolve action hosted by
cube_motor_control's motor_action_server.

Swapping in a different algorithm (Korf's, etc.) later means adding a new
SolverBackend subclass in backends/registry.py — this node only depends on
the `algorithm` parameter naming a registered backend, nothing here changes.

Two services are exposed, both cube_solver_interfaces/srv/SolveCube:
  /cube_solver/solve_cube        - solve only, report the moves
  /cube_solver/solve_and_execute - solve, then drive the moves through the
                                    motor rig and report the outcome

In both, leaving the request's `facelets` field empty auto-loads the most
recently labeled state from cube_vision_tool's dataset (see
_latest_labeled_facelets) instead of requiring the caller to pass a
54-character string by hand.
"""

import json
import os
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from cube_motor_control import pending_solve
from cube_solver_interfaces.action import ExecuteSolve
from cube_solver_interfaces.srv import SolveCube

from cube_solver.backends.registry import get_backend


def _latest_labeled_facelets(vision_tool_dir):
    """Reads cube_vision_tool's dataset/master_index.jsonl directly (plain
    JSON Lines - no cv2/PyQt import needed here) and returns the most recent
    upper_corner/lower_corner label records merged into a 54-slot facelet
    list (None for occluded/unlabeled cells), matching what
    cube_vision_tool/solve_state.py builds before calling its occlusion
    solver. Reuses facelet_index from cube_vision_tool/common (pure Python,
    no heavy deps) rather than redefining the URFDLB indexing scheme here.
    """
    if vision_tool_dir not in sys.path:
        sys.path.insert(0, vision_tool_dir)
    from common.cube_topology import facelet_index  # noqa: E402

    master_index_path = os.path.join(vision_tool_dir, "dataset", "master_index.jsonl")
    if not os.path.exists(master_index_path):
        raise RuntimeError(f"No dataset found at {master_index_path} - capture and label a state first.")

    latest = {}
    with open(master_index_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record["slot"] in ("upper_corner", "lower_corner"):
                latest[record["slot"]] = record

    missing = [s for s in ("upper_corner", "lower_corner") if s not in latest]
    if missing:
        raise RuntimeError(f"No labeled record found for: {missing}. Label both views first.")

    facelets = [None] * 54
    for record in latest.values():
        for face in record["faces"]:
            for cell in face["cells"]:
                idx = facelet_index(face["face"], cell["row"], cell["col"])
                facelets[idx] = None if cell["occluded"] else cell["label"]
    return facelets


class CubeSolverNode(Node):
    def __init__(self):
        super().__init__("cube_solver_node")
        self.declare_parameter("algorithm", "kociemba")
        self.declare_parameter("vision_tool_dir", "")
        self.declare_parameter("motor_action_name", "/cube_motor_control/execute_solve")

        self._action_client = ActionClient(
            self, ExecuteSolve, self.get_parameter("motor_action_name").value
        )
        self.create_service(SolveCube, "/cube_solver/solve_cube", self._on_solve_cube)
        self.create_service(SolveCube, "/cube_solver/solve_and_execute", self._on_solve_and_execute)

        self.get_logger().info(
            "cube_solver_node ready: /cube_solver/solve_cube (solve only), "
            "/cube_solver/solve_and_execute (solve + drive motors). Leave "
            "'facelets' empty in the request to auto-load the latest "
            "labeled state from cube_vision_tool's dataset."
        )

    def _resolve_facelets(self, request):
        if request.facelets:
            return request.facelets
        vision_tool_dir = self.get_parameter("vision_tool_dir").value
        if not vision_tool_dir:
            raise RuntimeError(
                "No facelets given and the 'vision_tool_dir' parameter is unset - "
                "can't auto-load the latest labeled state."
            )
        facelets = _latest_labeled_facelets(vision_tool_dir)
        if any(f is None for f in facelets):
            raise RuntimeError(
                "Latest labeled state has occluded/unlabeled cells; run "
                "cube_vision_tool/solve_state.py to resolve them (or fully "
                "label both views) before solving."
            )
        return "".join(facelets)

    def _solve(self, request):
        facelets = self._resolve_facelets(request)
        algorithm = request.algorithm or self.get_parameter("algorithm").value
        backend = get_backend(algorithm)
        moves = backend.solve(facelets)
        self.get_logger().info(f"[{algorithm}] solved {facelets} -> {' '.join(moves)}")
        return moves

    def _on_solve_cube(self, request, response):
        try:
            moves = self._solve(request)
        except (RuntimeError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.moves = []
            return response
        response.success = True
        response.message = f"{len(moves)} moves"
        response.moves = moves
        return response

    async def _on_solve_and_execute(self, request, response):
        # This callback runs inside the executor's own spin (started once by
        # main()'s rclpy.spin(node)) - blocking here with
        # rclpy.spin_until_future_complete(self, ...) would try to re-enter
        # that same spin from inside itself and raise "Executor is already
        # spinning". `await`ing the futures instead lets the *existing* spin
        # keep servicing the action client's callbacks while this coroutine
        # is suspended, with no nested spin at all.
        pending = pending_solve.load_pending()
        if pending is not None:
            moves = pending["moves"][pending["completed"]:]
            self.get_logger().info(
                f"resuming pending solve: {pending['completed']}/{len(pending['moves'])} "
                f"moves already done, {len(moves)} remaining — not re-solving from vision"
            )
        else:
            try:
                moves = self._solve(request)
            except (RuntimeError, ValueError) as exc:
                response.success = False
                response.message = str(exc)
                response.moves = []
                return response

        if not self._action_client.wait_for_server(timeout_sec=5.0):
            response.success = False
            response.message = "motor action server not available"
            response.moves = moves
            return response

        goal = ExecuteSolve.Goal()
        goal.moves = moves
        goal_handle = await self._action_client.send_goal_async(goal)
        if goal_handle is None or not goal_handle.accepted:
            response.success = False
            response.message = "motor action server rejected the goal"
            response.moves = moves
            return response

        result = (await goal_handle.get_result_async()).result

        response.success = result.success
        response.message = result.message
        response.moves = moves
        return response


def main(args=None):
    rclpy.init(args=args)
    node = CubeSolverNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
