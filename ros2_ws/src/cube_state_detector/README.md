# Cube State Detector

This ROS 2 package reads the full state of a Rubik's Cube using two fixed
RealSense D405 cameras. It does not solve the cube. It only reads the 6
faces and gives back a 54-color string, ready for a solver to use later.

## How it works

The cube body never moves in this rig — each face spins in place on its own
motor, and nothing ever rotates a new face toward a camera. So instead of
one camera seeing every face in turn, two cameras are used so that together
they see all 6 faces at once: each camera sees 3 faces (which ones is set
in `config/roi.yaml`, under `position_a` / `position_b`).

Cameras can be repositioned before every capture — there's no fixed pixel
ROI. Instead, each capture detects the 9 stickers of each visible face
directly in the image (contour shape + size, see `sticker_detect.py`),
groups them into faces, and works out row/column order even if the face is
tilted. This only breaks if a camera's view is flipped to a drastically
different angle than usual (see step 2 below) — ordinary repositioning,
zoom, or tilt is fine.

For each camera position:

1. The robot calls the `capture_position` service with that position's id
   (`position_a` or `position_b`).
2. The node reads the latest image from that camera and reads all 3 faces
   visible in it — a 3x3 grid per face — in one shot.

After both positions have been captured (6 faces total), the robot calls
`get_cube_state`. This returns one 54-character string: 9 letters per face,
in `U R F D L B` order. Each letter is one of:

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

The detection tuning and face ordering in `config/roi.yaml`, the face
letters in `config/motor_faces.yaml`, and the default colors in
`config/colors.yaml` are only starting guesses. Do this before real use:

1. With the node running, open the debug image for each camera:
   ```bash
   ros2 run rqt_image_view rqt_image_view
   ```
   Pick topic `/cube_state/debug_image/position_a` or `/position_b`. Every
   contour that looks sticker-shaped is drawn: red if it wasn't grouped
   into a detected face, green (with its classified color letter) if it
   was.

2. **Detection tuning.** If real stickers show up red (not detected) or
   you see lots of red noise from the background, adjust
   `config/roi.yaml`'s `detection:` block — `min_sticker_area` /
   `max_sticker_area` to match how big a sticker actually is in pixels at
   your typical camera distance, `canny_low`/`canny_high` if edges are
   too faint or too noisy, `cluster_distance_factor` if 3 faces are
   merging into one group or one face is splitting into two.

3. **Face identity, once per camera position.** Look at which physical
   face sits in each of the 3 slots visible to that camera in a typical
   framing and decide the permanent U/R/F/D/L/B assignment for your rig —
   this only needs doing once, since the cube itself never reorients, only
   the cameras move around it. Update the `faces:` list order in
   `config/roi.yaml` (top-to-bottom, left-to-right as they appear) and the
   `face:` values in `config/motor_faces.yaml` to match.

4. **Colors.** In `config/colors.yaml`, point each of the 6 known colors at
   either camera in turn and check the label the debug image shows. If
   wrong, adjust that color's HSV numbers (hue matters most). Lighting can
   vary shot to shot with a moved camera — if calibration doesn't hold up
   across a few different repositionings, loosen up which references you
   calibrate against (e.g. average a few readings per color) rather than
   tuning to one single shot.

5. Restart the node after any config change and check again.

## Try it by hand

Call the services directly to check everything works, before wiring in
the robot:

```bash
# Capture the 3 faces visible from each camera
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'position_a'}"
ros2 service call /cube_state/capture_position cube_state_interfaces/srv/CapturePosition "{position_id: 'position_b'}"

# After both positions are captured
ros2 service call /cube_state/get_cube_state cube_state_interfaces/srv/GetCubeState "{}"
```

A correct result has `complete: true` and a 54-character string with
exactly 9 of each of the 6 letters. If a letter count is not 9, the node
logs a warning — check the grid position and the color calibration.

## What this package does NOT do

- It does not solve the cube.
- It does not control the robot or turn the cube's faces. Your robot code
  calls `capture_position` after the faces are in a known state.
