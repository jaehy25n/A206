"""Show the OMX-F URDF in RViz with a joint slider GUI (no hardware needed).

    ros2 launch omx_description display.launch.py
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('omx_description')
    with open(os.path.join(share, 'urdf', 'omx_f.urdf'), 'r', encoding='utf-8') as f:
        robot_description = f.read()
    rviz_config = os.path.join(share, 'rviz', 'omx.rviz')

    return LaunchDescription([
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            parameters=[{'robot_description': robot_description}],
            output='screen',
        ),
        Node(
            package='joint_state_publisher_gui',
            executable='joint_state_publisher_gui',
            output='screen',
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            arguments=['-d', rviz_config],
            output='screen',
        ),
    ])
