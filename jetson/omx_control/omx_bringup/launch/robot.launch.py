"""Real robot bring-up.

    ros2 launch omx_bringup robot.launch.py                       # arm only, mode IDLE
    ros2 launch omx_bringup robot.launch.py camera:=true          # + wrist webcam (usb_cam)
    ros2 launch omx_bringup robot.launch.py port:=/dev/omx_arm dummy_policy:=true

The arm starts with torque OFF in IDLE. Enable with:
    ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: HOME}"
    ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: POLICY}"
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    bringup = get_package_share_directory('omx_bringup')
    desc = get_package_share_directory('omx_description')
    driver = get_package_share_directory('omx_driver')
    perception = get_package_share_directory('omx_perception')

    with open(os.path.join(desc, 'urdf', 'omx_f.urdf'), 'r', encoding='utf-8') as f:
        robot_description = f.read()
    limits = os.path.join(bringup, 'config', 'joint_limits.yaml')
    driver_cfg = os.path.join(driver, 'config', 'omx_f_driver.yaml')
    rviz_cfg = os.path.join(desc, 'rviz', 'omx.rviz')

    port = LaunchConfiguration('port')
    start_mode = LaunchConfiguration('start_mode')
    dummy_policy = LaunchConfiguration('dummy_policy')
    camera = LaunchConfiguration('camera')
    camera_device = LaunchConfiguration('camera_device')
    rviz = LaunchConfiguration('rviz')
    time_scale = LaunchConfiguration('time_scale')

    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='/dev/ttyACM0'),
        DeclareLaunchArgument('start_mode', default_value='IDLE'),
        DeclareLaunchArgument('dummy_policy', default_value='false'),
        DeclareLaunchArgument('camera', default_value='false'),
        DeclareLaunchArgument('camera_device', default_value='/dev/video0'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('time_scale', default_value='2.0'),

        Node(package='omx_driver', executable='dxl_driver_node', name='dxl_driver_node',
             parameters=[driver_cfg, limits, {'mock': False, 'port_name': port}],
             output='screen'),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': robot_description}], output='screen'),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(perception, 'launch', 'camera.launch.py')),
            launch_arguments={'device': camera_device}.items(),
            condition=IfCondition(camera)),
        Node(package='omx_perception', executable='ee_state_node', name='ee_state_node',
             parameters=[limits], output='screen'),

        Node(package='omx_policy', executable='dummy_policy_node', name='policy_node',
             parameters=[{'auto_start': False}], output='screen',
             condition=IfCondition(dummy_policy)),

        Node(package='omx_task_control', executable='action_chunk_executor',
             name='action_chunk_executor',
             parameters=[{'time_scale': ParameterValue(time_scale, value_type=float)}],
             output='screen'),
        Node(package='omx_task_control', executable='ik_node', name='ik_node',
             parameters=[limits], output='screen'),

        Node(package='omx_supervisor', executable='mode_manager', name='mode_manager',
             parameters=[limits, {'start_mode': start_mode}], output='screen'),

        Node(package='rviz2', executable='rviz2', arguments=['-d', rviz_cfg],
             condition=IfCondition(rviz), output='screen'),
    ])
