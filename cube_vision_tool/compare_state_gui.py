#!/usr/bin/env python3
"""Side-by-side comparison for eyeballing every labeled cell against the
real photo at once: for each capture (upper_corner, lower_corner), the
actual photo with the recorded label drawn on every cell, next to a clean
isometric cube-corner render filled with those same labels' colors.

Run: python3 compare_state_gui.py [--upper NAME] [--lower NAME]
     [--out state_comparison.png] [--config config.yaml]
"""

import argparse
import os

import cv2
import numpy as np

from common.config import load_config, resolve_paths
from common.geometry import face_grid
from label_gui import SLOT_FACE_ORDER
from solve_state import _load_records

# (top-diamond face, front-left face, front-right face) for each slot's
# isometric render - same fixed rig convention as label_gui.SLOT_FACE_ORDER
# (upper_corner is a from-above view, U on top; lower_corner is from below,
# so the "up-facing" plane there is D).
ROLE_ORDER = SLOT_FACE_ORDER

SWATCH_BGR = {
    "W": (255, 255, 255),
    "Y": (0, 220, 255),
    "R": (40, 40, 220),
    "O": (0, 140, 255),
    "B": (200, 80, 30),
    "G": (60, 160, 60),
}
UNKNOWN_BGR = (120, 120, 120)
PANEL_HEIGHT = 480


def _draw_labels_on_photo(record):
    """Real capture, with the recorded label drawn on every cell so a
    misread color is visually obvious against the actual sticker."""
    image = cv2.imread(record["image_path"])
    for face in record["faces"]:
        for cell in face["cells"]:
            polygon = np.array(cell["polygon"], dtype=np.int32)
            cv2.polylines(image, [polygon], True, (0, 255, 0), 1)
            label = cell["label"] if not cell["occluded"] else "?"
            cx, cy = (int(round(v)) for v in cell["center"])
            color = SWATCH_BGR.get(label, (255, 255, 255))
            # White outline behind the text so it's readable over any sticker color.
            cv2.putText(image, label, (cx - 10, cy + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 4)
            cv2.putText(image, label, (cx - 10, cy + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        x0, y0 = (int(round(v)) for v in face["quad"][0])
        cv2.putText(image, face["face"], (x0, y0 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

    scale = PANEL_HEIGHT / image.shape[0]
    return cv2.resize(image, (int(image.shape[1] * scale), PANEL_HEIGHT))


def _isometric_corner(record, size=140):
    """Idealized 3-face cube corner (top diamond + two side parallelograms,
    same convention as the classic cube-net diagrams), filled with the
    recorded label colors.

    Each quad below is given in the CANONICAL (0,0),(0,2),(2,2),(2,0) order
    of its face - the same URFDLB row/col convention the stored cells use -
    so a cell drawn here sits where that facelet really is on the cube, not
    merely where it happened to appear on screen. upper_corner is drawn as
    the from-above view (U diamond on top, F/R walls hanging below);
    lower_corner as the from-below view (D diamond at the bottom, B/L walls
    rising above it), which is what the camera actually sees."""
    h = size // 2
    cx, cy = size * 2, size
    top, right, bottom, left = (cx, cy), (cx + size, cy + h), (cx, cy + 2 * h), (cx - size, cy + h)
    up = lambda p: (p[0], p[1] - size)
    down = lambda p: (p[0], p[1] + size)

    if record["slot"] == "lower_corner":
        # D diamond: near/front point is `bottom` (lowest in frame), the B
        # wall is on the left, the L wall on the right.
        # D canonical (0,0)=DLF (0,2)=DFR (2,2)=DRB (2,0)=DBL
        #   -> right point, back point, left point, near point
        quads = {
            0: [right, top, left, bottom],
            1: [up(left), up(bottom), bottom, left],    # B, rising above the left edge
            2: [up(bottom), up(right), right, bottom],  # L, rising above the right edge
        }
    else:
        # U canonical (0,0)=ULB (0,2)=UBR (2,2)=URF (2,0)=UFL
        #   -> back point, right point, near point, left point
        quads = {
            0: [top, right, bottom, left],
            1: [left, bottom, down(bottom), down(left)],   # F, hanging below the left edge
            2: [bottom, right, down(right), down(bottom)],  # R, hanging below the right edge
        }

    width, height = size * 4, size * 3
    canvas = np.full((height, width, 3), 30, dtype=np.uint8)

    faces_by_letter = {f["face"]: f for f in record["faces"]}
    role_letters = ROLE_ORDER.get(record["slot"], tuple(f["face"] for f in record["faces"][:3]))

    for i, letter in enumerate(role_letters):
        face = faces_by_letter[letter]
        cells = face_grid(quads[i], grid_size=3)
        grid = {(c["row"], c["col"]): c for c in face["cells"]}
        for idx, cell in enumerate(cells):
            row, col = idx // 3, idx % 3
            source = grid.get((row, col))
            label = None if source is None or source["occluded"] else source["label"]
            color = UNKNOWN_BGR if label is None else SWATCH_BGR.get(label, UNKNOWN_BGR)
            polygon = np.array(cell["polygon"], dtype=np.int32)
            cv2.fillPoly(canvas, [polygon], color)
            cv2.polylines(canvas, [polygon], True, (0, 0, 0), 2)
            cx_, cy_ = (int(round(v)) for v in cell["center"])
            text = label if label else "?"
            text_color = (0, 0, 0) if label else (255, 255, 255)
            cv2.putText(canvas, text, (cx_ - 8, cy_ + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
        label_anchor = quads[i][0]
        cv2.putText(canvas, face["face"], (int(label_anchor[0]) - 10, int(label_anchor[1]) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

    scale = PANEL_HEIGHT / canvas.shape[0]
    return cv2.resize(canvas, (int(canvas.shape[1] * scale), PANEL_HEIGHT))


def _hstack_padded(images, pad=10, bg=(20, 20, 20)):
    height = max(img.shape[0] for img in images)
    padded = []
    for img in images:
        canvas = np.full((height, img.shape[1] + pad, 3), bg, dtype=np.uint8)
        canvas[: img.shape[0], : img.shape[1]] = img
        padded.append(canvas)
    return np.hstack(padded)


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("--upper", default=None)
    parser.add_argument("--lower", default=None)
    parser.add_argument("--out", default="state_comparison.png")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    records = _load_records(paths, args.upper, args.lower)

    rows = []
    for record in records:
        photo_panel = _draw_labels_on_photo(record)
        render_panel = _isometric_corner(record)
        rows.append(_hstack_padded([photo_panel, render_panel]))

    width = max(row.shape[1] for row in rows)
    padded_rows = []
    for row in rows:
        canvas = np.full((row.shape[0], width, 3), 20, dtype=np.uint8)
        canvas[:, : row.shape[1]] = row
        padded_rows.append(canvas)
    final = np.vstack(padded_rows)

    cv2.imwrite(args.out, final)
    print(f"Wrote {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
