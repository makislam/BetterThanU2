"""Find the 9 stickers of each visible cube face directly from the image.

No fixed pixel ROI and no fiducial marker — the cube's own geometry (9
roughly-square, roughly-equal-size stickers separated by dark plastic) is
distinctive enough to find on its own. This makes the whole pipeline
tolerant of the camera being repositioned before every capture.

Pipeline:
  1. `find_sticker_candidates` — edge-detect the frame, keep contours that
     look like a single sticker (convex, roughly square, in a plausible
     size range).
  2. `cluster_into_faces` — group candidates that are close together into
     per-face clusters (one cluster per visible face), pick the clusters
     that best match "9 stickers", and order them left-to-right/top-to-
     bottom to match how faces are listed in config/roi.yaml.
  3. `order_grid` — within one face's 9 points, work out row/column order
     even if the face is tilted or rotated in frame.
"""

import cv2
import numpy as np


def find_sticker_candidates(bgr_image, params):
    """Return a list of {"center": (x, y), "size": float, "contour": ndarray}
    for every contour in the image that looks like it could be one sticker.
    """
    # Edge-detect each color channel separately and combine (rather than
    # grayscale only) — a saturated blue sticker has low luminance and can
    # go nearly invisible to a grayscale gradient against a dark plastic
    # gap, even though it's obviously distinct in the blue channel.
    blur_kernel = params["blur_kernel"] | 1  # must be odd
    edges = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
    for channel in cv2.split(bgr_image):
        blurred = cv2.GaussianBlur(channel, (blur_kernel, blur_kernel), 0)
        edges = np.maximum(
            edges, cv2.Canny(blurred, params["canny_low"], params["canny_high"])
        )
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < params["min_sticker_area"] or area > params["max_sticker_area"]:
            continue

        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        if not (4 <= len(approx) <= 6):
            continue
        if not cv2.isContourConvex(cv2.convexHull(approx)):
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if h == 0:
            continue
        aspect_ratio = min(w, h) / max(w, h)
        if aspect_ratio < params["aspect_ratio_tolerance"]:
            continue

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]

        candidates.append({"center": (cx, cy), "size": (w + h) / 2.0, "contour": contour})

    return _drop_nested_duplicates(candidates)


def _drop_nested_duplicates(candidates):
    """Edge detection often yields both a sticker's inner and outer contour.
    Keep one per sticker by dropping candidates whose center nearly
    coincides with a larger candidate already kept.
    """
    kept = []
    for candidate in sorted(candidates, key=lambda c: c["size"], reverse=True):
        cx, cy = candidate["center"]
        too_close = False
        for other in kept:
            ox, oy = other["center"]
            if ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5 < 0.4 * candidate["size"]:
                too_close = True
                break
        if not too_close:
            kept.append(candidate)
    return kept


def _cluster_by_distance(candidates, distance_threshold):
    """Union-find clustering: group candidates within distance_threshold of
    each other (directly or transitively) into the same face.
    """
    n = len(candidates)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        xi, yi = candidates[i]["center"]
        for j in range(i + 1, n):
            xj, yj = candidates[j]["center"]
            if ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5 <= distance_threshold:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(candidates[i])
    return list(groups.values())


def cluster_into_faces(candidates, expected_face_count, cluster_distance_factor):
    """Group sticker candidates into `expected_face_count` faces.

    Returns a list of clusters (each a list of candidate dicts), ordered
    top-to-bottom then left-to-right by cluster centroid, or None if fewer
    than `expected_face_count` clusters of plausible size (7-11 stickers,
    tolerating a couple of missed/spurious detections) were found.
    """
    if not candidates:
        return None

    median_size = float(np.median([c["size"] for c in candidates]))
    distance_threshold = median_size * cluster_distance_factor

    groups = _cluster_by_distance(candidates, distance_threshold)
    face_sized_groups = [g for g in groups if 7 <= len(g) <= 11]
    if len(face_sized_groups) < expected_face_count:
        return None

    def group_center(group):
        xs = [c["center"][0] for c in group]
        ys = [c["center"][1] for c in group]
        return (sum(ys) / len(ys), sum(xs) / len(xs))  # (row key, col key)

    face_sized_groups.sort(key=lambda g: abs(len(g) - 9))
    best_groups = face_sized_groups[:expected_face_count]
    best_groups.sort(key=group_center)
    return best_groups


def order_grid(cluster):
    """Sort one face's 9 sticker candidates into row-major (U R F D L B
    facelet) order, correcting for the face being rotated/tilted in frame.

    Returns None if the cluster isn't exactly 9 stickers.
    """
    if len(cluster) != 9:
        return None

    points = np.array([c["center"] for c in cluster], dtype=np.float32)
    center = points.mean(axis=0)

    rect = cv2.minAreaRect(points)
    # A 3x3 grid has 90-degree rotational symmetry, so minAreaRect's angle
    # (whose convention also varies by OpenCV version) is only meaningful
    # modulo 90 degrees here. Normalize into (-45, 45] so index 0 is always
    # a single row's y-extent, not a full column's.
    angle_deg = rect[2] % 90
    if angle_deg > 45:
        angle_deg -= 90
    angle = np.deg2rad(angle_deg)

    cos_a, sin_a = np.cos(-angle), np.sin(-angle)
    rotation = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    rotated = (points - center) @ rotation.T

    row_order = np.argsort(rotated[:, 1])
    rows = [row_order[0:3], row_order[3:6], row_order[6:9]]
    ordered_indices = []
    for row in rows:
        row_sorted = row[np.argsort(rotated[row][:, 0])]
        ordered_indices.extend(row_sorted.tolist())

    return [cluster[i] for i in ordered_indices]


def detect_faces(bgr_image, expected_face_count, params):
    """Full pipeline: image -> list of `expected_face_count` faces, each a
    row-major list of 9 {"center", "size", "contour"} dicts. Returns None if
    detection didn't confidently find that many faces.
    """
    candidates = find_sticker_candidates(bgr_image, params)
    clusters = cluster_into_faces(
        candidates, expected_face_count, params["cluster_distance_factor"]
    )
    if clusters is None:
        return None

    ordered_faces = []
    for cluster in clusters:
        ordered = order_grid(cluster)
        if ordered is None:
            return None
        ordered_faces.append(ordered)
    return ordered_faces
