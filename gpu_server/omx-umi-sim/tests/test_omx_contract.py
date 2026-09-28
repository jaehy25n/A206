"""Contract tests for the OMX GPU validation gate.

    python tests/test_omx_contract.py          # standalone
    pytest tests/test_omx_contract.py          # or under pytest

The one that matters most is ``test_inspector_and_converter_agree``: the
inspector and the converter must reach the same verdict on every case, so a
dataset can never inspect PASS and then build FAIL (handoff item GPU-2).
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import csv
import importlib.util
import pathlib
import shutil
import tempfile

import cv2
import numpy as np

from omx.collector_config import load_collector_config
from omx.data.build import build_segments, min_stored_frames, stored_frames_for
from omx.data.contract import ContractError
from omx.data.handoff_contract import HandoffContract, validate_contracts
from omx.data.processed_v1 import ProcessedV1Reader, _is_excluded
from omx.data.validity import (check_pose_provenance,
                               compute_effective_pose_validity)

_spec = importlib.util.spec_from_file_location(
    "omx_inspect", os.path.join(ROOT_DIR, "scripts", "inspect_synced_processed.py"))
inspect_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inspect_mod)

COLUMNS = ["frame_idx", "timestamp_ns", "rgb_path",
           "camera_tx", "camera_ty", "camera_tz",
           "camera_qx", "camera_qy", "camera_qz", "camera_qw",
           "tracking_state", "pose_valid", "pose_valid_original",
           "pose_interpolated", "gripper_width_m"]


def make_episode(ep_dir: pathlib.Path, n: int = 60, mutate=None) -> pathlib.Path:
    """Smallest thing the pipeline accepts: n aligned rows plus n tiny frames."""
    (ep_dir / "rgb_frames").mkdir(parents=True, exist_ok=True)
    img = np.zeros((16, 28, 3), dtype=np.uint8)
    rows = []
    for i in range(n):
        rel = f"rgb_frames/frame_{i:06d}.jpg"
        cv2.imwrite(str(ep_dir / rel), img)
        rows.append({
            "frame_idx": i,
            "timestamp_ns": 1_700_000_000_000_000_000 + int(i / 30 * 1e9),
            "rgb_path": rel,
            "camera_tx": i * 0.001, "camera_ty": 0.2, "camera_tz": 0.0,
            "camera_qx": 0.0, "camera_qy": 0.0, "camera_qz": 0.0, "camera_qw": 1.0,
            "tracking_state": "TRACKING", "pose_valid": 1,
            "pose_valid_original": 1, "pose_interpolated": 0,
            "gripper_width_m": 0.105 if i < n // 2 else 0.025,
        })
    if mutate:
        mutate(rows)
    with (ep_dir / "frames.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return ep_dir


def make_tree(root: pathlib.Path, mutate=None, n: int = 60) -> pathlib.Path:
    session = root / "sess-0001"
    make_episode(session / "episode_0001", n=n, mutate=mutate)
    (session / "READY").touch()
    return root


# --------------------------------------------------------------------------- #
# GPU-1: effective validity
# --------------------------------------------------------------------------- #
def test_effective_validity_truth_table():
    pos = np.zeros((5, 3))
    quat = np.tile([0.0, 0.0, 0.0, 1.0], (5, 1))
    pos[4] = np.nan
    r = compute_effective_pose_validity(
        pos, quat, "quat_xyzw",
        pose_valid=[1, 0, 1, 1, 1],
        tracking_state=["TRACKING", "TRACKING", "PAUSED", "PAUSED", "TRACKING"],
        pose_interpolated=[0, 0, 0, 1, 0])
    assert r.effective_valid[0], "healthy row must pass"
    assert not r.effective_valid[1], "pose_valid=false must fail"
    assert not r.effective_valid[2], "PAUSED without interpolation must fail"
    assert r.effective_valid[3], "PAUSED + pose_interpolated=true must PASS"
    assert not r.effective_valid[4], "NaN pose must fail"


def test_bad_quaternion_norm_fails():
    pos = np.zeros((2, 3))
    quat = np.array([[0.0, 0, 0, 1.0], [0.0, 0, 0, 0.5]])
    r = compute_effective_pose_validity(pos, quat, "quat_xyzw")
    assert r.effective_valid[0] and not r.effective_valid[1]


def test_missing_columns_are_permissive_but_nan_is_not():
    pos = np.zeros((2, 3)); pos[1] = np.nan
    quat = np.tile([0.0, 0, 0, 1.0], (2, 1))
    r = compute_effective_pose_validity(pos, quat, "quat_xyzw")
    assert r.effective_valid[0] and not r.effective_valid[1]


# --------------------------------------------------------------------------- #
# GPU-3: provenance
# --------------------------------------------------------------------------- #
def test_provenance_flags_contradictions():
    assert check_pose_provenance(pose_valid=[1], pose_valid_original=[1],
                                 pose_interpolated=[1], tracking_state=["PAUSED"])
    assert check_pose_provenance(pose_valid=[0], pose_valid_original=[0],
                                 pose_interpolated=[1], tracking_state=["PAUSED"])
    assert check_pose_provenance(pose_valid=[1], pose_valid_original=[0],
                                 pose_interpolated=[1], tracking_state=["TRACKING"])
    assert check_pose_provenance(pose_valid=[1], pose_valid_original=[0],
                                 pose_interpolated=[0], tracking_state=["TRACKING"])


def test_provenance_accepts_the_documented_combinations():
    assert not check_pose_provenance(
        pose_valid=[1, 1], pose_valid_original=[1, 0],
        pose_interpolated=[0, 1], tracking_state=["TRACKING", "PAUSED"])


# --------------------------------------------------------------------------- #
# GPU-4: discovery exclusions
# --------------------------------------------------------------------------- #
def test_rejected_and_failed_directories_are_excluded():
    for name in ("episode_abc", "episode_abc_seg000", "episode_abc_seg012"):
        assert not _is_excluded(pathlib.Path(name)), name
    for name in ("rejected_episode_abc", "failed_episode_abc", "rejected/ep",
                 "failed/ep", ".incoming/ep", ".superseded/ep", "quarantine/ep"):
        assert _is_excluded(pathlib.Path(name)), name


# --------------------------------------------------------------------------- #
# min-length arithmetic must be the same on both sides
# --------------------------------------------------------------------------- #
def test_stored_frame_arithmetic():
    assert min_stored_frames(16, 1) == 16
    assert min_stored_frames(16, 3) == 46
    assert stored_frames_for(45, 3) == 15
    assert stored_frames_for(46, 3) == 16


# --------------------------------------------------------------------------- #
# handoff contract
# --------------------------------------------------------------------------- #
GOOD_CONTRACT = HandoffContract("omx_processed_v1_posefix_1", 30.0, 10.0, 16, 48)


def _validate(contracts):
    return validate_contracts(contracts, 30.0, 10.0, 16, 46)[0]


def test_contract_accepts_a_more_conservative_publish_gate():
    # CPU publishes at 48 source frames, the GPU needs 46 -> not a mismatch
    assert not _validate({"session_metadata.json": GOOD_CONTRACT})


def test_contract_rejects_a_looser_publish_gate():
    loose = HandoffContract("omx_processed_v1_posefix_1", 30.0, 10.0, 16, 40)
    assert _validate({"a": loose})


def test_contract_requires_exact_hz_and_horizon():
    for bad in (HandoffContract("omx_processed_v1_posefix_1", 60.0, 10.0, 16, 48),
                HandoffContract("omx_processed_v1_posefix_1", 30.0, 15.0, 16, 48),
                HandoffContract("omx_processed_v1_posefix_1", 30.0, 10.0, 8, 48)):
        assert _validate({"a": bad}), bad


def test_contract_rejects_unknown_version():
    assert _validate({"a": HandoffContract("omx_processed_v9", 30.0, 10.0, 16, 48)})


def test_contract_rejects_session_segment_disagreement():
    other = HandoffContract("omx_processed_v1_posefix_1", 30.0, 10.0, 16, 52)
    assert _validate({"session_metadata.json": GOOD_CONTRACT,
                      "ep1/metadata.json": other})


def test_contract_rejects_absence():
    assert _validate({})


# --------------------------------------------------------------------------- #
# GPU-2: the inspector and the converter must never disagree
# --------------------------------------------------------------------------- #
def _mutate(kind):
    def apply(rows):
        for r in rows[20:30]:
            if kind == "clean":
                return
            if kind == "paused_not_interpolated":
                r["tracking_state"] = "PAUSED"; r["pose_interpolated"] = 0
            elif kind == "cpu_interpolated":
                r["tracking_state"] = "PAUSED"; r["pose_interpolated"] = 1
                r["pose_valid_original"] = 0; r["pose_valid"] = 1
            elif kind == "blank_pose":
                for c in ("camera_tx", "camera_ty", "camera_tz",
                          "camera_qx", "camera_qy", "camera_qz", "camera_qw"):
                    r[c] = ""
                r["pose_valid"] = 0
            elif kind == "pose_invalid":
                r["pose_valid"] = 0
            elif kind == "interp_but_original_valid":
                r["tracking_state"] = "PAUSED"; r["pose_interpolated"] = 1
                r["pose_valid_original"] = 1
            elif kind == "interp_tracking_rewritten":
                r["tracking_state"] = "TRACKING"; r["pose_interpolated"] = 1
                r["pose_valid_original"] = 0
    return apply


CASES = {
    "clean": True,
    "cpu_interpolated": True,               # GPU-1: repaired rows are accepted
    "paused_not_interpolated": False,
    "blank_pose": False,
    "pose_invalid": False,
    "interp_but_original_valid": False,     # GPU-3
    "interp_tracking_rewritten": False,     # GPU-3
}


def _verdicts(root: pathlib.Path, cfg):
    """(inspector_ok, converter_ok) for a one-episode tree."""
    ep = root / "sess-0001" / "episode_0001"
    check = inspect_mod.check_episode(
        "sess-0001", ep, cfg.field_map, cfg, strict=True,
        min_stored=min_stored_frames(16, cfg.timing.task_down_sample_steps))

    reader = ProcessedV1Reader(ep, "sess-0001__episode_0001", field_map=cfg.field_map)
    try:
        low = reader.read_lowdim()
        build_segments(low, cfg, reader.episode_id, str(ep),
                       min_stored_frames(16, cfg.timing.task_down_sample_steps),
                       n_rgb_frames=len(reader.frame_paths()))
        converter_ok = True
    except ContractError:
        converter_ok = False
    return check.ok, converter_ok


def test_inspector_and_converter_agree():
    cfg = load_collector_config(os.path.join(ROOT_DIR, "configs/collector/default.yaml"))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="omx_contract_"))
    try:
        failures = []
        for kind, expect_pass in CASES.items():
            root = tmp / kind
            make_tree(root, mutate=_mutate(kind), n=60)
            insp_ok, conv_ok = _verdicts(root, cfg)
            if insp_ok != conv_ok:
                failures.append(f"{kind}: inspector={insp_ok} converter={conv_ok}")
            elif insp_ok != expect_pass:
                failures.append(
                    f"{kind}: both said {'PASS' if insp_ok else 'FAIL'}, "
                    f"expected {'PASS' if expect_pass else 'FAIL'}")
            print(f"  {kind:30s} inspector={'PASS' if insp_ok else 'FAIL'} "
                  f"converter={'PASS' if conv_ok else 'FAIL'} "
                  f"{'ok' if not failures or failures[-1].split(':')[0] != kind else 'MISMATCH'}")
        assert not failures, "\n".join(failures)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_short_episode_rejected_by_both():
    cfg = load_collector_config(os.path.join(ROOT_DIR, "configs/collector/default.yaml"))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="omx_short_"))
    try:
        need = min_stored_frames(16, cfg.timing.task_down_sample_steps)
        stride = cfg.timing.converter_stride
        short_n = (need - 1) * stride
        root = make_tree(tmp / "short", n=short_n)
        insp_ok, conv_ok = _verdicts(root, cfg)
        assert insp_ok == conv_ok, f"inspector={insp_ok} converter={conv_ok}"
        assert not insp_ok, f"{short_n} source frames should be too short"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}\n      {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
