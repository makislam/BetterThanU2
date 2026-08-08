"""Brings up cube_capture_pipeline_node, hosting /cube_vision/run_pipeline -
one call to run capture -> label upper -> label lower -> compare -> solve
(see pipeline_node.py for why this shells out to cube_vision_tool's own
venv instead of importing those scripts directly).

Run: ros2 launch cube_capture_pipeline run_pipeline.launch.py
     [vision_tool_dir:=/path/to/cube_vision_tool]
Then: ros2 service call /cube_vision/run_pipeline std_srvs/srv/Trigger "{}"
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    vision_tool_dir_arg = DeclareLaunchArgument(
        "vision_tool_dir",
        default_value="/home/makis/workspaces/BetterThanU2/cube_vision_tool",
        description="Path to cube_vision_tool (its own venv, capture_gui.py, label_gui.py, dataset/).",
    )

    pipeline_node = Node(
        package="cube_capture_pipeline",
        executable="pipeline_node",
        name="cube_capture_pipeline_node",
        parameters=[{
            "vision_tool_dir": LaunchConfiguration("vision_tool_dir"),
        }],
    )

    return LaunchDescription([vision_tool_dir_arg, pipeline_node])
