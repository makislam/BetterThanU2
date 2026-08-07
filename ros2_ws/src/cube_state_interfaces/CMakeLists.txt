cmake_minimum_required(VERSION 3.8)
project(cube_state_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/CapturePosition.srv"
  "srv/GetCubeState.srv"
)

ament_package()
