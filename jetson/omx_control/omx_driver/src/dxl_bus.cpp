#include "omx_driver/dxl_bus.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <sstream>

#include "dynamixel_sdk/dynamixel_sdk.h"

namespace omx_driver
{
namespace
{
// DYNAMIXEL X-series control table (Protocol 2.0). Same layout on XL430 and XL330.
constexpr uint16_t ADDR_RETURN_DELAY_TIME = 9;        // 1 B, EEPROM
constexpr uint16_t ADDR_DRIVE_MODE = 10;              // 1 B, EEPROM
constexpr uint16_t ADDR_OPERATING_MODE = 11;          // 1 B, EEPROM
constexpr uint16_t ADDR_TORQUE_ENABLE = 64;           // 1 B
constexpr uint16_t ADDR_HARDWARE_ERROR_STATUS = 70;   // 1 B
constexpr uint16_t ADDR_POSITION_D_GAIN = 80;         // 2 B
constexpr uint16_t ADDR_POSITION_P_GAIN = 84;         // 2 B
constexpr uint16_t ADDR_GOAL_CURRENT = 102;           // 2 B
constexpr uint16_t ADDR_PROFILE_ACCELERATION = 108;   // 4 B
constexpr uint16_t ADDR_PROFILE_VELOCITY = 112;       // 4 B
constexpr uint16_t ADDR_GOAL_POSITION = 116;          // 4 B
constexpr uint16_t ADDR_PRESENT_CURRENT = 126;        // 2 B
constexpr uint16_t ADDR_PRESENT_VELOCITY = 128;       // 4 B
constexpr uint16_t ADDR_PRESENT_POSITION = 132;       // 4 B
constexpr uint16_t LEN_STATE_BLOCK = 10;              // 126..135 in one read
constexpr uint16_t ADDR_PRESENT_INPUT_VOLTAGE = 144;  // 2 B
constexpr uint16_t ADDR_PRESENT_TEMPERATURE = 146;    // 1 B
constexpr uint16_t LEN_HEALTH_BLOCK = 3;              // 144..146
constexpr float PROTOCOL_VERSION = 2.0f;

std::string idStr(uint8_t id, uint16_t addr)
{
  std::ostringstream os;
  os << "id " << static_cast<int>(id) << " addr " << addr << ": ";
  return os.str();
}
}  // namespace

// ---------------------------------------------------------------------------
class RealBus : public DxlBus
{
public:
  RealBus(std::string port_name, int baud_rate)
  : port_name_(std::move(port_name)), baud_rate_(baud_rate) {}

  ~RealBus() override {close();}

  const char * name() const override {return "dynamixel_sdk";}

  bool open(std::string & err) override
  {
    port_ = dynamixel::PortHandler::getPortHandler(port_name_.c_str());
    packet_ = dynamixel::PacketHandler::getPacketHandler(PROTOCOL_VERSION);
    if (!port_->openPort()) {
      err = "failed to open " + port_name_;
      return false;
    }
    if (!port_->setBaudRate(baud_rate_)) {
      err = "failed to set baud rate " + std::to_string(baud_rate_);
      port_->closePort();
      return false;
    }
    opened_ = true;
    return true;
  }

  void close() override
  {
    if (opened_ && port_) {
      port_->closePort();
      opened_ = false;
    }
  }

  bool configure(const std::vector<MotorConfig> & motors, std::string & err) override
  {
    ids_.clear();
    for (const auto & m : motors) {
      ids_.push_back(m.id);
    }
    for (const auto & m : motors) {
      uint16_t model = 0;
      uint8_t dxl_err = 0;
      int rc = packet_->ping(port_, m.id, &model, &dxl_err);
      if (rc != COMM_SUCCESS) {
        err = idStr(m.id, 0) + "ping failed: " + packet_->getTxRxResult(rc);
        return false;
      }
    }
    // EEPROM fields can only be written with torque off. Only write when the
    // stored value differs, to spare the EEPROM write cycles.
    for (const auto & m : motors) {
      if (!write1(m.id, ADDR_TORQUE_ENABLE, 0, err)) {return false;}
      if (!ensure1(m.id, ADDR_RETURN_DELAY_TIME, 0, err)) {return false;}
      if (!ensure1(m.id, ADDR_DRIVE_MODE, m.drive_mode, err)) {return false;}
      if (!ensure1(m.id, ADDR_OPERATING_MODE, m.operating_mode, err)) {return false;}
      // RAM fields: always write
      if (!write2(m.id, ADDR_POSITION_P_GAIN, m.position_p_gain, err)) {return false;}
      if (!write2(m.id, ADDR_POSITION_D_GAIN, m.position_d_gain, err)) {return false;}
      if (!write4(m.id, ADDR_PROFILE_ACCELERATION, m.profile_acceleration, err)) {return false;}
      if (!write4(m.id, ADDR_PROFILE_VELOCITY, m.profile_velocity, err)) {return false;}
      if (m.operating_mode == 5 && m.goal_current > 0) {
        if (!write2(m.id, ADDR_GOAL_CURRENT, m.goal_current, err)) {return false;}
      }
    }
    sync_read_state_ = std::make_unique<dynamixel::GroupSyncRead>(
      port_, packet_, ADDR_PRESENT_CURRENT, LEN_STATE_BLOCK);
    sync_read_health_ = std::make_unique<dynamixel::GroupSyncRead>(
      port_, packet_, ADDR_PRESENT_INPUT_VOLTAGE, LEN_HEALTH_BLOCK);
    sync_read_error_ = std::make_unique<dynamixel::GroupSyncRead>(
      port_, packet_, ADDR_HARDWARE_ERROR_STATUS, 1);
    sync_write_goal_ = std::make_unique<dynamixel::GroupSyncWrite>(
      port_, packet_, ADDR_GOAL_POSITION, 4);
    for (auto id : ids_) {
      sync_read_state_->addParam(id);
      sync_read_health_->addParam(id);
      sync_read_error_->addParam(id);
    }
    return true;
  }

  bool readStates(std::vector<MotorState> & out, std::string & err) override
  {
    int rc = sync_read_state_->txRxPacket();
    if (rc != COMM_SUCCESS) {
      err = std::string("SyncRead: ") + packet_->getTxRxResult(rc);
      return false;
    }
    out.resize(ids_.size());
    for (size_t i = 0; i < ids_.size(); ++i) {
      const auto id = ids_[i];
      auto & s = out[i];
      if (!sync_read_state_->isAvailable(id, ADDR_PRESENT_CURRENT, LEN_STATE_BLOCK)) {
        s.valid = false;
        continue;
      }
      s.current_raw = static_cast<int16_t>(sync_read_state_->getData(id, ADDR_PRESENT_CURRENT, 2));
      s.velocity_raw = static_cast<int32_t>(sync_read_state_->getData(id, ADDR_PRESENT_VELOCITY, 4));
      s.position_ticks = static_cast<int32_t>(sync_read_state_->getData(id, ADDR_PRESENT_POSITION, 4));
      s.valid = true;
    }
    return true;
  }

  bool readHealth(std::vector<MotorState> & out, std::string & err) override
  {
    out.resize(ids_.size());
    int rc = sync_read_health_->txRxPacket();
    if (rc != COMM_SUCCESS) {
      err = std::string("SyncRead health: ") + packet_->getTxRxResult(rc);
      return false;
    }
    int rc2 = sync_read_error_->txRxPacket();
    for (size_t i = 0; i < ids_.size(); ++i) {
      const auto id = ids_[i];
      auto & s = out[i];
      s.valid = sync_read_health_->isAvailable(id, ADDR_PRESENT_INPUT_VOLTAGE, LEN_HEALTH_BLOCK);
      if (s.valid) {
        s.voltage_raw = static_cast<uint16_t>(sync_read_health_->getData(id, ADDR_PRESENT_INPUT_VOLTAGE, 2));
        s.temperature_c = static_cast<uint8_t>(sync_read_health_->getData(id, ADDR_PRESENT_TEMPERATURE, 1));
      }
      if (rc2 == COMM_SUCCESS && sync_read_error_->isAvailable(id, ADDR_HARDWARE_ERROR_STATUS, 1)) {
        s.hardware_error = static_cast<uint8_t>(sync_read_error_->getData(id, ADDR_HARDWARE_ERROR_STATUS, 1));
      }
    }
    return true;
  }

  bool writeGoalPositions(const std::vector<int32_t> & ticks, std::string & err) override
  {
    if (ticks.size() != ids_.size()) {
      err = "writeGoalPositions: size mismatch";
      return false;
    }
    sync_write_goal_->clearParam();
    for (size_t i = 0; i < ids_.size(); ++i) {
      const uint32_t t = static_cast<uint32_t>(ticks[i]);
      uint8_t p[4] = {
        DXL_LOBYTE(DXL_LOWORD(t)), DXL_HIBYTE(DXL_LOWORD(t)),
        DXL_LOBYTE(DXL_HIWORD(t)), DXL_HIBYTE(DXL_HIWORD(t))};
      if (!sync_write_goal_->addParam(ids_[i], p)) {
        err = idStr(ids_[i], ADDR_GOAL_POSITION) + "addParam failed";
        return false;
      }
    }
    int rc = sync_write_goal_->txPacket();
    if (rc != COMM_SUCCESS) {
      err = std::string("SyncWrite: ") + packet_->getTxRxResult(rc);
      return false;
    }
    return true;
  }

  bool setTorque(bool on, std::string & err) override
  {
    for (auto id : ids_) {
      if (!write1(id, ADDR_TORQUE_ENABLE, on ? 1 : 0, err)) {return false;}
    }
    return true;
  }

  bool reboot(std::string & err) override
  {
    for (auto id : ids_) {
      uint8_t dxl_err = 0;
      int rc = packet_->reboot(port_, id, &dxl_err);
      if (rc != COMM_SUCCESS) {
        err = idStr(id, 0) + "reboot: " + packet_->getTxRxResult(rc);
        return false;
      }
    }
    return true;
  }

private:
  bool check(int rc, uint8_t dxl_err, uint8_t id, uint16_t addr, std::string & err)
  {
    if (rc != COMM_SUCCESS) {
      err = idStr(id, addr) + packet_->getTxRxResult(rc);
      return false;
    }
    if (dxl_err != 0) {
      err = idStr(id, addr) + packet_->getRxPacketError(dxl_err);
      return false;
    }
    return true;
  }
  bool write1(uint8_t id, uint16_t addr, uint8_t v, std::string & err)
  {
    uint8_t e = 0;
    return check(packet_->write1ByteTxRx(port_, id, addr, v, &e), e, id, addr, err);
  }
  bool write2(uint8_t id, uint16_t addr, uint16_t v, std::string & err)
  {
    uint8_t e = 0;
    return check(packet_->write2ByteTxRx(port_, id, addr, v, &e), e, id, addr, err);
  }
  bool write4(uint8_t id, uint16_t addr, uint32_t v, std::string & err)
  {
    uint8_t e = 0;
    return check(packet_->write4ByteTxRx(port_, id, addr, v, &e), e, id, addr, err);
  }
  bool read1(uint8_t id, uint16_t addr, uint8_t & v, std::string & err)
  {
    uint8_t e = 0;
    return check(packet_->read1ByteTxRx(port_, id, addr, &v, &e), e, id, addr, err);
  }
  bool ensure1(uint8_t id, uint16_t addr, uint8_t v, std::string & err)
  {
    uint8_t cur = 0;
    if (!read1(id, addr, cur, err)) {return false;}
    if (cur == v) {return true;}
    return write1(id, addr, v, err);
  }

  std::string port_name_;
  int baud_rate_;
  bool opened_{false};
  dynamixel::PortHandler * port_{nullptr};
  dynamixel::PacketHandler * packet_{nullptr};
  std::vector<uint8_t> ids_;
  std::unique_ptr<dynamixel::GroupSyncRead> sync_read_state_;
  std::unique_ptr<dynamixel::GroupSyncRead> sync_read_health_;
  std::unique_ptr<dynamixel::GroupSyncRead> sync_read_error_;
  std::unique_ptr<dynamixel::GroupSyncWrite> sync_write_goal_;
};

// ---------------------------------------------------------------------------
// Mock: first-order tracking of the goal with a velocity cap. Lets the whole
// graph run without hardware (and without USB pass-through into WSL).
class MockBus : public DxlBus
{
public:
  MockBus(std::vector<int32_t> initial_ticks, double vmax_ticks_per_s)
  : vmax_(vmax_ticks_per_s)
  {
    pos_.assign(initial_ticks.begin(), initial_ticks.end());
    goal_ = pos_;
    vel_.assign(pos_.size(), 0.0);
    last_ = std::chrono::steady_clock::now();
  }

  const char * name() const override {return "mock";}
  bool open(std::string &) override {return true;}
  void close() override {}

  bool configure(const std::vector<MotorConfig> & motors, std::string & err) override
  {
    if (motors.size() != pos_.size()) {
      err = "mock: motor count (" + std::to_string(motors.size()) +
        ") != initial position count (" + std::to_string(pos_.size()) + ")";
      return false;
    }
    return true;
  }

  bool readStates(std::vector<MotorState> & out, std::string &) override
  {
    const auto now = std::chrono::steady_clock::now();
    double dt = std::chrono::duration<double>(now - last_).count();
    last_ = now;
    dt = std::clamp(dt, 0.0, 0.1);
    out.resize(pos_.size());
    for (size_t i = 0; i < pos_.size(); ++i) {
      if (torque_ && dt > 0.0) {
        const double max_step = vmax_ * dt;
        const double step = std::clamp(goal_[i] - pos_[i], -max_step, max_step);
        pos_[i] += step;
        vel_[i] = step / dt;
      } else {
        vel_[i] = 0.0;
      }
      auto & s = out[i];
      s.position_ticks = static_cast<int32_t>(std::lround(pos_[i]));
      // ticks/s -> rev/s -> rpm -> raw (0.229 rpm per unit)
      s.velocity_raw = static_cast<int32_t>(std::lround(vel_[i] / 4096.0 * 60.0 / 0.229));
      s.current_raw = 0;
      s.valid = true;
    }
    return true;
  }

  bool readHealth(std::vector<MotorState> & out, std::string &) override
  {
    out.resize(pos_.size());
    for (auto & s : out) {
      s.temperature_c = 35;
      s.voltage_raw = 120;
      s.hardware_error = 0;
      s.valid = true;
    }
    return true;
  }

  bool writeGoalPositions(const std::vector<int32_t> & ticks, std::string & err) override
  {
    if (ticks.size() != goal_.size()) {
      err = "mock: goal size mismatch";
      return false;
    }
    if (torque_) {
      goal_.assign(ticks.begin(), ticks.end());
    }
    return true;
  }

  bool setTorque(bool on, std::string &) override
  {
    torque_ = on;
    if (on) {
      goal_ = pos_;
    }
    return true;
  }

  bool reboot(std::string &) override
  {
    torque_ = false;
    return true;
  }

private:
  std::vector<double> pos_, goal_, vel_;
  bool torque_{false};
  double vmax_;
  std::chrono::steady_clock::time_point last_;
};

// ---------------------------------------------------------------------------
std::unique_ptr<DxlBus> makeRealBus(const std::string & port_name, int baud_rate)
{
  return std::make_unique<RealBus>(port_name, baud_rate);
}

std::unique_ptr<DxlBus> makeMockBus(
  const std::vector<int32_t> & initial_ticks, double max_velocity_ticks_per_s)
{
  return std::make_unique<MockBus>(initial_ticks, max_velocity_ticks_per_s);
}

}  // namespace omx_driver
