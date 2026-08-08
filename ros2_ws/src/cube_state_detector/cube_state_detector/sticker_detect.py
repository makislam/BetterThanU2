"""Find one whole cube face and read its 3x3 grid of colors directly from
the image, geometrically — not by detecting each of the 9 individual
cubie boundaries.

This rig's cube is stickerless: adjacent cubies are separated only by a
thin painted-plastic seam, not a sticker's dark border. That seam is too
low-contrast to rely on for finding each of the 9 cubie squares
individually. But it doesn't need to be: given one whole face, the *outer*
boundary of the face (a strong, high-contrast edge against the background)
is easy to find, and once that's found the 3x3 grid inside it is pure
geometry — divide the found quad into 3x3 and sample each cell's color
directly, with no dependency on detecting the faint internal seams at all.

The camera on this rig can never be perpendicular to a face — every shot
has real keystone/trapezoid perspective distortion, not just in-plane
rotation. `find_face_quad` returns the face's actual 4 corners (not a
rotated bounding rect, which would silently flatten a trapezoid into a
rectangle), and `sample_face_grid`'s perspective transform corrects for
that real quad shape.

Pipeline:
  1. `find_face_quad` — edge-detect the frame, find the single largest
     face-shaped contour (the whole visible face), return its 4 corners.
  2. `sample_face_grid` — perspective-correct that quad into a canonical
     top-down view, and return the pixel center of each of the 9 grid
     cells (row-major, including the center slot — callers overwrite slot
     4 with the known center color, since it's always occluded by the
     face motor's drive shaft).
"""

import cv2
import numpy as np


def _order_quad_corners(points):
    """Order 4 points as (top-left, top-right, bottom-right, bottom-left)."""
    pts = points.reshape(-1, 2).astype(np.float32)
    sums = pts.sum(axis=1)
    diffs = pts[:, 0] - pts[:, 1]
    top_left = pts[np.argmin(sums)]
    bottom_right = pts[np.argmax(sums)]
    top_right = pts[np.argmax(diffs)]
    bottom_left = pts[np.argmin(diffs)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def find_face_quad(bgr_image, params):
    """Return the 4 corners (top-left, top-right, bottom-right, bottom-left)
    of the single largest face-shaped contour in the image, or None if
    nothing plausible was found.

    This rig can't get the camera perpendicular to a face — every view has
    real keystone/trapezoid perspective distortion, not just in-plane
    rotation. So the returned quad is the contour's own 4 approximated
    corners (found by relaxing approxPolyDP's epsilon until exactly 4
    survive), not a rotated bounding rect — a bounding rect would silently
    force a true trapezoid into a rectangle and warp the grid sampling
    incorrectly. `sample_face_grid`'s perspective transform then corrects
    for the real quad shape, trapezoid included.
    """
    blur_kernel = params["blur_kernel"] | 1  # must be odd
    edges = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
    for channel in cv2.split(bgr_image):
        blurred = cv2.GaussianBlur(channel, (blur_kernel, blur_kernel), 0)
        edges = np.maximum(
            edges, cv2.Canny(blurred, params["canny_low"], params["canny_high"])
        )
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_quad = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < params["min_face_area"] or area > params["max_face_area"]:
            continue

        hull = cv2.convexHull(contour)
        perimeter = cv2.arcLength(hull, True)
        if perimeter == 0:
            continue

        approx = None
        for eps_fraction in (0.02, 0.03, 0.05, 0.08, 0.12):
            candidate = cv2.approxPolyDP(hull, eps_fraction * perimeter, True)
            if len(candidate) == 4:
                approx = candidate
                break
        if approx is None:
            continue

        quad = _order_quad_corners(approx)
        top_w = np.linalg.norm(quad[1] - quad[0])
        bottom_w = np.linalg.norm(quad[2] - quad[3])
        left_h = np.linalg.norm(quad[3] - quad[0])
        right_h = np.linalg.norm(quad[2] - quad[1])
        avg_w, avg_h = (top_w + bottom_w) / 2.0, (left_h + right_h) / 2.0
        if avg_w == 0 or avg_h == 0:
            continue
        aspect_ratio = min(avg_w, avg_h) / max(avg_w, avg_h)
        if aspect_ratio < params["aspect_ratio_tolerance"]:
            continue

        if area > best_area:
            best_area = area
            best_quad = quad

    return best_quad


def sample_face_grid(bgr_image, quad, params):
    """Perspective-correct `quad` into a canonical top-down square and
    return (warped_bgr_image, cells), where cells is a row-major list of 9
    {"center": (x, y)} dicts locating each grid cell's center in the warped
    image (slot 4 is the center cell — always occluded in practice, but its
    position is returned for debug-image purposes).
    """
    warp_size = params["warp_size"]
    dst = np.array(
        [[0, 0], [warp_size - 1, 0], [warp_size - 1, warp_size - 1], [0, warp_size - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(bgr_image, transform, (warp_size, warp_size))

    cell_size = warp_size / 3.0
    cells = []
    for row in range(3):
        for col in range(3):
            cx = col * cell_size + cell_size / 2.0
            cy = row * cell_size + cell_size / 2.0
            cells.append({"center": (cx, cy)})
    return warped, cells
