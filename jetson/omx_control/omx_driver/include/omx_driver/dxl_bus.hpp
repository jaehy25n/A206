// Thin bus abstraction over DynamixelSDK so the driver node can run against a
// real serial bus or an in-process mock with identical code paths.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace omx_driver
{

// Per-motor configuration written at start-up. Values follow the ROBOTIS
// OMX-F defaults (Drive Mode 4 = time-based profile, Profile Velocity 50 ms,
// Profile Acceleration 25 ms, P/D gains 1000).
struct MotorConfig
{
  uint8_t id{0};
  uint8_t operating_mode{3};      // 3 position, 4 extended position, 5 current-based position
  uint8_t drive_mode{4};          // bit2: time-based profile
  uint32_t profile_velocity{50};
  uint32_t profile_acceleration{25};
  uint16_t position_p_gain{1000};
  uint16_t position_i_gain{0};
  uint16_t position_d_gain{1000};
  uint16_t goal_current{0};       // used only when operating_mode == 5
};

struct MotorState
{
  int32_t position_ticks{0};
  int32_t velocity_raw{0};        // unit 0.229 rpm
  int16_t current_raw{0};         // XL330: mA, XL430: load in 0.1 %
  int16_t pwm_raw{0};             // Present PWM, 885 = 100 %
  uint8_t temperature_c{0};
  uint16_t voltage_raw{0};        // unit 0.1 V
  uint8_t hardware_error{0};
  bool valid{false};
};

class DxlBus
{
public:
  virtual ~DxlBus() = default;

  virtual bool open(std::string & err) = 0;
  virtual void close() = 0;

  // Ping every motor, clear hardware errors (reboot, if allowed), torque off,
  // write configuration (EEPROM fields only if changed). `warn` collects
  // non-fatal findings for the caller to log.
  virtual bool configure(
    const std::vector<MotorConfig> & motors, bool reboot_on_hardware_error,
    std::string & err, std::string & warn) = 0;

  // Present position / velocity / current for every motor (one SyncRead).
  virtual bool readStates(std::vector<MotorState> & out, std::string & err) = 0;

  // Temperature / voltage / hardware error status (slow path, ~1 Hz).
  virtual bool readHealth(std::vector<MotorState> & out, std::string & err) = 0;

  virtual bool writeGoalPositions(const std::vector<int32_t> & ticks, std::string & err) = 0;
  virtual bool setTorque(bool on, std::string & err) = 0;
  virtual bool reboot(std::string & err) = 0;

  virtual const char * name() const = 0;
};

// Human readable decode of the Hardware Error Status register (addr 70).
std::string describeHardwareError(uint8_t status);

std::unique_ptr<DxlBus> makeRealBus(const std::string & port_name, int baud_rate);

// initial_ticks: start pose; max_velocity_ticks_per_s: how fast the fake motors track goals
std::unique_ptr<DxlBus> makeMockBus(
  const std::vector<int32_t> & initial_ticks, double max_velocity_ticks_per_s);

}  // namespace omx_driver
