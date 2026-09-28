"""Collector-side configuration: calibration, conventions and timing.

Every value here changes the *meaning* of the exported dataset, so the resolved
config is stamped verbatim into the zarr metadata and into the W&B run config.
A dataset can therefore always be traced back to the calibration it was built
with (handoff doc section 6).
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import yaml

from omx.data import pose_convert as pc

DEFAULT_CONFIG_PATH = "configs/collector/default.yaml"

GRIPPER_MODES = ("width_m", "normalized", "binary", "constant")
INVALID_POLICIES = ("error", "trim", "split", "keep")
DOWNSAMPLE_STAGES = ("converter", "dataset")


@dataclass
class PoseConfig:
    rotation_format: str = "quat_xyzw"
    position_unit: str = "m"
    world_axis_remap: str = "identity"
    pose_frame: str = "episode_start"     # episode_start | world


@dataclass
class CameraToEeConfig:
    status: str = "placeholder"           # placeholder | calibrated
    calibration_version: str = "none"
    translation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    quaternion: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])  # xyzw

    def matrix(self) -> np.ndarray:
        return pc.make_transform(self.translation, self.quaternion, "quat_xyzw")

    def is_identity(self) -> bool:
        return bool(np.allclose(self.matrix(), np.eye(4), atol=1e-12))


@dataclass
class GripperConfig:
    """Canonical representation is physical finger opening width, in metres."""
    representation: str = "physical_width"
    unit: str = "meter"
    mode: str = "width_m"                 # how the *input* encodes it
    source: str = "visual_marker"
    status: str = "placeholder"           # placeholder | calibrated
    closed_width_m: float = 0.025
    open_width_m: float = 0.105
    invert: bool = False
    placeholder_value_m: float = 0.105

    def to_width_m(self, raw: np.ndarray) -> np.ndarray:
        v = np.asarray(raw, dtype=np.float64)
        if self.invert:
            if self.mode == "width_m":
                v = self.closed_width_m + self.open_width_m - v
            else:
                v = 1.0 - v
        if self.mode == "width_m":
            return v
        if self.mode == "normalized":
            return self.closed_width_m + v * (self.open_width_m - self.closed_width_m)
        if self.mode == "binary":
            return np.where(v >= 0.5, self.open_width_m, self.closed_width_m)
        if self.mode == "constant":
            return np.full_like(v, float(self.placeholder_value_m))
        raise ValueError(f"unknown gripper mode {self.mode!r}; expected {GRIPPER_MODES}")

    def normalized(self, width_m: np.ndarray) -> np.ndarray:
        """Debug-only view; never a replacement for robot0_gripper_width."""
        span = self.open_width_m - self.closed_width_m
        if abs(span) < 1e-9:
            return np.zeros_like(width_m)
        return (np.asarray(width_m, dtype=np.float64) - self.closed_width_m) / span


@dataclass
class TimingConfig:
    source_fps: float = 30.0
    policy_hz: float = 10.0
    downsample_stage: str = "converter"   # where the 30->10 Hz decimation happens

    @property
    def total_decimation(self) -> int:
        ratio = self.source_fps / self.policy_hz
        n = int(round(ratio))
        if n < 1 or abs(ratio - n) > 1e-6:
            raise ValueError(
                f"source_fps/policy_hz = {self.source_fps}/{self.policy_hz} = {ratio:.4f} "
                "is not an integer; pick a policy_hz that divides source_fps evenly "
                "(the sampler can only stride by whole frames).")
        return n

    @property
    def converter_stride(self) -> int:
        return self.total_decimation if self.downsample_stage == "converter" else 1

    @property
    def task_down_sample_steps(self) -> int:
        """What ``obs_down_sample_steps`` must be in the hydra task config.

        This is the guard against silently decimating twice: whatever the
        converter already dropped, the dataset must not drop again.
        ``converter_stride * task_down_sample_steps`` always equals
        ``source_fps / policy_hz``.
        """
        return 1 if self.downsample_stage == "converter" else self.total_decimation

    @property
    def stored_fps(self) -> float:
        return self.source_fps / self.converter_stride


@dataclass
class ValidityConfig:
    use_pose_valid: bool = True
    use_tracking_state: bool = True
    good_tracking_states: List[str] = field(
        default_factory=lambda: ["tracking", "normal", "ok", "good", "true", "1"])
    # The GPU is the final gate, not a repair step: CPU preprocessing owns
    # trimming, gap interpolation, splitting and rejection. Anything invalid that
    # survives to here is a contract violation.
    invalid_policy: str = "error"         # error | trim | split | keep
    # pose_interpolated / pose_valid_original disagreeing with each other makes
    # the dataset untraceable even when the numbers look fine. Kept as its own
    # setting so both the inspector and the converter read one value.
    provenance_policy: str = "error"      # error | warn
    # CPU <-> GPU handoff contract (source/policy Hz, action horizon, publish gate).
    # A mismatch silently changes every downstream timing, so it gates by default.
    contract_policy: str = "error"        # error | warn
    min_segment_frames: Optional[int] = None   # None -> derived from action horizon


@dataclass
class CameraConfig:
    collector_intrinsics: Optional[Dict[str, Any]] = None
    robot_intrinsics: Optional[Dict[str, Any]] = None
    matched_fov_deg: Optional[float] = None
    matched_fov_axis: str = "horizontal"


@dataclass
class CollectorConfig:
    calibration_version: str = "v0-placeholder"
    notes: str = ""
    pose: PoseConfig = field(default_factory=PoseConfig)
    camera_to_ee: CameraToEeConfig = field(default_factory=CameraToEeConfig)
    gripper: GripperConfig = field(default_factory=GripperConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    validity: ValidityConfig = field(default_factory=ValidityConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    field_map: Dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    # ------------------------------------------------------------------ #
    def validate(self) -> List[str]:
        """Return human-readable warnings; raise on anything unrecoverable."""
        warnings: List[str] = []

        if self.pose.rotation_format not in pc.ROTATION_FORMATS:
            raise ValueError(
                f"pose.rotation_format={self.pose.rotation_format!r} not in {pc.ROTATION_FORMATS}")
        if self.pose.world_axis_remap not in pc.WORLD_AXIS_REMAPS:
            raise ValueError(
                f"pose.world_axis_remap={self.pose.world_axis_remap!r} not in "
                f"{sorted(pc.WORLD_AXIS_REMAPS)}")
        if self.pose.pose_frame not in ("episode_start", "world"):
            raise ValueError(
                f"pose.pose_frame={self.pose.pose_frame!r}; expected 'episode_start' or 'world'")
        if self.gripper.mode not in GRIPPER_MODES:
            raise ValueError(f"gripper.mode={self.gripper.mode!r} not in {GRIPPER_MODES}")
        if self.validity.contract_policy not in ("error", "warn"):
            raise ValueError(
                f"validity.contract_policy={self.validity.contract_policy!r}; "
                f"expected 'error' or 'warn'")
        if self.validity.provenance_policy not in ("error", "warn"):
            raise ValueError(
                f"validity.provenance_policy={self.validity.provenance_policy!r}; "
                f"expected 'error' or 'warn'")
        if self.validity.invalid_policy not in INVALID_POLICIES:
            raise ValueError(
                f"validity.invalid_policy={self.validity.invalid_policy!r} not in {INVALID_POLICIES}")
        if self.timing.downsample_stage not in DOWNSAMPLE_STAGES:
            raise ValueError(
                f"timing.downsample_stage={self.timing.downsample_stage!r} not in {DOWNSAMPLE_STAGES}")
        _ = self.timing.total_decimation   # raises on a non-integer ratio

        q = np.asarray(self.camera_to_ee.quaternion, dtype=np.float64)
        if q.shape != (4,):
            raise ValueError(f"camera_to_ee.quaternion must have 4 elements, got {q.shape}")
        if abs(np.linalg.norm(q) - 1.0) > 1e-6:
            raise ValueError(
                f"camera_to_ee.quaternion is not unit norm (|q|={np.linalg.norm(q):.6f}); "
                "it is [qx, qy, qz, qw] -- identity is [0, 0, 0, 1]")

        if self.camera_to_ee.status != "calibrated" or self.camera_to_ee.calibration_version in ("none", ""):
            warnings.append(
                f"T_camera_to_ee is a PLACEHOLDER (status={self.camera_to_ee.status!r}, "
                f"version={self.camera_to_ee.calibration_version!r}). The exported EE "
                f"trajectory is NOT a calibrated physical EE trajectory. Re-export once "
                f"the real calibration lands; no re-collection is needed.")
        elif self.camera_to_ee.is_identity():
            warnings.append(
                "camera_to_ee is marked 'calibrated' but the transform is exactly identity.")

        if self.gripper.status != "calibrated":
            warnings.append(
                f"gripper is a PLACEHOLDER (status={self.gripper.status!r}, "
                f"mode={self.gripper.mode!r}). robot0_gripper_width will not carry real "
                f"marker-derived widths.")
        if self.gripper.open_width_m <= self.gripper.closed_width_m:
            raise ValueError(
                f"gripper.open_width_m ({self.gripper.open_width_m}) must exceed "
                f"gripper.closed_width_m ({self.gripper.closed_width_m})")

        if self.pose.world_axis_remap != "identity":
            warnings.append(
                f"pose.world_axis_remap={self.pose.world_axis_remap!r}: the input contract "
                f"says ARCore's Y-up session world frame is kept as-is, so this should "
                f"normally be 'identity'.")
        return warnings

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["derived"] = {
            "total_decimation": self.timing.total_decimation,
            "converter_stride": self.timing.converter_stride,
            "task_down_sample_steps": self.timing.task_down_sample_steps,
            "stored_fps": self.timing.stored_fps,
            "camera_to_ee_matrix": [[float(v) for v in row]
                                    for row in self.camera_to_ee.matrix()],
            "camera_to_ee_is_identity": self.camera_to_ee.is_identity(),
            "world_axis_remap_matrix": [[float(v) for v in row]
                                        for row in pc.WORLD_AXIS_REMAPS[self.pose.world_axis_remap]],
        }
        return d

    def summary(self) -> str:
        t = self.timing
        c2e = self.camera_to_ee
        g = self.gripper
        return "\n".join([
            f"collector config      : {self.source_path or '<defaults>'}",
            f"  calibration_version : {self.calibration_version}",
            f"  rotation_format     : {self.pose.rotation_format}   "
            f"position_unit: {self.pose.position_unit}   "
            f"world_axis_remap: {self.pose.world_axis_remap}",
            f"  pose_frame          : {self.pose.pose_frame}",
            f"  T_camera_to_ee      : status={c2e.status} version={c2e.calibration_version} "
            f"identity={c2e.is_identity()}",
            f"                        t={list(c2e.translation)} q_xyzw={list(c2e.quaternion)}",
            f"  gripper             : {g.representation} [{g.unit}] mode={g.mode} "
            f"status={g.status} range=[{g.closed_width_m}, {g.open_width_m}] m",
            f"  timing              : {t.source_fps} Hz -> {t.policy_hz} Hz "
            f"(total decimation {t.total_decimation}x)",
            f"                        converter stride {t.converter_stride}x, "
            f"task obs_down_sample_steps {t.task_down_sample_steps} "
            f"-> stored at {t.stored_fps:g} Hz",
            f"  validity            : policy={self.validity.invalid_policy} "
            f"pose_valid={self.validity.use_pose_valid} "
            f"tracking_state={self.validity.use_tracking_state}",
        ])


# --------------------------------------------------------------------------- #
def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _build(cls, data: Dict[str, Any]):
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"unknown key(s) {sorted(unknown)} in the {cls.__name__} section of the "
            f"collector config; known keys: {sorted(known)}")
    return cls(**{k: v for k, v in data.items() if k in known})


def load_collector_config(path: Optional[str] = None,
                          overrides: Optional[Dict[str, Any]] = None) -> CollectorConfig:
    raw: Dict[str, Any] = {}
    source = ""
    if path:
        p = pathlib.Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"collector config not found: {p}")
        with open(p, "r") as f:
            loaded = yaml.safe_load(f) or {}
        raw = loaded.get("collector", loaded)
        source = str(p)

    raw = _merge(raw, overrides or {})

    cfg = CollectorConfig(
        calibration_version=raw.get("calibration_version", "v0-placeholder"),
        notes=raw.get("notes", ""),
        pose=_build(PoseConfig, raw.get("pose", {})),
        camera_to_ee=_build(CameraToEeConfig, raw.get("camera_to_ee", {})),
        gripper=_build(GripperConfig, raw.get("gripper", {})),
        timing=_build(TimingConfig, raw.get("timing", {})),
        validity=_build(ValidityConfig, raw.get("validity", {})),
        camera=_build(CameraConfig, raw.get("camera", {})),
        field_map=raw.get("field_map", {}) or {},
        source_path=source,
    )
    return cfg
