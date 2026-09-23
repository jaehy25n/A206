"""Whole stack without hardware: mock driver + dummy policy.

    ros2 launch omx_bringup mock.launch.py
    ros2 launch omx_bringup mock.launch.py rviz:=true
    ros2 launch omx_bringup mock.launch.py dummy_policy:=false start_mode:=IDLE

Then, e.g.:
    ros2 topic echo /mode_state
    ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: HOME}"
    ros2 topic pub -1 /e_stop std_msgs/msg/Bool "{data: true}"
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    bringup = get_package_share_directory('omx_bringup')
    desc = get_package_share_directory('omx_description')
    driver = get_package_share_directory('omx_driver')

    with open(os.path.join(desc, 'urdf', 'omx_f.urdf'), 'r', encoding='utf-8') as f:
        robot_description = f.read()
    limits = os.path.join(bringup, 'config', 'joint_limits.yaml')
    driver_cfg = os.path.join(driver, 'config', 'omx_f_driver.yaml')
    rviz_cfg = os.path.join(desc, 'rviz', 'omx.rviz')

    start_mode = LaunchConfiguration('start_mode')
    dummy_policy = LaunchConfiguration('dummy_policy')
    rviz = LaunchConfiguration('rviz')
    time_scale = LaunchConfiguration('time_scale')

    return LaunchDescription([
        DeclareLaunchArgument('start_mode', default_value='POLICY'),
        DeclareLaunchArgument('dummy_policy', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('time_scale', default_value='1.0'),

        # A. driver (mock bus) + robot_state_publisher
        Node(package='omx_driver', executable='dxl_driver_node', name='dxl_driver_node',
             parameters=[driver_cfg, limits, {'mock': True}], output='screen'),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': robot_description}], output='screen'),

        # B. perception (no camera in mock)
        Node(package='omx_perception', executable='ee_state_node', name='ee_state_node',
             parameters=[limits], output='screen'),

        # C. policy
        Node(package='omx_policy', executable='dummy_policy_node', name='policy_node',
             parameters=[{'auto_start': True}], output='screen',
             condition=IfCondition(dummy_policy)),

        # D. task space -> joint space
        Node(package='omx_task_control', executable='action_chunk_executor',
             name='action_chunk_executor',
             parameters=[{'time_scale': ParameterValue(time_scale, value_type=float)}],
             output='screen'),
        Node(package='omx_task_control', executable='ik_node', name='ik_node',
             parameters=[limits], output='screen'),

        # E. supervisor
        Node(package='omx_supervisor', executable='mode_manager', name='mode_manager',
             parameters=[limits, {'start_mode': start_mode}], output='screen'),

        # F. visualisation
        Node(package='rviz2', executable='rviz2', arguments=['-d', rviz_cfg],
             condition=IfCondition(rviz), output='screen'),
    ])
