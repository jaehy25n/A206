#!/usr/bin/env python3
"""Build deterministic, episode-scoped processed_v1 data from uploaded sessions.

The implementation deliberately uses only Python's standard library and
ffmpeg/ffprobe. ``frames.csv`` is the canonical row table; ``trajectory.npz``
is written as a standards-compatible NumPy archive without requiring NumPy at
preprocessing time.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence


VERSION = "processed_v1"
HANDOFF_CONTRACT_VERSION = "omx_processed_v1_posefix_1"
REQUIRED_FILES = {
    "metadata.json",
    "main_rgb.mp4",
    "main_frame_timestamps.csv",
    "arcore_poses.csv",
    "episodes.csv",
    "accelerometer.csv",
    "gyroscope.csv",
    "rotation_vector.csv",
}
EXPECTED_HEADERS = {
    "main_frame_timestamps.csv": ["frame_number", "timestamp_ns", "timestamp_source"],
    "arcore_poses.csv": [
        "android_camera_timestamp_ns", "tx", "ty", "tz", "qx", "qy", "qz", "qw",
        "tracking_state", "tracking_failure_reason",
    ],
    "episodes.csv": ["episode_id", "start_timestamp_ns", "end_timestamp_ns", "task", "object", "outcome"],
    "accelerometer.csv": ["timestamp_ns", "x", "y", "z", "accuracy"],
    "gyroscope.csv": ["timestamp_ns", "x", "y", "z", "accuracy"],
    "rotation_vector.csv": [
        "timestamp_ns", "x", "y", "z", "scalar_component", "heading_accuracy_rad", "accuracy",
    ],
}
FRAME_COLUMNS = [
    "frame_idx", "timestamp_ns", "timestamp_source", "rgb_frame_index", "tracking_state",
    "camera_tx", "camera_ty", "camera_tz", "camera_qx", "camera_qy", "camera_qz", "camera_qw",
    "pose_valid", "pose_valid_original", "pose_interpolated", "tracking_failure_reason", "rgb_path",
]
BOOL_FRAME_COLUMNS = ("pose_valid", "pose_valid_original", "pose_interpolated")
QUALITY_DEFAULTS = {
    "valid_min_tracking_ratio": 0.98,
    "valid_max_paused_duration_ms": 100.0,
    "invalid_max_paused_duration_ms": 2000.0,
    "thresholds_finalized": False,
}
POSE_VALIDITY_DEFAULTS = {
    # Only these ARCore tracking states may carry a usable pose. PAUSED/MISSING
    # rows in real uploads still carry a filled-in dummy pose, so the numeric
    # checks below cannot stand alone.
    "usable_tracking_states": ["TRACKING"],
    "quaternion_norm_tolerance": 0.1,
}
POSE_GAP_DEFAULTS = {
    # A dropout no longer than this is repaired in place; anything longer splits
    # the episode. 2 frames at 30 Hz is ~67 ms.
    "interpolate_max_frames": 2,
    "interpolate_max_gap_ms": 100.0,
}
TRAJECTORY_QUALITY_DEFAULTS = {
    # A published segment must be long enough for the GPU SequenceSampler to
    # build a sample with action_padding=False. CPU and GPU gate on the same
    # number of source frames; the reference rates record what it was derived
    # from, and the loader refuses a value below what they imply.
    "min_publish_segment_frames": 48,
    "source_hz_reference": 30.0,
    "policy_hz_reference": 10.0,
    "action_horizon_reference": 16,
    "thresholds_finalized": False,
}
DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 1,
    "timestamp_alignment": {
        "max_interval_error_ms": 2.0,
        "max_relative_error_ms": 10.0,
    },
    "quality_thresholds": QUALITY_DEFAULTS,
    "pose_validity": POSE_VALIDITY_DEFAULTS,
    "pose_gap": POSE_GAP_DEFAULTS,
    "trajectory_quality": TRAJECTORY_QUALITY_DEFAULTS,
    "calibration": {
        "T_camera_EE": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        "status": "placeholder_identity_not_for_training",
    },
    "rgb": {"jpeg_qscale": 2},
}


class PreprocessError(RuntimeError):
    """Raised when a raw session cannot be safely mapped into processed_v1."""


def _run(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise PreprocessError(f"Required executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise PreprocessError(f"Command failed ({' '.join(command[:3])}...): {details}") from exc
    return result.stdout


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreprocessError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreprocessError(f"Expected a JSON object in {path}")
    return value


def _read_csv(path: Path, expected_header: list[str] | None = None) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise PreprocessError(f"CSV has no header: {path.name}")
            if expected_header is not None and reader.fieldnames != expected_header:
                raise PreprocessError(
                    f"Unexpected header in {path.name}: {reader.fieldnames!r}; expected {expected_header!r}"
                )
            rows = list(reader)
    except OSError as exc:
        raise PreprocessError(f"Cannot read CSV {path}: {exc}") from exc
    if any(None in row for row in rows):
        raise PreprocessError(f"CSV has rows with extra columns: {path.name}")
    return rows


def _int_field(row: dict[str, str], key: str, source: str) -> int:
    try:
        return int(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError(f"Invalid integer {key!r} in {source}: {row.get(key)!r}") from exc


def _float_field(row: dict[str, str], key: str, source: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError(f"Invalid float {key!r} in {source}: {row.get(key)!r}") from exc
    if not math.isfinite(value):
        raise PreprocessError(f"Non-finite value {key!r} in {source}: {row.get(key)!r}")
    return value


def _validate_strictly_increasing(values: Sequence[int], label: str) -> None:
    for index in range(1, len(values)):
        if values[index] <= values[index - 1]:
            raise PreprocessError(
                f"{label} must be strictly increasing; rows {index - 1}/{index}: "
                f"{values[index - 1]} >= {values[index]}"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_manifest(session_dir: Path, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = metadata.get("files")
    if not isinstance(entries, list):
        raise PreprocessError("metadata.json has no files manifest")
    manifest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PreprocessError("metadata.json contains a malformed manifest entry")
        name = entry.get("path")
        if not isinstance(name, str) or Path(name).name != name or name in manifest:
            raise PreprocessError(f"Unsafe or duplicate manifest path: {name!r}")
        path = session_dir / name
        size = entry.get("sizeBytes", entry.get("size_bytes"))
        digest = entry.get("sha256")
        if not path.is_file():
            raise PreprocessError(f"Manifest file is missing: {name}")
        if not isinstance(size, int) or path.stat().st_size != size:
            raise PreprocessError(f"Manifest size mismatch: {name}")
        if not isinstance(digest, str) or _sha256(path) != digest.lower():
            raise PreprocessError(f"Manifest SHA-256 mismatch: {name}")
        manifest[name] = {"size_bytes": size, "sha256": digest.lower()}
    # metadata.json cannot include its own digest without a recursive contract.
    missing = (REQUIRED_FILES - {"metadata.json"}) - set(manifest)
    if missing:
        raise PreprocessError(f"Required files absent from manifest: {sorted(missing)}")
    return manifest


def _load_session(session_dir: Path) -> dict[str, Any]:
    if not session_dir.is_dir():
        raise PreprocessError(f"Not a session directory: {session_dir}")
    actual_missing = [name for name in REQUIRED_FILES if not (session_dir / name).is_file()]
    if actual_missing:
        raise PreprocessError(f"Required files missing: {sorted(actual_missing)}")
    metadata = _read_json(session_dir / "metadata.json")
    if metadata.get("session_id") != session_dir.name:
        raise PreprocessError(
            f"metadata session_id {metadata.get('session_id')!r} does not match directory {session_dir.name!r}"
        )
    manifest = _validate_manifest(session_dir, metadata)

    frame_rows = _read_csv(session_dir / "main_frame_timestamps.csv", EXPECTED_HEADERS["main_frame_timestamps.csv"])
    frames = [
        {"timestamp_ns": _int_field(row, "timestamp_ns", "main_frame_timestamps.csv"),
         "timestamp_source": row["timestamp_source"]}
        for row in frame_rows
    ]
    if not frames:
        raise PreprocessError("main_frame_timestamps.csv has no frames")
    _validate_strictly_increasing([row["timestamp_ns"] for row in frames], "RGB timestamp_ns")

    pose_rows = _read_csv(session_dir / "arcore_poses.csv", EXPECTED_HEADERS["arcore_poses.csv"])
    poses: dict[int, dict[str, Any]] = {}
    pose_timestamps: list[int] = []
    for row in pose_rows:
        timestamp = _int_field(row, "android_camera_timestamp_ns", "arcore_poses.csv")
        if timestamp in poses:
            raise PreprocessError(f"Duplicate ARCore timestamp_ns: {timestamp}")
        pose_timestamps.append(timestamp)
        poses[timestamp] = row
    _validate_strictly_increasing(pose_timestamps, "ARCore timestamp_ns")

    episode_rows = _read_csv(session_dir / "episodes.csv", EXPECTED_HEADERS["episodes.csv"])
    episodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in episode_rows:
        episode_id = row["episode_id"]
        if not episode_id or episode_id in seen_ids:
            raise PreprocessError(f"Empty or duplicate episode_id: {episode_id!r}")
        seen_ids.add(episode_id)
        start = _int_field(row, "start_timestamp_ns", "episodes.csv")
        end = _int_field(row, "end_timestamp_ns", "episodes.csv")
        if start >= end:
            raise PreprocessError(f"Episode {episode_id} has start >= end")
        episodes.append({**row, "start_timestamp_ns": start, "end_timestamp_ns": end})
    episodes.sort(key=lambda item: (item["start_timestamp_ns"], item["episode_id"]))
    for previous, current in zip(episodes, episodes[1:]):
        if current["start_timestamp_ns"] < previous["end_timestamp_ns"]:
            raise PreprocessError(
                f"Episode overlap: {previous['episode_id']} and {current['episode_id']}"
            )

    sensors: dict[str, list[dict[str, str]]] = {}
    for name in ("accelerometer.csv", "gyroscope.csv", "rotation_vector.csv"):
        rows = _read_csv(session_dir / name, EXPECTED_HEADERS[name])
        timestamps = [_int_field(row, "timestamp_ns", name) for row in rows]
        _validate_strictly_increasing(timestamps, f"{name} timestamp_ns")
        sensors[name] = rows

    return {
        "session_id": session_dir.name,
        "source_path": str(session_dir),
        "metadata": metadata,
        "manifest": manifest,
        "frames": frames,
        "poses": poses,
        "pose_count": len(poses),
        "episodes": episodes,
        "sensors": sensors,
    }


def _probe_video(video_path: Path) -> tuple[list[int], int, str | None]:
    output = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames,time_base:frame=pts_time",
        "-show_frames", "-of", "json", str(video_path),
    ])
    try:
        probe = json.loads(output)
        stream = probe["streams"][0]
        pts = [
            int((Decimal(frame["pts_time"]) * Decimal(1_000_000_000)).to_integral_value())
            for frame in probe.get("frames", [])
        ]
        decoded_count = int(stream["nb_read_frames"])
        time_base = stream.get("time_base")
    except (KeyError, IndexError, ValueError, TypeError, ArithmeticError) as exc:
        raise PreprocessError(f"Cannot parse ffprobe frame PTS for {video_path.name}: {exc}") from exc
    if not pts or decoded_count <= 0:
        raise PreprocessError(f"Video has no decodable frames: {video_path.name}")
    if len(pts) != decoded_count:
        raise PreprocessError(
            f"ffprobe listed {len(pts)} PTS rows but decoded {decoded_count} frames"
        )
    _validate_strictly_increasing(pts, "MP4 PTS")
    return pts, decoded_count, time_base


def _alignment_report(
    timestamps: Sequence[int], pts_ns: Sequence[int], common_count: int, config: dict[str, Any]
) -> dict[str, Any]:
    if common_count < 2:
        raise PreprocessError("At least two common CSV/MP4 frames are needed for sequence validation")
    relative_errors = [
        (timestamps[index] - timestamps[0]) - (pts_ns[index] - pts_ns[0])
        for index in range(common_count)
    ]
    interval_errors = [relative_errors[index] - relative_errors[index - 1] for index in range(1, common_count)]
    max_relative_ms = max(abs(value) for value in relative_errors) / 1_000_000.0
    max_interval_ms = max(abs(value) for value in interval_errors) / 1_000_000.0
    median_rgb_interval_ms = statistics.median(
        (timestamps[index] - timestamps[index - 1]) / 1_000_000.0
        for index in range(1, common_count)
    )
    median_pts_interval_ms = statistics.median(
        (pts_ns[index] - pts_ns[index - 1]) / 1_000_000.0
        for index in range(1, common_count)
    )
    max_gap_ms = max(
        max((timestamps[index] - timestamps[index - 1]) / 1_000_000.0 for index in range(1, common_count)),
        max((pts_ns[index] - pts_ns[index - 1]) / 1_000_000.0 for index in range(1, common_count)),
    )
    if max_interval_ms > float(config["max_interval_error_ms"]):
        raise PreprocessError(
            f"RGB/MP4 interval sequences diverge by {max_interval_ms:.3f}ms "
            f"(limit {config['max_interval_error_ms']}ms)"
        )
    if max_relative_ms > float(config["max_relative_error_ms"]):
        raise PreprocessError(
            f"RGB/MP4 relative timelines diverge by {max_relative_ms:.3f}ms "
            f"(limit {config['max_relative_error_ms']}ms)"
        )
    return {
        "method": "first-sample-relative; ordered common-prefix mapping",
        "common_frame_count": common_count,
        "csv_timestamp_row_count": len(timestamps),
        "mp4_decoded_frame_count": len(pts_ns),
        "csv_rows_without_encoded_frame": max(0, len(timestamps) - len(pts_ns)),
        "mp4_frames_without_csv_timestamp": max(0, len(pts_ns) - len(timestamps)),
        "max_relative_error_ms": max_relative_ms,
        "max_interval_error_ms": max_interval_ms,
        "median_rgb_interval_ms": median_rgb_interval_ms,
        "median_mp4_pts_interval_ms": median_pts_interval_ms,
        "max_common_interval_ms": max_gap_ms,
        "first_sample_identity_assumed": True,
        "absolute_clock_offset_verified": False,
    }


def _matrix_identity() -> list[list[float]]:
    return [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]


def matrix_multiply(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> list[list[float]]:
    return [
        [sum(left[row][index] * right[index][column] for index in range(4)) for column in range(4)]
        for row in range(4)
    ]


def invert_rigid_transform(transform: Sequence[Sequence[float]]) -> list[list[float]]:
    rotation_t = [[transform[column][row] for column in range(3)] for row in range(3)]
    translation = [transform[row][3] for row in range(3)]
    inverse_translation = [-sum(rotation_t[row][column] * translation[column] for column in range(3)) for row in range(3)]
    inverse = _matrix_identity()
    for row in range(3):
        for column in range(3):
            inverse[row][column] = rotation_t[row][column]
        inverse[row][3] = inverse_translation[row]
    return inverse


def quaternion_xyzw_to_matrix(quaternion: Sequence[float]) -> list[list[float]]:
    """Return active rotation for an [x,y,z,w] unit quaternion."""
    x, y, z, w = (float(value) for value in quaternion)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("Quaternion must be finite and non-zero")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def quaternion_normalize(quaternion: Sequence[float]) -> list[float]:
    values = [float(value) for value in quaternion]
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("Quaternion must be finite and non-zero")
    return [value / norm for value in values]


def quaternion_slerp(start: Sequence[float], end: Sequence[float], alpha: float) -> list[float]:
    """Shortest-arc SLERP between two [x,y,z,w] quaternions.

    Component-wise linear interpolation is only used as the degenerate
    small-angle fallback, where it is numerically equal to SLERP.
    """
    first = quaternion_normalize(start)
    second = quaternion_normalize(end)
    dot = sum(left * right for left, right in zip(first, second))
    if dot < 0.0:
        second = [-value for value in second]
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 1.0 - 1e-9:
        blended = [left + alpha * (right - left) for left, right in zip(first, second)]
        return quaternion_normalize(blended)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    scale_first = math.sin((1.0 - alpha) * theta) / sin_theta
    scale_second = math.sin(alpha * theta) / sin_theta
    return quaternion_normalize([
        scale_first * left + scale_second * right for left, right in zip(first, second)
    ])


def pose_to_transform(translation: Sequence[float], quaternion_xyzw: Sequence[float]) -> list[list[float]]:
    rotation = quaternion_xyzw_to_matrix(quaternion_xyzw)
    result = _matrix_identity()
    for row in range(3):
        for column in range(3):
            result[row][column] = rotation[row][column]
        result[row][3] = float(translation[row])
    return result


def camera_to_ee_transform(
    T_world_camera: Sequence[Sequence[float]], T_camera_EE: Sequence[Sequence[float]]
) -> list[list[float]]:
    """Apply the configured T_world_camera × T_camera_EE interface."""
    return matrix_multiply(T_world_camera, T_camera_EE)


def relative_transform_actions(
    transforms: Sequence[Sequence[Sequence[float]]],
    valid: Sequence[bool],
    horizon: int = 1,
) -> tuple[list[list[list[float]]], list[tuple[int, int]]]:
    """Generate valid-pair actions inv(T_t) × T_(t+h); no interpolation/skipping."""
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if len(valid) != len(transforms):
        raise ValueError("validity mask length must match transforms")
    matrices: list[list[list[float]]] = []
    pairs: list[tuple[int, int]] = []
    for start in range(max(0, len(transforms) - horizon)):
        end = start + horizon
        if valid[start] and valid[end]:
            matrices.append(matrix_multiply(invert_rigid_transform(transforms[start]), transforms[end]))
            pairs.append((start, end))
    return matrices, pairs


def _validate_transform(transform: Any) -> list[list[float]]:
    try:
        matrix = [[float(value) for value in row] for row in transform]
    except (TypeError, ValueError) as exc:
        raise PreprocessError("calibration.T_camera_EE must be a finite 4x4 matrix") from exc
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise PreprocessError("calibration.T_camera_EE must be a finite 4x4 matrix")
    if any(not math.isfinite(value) for row in matrix for value in row):
        raise PreprocessError("calibration.T_camera_EE contains non-finite values")
    if any(abs(matrix[3][column] - expected) > 1e-6 for column, expected in enumerate((0.0, 0.0, 0.0, 1.0))):
        raise PreprocessError("calibration.T_camera_EE bottom row must be [0,0,0,1]")
    rotation = [row[:3] for row in matrix[:3]]
    for row in range(3):
        for column in range(3):
            dot = sum(rotation[axis][row] * rotation[axis][column] for axis in range(3))
            if abs(dot - (1.0 if row == column else 0.0)) > 1e-3:
                raise PreprocessError("calibration.T_camera_EE rotation must be orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if abs(determinant - 1.0) > 1e-3:
        raise PreprocessError("calibration.T_camera_EE rotation must be proper (determinant +1)")
    return matrix


def _load_config(path: Path) -> dict[str, Any]:
    # Defaults go through the same validation, so a missing config file and an
    # explicit one that restates the defaults produce identical output.
    supplied = _read_json(path) if path.exists() else {}
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in supplied.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    config["calibration"]["T_camera_EE"] = _validate_transform(config["calibration"].get("T_camera_EE"))
    thresholds = config["quality_thresholds"]
    for key in ("valid_min_tracking_ratio", "valid_max_paused_duration_ms", "invalid_max_paused_duration_ms"):
        if key not in thresholds or not math.isfinite(float(thresholds[key])):
            raise PreprocessError(f"Invalid quality threshold {key}")
    if not 0 <= float(thresholds["valid_min_tracking_ratio"]) <= 1:
        raise PreprocessError("valid_min_tracking_ratio must be within [0,1]")
    if float(thresholds["valid_max_paused_duration_ms"]) < 0 or float(thresholds["invalid_max_paused_duration_ms"]) < 0:
        raise PreprocessError("Paused-duration thresholds must be non-negative")
    if float(thresholds["invalid_max_paused_duration_ms"]) < float(thresholds["valid_max_paused_duration_ms"]):
        raise PreprocessError("invalid_max_paused_duration_ms must not be below valid_max_paused_duration_ms")
    for key in ("max_interval_error_ms", "max_relative_error_ms"):
        try:
            value = float(config["timestamp_alignment"][key])
        except (KeyError, TypeError, ValueError) as exc:
            raise PreprocessError(f"Invalid timestamp alignment threshold {key}") from exc
        if not math.isfinite(value) or value <= 0:
            raise PreprocessError(f"{key} must be a positive finite number")

    validity = config["pose_validity"]
    states = validity.get("usable_tracking_states")
    if not isinstance(states, list) or not states or not all(isinstance(item, str) and item for item in states):
        raise PreprocessError("pose_validity.usable_tracking_states must be a non-empty list of strings")
    validity["usable_tracking_states"] = [state.strip().upper() for state in states]
    tolerance = _positive_float(validity, "quaternion_norm_tolerance", "pose_validity", allow_zero=True)
    if tolerance >= 1.0:
        raise PreprocessError("pose_validity.quaternion_norm_tolerance must be below 1.0")

    gap = config["pose_gap"]
    try:
        max_frames = int(gap["interpolate_max_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError("pose_gap.interpolate_max_frames must be an integer") from exc
    if max_frames < 0:
        raise PreprocessError("pose_gap.interpolate_max_frames must be non-negative")
    gap["interpolate_max_frames"] = max_frames
    _positive_float(gap, "interpolate_max_gap_ms", "pose_gap", allow_zero=True)

    trajectory = config["trajectory_quality"]
    try:
        min_publish_frames = int(trajectory["min_publish_segment_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError("trajectory_quality.min_publish_segment_frames must be an integer") from exc
    if min_publish_frames < 2:
        raise PreprocessError("trajectory_quality.min_publish_segment_frames must be at least 2")
    trajectory["min_publish_segment_frames"] = min_publish_frames
    source_hz = _positive_float(trajectory, "source_hz_reference", "trajectory_quality")
    policy_hz = _positive_float(trajectory, "policy_hz_reference", "trajectory_quality")
    try:
        horizon = int(trajectory["action_horizon_reference"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError("trajectory_quality.action_horizon_reference must be an integer") from exc
    if horizon < 1:
        raise PreprocessError("trajectory_quality.action_horizon_reference must be positive")
    trajectory["action_horizon_reference"] = horizon
    # A segment shorter than this yields no sample under action_padding=False,
    # which the GPU treats as a contract error. Publishing one would export the
    # failure instead of preventing it, so a too-small threshold is refused here
    # rather than silently raised at use.
    implied = math.ceil(horizon * source_hz / policy_hz)
    trajectory["implied_min_publish_segment_frames"] = implied
    if min_publish_frames < implied:
        raise PreprocessError(
            f"trajectory_quality.min_publish_segment_frames ({min_publish_frames}) is below the "
            f"{implied} source frames required by the reference policy contract "
            f"(action_horizon {horizon} at {policy_hz} Hz policy over {source_hz} Hz source)"
        )
    return config


def _positive_float(block: dict[str, Any], key: str, label: str, allow_zero: bool = False) -> float:
    try:
        value = float(block[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreprocessError(f"Invalid {label}.{key}") from exc
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise PreprocessError(f"{label}.{key} must be a {'non-negative' if allow_zero else 'positive'} finite number")
    block[key] = value
    return value


def _handoff_contract(config: dict[str, Any]) -> dict[str, Any]:
    """The numbers the GPU side must agree with, recorded in the output itself.

    This preprocessor cannot see the GPU's configuration, so its own config
    check cannot detect the GPU moving first. Publishing the values the output
    was built against lets the GPU inspector fail on a mismatch instead of both
    sides drifting apart silently.
    """
    trajectory = config["trajectory_quality"]
    return {
        "version": HANDOFF_CONTRACT_VERSION,
        "source_hz_reference": float(trajectory["source_hz_reference"]),
        "policy_hz_reference": float(trajectory["policy_hz_reference"]),
        "action_horizon_reference": int(trajectory["action_horizon_reference"]),
        "min_publish_segment_frames": int(trajectory["min_publish_segment_frames"]),
    }


def _classify_quality(metrics: dict[str, Any], thresholds: dict[str, Any]) -> tuple[str, list[str]]:
    invalid_reasons: list[str] = []
    if metrics["total_frame_count"] == 0:
        invalid_reasons.append("NO_RGB_FRAMES_IN_EPISODE")
    if metrics["valid_pose_count"] == 0:
        invalid_reasons.append("NO_VALID_TRACKING_POSE")
    if metrics["max_paused_duration_ms"] >= float(thresholds["invalid_max_paused_duration_ms"]):
        invalid_reasons.append("PAUSED_DURATION_EXCEEDS_PROVISIONAL_LIMIT")
    if invalid_reasons:
        return "INVALID_TRACKING", invalid_reasons
    if (
        metrics["tracking_ratio"] >= float(thresholds["valid_min_tracking_ratio"])
        and metrics["max_paused_duration_ms"] <= float(thresholds["valid_max_paused_duration_ms"])
        and metrics["num_paused_segments"] == 0
    ):
        return "VALID", []
    return "DEGRADED", []


def _max_paused_duration(frames: Sequence[dict[str, Any]]) -> tuple[float, int]:
    if not frames:
        return 0.0, 0
    intervals = [
        frames[index]["timestamp_ns"] - frames[index - 1]["timestamp_ns"]
        for index in range(1, len(frames))
    ]
    sample_interval = int(statistics.median(intervals)) if intervals else 0
    segments: list[tuple[int, int]] = []
    segment_start: int | None = None
    for index, frame in enumerate(frames):
        if frame["tracking_state"] == "PAUSED":
            if segment_start is None:
                segment_start = index
        elif segment_start is not None:
            segments.append((segment_start, index))
            segment_start = None
    if segment_start is not None:
        segments.append((segment_start, len(frames)))
    durations = []
    for start, end_exclusive in segments:
        if end_exclusive < len(frames):
            end_ns = frames[end_exclusive]["timestamp_ns"]
        else:
            end_ns = frames[end_exclusive - 1]["timestamp_ns"] + sample_interval
        durations.append(max(0, end_ns - frames[start]["timestamp_ns"]) / 1_000_000.0)
    return max(durations, default=0.0), len(segments)


def _npy_bytes(dtype: str, shape: tuple[int, ...], values: Sequence[Any]) -> bytes:
    if dtype not in {"<f8", "<i8", "|b1"}:
        raise ValueError(f"Unsupported npy dtype {dtype}")
    expected_count = math.prod(shape)
    if len(values) != expected_count:
        raise ValueError(f"Array shape {shape} needs {expected_count} values, got {len(values)}")
    if len(shape) == 0:
        shape_repr = "()"
    elif len(shape) == 1:
        shape_repr = f"({shape[0]},)"
    else:
        shape_repr = "(" + ", ".join(str(value) for value in shape) + ")"
    header = f"{{'descr': '{dtype}', 'fortran_order': False, 'shape': {shape_repr}, }}"
    padding = (16 - ((10 + len(header) + 1) % 16)) % 16
    header_bytes = (header + " " * padding + "\n").encode("latin1")
    if len(header_bytes) > 65535:
        raise ValueError("NPY v1 header is too long")
    if not values:
        data = b""
    elif dtype == "<f8":
        data = struct.pack("<" + "d" * len(values), *(float(value) for value in values))
    elif dtype == "<i8":
        data = struct.pack("<" + "q" * len(values), *(int(value) for value in values))
    else:
        data = bytes(1 if value else 0 for value in values)
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header_bytes)) + header_bytes + data


def _write_npz(path: Path, arrays: dict[str, tuple[str, tuple[int, ...], Sequence[Any]]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(arrays):
            dtype, shape, values = arrays[name]
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, _npy_bytes(dtype, shape, values), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def _flatten_matrices(matrices: Sequence[Sequence[Sequence[float]]]) -> list[float]:
    return [float(value) for matrix in matrices for row in matrix for value in row]


def _write_frames_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FRAME_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = dict(row)
            for column in BOOL_FRAME_COLUMNS:
                output[column] = "true" if row[column] else "false"
            for column in FRAME_COLUMNS:
                if output.get(column) is None:
                    output[column] = ""
            writer.writerow(output)


def _write_sensor_csv(path: Path, rows: Sequence[dict[str, str]], start: int, end: int) -> int:
    header = list(rows[0]) if rows else EXPECTED_HEADERS[path.name]
    selected = [row for row in rows if start <= int(row["timestamp_ns"]) <= end]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(selected)
    return len(selected)


def _safe_episode_name(episode_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_")
    if not slug:
        raise PreprocessError(f"Cannot make a safe folder for episode_id {episode_id!r}")
    return f"episode_{slug}"


def _episode_frames(
    episode: dict[str, Any],
    all_frames: Sequence[dict[str, Any]],
    common_count: int,
    first_valid_ts: int,
) -> tuple[list[dict[str, Any]], int, int, int]:
    episode_start = episode["start_timestamp_ns"]
    episode_end = episode["end_timestamp_ns"]
    effective_start = max(episode_start, first_valid_ts)
    selected: list[dict[str, Any]] = []
    for rgb_index, frame in enumerate(all_frames[:common_count]):
        timestamp = frame["timestamp_ns"]
        if effective_start <= timestamp <= episode_end:
            selected.append({"rgb_frame_index": rgb_index, **frame})
    # These count source MP4 frames excluded by the episode window. No frames
    # are estimated or synthesized outside the recorded range.
    trimmed_start = sum(
        1 for frame in all_frames[:common_count]
        if frame["timestamp_ns"] < effective_start
    )
    trimmed_end = sum(
        1 for frame in all_frames[:common_count]
        if frame["timestamp_ns"] > episode_end
    )
    unencoded_rows_in_episode = sum(
        1 for index, frame in enumerate(all_frames)
        if index >= common_count and effective_start <= frame["timestamp_ns"] <= episode_end
    )
    return selected, trimmed_start, trimmed_end, unencoded_rows_in_episode


def _make_episode_rows(
    selected: Sequence[dict[str, Any]],
    poses: dict[int, dict[str, Any]],
    validity: dict[str, Any],
) -> list[dict[str, Any]]:
    """Join RGB frames to ARCore poses and decide per-frame pose validity.

    A pose counts as usable only when the reported tracking state is usable AND
    every translation/rotation component is present and finite AND the
    quaternion norm is within tolerance of unity. Real uploads fill PAUSED and
    MISSING rows with a constant dummy pose, so the state gate is load-bearing
    and the numeric checks alone would accept unusable samples.
    """
    usable_states = set(validity["usable_tracking_states"])
    tolerance = float(validity["quaternion_norm_tolerance"])
    result: list[dict[str, Any]] = []
    for episode_index, frame in enumerate(selected):
        timestamp = frame["timestamp_ns"]
        pose = poses.get(timestamp)
        if pose is None:
            tracking_state = "MISSING"
            reason = "MISSING_POSE"
            translation: list[float] | None = None
            quaternion: list[float] | None = None
            pose_valid = False
        else:
            tracking_state = pose["tracking_state"].strip().upper()
            reason = pose["tracking_failure_reason"].strip() or "UNKNOWN"
            state_usable = tracking_state in usable_states
            try:
                raw_translation = [_float_field(pose, key, "arcore_poses.csv") for key in ("tx", "ty", "tz")]
                raw_quaternion = [_float_field(pose, key, "arcore_poses.csv") for key in ("qx", "qy", "qz", "qw")]
                norm = math.sqrt(sum(value * value for value in raw_quaternion))
                numbers_usable = math.isfinite(norm) and abs(norm - 1.0) <= tolerance
                pose_valid = state_usable and numbers_usable
                if pose_valid:
                    # Validate rotation here; invalid tracking samples remain present but unusable.
                    quaternion_xyzw_to_matrix(raw_quaternion)
                    translation, quaternion = raw_translation, raw_quaternion
                else:
                    translation, quaternion = None, None
                if state_usable and not numbers_usable:
                    reason = "INVALID_TRACKING_POSE"
            except (PreprocessError, ValueError):
                # A usable state with unreadable numbers is a contradiction, not
                # a usable pose; record it as such instead of trusting the flag.
                tracking_state = "INVALID_POSE" if state_usable else tracking_state
                reason = "INVALID_TRACKING_POSE"
                translation, quaternion, pose_valid = None, None, False
        result.append({
            "frame_idx": episode_index,
            "episode_frame_idx": episode_index,
            "timestamp_ns": timestamp,
            "timestamp_source": frame["timestamp_source"],
            "rgb_frame_index": frame["rgb_frame_index"],
            "tracking_state": tracking_state,
            "camera_tx": translation[0] if translation is not None else None,
            "camera_ty": translation[1] if translation is not None else None,
            "camera_tz": translation[2] if translation is not None else None,
            "camera_qx": quaternion[0] if quaternion is not None else None,
            "camera_qy": quaternion[1] if quaternion is not None else None,
            "camera_qz": quaternion[2] if quaternion is not None else None,
            "camera_qw": quaternion[3] if quaternion is not None else None,
            "pose_valid": pose_valid,
            "pose_valid_original": pose_valid,
            "pose_interpolated": False,
            "tracking_failure_reason": reason,
            "rgb_path": None,
        })
    return result


def _interpolate_pose(row: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> None:
    """Fill one dropout frame from its bounding valid poses, in place."""
    span = after["timestamp_ns"] - before["timestamp_ns"]
    alpha = (row["timestamp_ns"] - before["timestamp_ns"]) / span if span > 0 else 0.0
    alpha = max(0.0, min(1.0, alpha))
    for key in ("camera_tx", "camera_ty", "camera_tz"):
        row[key] = before[key] + alpha * (after[key] - before[key])
    quaternion = quaternion_slerp(
        [before[key] for key in ("camera_qx", "camera_qy", "camera_qz", "camera_qw")],
        [after[key] for key in ("camera_qx", "camera_qy", "camera_qz", "camera_qw")],
        alpha,
    )
    for key, value in zip(("camera_qx", "camera_qy", "camera_qz", "camera_qw"), quaternion):
        row[key] = value
    row["pose_valid"] = True
    row["pose_interpolated"] = True


def _repair_episode_rows(
    rows: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[tuple[int, list[dict[str, Any]]]], dict[str, Any], str | None]:
    """Turn a raw episode row table into continuous, fully-posed segments.

    Leading/trailing invalid frames are trimmed, short dropouts are
    interpolated, longer tracking losses split the episode, and segments too
    short to yield a training sample are dropped. Returns the surviving
    segments as ``(segment_index, rows)``, the lineage counters, and a
    rejection reason when nothing usable remains.
    """
    gap_config = config["pose_gap"]
    quality_config = config["trajectory_quality"]
    max_gap_frames = int(gap_config["interpolate_max_frames"])
    max_gap_ms = float(gap_config["interpolate_max_gap_ms"])
    min_publish_frames = int(quality_config["min_publish_segment_frames"])

    valid_before = sum(1 for row in rows if row["pose_valid_original"])
    stats: dict[str, Any] = {
        "original_frame_count": len(rows),
        "valid_pose_count_before_repair": valid_before,
        "invalid_pose_count_before_repair": len(rows) - valid_before,
        "trimmed_start_frames": 0,
        "trimmed_end_frames": 0,
        "interpolated_pose_frames": 0,
        "dropped_gap_frames": 0,
        "split_count": 0,
        "dropped_short_segment_count": 0,
        "dropped_short_segment_frames": 0,
        "output_segment_count": 0,
    }
    if not rows:
        return [], stats, "NO_RGB_FRAMES_IN_EPISODE"
    valid_indices = [index for index, row in enumerate(rows) if row["pose_valid_original"]]
    if not valid_indices:
        return [], stats, "NO_VALID_TRACKING_POSE"

    first_valid, last_valid = valid_indices[0], valid_indices[-1]
    stats["trimmed_start_frames"] = first_valid
    stats["trimmed_end_frames"] = len(rows) - 1 - last_valid
    core = rows[first_valid:last_valid + 1]

    segments: list[list[dict[str, Any]]] = []
    current = [core[0]]
    index = 1
    while index < len(core):
        row = core[index]
        if row["pose_valid_original"]:
            current.append(row)
            index += 1
            continue
        gap_end = index
        while gap_end < len(core) and not core[gap_end]["pose_valid_original"]:
            gap_end += 1
        # ``core`` ends on a valid frame, so a bounding valid pose always exists.
        before, after = core[index - 1], core[gap_end]
        gap_frames = gap_end - index
        gap_ms = (after["timestamp_ns"] - before["timestamp_ns"]) / 1_000_000.0
        if gap_frames <= max_gap_frames and gap_ms <= max_gap_ms:
            for gap_index in range(index, gap_end):
                _interpolate_pose(core[gap_index], before, after)
            current.extend(core[index:gap_end])
            current.append(after)
            stats["interpolated_pose_frames"] += gap_frames
        else:
            # Never bridge a tracking loss whose real motion is unknown.
            segments.append(current)
            stats["dropped_gap_frames"] += gap_frames
            current = [after]
        index = gap_end + 1
    segments.append(current)
    stats["split_count"] = len(segments) - 1

    kept: list[tuple[int, list[dict[str, Any]]]] = []
    for segment_index, segment in enumerate(segments):
        if len(segment) < min_publish_frames:
            stats["dropped_short_segment_count"] += 1
            stats["dropped_short_segment_frames"] += len(segment)
            continue
        kept.append((segment_index, segment))
    stats["output_segment_count"] = len(kept)
    if not kept:
        return [], stats, "ALL_SEGMENTS_BELOW_MIN_PUBLISH_LENGTH"
    return kept, stats, None


def _segment_folder(episode_id: str, segment_index: int, split_count: int) -> str:
    base = _safe_episode_name(episode_id)
    return base if split_count == 0 else f"{base}_seg{segment_index:03d}"


def _episode_trajectory(
    rows: Sequence[dict[str, Any]],
    calibration: Sequence[Sequence[float]],
    action_horizon: int = 1,
) -> tuple[dict[str, tuple[str, tuple[int, ...], Sequence[Any]]], dict[str, Any]]:
    count = len(rows)
    nan_matrix = [[math.nan] * 4 for _ in range(4)]
    camera_matrices: list[list[list[float]]] = []
    ee_matrices: list[list[list[float]]] = []
    valid: list[bool] = []
    for row in rows:
        if row["pose_valid"]:
            camera = pose_to_transform(
                (row["camera_tx"], row["camera_ty"], row["camera_tz"]),
                (row["camera_qx"], row["camera_qy"], row["camera_qz"], row["camera_qw"]),
            )
            camera_matrices.append(camera)
            ee_matrices.append(camera_to_ee_transform(camera, calibration))
            valid.append(True)
        else:
            camera_matrices.append([line[:] for line in nan_matrix])
            ee_matrices.append([line[:] for line in nan_matrix])
            valid.append(False)
    first_valid = next((index for index, value in enumerate(valid) if value), None)
    relative_matrices = [[line[:] for line in nan_matrix] for _ in rows]
    if first_valid is not None:
        inverse_first = invert_rigid_transform(ee_matrices[first_valid])
        for index, is_valid in enumerate(valid):
            if is_valid:
                relative_matrices[index] = matrix_multiply(inverse_first, ee_matrices[index])
    actions, action_pairs = relative_transform_actions(ee_matrices, valid, action_horizon)
    flat_actions = _flatten_matrices(actions)
    pair_starts = [pair[0] for pair in action_pairs]
    pair_ends = [pair[1] for pair in action_pairs]
    arrays = {
        "frame_idx": ("<i8", (count,), [row["frame_idx"] for row in rows]),
        "timestamp_ns": ("<i8", (count,), [row["timestamp_ns"] for row in rows]),
        "pose_valid": ("|b1", (count,), valid),
        "pose_valid_original": ("|b1", (count,), [bool(row["pose_valid_original"]) for row in rows]),
        "pose_interpolated": ("|b1", (count,), [bool(row["pose_interpolated"]) for row in rows]),
        "T_world_camera": ("<f8", (count, 4, 4), _flatten_matrices(camera_matrices)),
        "T_camera_EE": ("<f8", (4, 4), _flatten_matrices(calibration and [calibration] or [_matrix_identity()])),
        "T_world_EE": ("<f8", (count, 4, 4), _flatten_matrices(ee_matrices)),
        "T_episode0_EE": ("<f8", (count, 4, 4), _flatten_matrices(relative_matrices)),
        "action_delta_T": ("<f8", (len(actions), 4, 4), flat_actions),
        "action_from_frame_idx": ("<i8", (len(action_pairs),), pair_starts),
        "action_to_frame_idx": ("<i8", (len(action_pairs),), pair_ends),
    }
    trajectory_metadata = {
        "episode_origin_frame_idx": first_valid,
        "episode_origin_timestamp_ns": rows[first_valid]["timestamp_ns"] if first_valid is not None else None,
        "relative_pose_formula": "inverse(T_world_EE[t0]) @ T_world_EE[t]",
        "action_formula": "inverse(T_world_EE[t]) @ T_world_EE[t+h]",
        "action_horizon_frames": action_horizon,
        "action_pair_count": len(action_pairs),
        "action_schema_status": "transform_matrix_only; position/rotation/gripper encoding pending GPU contract",
        "interpolated_pose_frames": sum(1 for row in rows if row["pose_interpolated"]),
    }
    return arrays, trajectory_metadata


def _copy_episode_rgb(decoded_dir: Path, episode_dir: Path, rows: Sequence[dict[str, Any]]) -> None:
    target = episode_dir / "rgb_frames"
    target.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source = decoded_dir / f"frame_{row['rgb_frame_index'] + 1:08d}.jpg"
        destination = episode_dir / row["rgb_path"]
        if not source.is_file():
            raise PreprocessError(f"Decoded RGB frame missing: {source.name}")
        shutil.copyfile(source, destination)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _episode_warnings(
    start: int,
    end: int,
    first_valid_ts: int,
    last_rgb_ts: int | None,
    session_alignment: dict[str, Any],
    unencoded_rows_in_episode: int,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if start < first_valid_ts:
        warnings.append({
            "code": "EPISODE_START_PRECEDES_FIRST_RGB_FRAME",
            "first_rgb_minus_episode_start_ms": (first_valid_ts - start) / 1_000_000.0,
            "handling": "effective_start=max(episode_start,first_valid_frame_timestamp); warning only",
        })
    if last_rgb_ts is not None and end > last_rgb_ts:
        warnings.append({
            "code": "EPISODE_END_AFTER_LAST_ENCODED_RGB_FRAME",
            "episode_end_minus_last_rgb_ms": (end - last_rgb_ts) / 1_000_000.0,
            "handling": "no synthetic frames or timestamp correction",
        })
    if session_alignment["csv_rows_without_encoded_frame"]:
        warnings.append({
            "code": "CSV_TAIL_ROWS_WITHOUT_ENCODED_FRAME",
            "session_csv_tail_rows_discarded": session_alignment["csv_rows_without_encoded_frame"],
            "unencoded_csv_rows_inside_episode": unencoded_rows_in_episode,
        })
    return warnings


def _write_segment(
    stage_dir: Path,
    episode: dict[str, Any],
    raw: dict[str, Any],
    segment_index: int,
    segment_rows: list[dict[str, Any]],
    repair_stats: dict[str, Any],
    window: dict[str, Any],
    warnings: Sequence[dict[str, Any]],
    decoded_dir: Path,
    config: dict[str, Any],
    session_alignment: dict[str, Any],
) -> dict[str, Any]:
    episode_id = episode["episode_id"]
    folder = _segment_folder(episode_id, segment_index, repair_stats["split_count"])
    segment_dir = stage_dir / folder
    segment_dir.mkdir(parents=True, exist_ok=True)
    (segment_dir / "rgb_frames").mkdir(parents=True, exist_ok=True)

    original_frame_range = [segment_rows[0]["episode_frame_idx"], segment_rows[-1]["episode_frame_idx"]]
    for index, row in enumerate(segment_rows):
        row["frame_idx"] = index
        row["rgb_path"] = f"rgb_frames/frame_{index:06d}.jpg"

    _copy_episode_rgb(decoded_dir, segment_dir, segment_rows)
    _write_frames_csv(segment_dir / "frames.csv", segment_rows)

    segment_start = segment_rows[0]["timestamp_ns"]
    segment_end = segment_rows[-1]["timestamp_ns"]
    sensor_counts = {}
    for sensor_name, sensor_rows in raw["sensors"].items():
        sensor_counts[sensor_name] = _write_sensor_csv(
            segment_dir / sensor_name, sensor_rows, segment_start, segment_end
        )

    state_counts = Counter(row["tracking_state"] for row in segment_rows)
    failure_counts = Counter(row["tracking_failure_reason"] for row in segment_rows)
    valid_pose_count = sum(1 for row in segment_rows if row["pose_valid"])
    interpolated_count = sum(1 for row in segment_rows if row["pose_interpolated"])
    max_paused_ms, paused_segments = _max_paused_duration(segment_rows)
    metrics = {
        "total_frame_count": len(segment_rows),
        "valid_pose_count": valid_pose_count,
        "tracking_ratio": valid_pose_count / len(segment_rows) if segment_rows else 0.0,
        "max_paused_duration_ms": max_paused_ms,
        "num_paused_segments": paused_segments,
        "tracking_state_count": dict(sorted(state_counts.items())),
        "tracking_failure_reason_count": dict(sorted(failure_counts.items())),
        "missing_pose_count": state_counts.get("MISSING", 0),
    }
    quality_label, invalid_reasons = _classify_quality(metrics, config["quality_thresholds"])

    arrays, trajectory_meta = _episode_trajectory(segment_rows, config["calibration"]["T_camera_EE"])
    _write_npz(segment_dir / "trajectory.npz", arrays)
    trajectory_meta.update({
        "calibration_status": config["calibration"].get("status", "unspecified"),
        "is_calibration_final": config["calibration"].get("status") == "calibrated",
        "rotation_convention": "Hamilton quaternion [x,y,z,w], active rotation, column vectors, right-handed",
        "matrix_convention": "T_A_B maps coordinates expressed in B into A; homogeneous 4x4 row-major storage",
        "camera_pose_convention": "ARCore local camera pose to session world; translation meters",
        "axis_convention": {
            "world": "ARCore right-handed world coordinate system; world axes are session-local and may be adjusted by ARCore",
            "camera": "+X image-right, +Y image-up, -Z camera-forward (OpenGL camera pose)",
            "sdk_version_verified": False,
            "legacy_sdk_note": "Uploader ARCore SDK version is not recorded; ARCore 1.5 and earlier may use a legacy camera-axis rotation",
        },
        "interpolation_applied": interpolated_count > 0,
        "interpolation_method": "translation linear in timestamp; rotation shortest-arc SLERP",
    })

    lineage = {
        "source_episode_id": episode_id,
        "segment_index": segment_index,
        "segment_count": repair_stats["output_segment_count"],
        "segment_folder": folder,
        "original_frame_range": original_frame_range,
        "original_frame_count": repair_stats["original_frame_count"],
        "final_frame_count": len(segment_rows),
        "trimmed_start_frames": repair_stats["trimmed_start_frames"],
        "trimmed_end_frames": repair_stats["trimmed_end_frames"],
        "interpolated_pose_frames": interpolated_count,
        "episode_interpolated_pose_frames": repair_stats["interpolated_pose_frames"],
        "split_count": repair_stats["split_count"],
        "dropped_gap_frames": repair_stats["dropped_gap_frames"],
        "dropped_short_segment_count": repair_stats["dropped_short_segment_count"],
        "dropped_short_segment_frames": repair_stats["dropped_short_segment_frames"],
    }

    _write_json(segment_dir / "quality.json", {
        **metrics,
        "quality_label": quality_label,
        "invalid_reasons": invalid_reasons,
        "processing_status": "SUCCESS",
        "training_usable": True,
        "reject_reason": None,
        "original_frame_count": repair_stats["original_frame_count"],
        "valid_pose_count_before_repair": repair_stats["valid_pose_count_before_repair"],
        "invalid_pose_count_before_repair": repair_stats["invalid_pose_count_before_repair"],
        "trimmed_start_frames": repair_stats["trimmed_start_frames"],
        "trimmed_end_frames": repair_stats["trimmed_end_frames"],
        "interpolated_pose_frames": interpolated_count,
        "split_count": repair_stats["split_count"],
        "output_segment_count": repair_stats["output_segment_count"],
        "final_frame_count": len(segment_rows),
        "final_valid_pose_count": valid_pose_count,
        "final_invalid_pose_count": len(segment_rows) - valid_pose_count,
        "lineage": lineage,
        "thresholds": config["quality_thresholds"],
        "trajectory_quality": config["trajectory_quality"],
        "pose_gap": config["pose_gap"],
        "pose_validity": config["pose_validity"],
        "thresholds_finalized": bool(config["quality_thresholds"].get("thresholds_finalized", False)),
    })

    metadata = {
        "processed_schema": VERSION,
        "handoff_contract": _handoff_contract(config),
        "session_id": raw["session_id"],
        "episode_id": episode_id,
        "task": episode.get("task"),
        "object": episode.get("object"),
        "outcome": episode.get("outcome"),
        **window,
        "segment_start_timestamp_ns": segment_start,
        "segment_end_timestamp_ns": segment_end,
        "segment_duration_s": (segment_end - segment_start) / 1_000_000_000.0,
        **lineage,
        "source_video": str(Path(raw["source_path"]) / "main_rgb.mp4"),
        "episode_rgb_is_self_contained": True,
        "rgb_mapping": "zero-based decoded MP4 frame index mapped to CSV timestamp by ordered common-prefix position; frame_number column ignored",
        "timestamp_alignment": session_alignment,
        "timestamp_timebase_verified": False,
        "frame_count": len(segment_rows),
        "valid_pose_count": valid_pose_count,
        "tracking_ratio": metrics["tracking_ratio"],
        "max_paused_duration_ms": max_paused_ms,
        "num_paused_segments": paused_segments,
        "tracking_failure_reason_count": dict(sorted(failure_counts.items())),
        "rgb_missing_pose_frame_count": metrics["missing_pose_count"],
        "pose_join_method": "exact timestamp equality; short dropouts interpolated, longer losses split",
        "pose_validity_rule": (
            "usable tracking state AND finite translation/rotation AND |quaternion norm - 1| <= tolerance"
        ),
        "sensor_row_counts": sensor_counts,
        "calibration_status": config["calibration"].get("status", "unspecified"),
        "trajectory": trajectory_meta,
        "warnings": list(warnings),
    }
    _write_json(segment_dir / "metadata.json", metadata)
    return {
        "session_id": raw["session_id"],
        "episode_id": episode_id,
        "segment_index": segment_index,
        "episode_folder": folder,
        "processing_status": "SUCCESS",
        "training_usable": True,
        "reject_reason": None,
        "quality_label": quality_label,
        "invalid_reasons": invalid_reasons,
        "original_frame_count": repair_stats["original_frame_count"],
        "valid_pose_count_before_repair": repair_stats["valid_pose_count_before_repair"],
        "invalid_pose_count_before_repair": repair_stats["invalid_pose_count_before_repair"],
        "trimmed_start_frames": repair_stats["trimmed_start_frames"],
        "trimmed_end_frames": repair_stats["trimmed_end_frames"],
        "interpolated_pose_frames": interpolated_count,
        "split_count": repair_stats["split_count"],
        "output_segment_count": repair_stats["output_segment_count"],
        "final_frame_count": len(segment_rows),
        "final_valid_pose_count": valid_pose_count,
        "frame_count": len(segment_rows),
        "valid_pose_count": valid_pose_count,
        "tracking_ratio": metrics["tracking_ratio"],
        "max_paused_duration_ms": max_paused_ms,
        "num_paused_segments": paused_segments,
        "tracking_failure_reason_count": dict(sorted(failure_counts.items())),
        "num_frames_trimmed_at_start": window["num_frames_trimmed_at_start"],
        "num_frames_trimmed_at_end": window["num_frames_trimmed_at_end"],
        "num_unencoded_csv_rows_in_episode": window["num_unencoded_csv_rows_in_episode"],
        "episode_start_clipped_duration_ms": window["episode_start_clipped_duration_ms"],
        "warnings": list(warnings),
    }


def _write_rejected_episode(
    stage_dir: Path,
    episode: dict[str, Any],
    raw: dict[str, Any],
    repair_stats: dict[str, Any],
    reject_reason: str,
    window: dict[str, Any],
    warnings: Sequence[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Record a rejected episode without publishing it as a usable episode.

    The folder is deliberately not named ``episode_*``: GPU handoff globs that
    prefix, and a rejected episode must never be picked up. No RGB frames are
    copied, so a fully untracked episode costs nothing to reject.
    """
    episode_id = episode["episode_id"]
    folder = f"rejected_{_safe_episode_name(episode_id)}"
    reject_dir = stage_dir / folder
    reject_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": raw["session_id"],
        "episode_id": episode_id,
        "episode_folder": folder,
        "processing_status": "REJECTED",
        "training_usable": False,
        "reject_reason": reject_reason,
        "quality_label": "INVALID_TRACKING",
        "invalid_reasons": [reject_reason],
        **repair_stats,
        "final_frame_count": 0,
        "final_valid_pose_count": 0,
    }
    _write_json(reject_dir / "quality.json", {
        **payload,
        "thresholds": config["quality_thresholds"],
        "trajectory_quality": config["trajectory_quality"],
        "pose_gap": config["pose_gap"],
        "pose_validity": config["pose_validity"],
        "thresholds_finalized": bool(config["quality_thresholds"].get("thresholds_finalized", False)),
    })
    _write_json(reject_dir / "metadata.json", {
        "processed_schema": VERSION,
        "handoff_contract": _handoff_contract(config),
        "task": episode.get("task"),
        "object": episode.get("object"),
        "outcome": episode.get("outcome"),
        **window,
        **payload,
        "source_episode_id": episode_id,
        "warnings": list(warnings),
    })
    return {
        **payload,
        "frame_count": 0,
        "valid_pose_count": 0,
        "tracking_ratio": 0.0,
        "max_paused_duration_ms": 0.0,
        "num_paused_segments": 0,
        "tracking_failure_reason_count": {},
        "num_frames_trimmed_at_start": window["num_frames_trimmed_at_start"],
        "num_frames_trimmed_at_end": window["num_frames_trimmed_at_end"],
        "num_unencoded_csv_rows_in_episode": window["num_unencoded_csv_rows_in_episode"],
        "episode_start_clipped_duration_ms": window["episode_start_clipped_duration_ms"],
        "warnings": list(warnings),
    }


def _process_episode(
    stage_dir: Path,
    episode: dict[str, Any],
    raw: dict[str, Any],
    mapped_frames: Sequence[dict[str, Any]],
    common_count: int,
    first_valid_ts: int,
    ensure_decoded: Any,
    config: dict[str, Any],
    session_alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    start = episode["start_timestamp_ns"]
    end = episode["end_timestamp_ns"]
    effective_start = max(start, first_valid_ts)
    selected, trimmed_start_count, trimmed_end_count, unencoded_rows_in_episode = _episode_frames(
        episode, mapped_frames, common_count, first_valid_ts
    )
    rows = _make_episode_rows(selected, raw["poses"], config["pose_validity"])
    segments, repair_stats, reject_reason = _repair_episode_rows(rows, config)

    last_rgb_ts = mapped_frames[common_count - 1]["timestamp_ns"] if common_count else None
    warnings = _episode_warnings(
        start, end, first_valid_ts, last_rgb_ts, session_alignment, unencoded_rows_in_episode
    )
    window = {
        "episode_start_timestamp_ns": start,
        "effective_start_timestamp_ns": effective_start,
        "episode_end_timestamp_ns": end,
        "first_valid_rgb_timestamp_ns": first_valid_ts,
        "last_encoded_rgb_timestamp_ns": last_rgb_ts,
        "num_frames_trimmed_at_start": trimmed_start_count,
        "num_frames_trimmed_at_end": trimmed_end_count,
        "num_unencoded_csv_rows_in_episode": unencoded_rows_in_episode,
        "episode_start_clipped_duration_ms": max(0, first_valid_ts - start) / 1_000_000.0,
    }
    if reject_reason is not None:
        return [_write_rejected_episode(
            stage_dir, episode, raw, repair_stats, reject_reason, window, warnings, config
        )]
    decoded_dir = ensure_decoded()
    return [
        _write_segment(
            stage_dir, episode, raw, segment_index, segment_rows, repair_stats,
            window, warnings, decoded_dir, config, session_alignment,
        )
        for segment_index, segment_rows in segments
    ]


def _commit_directory(stage: Path, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        raise PreprocessError(f"Output already exists (pass --force to replace): {destination}")
    backup: Path | None = None
    if destination.exists():
        backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def _publish_ready(final_dir: Path) -> None:
    """Mark a committed session directory as safe for the GPU to pull.

    Always the last operation on the directory: everything it claims must
    already be on disk when this runs.
    """
    if not (final_dir / "session_metadata.json").is_file():
        raise PreprocessError(f"Refusing to write READY before output is published: {final_dir}")
    (final_dir / "READY").touch()


def preprocess_session(
    session_dir: Path,
    output_root: Path,
    config: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    raw = _load_session(session_dir)
    session_id = raw["session_id"]
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / session_id
    stage_dir = output_root / f".{session_id}.staging-{uuid.uuid4().hex}"
    stage_dir.mkdir(parents=True, exist_ok=False)
    try:
        pts_ns, decoded_count, time_base = _probe_video(session_dir / "main_rgb.mp4")
        timestamps = [frame["timestamp_ns"] for frame in raw["frames"]]
        common_count = min(len(timestamps), decoded_count)
        alignment = _alignment_report(timestamps, pts_ns, common_count, config["timestamp_alignment"])
        alignment.update({
            "mp4_time_base": time_base,
            "csv_timestamp_source_counts": dict(sorted(Counter(frame["timestamp_source"] for frame in raw["frames"]).items())),
            "frame_number_column_used": False,
        })
        mapped_frames = raw["frames"]

        with tempfile.TemporaryDirectory(prefix=f"preprocess-{session_id[:8]}-") as temp_name:
            decoded_state: dict[str, Path] = {}

            def ensure_decoded() -> Path:
                """Decode the session MP4 once, and only if a segment needs it."""
                if "dir" not in decoded_state:
                    decoded_dir = Path(temp_name) / "decoded"
                    decoded_dir.mkdir()
                    _run([
                        "ffmpeg", "-v", "error", "-i", str(session_dir / "main_rgb.mp4"),
                        "-map", "0:v:0", "-frames:v", str(common_count), "-fps_mode", "passthrough",
                        "-q:v", str(int(config["rgb"].get("jpeg_qscale", 2))),
                        str(decoded_dir / "frame_%08d.jpg"),
                    ])
                    decoded_files = sorted(decoded_dir.glob("frame_*.jpg"))
                    if len(decoded_files) != common_count:
                        raise PreprocessError(
                            f"ffmpeg extracted {len(decoded_files)} frames, expected common-prefix count {common_count}"
                        )
                    decoded_state["dir"] = decoded_dir
                return decoded_state["dir"]

            episode_results: list[dict[str, Any]] = []
            for episode in raw["episodes"]:
                try:
                    episode_results.extend(_process_episode(
                        stage_dir, episode, raw, mapped_frames, common_count, timestamps[0],
                        ensure_decoded, config, alignment,
                    ))
                except Exception as exc:
                    # Failure output is not named ``episode_*``: only publishable
                    # segments may carry that prefix.
                    folder = f"failed_{_safe_episode_name(episode['episode_id'])}"
                    result = {
                        "session_id": session_id,
                        "episode_id": episode["episode_id"],
                        "segment_index": None,
                        "episode_folder": folder,
                        "processing_status": "FAILED",
                        "training_usable": False,
                        "reject_reason": "PROCESSING_ERROR",
                        "quality_label": None,
                        "invalid_reasons": [f"PROCESSING_ERROR: {type(exc).__name__}: {exc}"],
                        "frame_count": 0,
                        "valid_pose_count": 0,
                        "final_frame_count": 0,
                        "final_valid_pose_count": 0,
                        "tracking_ratio": 0.0,
                        "max_paused_duration_ms": 0.0,
                        "num_paused_segments": 0,
                        "tracking_failure_reason_count": {},
                        "num_frames_trimmed_at_start": 0,
                        "num_frames_trimmed_at_end": 0,
                        "num_unencoded_csv_rows_in_episode": 0,
                        "episode_start_clipped_duration_ms": None,
                        "warnings": [],
                    }
                    for stale in stage_dir.glob(f"{_safe_episode_name(episode['episode_id'])}*"):
                        shutil.rmtree(stale)
                    failed_dir = stage_dir / folder
                    if failed_dir.exists():
                        shutil.rmtree(failed_dir)
                    failed_dir.mkdir(parents=True, exist_ok=True)
                    _write_json(failed_dir / "metadata.json", result)
                    _write_json(failed_dir / "quality.json", {
                        "quality_label": None,
                        "invalid_reasons": result["invalid_reasons"],
                        "processing_status": "FAILED",
                        "training_usable": False,
                        "reject_reason": "PROCESSING_ERROR",
                    })
                    episode_results.append(result)

        raw_meta = raw["metadata"]
        camera_timestamp_set = {frame["timestamp_ns"] for frame in raw["frames"]}
        usable_results = [item for item in episode_results if item.get("training_usable")]
        failed_count = sum(1 for item in episode_results if item["processing_status"] == "FAILED")
        rejected_count = sum(1 for item in episode_results if item["processing_status"] == "REJECTED")
        if failed_count:
            session_status = "PARTIAL" if usable_results else "FAILED"
        elif not usable_results:
            session_status = "REJECTED"
        elif rejected_count:
            session_status = "PARTIAL"
        else:
            session_status = "SUCCESS"
        ready = bool(usable_results)
        ready_reason = None if ready else "NO_TRAINING_USABLE_SEGMENT"
        session_metadata = {
            "processed_schema": VERSION,
            "handoff_contract": _handoff_contract(config),
            "session_id": session_id,
            "raw_session_path": str(session_dir),
            "raw_manifest": raw["manifest"],
            "episode_count": len(raw["episodes"]),
            "rgb_timestamp_row_count": len(raw["frames"]),
            "arcore_pose_row_count": raw["pose_count"],
            "rgb_pose_exact_join_count": sum(
                1 for frame in raw["frames"][:common_count]
                if frame["timestamp_ns"] in raw["poses"]
            ),
            "rgb_pose_missing_count": sum(
                1 for frame in raw["frames"][:common_count]
                if frame["timestamp_ns"] not in raw["poses"]
            ),
            "csv_timestamp_pose_exact_join_count": sum(
                1 for frame in raw["frames"] if frame["timestamp_ns"] in raw["poses"]
            ),
            "csv_timestamp_pose_missing_count": sum(
                1 for frame in raw["frames"] if frame["timestamp_ns"] not in raw["poses"]
            ),
            "csv_timestamp_pose_missing_frame_indices": [
                index for index, frame in enumerate(raw["frames"])
                if frame["timestamp_ns"] not in raw["poses"]
            ],
            "arcore_rows_without_camera_timestamp_count": sum(
                1 for timestamp in raw["poses"]
                if timestamp not in camera_timestamp_set
            ),
            "timestamp_alignment": alignment,
            "sensor_row_counts": {name: len(rows) for name, rows in raw["sensors"].items()},
            "timestamp_timebase_verified": False,
            "processing_status": session_status,
            "usable_segment_count": len(usable_results),
            "rejected_episode_count": rejected_count,
            "failed_episode_count": failed_count,
            "ready": ready,
            "ready_reason": ready_reason,
            "ready_contract": (
                "READY is written only after preprocessing, validation and output publication complete, "
                "and only when at least one training-usable segment exists"
            ),
            "pose_validity": config["pose_validity"],
            "pose_gap": config["pose_gap"],
            "trajectory_quality": config["trajectory_quality"],
            "camera_streams": raw_meta.get("camera_streams"),
            "episode_results": episode_results,
            "quality_thresholds": config["quality_thresholds"],
            "thresholds_finalized": bool(config["quality_thresholds"].get("thresholds_finalized", False)),
            "calibration_status": config["calibration"].get("status", "unspecified"),
            "coordinate_convention": {
                "quaternion_order": "[x,y,z,w]",
                "quaternion_action": "active Hamilton rotation",
                "matrix_storage": "row-major homogeneous matrices; column-vector transform convention",
                "camera_axes": "+X image-right, +Y image-up, -Z forward",
                "arcore_sdk_version_verified": False,
                "legacy_sdk_axis_behavior_verified": False,
                "translation_units": "meters",
                "world_axes": "session-local ARCore right-handed world; no cross-session alignment claimed",
            },
        }
        _write_json(stage_dir / "session_metadata.json", session_metadata)
        _commit_directory(stage_dir, final_dir, force)
        if ready:
            _publish_ready(final_dir)
        return {
            "session_id": session_id,
            "processing_status": session_status,
            "output_path": str(final_dir),
            "ready": ready,
            "ready_reason": ready_reason,
            "usable_segment_count": len(usable_results),
            "rejected_episode_count": rejected_count,
            "failed_episode_count": failed_count,
            "episode_count": len(raw["episodes"]),
            "rgb_timestamp_row_count": len(raw["frames"]),
            "mp4_decoded_frame_count": decoded_count,
            "csv_rows_without_encoded_frame": alignment["csv_rows_without_encoded_frame"],
            "rgb_pose_exact_join_count": session_metadata["rgb_pose_exact_join_count"],
            "rgb_pose_missing_count": session_metadata["rgb_pose_missing_count"],
            "csv_timestamp_pose_exact_join_count": session_metadata["csv_timestamp_pose_exact_join_count"],
            "csv_timestamp_pose_missing_count": session_metadata["csv_timestamp_pose_missing_count"],
            "arcore_rows_without_camera_timestamp_count": session_metadata["arcore_rows_without_camera_timestamp_count"],
            "timestamp_alignment": alignment,
            "episodes": episode_results,
        }
    except Exception:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        raise


def _write_report(
    output_root: Path,
    session_results: Sequence[dict[str, Any]],
    failures: Sequence[dict[str, Any]],
    handoff_contract: dict[str, Any],
) -> dict[str, Any]:
    episodes = [episode for session in session_results for episode in session.get("episodes", [])]
    # split_count is per source episode, so it is counted once per episode
    # rather than once per segment row.
    split_counts: dict[tuple[str, Any], int] = {}
    for episode in episodes:
        key = (episode["session_id"], episode.get("episode_id"))
        split_counts[key] = max(split_counts.get(key, 0), int(episode.get("split_count") or 0))
    summary = {
        "processed_schema": VERSION,
        "handoff_contract": handoff_contract,
        "preprocessor_version": "1.1.0",
        "session_success_count": sum(1 for session in session_results if session["processing_status"] == "SUCCESS"),
        "session_partial_count": sum(1 for session in session_results if session["processing_status"] == "PARTIAL"),
        "session_rejected_count": sum(1 for session in session_results if session["processing_status"] == "REJECTED"),
        "session_failure_count": len(failures) + sum(1 for session in session_results if session["processing_status"] == "FAILED"),
        "session_ready_count": sum(1 for session in session_results if session.get("ready")),
        "usable_segment_count": sum(1 for episode in episodes if episode.get("training_usable")),
        "episode_processing_success_count": sum(1 for episode in episodes if episode["processing_status"] == "SUCCESS"),
        "episode_rejected_count": sum(1 for episode in episodes if episode["processing_status"] == "REJECTED"),
        "episode_processing_failure_count": sum(1 for episode in episodes if episode["processing_status"] == "FAILED"),
        "reject_reason_counts": dict(sorted(Counter(
            episode["reject_reason"] for episode in episodes if episode.get("reject_reason")
        ).items())),
        "interpolated_pose_frame_count": sum(int(episode.get("interpolated_pose_frames") or 0) for episode in episodes),
        "split_count": sum(split_counts.values()),
        "quality_label_counts": dict(sorted(Counter(
            episode["quality_label"] for episode in episodes if episode["quality_label"]
        ).items())),
        "invalid_reason_counts": dict(sorted(Counter(
            reason for episode in episodes for reason in episode.get("invalid_reasons", [])
        ).items())),
        "sessions": list(session_results),
        "session_failures": list(failures),
    }
    _write_json(output_root / "validation_report.json", summary)

    report_fields = [
        "session_id", "episode_id", "segment_index", "episode_folder", "processing_status",
        "training_usable", "reject_reason", "quality_label", "invalid_reasons",
        "original_frame_count", "valid_pose_count_before_repair", "invalid_pose_count_before_repair",
        "trimmed_start_frames", "trimmed_end_frames", "interpolated_pose_frames",
        "split_count", "output_segment_count", "final_frame_count", "final_valid_pose_count",
        "frame_count", "valid_pose_count", "tracking_ratio", "max_paused_duration_ms",
        "num_paused_segments", "tracking_failure_reason_count", "num_frames_trimmed_at_start",
        "num_frames_trimmed_at_end", "num_unencoded_csv_rows_in_episode",
        "episode_start_clipped_duration_ms", "warnings",
    ]
    with (output_root / "validation_report.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=report_fields, extrasaction="ignore")
        writer.writeheader()
        for episode in episodes:
            writer.writerow({
                **episode,
                "invalid_reasons": json.dumps(episode.get("invalid_reasons", []), ensure_ascii=False),
                "tracking_failure_reason_count": json.dumps(episode.get("tracking_failure_reason_count", {}), ensure_ascii=False, sort_keys=True),
                "warnings": json.dumps(episode.get("warnings", []), ensure_ascii=False, sort_keys=True),
            })
        for failure in failures:
            writer.writerow({
                "session_id": failure["session_id"],
                "processing_status": "FAILED",
                "training_usable": False,
                "reject_reason": "SESSION_PROCESSING_ERROR",
                "invalid_reasons": json.dumps([failure["error"]], ensure_ascii=False),
            })
    return summary


def _default_config_path() -> Path:
    return Path(__file__).with_name("preprocess_v1_config.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preprocess uploaded Android sessions into processed_v1 episodes")
    parser.add_argument("--sessions-root", type=Path, default=Path("/srv/sessions"))
    parser.add_argument("--output-root", type=Path, default=Path("/srv/processed/v1"))
    parser.add_argument("--config", type=Path, default=_default_config_path())
    parser.add_argument("--session-id", action="append", help="Process only this session (repeatable)")
    parser.add_argument("--force", action="store_true", help="Atomically replace existing session output directories")
    args = parser.parse_args(argv)
    try:
        config = _load_config(args.config)
        if args.session_id:
            session_dirs = [args.sessions_root / session_id for session_id in args.session_id]
        else:
            session_dirs = sorted(path for path in args.sessions_root.iterdir() if path.is_dir())
        if not session_dirs:
            raise PreprocessError(f"No sessions found under {args.sessions_root}")
        args.output_root.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for session_dir in session_dirs:
            try:
                result = preprocess_session(session_dir, args.output_root, config, force=args.force)
                results.append(result)
                print(
                    f"{result['session_id']}: {result['processing_status']} "
                    f"(READY={'yes' if result['ready'] else 'no'}, "
                    f"{result['usable_segment_count']} usable segments, "
                    f"{result['rejected_episode_count']} rejected episodes, "
                    f"{result['rgb_pose_missing_count']} frame-pose misses)"
                )
            except Exception as exc:
                failure = {"session_id": session_dir.name, "error": f"{type(exc).__name__}: {exc}"}
                failures.append(failure)
                print(f"{session_dir.name}: FAILED: {failure['error']}", file=sys.stderr)
        summary = _write_report(args.output_root, results, failures, _handoff_contract(config))
        print(
            f"Report: {args.output_root / 'validation_report.json'}; "
            f"sessions={len(session_dirs)}, READY={summary['session_ready_count']}, "
            f"segments={summary['usable_segment_count']} usable/"
            f"{summary['episode_rejected_count']} rejected/"
            f"{summary['episode_processing_failure_count']} failed, "
            f"interpolated={summary['interpolated_pose_frame_count']} frames, "
            f"splits={summary['split_count']}, labels={summary['quality_label_counts']}"
        )
        return 1 if summary["session_failure_count"] or summary["episode_processing_failure_count"] else 0
    except Exception as exc:
        print(f"preprocess_v1: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
