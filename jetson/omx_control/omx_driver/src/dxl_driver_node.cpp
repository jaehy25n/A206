// dxl_driver_node: the only process that talks to the OMX-F motors.
//
//   /joint_command (sensor_msgs/JointState)  -->  [clamp limits, cap velocity]  -->  SyncWrite Goal Position
//   SyncRead Present Position/Velocity/Current --> /joint_states (100 Hz)
//   /dxl_driver/status (diagnostic_msgs/DiagnosticArray, 1 Hz)
//   services: /dxl_driver/set_torque (std_srvs/SetBool), /dxl_driver/reboot (std_srvs/Trigger)
//
// Safety behaviour:
//   * no /joint_command for command_timeout_ms  -> stop writing goals (motors hold)
//   * every target clamped to [lower, upper] limits
//   * goal moves toward the target at most max_velocity_rad_s
//   * torque is OFF at start unless torque_on_start is true
//   * mock:=true replaces the serial bus with a simulated one

#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "diagnostic_msgs/msg/diagnostic_array.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_srvs/srv/set_bool.hpp"
#include "std_srvs/srv/trigger.hpp"

#include "omx_driver/dxl_bus.hpp"

using namespace std::chrono_literals;

namespace omx_driver
{

class DxlDriverNode : public rclcpp::Node
{
public:
  DxlDriverNode()
  : Node("dxl_driver_node")
  {
    // ---------------- parameters ----------------
    port_name_ = declare_parameter<std::string>("port_name", "/dev/ttyACM0");
    baud_rate_ = static_cast<int>(declare_parameter<int64_t>("baud_rate", 1000000));
    mock_ = declare_parameter<bool>("mock", false);
    loop_rate_hz_ = declare_parameter<double>("loop_rate_hz", 100.0);
    command_timeout_ms_ = declare_parameter<double>("command_timeout_ms", 200.0);
    max_velocity_ = declare_parameter<double>("max_velocity_rad_s", 1.5);
    torque_on_start_ = declare_parameter<bool>("torque_on_start", false);
    ticks_per_rev_ = static_cast<double>(declare_parameter<int64_t>("ticks_per_rev", 4096));

    joint_names_ = declare_parameter<std::vector<std::string>>(
      "joint_names", {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"});
    const auto ids = declare_parameter<std::vector<int64_t>>("dxl_ids", {11, 12, 13, 14, 15, 16});
    const auto modes = declare_parameter<std::vector<int64_t>>("operating_modes", {4, 3, 3, 3, 3, 5});
    const auto zero = declare_parameter<std::vector<int64_t>>(
      "zero_ticks", {2048, 2048, 2048, 2048, 2048, 2048});
    const auto dir = declare_parameter<std::vector<int64_t>>("direction", {1, 1, 1, 1, 1, 1});
    lower_ = declare_parameter<std::vector<double>>(
      "lower_limits_rad", {-3.1416, -1.868, -1.571, -1.745, -3.1416, 0.0});
    upper_ = declare_parameter<std::vector<double>>(
      "upper_limits_rad", {3.1416, 1.658, 1.675, 1.745, 3.1416, 1.745});
    const int drive_mode = static_cast<int>(declare_parameter<int64_t>("drive_mode", 4));
    const int profile_velocity = static_cast<int>(declare_parameter<int64_t>("profile_velocity", 50));
    const int profile_acceleration =
      static_cast<int>(declare_parameter<int64_t>("profile_acceleration", 25));
    const int p_gain = static_cast<int>(declare_parameter<int64_t>("position_p_gain", 1000));
    const int d_gain = static_cast<int>(declare_parameter<int64_t>("position_d_gain", 1000));
    const int gripper_goal_current =
      static_cast<int>(declare_parameter<int64_t>("gripper_goal_current", 600));
    const auto mock_init = declare_parameter<std::vector<double>>(
      "mock_initial_positions_rad", {0.0, -1.57, 1.57, 1.57, 0.0, 0.0});
    const double mock_vmax = declare_parameter<double>("mock_max_velocity_rad_s", 3.0);

    n_ = joint_names_.size();
    auto need = [this](size_t sz, const char * what) {
        if (sz != n_) {
          throw std::runtime_error(
                  std::string("parameter '") + what + "' must have " + std::to_string(n_) +
                  " entries (one per joint)");
        }
      };
    need(ids.size(), "dxl_ids");
    need(modes.size(), "operating_modes");
    need(zero.size(), "zero_ticks");
    need(dir.size(), "direction");
    need(lower_.size(), "lower_limits_rad");
    need(upper_.size(), "upper_limits_rad");
    need(mock_init.size(), "mock_initial_positions_rad");

    zero_ticks_.assign(zero.begin(), zero.end());
    direction_.resize(n_);
    for (size_t i = 0; i < n_; ++i) {
      direction_[i] = dir[i] < 0 ? -1.0 : 1.0;
      index_[joint_names_[i]] = i;
      MotorConfig m;
      m.id = static_cast<uint8_t>(ids[i]);
      m.operating_mode = static_cast<uint8_t>(modes[i]);
      m.drive_mode = static_cast<uint8_t>(drive_mode);
      m.profile_velocity = static_cast<uint32_t>(profile_velocity);
      m.profile_acceleration = static_cast<uint32_t>(profile_acceleration);
      m.position_p_gain = static_cast<uint16_t>(p_gain);
      m.position_d_gain = static_cast<uint16_t>(d_gain);
      m.goal_current = (m.operating_mode == 5) ? static_cast<uint16_t>(gripper_goal_current) : 0;
      motors_.push_back(m);
    }
    pos_rad_.assign(n_, 0.0);
    vel_rad_.assign(n_, 0.0);
    eff_.assign(n_, 0.0);
    cmd_rad_.assign(n_, 0.0);
    goal_rad_.assign(n_, 0.0);

    // ---------------- bus ----------------
    if (mock_) {
      std::vector<int32_t> init_ticks(n_);
      for (size_t i = 0; i < n_; ++i) {
        init_ticks[i] = radToTicks(i, mock_init[i]);
      }
      bus_ = makeMockBus(init_ticks, mock_vmax * ticks_per_rev_ / (2.0 * M_PI));
    } else {
      bus_ = makeRealBus(port_name_, baud_rate_);
    }
    std::string err;
    if (!bus_->open(err)) {
      throw std::runtime_error("bus open failed: " + err);
    }
    if (!bus_->configure(motors_, err)) {
      throw std::runtime_error("bus configure failed: " + err);
    }
    RCLCPP_INFO(
      get_logger(), "bus '%s' ready (%s @ %d), %zu joints, loop %.0f Hz, timeout %.0f ms",
      bus_->name(), mock_ ? "mock" : port_name_.c_str(), baud_rate_, n_, loop_rate_hz_,
      command_timeout_ms_);

    // ---------------- ROS interfaces ----------------
    pub_joint_states_ = create_publisher<sensor_msgs::msg::JointState>("/joint_states", 10);
    pub_status_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>("/dxl_driver/status", 10);
    sub_command_ = create_subscription<sensor_msgs::msg::JointState>(
      "/joint_command", 10,
      std::bind(&DxlDriverNode::onCommand, this, std::placeholders::_1));
    srv_torque_ = create_service<std_srvs::srv::SetBool>(
      "/dxl_driver/set_torque",
      std::bind(&DxlDriverNode::onSetTorque, this, std::placeholders::_1, std::placeholders::_2));
    srv_reboot_ = create_service<std_srvs::srv::Trigger>(
      "/dxl_driver/reboot",
      std::bind(&DxlDriverNode::onReboot, this, std::placeholders::_1, std::placeholders::_2));

    const auto period = std::chrono::duration<double>(1.0 / loop_rate_hz_);
    loop_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(period),
      std::bind(&DxlDriverNode::loop, this));
    status_timer_ = create_wall_timer(1s, std::bind(&DxlDriverNode::publishStatus, this));

    if (torque_on_start_) {
      applyTorque(true, err);
    }
  }

  ~DxlDriverNode() override
  {
    std::string err;
    if (bus_ && torque_on_) {
      // Leave the arm holding position: do NOT drop torque on shutdown.
      // Use the set_torque service explicitly when you want it limp.
    }
    if (bus_) {
      bus_->close();
    }
  }

private:
  // ---------------- conversions ----------------
  int32_t radToTicks(size_t i, double rad) const
  {
    return static_cast<int32_t>(std::lround(
             zero_ticks_[i] + direction_[i] * rad * ticks_per_rev_ / (2.0 * M_PI)));
  }
  double ticksToRad(size_t i, int32_t ticks) const
  {
    return direction_[i] * (static_cast<double>(ticks) - zero_ticks_[i]) * 2.0 * M_PI /
           ticks_per_rev_;
  }
  static constexpr double kRawVelToRadS = 0.229 * 2.0 * M_PI / 60.0;  // 0.229 rpm per unit

  // ---------------- main loop ----------------
  void loop()
  {
    std::string err;
    std::vector<MotorState> st;
    if (!bus_->readStates(st, err)) {
      ++read_failures_;
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "read failed: %s", err.c_str());
      return;
    }
    const auto now = this->now();
    sensor_msgs::msg::JointState js;
    js.header.stamp = now;
    js.name = joint_names_;
    js.position.resize(n_);
    js.velocity.resize(n_);
    js.effort.resize(n_);
    for (size_t i = 0; i < n_; ++i) {
      if (st[i].valid) {
        pos_rad_[i] = ticksToRad(i, st[i].position_ticks);
        vel_rad_[i] = direction_[i] * st[i].velocity_raw * kRawVelToRadS;
        eff_[i] = static_cast<double>(st[i].current_raw);
      }
      js.position[i] = pos_rad_[i];
      js.velocity[i] = vel_rad_[i];
      js.effort[i] = eff_[i];
    }
    have_state_ = true;
    pub_joint_states_->publish(js);

    if (!torque_on_ || !have_command_) {
      return;
    }
    const double age_ms = (now - last_command_time_).seconds() * 1000.0;
    if (age_ms > command_timeout_ms_) {
      if (!timeout_warned_) {
        RCLCPP_WARN(
          get_logger(), "no /joint_command for %.0f ms -> holding position", age_ms);
        timeout_warned_ = true;
      }
      return;
    }
    timeout_warned_ = false;

    const double max_step = max_velocity_ / loop_rate_hz_;
    std::vector<int32_t> ticks(n_);
    for (size_t i = 0; i < n_; ++i) {
      const double target = std::clamp(cmd_rad_[i], lower_[i], upper_[i]);
      const double step = std::clamp(target - goal_rad_[i], -max_step, max_step);
      goal_rad_[i] += step;
      ticks[i] = radToTicks(i, goal_rad_[i]);
    }
    if (!bus_->writeGoalPositions(ticks, err)) {
      ++write_failures_;
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "write failed: %s", err.c_str());
    }
  }

  // ---------------- command ----------------
  void onCommand(const sensor_msgs::msg::JointState::SharedPtr msg)
  {
    if (msg->name.size() != msg->position.size()) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 2000, "/joint_command: name/position size mismatch");
      return;
    }
    bool any = false;
    std::vector<double> next = cmd_rad_;
    for (size_t k = 0; k < msg->name.size(); ++k) {
      const auto it = index_.find(msg->name[k]);
      if (it == index_.end()) {
        continue;
      }
      const double v = msg->position[k];
      if (!std::isfinite(v)) {
        RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 2000, "/joint_command: non-finite value for %s, ignored",
          msg->name[k].c_str());
        return;
      }
      next[it->second] = v;
      any = true;
    }
    if (!any) {
      return;
    }
    if (!have_command_) {
      // first command after (re)enable: ramp from where the arm actually is
      goal_rad_ = pos_rad_;
    }
    cmd_rad_ = next;
    have_command_ = true;
    last_command_time_ = now();
  }

  // ---------------- torque / reboot ----------------
  bool applyTorque(bool on, std::string & err)
  {
    if (!bus_->setTorque(on, err)) {
      RCLCPP_ERROR(get_logger(), "set_torque(%d) failed: %s", on, err.c_str());
      return false;
    }
    torque_on_ = on;
    have_command_ = false;     // require fresh commands after every torque change
    timeout_warned_ = false;
    goal_rad_ = pos_rad_;
    RCLCPP_INFO(get_logger(), "torque %s", on ? "ON" : "OFF");
    return true;
  }

  void onSetTorque(
    const std::shared_ptr<std_srvs::srv::SetBool::Request> req,
    std::shared_ptr<std_srvs::srv::SetBool::Response> res)
  {
    std::string err;
    res->success = applyTorque(req->data, err);
    res->message = res->success ? (req->data ? "torque on" : "torque off") : err;
  }

  void onReboot(
    const std::shared_ptr<std_srvs::srv::Trigger::Request>,
    std::shared_ptr<std_srvs::srv::Trigger::Response> res)
  {
    std::string err;
    torque_on_ = false;
    have_command_ = false;
    if (!bus_->reboot(err)) {
      res->success = false;
      res->message = err;
      return;
    }
    std::this_thread::sleep_for(700ms);
    if (!bus_->configure(motors_, err)) {
      res->success = false;
      res->message = "rebooted but reconfigure failed: " + err;
      return;
    }
    res->success = true;
    res->message = "rebooted and reconfigured (torque off)";
  }

  // ---------------- diagnostics ----------------
  void publishStatus()
  {
    diagnostic_msgs::msg::DiagnosticArray arr;
    arr.header.stamp = now();

    diagnostic_msgs::msg::DiagnosticStatus sum;
    sum.name = "dxl_driver";
    sum.hardware_id = mock_ ? "mock" : port_name_;
    sum.level = diagnostic_msgs::msg::DiagnosticStatus::OK;
    sum.message = torque_on_ ? "torque on" : "torque off";
    if (read_failures_ > last_read_failures_) {
      sum.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
      sum.message = "communication errors";
    }
    last_read_failures_ = read_failures_;
    auto kv = [](const std::string & k, const std::string & v) {
        diagnostic_msgs::msg::KeyValue e;
        e.key = k;
        e.value = v;
        return e;
      };
    sum.values.push_back(kv("bus", bus_->name()));
    sum.values.push_back(kv("torque_on", torque_on_ ? "true" : "false"));
    sum.values.push_back(kv("have_command", have_command_ ? "true" : "false"));
    sum.values.push_back(
      kv("command_age_ms",
        have_command_ ? std::to_string((now() - last_command_time_).seconds() * 1000.0) : "n/a"));
    sum.values.push_back(kv("read_failures", std::to_string(read_failures_)));
    sum.values.push_back(kv("write_failures", std::to_string(write_failures_)));
    arr.status.push_back(sum);

    std::vector<MotorState> h;
    std::string err;
    const bool ok = bus_->readHealth(h, err);
    for (size_t i = 0; i < n_; ++i) {
      diagnostic_msgs::msg::DiagnosticStatus s;
      s.name = "dxl_driver/" + joint_names_[i];
      s.hardware_id = "id " + std::to_string(motors_[i].id);
      s.level = diagnostic_msgs::msg::DiagnosticStatus::OK;
      s.message = "ok";
      s.values.push_back(kv("position_rad", std::to_string(pos_rad_[i])));
      if (ok && i < h.size() && h[i].valid) {
        s.values.push_back(kv("temperature_c", std::to_string(h[i].temperature_c)));
        s.values.push_back(kv("voltage_v", std::to_string(h[i].voltage_raw / 10.0)));
        s.values.push_back(kv("hardware_error", std::to_string(h[i].hardware_error)));
        if (h[i].hardware_error != 0) {
          s.level = diagnostic_msgs::msg::DiagnosticStatus::ERROR;
          s.message = "hardware error status " + std::to_string(h[i].hardware_error);
        } else if (h[i].temperature_c >= 65) {
          s.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
          s.message = "hot";
        }
      } else {
        s.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
        s.message = ok ? "no health data" : err;
      }
      arr.status.push_back(s);
    }
    pub_status_->publish(arr);
  }

  // ---------------- members ----------------
  std::string port_name_;
  int baud_rate_{1000000};
  bool mock_{false};
  double loop_rate_hz_{100.0};
  double command_timeout_ms_{200.0};
  double max_velocity_{1.5};
  bool torque_on_start_{false};
  double ticks_per_rev_{4096.0};

  size_t n_{0};
  std::vector<std::string> joint_names_;
  std::map<std::string, size_t> index_;
  std::vector<MotorConfig> motors_;
  std::vector<double> zero_ticks_, direction_, lower_, upper_;
  std::vector<double> pos_rad_, vel_rad_, eff_, cmd_rad_, goal_rad_;

  std::unique_ptr<DxlBus> bus_;
  bool torque_on_{false};
  bool have_state_{false};
  bool have_command_{false};
  bool timeout_warned_{false};
  rclcpp::Time last_command_time_{0, 0, RCL_ROS_TIME};
  uint64_t read_failures_{0}, last_read_failures_{0}, write_failures_{0};

  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr pub_joint_states_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr pub_status_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr sub_command_;
  rclcpp::Service<std_srvs::srv::SetBool>::SharedPtr srv_torque_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr srv_reboot_;
  rclcpp::TimerBase::SharedPtr loop_timer_, status_timer_;
};

}  // namespace omx_driver

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  int rc = 0;
  try {
    auto node = std::make_shared<omx_driver::DxlDriverNode>();
    rclcpp::spin(node);
  } catch (const std::exception & e) {
    RCLCPP_FATAL(rclcpp::get_logger("dxl_driver_node"), "%s", e.what());
    rc = 1;
  }
  rclcpp::shutdown();
  return rc;
}
