#!/usr/bin/env python3
"""Renders the currently labeled state as a classic unfolded cube net
(cross layout) PNG, so you can check all 54 cells against the physical
cube at once instead of hunting one bad corner/edge at a time via
solve_state.py's error messages.

    layout:      U
             L   F   R   B
                 D

Occluded/unlabeled cells are drawn as a gray '?'.

Run: python3 visualize_state.py [--upper NAME] [--lower NAME] [--out state.png] [--config config.yaml]
"""

import argparse
import os

import cv2
import numpy as np

from common.config import load_config, resolve_paths
from solve_state import _load_records, _facelets_from_records

FACE_ORDER = "URFDLB"
# (grid_row, grid_col) of each face's top-left corner in the net, in face-grid units.
NET_POSITIONS = {
    "U": (0, 1),
    "L": (1, 0),
    "F": (1, 1),
    "R": (1, 2),
    "B": (1, 3),
    "D": (2, 1),
}
CELL_PX = 60
MARGIN_PX = 20
SWATCH_BGR = {
    "W": (255, 255, 255),
    "Y": (0, 220, 255),
    "R": (40, 40, 220),
    "O": (0, 140, 255),
    "B": (200, 80, 30),
    "G": (60, 160, 60),
}
UNKNOWN_BGR = (120, 120, 120)


def render_net(facelets):
    grid_h = 3 * 3 + 2 * MARGIN_PX // CELL_PX  # rows of net in face-cell units (not used directly)
    width = 4 * 3 * CELL_PX + 2 * MARGIN_PX
    height = 3 * 3 * CELL_PX + 2 * MARGIN_PX
    canvas = np.full((height, width, 3), 30, dtype=np.uint8)

    for face_idx, face in enumerate(FACE_ORDER):
        base_row, base_col = NET_POSITIONS[face]
        origin_y = MARGIN_PX + base_row * 3 * CELL_PX
        origin_x = MARGIN_PX + base_col * 3 * CELL_PX
        for r in range(3):
            for c in range(3):
                label = facelets[face_idx * 9 + r * 3 + c]
                color = UNKNOWN_BGR if label is None else SWATCH_BGR.get(label, UNKNOWN_BGR)
                x0, y0 = origin_x + c * CELL_PX, origin_y + r * CELL_PX
                x1, y1 = x0 + CELL_PX, y0 + CELL_PX
                cv2.rectangle(canvas, (x0, y0), (x1, y1), color, -1)
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 0, 0), 2)
                text = label if label else "?"
                text_color = (0, 0, 0) if label else (255, 255, 255)
                cv2.putText(
                    canvas, text, (x0 + CELL_PX // 2 - 8, y0 + CELL_PX // 2 + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2,
                )
        face_label_pos = (origin_x + 3 * CELL_PX // 2 - 6, origin_y - 6)
        cv2.putText(canvas, face, face_label_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    return canvas


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("--upper", default=None)
    parser.add_argument("--lower", default=None)
    parser.add_argument("--out", default="state_net.png")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    records = _load_records(paths, args.upper, args.lower)
    facelets = _facelets_from_records(records)

    known = sum(1 for f in facelets if f is not None)
    print(f"{known}/54 facelets known; {54 - known} occluded/unlabeled (shown as '?').")

    canvas = render_net(facelets)
    cv2.imwrite(args.out, canvas)
    print(f"Wrote {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
