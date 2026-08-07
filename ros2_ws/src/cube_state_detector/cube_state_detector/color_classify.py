"""Match a sampled sticker color to one of the 6 cube colors.

Colors are compared in HSV. Hue is a circle (0-179 in OpenCV), so we
measure hue distance the short way around the circle instead of a plain
subtraction.
"""

import numpy as np

# Default color labels used by this package. A cube sticker is always
# one of these 6 colors.
COLOR_LABELS = ["W", "Y", "R", "O", "B", "G"]


def hue_distance(h1, h2, hue_max=180):
    """Shortest distance between two hues on the OpenCV 0-179 hue circle."""
    diff = abs(h1 - h2) % hue_max
    return min(diff, hue_max - diff)


def color_distance(sample_hsv, reference_hsv, hue_weight=2.0):
    """Weighted distance between a sampled HSV color and a reference HSV color.

    Hue matters most for telling cube colors apart, so it gets extra weight.
    White and yellow can have low/unstable saturation under glare, which is
    why saturation and value are still included but weighted less.
    """
    h_diff = hue_distance(sample_hsv[0], reference_hsv[0])
    s_diff = float(sample_hsv[1]) - float(reference_hsv[1])
    v_diff = float(sample_hsv[2]) - float(reference_hsv[2])
    return (hue_weight * h_diff) ** 2 + s_diff**2 + v_diff**2


def classify_color(sample_hsv, reference_colors):
    """Return the label from reference_colors whose HSV is closest to sample_hsv.

    reference_colors: dict of {label: (h, s, v)}
    """
    best_label = None
    best_distance = None
    for label, reference_hsv in reference_colors.items():
        distance = color_distance(sample_hsv, reference_hsv)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_label = label
    return best_label


def median_hsv(hsv_image, center_x, center_y, patch_radius=6):
    """Median HSV of a square patch around (center_x, center_y).

    Using the median (not the mean) ignores a few stray glare/shadow
    pixels at the edge of the patch.
    """
    height, width = hsv_image.shape[:2]
    x_min = max(0, center_x - patch_radius)
    x_max = min(width, center_x + patch_radius + 1)
    y_min = max(0, center_y - patch_radius)
    y_max = min(height, center_y + patch_radius + 1)
    patch = hsv_image[y_min:y_max, x_min:x_max].reshape(-1, 3)
    return tuple(np.median(patch, axis=0))
