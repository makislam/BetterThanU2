#!/usr/bin/env python3
"""Part 2 — Labeling GUI.

Open a captured PNG, declare which 3 faces are visible (U/F/R/D/B/L),
click each face's 4 corners in the order the on-screen hint asks for
(that is the face's CANONICAL row/col order, which on an oblique corner
shot is not the same as screen order - see _CLICK_HINTS), confirm the bilinear-interpolated 3x3 grid overlay, then
label each cell's color with a keypress (or mark it occluded). Saves the
full record via common/dataset.py.

Run: python3 label_gui.py <image.png> [--slot upper_corner] [--config config.yaml]
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from common.config import ensure_dataset_dirs, load_config, resolve_paths
from common.dataset import save_label_record
from common.geometry import face_grid

FACE_LETTERS = ["U", "R", "F", "D", "L", "B"]

# The rig is fixed - each capture slot always frames the same 3 faces in the
# same arrangement (upper_corner: yellow/U on top, red/F, green/R; lower_corner:
# white/D on the bottom, orange/B, blue/L). This used to be a per-capture
# manual dropdown pick, which is exactly what let U/F/R swap or mirror
# between sessions - now it's a fixed fact of the rig, not a per-session guess.
SLOT_FACE_ORDER = {
    "upper_corner": ["U", "F", "R"],
    "lower_corner": ["D", "B", "L"],
}

# Which physical cubie corner each of the 4 clicks must land on, per slot and
# per face role, in the order face_grid() expects: (0,0), (0,2), (2,2), (2,0)
# of the CANONICAL face (looking straight at that face with U up and F toward
# you - the URFDLB row/col convention cube_topology.py indexes with).
#
# This is the whole point of the table: on an oblique 3-face corner shot, the
# canonical top-left of a face is NOT the top-left thing you see on screen.
# For the up-facing diamond in particular, what looks like the near/front
# point of the diamond is the canonical BOTTOM-RIGHT cell, so clicking
# "screen top-left first" files every sticker 180 degrees out of place - which
# the solver then rejects as an impossible cube even though the photo and the
# color keypresses were both fine.
#
# Derivation (upper_corner: U diamond up, F left wall, R right wall):
#   U canonical (0,0)=ULB (0,2)=UBR (2,2)=URF (2,0)=UFL
#     -> on screen: far point, right point, near point, left point
#   F canonical (0,0)=UFL (0,2)=URF (2,2)=DFR (2,0)=DLF  -> screen TL,TR,BR,BL
#   R canonical (0,0)=URF (0,2)=UBR (2,2)=DRB (2,0)=DFR  -> screen TL,TR,BR,BL
# (side walls happen to match the screen; only the diamond is rotated.)
#
# Derivation (lower_corner: D diamond DOWN at the bottom of frame, B left
# wall, L right wall, both walls rising ABOVE the diamond):
#   D canonical (0,0)=DLF (0,2)=DFR (2,2)=DRB (2,0)=DBL
#     -> on screen: right point, far point, left point, near point
#   B canonical (0,0)=UBR (0,2)=ULB (2,2)=DBL (2,0)=DRB
#   L canonical (0,0)=ULB (0,2)=UFL (2,2)=DLF (2,0)=DBL
# so here the diamond is rotated the *other* way (it is the face's own row-0
# edge, not the camera, that flips), and the two walls share their inner
# vertical edge: B's click 2 == L's click 1, and B's click 3 == L's click 4.
_CLICK_HINTS = {
    "upper_corner": {
        "U": [
            "BACK point of the yellow diamond - farthest from the camera, "
            "shared with neither {left} nor {right}",
            "RIGHT point of the yellow diamond - far end of the edge shared with {right}",
            "NEAR/FRONT point of the yellow diamond - the corner shared by {left} and {right}",
            "LEFT point of the yellow diamond - far end of the edge shared with {left}",
        ],
        "F": [
            "top-LEFT - the outer top corner of this face, same point as the "
            "LEFT point of the {top} diamond",
            "top-RIGHT - the near/front vertical edge, same point as the NEAR "
            "point of the {top} diamond (shared with {right})",
            "bottom-RIGHT - straight down from click 2, at the bottom of that "
            "shared front edge",
            "bottom-LEFT - straight down from click 1",
        ],
        "R": [
            "top-LEFT - the near/front vertical edge, same point as the NEAR "
            "point of the {top} diamond (shared with {left}, and the same "
            "physical point as {left}'s click 2)",
            "top-RIGHT - the outer top corner, same point as the RIGHT point "
            "of the {top} diamond",
            "bottom-RIGHT - straight down from click 2",
            "bottom-LEFT - straight down from click 1, at the bottom of the "
            "shared front edge",
        ],
    },
    "lower_corner": {
        "D": [
            "RIGHT point of the white diamond - far end of the edge shared with {right}",
            "BACK point of the white diamond - farthest from the camera, "
            "shared with neither {left} nor {right}",
            "LEFT point of the white diamond - far end of the edge shared with {left}",
            "NEAR/FRONT point of the white diamond - the corner shared by "
            "{left} and {right} (the lowest point in frame)",
        ],
        "B": [
            "TOP-OUTER corner of this face - straight UP from the LEFT point "
            "of the {top} diamond (this wall rises above the diamond)",
            "TOP-INNER corner - straight UP from the NEAR point of the {top} "
            "diamond, top of the vertical edge shared with {right}",
            "BOTTOM-INNER - the NEAR/FRONT point of the {top} diamond itself",
            "BOTTOM-OUTER - the LEFT point of the {top} diamond itself",
        ],
        "L": [
            "TOP-INNER corner - straight UP from the NEAR point of the {top} "
            "diamond, top of the vertical edge shared with {left} (same "
            "physical point as {left}'s click 2)",
            "TOP-OUTER corner - straight UP from the RIGHT point of the {top} "
            "diamond",
            "BOTTOM-OUTER - the RIGHT point of the {top} diamond itself",
            "BOTTOM-INNER - the NEAR/FRONT point of the {top} diamond itself "
            "(same physical point as {left}'s click 3)",
        ],
    },
}


class ImageCanvas(QLabel):
    """Displays the capture image scaled to fit, translates clicks back to
    original-image pixel coordinates, and draws quad/grid/label overlays.
    """

    def __init__(self, image_bgr, on_click, max_width=900):
        super().__init__()
        self.image_bgr = image_bgr
        self.on_click = on_click
        height, width = image_bgr.shape[:2]
        self.scale = min(1.0, max_width / width)
        self.display_size = (int(width * self.scale), int(height * self.scale))
        self.setFixedSize(*self.display_size)
        self.setMouseTracking(True)
        self.base_pixmap = self._make_base_pixmap()
        self.setPixmap(self.base_pixmap)

    def _make_base_pixmap(self):
        rgb = cv2.cvtColor(self.image_bgr, cv2.COLOR_BGR2RGB)
        height, width, _ = rgb.shape
        qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)
        return pixmap.scaled(*self.display_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def mousePressEvent(self, event):
        x_img = event.pos().x() / self.scale
        y_img = event.pos().y() / self.scale
        self.on_click(x_img, y_img)

    def redraw(self, faces, pending_points, selected=None, palette=None):
        pixmap = self.base_pixmap.copy()
        painter = QPainter(pixmap)

        for point in pending_points:
            self._draw_point(painter, point, QColor(255, 255, 0))

        for face_idx, face in enumerate(faces):
            if face["quad"] is None:
                continue
            self._draw_quad(painter, face["quad"], QColor(255, 255, 0))
            if face["cells"] is None:
                continue
            for cell_idx, cell in enumerate(face["cells"]):
                is_selected = selected == (face_idx, cell_idx)
                self._draw_cell(painter, cell, is_selected, palette)

        painter.end()
        self.setPixmap(pixmap)

    def _to_display(self, point):
        return point[0] * self.scale, point[1] * self.scale

    def _draw_point(self, painter, point, color):
        x, y = self._to_display(point)
        painter.setPen(QPen(color, 2))
        painter.setBrush(color)
        painter.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)

    def _draw_quad(self, painter, quad, color):
        painter.setPen(QPen(color, 2))
        pts = [self._to_display(p) for p in quad]
        for i in range(4):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 4]
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_cell(self, painter, cell, is_selected, palette):
        pts = [self._to_display(p) for p in cell["polygon"]]
        pen_color = QColor(255, 0, 255) if is_selected else QColor(0, 255, 0)
        painter.setPen(QPen(pen_color, 2 if is_selected else 1))
        for i in range(4):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 4]
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        cx, cy = self._to_display(cell["center"])
        label = cell.get("label")
        if label:
            swatch_color = QColor(120, 120, 120)
            if palette and label in palette:
                rgb = palette[label]["rgb"]
                swatch_color = QColor(*rgb)
            painter.setBrush(swatch_color)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(int(cx) - 10, int(cy) - 10, 20, 20)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawText(int(cx) - 5, int(cy) + 5, label)


class LabelWindow(QMainWindow):
    def __init__(self, config, paths, image_path, slot):
        super().__init__()
        self.config = config
        self.paths = paths
        self.image_path = image_path
        self.slot = slot
        self.palette = config["palette"]
        self.key_to_label = {k: v["label"] for k, v in self.palette.items()}
        self.undo_key = config["key_bindings"]["undo"]

        self.image_bgr = cv2.imread(image_path)
        if self.image_bgr is None:
            raise FileNotFoundError(f"Could not read image: {image_path}")

        self.faces = [{"face": None, "quad": None, "cells": None} for _ in range(3)]
        self.current_face_idx = 0
        self.pending_points = []
        self.selected = None  # (face_idx, cell_idx)
        self.history = []  # stack of (face_idx, cell_idx) for undo

        self.setWindowTitle(f"Label — {os.path.basename(image_path)}")
        self._build_ui()

    def _build_ui(self):
        self.canvas = ImageCanvas(self.image_bgr, self._on_canvas_click)

        fixed_order = SLOT_FACE_ORDER.get(self.slot)

        self.face_selectors = []
        face_row = QHBoxLayout()
        for i in range(3):
            box = QComboBox()
            box.addItem("(select face)")
            box.addItems(FACE_LETTERS)
            box.currentIndexChanged.connect(lambda _, idx=i: self._on_face_selected(idx))
            self.face_selectors.append(box)
            face_row.addWidget(QLabel(f"Face {i + 1}:"))
            face_row.addWidget(box)

        self.instructions = QLabel()

        if fixed_order:
            # Rig fact, not a per-session choice - lock it in and don't make
            # the user (mis-)pick it every time. Deferred until after
            # self.instructions exists, since setCurrentText fires
            # _on_face_selected -> _update_instructions synchronously.
            for i, box in enumerate(self.face_selectors):
                box.setCurrentText(fixed_order[i])
                box.setEnabled(False)
        else:
            self._update_instructions()

        self.lighting_tag_input = QLineEdit()
        self.lighting_tag_input.setPlaceholderText("lighting tag (carried over from capture if known)")

        legend = QLabel(
            "Keys: " + ", ".join(f"{k}={v['label']}" for k, v in self.palette.items())
            + f"  |  undo={self.undo_key}"
        )

        self.color_combo = QComboBox()
        self.color_combo.addItem("(pick a color for the selected cell)")
        for label in self.key_to_label.values():
            self.color_combo.addItem(label)
        self.color_combo.currentIndexChanged.connect(self._on_color_combo_chosen)

        self.undo_button = QPushButton("Undo last label")
        self.undo_button.clicked.connect(self._undo)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Cell color:"))
        color_row.addWidget(self.color_combo)
        color_row.addWidget(self.undo_button)

        self.save_button = QPushButton("Save")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)

        central = QWidget()
        layout = QVBoxLayout()
        layout.addLayout(face_row)
        layout.addWidget(self.instructions)
        layout.addWidget(self.canvas, alignment=Qt.AlignCenter)
        layout.addLayout(color_row)
        layout.addWidget(legend)
        layout.addWidget(self.lighting_tag_input)
        layout.addWidget(self.save_button)
        central.setLayout(layout)
        self.setCentralWidget(central)

    def _corner_hint(self, face_letter, corner_idx):
        """Generic top-left/top-right/bottom-right/bottom-left instructions
        are exactly what let U/F/R (and D/B/L) get mirrored or transposed
        between sessions - "top-left" is genuinely ambiguous on an oblique
        3-face corner shot. Since the rig is fixed, every face's role (the
        "up-facing" diamond, or the left/right wall hanging off it) and its
        neighbors are known in advance - so corners can be described by what
        they're physically shared with instead.

        The click order is NOT screen order: it is the canonical row/col order
        of that face (see _CLICK_HINTS), which for the diamond face is a
        rotation of what the screen suggests. Getting this wrong is what
        misassigns every sticker's position.
        """
        order = SLOT_FACE_ORDER.get(self.slot)
        slot_hints = _CLICK_HINTS.get(self.slot, {})
        if not order or face_letter not in slot_hints:
            return ["top-left", "top-right", "bottom-right", "bottom-left"][corner_idx]

        top, left, right = order
        return slot_hints[face_letter][corner_idx].format(top=top, left=left, right=right)

    def _update_instructions(self):
        face = self.faces[self.current_face_idx]
        if face["face"] is None:
            self.instructions.setText(
                f"Select the letter for Face {self.current_face_idx + 1} above."
            )
        elif face["quad"] is None:
            n = len(self.pending_points)
            self.instructions.setText(
                f"Face {face['face']}: click corner {n + 1}/4 ({self._corner_hint(face['face'], n)})."
            )
        elif face["cells"] is None:
            self.instructions.setText("(computing grid...)")
        else:
            labeled = sum(1 for c in face["cells"] if c.get("label"))
            self.instructions.setText(
                f"Face {face['face']}: click a cell, then press a color key. "
                f"({labeled}/9 labeled)"
            )

    def _on_face_selected(self, face_idx):
        letter = self.face_selectors[face_idx].currentText()
        if letter not in FACE_LETTERS:
            return
        chosen = [self.face_selectors[i].currentText() for i in range(3)]
        if chosen.count(letter) > 1:
            QMessageBox.warning(self, "Duplicate face", f"Face {letter} already assigned.")
            self.face_selectors[face_idx].setCurrentIndex(0)
            return
        self.faces[face_idx]["face"] = letter
        self._update_instructions()

    def _on_canvas_click(self, x, y):
        face = self.faces[self.current_face_idx]
        if face["face"] is None:
            return

        if face["quad"] is None:
            self.pending_points.append((x, y))
            if len(self.pending_points) == 4:
                face["quad"] = list(self.pending_points)
                face["cells"] = face_grid(face["quad"], grid_size=3)
                for cell in face["cells"]:
                    cell["label"] = None
                    cell["occluded"] = False
                self.pending_points = []
                self.selected = None
            self._update_instructions()
            self._redraw()
            return

        # Labeling mode: find which cell polygon contains the click.
        for cell_idx, cell in enumerate(face["cells"]):
            polygon = np.array(cell["polygon"], dtype=np.float32)
            if cv2.pointPolygonTest(polygon, (x, y), False) >= 0:
                self.selected = (self.current_face_idx, cell_idx)
                self._redraw()
                return

    def keyPressEvent(self, event):
        key = event.text().lower()
        if key == self.undo_key:
            self._undo()
            return
        if key in self.key_to_label and self.selected is not None:
            self._apply_label(self.key_to_label[key])

    def _on_color_combo_chosen(self, index):
        if index == 0 or self.selected is None:
            return
        label = self.color_combo.itemText(index)
        self._apply_label(label)
        self.color_combo.blockSignals(True)
        self.color_combo.setCurrentIndex(0)
        self.color_combo.blockSignals(False)

    def _apply_label(self, label):
        face_idx, cell_idx = self.selected
        cell = self.faces[face_idx]["cells"][cell_idx]
        cell["label"] = label
        cell["occluded"] = (label == "U")
        self.history.append((face_idx, cell_idx))
        self._advance_after_label(face_idx, cell_idx)
        self._redraw()

    def _advance_after_label(self, face_idx, cell_idx):
        face = self.faces[face_idx]
        next_unlabeled = next(
            (i for i, c in enumerate(face["cells"]) if c["label"] is None), None
        )
        if next_unlabeled is not None:
            self.selected = (face_idx, next_unlabeled)
            self._update_instructions()
            return

        # Face fully labeled — move to the next face, if any.
        self.selected = None
        if self.current_face_idx < 2:
            self.current_face_idx += 1
        self._update_instructions()
        self._check_all_done()

    def _undo(self):
        if not self.history:
            return
        face_idx, cell_idx = self.history.pop()
        cell = self.faces[face_idx]["cells"][cell_idx]
        cell["label"] = None
        cell["occluded"] = False
        self.selected = (face_idx, cell_idx)
        self.current_face_idx = face_idx
        self._update_instructions()
        self._redraw()
        self.save_button.setEnabled(False)

    def _check_all_done(self):
        all_done = all(
            face["cells"] is not None and all(c["label"] is not None for c in face["cells"])
            for face in self.faces
        )
        self.save_button.setEnabled(all_done)

    def _redraw(self):
        self.canvas.redraw(self.faces, self.pending_points, self.selected, self.palette)

    def _on_save(self):
        name, ok = QInputDialog.getText(
            self, "Capture name",
            "Base name for this record (used for filenames):",
            text=os.path.splitext(os.path.basename(self.image_path))[0],
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        record = {
            "name": name,
            "image_path": self.image_path,
            "slot": self.slot,
            "timestamp": time.time(),
            "lighting_tag": self.lighting_tag_input.text().strip(),
            "faces": [
                {
                    "face": face["face"],
                    "quad": [list(p) for p in face["quad"]],
                    "cells": [
                        {
                            "row": idx // 3,
                            "col": idx % 3,
                            "polygon": [list(p) for p in cell["polygon"]],
                            "center": list(cell["center"]),
                            "label": cell["label"],
                            "occluded": cell["occluded"],
                        }
                        for idx, cell in enumerate(face["cells"])
                    ],
                }
                for face in self.faces
            ],
        }

        sidecar_path, patch_count = save_label_record(
            record, self.image_bgr, self.paths, self.config["patch"]["size"]
        )
        QMessageBox.information(
            self, "Saved",
            f"Saved {sidecar_path}\nWrote {patch_count} sticker patches.",
        )


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("image", help="Path to a captured PNG")
    parser.add_argument("--slot", default="upper_corner", choices=["upper_corner", "lower_corner"])
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)
    ensure_dataset_dirs(paths)

    app = QApplication(sys.argv)
    window = LabelWindow(config, paths, args.image, args.slot)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
