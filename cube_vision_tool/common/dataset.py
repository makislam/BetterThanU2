"""Data persistence for the labeled cube dataset (Part 3):

- raw capture PNGs (written by capture_gui.py, lossless)
- one JSON sidecar per labeled image, with every quad/cell/label/occlusion
  fact needed to reconstruct or re-derive anything later
- a single append-only master_index.jsonl (JSON Lines — no read-modify-
  write of one giant array as the dataset grows)
- cropped sticker patches, one folder per color, for direct use as a
  classifier training set later
"""

import json
import os
import time

import cv2
import numpy as np


def make_capture_name(slot, timestamp=None):
    """Deterministic, sortable base name: <timestamp>_<slot>. Timestamp is
    seconds-resolution local time in a sortable format, which is enough to
    keep capture ordering unambiguous within this dataset's use case.
    """
    timestamp = timestamp if timestamp is not None else time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(timestamp))
    return f"{stamp}_{slot}"


def save_capture_png(image_bgr, name, captures_dir):
    """Save the raw frame losslessly. Returns the file path."""
    path = os.path.join(captures_dir, f"{name}.png")
    cv2.imwrite(path, image_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 0])
    return path


def _crop_polygon_patch(image_bgr, polygon, size):
    """Crop the axis-aligned bounding box of `polygon` from the image and
    resize to (size, size). Bounding-box crop (not a perspective warp of
    the polygon itself) is enough for a classifier training patch and
    keeps this simple.
    """
    height, width = image_bgr.shape[:2]
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x_min = max(0, int(round(min(xs))))
    x_max = min(width, int(round(max(xs))))
    y_min = max(0, int(round(min(ys))))
    y_max = min(height, int(round(max(ys))))
    if x_max <= x_min or y_max <= y_min:
        return None
    patch = image_bgr[y_min:y_max, x_min:x_max]
    return cv2.resize(patch, (size, size), interpolation=cv2.INTER_AREA)


def save_label_record(record, image_bgr, paths, patch_size):
    """Persist a completed label record.

    record = {
        "name": str, "image_path": str, "slot": str, "timestamp": float,
        "lighting_tag": str,
        "faces": [
            {"face": "U", "quad": [[x, y], ...4],
             "cells": [{"row": int, "col": int, "polygon": [[x, y], ...4],
                        "center": [x, y], "label": "W", "occluded": bool},
                       ...9]},
            ...
        ],
    }
    """
    name = record["name"]

    sidecar_path = os.path.join(paths["labels_dir"], f"{name}.json")
    with open(sidecar_path, "w") as f:
        json.dump(record, f, indent=2)

    with open(paths["master_index"], "a") as f:
        f.write(json.dumps(record) + "\n")

    patch_count = 0
    for face in record["faces"]:
        for cell in face["cells"]:
            if cell["occluded"]:
                continue
            patch = _crop_polygon_patch(image_bgr, cell["polygon"], patch_size)
            if patch is None:
                continue
            color_dir = os.path.join(paths["patches_dir"], cell["label"])
            os.makedirs(color_dir, exist_ok=True)
            patch_name = f"{name}_{face['face']}_{cell['row']}{cell['col']}.png"
            cv2.imwrite(os.path.join(color_dir, patch_name), patch)
            patch_count += 1

    return sidecar_path, patch_count


def load_label_record(labels_dir, name):
    with open(os.path.join(labels_dir, f"{name}.json"), "r") as f:
        return json.load(f)


def latest_records_by_slot(master_index_path, slots):
    """Scan master_index.jsonl and return {slot: most_recent_record} for
    the given slot names. Used by solve_state.py to grab the most recent
    upper_corner/lower_corner pair without having to name files explicitly.
    """
    latest = {}
    if not os.path.exists(master_index_path):
        return latest
    with open(master_index_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record["slot"] in slots:
                latest[record["slot"]] = record
    return latest
