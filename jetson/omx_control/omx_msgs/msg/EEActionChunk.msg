# One policy output: H future end-effector poses RELATIVE to the anchor pose,
# plus H ABSOLUTE gripper widths (UMI-style action chunk).
#
# header.stamp    : observation time t0 the chunk was predicted from
# header.frame_id : base_link (frame of anchor_pose)
std_msgs/Header header

# T_base_tcp at t0. Every delta below is expressed in this frame:
#   T_target_k = anchor_pose * deltas[k]
geometry_msgs/Pose anchor_pose

# Time between consecutive steps [s]. Step k is meant for t0 + (k+1)*dt.
float32 dt

# H relative poses (position [m], rotation as quaternion)
geometry_msgs/Pose[] deltas

# H normalised gripper widths, 0 = closed .. 1 = open. ABSOLUTE, not relative.
float32[] gripper_width

# Optional model confidence 0..1 (0 = unknown)
float32 confidence
