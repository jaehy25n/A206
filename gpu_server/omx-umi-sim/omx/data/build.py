"""processed_v1 episode -> UMI ReplayBuffer episode.

Implements the ordering the input contract (section 11) requires:

    processed episode
        -> validity / tracking filter
        -> RGB <-> pose <-> gripper alignment check
        -> frame-level aligned trajectory
        -> 30 Hz -> 10 Hz decimation (one shared index for EVERY stream)
        -> zarr export

The GPU side does NOT repair tracking: trimming, short-gap interpolation,
long-gap splitting and segment rejection all belong to CPU preprocessing, which
runs before READY is written.  ``validity.invalid_policy`` therefore defaults to
``error`` -- anything still invalid here is a contract violation to report, not
to work around.

and the pose chain of handoff doc section 6 / contract sections 4-5:

    T_world_ee(t)   = T_world_camera(t) @ T_camera_ee
    T_episode_ee(t) = inv(T_world_ee(0)) @ T_world_ee(t)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from omx.collector_config import CollectorConfig
from omx.data import pose_convert as pc
from omx.data.contract import ContractError, LowDimData
from omx.data.validity import (check_pose_provenance,
                               compute_effective_pose_validity)


@dataclass
class Segment:
    """One contiguous, fully valid, already decimated piece of a source episode."""

    episode_id: str
    source_path: str
    source_indices: np.ndarray        # into the source frames.csv rows
    eef_pos: np.ndarray               # [n, 3] float32
    eef_rot_axis_angle: np.ndarray    # [n, 3] float32
    gripper_width: np.ndarray         # [n, 1] float32, metres
    demo_start_pose: np.ndarray       # [n, 6] float32
    demo_end_pose: np.ndarray         # [n, 6] float32
    timestamp: np.ndarray             # [n] float64, seconds
    info: Dict[str, object] = field(default_factory=dict)

    @property
    def n_frames(self) -> int:
        return int(self.eef_pos.shape[0])

    def episode_data(self) -> Dict[str, np.ndarray]:
        """The lowdim payload for ``ReplayBuffer.add_episode``."""
        return {
            "robot0_eef_pos": self.eef_pos,
            "robot0_eef_rot_axis_angle": self.eef_rot_axis_angle,
            "robot0_gripper_width": self.gripper_width,
            "robot0_demo_start_pose": self.demo_start_pose,
            "robot0_demo_end_pose": self.demo_end_pose,
        }


def min_source_frames(min_stored: int, converter_stride: int) -> int:
    """Fewest source frames that survive decimation into ``min_stored`` frames."""
    return (int(min_stored) - 1) * int(converter_stride) + 1


def stored_frames_for(n_source_frames: int, converter_stride: int) -> int:
    """How many frames a source run of this length contributes after decimation.

    The inspector uses this so its "too short" verdict is the same arithmetic the
    converter applies, rather than an approximation of it.
    """
    return len(range(0, int(n_source_frames), int(converter_stride)))


def min_stored_frames(action_horizon: int, task_down_sample_steps: int) -> int:
    """Shortest episode the UMI sampler can draw even one sample from.

    ``SequenceSampler`` skips any ``current_idx`` where
    ``end_idx < current_idx + (action_horizon-1)*down_sample_steps + 1`` when
    ``action_padding`` is False -- so a shorter episode contributes *nothing*
    and is dropped completely silently.
    """
    return (int(action_horizon) - 1) * int(task_down_sample_steps) + 1


def compute_valid_mask(low: LowDimData, cfg: CollectorConfig
                       ) -> Tuple[np.ndarray, Dict[str, object]]:
    """Per-frame validity, delegated to the shared contract implementation.

    The inspector calls ``compute_effective_pose_validity`` on exactly the same
    ``LowDimData``, so "inspect PASS then build FAIL" is not reachable.
    """
    result = compute_effective_pose_validity(
        position=low.position,
        rotation=low.rotation,
        rotation_format=cfg.pose.rotation_format,
        pose_valid=low.extra.get("pose_valid"),
        tracking_state=low.extra.get("tracking_state"),
        pose_interpolated=low.extra.get("pose_interpolated"),
        usable_tracking_states=cfg.validity.good_tracking_states,
        use_pose_valid=cfg.validity.use_pose_valid,
        use_tracking_state=cfg.validity.use_tracking_state,
    )

    reasons: Dict[str, object] = {}
    for key, count in result.counts.items():
        if key in ("effective_invalid", "interpolated_by_cpu") or not count:
            continue
        reasons[key] = count
        if key in result.detail:
            reasons[f"_{key}_detail"] = result.detail[key]

    # blank / unparseable csv cells were turned into NaN by the reader, never
    # into a number -- report them separately from genuine NaN so the message
    # points at the CPU output rather than at the maths
    unparseable = low.extra.get("_unparseable") or {}
    if unparseable:
        reasons["_unparseable_columns"] = unparseable

    # provenance bookkeeping is reported but does not itself invalidate a frame
    prov = check_pose_provenance(
        pose_valid=low.extra.get("pose_valid"),
        pose_valid_original=low.extra.get("pose_valid_original"),
        pose_interpolated=low.extra.get("pose_interpolated"),
        tracking_state=low.extra.get("tracking_state"),
        usable_tracking_states=cfg.validity.good_tracking_states)
    if prov:
        reasons["_provenance"] = prov

    return result.effective_valid, reasons


def contiguous_runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """[(start, stop)) for every maximal run of True."""
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def apply_invalid_policy(mask: np.ndarray, policy: str, episode_id: str,
                         reasons: Optional[Dict[str, object]] = None
                         ) -> List[Tuple[int, int]]:
    n = len(mask)
    if policy == "keep":
        return [(0, n)]

    runs = contiguous_runs(mask)

    if policy == "error":
        if not np.all(mask):
            detail = ""
            if reasons:
                parts = []
                for k, v in reasons.items():
                    if k == "_unparseable_columns":
                        parts.append("blank/unparseable cells in " +
                                     ", ".join(f"{c} ({d})" for c, d in v.items()))
                    elif k == "_provenance":
                        parts.extend(str(x) for x in v)
                    elif k.endswith("_detail"):
                        continue
                    elif not k.startswith("_"):
                        parts.append(f"{k}={v}" +
                                     (f" ({reasons['_' + k + '_detail']})"
                                      if f"_{k}_detail" in reasons else ""))
                if parts:
                    detail = "\n  causes: " + "\n          ".join(parts)
            raise ContractError(
                f"[{episode_id}] {int((~mask).sum())}/{n} frames fail validation "
                f"and validity.invalid_policy='error'.{detail}\n"
                f"  This is a CPU processed_v1 contract violation: the CPU side is "
                f"responsible for trimming, interpolating short gaps, splitting long "
                f"gaps and rejecting unusable segments before writing READY.\n"
                f"  The GPU side is the final gate, not a repair step -- fix the CPU "
                f"output and re-sync rather than relaxing this setting.\n"
                f"  (validity.invalid_policy=trim|split exists for debugging a known-"
                f"bad export; it must not be used to produce a training dataset.)")
        return [(0, n)]

    if not runs:
        return []

    if policy == "trim":
        # keep only the single longest run; discard everything outside it
        return [max(runs, key=lambda r: r[1] - r[0])]

    if policy == "split":
        return runs

    raise ValueError(f"unknown invalid_policy {policy!r}")


def build_segments(low: LowDimData, cfg: CollectorConfig, episode_id: str,
                   source_path: str, min_frames: int,
                   n_rgb_frames: Optional[int] = None
                   ) -> Tuple[List[Segment], List[str]]:
    """Turn one source episode into 0..n zarr-ready segments."""
    notes: List[str] = []
    n = low.n_frames

    if n_rgb_frames is not None and n_rgb_frames != n:
        raise ContractError(
            f"[{episode_id}] rgb frame count {n_rgb_frames} != frames.csv rows {n}; "
            "the contract requires them to be equal")

    mask, reasons = compute_valid_mask(low, cfg)
    plain = {k: v for k, v in reasons.items() if not k.startswith("_")}
    if plain:
        notes.append(f"[{episode_id}] invalid frames: " +
                     ", ".join(f"{k}={v}" for k, v in plain.items()))
    provenance = reasons.get("_provenance", [])
    if provenance and cfg.validity.provenance_policy == "error":
        raise ContractError(
            f"[{episode_id}] pose provenance columns contradict each other:\n  - "
            + "\n  - ".join(provenance) +
            f"\n  The CPU repair bookkeeping must be self-consistent: a direct "
            f"measurement is pose_valid_original=true / pose_interpolated=false, "
            f"an interpolated row is pose_valid_original=false / "
            f"pose_interpolated=true / pose_valid=true with its ORIGINAL "
            f"tracking_state kept.\n  (validity.provenance_policy=warn downgrades "
            f"this, but then the dataset cannot be traced back to what was measured "
            f"and what was filled in.)")
    for problem in provenance:
        notes.append(f"[{episode_id}] provenance: {problem}")

    interp = low.extra.get("pose_interpolated")
    if interp is not None:
        from omx.data.validity import as_bool_array
        n_interp = int(sum(1 for v in as_bool_array(interp, default=False) if v))
        if n_interp:
            notes.append(f"[{episode_id}] {n_interp}/{low.n_frames} frames were "
                         f"interpolated by CPU preprocessing (accepted)")

    runs = apply_invalid_policy(mask, cfg.validity.invalid_policy, episode_id,
                                reasons=reasons)
    if len(runs) > 1:
        notes.append(
            f"[{episode_id}] split into {len(runs)} valid segments by "
            f"invalid_policy='{cfg.validity.invalid_policy}'")

    stride = cfg.timing.converter_stride
    T_cam_ee = cfg.camera_to_ee.matrix()

    # gripper: the contract's canonical unit is metres
    grip_raw = np.asarray(low.gripper, dtype=np.float64)
    if np.all(~np.isfinite(grip_raw)):
        if cfg.gripper.mode != "constant":
            raise ContractError(
                f"[{episode_id}] no gripper column in frames.csv "
                f"(source={low.extra.get('_gripper_source')!r}) but gripper.mode is "
                f"{cfg.gripper.mode!r}. For a Stage A integration build set\n"
                f"    gripper: {{mode: constant, placeholder_value_m: <m>}}\n"
                f"or pass --gripper-mode constant.")
        notes.append(f"[{episode_id}] gripper column absent; using the "
                     f"{cfg.gripper.placeholder_value_m} m constant placeholder")
    grip_m_full = cfg.gripper.to_width_m(np.nan_to_num(grip_raw, nan=0.0))

    segments: List[Segment] = []
    dropped_short: List[str] = []
    for run_i, (lo, hi) in enumerate(runs):
        idx = np.arange(lo, hi, stride, dtype=np.int64)
        if idx.size < min_frames:
            dropped_short.append(
                f"segment {run_i}: {hi - lo} source frames -> {idx.size} stored "
                f"(< {min_frames} required), source rows {lo}..{hi - 1}")
            notes.append(
                f"[{episode_id}] segment {run_i} dropped: {idx.size} stored frames "
                f"< {min_frames} required by action_horizon "
                f"(source frames {lo}..{hi}, stride {stride})")
            continue

        T_world_cam = pc.build_pose_matrices(
            low.position[idx], np.asarray(low.rotation)[idx],
            cfg.pose.rotation_format, cfg.pose.position_unit)
        T_world_cam = pc.apply_world_axis_remap(T_world_cam, cfg.pose.world_axis_remap)
        T_world_ee = pc.camera_to_ee(T_world_cam, T_cam_ee)

        if cfg.pose.pose_frame == "episode_start":
            T_out = np.linalg.inv(T_world_ee[0])[None, ...] @ T_world_ee
        else:
            T_out = T_world_ee

        pos, rotvec = pc.mat_to_pos_rotvec(T_out)
        grip = grip_m_full[idx]

        pose6 = pc.pos_rotvec_to_pose6(pos, rotvec)
        n_seg = idx.size
        segments.append(Segment(
            episode_id=episode_id if len(runs) == 1 else f"{episode_id}#seg{run_i}",
            source_path=source_path,
            source_indices=idx,
            eef_pos=pos.astype(np.float32),
            eef_rot_axis_angle=rotvec.astype(np.float32),
            gripper_width=grip.astype(np.float32).reshape(n_seg, 1),
            demo_start_pose=np.repeat(pose6[0][None, :], n_seg, axis=0).astype(np.float32),
            demo_end_pose=np.repeat(pose6[-1][None, :], n_seg, axis=0).astype(np.float32),
            timestamp=low.timestamp[idx],
            info={
                "source_frame_range": [int(lo), int(hi)],
                "stride": int(stride),
                "n_source_frames": int(hi - lo),
                "n_stored_frames": int(n_seg),
                "duration_s": float(low.timestamp[idx][-1] - low.timestamp[idx][0]),
                "gripper_source": low.extra.get("_gripper_source", "unknown"),
            },
        ))

    # Under the gate policy a too-short segment is a CPU contract violation, not
    # something to drop quietly: SequenceSampler(action_padding=False) would make
    # zero samples from it, so the episode would vanish without a trace.
    if dropped_short and cfg.validity.invalid_policy == "error":
        raise ContractError(
            f"[{episode_id}] {len(dropped_short)} segment(s) are too short to "
            f"produce a single training sample:\n  - " + "\n  - ".join(dropped_short) +
            f"\n  At {cfg.timing.policy_hz:g} Hz an episode needs at least "
            f"{min_frames} stored frames "
            f"({min_source_frames(min_frames, stride)} source frames).\n"
            f"  CPU preprocessing should have rejected these segments before "
            f"writing READY. The GPU side refuses rather than dropping them "
            f"silently, because SequenceSampler would then discard the episode "
            f"with no message at all.")

    if not segments:
        notes.append(f"[{episode_id}] produced NO usable segments")
    return segments, notes
