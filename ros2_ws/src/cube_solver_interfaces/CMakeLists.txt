cmake_minimum_required(VERSION 3.8)
project(cube_solver_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SolveCube.srv"
  "action/ExecuteSolve.action"
  DEPENDENCIES action_msgs
)

ament_package()
