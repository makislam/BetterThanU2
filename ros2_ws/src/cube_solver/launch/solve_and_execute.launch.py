"""Brings up the motor action server and the solver node together — the
"solve + execute" half of the pipeline, assuming a cube state has already
been captured and labeled (see cube_pipeline.launch.py for the full flow
including capture/labeling).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    vision_tool_dir_arg = DeclareLaunchArgument(
        "vision_tool_dir",
        default_value="/home/makis/workspaces/BetterThanU2/cube_vision_tool",
        description="Path to cube_vision_tool, so the solver can auto-load the latest labeled state.",
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
            "vision_tool_dir": LaunchConfiguration("vision_tool_dir"),
        }],
    )

    return LaunchDescription([vision_tool_dir_arg, motor_action_server, solver_node])
