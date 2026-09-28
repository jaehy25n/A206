"""teach_node on top of a running omx_control stack (mock or real).

    ros2 launch omx_teach teach.launch.py
    ros2 launch omx_teach teach.launch.py recordings_dir:=~/demos
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('recordings_dir', default_value='~/omx_recordings'),
        DeclareLaunchArgument('command_rate_hz', default_value='50.0'),
        Node(
            package='omx_teach',
            executable='teach_node',
            name='teach_node',
            parameters=[{
                'recordings_dir': LaunchConfiguration('recordings_dir'),
                'command_rate_hz': LaunchConfiguration('command_rate_hz'),
            }],
            output='screen',
        ),
    ])
