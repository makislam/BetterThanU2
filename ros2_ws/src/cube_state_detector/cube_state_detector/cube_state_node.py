"""ROS 2 node that reads a Rubik's Cube face by face using two cameras.

The cube body never moves in this rig — only individual faces spin, each on
its own motor. So no single camera ever sees more than half the cube, and
nothing ever rotates a new face into view. Instead:

  1. Two cameras are mounted (or held) so that together they see all 6
     faces: each one sees 3 faces at once, listed in `config/roi.yaml`
     under `positions.position_a` / `positions.position_b`.
  2. Cameras can be repositioned before every capture — faces are found by
     detecting the 9 stickers of each face directly in the image (see
     sticker_detect.py) rather than trusting fixed pixel coordinates.
  3. The robot calls `capture_position` with "position_a" or "position_b".
     This reads the latest image from that camera, detects the faces
     visible in it, and classifies all their stickers in one shot.
  4. After both positions have been captured (6 faces total), the robot
     calls `get_cube_state` to get the full 54-character result.

The result is a string of color letters (W, Y, R, O, B, G), 9 per face,
in U R F D L B order. Turning this into solver-ready notation (e.g. for
Kociemba) is a separate step done outside this node.
"""

import os

import cv2
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from cv_bridge import CvBridge
from cube_state_interfaces.srv import CapturePosition, GetCubeState
from rclpy.node import Node
from sensor_msgs.msg import Image

from cube_state_detector.color_classify import classify_color, median_hsv
from cube_state_detector.sticker_detect import detect_faces, find_sticker_candidates

FACE_ORDER = ["U", "R", "F", "D", "L", "B"]


class CubeStateNode(Node):
    def __init__(self):
        super().__init__("cube_state_node")

        default_config_dir = os.path.join(
            get_package_share_directory("cube_state_detector"), "config"
        )
        self.declare_parameter(
            "colors_yaml", os.path.join(default_config_dir, "colors.yaml")
        )
        self.declare_parameter(
            "roi_yaml", os.path.join(default_config_dir, "roi.yaml")
        )
        self.declare_parameter("publish_debug_image", True)

        self.reference_colors = self._load_colors(
            self.get_parameter("colors_yaml").value
        )
        self.positions, self.detection_params = self._load_roi(
            self.get_parameter("roi_yaml").value
        )
        self.publish_debug_image = self.get_parameter("publish_debug_image").value

        self.bridge = CvBridge()
        self.latest_images = {pos: None for pos in self.positions}
        self.captured_faces = {}

        self.image_subs = {}
        self.debug_pubs = {}
        for position_id, position in self.positions.items():
            self.image_subs[position_id] = self.create_subscription(
                Image,
                position["image_topic"],
                self._make_image_callback(position_id),
                10,
            )
            if self.publish_debug_image:
                self.debug_pubs[position_id] = self.create_publisher(
                    Image, f"/cube_state/debug_image/{position_id}", 10
                )

        self.capture_position_srv = self.create_service(
            CapturePosition, "/cube_state/capture_position", self._on_capture_position
        )
        self.get_cube_state_srv = self.create_service(
            GetCubeState, "/cube_state/get_cube_state", self._on_get_cube_state
        )

        self.get_logger().info(
            "cube_state_node ready. Call /cube_state/capture_position for each "
            f"of {list(self.positions.keys())}, then /cube_state/get_cube_state."
        )

    def _load_colors(self, path):
        with open(path, "r") as f:
            raw = yaml.safe_load(f)["colors"]
        return {label: tuple(hsv) for label, hsv in raw.items()}

    def _load_roi(self, path):
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        positions = {
            position_id: {
                "image_topic": position["image_topic"],
                "faces": list(position["faces"]),
            }
            for position_id, position in raw["positions"].items()
        }
        return positions, raw["detection"]

    def _make_image_callback(self, position_id):
        def callback(msg):
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            self.latest_images[position_id] = image
            if self.publish_debug_image:
                self._publish_debug_image(position_id, image)

        return callback

    def _classify_sticker(self, hsv_image, sticker):
        cx, cy = sticker["center"]
        sample = median_hsv(
            hsv_image, int(round(cx)), int(round(cy)), self.detection_params["sample_patch_radius"]
        )
        return classify_color(sample, self.reference_colors)

    def _publish_debug_image(self, position_id, bgr_image):
        debug_image = bgr_image.copy()
        candidates = find_sticker_candidates(bgr_image, self.detection_params)
        expected_face_count = len(self.positions[position_id]["faces"])
        faces = detect_faces(bgr_image, expected_face_count, self.detection_params)

        detected_centers = set()
        if faces is not None:
            hsv_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
            for face_name, stickers in zip(self.positions[position_id]["faces"], faces):
                for sticker in stickers:
                    cx, cy = (int(round(v)) for v in sticker["center"])
                    detected_centers.add((cx, cy))
                    label = self._classify_sticker(hsv_image, sticker)
                    cv2.drawContours(debug_image, [sticker["contour"]], -1, (0, 255, 0), 2)
                    cv2.putText(
                        debug_image, label, (cx - 8, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
                    )
                mean_x = sum(s["center"][0] for s in stickers) / len(stickers)
                mean_y = sum(s["center"][1] for s in stickers) / len(stickers)
                cv2.putText(
                    debug_image, face_name, (int(mean_x) - 10, int(mean_y) - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2,
                )

        # Candidates that weren't used in a detected face: drawn red, useful
        # for tuning detection.* thresholds in roi.yaml.
        for candidate in candidates:
            cx, cy = (int(round(v)) for v in candidate["center"])
            if (cx, cy) not in detected_centers:
                cv2.drawContours(debug_image, [candidate["contour"]], -1, (0, 0, 255), 1)

        msg = self.bridge.cv2_to_imgmsg(debug_image, encoding="bgr8")
        self.debug_pubs[position_id].publish(msg)

    def _on_capture_position(self, request, response):
        position_id = request.position_id.strip()
        if position_id not in self.positions:
            response.success = False
            response.message = (
                f"Unknown position_id '{request.position_id}'. "
                f"Use one of {list(self.positions.keys())}."
            )
            return response

        image = self.latest_images[position_id]
        if image is None:
            response.success = False
            response.message = f"No camera image received yet for {position_id}."
            return response

        face_names = self.positions[position_id]["faces"]
        faces = detect_faces(image, len(face_names), self.detection_params)
        if faces is None:
            response.success = False
            response.message = (
                f"Could not confidently find {len(face_names)} faces "
                f"(9 stickers each) in {position_id}. Check camera framing/"
                "lighting or tune config/roi.yaml's detection.* parameters "
                "against the debug image."
            )
            return response

        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        captured = {}
        for face_name, stickers in zip(face_names, faces):
            captured[face_name] = [self._classify_sticker(hsv_image, s) for s in stickers]
        self.captured_faces.update(captured)

        response.success = True
        response.message = ", ".join(
            f"{face}: {''.join(labels)}" for face, labels in captured.items()
        )
        self.get_logger().info(f"Captured {position_id} -> {response.message}")
        return response

    def _on_get_cube_state(self, request, response):
        missing = [f for f in FACE_ORDER if f not in self.captured_faces]
        if missing:
            response.complete = False
            response.facelets = ""
            response.missing_faces = ",".join(missing)
            return response

        facelets = "".join(
            "".join(self.captured_faces[face]) for face in FACE_ORDER
        )
        counts = {label: facelets.count(label) for label in set(facelets)}
        bad_counts = {label: n for label, n in counts.items() if n != 9}
        if bad_counts:
            self.get_logger().warn(
                f"Color counts are not 9 each: {bad_counts}. "
                "Check color calibration."
            )

        response.complete = True
        response.facelets = facelets
        response.missing_faces = ""
        return response


def main(args=None):
    rclpy.init(args=args)
    node = CubeStateNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
