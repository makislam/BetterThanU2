"""ROS 2 node that runs cube_vision_tool's full scan-to-solution sequence
in one call, instead of the 5 separate hand-run commands
(capture_gui.py -> label_latest.py x2 -> compare_state_gui.py ->
solve_state.py).

cube_vision_tool's scripts only run in its own venv (pyrealsense2/PyQt5/
opencv aren't in the ROS 2 Python environment - see
cube_solver/launch/cube_pipeline.launch.py, which shells out to
.venv/bin/python3 for the same reason). This node does the same via plain
blocking subprocess.run() calls in a normal Python function, which gives
natural step-by-step sequencing for free - no OnProcessExit event-handler
chaining needed like that launch file uses, since these aren't async
launch actions.

Stops at solve_state.py's output (facelet string + kociemba validity +
move list) - it does NOT drive the motors. Physically executing a solve
stays a deliberate separate step via /cube_solver/solve_and_execute.

Run: ros2 launch cube_capture_pipeline run_pipeline.launch.py
     [vision_tool_dir:=/path/to/cube_vision_tool]
Then: ros2 service call /cube_vision/run_pipeline std_srvs/srv/Trigger "{}"
"""

import os
import subprocess

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

STDERR_TAIL_LINES = 20


class CapturePipelineNode(Node):
    def __init__(self):
        super().__init__("cube_capture_pipeline_node")
        self.declare_parameter("vision_tool_dir", "")
        self.create_service(Trigger, "/cube_vision/run_pipeline", self._run_pipeline)
        self.get_logger().info(
            "cube_capture_pipeline_node ready, hosting /cube_vision/run_pipeline"
        )

    def _venv_python(self):
        vision_tool_dir = self.get_parameter("vision_tool_dir").value
        if not vision_tool_dir:
            raise RuntimeError("'vision_tool_dir' parameter is unset")
        return os.path.join(vision_tool_dir, ".venv", "bin", "python3"), vision_tool_dir

    def _run_step(self, name, args, venv_python, vision_tool_dir, capture_stdout=False):
        self.get_logger().info(f"running: {name}")
        result = subprocess.run(
            [venv_python] + args,
            cwd=vision_tool_dir,
            capture_output=capture_stdout,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr if capture_stdout else None
            tail = "\n".join(stderr.splitlines()[-STDERR_TAIL_LINES:]) if stderr else (
                "(see terminal output above for details)"
            )
            raise RuntimeError(f"step '{name}' failed (exit {result.returncode}): {tail}")
        self.get_logger().info(f"finished: {name}")
        return result.stdout if capture_stdout else None

    def _run_solve_state(self, venv_python, vision_tool_dir):
        """solve_state.py exits non-zero for its own expected diagnostic
        outcomes too (no_solution/setup error, not just plumbing failures),
        and prints the actual reason to stdout rather than stderr - so
        unlike the other steps, a non-zero exit here isn't a pipeline
        failure to raise on. Always return (ran_ok, stdout) and let the
        caller report whatever solve_state.py actually said."""
        self.get_logger().info("running: solve_state.py")
        result = subprocess.run(
            [venv_python, "solve_state.py"], cwd=vision_tool_dir,
            capture_output=True, text=True,
        )
        self.get_logger().info(f"finished: solve_state.py (exit {result.returncode})")
        return result.returncode == 0, result.stdout or result.stderr

    def _run_pipeline(self, request, response):
        try:
            venv_python, vision_tool_dir = self._venv_python()

            self._run_step("capture_gui.py", ["capture_gui.py"], venv_python, vision_tool_dir)
            self._run_step(
                "label upper_corner",
                ["label_latest.py", "--slot", "upper_corner"],
                venv_python, vision_tool_dir,
            )
            self._run_step(
                "label lower_corner",
                ["label_latest.py", "--slot", "lower_corner"],
                venv_python, vision_tool_dir,
            )
            self._run_step(
                "compare_state_gui.py", ["compare_state_gui.py"], venv_python, vision_tool_dir
            )
        except RuntimeError as exc:
            self.get_logger().error(str(exc))
            response.success = False
            response.message = str(exc)
            return response

        solved, solve_output = self._run_solve_state(venv_python, vision_tool_dir)
        comparison_path = os.path.join(vision_tool_dir, "state_comparison.png")
        response.success = solved
        response.message = f"{comparison_path}\n\n{solve_output}"
        return response


def main(args=None):
    rclpy.init(args=args)
    node = CapturePipelineNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
