"""Turn a human-clicked 4-corner quad into a 3x3 grid of sticker cell
polygons/centers, via bilinear interpolation. This deliberately does not
try to perspective-correct or assume the quad is a rectangle — a cube face
seen at an oblique angle is a general (non-rectangular) quadrilateral, and
bilinear interpolation across its 4 corners handles that directly without
needing a homography.
"""

import numpy as np


def _bilinear_point(quad, u, v):
    """quad = [top_left, top_right, bottom_right, bottom_left]. u, v in
    [0, 1], u is left->right, v is top->bottom."""
    top_left, top_right, bottom_right, bottom_left = quad
    top = top_left * (1 - u) + top_right * u
    bottom = bottom_left * (1 - u) + bottom_right * u
    return top * (1 - v) + bottom * v


def face_grid(quad, grid_size=3):
    """quad: 4 (x, y) points in [top_left, top_right, bottom_right,
    bottom_left] order. Returns a row-major list of `grid_size**2` cells,
    each {"polygon": [4 (x, y) points], "center": (x, y)}.
    """
    quad = np.array(quad, dtype=np.float64)
    step = 1.0 / grid_size
    cells = []
    for row in range(grid_size):
        for col in range(grid_size):
            u0, u1 = col * step, (col + 1) * step
            v0, v1 = row * step, (row + 1) * step
            polygon = [
                _bilinear_point(quad, u0, v0),
                _bilinear_point(quad, u1, v0),
                _bilinear_point(quad, u1, v1),
                _bilinear_point(quad, u0, v1),
            ]
            center = _bilinear_point(quad, (u0 + u1) / 2.0, (v0 + v1) / 2.0)
            cells.append({
                "polygon": [tuple(p) for p in polygon],
                "center": tuple(center),
            })
    return cells
