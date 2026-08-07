"""Start both RealSense cameras and the cube state node together.

Depth is turned off since this node only needs color images. Each camera
needs a distinct camera_name/serial_no so their topics don't collide —
fill in serial_no with each device's actual serial (`rs-enumerate-devices`).

camera_namespace is set to "" so topics come out as /camera_a/color/image_raw
and /camera_b/color/image_raw (matching config/roi.yaml's image_topic
entries), instead of the driver's default doubled-up
/camera_a/camera_a/color/image_raw.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    camera_a_node = Node(
        package="realsense2_camera",
        executable="realsense2_camera_node",
        name="camera_a",
        parameters=[
            {
                "camera_name": "camera_a",
                "camera_namespace": "",
                "serial_no": "",  # TODO: fill in this camera's serial number
                "enable_color": True,
                "enable_depth": False,
                "enable_infra1": False,
                "enable_infra2": False,
                "align_depth.enable": False,
            }
        ],
    )

    camera_b_node = Node(
        package="realsense2_camera",
        executable="realsense2_camera_node",
        name="camera_b",
        parameters=[
            {
                "camera_name": "camera_b",
                "camera_namespace": "",
                "serial_no": "",  # TODO: fill in this camera's serial number
                "enable_color": True,
                "enable_depth": False,
                "enable_infra1": False,
                "enable_infra2": False,
                "align_depth.enable": False,
            }
        ],
    )

    cube_state_node = Node(
        package="cube_state_detector",
        executable="cube_state_node",
        name="cube_state_node",
    )

    return LaunchDescription([camera_a_node, camera_b_node, cube_state_node])
