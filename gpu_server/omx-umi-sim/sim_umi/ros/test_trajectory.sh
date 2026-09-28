#!/bin/bash
# End-to-end proof: FollowJointTrajectory -> JointTrajectoryController
# -> ros2_control -> mujoco_ros2_control -> MuJoCo, and q back out on
# /joint_states. Run the launch file first.
set -e
source /tmp/claude-1003/-home-j-j15a206-universal-manipulation-interface/71c73aef-33b2-49ee-bca8-821148c30e91/scratchpad/ros_env.sh
echo "--- controllers ---"
ros2 control list_controllers
echo "--- joint_states before ---"
timeout 5 ros2 topic echo /joint_states --once | grep -A3 "position"
echo "--- sending a trajectory to arm_controller ---"
ros2 action send_goal /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [joint1, joint2, joint3, joint4, joint5],
    points: [{positions: [0.3, 0.6, -0.5, -0.4, 0.0], time_from_start: {sec: 3}}]}}" \
  2>&1 | tail -5
echo "--- joint_states after ---"
timeout 5 ros2 topic echo /joint_states --once | grep -A3 "position"
echo "--- gripper: close ---"
ros2 action send_goal /gripper_controller/gripper_cmd \
  control_msgs/action/GripperCommand \
  "{command: {position: 0.0, max_effort: 2.0}}" 2>&1 | tail -4
timeout 5 ros2 topic echo /joint_states --once | grep -A3 "position"
