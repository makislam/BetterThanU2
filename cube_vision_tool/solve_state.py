#!/usr/bin/env python3
"""Part 4 CLI — load the labeled upper_corner/lower_corner views, run the
occlusion solver, report the outcome, and validate a complete state with
kociemba.

Run: python3 solve_state.py [--upper NAME] [--lower NAME] [--config config.yaml]

Without --upper/--lower, uses the most recent record of each slot found in
dataset/master_index.jsonl.
"""

import argparse
import os
import sys

import kociemba

from common.config import load_config, resolve_paths
from common.cube_topology import FACELET_ORDER, center_index, facelet_index
from common.dataset import latest_records_by_slot, load_label_record
from common.facelet_solver import solve_facelets


def _facelets_from_records(records):
    """records: list of label records (each covering 3 faces). Returns a
    54-length list, color letter or None for occluded/unlabeled cells.
    """
    facelets = [None] * 54
    for record in records:
        for face in record["faces"]:
            letter = face["face"]
            for cell in face["cells"]:
                idx = facelet_index(letter, cell["row"], cell["col"])
                facelets[idx] = None if cell["occluded"] else cell["label"]
    return facelets


def _load_records(paths, upper_name, lower_name):
    if upper_name and lower_name:
        return [
            load_label_record(paths["labels_dir"], upper_name),
            load_label_record(paths["labels_dir"], lower_name),
        ]

    latest = latest_records_by_slot(paths["master_index"], ["upper_corner", "lower_corner"])
    missing = [s for s in ("upper_corner", "lower_corner") if s not in latest]
    if missing:
        print(f"No labeled record found for: {missing}. Label both views first.")
        sys.exit(1)
    return [latest["upper_corner"], latest["lower_corner"]]


def _print_multiple(result):
    print(f"MULTIPLE SOLUTIONS: {result['count']}{' (capped)' if result['capped'] else ''}")
    print(f"Ambiguous facelet positions: {result['ambiguous_positions']}")
    pos = result["recommended_observation"]
    if pos is not None:
        print(
            f"Observe facelet position {pos} next — in the worst case it narrows "
            f"the remaining solutions down to {result['recommended_worst_case_remaining']}."
        )
    else:
        print("All ambiguous positions are already observed; ambiguity is unresolvable by more capture.")
    print(f"Sample facelet string (one of the {result['count']} solutions):")
    print(f"  {result['sample_facelets']}")


def _to_kociemba_string(facelets):
    """kociemba.solve() expects each facelet encoded as the face letter
    (U/R/F/D/L/B) of whichever face has that facelet's color as its
    center — not the raw color letter. Translate using this cube's own
    6 observed centers.
    """
    color_to_face = {facelets[center_index(face)]: face for face in FACELET_ORDER}
    return "".join(color_to_face[c] for c in facelets)


def _validate_with_kociemba(facelets):
    try:
        solution = kociemba.solve(_to_kociemba_string(facelets))
        print(f"kociemba: VALID state. Solution: {solution}")
    except Exception as exc:
        print(f"kociemba: INVALID state — {exc}")


def main():
    parser = argparse.ArgumentParser()
    default_config = os.path.join(os.path.dirname(__file__), "config.yaml")
    parser.add_argument("--upper", default=None, help="Label record name for upper_corner")
    parser.add_argument("--lower", default=None, help="Label record name for lower_corner")
    parser.add_argument("--config", default=default_config)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    paths = resolve_paths(config, base_dir)

    records = _load_records(paths, args.upper, args.lower)
    facelets = _facelets_from_records(records)

    known = sum(1 for f in facelets if f is not None)
    print(f"{known}/54 facelets known from captures; {54 - known} occluded/unlabeled.")

    result = solve_facelets(facelets)
    outcome = result["outcome"]

    if outcome == "error":
        print(f"SETUP ERROR: {result['message']}")
        sys.exit(1)
    elif outcome == "no_solution":
        print(f"NO SOLUTION: {result['message']}")
        print("Check the labels most likely to be wrong for this slot.")
        sys.exit(1)
    elif outcome == "multiple":
        _print_multiple(result)
        sys.exit(0)
    elif outcome == "unique":
        print("UNIQUE SOLUTION:")
        print(f"  {result['facelets']}")
        _validate_with_kociemba(result["facelets"])
    else:
        print(f"Unexpected outcome: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
