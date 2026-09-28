"""move_group for the MuJoCo-backed OMX-F, on ROBOTIS's own configuration.

    ros2 launch sim_umi/ros/launch/moveit.launch.py

The SRDF, kinematics.yaml (KDL, position_only_ik), joint_limits.yaml and
moveit_controllers.yaml are ROBOTIS's files, vendored untouched under
sim_umi/ros/config. Only the URDF differs, and only by the <ros2_control>
block that points MoveIt's hardware at our MJCF.
"""
import pathlib

import yaml
from launch import LaunchDescription
from launch_ros.actions import Node

SIM = pathlib.Path(__file__).resolve().parents[2]
CFG = SIM / "ros" / "config"
URDF = SIM / "ros" / "description" / "omx_f_mujoco.urdf"


def load(name):
    return yaml.safe_load((CFG / name).read_text())


def generate_launch_description():
    params = {
        "robot_description": URDF.read_text(),
        "robot_description_semantic": (CFG / "omx_f.srdf").read_text(),
        "robot_description_kinematics": load("kinematics.yaml"),
        "robot_description_planning": load("joint_limits.yaml"),
        "publish_robot_description_semantic": True,
        # OMPL, the default MoveIt pipeline
        "planning_pipelines": ["ompl"],
        "default_planning_pipeline": "ompl",
        "ompl": {
            "planning_plugins": ["ompl_interface/OMPLPlanner"],
            "request_adapters": [
                "default_planning_request_adapters/ResolveConstraintFrames",
                "default_planning_request_adapters/ValidateWorkspaceBounds",
                "default_planning_request_adapters/CheckStartStateBounds",
                "default_planning_request_adapters/CheckStartStateCollision",
            ],
            "response_adapters": [
                "default_planning_response_adapters/AddTimeOptimalParameterization",
                "default_planning_response_adapters/ValidateSolution",
                "default_planning_response_adapters/DisplayMotionPath",
            ],
            "arm": {"planner_configs": ["RRTConnectkConfigDefault"]},
            "planner_configs": {
                "RRTConnectkConfigDefault": {
                    "type": "geometric::RRTConnect", "range": 0.0}},
        },
        # the controllers the trajectories are handed to
        **load("moveit_controllers.yaml"),
        "moveit_manage_controllers": True,
        "trajectory_execution.allowed_execution_duration_scaling": 2.0,
        "trajectory_execution.allowed_goal_duration_margin": 2.0,
        "trajectory_execution.allowed_start_tolerance": 0.05,
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
    }
    return LaunchDescription([
        Node(package="moveit_ros_move_group", executable="move_group",
             output="screen",
             # on the plant's clock, like everything else it talks to
             parameters=[params, {"use_sim_time": True}]),
    ])
