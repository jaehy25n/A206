# Supervisor (mode_manager) state.
std_msgs/Header header

# One of: IDLE, HOME, POLICY, TELEOP, STOP
string mode

bool torque_enabled
bool e_stop

# Milliseconds since the last policy heartbeat (negative = never received)
float32 policy_age_ms

# Human readable reason for the last transition
string reason
