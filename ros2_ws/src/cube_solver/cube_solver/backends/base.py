"""Pluggable interface for cube-solving algorithms.

Each backend takes a 54-character facelet string (URFDLB order, one of
W/Y/R/O/B/G per cell — same convention cube_vision_tool/solve_state.py
already validates with) and returns a list of moves in standard cube
notation (e.g. ["U", "R'", "F2", ...]). Adding a new algorithm (Korf's,
etc.) later means adding a class here and registering it in registry.py —
solver_node.py itself never changes.
"""

from abc import ABC, abstractmethod


class SolverBackend(ABC):
    @abstractmethod
    def solve(self, facelets):
        """facelets: 54-char string, URFDLB order. Returns a list of move
        strings. Raises ValueError if the facelets are invalid/unsolvable."""
