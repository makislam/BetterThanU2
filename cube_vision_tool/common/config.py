"""Load and validate config.yaml. Every other module takes the loaded
config as a constructor argument rather than reading the file itself, so
there's a single source of truth and no hidden globals.
"""

import os

import yaml

REQUIRED_TOP_KEYS = ("palette", "key_bindings", "capture", "paths", "patch")


def load_config(path):
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    missing = [k for k in REQUIRED_TOP_KEYS if k not in config]
    if missing:
        raise ValueError(f"config.yaml missing required section(s): {missing}")

    if len(config["capture"]["slots"]) != 2:
        raise ValueError("config.yaml: capture.slots must list exactly 2 slots")

    return config


def resolve_paths(config, base_dir):
    """Return config['paths'] with every entry made absolute, relative to
    `base_dir` (the directory config.yaml lives in)."""
    return {key: os.path.join(base_dir, value) for key, value in config["paths"].items()}


def ensure_dataset_dirs(paths):
    os.makedirs(paths["captures_dir"], exist_ok=True)
    os.makedirs(paths["labels_dir"], exist_ok=True)
    os.makedirs(paths["patches_dir"], exist_ok=True)
