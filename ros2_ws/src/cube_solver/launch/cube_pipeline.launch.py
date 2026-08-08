"""End-to-end pipeline: capture two views -> label each -> solve -> drive
the motors. Each capture/label step is a blocking GUI (cube_vision_tool's
own PyQt tools, run through its own venv since it isn't part of the ROS 2
Python environment) - the launch file chains them with OnProcessExit so
each step starts only once you close the previous window having saved your
work, then finally brings up the motor action server + solver node and
calls /cube_solver/solve_and_execute automatically.

Run: ros2 launch cube_solver cube_pipeline.launch.py
     [vision_tool_dir:=/path/to/cube_vision_tool]

If the automatic solve_and_execute call fails because the nodes weren't up
yet within the fixed delay below, just re-run it by hand:
  ros2 service call /cube_solver/solve_and_execute cube_solver_interfaces/srv/SolveCube "{}"
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, RegisterEventHandler, TimerAction
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

# Give the motor action server + solver node this long to come up (Dynamixel
# bus init, etc.) before the pipeline auto-calls solve_and_execute.
MOTOR_STARTUP_DELAY_S = 3.0


def generate_launch_description():
    vision_tool_dir_arg = DeclareLaunchArgument(
        "vision_tool_dir",
        default_value="/home/makis/workspaces/BetterThanU2/cube_vision_tool",
        description="Path to cube_vision_tool (its own venv, capture_gui.py, label_gui.py, dataset/).",
    )
    vision_tool_dir = LaunchConfiguration("vision_tool_dir")
    venv_python = PathJoinSubstitution([vision_tool_dir, ".venv", "bin", "python3"])

    capture_step = ExecuteProcess(
        cmd=[venv_python, "capture_gui.py"],
        cwd=vision_tool_dir,
        name="capture_gui",
        output="screen",
    )

    label_upper_step = ExecuteProcess(
        cmd=[venv_python, "label_latest.py", "--slot", "upper_corner"],
        cwd=vision_tool_dir,
        name="label_upper_corner",
        output="screen",
    )

    label_lower_step = ExecuteProcess(
        cmd=[venv_python, "label_latest.py", "--slot", "lower_corner"],
        cwd=vision_tool_dir,
        name="label_lower_corner",
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

    solve_and_execute_step = ExecuteProcess(
        cmd=[
            "ros2", "service", "call",
            "/cube_solver/solve_and_execute",
            "cube_solver_interfaces/srv/SolveCube",
            "{}",
        ],
        name="solve_and_execute",
        output="screen",
    )

    return LaunchDescription([
        vision_tool_dir_arg,
        capture_step,
        RegisterEventHandler(
            OnProcessExit(target_action=capture_step, on_exit=[label_upper_step])
        ),
        RegisterEventHandler(
            OnProcessExit(target_action=label_upper_step, on_exit=[label_lower_step])
        ),
        RegisterEventHandler(
            OnProcessExit(
                target_action=label_lower_step,
                on_exit=[
                    motor_action_server,
                    solver_node,
                    TimerAction(period=MOTOR_STARTUP_DELAY_S, actions=[solve_and_execute_step]),
                ],
            )
        ),
    ])
