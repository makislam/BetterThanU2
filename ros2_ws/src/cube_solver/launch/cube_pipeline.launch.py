"""End-to-end pipeline: capture two views -> label each -> compare -> solve
-> drive the motors, all from one persistent GUI (cube_vision_tool's
hmi_app.py) instead of a chain of separate windows that close between
steps. Brings up the motor action server + solver node alongside it; the
HMI's Solve/Execute buttons call their services directly (waiting up to 5s
for them to come up), so there's no fixed startup delay or auto-call to
race against.

hmi_app.py needs BOTH cube_vision_tool's own venv (PyQt5, opencv,
pyrealsense2) AND this sourced ROS 2 workspace (rclpy,
cube_solver_interfaces, cube_motor_control) importable from the same
interpreter. That works as long as the venv was NOT created with
`--system-site-packages` disabled in a way that blocks PYTHONPATH: `ros2
launch` inherits your shell's environment, so the ROS 2 install's
PYTHONPATH (from `source install/setup.bash`) is visible to the venv's
python3 alongside its own site-packages. If hmi_app.py fails to import
rclpy, that's the thing to check first.

Run: ros2 launch cube_solver cube_pipeline.launch.py
     [vision_tool_dir:=/path/to/cube_vision_tool]

If you need any individual step standalone, cube_vision_tool's own
capture_gui.py / label_gui.py / compare_state_gui.py / solve_state.py still
work exactly as before.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    vision_tool_dir_arg = DeclareLaunchArgument(
        "vision_tool_dir",
        default_value="/home/makis/workspaces/BetterThanU2/cube_vision_tool",
        description="Path to cube_vision_tool (its own venv, hmi_app.py, dataset/).",
    )
    vision_tool_dir = LaunchConfiguration("vision_tool_dir")
    venv_python = PathJoinSubstitution([vision_tool_dir, ".venv", "bin", "python3"])

    hmi_app = ExecuteProcess(
        cmd=[venv_python, "hmi_app.py"],
        cwd=vision_tool_dir,
        name="hmi_app",
        output="screen",
    )

    motor_action_server = Node(
        package="cube_motor_control",
        executable="motor_action_server",
        name="motor_action_server",
    )

    solver_node = Node(
        package="cube_solver",
        executable="cube_solver_node",
        name="cube_solver_node",
        parameters=[{
            "algorithm": "kociemba",
            "vision_tool_dir": vision_tool_dir,
        }],
    )

    return LaunchDescription([
        vision_tool_dir_arg,
        motor_action_server,
        solver_node,
        hmi_app,
    ])
