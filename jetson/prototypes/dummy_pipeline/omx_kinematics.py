#!/usr/bin/env python3
"""Analytic forward/inverse kinematics for the OMX-AI follower (5 DOF + gripper).

Link geometry is taken directly from
    open_manipulator_description/urdf/omx_f/omx_f_arm.urdf.xacro
    open_manipulator_description/urdf/omx_f/omx_f.urdf   (end_effector_joint)

Chain (parent -> child, origin xyz, axis):
    link0 -> joint1  (-0.01125, 0, 0.034)     axis Z    yaw
    link1 -> joint2  ( 0,       0, 0.0635)    axis Y    pitch
    link2 -> joint3  ( 0.0415,  0, 0.11315)   axis Y    pitch
    link3 -> joint4  ( 0.162,   0, 0)         axis Y    pitch
    link4 -> joint5  ( 0.0287,  0, 0)         axis X    roll
    link5 -> ee      ( 0.09193, -0.0016, 0)   fixed

Because joint2/3/4 all rotate about Y they span a single vertical plane, and
joint1 rotates that plane about Z.  Consequences:

    * EE yaw is NOT free -- it is locked to atan2(y, x) of the target.
    * Controllable pose = position (3) + approach pitch (1) + roll (1) = 5.

The tiny -0.0016 m y-offset of the EE is the only thing joint5 moves off-plane.
It is ignored here (1.6 mm, well inside the gripper's compliance).
"""

import math

# --- link constants (metres) -------------------------------------------------
BASE_X = -0.01125          # link0 -> joint1 axis, x
BASE_Z = 0.034             # link0 -> joint1 axis, z
J1_TO_J2_Z = 0.0635        # joint1 -> joint2, purely vertical

J2_TO_J3_X = 0.0415        # shoulder link has an elbow offset
J2_TO_J3_Z = 0.11315
L2 = math.hypot(J2_TO_J3_X, J2_TO_J3_Z)          # 0.120524
BETA = math.atan2(J2_TO_J3_X, J2_TO_J3_Z)        # 0.351240 rad, fixed skew

L3 = 0.162                 # joint3 -> joint4
L4 = 0.0287                # joint4 -> joint5
L5 = 0.09193               # joint5 -> end_effector_link (x component)
L45 = L4 + L5              # joint5 rotates about x, so these stay collinear

MAX_REACH = L2 + L3 + L45  # 0.4032 m -- matches the 400 mm datasheet reach

# --- joint limits ------------------------------------------------------------
# Three sources disagree, and only one of them is actually enforced:
#
#   URDF                 +-2*pi on every joint -- placeholders, ignore
#   datasheet            joint2/3: -120 .. +90
#   DXL Position Limit   joint2: -107 .. +95,  joint3: -90 .. +96   <-- enforced
#
# The DYNAMIXEL Min/Max Position Limit in omx_f.ros2_control.xacro is what the
# servo itself refuses to exceed, so that is what we mirror.  Using the
# datasheet numbers rejected a real folded pose the arm was physically holding
# (joint3 at ~98 deg), because the datasheet's +90 is tighter than the hardware.
#
# Conversion: angle_deg = (raw - 2048) / 4095 * 360
#   dxl12 joint2: raw 830..3129
#   dxl13 joint3: raw 1024..3140
#   dxl14/15 joint4/5 have raw 0..4095 (unrestricted), so the datasheet's
#   mechanical range is used for those instead.
#
# The raw->degree conversion above still did not match the hardware: the arm
# was observed parked at joint3 = 98.8 deg, past the 96 deg it predicts, so the
# hardware interface applies a calibration offset we cannot read remotely.
# Rather than keep guessing, these are deliberately generous and the real
# gatekeeping is done by limit_report()'s "never move further out" rule plus
# the DYNAMIXEL firmware, which refuses to exceed its own Position Limit.
JOINT_LIMITS = [
    (math.radians(-270.0), math.radians(360.0)),   # joint1, extended position mode
    (math.radians(-110.0), math.radians(100.0)),   # joint2
    (math.radians(-95.0), math.radians(100.0)),    # joint3
    (math.radians(-100.0), math.radians(100.0)),   # joint4
    (math.radians(-270.0), math.radians(270.0)),   # joint5
]
GRIPPER_LIMITS = (math.radians(0.0), math.radians(100.0))


class IKError(Exception):
    """Target is unreachable with the requested approach pitch."""


def forward(q):
    """q = [j1..j5] -> (x, y, z, pitch, roll) of end_effector_link in base frame.

    pitch is the angle of the EE x-axis below horizontal (positive = pointing down).
    """
    j1, j2, j3, j4, j5 = q

    # cumulative angles measured from the +z (vertical) axis, in the arm plane
    psi2 = j2 + BETA               # joint2 -> joint3 (the skewed shoulder link)
    psi3 = j2 + j3 + math.pi / 2   # joint3 -> joint4 (link along local +x)
    psi4 = j2 + j3 + j4 + math.pi / 2   # joint4 -> joint5 -> EE

    r = L2 * math.sin(psi2) + L3 * math.sin(psi3) + L45 * math.sin(psi4)
    h = L2 * math.cos(psi2) + L3 * math.cos(psi3) + L45 * math.cos(psi4)
    h += J1_TO_J2_Z

    x = BASE_X + r * math.cos(j1)
    y = r * math.sin(j1)
    z = BASE_Z + h

    pitch = j2 + j3 + j4          # psi4 - pi/2
    return x, y, z, pitch, j5


def inverse(x, y, z, pitch, roll, elbow_up=True):
    """(x, y, z, pitch, roll) -> [j1..j5].  Raises IKError if unreachable.

    pitch: approach angle of the EE x-axis below horizontal (rad).
    roll:  rotation about the EE x-axis -> joint5 directly.

    EE yaw is not an argument: it is forced to atan2(y, x) by the mechanism.
    """
    # 1. yaw is determined by the target azimuth -- no choice here
    dx = x - BASE_X
    dy = y
    j1 = math.atan2(dy, dx)
    r = math.hypot(dx, dy)
    h = z - BASE_Z - J1_TO_J2_Z          # planar coords relative to joint2

    # 2. back off along the approach direction to find the wrist (joint3 end)
    wr = r - L45 * math.cos(pitch)
    wh = h + L45 * math.sin(pitch)

    # 3. planar 2-link IK for (L2, L3) reaching the wrist point
    d = math.hypot(wr, wh)
    if d > L2 + L3 or d < abs(L2 - L3):
        raise IKError(
            f'wrist at distance {d:.4f} m out of [{abs(L2 - L3):.4f}, '
            f'{L2 + L3:.4f}] for pitch={math.degrees(pitch):.1f} deg')

    cos_c = (L2 * L2 + d * d - L3 * L3) / (2.0 * L2 * d)
    cos_c = max(-1.0, min(1.0, cos_c))
    c = math.acos(cos_c)

    a = math.atan2(wr, wh)               # wrist direction, from vertical
    psi2 = a - c if elbow_up else a + c
    j2 = psi2 - BETA

    # 4. remaining joints follow from the cumulative-angle identities
    dr = wr - L2 * math.sin(psi2)
    dh = wh - L2 * math.cos(psi2)
    psi3 = math.atan2(dr, dh)
    j3 = psi3 - j2 - math.pi / 2
    j4 = pitch - j2 - j3
    j5 = roll

    return [wrap(j1), wrap(j2), wrap(j3), wrap(j4), wrap(j5)]


def wrap(a):
    """Wrap to (-pi, pi]."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def within_limits(q):
    """True if every joint is inside the datasheet range."""
    return all(lo <= v <= hi for v, (lo, hi) in zip(q, JOINT_LIMITS))


def limit_report(q):
    """List of human-readable violations, empty if the pose is fine."""
    out = []
    for i, (v, (lo, hi)) in enumerate(zip(q, JOINT_LIMITS), start=1):
        if not lo <= v <= hi:
            out.append(f'joint{i}={math.degrees(v):.1f} deg outside '
                       f'[{math.degrees(lo):.0f}, {math.degrees(hi):.0f}]')
    return out


def clamp_gripper(a):
    lo, hi = GRIPPER_LIMITS
    return max(lo, min(hi, a))


# -----------------------------------------------------------------------------
if __name__ == '__main__':
    import random

    print(f'L2={L2:.6f}  BETA={math.degrees(BETA):.3f} deg  '
          f'L3={L3}  L45={L45:.5f}')
    print(f'MAX_REACH={MAX_REACH:.4f} m  (datasheet: 0.400 m)\n')

    # --- round trip: random joints -> FK -> IK -> FK, compare ----------------
    random.seed(0)
    worst = 0.0
    tested = 0
    failed = 0
    for _ in range(20000):
        q = [random.uniform(lo, hi) for lo, hi in JOINT_LIMITS]
        pose = forward(q)
        try:
            for elbow in (True, False):
                q2 = inverse(*pose, elbow_up=elbow)
                pose2 = forward(q2)
                err = max(abs(a - b) for a, b in zip(pose[:3], pose2[:3]))
                aerr = abs(wrap(pose[3] - pose2[3]))
                if err < 1e-9 and aerr < 1e-9:
                    worst = max(worst, err)
                    tested += 1
                    break
            else:
                failed += 1
        except IKError:
            failed += 1

    print(f'round trip: {tested} matched, {failed} unmatched, '
          f'worst position error {worst:.3e} m')

    # --- a concrete pose in front of the robot -------------------------------
    print('\nsample: 22 cm in front, 12 cm high, pointing 30 deg down')
    q = inverse(0.22, 0.0, 0.12, math.radians(30), 0.0)
    print('  joints [deg]:', [round(math.degrees(v), 2) for v in q])
    print('  limits     :', limit_report(q) or 'ok')
    print('  FK back    :', [round(v, 6) for v in forward(q)[:3]])
