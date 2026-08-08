#!/usr/bin/env python3
"""Fixes a face whose 4 corners were clicked in the wrong order during
labeling (e.g. didn't start at top-left, or went the wrong rotational
direction) — this makes the *colors* correct but files them under the
wrong row/col, which the solver's fixed corner/edge cubie checks then
reject as an impossible cube state even though nothing is actually wrong
in the photo.

Re-click just the 4 corners for the affected face(s), in the correct
order shown in the on-screen hint for each click (which is the face's
canonical row/col order, NOT screen order - see label_gui._CLICK_HINTS).
Existing labels
are carried over automatically by matching each new grid cell to the
closest old one by pixel position — you don't need to re-key any colors,
only fix if the nearest-match guess is visibly wrong (rare; only happens
if the old orientation was ambiguous, e.g. a 180 degree case where every
cell has a plausible match on the opposite side).

Run: python3 fix_orientation_gui.py dataset/labels/<name>.json [--face U]
     (omit --face to step through all 3 faces in the record)
"""

import argparse
import json
import os
import sys

import numpy as np
from PyQt5.QtWidgets import QApplication, QMessageBox

from common.config import load_config, resolve_paths
from common.dataset import save_label_record
from common.geometry import face_grid
from label_gui import SLOT_FACE_ORDER, LabelWindow


class FixOrientationWindow(LabelWindow):
    def __init__(self, config, paths, record, only_face=None):
        self._record = record
        self._old_cells_by_face = {f["face"]: f["cells"] for f in record["faces"]}
        self._only_face = only_face
        super().__init__(config, paths, record["image_path"], record["slot"])
        self.setWindowTitle(f"Fix orientation — {record['name']}")
        self._select_target_faces()

    def _select_target_faces(self):
        # LabelWindow._build_ui already auto-assigned all 3 dropdowns from
        # SLOT_FACE_ORDER (the rig's fixed face layout) — no need to (and,
        # since all 3 letters are already taken, must not try to) reassign
        # them here. Just work out which face index(es) this run should
        # actually re-click.
        fixed_order = SLOT_FACE_ORDER.get(self.slot)
        if fixed_order is None:
            # Fallback for a slot with no fixed layout: assign manually.
            letters = [self._only_face] if self._only_face else [f["face"] for f in self._record["faces"]]
            for i, letter in enumerate(letters):
                self.face_selectors[i].setCurrentText(letter)
            fixed_order = [self.faces[i]["face"] for i in range(3)]

        target_letters = [self._only_face] if self._only_face else list(fixed_order)
        self._target_indices = [i for i, letter in enumerate(fixed_order) if letter in target_letters]
        self.current_face_idx = self._target_indices[0]
        self._update_instructions()
        self._redraw()

    def _on_canvas_click(self, x, y):
        face = self.faces[self.current_face_idx]
        if self.current_face_idx not in self._target_indices or face["quad"] is not None:
            super()._on_canvas_click(x, y)
            return

        self.pending_points.append((x, y))
        if len(self.pending_points) == 4:
            face["quad"] = list(self.pending_points)
            face["cells"] = face_grid(face["quad"], grid_size=3)
            self._carry_over_labels(face)
            self.pending_points = []
            self.selected = None
            self._advance_after_reorient()
        self._update_instructions()
        self._redraw()

    def _carry_over_labels(self, face):
        old_cells = self._old_cells_by_face.get(face["face"], [])
        old_centers = np.array([c["center"] for c in old_cells], dtype=np.float64)
        for cell in face["cells"]:
            if len(old_cells) == 0:
                cell["label"], cell["occluded"] = None, False
                continue
            dists = np.linalg.norm(old_centers - np.array(cell["center"]), axis=1)
            nearest = old_cells[int(np.argmin(dists))]
            cell["label"] = nearest["label"]
            cell["occluded"] = nearest["occluded"]

    def _check_all_done(self):
        # Unlike LabelWindow, a --face-only run leaves the other faces'
        # quads at None on purpose — only require the target face(s) (the
        # ones actually being re-clicked here) to be done.
        all_done = all(self.faces[i]["cells"] is not None for i in self._target_indices)
        self.save_button.setEnabled(all_done)

    def _advance_after_reorient(self):
        # Skip the "click a cell, press a color key" phase entirely — labels
        # were just carried over. Move straight to the next target face
        # needing a re-click, if any.
        remaining = [i for i in self._target_indices if self.faces[i]["quad"] is None]
        if remaining:
            self.current_face_idx = remaining[0]
        self._check_all_done()

    def _on_save(self):
        # A --face-only run leaves the other faces untouched in self.faces
        # (face=None); carry those over unchanged from the original record
        # so the saved record still has all 3 faces, not just the fixed one.
        corrected_by_letter = {
            face["face"]: face for face in self.faces if face["quad"] is not None
        }
        # Re-read the sidecar from disk right before merging, not the
        # snapshot loaded when this session started - another tool may have
        # saved a fix to a different face in the meantime, and writing back
        # this session's stale copy of it would silently undo that fix.
        sidecar_path = os.path.join(self.paths["labels_dir"], f"{self._record['name']}.json")
        base_faces = self._record["faces"]
        if os.path.exists(sidecar_path):
            with open(sidecar_path) as f:
                base_faces = json.load(f)["faces"]

        faces_out = []
        for original in base_faces:
            letter = original["face"]
            face = corrected_by_letter.get(letter)
            if face is None:
                faces_out.append(original)
                continue
            faces_out.append({
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
            })

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
            f"Saved corrected orientation to {sidecar_path}\n"
            f"Wrote {patch_count} sticker patches.\n\n"
            "This appends a newer record for this slot, which solve_state.py "
            "and cube_solver_node both already pick up as the latest.",
        )


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("label_json", help="Path to a saved dataset/labels/<name>.json")
    parser.add_argument("--face", choices=["U", "R", "F", "D", "L", "B"], default=None,
                         help="Only re-click this one face (default: step through all 3 in the record)")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    with open(args.label_json) as f:
        record = json.load(f)

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    app = QApplication(sys.argv)
    window = FixOrientationWindow(config, paths, record, only_face=args.face)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
