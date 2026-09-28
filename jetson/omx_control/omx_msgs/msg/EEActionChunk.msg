# One policy output: H end-effector poses RELATIVE to the anchor pose, plus H
# ABSOLUTE gripper widths.  Same meaning as the GPU handoff contract's [16, 10]
# action (gpu_server/omx-umi-sim/README_JETSON_HANDOFF.md, sections 3-4).
#
# header.stamp    : t0, time of the last observation the chunk was predicted from
# header.frame_id : base_link (frame of anchor_pose)
std_msgs/Header header

# T_base_tcp at t0. Every delta below is expressed in this frame:
#   T_target_k = anchor_pose * deltas[k]
geometry_msgs/Pose anchor_pose

# Time between consecutive steps [s] (0.1 in the contract). Step k is meant for
# t0 + k*dt, so step 0 is the pose the arm was in at t0 (an alignment reference).
float32 dt

# H relative poses (position [m], rotation as quaternion)
geometry_msgs/Pose[] deltas

# H gripper jaw widths [m]. ABSOLUTE, not relative, not normalised.
float32[] gripper_width

# Optional model confidence 0..1 (0 = unknown)
float32 confidence
