# Cube Vision Tool

A standalone tool — not wired into the ROS 2 stack — for manually capturing and labeling the
cube's state, and inferring whatever the grippers occlude via constraint solving. It also builds
a labeled dataset (patch crops per color, full sidecar records) for training a real classifier
later.

Why manual labeling instead of automatic detection: this cube is stickerless (cubies are
separated only by a thin painted seam, not a sticker's dark border) and the rig's camera can
never be perpendicular to a face (always an oblique corner view, seeing 3 faces at once, with
the drive shaft permanently blocking part of each face). Automatic detection kept chasing
lighting/exposure noise with no reliable stopping point — this tool sidesteps that with a human
in the loop for labeling, and a solver to fill in what the human can't see.

## Setup

```bash
cd cube_vision_tool
python3 -m venv .venv --system-site-packages   # --system-site-packages picks up apt's PyQt5/opencv/numpy
.venv/bin/pip install -r requirements.txt       # pyrealsense2, kociemba
```

Run every command below with `.venv/bin/python3`, or activate the venv first
(`source .venv/bin/activate`).

## How it works

Two capture slots, `upper_corner` and `lower_corner`, match the rig's actual camera geometry:
each is an oblique view showing 3 faces at once, and together the two views cover all 6 faces.
For each of the 6 faces across both views, you label its 9 stickers by hand (or mark them
occluded) — no color thresholds, no edge detection, 100% manual keypresses. A constraint solver
then fills in anything occluded, using the fixed structural facts of any 3x3 cube (which facelet
positions form each of the 8 corner cubies / 12 edge cubies, and their fixed chirality) combined
with the 6 center colors you actually observed.

### 1. Capture (`capture_gui.py`)

```bash
.venv/bin/python3 capture_gui.py
```

- Live viewfinder from the RealSense camera.
- **Lock Exposure/WB** before capturing anything — auto-exposure/auto-white-balance will
  otherwise shift colors between the two shots and corrupt the dataset. Let the viewfinder run a
  moment first so auto values settle, then lock.
- Enter a free-text lighting tag (e.g. `workshop_overhead_led_night`) so later training can
  account for lighting variation.
- **Snap** each of the two slots once the camera is framed on the right 3 faces. **Retake** to
  redo a slot. Saved as lossless PNG under `dataset/captures/`.

### 2. Label (`label_gui.py`)

```bash
.venv/bin/python3 label_gui.py dataset/captures/<capture>.png --slot upper_corner
```

- Pick the 3 visible faces' letters (U/R/F/D/L/B) in the 3 dropdowns.
- For each face: click its 4 corners in order (top-left, top-right, bottom-right, bottom-left).
  The 3x3 grid overlay appears immediately from those 4 points (bilinear interpolation — no
  assumption that the face is a rectangle, since an oblique view makes it a general
  quadrilateral).
- Click a cell, then press a color key to label it: `y r g o b w` for the 6 colors, `u` for
  unknown/occluded. Selection auto-advances to the next unlabeled cell. Press `z` to undo the
  last label.
- **Save** once all 9 cells of all 3 faces are labeled (occluded cells count as labeled — they're
  just marked unknown for the solver). Writes the JSON sidecar, appends to
  `dataset/master_index.jsonl`, and crops a training patch per non-occluded cell into
  `dataset/patches/<color>/`.
- Repeat for the other slot (`--slot lower_corner`).

`label_latest.py --slot <slot>` finds the most recently captured PNG for that slot under
`dataset/captures/` and opens it in `label_gui.py` directly, so you don't need to know
`capture_gui.py`'s timestamped filename. Used by `cube_solver`'s `cube_pipeline.launch.py` to
chain capture → label without hardcoding paths.

### 3. Solve (`solve_state.py`)

```bash
.venv/bin/python3 solve_state.py
```

Loads the most recent `upper_corner`/`lower_corner` label records (or pass `--upper NAME --lower
NAME` for specific ones), builds the 54-facelet model, and reports one of:

- **Unique solution** — prints the complete 54-character facelet string, then validates it with
  `kociemba` (catches parity errors the constraints above don't, e.g. two swapped edges).
- **Multiple solutions** — prints how many, which facelet positions are still ambiguous, and
  which single position to observe next to best resolve the ambiguity.
- **No solution** — prints which corner/edge slot has no valid color combination, and its known
  cell values, so you know which label is likely wrong.

## Config (`config.yaml`)

Color palette (key → label → display color for overlays), key bindings, capture resolution/fps,
dataset paths, and patch crop size all live here — nothing about color thresholds or detection
tuning, since labeling is entirely manual.

## Dataset layout

```
dataset/
  captures/<timestamp>_<slot>.png       # raw lossless capture
  labels/<name>.json                     # one sidecar per labeled capture
  master_index.jsonl                     # append-only log of every label record
  patches/<color>/<name>_<face><row><col>.png   # cropped sticker patches for classifier training
```
