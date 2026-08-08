"""ROS 2 node that reads a Rubik's Cube one whole face at a time.

The cube body never moves in this rig — only individual faces spin, each on
its own motor. So no single fixed camera view sees more than half the
cube. Rather than trying to see multiple faces at once from fixed
positions, this node captures one face at a time, straight-on: reposition
a camera (or the cube) so exactly one face fills the frame, call
`capture_position` with that face's letter, then move to the next face.

The cube is stickerless, so there's no dark sticker border between cubies
to detect — just a thin, low-contrast painted seam. Rather than trying to
find each of the 9 individual cubie squares, this node finds the *outer*
boundary of the whole face (a strong, high-contrast edge against the
background, see sticker_detect.py's `find_face_quad`), perspective-corrects
it, and divides it into a 3x3 grid geometrically — no dependency on
detecting the faint internal seams at all.

The center cell is never sampled from the image: a motor's drive shaft
passes through the center of whatever face it turns, permanently occluding
it from every camera angle. That's fine — center color is a fixed rig fact
(config/motor_faces.yaml), not something vision needs to read.

Workflow:
  1. Frame one face straight-on, call `capture_position` with its letter
     (U/R/F/D/L/B, per config/roi.yaml's `positions`).
  2. Repeat for all 6 faces.
  3. Call `get_cube_state` to get the full 54-character result.

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
from cube_state_detector.sticker_detect import find_face_quad, sample_face_grid

FACE_ORDER = ["U", "R", "F", "D", "L", "B"]
CENTER_SLOT = 4  # row-major index of the 3x3 grid's center cell


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
        self.declare_parameter(
            "motor_faces_yaml", os.path.join(default_config_dir, "motor_faces.yaml")
        )
        self.declare_parameter("publish_debug_image", True)

        self.reference_colors = self._load_colors(
            self.get_parameter("colors_yaml").value
        )
        self.positions, self.detection_params = self._load_roi(
            self.get_parameter("roi_yaml").value
        )
        self.center_colors = self._load_motor_faces(
            self.get_parameter("motor_faces_yaml").value
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
            face_id: {"image_topic": position["image_topic"]}
            for face_id, position in raw["positions"].items()
        }
        return positions, raw["detection"]

    def _load_motor_faces(self, path):
        """Map face letter (U/R/F/D/L/B) -> its fixed center sticker color.

        The center is never optically detected (a motor's drive shaft
        permanently occludes it) so this is the only source of truth for it.
        """
        with open(path, "r") as f:
            raw = yaml.safe_load(f)["motors"]
        return {motor["face"]: motor["color"] for motor in raw.values()}

    def _make_image_callback(self, position_id):
        def callback(msg):
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            self.latest_images[position_id] = image
            if self.publish_debug_image:
                self._publish_debug_image(position_id, image)

        return callback

    def _classify_cell(self, hsv_image, cx, cy):
        sample = median_hsv(
            hsv_image, int(round(cx)), int(round(cy)),
            self.detection_params["sample_patch_radius"],
        )
        return classify_color(sample, self.reference_colors)

    def _read_face_labels(self, face_id, bgr_image, quad):
        """Perspective-correct `quad` and classify all 9 grid cells, with
        the center cell filled from config/motor_faces.yaml instead of
        sampled (it's always occluded by the drive shaft)."""
        warped, cells = sample_face_grid(bgr_image, quad, self.detection_params)
        hsv_warped = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
        labels = []
        for idx, cell in enumerate(cells):
            if idx == CENTER_SLOT:
                labels.append(self.center_colors[face_id])
                continue
            cx, cy = cell["center"]
            labels.append(self._classify_cell(hsv_warped, cx, cy))
        return labels, warped, cells

    def _publish_debug_image(self, face_id, bgr_image):
        quad = find_face_quad(bgr_image, self.detection_params)
        if quad is None:
            # Nothing plausible found — publish the raw frame so it's still
            # possible to see what the camera sees while repositioning.
            msg = self.bridge.cv2_to_imgmsg(bgr_image, encoding="bgr8")
            self.debug_pubs[face_id].publish(msg)
            return

        labels, warped, cells = self._read_face_labels(face_id, bgr_image, quad)
        debug_image = warped.copy()
        warp_size = self.detection_params["warp_size"]
        cell_size = warp_size / 3.0
        for i in (1, 2):
            offset = int(i * cell_size)
            cv2.line(debug_image, (0, offset), (warp_size, offset), (0, 255, 0), 1)
            cv2.line(debug_image, (offset, 0), (offset, warp_size), (0, 255, 0), 1)

        for idx, (label, cell) in enumerate(zip(labels, cells)):
            cx, cy = (int(round(v)) for v in cell["center"])
            color = (255, 0, 255) if idx == CENTER_SLOT else (255, 255, 255)
            text = f"({label})" if idx == CENTER_SLOT else label
            cv2.putText(
                debug_image, text, (cx - 15, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
            )

        msg = self.bridge.cv2_to_imgmsg(debug_image, encoding="bgr8")
        self.debug_pubs[face_id].publish(msg)

    def _on_capture_position(self, request, response):
        face_id = request.position_id.strip()
        if face_id not in self.positions:
            response.success = False
            response.message = (
                f"Unknown position_id '{request.position_id}'. "
                f"Use one of {list(self.positions.keys())}."
            )
            return response

        image = self.latest_images[face_id]
        if image is None:
            response.success = False
            response.message = f"No camera image received yet for {face_id}."
            return response

        quad = find_face_quad(image, self.detection_params)
        if quad is None:
            response.success = False
            response.message = (
                f"Could not confidently find the cube face square for "
                f"{face_id}. Make sure the whole face fills the frame and "
                "is roughly straight-on to the camera; check config/"
                "roi.yaml's detection.* parameters against the debug image."
            )
            return response

        labels, _, _ = self._read_face_labels(face_id, image, quad)
        self.captured_faces[face_id] = labels

        response.success = True
        response.message = f"{face_id}: {''.join(labels)}"
        self.get_logger().info(f"Captured {face_id} -> {response.message}")
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
