"""Persists in-progress ExecuteSolve move lists to disk, so a partial solve
survives a failed move (a motor slip aborts the goal, see
motor_action_server.py) or even a node crash/restart - the next
solve_and_execute call can finish the remaining moves instead of either
re-solving from a stale vision capture (wrong: the physical cube has
already had `completed` moves applied to it) or leaving the cube stuck
mid-solve with no record of where it left off.
"""

import json
from pathlib import Path

PENDING_SOLVE_PATH = Path.home() / ".cube_motor_control" / "pending_solve.json"


def save_pending(moves, completed, facelets_hash=None):
    PENDING_SOLVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PENDING_SOLVE_PATH, "w") as f:
        json.dump(
            {"moves": list(moves), "completed": completed, "facelets_hash": facelets_hash}, f
        )


def load_pending():
    """Returns {"moves": [...], "completed": int, "facelets_hash": str|None}
    for an unfinished solve, or None if there isn't one. facelets_hash
    identifies the cube state the plan was computed for - the caller should
    refuse to resume (and re-solve instead) if the cube's current facelets
    hash to something else, since that means the plan no longer matches
    reality (a comm error left a move unverified, someone touched the cube,
    etc). Missing on files written before this field existed."""
    if not PENDING_SOLVE_PATH.exists():
        return None
    with open(PENDING_SOLVE_PATH) as f:
        data = json.load(f)
    if data["completed"] >= len(data["moves"]):
        return None
    data.setdefault("facelets_hash", None)
    return data


def clear_pending():
    PENDING_SOLVE_PATH.unlink(missing_ok=True)
