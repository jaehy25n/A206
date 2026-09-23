"""UMI-style action chunk format and the pose maths shared by the stack.

One action step is 10 numbers (the array form a policy network emits):

    [0:3]   delta position   (x, y, z) in metres, RELATIVE to the anchor pose
    [3:9]   delta rotation   6D representation (Zhou et al. 2019), RELATIVE
    [9]     gripper width    normalised 0 (closed) .. 1 (open), ABSOLUTE

Note the mixed frames: pose is relative, gripper width is absolute.  Width has
a physical meaning (the object's size), so a relative encoding would be
meaningless.  This is the easiest place in the pipeline to make a silent
mistake.

On the wire the same content travels as omx_msgs/EEActionChunk, where every
relative pose is a geometry_msgs/Pose (quaternion) and the anchor pose is
carried explicitly so the executor never has to time-match /ee_state.
"""

import math

import numpy as np

ACTION_DIM = 10


# --- 6D rotation representation ------------------------------------------------
def rot_to_6d(rot):
    """3x3 rotation matrix -> 6 numbers (first two columns)."""
    return np.concatenate([rot[:, 0], rot[:, 1]])


def rot_from_6d(v):
    """6 numbers -> 3x3 rotation matrix via Gram-Schmidt."""
    a1, a2 = np.asarray(v[0:3], float), np.asarray(v[3:6], float)
    b1 = a1 / np.linalg.norm(a1)
    a2 = a2 - np.dot(b1, a2) * b1
    b2 = a2 / np.linalg.norm(a2)
    b3 = np.cross(b1, b2)
    return np.stack([b1, b2, b3], axis=1)


# --- quaternion <-> matrix (x, y, z, w) -----------------------------------------
def quat_to_mat(x, y, z, w):
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([
        [1.0 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
        [s * (x * y + z * w), 1.0 - s * (x * x + z * z), s * (y * z - x * w)],
        [s * (x * z - y * w), s * (y * z + x * w), 1.0 - s * (x * x + y * y)],
    ])


def mat_to_quat(r):
    """3x3 rotation matrix -> (x, y, z, w)."""
    tr = r[0, 0] + r[1, 1] + r[2, 2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    return float(x), float(y), float(z), float(w)


# --- homogeneous transforms -----------------------------------------------------
def make_t(p, rot):
    t = np.eye(4)
    t[:3, :3] = rot
    t[:3, 3] = p
    return t


def inv_t(t):
    rot = t[:3, :3].T
    out = np.eye(4)
    out[:3, :3] = rot
    out[:3, 3] = -rot @ t[:3, 3]
    return out


def so3_log(rot):
    """Rotation matrix -> rotation vector (axis * angle)."""
    cos_a = max(-1.0, min(1.0, (np.trace(rot) - 1.0) / 2.0))
    angle = math.acos(cos_a)
    if angle < 1e-9:
        return np.zeros(3)
    if math.pi - angle < 1e-6:
        # near pi: use the symmetric part
        m = (rot + np.eye(3)) / 2.0
        axis = np.sqrt(np.maximum(np.diag(m), 0.0))
        i = int(np.argmax(axis))
        axis = m[:, i] / max(axis[i], 1e-12)
        axis = axis / np.linalg.norm(axis)
        return axis * angle
    w = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    return w * (angle / (2.0 * math.sin(angle)))


def so3_exp(w):
    """Rotation vector -> rotation matrix (Rodrigues)."""
    angle = float(np.linalg.norm(w))
    if angle < 1e-12:
        return np.eye(3)
    k = np.asarray(w, float) / angle
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + math.sin(angle) * kx + (1.0 - math.cos(angle)) * (kx @ kx)


def interp_t(ta, tb, s):
    """Interpolate between two transforms, s in [0, 1] (linear + geodesic)."""
    s = min(1.0, max(0.0, float(s)))
    p = (1.0 - s) * ta[:3, 3] + s * tb[:3, 3]
    ra, rb = ta[:3, :3], tb[:3, :3]
    rot = ra @ so3_exp(s * so3_log(ra.T @ rb))
    return make_t(p, rot)


# --- ROS message conversions ----------------------------------------------------
def t_from_pose(pose):
    """geometry_msgs/Pose -> 4x4."""
    q = pose.orientation
    return make_t(
        (pose.position.x, pose.position.y, pose.position.z),
        quat_to_mat(q.x, q.y, q.z, q.w))


def pose_from_t(t):
    """4x4 -> geometry_msgs/Pose."""
    from geometry_msgs.msg import Pose
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = (float(v) for v in t[:3, 3])
    x, y, z, w = mat_to_quat(t[:3, :3])
    pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w = x, y, z, w
    return pose


def chunk_to_msg(chunk, t_anchor, dt, stamp, frame_id='base_link', confidence=0.0):
    """[H, 10] relative actions + anchor -> omx_msgs/EEActionChunk."""
    from omx_msgs.msg import EEActionChunk
    chunk = np.asarray(chunk, float)
    assert chunk.ndim == 2 and chunk.shape[1] == ACTION_DIM, chunk.shape
    msg = EEActionChunk()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.anchor_pose = pose_from_t(t_anchor)
    msg.dt = float(dt)
    msg.confidence = float(confidence)
    for a in chunk:
        msg.deltas.append(pose_from_t(make_t(a[0:3], rot_from_6d(a[3:9]))))
        msg.gripper_width.append(float(a[9]))
    return msg


def msg_to_targets(msg):
    """omx_msgs/EEActionChunk -> (t_anchor, [(T_target_k, width_k), ...])."""
    t_anchor = t_from_pose(msg.anchor_pose)
    widths = list(msg.gripper_width)
    if len(widths) < len(msg.deltas):
        widths += [widths[-1] if widths else 1.0] * (len(msg.deltas) - len(widths))
    targets = [(t_anchor @ t_from_pose(d), float(w)) for d, w in zip(msg.deltas, widths)]
    return t_anchor, targets
