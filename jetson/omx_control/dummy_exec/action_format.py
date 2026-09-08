#!/usr/bin/env python3
"""UMI-style action chunk format, and the conversion down to OMX joint targets.

One action step is 10 numbers:

    [0:3]   delta position   (x, y, z) in metres, RELATIVE to the anchor pose
    [3:9]   delta rotation   6D representation (Zhou et al. 2019), RELATIVE
    [9]     gripper width    normalised 0 (closed) .. 1 (open), ABSOLUTE

Note the mixed frames: pose is relative, gripper width is absolute.  Width has a
physical meaning (the object's size) so a relative encoding would be meaningless.
This is the easiest place in the pipeline to make a silent mistake.

A chunk is [H, 10] and carries no timestamps.  Timing is the fixed DT agreed at
label-construction time; it becomes explicit only here, when we fill in
time_from_start on the JointTrajectory.
"""

import math

import numpy as np

import omx_kinematics as K

ACTION_DIM = 10


# --- 6D rotation representation ----------------------------------------------
def rot_to_6d(R):
    """3x3 rotation matrix -> 6 numbers (first two columns)."""
    return np.concatenate([R[:, 0], R[:, 1]])


def rot_from_6d(v):
    """6 numbers -> 3x3 rotation matrix, via Gram-Schmidt.

    Continuous and unconstrained, which is why networks regress this instead of
    quaternions (double cover) or Euler angles (gimbal lock, wraparound).
    """
    a1, a2 = np.asarray(v[0:3], float), np.asarray(v[3:6], float)
    b1 = a1 / np.linalg.norm(a1)
    a2 = a2 - np.dot(b1, a2) * b1
    b2 = a2 / np.linalg.norm(a2)
    b3 = np.cross(b1, b2)
    return np.stack([b1, b2, b3], axis=1)


# --- pose helpers -------------------------------------------------------------
def rpy_to_rot(yaw, pitch, roll):
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll) -- the OMX composition order.

    joint1 supplies yaw, joints 2/3/4 sum to pitch, joint5 is roll.
    """
    cz, sz = math.cos(yaw), math.sin(yaw)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cx, sx = math.cos(roll), math.sin(roll)
    Rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    Ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    return Rz @ Ry @ Rx


def make_T(p, R):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def joints_to_T(q):
    """Current joint angles -> 4x4 EE pose in the base frame."""
    x, y, z, pitch, roll = K.forward(q)
    yaw = math.atan2(y - 0.0, x - K.BASE_X)
    return make_T(np.array([x, y, z]), rpy_to_rot(yaw, pitch, roll))


def project_to_5dof(T):
    """4x4 target pose -> (x, y, z, pitch, roll), discarding EE yaw.

    The arm cannot set yaw independently: joints 2/3/4 share one plane and
    joint1 rotates that plane, so yaw is pinned to atan2(y, x) of the target.
    We keep position, pitch and roll, and drop the yaw the policy asked for.
    """
    p = T[:3, 3]
    yaw_forced = math.atan2(p[1], p[0] - K.BASE_X)

    # residual orientation after removing the yaw the mechanism will impose
    cz, sz = math.cos(-yaw_forced), math.sin(-yaw_forced)
    Rz_inv = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    M = Rz_inv @ T[:3, :3]

    # M should now be Ry(pitch) @ Rx(roll)
    pitch = math.atan2(-M[2, 0], M[0, 0])
    roll = math.atan2(-M[1, 2], M[1, 1])
    return float(p[0]), float(p[1]), float(p[2]), pitch, roll


def yaw_discarded(T):
    """How much EE yaw the projection had to throw away, in radians.

    Worth logging: a large value means the demonstration approached from an
    azimuth this arm structurally cannot reproduce.
    """
    p = T[:3, 3]
    yaw_forced = math.atan2(p[1], p[0] - K.BASE_X)
    R = T[:3, :3]
    # yaw actually encoded in the requested rotation
    yaw_req = math.atan2(R[1, 0], R[0, 0])
    return K.wrap(yaw_req - yaw_forced)


# --- chunk -> joint targets ---------------------------------------------------
def width_to_gripper_angle(w):
    """Normalised width 0..1 -> gripper_joint_1 angle (rad)."""
    lo, hi = K.GRIPPER_LIMITS
    return K.clamp_gripper(lo + (hi - lo) * float(np.clip(w, 0.0, 1.0)))


def decode_chunk(chunk, T_anchor, elbow_up=True):
    """[H, 10] relative actions -> list of per-step results.

    Each entry is a dict:
        q          [j1..j5] or None if IK failed
        gripper    gripper_joint_1 angle (rad)
        pose       (x, y, z, pitch, roll) after the 5-DOF projection
        yaw_drop   radians of EE yaw discarded by the projection
        problem    None, or a string explaining why this step is unusable
    """
    chunk = np.asarray(chunk, float)
    assert chunk.ndim == 2 and chunk.shape[1] == ACTION_DIM, chunk.shape

    out = []
    for a in chunk:
        dT = make_T(a[0:3], rot_from_6d(a[3:9]))
        T_target = T_anchor @ dT

        x, y, z, pitch, roll = project_to_5dof(T_target)
        drop = yaw_discarded(T_target)
        entry = {
            'pose': (x, y, z, pitch, roll),
            'yaw_drop': drop,
            'gripper': width_to_gripper_angle(a[9]),
            'q': None,
            'problem': None,
        }
        try:
            q = K.inverse(x, y, z, pitch, roll, elbow_up=elbow_up)
        except K.IKError as exc:
            entry['problem'] = f'IK: {exc}'
            out.append(entry)
            continue

        violations = K.limit_report(q)
        if violations:
            entry['problem'] = 'limits: ' + '; '.join(violations)
        entry['q'] = q
        out.append(entry)
    return out
