"""Input contract between the EC2 CPU preprocessing server and the GPU server.

The GPU server deliberately does **not** re-implement IMU synchronisation or
ARCore timestamp interpolation.  Everything below is assumed to already be
aligned onto a single per-frame timeline by the CPU layer (handoff doc section 5).

Per episode we need exactly:

    timestamp    [N]            float, seconds, strictly increasing
    rgb          [N, H, W, 3]   uint8, RGB channel order
    position     [N, 3]         camera (or EE) translation
    rotation     [N, ...]       camera (or EE) orientation, see ``rotation_format``
    gripper      [N]            scalar gripper state

``position``/``rotation`` describe ``T_world_camera`` by default; the converter
turns them into ``T_world_ee`` using ``T_camera_to_ee`` from the collector config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

# Field-name aliases.  We do not know the exact key names the CPU server will
# emit, so every reader resolves keys through these lists first and falls back
# to an explicit ``field_map`` override in the collector config.
FIELD_ALIASES: Dict[str, List[str]] = {
    "timestamp": [
        "timestamp", "timestamps", "time", "times", "t", "ts",
        "frame_time", "time_s", "time_sec", "stamp", "frame_timestamp",
    ],
    "rgb": [
        "rgb", "rgbs", "image", "images", "img", "imgs", "frame", "frames",
        "color", "colors", "camera0_rgb", "cam0_rgb", "video",
    ],
    "position": [
        "position", "positions", "pos", "xyz", "translation", "trans",
        "ee_position", "ee_pos", "eef_pos", "tcp_pos", "tcp_position",
        "camera_position", "cam_pos", "camera_pos", "t_world_camera_pos",
    ],
    "rotation": [
        "rotation", "rotations", "rot", "orientation", "quat", "quaternion",
        "ee_rotation", "ee_rot", "ee_quat", "eef_quat", "eef_rot",
        "tcp_rot", "tcp_quat", "camera_rotation", "cam_quat", "camera_quat",
        "rotvec", "rot_vec", "axis_angle", "rot_axis_angle", "euler",
    ],
    "pose_matrix": [
        "pose", "poses", "T_world_camera", "t_world_camera", "T_world_cam",
        "camera_pose", "cam_pose", "ee_pose", "tcp_pose", "transform",
    ],
    "gripper": [
        "gripper", "grippers", "gripper_width", "gripper_state", "grip",
        "grip_width", "width", "gripper_value", "gripper_pos", "gripper_open",
    ],
}


class ContractError(ValueError):
    """Raised when a processed episode does not satisfy the input contract."""


@dataclass
class LowDimData:
    """Per-frame low-dimensional signals of one episode, before pose conversion."""

    timestamp: np.ndarray            # [N] float64, seconds
    position: np.ndarray             # [N, 3] float64
    rotation: np.ndarray             # [N, K] or [N, 3, 3] / [N, 4, 4] float64
    gripper: np.ndarray              # [N] float64
    rotation_format: str             # see omx.data.pose_convert.ROTATION_FORMATS
    source: str = ""                 # human readable provenance
    extra: Dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n_frames(self) -> int:
        return int(self.timestamp.shape[0])


@dataclass
class ProcessedEpisode:
    """Fully converted episode, ready to be written into the UMI ReplayBuffer."""

    rgb: np.ndarray                  # [N, H, W, 3] uint8
    eef_pos: np.ndarray              # [N, 3] float32, metres
    eef_rot_axis_angle: np.ndarray   # [N, 3] float32, rotvec
    gripper_width: np.ndarray        # [N, 1] float32, metres
    timestamp: np.ndarray            # [N] float64, seconds
    episode_id: str = ""


def _fps_from_timestamp(timestamp: np.ndarray) -> Optional[float]:
    if timestamp is None or timestamp.shape[0] < 2:
        return None
    dt = np.diff(timestamp.astype(np.float64))
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if dt.size == 0:
        return None
    return float(1.0 / np.median(dt))


def validate_lowdim(data: LowDimData, n_rgb_frames: Optional[int] = None,
                    strict: bool = True) -> List[str]:
    """Check one episode against the contract.

    Returns the list of warnings.  Hard violations raise ``ContractError`` when
    ``strict`` (the default); with ``strict=False`` they are returned as strings
    so a whole dataset can be scanned before failing.
    """
    problems: List[str] = []
    warnings: List[str] = []

    n = data.n_frames
    if n == 0:
        problems.append("episode has 0 frames")

    for name, arr, expect_last in (
        ("position", data.position, 3),
        ("gripper", data.gripper, None),
    ):
        if arr is None:
            problems.append(f"missing '{name}'")
            continue
        if arr.shape[0] != n:
            problems.append(
                f"'{name}' length {arr.shape[0]} != timestamp length {n}")
        if expect_last is not None and arr.shape[-1] != expect_last:
            problems.append(
                f"'{name}' last dim {arr.shape[-1]} != {expect_last}")

    if data.rotation is None:
        problems.append("missing 'rotation'")
    elif data.rotation.shape[0] != n:
        problems.append(
            f"'rotation' length {data.rotation.shape[0]} != timestamp length {n}")

    if n_rgb_frames is not None and n_rgb_frames != n:
        problems.append(
            f"rgb frame count {n_rgb_frames} != lowdim frame count {n}")

    for name, arr in (("timestamp", data.timestamp), ("position", data.position),
                      ("rotation", data.rotation), ("gripper", data.gripper)):
        if arr is None:
            continue
        a = np.asarray(arr, dtype=np.float64)
        if not np.all(np.isfinite(a)):
            n_bad = int((~np.isfinite(a)).sum())
            problems.append(f"'{name}' contains {n_bad} non-finite values")

    if data.timestamp is not None and n > 1:
        dt = np.diff(data.timestamp.astype(np.float64))
        if np.any(dt <= 0):
            problems.append(
                f"timestamp is not strictly increasing "
                f"({int((dt <= 0).sum())} non-positive steps)")
        else:
            fps = _fps_from_timestamp(data.timestamp)
            jitter = float(np.max(dt) / np.min(dt)) if np.min(dt) > 0 else float("inf")
            if jitter > 2.0:
                warnings.append(
                    f"frame interval jitter is high (max/min dt = {jitter:.2f}); "
                    f"median fps = {fps:.2f}" if fps else "frame interval jitter is high")

    if problems:
        msg = f"[{data.source}] contract violation:\n  - " + "\n  - ".join(problems)
        if strict:
            raise ContractError(msg)
        warnings.append(msg)

    return warnings
