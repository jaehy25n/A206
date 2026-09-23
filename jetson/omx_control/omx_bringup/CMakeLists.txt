cmake_minimum_required(VERSION 3.8)
project(omx_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)
install(PROGRAMS
  scripts/graph_dump.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
