#!/usr/bin/env python3
"""Part 1 — Capture GUI.

Live viewfinder from the RealSense camera, an exposure/white-balance lock
(so colors don't drift between the two capture slots), and two named
capture slots — upper_corner and lower_corner — each showing 3 faces of
the cube at an oblique angle; together they cover all 6 faces. Saves each
snap as a lossless PNG.

Run: python3 capture_gui.py [--config config.yaml]
"""

import argparse
import os
import sys
import time

import cv2
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from common.camera import Camera
from common.config import ensure_dataset_dirs, load_config, resolve_paths
from common.dataset import make_capture_name, save_capture_png


def _bgr_to_pixmap(image_bgr, max_width=640):
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(qimage)
    if width > max_width:
        pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
    return pixmap


class SlotPanel(QGroupBox):
    def __init__(self, slot_name, on_snap, on_retake):
        super().__init__(slot_name)
        self.slot_name = slot_name
        self.captured_path = None

        self.thumbnail = QLabel("(not captured)")
        self.thumbnail.setFixedSize(320, 240)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background-color: #222; color: #888;")

        self.status_label = QLabel("Not captured")
        self.snap_button = QPushButton("Snap")
        self.retake_button = QPushButton("Retake")
        self.retake_button.setEnabled(False)

        self.snap_button.clicked.connect(lambda: on_snap(self))
        self.retake_button.clicked.connect(lambda: on_retake(self))

        layout = QVBoxLayout()
        layout.addWidget(self.thumbnail)
        layout.addWidget(self.status_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.snap_button)
        buttons.addWidget(self.retake_button)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def mark_captured(self, path, pixmap):
        self.captured_path = path
        self.thumbnail.setPixmap(pixmap)
        self.status_label.setText(f"Captured: {os.path.basename(path)}")
        self.snap_button.setEnabled(False)
        self.retake_button.setEnabled(True)

    def mark_uncaptured(self):
        self.captured_path = None
        self.thumbnail.clear()
        self.thumbnail.setText("(not captured)")
        self.status_label.setText("Not captured")
        self.snap_button.setEnabled(True)
        self.retake_button.setEnabled(False)


class CapturePanel(QWidget):
    """The capture step's UI and camera lifecycle, as a plain QWidget so it
    can be embedded as one step of a larger multi-step window (see
    hmi_app.py) instead of only ever running as its own top-level window."""

    state_changed = pyqtSignal()

    def __init__(self, config, paths):
        super().__init__()
        self.config = config
        self.paths = paths

        capture_cfg = config["capture"]
        self.camera = Camera(capture_cfg["width"], capture_cfg["height"], capture_cfg["fps"])
        self.latest_bgr = None

        self.viewfinder = QLabel("Starting camera...")
        self.viewfinder.setFixedSize(640, 480)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        self.viewfinder.setStyleSheet("background-color: #000; color: #888;")

        self.lock_button = QPushButton("Lock Exposure/WB")
        self.lock_button.clicked.connect(self._toggle_lock)
        self.lock_status = QLabel("Auto exposure/WB (unlocked)")

        self.lighting_tag_input = QLineEdit()
        self.lighting_tag_input.setPlaceholderText(
            "lighting tag, e.g. workshop_overhead_led_night"
        )

        self.slots = {}
        slots_layout = QHBoxLayout()
        for slot_name in capture_cfg["slots"]:
            panel = SlotPanel(slot_name, self._on_snap, self._on_retake)
            self.slots[slot_name] = panel
            slots_layout.addWidget(panel)

        top_controls = QHBoxLayout()
        top_controls.addWidget(self.lock_button)
        top_controls.addWidget(self.lock_status)

        lighting_row = QHBoxLayout()
        lighting_row.addWidget(QLabel("Lighting tag:"))
        lighting_row.addWidget(self.lighting_tag_input)

        layout = QVBoxLayout()
        layout.addWidget(self.viewfinder, alignment=Qt.AlignCenter)
        layout.addLayout(top_controls)
        layout.addLayout(lighting_row)
        layout.addLayout(slots_layout)
        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self._on_frame_tick)
        self.timer.start(30)

    def _on_frame_tick(self):
        frame = self.camera.latest_frame()
        if frame is None:
            return
        self.latest_bgr = frame
        self.viewfinder.setPixmap(_bgr_to_pixmap(frame, max_width=640))

    def _toggle_lock(self):
        if self.camera.locked:
            self.camera.unlock_exposure_and_white_balance()
            self.lock_button.setText("Lock Exposure/WB")
            self.lock_status.setText("Auto exposure/WB (unlocked)")
        else:
            exposure, white_balance = self.camera.lock_exposure_and_white_balance()
            self.lock_button.setText("Unlock Exposure/WB")
            self.lock_status.setText(
                f"Locked (exposure={exposure:.0f}, white_balance={white_balance:.0f})"
            )

    def _on_snap(self, panel):
        if self.latest_bgr is None:
            QMessageBox.warning(self, "No frame", "No camera frame available yet.")
            return
        if not self.camera.locked:
            reply = QMessageBox.question(
                self, "Exposure/WB not locked",
                "Exposure/white-balance isn't locked. Colors may shift between "
                "captures. Snap anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        timestamp = time.time()
        name = make_capture_name(panel.slot_name, timestamp)
        path = save_capture_png(self.latest_bgr, name, self.paths["captures_dir"])
        panel.mark_captured(path, _bgr_to_pixmap(self.latest_bgr, max_width=320))
        panel.capture_meta = {
            "name": name,
            "timestamp": timestamp,
            "lighting_tag": self.lighting_tag_input.text().strip(),
        }
        self.state_changed.emit()

    def _on_retake(self, panel):
        panel.mark_uncaptured()
        panel.capture_meta = None
        self.state_changed.emit()

    def all_captured(self):
        return all(panel.captured_path is not None for panel in self.slots.values())

    def captures(self):
        """{slot_name: {"path": ..., **capture_meta}} for every captured slot."""
        return {
            slot_name: {"path": panel.captured_path, **(panel.capture_meta or {})}
            for slot_name, panel in self.slots.items()
            if panel.captured_path is not None
        }

    def shutdown(self):
        self.timer.stop()
        self.camera.stop()


class CaptureWindow(QMainWindow):
    """Standalone top-level window wrapping CapturePanel, for running this
    step on its own (python3 capture_gui.py) rather than embedded in the
    combined HMI."""

    def __init__(self, config, paths):
        super().__init__()
        self.setWindowTitle("Cube Capture")
        self.panel = CapturePanel(config, paths)
        self.setCentralWidget(self.panel)

    def closeEvent(self, event):
        self.panel.shutdown()
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
    window = CaptureWindow(config, paths)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
