#!/usr/bin/env python3
"""Combined HMI — one persistent window covering the whole cube workflow:
capture -> label upper_corner -> label lower_corner -> compare -> solve &
execute, plus manual per-face jog and a scramble button.

Replaces the old flow of separate GUI processes chained by
`ros2 launch cube_solver cube_pipeline.launch.py`, where each step's window
had to be closed to launch the next one. Here every step is a page of one
QStackedWidget in one QApplication, so nothing closes until the whole
session is done.

Needs BOTH the cube_vision_tool environment (PyQt5, opencv, pyrealsense2)
and a sourced ROS 2 workspace (rclpy, cube_solver_interfaces,
cube_motor_control) importable from the same interpreter. Run as:

    source ros2_ws/install/setup.bash
    python3 cube_vision_tool/hmi_app.py [--config config.yaml]
"""

import argparse
import os
import sys
import threading

from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from capture_gui import CapturePanel
from common.config import ensure_dataset_dirs, load_config, resolve_paths
from compare_state_gui import _draw_labels_on_photo, _hstack_padded, _isometric_corner
from label_gui import LabelPanel

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from cube_motor_control.scramble_cube import generate_scramble
from cube_solver_interfaces.action import ExecuteSolve
from cube_solver_interfaces.srv import SolveCube
from std_srvs.srv import Trigger

FACES = ["U", "R", "F", "D", "L", "B"]
SUFFIXES = ("", "'", "2")


def _bgr_to_pixmap(image_bgr):
    import cv2

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888)
    return QPixmap.fromImage(qimage)


class RosBridge(QObject):
    """Owns the rclpy node and spins it on a background thread so the Qt
    event loop never blocks on a service/action call. All results come back
    through Qt signals, which PyQt marshals safely onto the GUI thread even
    though they're emitted from the executor thread."""

    execute_feedback = pyqtSignal(int, str)
    execute_done = pyqtSignal(bool, str, int)
    solve_done = pyqtSignal(bool, str, list)
    clear_pending_done = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        rclpy.init(args=None)
        self.node = Node("cube_hmi")
        self._solve_cube_client = self.node.create_client(SolveCube, "/cube_solver/solve_cube")
        self._solve_execute_client = self.node.create_client(
            SolveCube, "/cube_solver/solve_and_execute"
        )
        self._execute_client = ActionClient(
            self.node, ExecuteSolve, "/cube_motor_control/execute_solve"
        )
        self._clear_pending_client = self.node.create_client(
            Trigger, "/cube_motor_control/clear_pending_solve"
        )
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self.node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def shutdown(self):
        self._executor.shutdown()
        self.node.destroy_node()
        rclpy.shutdown()

    def solve(self, execute, facelets="", algorithm=""):
        client = self._solve_execute_client if execute else self._solve_cube_client
        if not client.wait_for_service(timeout_sec=5.0):
            self.solve_done.emit(False, f"{client.srv_name} not available", [])
            return
        request = SolveCube.Request()
        request.facelets = facelets
        request.algorithm = algorithm
        future = client.call_async(request)
        future.add_done_callback(
            lambda f: self.solve_done.emit(
                f.result().success, f.result().message, list(f.result().moves)
            )
        )

    def clear_pending(self):
        if not self._clear_pending_client.wait_for_service(timeout_sec=5.0):
            self.clear_pending_done.emit(False, "clear_pending_solve service not available")
            return
        future = self._clear_pending_client.call_async(Trigger.Request())
        future.add_done_callback(
            lambda f: self.clear_pending_done.emit(f.result().success, f.result().message)
        )

    def send_moves(self, moves):
        if not self._execute_client.wait_for_server(timeout_sec=5.0):
            self.execute_done.emit(False, "execute_solve action server not available", 0)
            return

        goal = ExecuteSolve.Goal()
        goal.moves = moves

        def feedback_cb(feedback_msg):
            self.execute_feedback.emit(
                feedback_msg.feedback.move_index, feedback_msg.feedback.move
            )

        def goal_response_cb(future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self.execute_done.emit(False, "goal rejected", 0)
                return
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda f: self.execute_done.emit(
                    f.result().result.success,
                    f.result().result.message,
                    f.result().result.moves_completed,
                )
            )

        send_future = self._execute_client.send_goal_async(goal, feedback_callback=feedback_cb)
        send_future.add_done_callback(goal_response_cb)


class LabelStepPage(QWidget):
    """A LabelPanel plus a Continue button that only unlocks once the panel
    has emitted `saved`."""

    continued = pyqtSignal(dict, str)  # (record, sidecar_path)

    def __init__(self, config, paths, image_path, slot, continue_text, existing_record=None):
        super().__init__()
        self.panel = LabelPanel(config, paths, image_path, slot, existing_record)
        self._record = None
        self._sidecar_path = None

        self.continue_button = QPushButton(continue_text)
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(
            lambda: self.continued.emit(self._record, self._sidecar_path)
        )

        layout = QVBoxLayout()
        layout.addWidget(self.panel)
        layout.addWidget(self.continue_button)
        self.setLayout(layout)

        self.panel.saved.connect(self._on_saved)

    def _on_saved(self, record, sidecar_path):
        self._record = record
        self._sidecar_path = sidecar_path
        self.continue_button.setEnabled(True)


class ComparePage(QWidget):
    """Shows the labeled photo + isometric render for each slot side by
    side, with a "Fix" button per slot that sends the user back to that
    slot's LabelStepPage (pre-loaded from the same captured image) to
    correct any wrong labels, then rebuilds this page from the corrected
    record."""

    def __init__(self, upper_record, lower_record, on_continue, on_edit_upper, on_edit_lower):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Sanity-check every face before solving:"))

        records = (("upper_corner", upper_record, on_edit_upper), ("lower_corner", lower_record, on_edit_lower))
        for slot, record, on_edit in records:
            photo_panel = _draw_labels_on_photo(record)
            render_panel = _isometric_corner(record)
            combined = _hstack_padded([photo_panel, render_panel])
            image_label = QLabel()
            image_label.setPixmap(_bgr_to_pixmap(combined))
            layout.addWidget(image_label, alignment=Qt.AlignCenter)

            fix_button = QPushButton(f"Fix {slot} labels")
            fix_button.clicked.connect(on_edit)
            layout.addWidget(fix_button, alignment=Qt.AlignCenter)

        continue_button = QPushButton("Continue to Solve && Execute")
        continue_button.clicked.connect(on_continue)
        layout.addWidget(continue_button)
        self.setLayout(layout)


class SolvePage(QWidget):
    def __init__(self, ros_bridge):
        super().__init__()
        self.ros_bridge = ros_bridge

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        solve_row = QHBoxLayout()
        solve_only_button = QPushButton("Solve Only")
        solve_only_button.clicked.connect(lambda: self._solve(execute=False))
        solve_execute_button = QPushButton("Solve && Execute")
        solve_execute_button.clicked.connect(lambda: self._solve(execute=True))
        clear_pending_button = QPushButton("Clear Pending Solve")
        clear_pending_button.clicked.connect(self._clear_pending)
        solve_row.addWidget(solve_only_button)
        solve_row.addWidget(solve_execute_button)
        solve_row.addWidget(clear_pending_button)

        jog_box = QGroupBox("Manual jog")
        jog_grid = QGridLayout()
        for row, face in enumerate(FACES):
            for col, suffix in enumerate(SUFFIXES):
                move = face + suffix
                button = QPushButton(move)
                button.clicked.connect(lambda _, m=move: self._jog(m))
                jog_grid.addWidget(button, row, col)
        jog_box.setLayout(jog_grid)

        scramble_button = QPushButton("Scramble (20 moves)")
        scramble_button.clicked.connect(self._scramble)

        layout = QVBoxLayout()
        layout.addLayout(solve_row)
        layout.addWidget(jog_box)
        layout.addWidget(scramble_button)
        layout.addWidget(self.log)
        self.setLayout(layout)

        ros_bridge.solve_done.connect(self._on_solve_done)
        ros_bridge.execute_done.connect(self._on_execute_done)
        ros_bridge.execute_feedback.connect(self._on_execute_feedback)
        ros_bridge.clear_pending_done.connect(self._on_clear_pending_done)

    def _append(self, text):
        self.log.append(text)

    def _solve(self, execute):
        self._append(f"Requesting {'solve + execute' if execute else 'solve only'}...")
        self.ros_bridge.solve(execute)

    def _clear_pending(self):
        self._append("Clearing pending solve...")
        self.ros_bridge.clear_pending()

    def _jog(self, move):
        self._append(f"Jog: {move}")
        self.ros_bridge.send_moves([move])

    def _scramble(self):
        moves = generate_scramble(20)
        self._append(f"Scrambling: {' '.join(moves)}")
        self.ros_bridge.send_moves(moves)

    def _on_solve_done(self, success, message, moves):
        if success:
            self._append(f"Solve result: {message} -> {' '.join(moves)}")
        else:
            self._append(f"Solve FAILED: {message}")

    def _on_execute_done(self, success, message, moves_completed):
        status = "OK" if success else "FAILED"
        self._append(f"Execute {status}: {message} ({moves_completed} moves completed)")

    def _on_execute_feedback(self, move_index, move):
        self._append(f"  move {move_index}: {move}")

    def _on_clear_pending_done(self, success, message):
        self._append(f"Clear pending: {'OK' if success else 'FAILED'} — {message}")


class CubeHMI(QMainWindow):
    def __init__(self, config, paths, ros_bridge):
        super().__init__()
        self.setWindowTitle("Cube HMI")
        self.config = config
        self.paths = paths
        self.ros_bridge = ros_bridge

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.capture_panel = CapturePanel(config, paths)
        self.capture_page = QWidget()
        capture_layout = QVBoxLayout()
        capture_layout.addWidget(self.capture_panel)
        self.capture_continue_button = QPushButton("Continue to Labeling")
        self.capture_continue_button.setEnabled(False)
        self.capture_continue_button.clicked.connect(self._go_to_label_upper)
        capture_layout.addWidget(self.capture_continue_button)
        self.capture_page.setLayout(capture_layout)
        self.capture_panel.state_changed.connect(self._refresh_capture_continue)

        self.stack.addWidget(self.capture_page)
        self.stack.setCurrentWidget(self.capture_page)

    def _refresh_capture_continue(self):
        self.capture_continue_button.setEnabled(self.capture_panel.all_captured())

    def _go_to_label_upper(self):
        path = self.capture_panel.captures()["upper_corner"]["path"]
        page = LabelStepPage(
            self.config, self.paths, path, "upper_corner", "Continue to Labeling (lower)"
        )
        page.continued.connect(self._go_to_label_lower)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        page.panel.setFocus()

    def _go_to_label_lower(self, upper_record, upper_sidecar_path):
        self._upper_record = upper_record
        path = self.capture_panel.captures()["lower_corner"]["path"]
        page = LabelStepPage(
            self.config, self.paths, path, "lower_corner", "Continue to Compare"
        )
        page.continued.connect(self._go_to_compare)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        page.panel.setFocus()

    def _go_to_compare(self, lower_record, lower_sidecar_path):
        self._lower_record = lower_record
        self._show_compare()

    def _show_compare(self):
        page = ComparePage(
            self._upper_record,
            self._lower_record,
            self._go_to_solve,
            lambda: self._edit_slot("upper_corner"),
            lambda: self._edit_slot("lower_corner"),
        )
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _edit_slot(self, slot):
        path = self.capture_panel.captures()[slot]["path"]
        existing_record = self._upper_record if slot == "upper_corner" else self._lower_record
        page = LabelStepPage(
            self.config, self.paths, path, slot, "Save Changes", existing_record
        )
        page.continued.connect(lambda record, sidecar_path: self._apply_edit(slot, record))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        page.panel.setFocus()

    def _apply_edit(self, slot, record):
        if slot == "upper_corner":
            self._upper_record = record
        else:
            self._lower_record = record
        self._show_compare()

    def _go_to_solve(self):
        page = SolvePage(self.ros_bridge)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def closeEvent(self, event):
        self.capture_panel.shutdown()
        self.ros_bridge.shutdown()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)
    ensure_dataset_dirs(paths)

    app = QApplication(sys.argv)
    ros_bridge = RosBridge()
    window = CubeHMI(config, paths, ros_bridge)
    window.resize(1000, 800)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
