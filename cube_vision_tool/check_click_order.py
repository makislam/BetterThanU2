#!/usr/bin/env python3
"""Self-check for the labeling click order (label_gui._CLICK_HINTS).

The hint text tells the user which *physical cubie corner* to click for
each of the 4 clicks. This asserts that those physical corners really are
the canonical (0,0)/(0,2)/(2,2)/(2,0) corners of that face according to
cube_topology.CORNERS - i.e. that a correctly-followed hint files stickers
at the right row/col, which is exactly what was going wrong before.

Run: python3 check_click_order.py
"""

import sys

from common.cube_topology import CORNERS, facelet_index

# The physical cubie each click should land on, in click order, mirroring
# the geometry comments in label_gui._CLICK_HINTS.
EXPECTED = {
    "upper_corner": {  # U diamond up, F left wall, R right wall
        "U": ["ULB", "UBR", "URF", "UFL"],  # back, right, near, left
        "F": ["UFL", "URF", "DFR", "DLF"],
        "R": ["URF", "UBR", "DRB", "DFR"],
    },
    "lower_corner": {  # D diamond down, B left wall, L right wall
        "D": ["DLF", "DFR", "DRB", "DBL"],  # right, back, left, near
        "B": ["UBR", "ULB", "DBL", "DRB"],
        "L": ["ULB", "UFL", "DLF", "DBL"],
    },
}

CANONICAL_CELLS = [(0, 0), (0, 2), (2, 2), (2, 0)]

_CORNER_BY_FACELET = {}
for corner in CORNERS:
    name = "".join(corner["letters"])
    for idx in corner["facelets"]:
        _CORNER_BY_FACELET[idx] = frozenset(name)


def main():
    failures = []
    for slot, faces in EXPECTED.items():
        for face, cubies in faces.items():
            for click, (cubie, (row, col)) in enumerate(zip(cubies, CANONICAL_CELLS), 1):
                actual = _CORNER_BY_FACELET[facelet_index(face, row, col)]
                if actual != frozenset(cubie):
                    failures.append(
                        f"{slot} face {face} click {click}: canonical ({row},{col}) "
                        f"is cubie {''.join(sorted(actual))}, hint says {cubie}"
                    )

    # Both walls of a view must agree on the physical points they share.
    shared = [
        ("upper_corner", "F", 2, "R", 1),  # near/front top point (URF)
        ("upper_corner", "F", 3, "R", 4),  # bottom of the shared front edge (DFR)
        ("lower_corner", "B", 2, "L", 1),  # top of the shared vertical edge (ULB)
        ("lower_corner", "B", 3, "L", 4),  # near/front point of the D diamond (DBL)
    ]
    for slot, face_a, click_a, face_b, click_b in shared:
        a = EXPECTED[slot][face_a][click_a - 1]
        b = EXPECTED[slot][face_b][click_b - 1]
        if frozenset(a) != frozenset(b):
            failures.append(
                f"{slot}: {face_a} click {click_a} ({a}) and {face_b} click "
                f"{click_b} ({b}) are described as the same point but differ"
            )

    if failures:
        print("FAIL:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print(f"OK — all {sum(len(f) * 4 for f in EXPECTED.values())} clicks land on the "
          "canonical corner cube_topology expects.")


if __name__ == "__main__":
    main()
