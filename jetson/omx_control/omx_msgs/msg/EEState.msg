# Current end-effector (TCP) state of the robot, computed from /joint_states.
#
# header.frame_id : base_link
# header.stamp    : stamp of the joint_states sample this was computed from
std_msgs/Header header

# T_base_tcp
geometry_msgs/Pose tcp_pose

# Normalised gripper opening: 0 = closed, 1 = open (same definition as the collector)
float32 gripper_width

# Joint positions at the same stamp: joint1..joint5, gripper_joint_1 [rad]
string[] joint_names
float64[] joint_positions
