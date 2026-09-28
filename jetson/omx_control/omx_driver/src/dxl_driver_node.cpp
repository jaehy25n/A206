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
#include "omx_msgs/msg/motor_state.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_srvs/srv/set_bool.hpp"
#include "std_srvs/srv/trigger.hpp"

#include "omx_driver/dxl_bus.hpp"
#include "omx_driver/gravity_model.hpp"

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
    // Motor position PID gains, one per joint. Register units: P/128, I/65536, D/16.
    // I > 0 removes the steady-state sag under gravity that P-only control leaves.
    const auto p_gains = declare_parameter<std::vector<int64_t>>(
      "position_p_gains", {1000, 1000, 1000, 1000, 1000, 1000});
    const auto i_gains = declare_parameter<std::vector<int64_t>>(
      "position_i_gains", {0, 0, 0, 0, 0, 0});
    const auto d_gains = declare_parameter<std::vector<int64_t>>(
      "position_d_gains", {1000, 1000, 1000, 1000, 1000, 1000});
    const int gripper_goal_current =
      static_cast<int>(declare_parameter<int64_t>("gripper_goal_current", 600));
    const auto mock_init = declare_parameter<std::vector<double>>(
      "mock_initial_positions_rad", {0.0, -1.57, 1.57, 1.57, 0.0, 0.0});
    const double mock_vmax = declare_parameter<double>("mock_max_velocity_rad_s", 3.0);
    reboot_on_hw_error_ = declare_parameter<bool>("reboot_on_hardware_error", true);
    // Feed-forward sag compensation: added to every command before it becomes the
    // motor goal. Set it to the steady-state /dxl_driver/tracking_error measured at
    // the working pose with offsets = 0 (P-only gains, arm resting on gear friction).
    goal_offset_ = declare_parameter<std::vector<double>>(
      "goal_offset_rad", {0.0, 0.0, 0.0, 0.0, 0.0, 0.0});
    // Model-based part: offset_j -= compliance_j * gravity_torque_j(q_cmd). Identify the
    // compliances with `ros2 run omx_driver fit_sag.py`. 0 = constant offsets only.
    compliance_ = declare_parameter<std::vector<double>>(
      "sag_compliance_rad_per_nm", {0.0, 0.0, 0.0, 0.0, 0.0, 0.0});
    const double payload_mass = declare_parameter<double>("payload_mass_kg", 0.0);
    const auto payload_xyz = declare_parameter<std::vector<double>>(
      "payload_offset_xyz", {0.015, 0.0, 0.04});   // wrist camera + mount, in the link5 frame
    if (payload_xyz.size() != 3) {
      throw std::runtime_error("payload_offset_xyz must have 3 entries");
    }
    gravity_ = std::make_unique<GravityModel>(
      payload_mass, std::array<double, 3>{payload_xyz[0], payload_xyz[1], payload_xyz[2]});

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
    need(goal_offset_.size(), "goal_offset_rad");
    need(compliance_.size(), "sag_compliance_rad_per_nm");
    need(p_gains.size(), "position_p_gains");
    need(i_gains.size(), "position_i_gains");
    need(d_gains.size(), "position_d_gains");

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
      m.position_p_gain = static_cast<uint16_t>(p_gains[i]);
      m.position_i_gain = static_cast<uint16_t>(i_gains[i]);
      m.position_d_gain = static_cast<uint16_t>(d_gains[i]);
      m.goal_current = (m.operating_mode == 5) ? static_cast<uint16_t>(gripper_goal_current) : 0;
      motors_.push_back(m);
    }
    pos_rad_.assign(n_, 0.0);
    vel_rad_.assign(n_, 0.0);
    eff_.assign(n_, 0.0);
    pwm_raw_.assign(n_, 0);
    last_health_.assign(n_, MotorState{});
    gravity_nm_.assign(n_, 0.0);
    offset_applied_.assign(n_, 0.0);
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
    std::string err, warn;
    if (!bus_->open(err)) {
      throw std::runtime_error("bus open failed: " + err);
    }
    const bool ok = bus_->configure(motors_, reboot_on_hw_error_, err, warn);
    if (!warn.empty()) {
      RCLCPP_WARN(get_logger(), "%s", warn.c_str());
    }
    if (!ok) {
      throw std::runtime_error("bus configure failed: " + err);
    }
    RCLCPP_INFO(
      get_logger(), "bus '%s' ready (%s @ %d), %zu joints, loop %.0f Hz, timeout %.0f ms",
      bus_->name(), mock_ ? "mock" : port_name_.c_str(), baud_rate_, n_, loop_rate_hz_,
      command_timeout_ms_);

    // ---------------- ROS interfaces ----------------
    pub_joint_states_ = create_publisher<sensor_msgs::msg::JointState>("/joint_states", 10);
    pub_status_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>("/dxl_driver/status", 10);
    pub_tracking_ = create_publisher<sensor_msgs::msg::JointState>("/dxl_driver/tracking_error", 10);
    pub_motor_state_ = create_publisher<omx_msgs::msg::MotorState>("/dxl_driver/motor_state", 10);
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
    tracking_timer_ = create_wall_timer(
      100ms, std::bind(&DxlDriverNode::publishTrackingError, this));

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
        pwm_raw_[i] = st[i].pwm_raw;
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

    updateSagOffsets();
    const double max_step = max_velocity_ / loop_rate_hz_;
    std::vector<int32_t> ticks(n_);
    for (size_t i = 0; i < n_; ++i) {
      const double target = std::clamp(cmd_rad_[i] + offset_applied_[i], lower_[i], upper_[i]);
      const double step = std::clamp(target - goal_rad_[i], -max_step, max_step);
      goal_rad_[i] += step;
      ticks[i] = radToTicks(i, goal_rad_[i]);
    }
    if (!bus_->writeGoalPositions(ticks, err)) {
      ++write_failures_;
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "write failed: %s", err.c_str());
    }
  }

  // ---------------- sag compensation ----------------
  // offset_j = goal_offset_j - compliance_j * tau_j(q_cmd); tau from the planar gravity model.
  void updateSagOffsets()
  {
    std::array<double, 6> q{0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
    for (size_t i = 0; i < std::min<size_t>(6, n_); ++i) {
      q[i] = have_command_ ? cmd_rad_[i] : pos_rad_[i];
    }
    const auto tau = gravity_->torques(q);
    for (size_t i = 0; i < n_; ++i) {
      gravity_nm_[i] = (i >= 1 && i <= 3) ? tau[i - 1] : 0.0;
      offset_applied_[i] = goal_offset_[i] - compliance_[i] * gravity_nm_[i];
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
    std::string warn;
    if (!bus_->configure(motors_, reboot_on_hw_error_, err, warn)) {
      res->success = false;
      res->message = "rebooted but reconfigure failed: " + err;
      return;
    }
    if (!warn.empty()) {
      RCLCPP_WARN(get_logger(), "%s", warn.c_str());
    }
    res->success = true;
    res->message = "rebooted and reconfigured (torque off)";
  }

  // ---------------- tracking error + motor telemetry (10 Hz) ----------------
  // tracking_error: commanded - present per joint [rad], i.e. the error the user
  // cares about (with goal_offset_rad = 0 this equals goal - present). A steady
  // negative value on the pitch joints while holding a pose is gravity sag: copy
  // it into goal_offset_rad and it should read ~0 afterwards.
  // motor_state: PWM, load, voltage, temperature, alarm bits per motor.
  void publishTrackingError()
  {
    const bool active = torque_on_ && have_command_;
    sensor_msgs::msg::JointState msg;
    msg.header.stamp = now();
    msg.name = joint_names_;
    msg.position.assign(n_, 0.0);
    if (active) {
      for (size_t i = 0; i < n_; ++i) {
        msg.position[i] = cmd_rad_[i] - pos_rad_[i];
      }
    }
    pub_tracking_->publish(msg);

    omx_msgs::msg::MotorState ms;
    ms.header.stamp = msg.header.stamp;
    ms.joint_names = joint_names_;
    ms.torque_enabled = torque_on_;
    for (size_t i = 0; i < n_; ++i) {
      ms.ids.push_back(motors_[i].id);
      ms.goal_rad.push_back(active ? goal_rad_[i] : 0.0);
      ms.present_rad.push_back(pos_rad_[i]);
      ms.error_deg.push_back(active ? (cmd_rad_[i] - pos_rad_[i]) * 180.0 / M_PI : 0.0);
      ms.pwm_percent.push_back(static_cast<float>(pwm_raw_[i] / 885.0 * 100.0));
      ms.load_raw.push_back(static_cast<int16_t>(eff_[i]));
      ms.voltage_v.push_back(static_cast<float>(last_health_[i].voltage_raw / 10.0));
      ms.temperature_c.push_back(last_health_[i].temperature_c);
      ms.hardware_error.push_back(last_health_[i].hardware_error);
      ms.hardware_error_text.push_back(describeHardwareError(last_health_[i].hardware_error));
      ms.gravity_nm.push_back(static_cast<float>(gravity_nm_[i]));
      ms.offset_rad.push_back(offset_applied_[i]);
    }
    if (!active) {
      updateSagOffsets();   // keep gravity_nm meaningful (from the present pose) while idle
    }
    pub_motor_state_->publish(ms);
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
    if (ok && h.size() == n_) {
      last_health_ = h;
    }
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
        s.values.push_back(kv("hardware_error_text", describeHardwareError(h[i].hardware_error)));
        if (h[i].hardware_error != 0) {
          s.level = diagnostic_msgs::msg::DiagnosticStatus::ERROR;
          s.message = "hardware error " + describeHardwareError(h[i].hardware_error);
          if (!(hw_error_seen_ & (1u << i))) {
            hw_error_seen_ |= (1u << i);
            RCLCPP_ERROR(
              get_logger(),
              "%s (id %d): ALARM SHUTDOWN %s at %.1f V, %d C -> joint is limp. Support the arm, "
              "fix the cause, then call /dxl_driver/reboot",
              joint_names_[i].c_str(), motors_[i].id,
              describeHardwareError(h[i].hardware_error).c_str(), h[i].voltage_raw / 10.0,
              h[i].temperature_c);
          }
        } else if (h[i].temperature_c >= 65) {
          s.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
          s.message = "hot";
        }
      } else {
        s.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
        s.message = ok ? "no health data" : err;
      }
      if (ok && i < h.size() && h[i].valid && h[i].hardware_error == 0) {
        hw_error_seen_ &= ~(1u << i);   // cleared (rebooted): report again if it recurs
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
  bool reboot_on_hw_error_{true};
  double ticks_per_rev_{4096.0};

  size_t n_{0};
  std::vector<std::string> joint_names_;
  std::map<std::string, size_t> index_;
  std::vector<MotorConfig> motors_;
  std::vector<double> zero_ticks_, direction_, lower_, upper_, goal_offset_, compliance_;
  std::vector<double> gravity_nm_, offset_applied_;
  std::unique_ptr<GravityModel> gravity_;
  std::vector<double> pos_rad_, vel_rad_, eff_, cmd_rad_, goal_rad_;
  std::vector<int16_t> pwm_raw_;
  std::vector<MotorState> last_health_;

  std::unique_ptr<DxlBus> bus_;
  bool torque_on_{false};
  bool have_state_{false};
  bool have_command_{false};
  bool timeout_warned_{false};
  rclcpp::Time last_command_time_{0, 0, RCL_ROS_TIME};
  uint64_t read_failures_{0}, last_read_failures_{0}, write_failures_{0};
  uint32_t hw_error_seen_{0};   // bit i: joint i already reported in alarm state

  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr pub_joint_states_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr pub_tracking_;
  rclcpp::Publisher<omx_msgs::msg::MotorState>::SharedPtr pub_motor_state_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr pub_status_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr sub_command_;
  rclcpp::Service<std_srvs::srv::SetBool>::SharedPtr srv_torque_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr srv_reboot_;
  rclcpp::TimerBase::SharedPtr loop_timer_, status_timer_, tracking_timer_;
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
