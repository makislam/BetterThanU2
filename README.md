# BetterThanU2

A ROS 2 rig that reads and solves a Rubik's Cube: two fixed RealSense D405 cameras read the
cube's full 54-sticker state, and 6 Dynamixel motors — one per face — turn the cube without
ever reorienting its body.

## Packages (`ros2_ws/src/`)

- **`cube_state_detector`** — reads the cube's state from the two cameras and returns a
  54-color string ready for a solver. Does not solve the cube itself. See its
  [README](ros2_ws/src/cube_state_detector/README.md) for calibration and running instructions.
  - Node: `cube_state_node`

- **`cube_state_interfaces`** — the `CapturePosition` and `GetCubeState` service definitions
  used by `cube_state_detector`.

- **`cube_motor_control`** — keyboard teleop for the 6 Dynamixel face motors over a U2D2. Jog
  any face 90° CW/CCW, or run a scramble-then-solve demo. Each move is verified against the
  motor's actual position (±20°) before the next move is issued, so a stuck or slipping motor
  stops the sequence instead of jamming the cube.
  - Node: `keyboard_motor_control` — keys `u/d/l/r/f/b` turn that face CW, Shift+key turns CCW,
    `p` runs a scramble+solve demo, `q`/Ctrl-C quits.
    ```bash
    ros2 run cube_motor_control keyboard_motor_control
    # or launch straight into a demo:
    ros2 run cube_motor_control keyboard_motor_control --ros-args -p demo:=true -p scramble_length:=15
    ```

## Build

```bash
cd ros2_ws
colcon build
source install/setup.bash
```
