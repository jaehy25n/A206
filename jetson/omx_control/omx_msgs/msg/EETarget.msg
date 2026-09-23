# Instantaneous end-effector target produced by the action chunk executor
# (interpolated along the active chunk at the control rate).
#
# header.frame_id : base_link
std_msgs/Header header

# Desired T_base_tcp
geometry_msgs/Pose pose

# Desired normalised gripper width 0..1
float32 gripper_width

# header.stamp of the EEActionChunk being executed
builtin_interfaces/Time chunk_stamp

# 0..1 progress along that chunk
float32 progress
