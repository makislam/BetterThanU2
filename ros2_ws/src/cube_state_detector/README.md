# Cube State Detector

This ROS 2 package reads the full state of a Rubik's Cube using RealSense
D405 cameras. It does not solve the cube. It only reads the 6 faces and
gives back a 54-color string, ready for a solver to use later.

## How it works

The cube body never moves in this rig — each face spins in place on its own
motor, and nothing ever rotates a new face toward a camera. So no fixed
camera position sees more than half the cube. Instead, this node captures
one face at a time, straight-on: reposition a camera (or the cube) so
exactly one face fills the frame, capture it, then move to the next face.
Which physical face is at which camera topic is set in `config/roi.yaml`,
under `positions` (keyed `U`/`R`/`F`/`D`/`L`/`B`).

The cube is stickerless — cubies are separated only by a thin painted
seam, not a sticker's dark border, too low-contrast to reliably find each
of the 9 individual cubie squares by edge detection. So instead, each
capture finds the *outer* boundary of the whole face (a strong,
high-contrast edge against the background, see `sticker_detect.py`),
perspective-corrects it, and divides it into a 3x3 grid geometrically — the
9 cell colors are sampled directly, with no dependency on detecting the
faint internal seams at all. This means each face needs to be framed
roughly straight-on (not at a steep oblique angle) so the perspective
correction holds up.

The 9th cell — the center — is never sampled. A motor's drive shaft passes
through the center of whatever face it turns, so it's permanently occluded
from every camera angle on this rig. That's not a problem: a face's center
color is a fixed rig fact, not something that can ever change, so it's
read from `config/motor_faces.yaml` instead of the camera.

For each face:

1. Frame that one face straight-on to a camera.
2. The robot calls the `capture_position` service with that face's letter
   (e.g. `U`).
3. The node reads the latest image, finds the face square, and reads its
   3x3 grid in one shot.

After all 6 faces have been captured, the robot calls `get_cube_state`.
This returns one 54-character string: 9 letters per face, in `U R F D L B`
order. Each letter is one of:

- `W` white
- `Y` yellow
- `R` red
- `O` orange
- `B` blue
- `G` green

`config/motor_faces.yaml` documents the fixed motor → color → face mapping
for this rig (motor 1 = yellow = whichever face that is, etc.). It's not
read by this node — it's the reference for whatever robot code drives the
motors, kept next to the vision config since both describe the same
physical layout.

## Install

```bash
sudo apt install ros-jazzy-realsense2-camera ros-jazzy-cv-bridge python3-yaml
```

## Build

From the workspace root (`ros2_ws/`):

```bash
colcon build --packages-select cube_state_interfaces cube_state_detector
source install/setup.bash
```

## Run

```bash
ros2 launch cube_state_detector cube_state.launch.py
```

This starts both camera drivers and the cube state node together. Fill in
each camera's `serial_no` in `launch/cube_state.launch.py` first
(`rs-enumerate-devices` lists them) so `camera_a` and `camera_b` map to the
right physical device.

## Calibrate the rig (do this once per setup)

The detection tuning in `config/roi.yaml`, the face letters in
`config/motor_faces.yaml`, and the default colors in `config/colors.yaml`
are only starting guesses. Do this before real use:

1. With the node running, frame one face straight-on and open the debug
   image:
   ```bash
   ros2 run rqt_image_view rqt_image_view
   ```
   Pick topic `/cube_state/debug_image/<face>` (e.g. `/U`). If no face
   square was found yet, you'll see the raw camera frame — reposition until
   the whole face fills it. Once found, the debug image shows the
   perspective-corrected face with green grid lines and each cell's
   classified color letter. The center cell shows a magenta `(letter)` —
   that's the known center color from `config/motor_faces.yaml`, not a
   detection, since the center is always occluded by the drive shaft.

2. **Detection tuning.** If the debug image keeps showing the raw frame
   (no face square found) even with the face filling it, adjust
   `config/roi.yaml`'s `detection:` block — `min_face_area`/`max_face_area`
   to match how big the whole face actually is in pixels at your typical
   camera distance, `canny_low`/`canny_high` if the face's outer edge
   against the background is too faint or too noisy, `aspect_ratio_tolerance`
   if a valid squarish face is being rejected.

3. **Face identity, once per camera setup.** Decide which physical face
   you'll present for each of the 6 letters and set `image_topic` per face
   in `config/roi.yaml`'s `positions:` (which camera you're using, if you
   have a choice). Also make sure `config/motor_faces.yaml`'s `face:`
   values match your rig's actual U/R/F/D/L/B assignment.

4. **Colors.** In `config/colors.yaml`, point each of the 6 known colors at
   the camera in turn and check the label the debug image shows. If wrong,
   adjust that color's HSV numbers (hue matters most). Lighting can vary
   shot to shot with a moved camera — if calibration doesn't hold up across
   a few different repositionings, loosen up which references you
   calibrate against (e.g. average a few readings per color) rather than
   tuning to one single shot.

5. Restart the node after any config change and check again.

## Try it by hand

Call the services directly to check everything works, before wiring in
the robot:

```bash
# Frame each face straight-on and capture it, one at a time
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'U'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'R'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'F'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'D'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'L'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'B'}"

# After all 6 faces are captured
ros2 service call /cube_state/get_cube_state cube_state_interfaces/srv/GetCubeState "{}"
```

A correct result has `complete: true` and a 54-character string with
exactly 9 of each of the 6 letters. If a letter count is not 9, the node
logs a warning — check the grid position and the color calibration.

## What this package does NOT do

- It does not solve the cube.
- It does not control the robot or turn the cube's faces. Your robot code
  calls `capture_position` after the faces are in a known state.
