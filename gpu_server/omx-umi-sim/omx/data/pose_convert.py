"""Pose conversion: collector camera pose -> UMI EE pose (handoff doc section 6).

    T_world_ee = T_world_camera @ T_camera_ee

Everything that could plausibly be wrong about the incoming data is an explicit,
recorded option: rotation encoding, world axis handedness/up-axis, and the
position unit.  The exact values used are written into the dataset metadata so a
zarr can always be traced back to the calibration it was built with.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import scipy.spatial.transform as st

ROTATION_FORMATS = (
    "quat_xyzw",    # scipy / ARCore convention
    "quat_wxyz",    # ROS-ish / Eigen convention
    "rotvec",       # axis-angle, what UMI stores
    "matrix",       # [N, 3, 3]
    "matrix4x4",    # [N, 4, 4] homogeneous, translation taken from the matrix
    "euler_xyz",    # intrinsic XYZ, radians
    "euler_zyx",    # intrinsic ZYX, radians
)

# Named world-frame changes of basis.  ``R`` maps a vector expressed in the
# source world frame to the same physical vector expressed in the target frame.
#
#   ARCore world: X right, Y up (opposite gravity), Z toward the user.
#   Robot  world: Z up.  ``arcore_yup_to_zup`` is a +90 deg rotation about X,
#                 so (x, y, z) -> (x, -z, y) and "down" maps to -Z.
WORLD_AXIS_REMAPS = {
    "identity": np.eye(3),
    "arcore_yup_to_zup": np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ]),
    # Inverse of the above, in case the CPU layer already applied it.
    "zup_to_arcore_yup": np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, -1.0, 0.0],
    ]),
}

POSITION_UNIT_SCALE = {"m": 1.0, "meter": 1.0, "metre": 1.0,
                       "cm": 1e-2, "mm": 1e-3}


def rotation_to_matrix(rotation: np.ndarray, fmt: str) -> np.ndarray:
    """[N, ...] rotation in ``fmt`` -> [N, 3, 3] rotation matrices."""
    if fmt not in ROTATION_FORMATS:
        raise ValueError(
            f"unknown rotation_format {fmt!r}; expected one of {ROTATION_FORMATS}")
    rot = np.asarray(rotation, dtype=np.float64)

    if fmt == "quat_xyzw":
        _assert_last(rot, 4, fmt)
        return st.Rotation.from_quat(_normalize_quat(rot)).as_matrix()
    if fmt == "quat_wxyz":
        _assert_last(rot, 4, fmt)
        return st.Rotation.from_quat(_normalize_quat(rot[..., [1, 2, 3, 0]])).as_matrix()
    if fmt == "rotvec":
        _assert_last(rot, 3, fmt)
        return st.Rotation.from_rotvec(rot).as_matrix()
    if fmt == "matrix":
        if rot.shape[-2:] != (3, 3):
            raise ValueError(f"rotation_format={fmt} expects [N,3,3], got {rot.shape}")
        return rot
    if fmt == "matrix4x4":
        if rot.shape[-2:] != (4, 4):
            raise ValueError(f"rotation_format={fmt} expects [N,4,4], got {rot.shape}")
        return rot[..., :3, :3]
    if fmt == "euler_xyz":
        _assert_last(rot, 3, fmt)
        return st.Rotation.from_euler("XYZ", rot).as_matrix()
    if fmt == "euler_zyx":
        _assert_last(rot, 3, fmt)
        return st.Rotation.from_euler("ZYX", rot).as_matrix()
    raise AssertionError("unreachable")


def _assert_last(arr: np.ndarray, size: int, fmt: str) -> None:
    if arr.shape[-1] != size:
        raise ValueError(
            f"rotation_format={fmt} expects last dim {size}, got {arr.shape}")


def _normalize_quat(q: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    bad = (~np.isfinite(n)) | (n < 1e-8)
    if np.any(bad):
        raise ValueError(f"{int(bad.sum())} quaternion(s) have (near) zero norm")
    return q / n


def make_transform(translation, rotation, rotation_format: str = "quat_xyzw") -> np.ndarray:
    """Build a single [4, 4] homogeneous transform."""
    t = np.asarray(translation, dtype=np.float64).reshape(3)
    R = rotation_to_matrix(np.asarray(rotation, dtype=np.float64)[None, ...],
                           rotation_format)[0]
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def build_pose_matrices(position: np.ndarray, rotation: np.ndarray,
                        rotation_format: str,
                        position_unit: str = "m") -> np.ndarray:
    """[N,3] + [N,...] -> [N,4,4] ``T_world_source``, positions in metres."""
    rot = np.asarray(rotation, dtype=np.float64)
    if rotation_format == "matrix4x4":
        # translation lives inside the matrix; ignore the separate position array
        pos = rot[..., :3, 3]
    else:
        pos = np.asarray(position, dtype=np.float64)
        if pos.shape[-1] != 3:
            raise ValueError(f"position must be [N,3], got {pos.shape}")

    scale = POSITION_UNIT_SCALE.get(str(position_unit).lower())
    if scale is None:
        raise ValueError(
            f"unknown position_unit {position_unit!r}; "
            f"expected one of {sorted(POSITION_UNIT_SCALE)}")

    R = rotation_to_matrix(rot, rotation_format)
    n = R.shape[0]
    T = np.zeros((n, 4, 4), dtype=np.float64)
    T[:, :3, :3] = R
    T[:, :3, 3] = pos * scale
    T[:, 3, 3] = 1.0
    return T


def apply_world_axis_remap(T_world_x: np.ndarray, remap) -> np.ndarray:
    """Re-express poses in a rotated world frame: ``T' = G @ T``."""
    if remap is None:
        return T_world_x
    if isinstance(remap, str):
        if remap not in WORLD_AXIS_REMAPS:
            raise ValueError(
                f"unknown world_axis_remap {remap!r}; "
                f"expected one of {sorted(WORLD_AXIS_REMAPS)}")
        R = WORLD_AXIS_REMAPS[remap]
    else:
        R = np.asarray(remap, dtype=np.float64).reshape(3, 3)
    if abs(np.linalg.det(R) - 1.0) > 1e-6:
        raise ValueError(
            f"world_axis_remap must be a proper rotation (det=+1), got det={np.linalg.det(R):.6f}. "
            "A det=-1 matrix would flip handedness and silently mirror the whole dataset.")
    G = np.eye(4, dtype=np.float64)
    G[:3, :3] = R
    return G[None, ...] @ T_world_x


def camera_to_ee(T_world_camera: np.ndarray, T_camera_ee: np.ndarray) -> np.ndarray:
    """``T_world_ee = T_world_camera @ T_camera_ee`` (handoff doc section 6)."""
    T_camera_ee = np.asarray(T_camera_ee, dtype=np.float64).reshape(4, 4)
    return T_world_camera @ T_camera_ee[None, ...]


def mat_to_pos_rotvec(T: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """[N,4,4] -> ([N,3] position, [N,3] axis-angle), the UMI storage format."""
    pos = T[:, :3, 3]
    rotvec = st.Rotation.from_matrix(T[:, :3, :3]).as_rotvec()
    return pos, rotvec


def pos_rotvec_to_pose6(pos: np.ndarray, rotvec: np.ndarray) -> np.ndarray:
    """[N,3] + [N,3] -> [N,6], the ``demo_start_pose`` / ``demo_end_pose`` layout."""
    return np.concatenate([pos, rotvec], axis=-1)


def unwrap_rotvec(rotvec: np.ndarray) -> np.ndarray:
    """Pick the +-2pi-equivalent axis-angle closest to the previous frame.

    ``scipy`` returns rotation vectors with angle in [0, pi], so a trajectory can
    jump by ~2pi between consecutive frames even though the physical rotation is
    smooth.  The UMI sampler slerps through ``Rotation.from_rotvec`` so the
    stored discontinuity is harmless for training, but it makes trajectory plots
    and range statistics unreadable.  This keeps them continuous.
    """
    out = np.array(rotvec, dtype=np.float64, copy=True)
    for i in range(1, out.shape[0]):
        prev, cur = out[i - 1], out[i]
        angle = np.linalg.norm(cur)
        if angle < 1e-8:
            continue
        axis = cur / angle
        # candidates: angle + 2*pi*k about +axis, and (2*pi - angle) about -axis
        best, best_d = cur, np.linalg.norm(cur - prev)
        for k in (-1, 1):
            cand = axis * (angle + 2.0 * np.pi * k)
            d = np.linalg.norm(cand - prev)
            if d < best_d:
                best, best_d = cand, d
        out[i] = best
    return out
