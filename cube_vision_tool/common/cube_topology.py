"""Fixed structural facts about any standard 3x3 Rubik's Cube: which
facelet positions belong to which corner/edge cubie, and each corner's
fixed clockwise-from-outside color order.

This is NOT a tunable assumption about *this* cube — it's the same
topology (which face is adjacent to which, in what rotational order) that
every 3x3 cube solver relies on, including the `kociemba` package used
for final validation. What *is* specific to this physical cube (which
color sits on which face) comes entirely from the 6 observed center
colors, handled in facelet_solver.py — not from anything in this file.

Facelet indexing: 54 facelets, ordered U R F D L B, 9 per face, row-major
(row 0 = top, col 0 = left, as seen looking directly at that face with U
up and F towards the viewer). This matches the convention the `kociemba`
package's solve() expects for its facelet string.
"""

FACELET_ORDER = "URFDLB"


def facelet_index(face, row, col):
    return FACELET_ORDER.index(face) * 9 + row * 3 + col


def center_index(face):
    return facelet_index(face, 1, 1)


# Each entry: (slot letters in fixed clockwise-from-outside order,
#              (face, row, col) for each of the 3 facelets, same order).
_CORNER_DEFS = [
    (("U", "R", "F"), [("U", 2, 2), ("R", 0, 0), ("F", 0, 2)]),
    (("U", "F", "L"), [("U", 2, 0), ("F", 0, 0), ("L", 0, 2)]),
    (("U", "L", "B"), [("U", 0, 0), ("L", 0, 0), ("B", 0, 2)]),
    (("U", "B", "R"), [("U", 0, 2), ("B", 0, 0), ("R", 0, 2)]),
    (("D", "F", "R"), [("D", 0, 2), ("F", 2, 2), ("R", 2, 0)]),
    (("D", "L", "F"), [("D", 0, 0), ("L", 2, 2), ("F", 2, 0)]),
    (("D", "B", "L"), [("D", 2, 0), ("B", 2, 2), ("L", 2, 0)]),
    (("D", "R", "B"), [("D", 2, 2), ("R", 2, 2), ("B", 2, 0)]),
]

_EDGE_DEFS = [
    (("U", "R"), [("U", 1, 2), ("R", 0, 1)]),
    (("U", "F"), [("U", 2, 1), ("F", 0, 1)]),
    (("U", "L"), [("U", 1, 0), ("L", 0, 1)]),
    (("U", "B"), [("U", 0, 1), ("B", 0, 1)]),
    (("D", "R"), [("D", 1, 2), ("R", 2, 1)]),
    (("D", "F"), [("D", 0, 1), ("F", 2, 1)]),
    (("D", "L"), [("D", 1, 0), ("L", 2, 1)]),
    (("D", "B"), [("D", 2, 1), ("B", 2, 1)]),
    (("F", "R"), [("F", 1, 2), ("R", 1, 0)]),
    (("F", "L"), [("F", 1, 0), ("L", 1, 2)]),
    (("B", "L"), [("B", 1, 2), ("L", 1, 0)]),
    (("B", "R"), [("B", 1, 0), ("R", 1, 2)]),
]

CORNERS = [
    {"letters": letters, "facelets": tuple(facelet_index(f, r, c) for f, r, c in cells)}
    for letters, cells in _CORNER_DEFS
]

EDGES = [
    {"letters": letters, "facelets": tuple(facelet_index(f, r, c) for f, r, c in cells)}
    for letters, cells in _EDGE_DEFS
]
