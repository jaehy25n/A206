// Planar gravity model of the OMX-F arm for position-domain sag compensation.
//
// joint2/3/4 all pitch about the same axis direction, so everything downstream
// of joint2 lives in one vertical plane (radial coordinate r, height h). The
// gravity torque about a pitch joint is  tau = g * sum_k m_k * (r_k - r_joint)
// over the links beyond that joint. Positive tau pulls the arm DOWN (increases
// pitch), which is the direction the arm sags under P-only position control.
//
// Link masses and centres of mass are the URDF values (omx_description/urdf/
// omx_f.urdf, ROBOTIS inertials). The wrist camera + mount are NOT in the URDF:
// they enter as a point-mass payload expressed in the link5 (joint5) frame.
#pragma once

#include <array>
#include <cmath>
#include <utility>

namespace omx_driver
{

class GravityModel
{
public:
  struct Local {double m, x, y, z;};   // mass [kg] and position in the owning link frame [m]

  GravityModel(double payload_mass_kg, std::array<double, 3> payload_xyz_link5)
  : payload_{payload_mass_kg, payload_xyz_link5[0], payload_xyz_link5[1], payload_xyz_link5[2]} {}

  // q = [joint1..joint5, gripper] in radians. Returns torques about joint2, joint3, joint4 [N m].
  std::array<double, 3> torques(const std::array<double, 6> & q) const
  {
    constexpr double g = 9.81;
    const double th2 = q[1];
    const double th3 = q[1] + q[2];
    const double th4 = q[1] + q[2] + q[3];
    const double roll = q[4];

    // joint origins in the arm plane (joint2 at the origin)
    const auto o2 = std::pair<double, double>{0.0, 0.0};
    const auto o3 = add(o2, ry(th2, 0.0415, 0.11315));
    const auto o4 = add(o3, ry(th3, 0.162, 0.0));
    const auto o5 = add(o4, ry(th4, 0.0287, 0.0));

    // (mass, radial position) of every body, grouped by the first joint that carries it
    struct Body {double m, r; int first_joint;};   // first_joint: 2, 3 or 4
    std::array<Body, 7> bodies{{
      {kLink2.m, add(o2, ry(th2, kLink2.x, kLink2.z)).first, 2},
      {kLink3.m, add(o3, ry(th3, kLink3.x, kLink3.z)).first, 3},
      {kLink4.m, add(o4, ry(th4, kLink4.x, kLink4.z)).first, 4},
      {kLink5.m, add(o5, ry(th4, kLink5.x, rolled_z(roll, kLink5.y, kLink5.z))).first, 4},
      {kFinger1.m, add(o5, ry(th4, kFinger1.x, rolled_z(roll, kFinger1.y, kFinger1.z))).first, 4},
      {kFinger2.m, add(o5, ry(th4, kFinger2.x, rolled_z(roll, kFinger2.y, kFinger2.z))).first, 4},
      {payload_.m, add(o5, ry(th4, payload_.x, rolled_z(roll, payload_.y, payload_.z))).first, 4},
    }};

    std::array<double, 3> tau{0.0, 0.0, 0.0};
    const std::array<double, 3> joint_r{o2.first, o3.first, o4.first};
    for (const auto & b : bodies) {
      for (int j = 2; j <= b.first_joint; ++j) {
        tau[j - 2] += g * b.m * (b.r - joint_r[j - 2]);
      }
    }
    return tau;
  }

private:
  // rotate a local (x, ., z) by pitch th about +y: returns (r, h)
  static std::pair<double, double> ry(double th, double x, double z)
  {
    return {x * std::cos(th) + z * std::sin(th), -x * std::sin(th) + z * std::cos(th)};
  }
  // roll about the link5 x axis moves a local y/z offset: returns the new z
  static double rolled_z(double roll, double y, double z)
  {
    return y * std::sin(roll) + z * std::cos(roll);
  }
  static std::pair<double, double> add(std::pair<double, double> a, std::pair<double, double> b)
  {
    return {a.first + b.first, a.second + b.second};
  }

  // URDF inertials (mass, COM in the link frame whose origin is the link's parent joint)
  static constexpr Local kLink2{0.08722147, 0.018089916, 0.000297788, 0.099005452};
  static constexpr Local kLink3{0.08375913, 0.087398602, 0.000413101, -0.003582921};
  static constexpr Local kLink4{0.02997506, 0.023234980, 0.000067735, 0.005976131};
  static constexpr Local kLink5{0.04381089, 0.028072407, 0.000024136, 0.013528914};
  // gripper fingers: joint origin (0.0295, +-y, 0) in link5 + finger COM (0.01616, 0.00127, 0.00027)
  static constexpr Local kFinger1{0.01209068, 0.045664565, 0.008773103, 0.000272916};
  static constexpr Local kFinger2{0.01209068, 0.045664565, -0.009526897, 0.000272916};

  Local payload_;
};

}  // namespace omx_driver
