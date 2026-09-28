"""Stand-alone driver launch.

    ros2 launch omx_driver driver.launch.py                 # real bus, /dev/ttyACM0
    ros2 launch omx_driver driver.launch.py mock:=true      # no hardware
    ros2 launch omx_driver driver.launch.py port:=/dev/omx_arm
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory('omx_driver'), 'config', 'omx_f_driver.yaml')
    mock = LaunchConfiguration('mock')
    port = LaunchConfiguration('port')

    return LaunchDescription([
        DeclareLaunchArgument('mock', default_value='false'),
        DeclareLaunchArgument('port', default_value='/dev/ttyACM0'),
        Node(
            package='omx_driver',
            executable='dxl_driver_node',
            name='dxl_driver_node',
            parameters=[
                cfg,
                {'mock': ParameterValue(mock, value_type=bool),
                 'port_name': port},
            ],
            output='screen',
        ),
    ])
