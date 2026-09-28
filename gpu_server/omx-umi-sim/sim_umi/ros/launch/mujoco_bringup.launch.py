"""ros2_control on top of the MuJoCo scene, with ROBOTIS's controllers.

    ros2 launch sim_umi/ros/launch/mujoco_bringup.launch.py

Starts mujoco_ros2_control's ros2_control_node (the controller manager whose
hardware IS our MJCF), then the joint_state_broadcaster and the two
controllers MoveIt expects to find.
"""
import os
import pathlib

from launch import LaunchDescription
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch_ros.actions import Node

SIM = pathlib.Path(__file__).resolve().parents[2]
URDF = SIM / "ros" / "description" / "omx_f_mujoco.urdf"
CONTROLLERS = SIM / "ros" / "config" / "controllers.yaml"
# The plant's plugins. Default: the asynchronous evaluators' file, unchanged. The DSE runs
# with OMX_MUJOCO_PLUGINS=sim_umi/ros/config/mujoco_plugins_dse.yaml (sim-state camera
# trigger + joint snapshot).
PLUGINS = pathlib.Path(os.environ.get("OMX_MUJOCO_PLUGINS", SIM / "ros" / "config" / "mujoco_plugins.yaml"))


def generate_launch_description():
    description = {"robot_description": URDF.read_text()}
    # The plant publishes /clock and stamps its camera on the simulation
    # clock; the controller manager stamped /joint_states on the system clock.
    # Two halves of one observation on two clocks cannot be lined up except by
    # assuming a constant between them, and a constant is exactly what a
    # real-time factor that wanders, a stall or a reset takes away. So
    # everything here runs on the plant's clock.
    sim_time = {"use_sim_time": True}

    control = Node(
        package="mujoco_ros2_control",
        executable="ros2_control_node",
        parameters=[description, str(CONTROLLERS), str(PLUGINS), sim_time],
        output="screen",
    )
    state_pub = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        parameters=[description, sim_time],
        output="screen",
    )

    def spawner(name, after=None):
        node = Node(package="controller_manager", executable="spawner",
                    arguments=[name, "--controller-manager", "/controller_manager"],
                    output="screen")
        return node if after is None else RegisterEventHandler(
            OnProcessExit(target_action=after, on_exit=[node]))

    jsb = spawner("joint_state_broadcaster")
    arm = spawner("arm_controller", after=jsb)
    grip = spawner("gripper_controller", after=jsb)
    return LaunchDescription([control, state_pub, jsb, arm, grip])
