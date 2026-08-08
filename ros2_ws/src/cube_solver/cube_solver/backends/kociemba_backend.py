import kociemba

from .base import SolverBackend

FACE_ORDER = "URFDLB"
CENTER_INDICES = {face: i * 9 + 4 for i, face in enumerate(FACE_ORDER)}


def _colors_to_face_letters(facelets):
    """kociemba.solve() expects each cell written as the face letter whose
    center shares its color (e.g. all cells matching the U-face's observed
    center color become 'U') - not our W/Y/R/O/B/G color letters. Build that
    color->face mapping from the 6 known centers, then translate."""
    color_to_face = {}
    for face, idx in CENTER_INDICES.items():
        color = facelets[idx]
        if color in color_to_face:
            raise ValueError(
                f"centers for faces {color_to_face[color]!r} and {face!r} both read "
                f"as color '{color}' - check color labeling/calibration."
            )
        color_to_face[color] = face

    try:
        return "".join(color_to_face[c] for c in facelets)
    except KeyError as exc:
        raise ValueError(f"facelet color {exc} doesn't match any of the 6 centers' colors") from exc


class KociembaBackend(SolverBackend):
    """Two-phase algorithm, via the same `kociemba` package
    cube_vision_tool/solve_state.py already uses to validate a captured
    state."""

    def solve(self, facelets):
        face_letters = _colors_to_face_letters(facelets)
        try:
            solution = kociemba.solve(face_letters)
        except Exception as exc:
            raise ValueError(f"kociemba could not solve facelets '{facelets}': {exc}") from exc
        return solution.split()
