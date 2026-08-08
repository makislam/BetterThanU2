"""Part 4 — occlusion inference.

Builds a 54-slot facelet model (URFDLB order), takes whatever's known from
the two labeled views, treats every occluded/unlabeled cell as a free
variable, and solves for the rest via constraint propagation + backtracking
over the 8 corner and 12 edge cubie slots (see cube_topology.py for the
fixed structural tables).

Key idea: the 8 valid corner-cubie color combinations and 12 valid
edge-cubie color combinations are just the same 8 corner-letter-patterns
and 12 edge-letter-patterns from cube_topology.py, with each face-letter
substituted for its *observed center color*. A corner/edge slot's actual
colors (in its fixed chirality order) must be some rotation of one of
these fixed combinations, and each combination is used by exactly one
slot (a permutation) — cubies get shuffled and twisted by scrambling, but
the underlying set of 8 (or 12) combinations never changes.
"""

from .cube_topology import CORNERS, EDGES, FACELET_ORDER, center_index

ALL_COLORS = frozenset("WYROBG")
MAX_TRACKED = 200  # cap on enumerated solutions per space, to bound runtime


def _rotations3(triple):
    return [triple, (triple[1], triple[2], triple[0]), (triple[2], triple[0], triple[1])]


def _rotations2(pair):
    return [pair, (pair[1], pair[0])]


def build_face_colors(facelets):
    """Return (face_colors, error) from the 6 center cells. If exactly one
    center is occluded/unlabeled, infer it by elimination (6 colors total,
    5 known and distinct -> the 6th is whichever color is left over).
    """
    known = {}
    missing = []
    for face in FACELET_ORDER:
        value = facelets[center_index(face)]
        if value is None:
            missing.append(face)
        else:
            known[face] = value

    if not missing:
        if len(set(known.values())) != 6:
            return None, f"Center colors are not all distinct: {known}"
        return known, None

    if len(missing) == 1:
        if len(set(known.values())) != 5:
            return None, f"Known centers are not all distinct: {known}"
        remaining = ALL_COLORS - set(known.values())
        if len(remaining) != 1:
            return None, "Could not infer the missing center color unambiguously."
        known[missing[0]] = next(iter(remaining))
        return known, None

    return None, (
        f"Too many unknown centers {missing} — need at least 5 of 6 centers "
        "known to infer the rest."
    )


def _build_domains(slots, valid_sets, facelets, rotations_fn):
    domains = []
    for slot in slots:
        known = [facelets[i] for i in slot["facelets"]]
        candidates = [
            (set_id, rotated)
            for set_id, valid in enumerate(valid_sets)
            for rotated in rotations_fn(valid)
            if all(k is None or k == rotated[j] for j, k in enumerate(known))
        ]
        domains.append(candidates)
    return domains


def _enumerate_assignments(domains, cap):
    """All one-to-one assignments (each valid-set id used at most once
    across slots), up to `cap` results."""
    results = []
    n = len(domains)
    assignment = [None] * n
    used = set()

    def backtrack(i):
        if len(results) >= cap:
            return
        if i == n:
            results.append(list(assignment))
            return
        for set_id, rotated in domains[i]:
            if set_id in used:
                continue
            used.add(set_id)
            assignment[i] = (set_id, rotated)
            backtrack(i + 1)
            used.discard(set_id)
            if len(results) >= cap:
                return

    backtrack(0)
    return results


def solve_facelets(facelets):
    """facelets: list of 54 items, each a color letter or None (unknown/
    occluded). Returns a dict describing one of: unique solution, multiple
    solutions (with the position to observe next), no solution, or a
    setup error (e.g. too many unknown centers).
    """
    face_colors, error = build_face_colors(facelets)
    if error:
        return {"outcome": "error", "message": error}

    corner_valid_sets = [tuple(face_colors[l] for l in c["letters"]) for c in CORNERS]
    edge_valid_sets = [tuple(face_colors[l] for l in e["letters"]) for e in EDGES]

    corner_domains = _build_domains(CORNERS, corner_valid_sets, facelets, _rotations3)
    for slot, domain in zip(CORNERS, corner_domains):
        if not domain:
            known = [facelets[i] for i in slot["facelets"]]
            return {
                "outcome": "no_solution",
                "message": (
                    f"Corner {slot['letters']} has no valid color combination "
                    f"consistent with its known cells {known}."
                ),
            }

    edge_domains = _build_domains(EDGES, edge_valid_sets, facelets, _rotations2)
    for slot, domain in zip(EDGES, edge_domains):
        if not domain:
            known = [facelets[i] for i in slot["facelets"]]
            return {
                "outcome": "no_solution",
                "message": (
                    f"Edge {slot['letters']} has no valid color combination "
                    f"consistent with its known cells {known}."
                ),
            }

    corner_solutions = _enumerate_assignments(corner_domains, MAX_TRACKED)
    edge_solutions = _enumerate_assignments(edge_domains, MAX_TRACKED)

    if not corner_solutions:
        return {
            "outcome": "no_solution",
            "message": "No valid one-to-one assignment of corner cubies to corner slots.",
        }
    if not edge_solutions:
        return {
            "outcome": "no_solution",
            "message": "No valid one-to-one assignment of edge cubies to edge slots.",
        }

    def build_full(corner_solution, edge_solution):
        result = list(facelets)
        for face in FACELET_ORDER:
            result[center_index(face)] = face_colors[face]
        for slot, (_, rotated) in zip(CORNERS, corner_solution):
            for idx, color in zip(slot["facelets"], rotated):
                result[idx] = color
        for slot, (_, rotated) in zip(EDGES, edge_solution):
            for idx, color in zip(slot["facelets"], rotated):
                result[idx] = color
        return result

    total = len(corner_solutions) * len(edge_solutions)
    capped = len(corner_solutions) >= MAX_TRACKED or len(edge_solutions) >= MAX_TRACKED

    if total == 1:
        full = build_full(corner_solutions[0], edge_solutions[0])
        return {"outcome": "unique", "facelets": "".join(full)}

    all_full = []
    for corner_solution in corner_solutions:
        for edge_solution in edge_solutions:
            all_full.append(build_full(corner_solution, edge_solution))
            if len(all_full) >= MAX_TRACKED:
                break
        if len(all_full) >= MAX_TRACKED:
            break

    ambiguous_positions = [i for i in range(54) if len({sol[i] for sol in all_full}) > 1]

    best_position, best_worst_case = None, None
    for pos in ambiguous_positions:
        if facelets[pos] is not None:
            continue  # already observed; only unresolved cells are candidates to observe next
        counts = {}
        for sol in all_full:
            counts[sol[pos]] = counts.get(sol[pos], 0) + 1
        worst_case_remaining = max(counts.values())
        if best_worst_case is None or worst_case_remaining < best_worst_case:
            best_worst_case = worst_case_remaining
            best_position = pos

    return {
        "outcome": "multiple",
        "count": total,
        "capped": capped,
        "ambiguous_positions": ambiguous_positions,
        "recommended_observation": best_position,
        "recommended_worst_case_remaining": best_worst_case,
        "sample_facelets": "".join(all_full[0]),
    }
