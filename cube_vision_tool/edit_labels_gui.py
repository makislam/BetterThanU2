#!/usr/bin/env python3
"""Fixes individual mislabeled cells in an already-saved label record,
without redoing the whole capture.

label_gui.py always starts from a blank slate (it doesn't load an existing
sidecar) and only enables Save once every one of the 27 cells across all 3
faces has been freshly labeled in that session — so "just fix one cell"
isn't actually possible with it; you'd have to relabel everything from the
photo by eye, and it's easy to reproduce the same misread on an ambiguous
cell. This tool loads the existing quads/cells/labels directly, so you can
click just the cell(s) that are wrong, relabel those, and save immediately.

Run: python3 edit_labels_gui.py dataset/labels/<name>.json
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication, QMessageBox

from common.config import load_config, resolve_paths
from common.dataset import save_label_record
from label_gui import LabelWindow


class EditLabelsWindow(LabelWindow):
    def __init__(self, config, paths, record):
        self._record = record
        self._touched = set()  # (face_letter, row, col) actually edited this session
        super().__init__(config, paths, record["image_path"], record["slot"])
        self.setWindowTitle(f"Edit labels — {record['name']}")
        self._load_existing_record()

    def _apply_label(self, label):
        face_idx, cell_idx = self.selected
        face_letter = self.faces[face_idx]["face"]
        self._touched.add((face_letter, cell_idx // 3, cell_idx % 3))
        super()._apply_label(label)

    def _load_existing_record(self):
        for i, face in enumerate(self._record["faces"]):
            self.faces[i]["face"] = face["face"]
            self.faces[i]["quad"] = [tuple(p) for p in face["quad"]]
            self.faces[i]["cells"] = [
                {
                    "polygon": [tuple(p) for p in cell["polygon"]],
                    "center": tuple(cell["center"]),
                    "label": cell["label"],
                    "occluded": cell["occluded"],
                }
                for cell in sorted(face["cells"], key=lambda c: (c["row"], c["col"]))
            ]
            self.face_selectors[i].setCurrentText(face["face"])
        self.current_face_idx = 0
        self._check_all_done()
        self._update_instructions()
        self._redraw()

    def _on_canvas_click(self, x, y):
        # All 3 faces are already fully loaded (quads and all) - unlike the
        # base flow, a click should be able to hit any of them, not just
        # whichever one happens to be "current".
        for face_idx, face in enumerate(self.faces):
            for cell_idx, cell in enumerate(face["cells"]):
                polygon = np.array(cell["polygon"], dtype=np.float32)
                if cv2.pointPolygonTest(polygon, (x, y), False) >= 0:
                    self.current_face_idx = face_idx
                    self.selected = (face_idx, cell_idx)
                    self._update_instructions()
                    self._redraw()
                    return

    def _on_save(self):
        # Only cells actually clicked+relabeled in this session are trusted
        # from self.faces. Everything else is re-read fresh from disk right
        # before merging - another tool (fix_orientation_gui.py, another
        # edit_labels_gui.py run) may have saved a fix while this window was
        # open, and blindly writing back this session's full startup
        # snapshot would silently undo that fix.
        sidecar_path = os.path.join(self.paths["labels_dir"], f"{self._record['name']}.json")
        base_faces = self._record["faces"]
        if os.path.exists(sidecar_path):
            with open(sidecar_path) as f:
                base_faces = json.load(f)["faces"]
        touched_by_letter = {}
        for face in self.faces:
            for idx, cell in enumerate(face["cells"]):
                row, col = idx // 3, idx % 3
                if (face["face"], row, col) in self._touched:
                    touched_by_letter.setdefault(face["face"], {})[(row, col)] = (
                        cell["label"], cell["occluded"],
                    )

        faces_out = []
        for base in base_faces:
            overrides = touched_by_letter.get(base["face"], {})
            cells_out = []
            for cell in base["cells"]:
                label, occluded = overrides.get((cell["row"], cell["col"]), (cell["label"], cell["occluded"]))
                cells_out.append({**cell, "label": label, "occluded": occluded})
            faces_out.append({"face": base["face"], "quad": base["quad"], "cells": cells_out})

        record = {
            "name": self._record["name"],
            "image_path": self.image_path,
            "slot": self.slot,
            "timestamp": self._record["timestamp"],
            "lighting_tag": self._record.get("lighting_tag", ""),
            "faces": faces_out,
        }
        sidecar_path, patch_count = save_label_record(
            record, self.image_bgr, self.paths, self.config["patch"]["size"]
        )
        QMessageBox.information(
            self, "Saved",
            f"Saved corrected labels to {sidecar_path}\nWrote {patch_count} sticker patches.",
        )


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("label_json", help="Path to a saved dataset/labels/<name>.json")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    with open(args.label_json) as f:
        record = json.load(f)

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    app = QApplication(sys.argv)
    window = EditLabelsWindow(config, paths, record)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
