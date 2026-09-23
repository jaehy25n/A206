"""Analytic forward / inverse kinematics for the OMX-F arm (5 DOF + gripper).

Ported from the prototype ``dummy_exec/omx_kinematics.py`` and parametrised so
the tool centre point (TCP) can sit anywhere along the approach axis.

Chain (parent -> child, origin xyz, axis) -- see omx_description/urdf/omx_f.urdf:

    base_link -> joint1  (-0.01125, 0, 0.034)     axis Z   yaw
    link1     -> joint2  ( 0,       0, 0.0635)    axis Y   pitch
    link2     -> joint3  ( 0.0415,  0, 0.11315)   axis Y   pitch
    link3     -> joint4  ( 0.162,   0, 0)         axis Y   pitch
    link4     -> joint5  ( 0.0287,  0, 0)         axis X   roll
    link5     -> end_effector_link (0.09193, -0.0016, 0)  fixed
    end_effector_link -> tcp (tcp_offset_x, 0, 0)          fixed

joint2/3/4 all rotate about Y, so they span one vertical plane which joint1
rotates about Z.  Consequences:

    * EE yaw is NOT free: it is locked to atan2(y, x - BASE_X) of the target.
    * Controllable pose = position (3) + approach pitch (1) + roll (1) = 5.

Orientation convention: R = Rz(yaw) @ Ry(pitch) @ Rx(roll).  Positive pitch
points the approach axis (+x of the TCP) downwards.  The 1.6 mm y-offset of
the end effector is ignored (well inside the gripper compliance).
"""

import math

import numpy as np

# --- link constants (metres) --------------------------------------------------
BASE_X = -0.01125          # base_link -> joint1 axis, x
BASE_Z = 0.034             # base_link -> joint1 axis, z
J1_TO_J2_Z = 0.0635        # joint1 -> joint2, purely vertical

J2_TO_J3_X = 0.0415        # shoulder link has an elbow offset
J2_TO_J3_Z = 0.11315
L2 = math.hypot(J2_TO_J3_X, J2_TO_J3_Z)          # 0.120524
BETA = math.atan2(J2_TO_J3_X, J2_TO_J3_Z)        # 0.351240 rad, fixed skew

L3 = 0.162                 # joint3 -> joint4
L4 = 0.0287                # joint4 -> joint5
L5_EE = 0.09193            # joint5 -> end_effector_link (x component)

ARM_JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
GRIPPER_JOINT = 'gripper_joint_1'
JOINT_NAMES = ARM_JOINTS + [GRIPPER_JOINT]

# Safe default limits [rad] -- keep in sync with omx_bringup/config/joint_limits.yaml
DEFAULT_LOWER = [-3.1416, -1.868, -1.571, -1.745, -3.1416, 0.0]
DEFAULT_UPPER = [3.1416, 1.658, 1.675, 1.745, 3.1416, 1.745]


class IKError(Exception):
    """Target is unreachable with the requested approach pitch."""


def wrap(a):
    """Wrap an angle to (-pi, pi]."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def rpy_to_rot(yaw, pitch, roll):
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    cz, sz = math.cos(yaw), math.sin(yaw)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cx, sx = math.cos(roll), math.sin(roll)
    rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    return rz @ ry @ rx


class Kinematics:
    """FK / IK / 5-DOF projection for one TCP definition and one set of limits."""

    def __init__(self, tcp_offset_x=0.0, lower=None, upper=None,
                 gripper_open_rad=1.745, gripper_closed_rad=0.0):
        self.tcp_offset_x = float(tcp_offset_x)
        self.l45 = L4 + L5_EE + self.tcp_offset_x   # joint5 rotates about x: collinear
        self.lower = [float(v) for v in (lower if lower is not None else DEFAULT_LOWER)]
        self.upper = [float(v) for v in (upper if upper is not None else DEFAULT_UPPER)]
        if len(self.lower) != 6 or len(self.upper) != 6:
            raise ValueError('limits must have 6 entries (5 arm joints + gripper)')
        self.gripper_open = float(gripper_open_rad)
        self.gripper_closed = float(gripper_closed_rad)

    # --- reach -----------------------------------------------------------------
    @property
    def max_reach(self):
        return L2 + L3 + self.l45

    # --- forward ---------------------------------------------------------------
    def forward(self, q):
        """q = [j1..j5] -> (x, y, z, pitch, roll) of the TCP in base_link."""
        j1, j2, j3, j4, j5 = q[:5]
        psi2 = j2 + BETA                       # joint2 -> joint3 (skewed shoulder link)
        psi3 = j2 + j3 + math.pi / 2.0         # joint3 -> joint4
        psi4 = j2 + j3 + j4 + math.pi / 2.0    # joint4 -> joint5 -> TCP
        r = L2 * math.sin(psi2) + L3 * math.sin(psi3) + self.l45 * math.sin(psi4)
        h = L2 * math.cos(psi2) + L3 * math.cos(psi3) + self.l45 * math.cos(psi4)
        h += J1_TO_J2_Z
        x = BASE_X + r * math.cos(j1)
        y = r * math.sin(j1)
        z = BASE_Z + h
        pitch = j2 + j3 + j4
        return x, y, z, pitch, j5

    def forward_matrix(self, q):
        """q = [j1..j5] -> 4x4 T_base_tcp."""
        x, y, z, pitch, roll = self.forward(q)
        yaw = math.atan2(y, x - BASE_X)
        t = np.eye(4)
        t[:3, :3] = rpy_to_rot(yaw, pitch, roll)
        t[:3, 3] = (x, y, z)
        return t

    # --- inverse ---------------------------------------------------------------
    def inverse(self, x, y, z, pitch, roll, elbow_up=True):
        """(x, y, z, pitch, roll) -> [j1..j5]. Raises IKError if unreachable.

        yaw is not an argument: the mechanism forces it to atan2(y, x - BASE_X).
        """
        dx = x - BASE_X
        dy = y
        j1 = math.atan2(dy, dx)
        r = math.hypot(dx, dy)
        h = z - BASE_Z - J1_TO_J2_Z              # planar coords relative to joint2

        # back off along the approach direction to find the wrist point (joint4)
        wr = r - self.l45 * math.cos(pitch)
        wh = h + self.l45 * math.sin(pitch)

        d = math.hypot(wr, wh)
        if d > L2 + L3 or d < abs(L2 - L3):
            raise IKError(
                f'wrist at {d:.4f} m outside [{abs(L2 - L3):.4f}, {L2 + L3:.4f}] '
                f'for pitch={math.degrees(pitch):.1f} deg')

        cos_c = (L2 * L2 + d * d - L3 * L3) / (2.0 * L2 * d)
        cos_c = max(-1.0, min(1.0, cos_c))
        c = math.acos(cos_c)

        a = math.atan2(wr, wh)                   # wrist direction, from vertical
        psi2 = a - c if elbow_up else a + c
        j2 = psi2 - BETA

        dr = wr - L2 * math.sin(psi2)
        dh = wh - L2 * math.cos(psi2)
        psi3 = math.atan2(dr, dh)
        j3 = psi3 - j2 - math.pi / 2.0
        j4 = pitch - j2 - j3
        j5 = roll
        return [wrap(j1), wrap(j2), wrap(j3), wrap(j4), wrap(j5)]

    # --- 5-DOF projection ------------------------------------------------------
    @staticmethod
    def project(t):
        """4x4 target pose -> (x, y, z, pitch, roll, yaw_dropped).

        Removes the yaw the mechanism will impose anyway and reports how much
        of the requested yaw had to be discarded (radians, wrapped).
        """
        p = t[:3, 3]
        rot = t[:3, :3]
        yaw_forced = math.atan2(p[1], p[0] - BASE_X)
        cz, sz = math.cos(-yaw_forced), math.sin(-yaw_forced)
        rz_inv = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
        m = rz_inv @ rot                          # should now be Ry(pitch) @ Rx(roll)
        pitch = math.atan2(-m[2, 0], m[0, 0])
        roll = math.atan2(-m[1, 2], m[1, 1])
        yaw_req = math.atan2(rot[1, 0], rot[0, 0])
        return float(p[0]), float(p[1]), float(p[2]), pitch, roll, wrap(yaw_req - yaw_forced)

    # --- limits ----------------------------------------------------------------
    def limit_violations(self, q):
        """Human readable list of arm joint limit violations (empty if fine)."""
        out = []
        for i, v in enumerate(q[:5]):
            lo, hi = self.lower[i], self.upper[i]
            if not lo <= v <= hi:
                out.append(f'{ARM_JOINTS[i]}={math.degrees(v):.1f} deg outside '
                           f'[{math.degrees(lo):.0f}, {math.degrees(hi):.0f}]')
        return out

    def solve(self, t, q_seed=None):
        """4x4 target -> (q[5] or None, info).

        Tries both elbow branches, drops solutions outside the limits and, when
        two remain, picks the one closest to q_seed (or elbow-up).
        info = {'yaw_drop', 'pose', 'branch', 'reason'}
        """
        x, y, z, pitch, roll, drop = self.project(t)
        info = {'yaw_drop': drop, 'pose': (x, y, z, pitch, roll), 'branch': None, 'reason': None}
        candidates = []
        reasons = []
        for branch in (True, False):
            try:
                q = self.inverse(x, y, z, pitch, roll, elbow_up=branch)
            except IKError as exc:
                reasons.append(str(exc))
                continue
            viol = self.limit_violations(q)
            if viol:
                reasons.append(('elbow_up' if branch else 'elbow_down') + ': ' + '; '.join(viol))
                continue
            candidates.append((branch, q))
        if not candidates:
            info['reason'] = ' | '.join(reasons) if reasons else 'no solution'
            return None, info
        if q_seed is not None and len(candidates) > 1:
            seed = list(q_seed)[:5]
            candidates.sort(key=lambda bq: sum(abs(wrap(a - b)) for a, b in zip(bq[1], seed)))
        branch, q = candidates[0]
        info['branch'] = 'elbow_up' if branch else 'elbow_down'
        return q, info

    # --- gripper ---------------------------------------------------------------
    def width_to_gripper(self, width):
        """Normalised width 0 (closed) .. 1 (open) -> gripper_joint_1 angle [rad]."""
        w = min(1.0, max(0.0, float(width)))
        return self.gripper_closed + (self.gripper_open - self.gripper_closed) * w

    def gripper_to_width(self, angle):
        span = self.gripper_open - self.gripper_closed
        if abs(span) < 1e-9:
            return 0.0
        return min(1.0, max(0.0, (float(angle) - self.gripper_closed) / span))
