cmake_minimum_required(VERSION 3.8)
project(omx_driver)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(dynamixel_sdk REQUIRED)

add_executable(dxl_driver_node
  src/dxl_driver_node.cpp
  src/dxl_bus.cpp
)
target_include_directories(dxl_driver_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(dxl_driver_node
  rclcpp sensor_msgs std_srvs diagnostic_msgs dynamixel_sdk
)

install(TARGETS dxl_driver_node
  DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY config launch udev
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
