#!/usr/bin/env python3
"""Convenience wrapper for the ROS pipeline launch file: finds the most
recently captured PNG for one capture slot and hands it straight to
label_gui.py, so the launch file doesn't need to know capture_gui.py's
timestamped filenames.

Run: python3 label_latest.py --slot upper_corner [--config config.yaml]
"""
import argparse
import glob
import os
import sys

from common.config import load_config, resolve_paths
from label_gui import main as label_gui_main


def _latest_capture(captures_dir, slot):
    matches = sorted(glob.glob(os.path.join(captures_dir, f"*_{slot}.png")))
    if not matches:
        raise FileNotFoundError(f"No captures found for slot '{slot}' in {captures_dir}")
    return matches[-1]


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("--slot", default="upper_corner", choices=["upper_corner", "lower_corner"])
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    image_path = _latest_capture(paths["captures_dir"], args.slot)
    # label_gui.py parses sys.argv itself; hand off with the resolved path.
    sys.argv = [sys.argv[0], image_path, "--slot", args.slot, "--config", args.config]
    label_gui_main()


if __name__ == "__main__":
    main()
