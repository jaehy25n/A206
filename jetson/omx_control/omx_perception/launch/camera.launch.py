"""Wrist webcam via usb_cam.

    ros2 launch omx_perception camera.launch.py device:=/dev/wrist_cam

Requires: sudo apt install ros-humble-usb-cam
Publishes /wrist_camera/image_raw, /wrist_camera/camera_info, /wrist_camera/image_raw/compressed
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory('omx_perception'), 'config', 'wrist_camera.yaml')
    device = LaunchConfiguration('device')
    return LaunchDescription([
        DeclareLaunchArgument('device', default_value='/dev/video0'),
        Node(
            package='usb_cam',
            executable='usb_cam_node_exe',
            name='wrist_camera',
            namespace='wrist_camera',
            parameters=[cfg, {'video_device': device}],
            remappings=[
                ('image_raw', '/wrist_camera/image_raw'),
                ('image_raw/compressed', '/wrist_camera/image_raw/compressed'),
                ('camera_info', '/wrist_camera/camera_info'),
            ],
            output='screen',
        ),
    ])
