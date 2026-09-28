# Live per-motor telemetry from dxl_driver_node (10 Hz). All arrays are indexed by joint.
# Use it to see how hard each motor is working while the stack runs:
#   ros2 topic echo /dxl_driver/motor_state --field pwm_percent
std_msgs/Header header
string[] joint_names
uint8[] ids
bool torque_enabled

float64[] goal_rad            # last goal written by the driver (0 when no command yet)
float64[] present_rad
float64[] error_deg           # (commanded - present) in degrees, 0 when no command

float32[] pwm_percent         # Present PWM / 885 * 100, signed. XL430: > ~45 % sustained trips Overload
int16[] load_raw              # XL430: Present Load [0.1 %], XL330: Present Current [mA]
float32[] voltage_v           # Present Input Voltage (refreshed at 1 Hz)
uint8[] temperature_c         # Present Temperature (refreshed at 1 Hz), shutdown at 72 C
uint8[] hardware_error        # Hardware Error Status bits: 1 voltage, 4 heat, 8 encoder, 16 shock, 32 overload
string[] hardware_error_text

float32[] gravity_nm          # model gravity torque about each joint at the commanded pose (joints 2-4, else 0)
float64[] offset_rad          # sag compensation currently added to the command per joint
