# Current end-effector (TCP) state of the robot, computed from /joint_states.
#
# header.frame_id : base_link
# header.stamp    : stamp of the joint_states sample this was computed from
std_msgs/Header header

# T_base_tcp
geometry_msgs/Pose tcp_pose

# Gripper jaw width [m], the unit of the policy's action[9] (robot0_gripper_width)
float32 gripper_width

# Joint positions at the same stamp: joint1..joint5, gripper_joint_1 [rad]
string[] joint_names
float64[] joint_positions
