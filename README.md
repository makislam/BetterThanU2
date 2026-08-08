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

- **`cube_motor_control`** — drives the 6 Dynamixel face motors over a U2D2. The Dynamixel bus
  protocol (jog + position verification) lives in `motor_driver.py`'s `MotorDriver`, shared by:
  - Node: `keyboard_motor_control` — keyboard teleop. Keys `u/d/l/r/f/b` turn that face CW,
    Shift+key turns CCW, `p` runs a scramble+solve demo, `q`/Ctrl-C quits.
    ```bash
    ros2 run cube_motor_control keyboard_motor_control
    # or launch straight into a demo:
    ros2 run cube_motor_control keyboard_motor_control --ros-args -p demo:=true -p scramble_length:=15
    ```
  - Node: `motor_action_server` — hosts the `/cube_motor_control/execute_solve` action so
    `cube_solver` can drive a solved move list through the motors. Each move is verified against
    the motor's actual position (±20°) before the next is issued; a stuck or slipping motor aborts
    the action instead of jamming the cube.

- **`cube_solver_interfaces`** — `SolveCube.srv` (facelets in, moves out) and `ExecuteSolve.action`
  (move list in, per-move feedback + success/failure out), used by `cube_solver` and
  `cube_motor_control`.

- **`cube_solver`** — turns a captured facelet state into moves via a pluggable algorithm backend,
  and optionally drives them through the motor rig. Backends live in `cube_solver/backends/`
  (`base.py`'s `SolverBackend` interface, `registry.py`'s name→class map) — adding Korf's algorithm
  or another solver later is a new backend class registered there; nothing else changes.
  - Node: `cube_solver_node` — exposes two services (both `cube_solver_interfaces/srv/SolveCube`):
    - `/cube_solver/solve_cube` — solve only, returns the move list.
    - `/cube_solver/solve_and_execute` — solve, then send the moves to
      `motor_action_server`'s `execute_solve` action and report the outcome.

    Leave the request's `facelets` field empty to auto-load the most recently labeled state from
    `cube_vision_tool/dataset` instead of passing a 54-character string by hand:
    ```bash
    ros2 launch cube_solver solve_and_execute.launch.py
    ros2 service call /cube_solver/solve_and_execute cube_solver_interfaces/srv/SolveCube "{}"
    ```
    Requires the `kociemba` pip package for whichever Python `cube_solver_node` runs under
    (system python3, not `cube_vision_tool`'s venv):
    `pip install --user --break-system-packages kociemba` (Debian/Ubuntu's system python3 is
    PEP-668 externally managed, hence the flag).

  - Launch: `cube_pipeline.launch.py` — the full pipeline in one command: `capture_gui.py` (snap
    both the `upper_corner` and `lower_corner` views in one session) → label the upper view →
    label the lower view → bring up `motor_action_server` + `cube_solver_node` → automatically
    call `solve_and_execute`. Each capture/label step is a blocking GUI window from
    `cube_vision_tool`; close it (having saved) to advance to the next step.
    ```bash
    ros2 launch cube_solver cube_pipeline.launch.py
    # or, if cube_vision_tool lives somewhere else:
    ros2 launch cube_solver cube_pipeline.launch.py vision_tool_dir:=/path/to/cube_vision_tool
    ```
    If the final automatic `solve_and_execute` call fires before the motor/solver nodes finish
    starting (slow Dynamixel bus init), just re-run it by hand with the command shown above.

## Build

```bash
cd ros2_ws
colcon build
source install/setup.bash
```

## `cube_vision_tool/` — standalone capture/label/solve tool

A standalone tool (not wired into the ROS 2 stack) for manually building a labeled cube-state
dataset and inferring gripper-occluded stickers via constraint solving. Built because this cube
is stickerless (no dark border between cubies for automatic detection) and the rig's camera
geometry can never be perpendicular to a face. See its
[README](cube_vision_tool/README.md) for setup and usage.
