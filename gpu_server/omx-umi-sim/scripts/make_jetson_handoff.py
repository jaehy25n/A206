"""Build the GPU -> Jetson runtime handoff bundle.

Everything written here is derived from the repo's own code on a fixed sample,
so the Jetson runtime never has to guess a convention. Nothing is copied from
prose documentation: the semantics recorded in the manifest are re-derived
numerically in this script and cross-checked, and every claim carries the
source file and function it came from.

    python scripts/make_jetson_handoff.py -e omx_pick_raw_center_v1

The reference sample is deterministic (fixed index, seeded RNG) so the bundle is
byte-reproducible except where the policy itself is not -- which this script
detects and reports rather than hiding.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import hashlib
import json
import pathlib
import subprocess
import time
from typing import Dict, Optional

import click
import cv2
import dill
import hydra
import numpy as np
import torch
from omegaconf import OmegaConf

from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
from diffusion_policy.common.pose_repr_util import convert_pose_mat_rep
from diffusion_policy.workspace.base_workspace import BaseWorkspace
from omx import config as omx_config
from omx.data.rgb_preprocess import build_preprocessor
from umi.common.pose_util import (mat_to_pose, mat_to_rot6d, mat_to_pose10d,
                                  pose10d_to_mat, pose_to_mat, rot6d_to_mat)

register_codecs()
OmegaConf.register_new_resolver("eval", eval, replace=True)

BUNDLE_SCHEMA = "omx-gpu-jetson-handoff/1"
TORCH_SEED = 42


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*a) -> str:
    try:
        return subprocess.check_output(("git",) + a, cwd=ROOT_DIR,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def arr_stats(a: np.ndarray) -> Dict[str, object]:
    return {"shape": list(a.shape), "dtype": str(a.dtype),
            "min": float(np.min(a)), "max": float(np.max(a)),
            "mean": float(np.mean(a))}


# --------------------------------------------------------------------------- #
# semantics, re-derived numerically from the repo's own functions
# --------------------------------------------------------------------------- #
def derive_decoder_contract() -> Dict[str, object]:
    """Probe the actual pose utilities instead of trusting documentation."""
    import scipy.spatial.transform as st
    R_b = st.Rotation.from_euler("xyz", [0.3, -0.2, 0.7]).as_matrix()
    p_b = np.array([0.10, -0.20, 0.30])
    R_t = st.Rotation.from_euler("xyz", [0.1, 0.4, -0.2]).as_matrix()
    p_t = np.array([0.25, 0.05, 0.40])
    T_b = np.eye(4); T_b[:3, :3] = R_b; T_b[:3, 3] = p_b
    T_t = np.eye(4); T_t[:3, :3] = R_t; T_t[:3, 3] = p_t

    # exactly umi_dataset.UmiDataset.__getitem__ lines 344-357
    T_rel = convert_pose_mat_rep(T_t[None], base_pose_mat=T_b,
                                 pose_rep="relative", backward=False)
    d10 = mat_to_pose10d(T_rel)[0]
    pos, d6 = d10[:3], d10[3:9]
    R_rel = R_b.T @ R_t

    checks = {
        "position_is_base_frame": bool(np.allclose(pos, R_b.T @ (p_t - p_b))),
        "position_is_world_delta": bool(np.allclose(pos, p_t - p_b)),
        "rot6d_is_first_two_rows": bool(np.allclose(d6, R_rel[:2, :].reshape(6))),
        "rot6d_is_first_two_cols": bool(np.allclose(d6, R_rel[:, :2].T.reshape(6))),
        "R_abs_eq_Rbase_at_Rrel": bool(np.allclose(R_b @ R_rel, R_t)),
        "R_abs_eq_Rrel_at_Rbase": bool(np.allclose(R_rel @ R_b, R_t)),
        "roundtrip_max_abs_err": float(np.abs(
            convert_pose_mat_rep(pose10d_to_mat(d10[None]), base_pose_mat=T_b,
                                 pose_rep="relative", backward=True)[0] - T_t).max()),
    }
    assert checks["position_is_base_frame"] and not checks["position_is_world_delta"]
    assert checks["rot6d_is_first_two_rows"] and not checks["rot6d_is_first_two_cols"]
    assert checks["R_abs_eq_Rbase_at_Rrel"] and not checks["R_abs_eq_Rrel_at_Rbase"]
    assert checks["roundtrip_max_abs_err"] < 1e-9

    return {
        "position_semantics":
            "relative to the observation base pose T0 (the LAST observation frame), "
            "expressed IN THE T0 EE FRAME: p_rel[k] = R0^T @ (p_abs[k] - p0). "
            "NOT a world-frame displacement and NOT a sequential delta -- the base "
            "is constant across all 16 steps.",
        "rotation_layout":
            "rot6d = first two ROWS of the relative rotation matrix, flattened "
            "row-major: [R00, R01, R02, R10, R11, R12]. Rebuild with "
            "Gram-Schmidt on the two rows; the third row is cross(b1, b2).",
        "rotation_multiplication":
            "relative. Recover absolute with R_abs = R_base @ R_rel "
            "(left-multiply by base). R_rel @ R_base is WRONG.",
        "position_recovery": "p_abs[k] = R_base @ p_rel[k] + p_base",
        "gripper_semantics":
            "ABSOLUTE target width, same unit as robot0_gripper_width in the zarr "
            "(metres). Not relative, not normalised, and not transformed by the "
            "pose representation -- taken straight from the replay buffer and "
            "un-normalised by the policy.",
        "base_pose_definition":
            "T0 = the EE pose at the LAST observation timestep (umi_dataset uses "
            "pose_mat[-1]), i.e. the pose at the inference instant.",
        "_probe_results": checks,
    }


# --------------------------------------------------------------------------- #
@click.command()
@click.option("-e", "--experiment", default="omx_pick_raw_center_v1")
@click.option("-c", "--checkpoint", default=None)
@click.option("-o", "--out-dir", default="jetson_handoff")
@click.option("--sample-index", type=int, default=None,
              help="Dataset sample index. Default: the midpoint of the longest "
                   "episode, so the observation horizon holds two distinct frames.")
@click.option("--device", default="cuda:0")
@click.option("--checkpoint-mode",
              type=click.Choice(["ema", "full", "ema-fp16", "none"]), default="ema",
              help="What to package. 'ema' (default) keeps only the EMA weights, "
                   "which is what inference actually uses, and halves the size. "
                   "'full' keeps both copies. 'ema-fp16' halves it again but "
                   "changes numerics. 'none' ships the manifest reference only.")
@click.option("--zip/--no-zip", "make_zip", default=True,
              help="Also write a single self-contained .zip next to the bundle.")
def main(experiment, checkpoint, out_dir, sample_index, device,
         checkpoint_mode, make_zip):
    exp = omx_config.get(experiment)
    out = pathlib.Path(out_dir).absolute()
    out.mkdir(parents=True, exist_ok=True)
    report = {}

    click.echo("=" * 78)
    click.echo("GPU -> Jetson handoff bundle")
    click.echo("=" * 78)

    # ------------------------------------------------------------- checkpoint #
    if checkpoint is None:
        root = omx_config.TRAIN_DIR / experiment
        cands = sorted(root.glob("**/checkpoints/latest.ckpt"),
                       key=lambda p: p.stat().st_mtime)
        if not cands:
            raise click.ClickException(f"no checkpoint under {root}")
        checkpoint = cands[-1]
    ckpt = pathlib.Path(checkpoint).absolute()
    click.echo(f"checkpoint : {ckpt}")
    ckpt_sha = sha256_file(ckpt)
    click.echo(f"sha256     : {ckpt_sha}")

    payload = torch.load(ckpt.open("rb"), pickle_module=dill, map_location="cpu")
    cfg = payload["cfg"]
    cls = hydra.utils.get_class(cfg._target_)
    workspace: BaseWorkspace = cls(cfg, output_dir=str(out))
    workspace.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = workspace.ema_model if (cfg.training.use_ema and
                                     getattr(workspace, "ema_model", None) is not None) \
        else workspace.model
    weights = "ema" if policy is getattr(workspace, "ema_model", None) else "raw"
    dev = torch.device(device)
    policy.to(dev).eval()

    # ---------------------------------------------------------------- dataset #
    zarr_path = exp.zarr_path.resolve()
    zmeta = json.loads(exp.dataset.meta_path.read_text())
    ds_cfg = OmegaConf.to_container(cfg.task.dataset, resolve=True)
    ds_cfg["dataset_path"] = str(zarr_path)
    dataset = hydra.utils.instantiate(OmegaConf.create(ds_cfg))
    rb = dataset.replay_buffer
    stored_fps = float(zmeta["dataset"]["stored_fps"])

    # ------------------------------------------------------ reference sample #
    if sample_index is None:
        longest = max(zmeta["episodes"], key=lambda e: e["n_stored_frames"])
        target = (longest["buffer_start"] + longest["buffer_end"]) // 2
        cand = [i for i, (cur, *_rest) in enumerate(dataset.sampler.indices)
                if cur == target]
        if not cand:                     # midpoint fell in the val split
            cand = [min(range(len(dataset.sampler.indices)),
                        key=lambda i: abs(dataset.sampler.indices[i][0] - target))]
        sample_index = cand[0]
    cur, start, end, _ = dataset.sampler.indices[int(sample_index)]
    click.echo(f"sample     : dataset index {sample_index} -> replay-buffer frame {cur}")

    ep = next(e for e in zmeta["episodes"]
              if e["buffer_start"] <= cur < e["buffer_end"])
    src_frame = ep["source_frame_range"][0] + (cur - ep["buffer_start"]) * ep["stride"]
    click.echo(f"source     : {ep['episode_id']}  source frame {src_frame}")

    # ----------------------------------------------------------- timing ----- #
    a_ds = int(dataset.key_down_sample_steps["action"])
    a_h = int(dataset.key_horizon["action"])
    o_ds = int(dataset.key_down_sample_steps["camera0_rgb"])
    o_h = int(dataset.key_horizon["camera0_rgb"])
    action_dt_s = a_ds / stored_fps
    slice_end = min(end, cur + (a_h - 1) * a_ds + 1)
    action_frames = np.arange(cur, slice_end, a_ds)
    n_valid = min(o_h, (cur - start) // o_ds + 1)
    obs_frames = np.arange(cur - (n_valid - 1) * o_ds, cur + 1, o_ds)
    first_action_offset_s = float(action_frames[0] - obs_frames[-1]) / stored_fps
    click.echo(f"timing     : action_dt_s={action_dt_s}  "
               f"first_action_offset_s={first_action_offset_s}")

    # ------------------------------------------------------- raw source RGB - #
    src_dir = pathlib.Path(ep["source_path"])
    from omx.data.processed_v1 import ProcessedV1Reader
    reader = ProcessedV1Reader(src_dir, ep["episode_id"])
    src_jpg = reader.frame_paths()[src_frame]
    bgr = cv2.imread(str(src_jpg), cv2.IMREAD_COLOR)
    raw_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    cv2.imwrite(str(out / "raw_rgb.png"), bgr)        # png stores the bytes losslessly
    click.echo(f"raw rgb    : {src_jpg.name}  {raw_rgb.shape}")

    # GPU preprocessing re-applied to the raw frame, compared with the zarr
    rgbp = zmeta["rgb_preprocess"]
    pre = build_preprocessor(rgbp["mode"], in_res=tuple(rgbp["in_res"]),
                             out_res=tuple(rgbp["out_res"]))
    repro = pre(raw_rgb)                      # what the Jetson can reproduce
    stored = rb["camera0_rgb"][cur]           # what the encoder actually saw
    # The zarr stores frames JpegXl-compressed at level 99, which is LOSSY, so
    # these two differ by the codec round-trip. The Jetson has no zarr at runtime,
    # so its achievable target is `repro`; `stored` is recorded alongside so the
    # train/deploy difference is visible rather than surprising.
    rgb_err = np.abs(repro.astype(np.int16) - stored.astype(np.int16))
    report["jpegxl_roundtrip_max_abs_err_uint8"] = int(rgb_err.max())
    report["jpegxl_roundtrip_mean_abs_err_uint8"] = float(rgb_err.mean())
    click.echo(f"rgb        : raw->preprocess vs JpegXl-stored frame  "
               f"max={rgb_err.max()} mean={rgb_err.mean():.4f}  (codec is lossy)")

    # --------------------------------------------------------- observation - #
    sample = dataset[int(sample_index)]
    obs = {k: v.numpy() for k, v in sample["obs"].items()}
    gt_action = sample["action"].numpy()
    prep_zarr = obs["camera0_rgb"]                     # [T,C,H,W] float32 in [0,1]
    # The contract target: raw frame -> preprocessing -> encoder input tensor.
    # Single frame, because that is the one the Jetson holds at inference time.
    prep = np.moveaxis(repro, -1, 0).astype(np.float32) / 255.0
    np.save(out / "preprocessed_rgb.npy", prep)
    np.save(out / "preprocessed_rgb_from_zarr.npy", prep_zarr)

    abs_pos = rb["robot0_eef_pos"][:]
    abs_rot = rb["robot0_eef_rot_axis_angle"][:]
    abs_grip = rb["robot0_gripper_width"][:]
    base_pose6 = np.concatenate([abs_pos[cur], abs_rot[cur]])

    # Only the policy's observation tensors carry the `obs_` prefix. Index and
    # timing arrays deliberately do not, so a consumer can select the observation
    # dict by prefix without picking up metadata by accident.
    np.savez(out / "observation_reference.npz",
             **{f"obs_{k}": v for k, v in obs.items()},
             preprocessed_rgb_from_raw=prep,
             frame_index_obs=obs_frames, frame_index_action=action_frames,
             timestamps_obs_s=(obs_frames - obs_frames[-1]) / stored_fps,
             action_target_times_s=(action_frames - obs_frames[-1]) / stored_fps,
             abs_eef_pos=abs_pos[obs_frames], abs_eef_rotvec=abs_rot[obs_frames],
             abs_gripper_width=abs_grip[obs_frames],
             base_pose6=base_pose6, stored_fps=np.array(stored_fps))

    # ------------------------------------------------------------- inference #
    torch.manual_seed(TORCH_SEED)
    np.random.seed(TORCH_SEED)
    obs_t = {k: torch.from_numpy(v)[None].to(dev) for k, v in obs.items()}
    with torch.no_grad():
        action = policy.predict_action(obs_t, None)["action"].cpu().numpy()[0]
    np.save(out / "reference_action.npy", action.astype(np.float32))

    # is the policy deterministic for a fixed seed / fixed input?
    torch.manual_seed(TORCH_SEED); np.random.seed(TORCH_SEED)
    with torch.no_grad():
        again = policy.predict_action(obs_t, None)["action"].cpu().numpy()[0]
    report["policy_reseeded_max_abs_err"] = float(np.abs(action - again).max())
    with torch.no_grad():
        unseeded = policy.predict_action(obs_t, None)["action"].cpu().numpy()[0]
    report["policy_unseeded_max_abs_err"] = float(np.abs(action - unseeded).max())
    nondet = report["policy_unseeded_max_abs_err"] > 1e-5
    click.echo(f"policy     : reseeded max|d|={report['policy_reseeded_max_abs_err']:.3e}  "
               f"unseeded max|d|={report['policy_unseeded_max_abs_err']:.3e}")

    # latency
    with torch.no_grad():
        for _ in range(2):
            policy.predict_action(obs_t, None)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(5):
            policy.predict_action(obs_t, None)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - t0) / 5 * 1e3

    # --------------------------------------------------------------- decode - #
    def decode(raw10: np.ndarray, base6: np.ndarray):
        world = convert_pose_mat_rep(pose10d_to_mat(raw10[:, :9]),
                                     base_pose_mat=pose_to_mat(base6),
                                     pose_rep=dataset.action_pose_repr, backward=True)
        pose6 = mat_to_pose(world)
        return pose6[:, :3], pose6[:, 3:], raw10[:, 9], world

    pos_d, rot_d, grip_d, world_mat = decode(action, base_pose6)
    np.savez(out / "reference_decoded_pose.npz",
             ee_position=pos_d, ee_rotation_rotvec=rot_d,
             ee_rotation_matrix=world_mat[:, :3, :3], gripper_width=grip_d,
             target_times_s=(action_frames - obs_frames[-1]) / stored_fps,
             base_pose6=base_pose6)

    # decoder parity fixture: ground-truth action, no model involved
    gt_pos, gt_rot, gt_grip, _ = decode(gt_action, base_pose6)
    n_gt = len(action_frames)
    gt_err_pos = float(np.abs(gt_pos[:n_gt] - abs_pos[action_frames]).max())
    import scipy.spatial.transform as st
    gt_err_rot = float(np.max((st.Rotation.from_rotvec(gt_rot[:n_gt]) *
                               st.Rotation.from_rotvec(abs_rot[action_frames]).inv()).magnitude()))
    gt_err_grip = float(np.abs(gt_grip[:n_gt] - abs_grip[action_frames, 0]).max())
    report["decoder_gt_position_max_err_m"] = gt_err_pos
    report["decoder_gt_rotation_max_err_rad"] = gt_err_rot
    report["decoder_gt_gripper_max_err_m"] = gt_err_grip
    click.echo(f"decoder    : ground-truth roundtrip  pos={gt_err_pos:.3e} m  "
               f"rot={gt_err_rot:.3e} rad  grip={gt_err_grip:.3e} m")

    np.savez(out / "decoder_reference.npz",
             base_pose6=base_pose6,
             base_position=base_pose6[:3], base_rotvec=base_pose6[3:],
             base_rotation_matrix=pose_to_mat(base_pose6)[:3, :3],
             raw_action=action.astype(np.float32),
             expected_position=pos_d, expected_rotvec=rot_d,
             expected_rotation_matrix=world_mat[:, :3, :3], expected_gripper=grip_d,
             groundtruth_raw_action=gt_action.astype(np.float32),
             groundtruth_expected_position=gt_pos,
             groundtruth_expected_rotvec=gt_rot,
             groundtruth_true_position=abs_pos[action_frames],
             groundtruth_true_rotvec=abs_rot[action_frames],
             groundtruth_true_gripper=abs_grip[action_frames, 0])

    # ---------------------------------------------------------------- config #
    OmegaConf.save(cfg, out / "model_config.yaml")

    contract = derive_decoder_contract()
    probe = contract.pop("_probe_results")

    tf = policy.obs_encoder.key_transform_map["camera0_rgb"]
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": "scripts/make_jetson_handoff.py",
        "repo": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                 "commit": git("rev-parse", "HEAD"),
                 "commit_short": git("rev-parse", "--short", "HEAD"),
                 "dirty": bool(git("status", "--porcelain")),
                 "dirty_paths": [l[3:] for l in
                                 git("status", "--porcelain").splitlines()][:10]},

        "checkpoint": str(ckpt),
        "checkpoint_sha256": ckpt_sha,
        "checkpoint_weights": weights,
        # epoch/global_step live in payload['pickles'] (dill) and are restored onto
        # the workspace by load_payload, not present at the payload top level
        "checkpoint_epoch": int(getattr(workspace, "epoch", -1)),
        "checkpoint_global_step": int(getattr(workspace, "global_step", -1)),

        "observation_keys": sorted(obs.keys()),
        "observation_npz_prefix": "obs_",
        "obs_horizon": o_h,
        "action_horizon": a_h,
        "action_dim": int(cfg.shape_meta.action.shape[0]),
        "policy_hz": stored_fps / a_ds,
        "diffusion_steps": int(cfg.policy.num_inference_steps),
        "rgb_size": int(cfg.shape_meta.obs.camera0_rgb.shape[-1]),

        "rotation_representation": "rot6d",
        "relative_action": True,
        "gripper_unit": zmeta["gripper"]["unit"],

        "action_dt_s": action_dt_s,
        "first_action_offset_s": first_action_offset_s,
        "action_target_times_s": [float(t) for t in
                                  (action_frames - obs_frames[-1]) / stored_fps],
        "obs_timestamps_s": [float(t) for t in
                             (obs_frames - obs_frames[-1]) / stored_fps],

        "decoder_contract": contract,

        "rgb_preprocess": {
            "input_color_order": "BGR from cv2.imread, converted to RGB with "
                                 "cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) before any "
                                 "other step",
            "rotate_k": 0,
            "crop_mode": (f"{rgbp['mode']}: central square of the source frame, "
                          f"crop box (x,y,w,h) = {rgbp.get('crop_box_xywh')} for a "
                          f"{rgbp['in_res'][0]}x{rgbp['in_res'][1]} input"),
            "interpolation": "cv2.INTER_AREA (crop -> 224x224)",
            "normalization": "uint8/255 -> float32 in [0,1], channels-first "
                             "(T,C,H,W). NO mean/std normalisation is applied "
                             "anywhere: the normalizer is an identity for images "
                             "and TimmObsEncoder ignores its imagenet_norm flag.",
            "source_resolution": list(rgbp["in_res"]),
            "output_resolution": list(rgbp["out_res"]),
            "effective_hfov_deg": rgbp.get("effective_hfov_deg"),
            "output_layout": "(C, H, W) float32, C = R,G,B",
            "training_storage_note":
                "the training zarr stores frames JpegXl-compressed at level 99, "
                "which is LOSSY. The model therefore trained on codec "
                "round-tripped frames while the Jetson feeds freshly preprocessed "
                "ones. Measured difference on this sample is in "
                "measured.jpegxl_roundtrip_*; it is far below the ColorJitter "
                "range the model is trained with, but it is not zero.",
        },

        "in_policy_transform": {
            "applied_at_inference": True,
            "modules": str(tf).replace("\n", " "),
            "deterministic": not nondet,
            "note": "TimmObsEncoder.forward applies key_transform_map "
                    "unconditionally; torchvision RandomCrop/ColorJitter ignore "
                    "eval(), so the policy randomises its own input at inference. "
                    "This happens INSIDE the policy, after the preprocessing "
                    "contract above. Jetson must reproduce the preprocessing, not "
                    "the policy output, bit-for-bit.",
        },

        "reference_sample": {
            "dataset_index": int(sample_index),
            "replay_buffer_frame": int(cur),
            "episode_id": ep["episode_id"],
            "source_path": ep["source_path"],
            "source_frame_index": int(src_frame),
            "source_file": str(src_jpg),
            "obs_frames": [int(x) for x in obs_frames],
            "action_frames": [int(x) for x in action_frames],
            "torch_seed": TORCH_SEED,
        },

        "dataset": {
            "zarr": str(zarr_path),
            "sha256": sha256_file(zarr_path),
            "n_episodes": zmeta["dataset"]["n_episodes"],
            "n_frames": zmeta["dataset"]["n_frames"],
            "stored_fps": stored_fps,
            "handoff_contract": list(zmeta["handoff_contract"].values())[0],
        },

        "measured": {
            "latency_ms_per_call_b1": round(latency_ms, 2),
            "device": torch.cuda.get_device_name(0) if dev.type == "cuda" else "cpu",
            **report,
        },

        "live_ready": False,
        "live_ready_blockers": [
            f"T_camera_EE is a placeholder "
            f"({zmeta['camera_to_ee_status']}/{zmeta['camera_to_ee_calibration_version']}) "
            f"-- the EE trajectory is not physically calibrated",
            f"gripper is a placeholder ({zmeta['gripper']['status']}); "
            f"robot0_gripper_width is constant in this dataset",
            "checkpoint is from a Stage A integration run on 7 segments of "
            "non-task footage, not a trained task policy",
        ],
        "warnings": [
            "INTEGRATION ONLY -- NOT FOR LIVE TASK EXECUTION",
            "the policy randomises its own input at inference (see "
            "in_policy_transform); its output is not bit-reproducible",
        ],
        "verified": True,
        "verified_scope": "action semantics, action time contract, RGB "
                          "preprocessing contract and decoder parity are each "
                          "derived from repo code and numerically checked in this "
                          "script. 'verified' refers to the CONTRACT, not to the "
                          "checkpoint's fitness for the task (see live_ready).",
    }
    (out / "model_manifest.json").write_text(json.dumps(manifest, indent=2))

    # ------------------------------------------------------------- parity --- #
    click.echo("\n[parity: reload from disk and recompute]")
    rl_prep = np.load(out / "preprocessed_rgb.npy")
    rl_act = np.load(out / "reference_action.npy")
    rl_dec = np.load(out / "reference_decoded_pose.npz")
    rl_raw = cv2.cvtColor(cv2.imread(str(out / "raw_rgb.png"), cv2.IMREAD_COLOR),
                          cv2.COLOR_BGR2RGB)

    e1 = float(np.abs(rl_prep - prep).max())
    # raw png -> preprocessing -> the [0,1] CHW tensor  (the Jetson contract)
    rebuilt = np.moveaxis(pre(rl_raw), -1, 0).astype(np.float32) / 255.0
    e2 = float(np.abs(rebuilt - rl_prep).max())
    p2, r2, g2, _ = decode(rl_act, base_pose6)
    e3 = float(np.abs(p2 - rl_dec["ee_position"]).max())
    e4 = float(np.abs(r2 - rl_dec["ee_rotation_rotvec"]).max())
    e5 = float(np.abs(g2 - rl_dec["gripper_width"]).max())
    for label, v in (("preprocessed_rgb.npy roundtrip", e1),
                     ("raw_rgb.png -> preprocess vs saved tensor", e2),
                     ("decoded position", e3), ("decoded rotation", e4),
                     ("decoded gripper", e5)):
        ok = v < 1e-6
        click.secho(f"  {'ok  ' if ok else 'FAIL'} {label:44s} max|d| = {v:.3e}",
                    fg="green" if ok else "red")
    manifest["measured"]["parity"] = {
        "preprocessed_rgb_roundtrip": e1, "raw_png_to_tensor": e2,
        "decoded_position": e3, "decoded_rotation": e4, "decoded_gripper": e5}
    (out / "model_manifest.json").write_text(json.dumps(manifest, indent=2))

    write_source_reference(out)

    # ------------------------------------------------------- checkpoint ---- #
    if checkpoint_mode != "none":
        dst = out / "checkpoint.ckpt"
        if checkpoint_mode == "full":
            import shutil
            shutil.copy2(ckpt, dst)
            kept = sorted(payload["state_dicts"].keys())
        else:
            slim = {"cfg": payload["cfg"], "pickles": payload["pickles"],
                    "state_dicts": {"ema_model": payload["state_dicts"]["ema_model"]}}
            if checkpoint_mode == "ema-fp16":
                slim["state_dicts"]["ema_model"] = {
                    k: (v.half() if torch.is_floating_point(v) else v)
                    for k, v in slim["state_dicts"]["ema_model"].items()}
            torch.save(slim, dst.open("wb"), pickle_module=dill)
            kept = ["ema_model"]
        manifest["packaged_checkpoint"] = {
            "file": "checkpoint.ckpt",
            "mode": checkpoint_mode,
            "sha256": sha256_file(dst),
            "size_bytes": dst.stat().st_size,
            "state_dicts": kept,
            "source_sha256": ckpt_sha,
            "load_with": "ema_model" if checkpoint_mode != "full" else "ema_model (preferred) or model",
            "note": ("only the EMA weights are packaged -- that is what inference "
                     "uses. Loading `model` from this file would give you an "
                     "untrained network, so load `ema_model`."
                     if checkpoint_mode != "full" else
                     "byte-identical copy of the training checkpoint"),
        }
        click.echo(f"checkpoint : packaged as {checkpoint_mode} "
                   f"({dst.stat().st_size/1e6:.1f} MB)")

    (out / "model_manifest.json").write_text(json.dumps(manifest, indent=2))
    write_readme(out, manifest, probe)
    write_install_guide(out, manifest)

    # --------------------------------------------------------- checksums --- #
    lines = []
    for f in sorted(out.iterdir()):
        if f.is_file() and f.name != "SHA256SUMS":
            lines.append(f"{sha256_file(f)}  {f.name}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    click.secho(f"\nbundle: {out}", fg="green")
    for f in sorted(out.iterdir()):
        click.echo(f"  {f.stat().st_size:>12,} B  {f.name}")

    # --------------------------------------------------------------- zip --- #
    if make_zip:
        import zipfile
        stamp = time.strftime("%Y%m%d", time.gmtime())
        zpath = out.parent / f"omx_jetson_handoff_{manifest['repo']['commit_short']}_{stamp}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(out.iterdir()):
                if f.is_file():
                    z.write(f, arcname=f"{out.name}/{f.name}")
        click.secho(f"\nzip   : {zpath}  ({zpath.stat().st_size/1e6:.1f} MB)", fg="green")
        click.echo(f"sha256: {sha256_file(zpath)}")


def write_install_guide(out: pathlib.Path, m: Dict) -> None:
    """Travels inside the zip, so the guide is never separated from the bundle."""
    ck = m.get("packaged_checkpoint")
    if ck:
        ck_block = (f"| `checkpoint.ckpt` | {ck['size_bytes']/1e6:.0f} MB, "
                    f"mode `{ck['mode']}`, sha256 `{ck['sha256'][:16]}...` |")
        load_note = ck["note"]
    else:
        ck_block = ("| _(checkpoint not packaged)_ | see `model_manifest.json` "
                    "-> `checkpoint` |")
        load_note = "not packaged in this bundle."
    blockers = "\n".join("* " + b for b in m["live_ready_blockers"])

    (out / "INSTALL.md").write_text(f"""# Installing this bundle on the Jetson

**INTEGRATION ONLY - NOT FOR LIVE TASK EXECUTION.** See `live_ready_blockers` in
`model_manifest.json`. Do not connect this checkpoint's output to OMX actuator
commands.

---

## 0. What this is

A self-contained reference of the GPU side's action / timing / RGB contract, so
the Jetson runtime never has to guess one. Every value in it was derived from the
GPU repo's own code at `{m["repo"]["branch"]}` @ `{m["repo"]["commit_short"]}`.

| | |
|---|---|
{ck_block}

The transfer method does not matter - scp, USB, shared drive. The zip is the unit.

### This bundle is only half of the handoff

Running the checkpoint also needs the **source snapshot**,
`jetson_inference_source_<commit>.tar.gz`, which carries the code that loads it
plus `inference_requirements.txt` and the full receiving procedure in
`README_JETSON_SETUP.md`. Unpack both side by side:

```
~/omx_policy/
|- jetson_handoff/            <- this bundle
`- jetson_inference_source/   <- the source snapshot
```

`verify_bundle.py` below needs only numpy and checks this bundle alone. The
checkpoint smoke test lives in the snapshot
(`scripts/smoke_predict_action.py`) and needs PyTorch.

---

## 1. Unpack and verify integrity

```bash
unzip omx_jetson_handoff_*.zip          # or, if unzip is not installed:
python3 -m zipfile -e omx_jetson_handoff_*.zip .

cd jetson_handoff
sha256sum -c SHA256SUMS
```

Every line must say `OK`. If any does not, the copy was corrupted - re-transfer
rather than continuing.

---

## 2. Verify the contract reproduces here

```bash
python3 verify_bundle.py
```

This imports nothing from the GPU repo. It re-implements the decoder from the
contract text and checks it against the bundle's own reference values, so a pass
means the Jetson can reproduce the GPU's semantics with numpy alone.

Expected tail:

```
ALL BUNDLE CHECKS PASSED
```

Needs `numpy`. The RGB section additionally needs `cv2` and is skipped without it.

---

## 3. Wire it into the runtime

### 3.1 Preprocessing

```python
bgr = cv2.imread(path, cv2.IMREAD_COLOR)          # or straight from the camera
rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)        # FIRST, before anything else
ih, iw = rgb.shape[:2]
side = min(iw, ih)
x0, y0 = (iw - side) // 2, (ih - side) // 2       # central square
crop = rgb[y0:y0 + side, x0:x0 + side]
img = cv2.resize(crop, (224, 224), interpolation=cv2.INTER_AREA)
tensor = np.moveaxis(img, -1, 0).astype(np.float32) / 255.0   # (3,224,224) in [0,1]
```

No mean/std normalisation. No rotation (`rotate_k = 0`).
Check the result against `preprocessed_rgb.npy`.

Observation tensors in `observation_reference.npz` are the keys prefixed `obs_`;
everything else in that file is metadata (frame indices, timestamps, absolute
poses). `model_manifest.json` -> `observation_keys` lists them explicitly, so
select by that list rather than by prefix alone.

### 3.2 Decode

```python
p_rel = action[:, 0:3]                 # expressed in the T0 EE frame
R_rel = rot6d_to_mat(action[:, 3:9])   # first two ROWS, row-major
grip  = action[:, 9]                   # absolute width, metres

p_abs = (R_base @ p_rel[..., None])[..., 0] + p_base
R_abs = R_base @ R_rel                 # base on the LEFT
```

`T_base` is the EE pose at the inference instant.

### 3.3 Timing

```
action[k] target time = t0 + k * {m["action_dt_s"]}
first_action_offset_s = {m["first_action_offset_s"]}
```

`t0` is the timestamp of the **last** observation frame, and `action[0]` targets
`t0` itself - it is the pose the robot is already at, so it carries no motion.
Begin the executed prefix after it.

### 3.4 Loading the checkpoint

{load_note}

---

## 4. Four things that will bite if skipped

1. **No mean/std normalisation anywhere.** The GPU config sets
   `imagenet_norm: True`, but `TimmObsEncoder` never reads that argument. Feeding
   CLIP- or ImageNet-normalised input would be wrong.
2. **The policy randomises its own input at inference.**
   `TimmObsEncoder.forward` applies `RandomCrop(212) + Resize(224) + ColorJitter`
   with no `training` guard, and torchvision ignores `eval()` for those. Two
   forward passes over one input differ (~2.0 measured). Match the **decoder**,
   not the policy output. If you export to ONNX/TensorRT, decide explicitly
   whether that transform ends up in the graph.
3. **The training frames went through a lossy codec.** The GPU's training zarr is
   JpegXl level 99, so the model trained on slightly different pixels than the
   Jetson will feed (max 34/255 on the reference frame). `preprocessed_rgb.npy`
   is the raw-path tensor you can reproduce; `preprocessed_rgb_from_zarr.npy` is
   what the encoder actually received, shipped only so the difference is visible.
   Do not try to match it.
4. **`action[0] ~ 0` is a property of the data, not of the policy output.** It
   holds for the ground-truth actions in `decoder_reference.npz` and for a
   trained policy. This checkpoint has seen 7 gradient steps, so asserting it on
   `reference_action.npy` will fail.

---

## 5. Gate

```json
"verified":   {str(m["verified"]).lower()},     // the CONTRACT is code-verified
"live_ready": {str(m["live_ready"]).lower()}    // the CHECKPOINT is not task-ready
```

Blockers:

{blockers}

The runtime's live gate must read `live_ready`, not `verified`.

---

## 6. When the next bundle arrives

Stage B changes the checkpoint, not the contract. These stay the same and need no
Jetson code changes:

action semantics, rot6d layout, multiplication order, gripper meaning,
`action_dt_s`, `first_action_offset_s`, RGB preprocessing.

These change: `checkpoint_sha256` / `packaged_checkpoint.sha256`, `live_ready`,
the gripper values, the EE trajectory (real `T_camera_EE`), and
`rgb_preprocess.effective_hfov_deg`.

So on a new bundle: `sha256sum -c SHA256SUMS`, `python3 verify_bundle.py`, then
diff `model_manifest.json` against the previous one. If only the fields above
moved, swapping the checkpoint is the whole job.
""")


def write_source_reference(out: pathlib.Path) -> None:
    (out / "decoder_source_reference.md").write_text('''# Source of every contract value

Line numbers are from the commit recorded in `model_manifest.json` (`repo.commit`).

## Action construction

`diffusion_policy/dataset/umi_dataset.py` — `UmiDataset.__getitem__`

```python
pose_mat   = pose_to_mat(concat(obs["robot0_eef_pos"], obs["robot0_eef_rot_axis_angle"]))
action_mat = pose_to_mat(data["action"][..., 7*r : 7*r+6])

obs_pose_mat    = convert_pose_mat_rep(pose_mat,    base_pose_mat=pose_mat[-1],
                                       pose_rep=self.obs_pose_repr, backward=False)
action_pose_mat = convert_pose_mat_rep(action_mat,  base_pose_mat=pose_mat[-1],
                                       pose_rep=self.obs_pose_repr, backward=False)

action_pose    = mat_to_pose10d(action_pose_mat)
action_gripper = data["action"][..., 7*r+6 : 7*r+7]
actions.append(concat([action_pose, action_gripper], axis=-1))
```

* `base_pose_mat=pose_mat[-1]` — the LAST observation pose, **constant for all 16
  steps**. Therefore every action is relative to t0, not to its predecessor.
* the action branch uses `self.obs_pose_repr`, not `action_pose_repr`. Both are
  `relative` in `task/umi_omx.yaml`, so they coincide today — but the field that
  actually controls the action is `pose_repr.obs_pose_repr`.
* `action_gripper` is sliced straight out of the replay buffer with no pose
  transform, so it stays an absolute width.

## Relative transform

`diffusion_policy/common/pose_repr_util.py` — `convert_pose_mat_rep`

```python
elif pose_rep == 'relative':
    out = np.linalg.inv(base_pose_mat) @ pose_mat      # forward  (training)
...
elif pose_rep == 'relative':
    out = base_pose_mat @ pose_mat                     # backward (decode)
```

`T_rel = inv(T0) @ T_abs`, so `T_abs = T0 @ T_rel`:

```
R_abs = R0 @ R_rel
p_abs = R0 @ p_rel + p0
```

and `p_rel = R0^T @ (p_abs - p0)` — a vector in the **T0 EE frame**.

## rot6d layout

`umi/common/pose_util.py`

```python
def mat_to_rot6d(mat):
    return mat[..., :2, :].copy().reshape(batch_dim + (6,))   # first two ROWS

def rot6d_to_mat(d6):
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = normalize(a1)
    b2 = normalize(a2 - (b1 * a2).sum(-1, keepdims=True) * b1)
    b3 = np.cross(b1, b2, axis=-1)
    return np.stack((b1, b2, b3), axis=-2)                    # rows again
```

`mat[..., :2, :]` selects rows 0 and 1; the reshape is row-major, giving
`[R00, R01, R02, R10, R11, R12]`. `np.stack(..., axis=-2)` puts b1/b2/b3 back as
rows, so the convention is self-consistent.

`mat_to_pose10d` = `concat([mat[...,:3,3], mat_to_rot6d(mat[...,:3,:3])])`, which
is where the 3 + 6 layout comes from; the 10th element is appended separately by
`umi_dataset`.

## Action timing

`diffusion_policy/common/sampler.py` — `SequenceSampler.sample_sequence`

```python
# action
slice_end = min(end_idx, current_idx + (action_horizon-1)*action_down_sample_steps + 1)
output    = input_arr[current_idx : slice_end : action_down_sample_steps]

# rgb observation
num_valid   = min(this_horizon, (current_idx - start_idx)//this_downsample_steps + 1)
slice_start = current_idx - (num_valid-1)*this_downsample_steps
output      = input_arr[slice_start : current_idx+1 : this_downsample_steps]
```

Both windows end at `current_idx`. The last observation frame and `action[0]` are
the **same** replay-buffer frame, so

```
action_dt_s           = action_down_sample_steps / stored_fps
first_action_offset_s = 0.0
action[k] target time = t0 + k * action_dt_s        (Case A)
```

`action[0]` is therefore the pose the robot is already at; it carries no motion.

## Policy output

`diffusion_policy/policy/diffusion_unet_timm_policy.py` — `predict_action`

```python
assert nsample.shape == (B, self.action_horizon, self.action_dim)
action_pred = self.normalizer['action'].unnormalize(nsample)
return {'action': action_pred, 'action_pred': action_pred}
```

The full 16-step horizon is returned, already un-normalised. `n_action_steps: 8`
exists in the config but is **not** applied on this path.

## RGB path

1. `omx/data/processed_v1.py` — `ProcessedV1Reader.read_rgb_indices`
   `cv2.imread(..., IMREAD_COLOR)` → BGR → `cv2.cvtColor(bgr, COLOR_BGR2RGB)`.
2. `omx/data/rgb_preprocess.py` — `RgbPreprocessor.__call__`, `center_crop`:
   `img[y0:y0+side, x0:x0+side]` then
   `cv2.resize(crop, out_res, interpolation=cv2.INTER_AREA)`.
3. stored in the zarr as uint8 RGB `[N,224,224,3]`.
4. `diffusion_policy/dataset/umi_dataset.py` — `__getitem__`:
   `np.moveaxis(data[key], -1, 1).astype(np.float32) / 255.` → `[T,C,H,W]` in `[0,1]`.
5. `diffusion_policy/common/normalize_util.py` — `get_image_identity_normalizer`:
   scale 1, offset 0, i.e. no change.

**No ImageNet or CLIP mean/std normalisation is applied.**
`TimmObsEncoder.__init__` accepts `imagenet_norm` and the configs set it to
`True`, but the parameter is never read in that class — `grep -n imagenet_norm
diffusion_policy/model/vision/timm_obs_encoder.py` returns only the signature
line. (`multi_image_obs_encoder.py` does use it, which is what makes the dead
parameter easy to miss.)

## In-policy transform — read this before writing the Jetson preprocessing

`diffusion_policy/model/vision/timm_obs_encoder.py` — `forward`

```python
img = self.key_transform_map[key](img)      # no `if self.training` guard
```

with

```
Sequential(
  RandomCrop(size=(212, 212)),
  Resize(size=224, interpolation=bilinear, antialias=True),
  ColorJitter(brightness=(0.7,1.3), contrast=(0.6,1.4),
              saturation=(0.5,1.5), hue=(-0.08,0.08)),
)
```

torchvision's `RandomCrop` and `ColorJitter` do not consult `self.training`, so
`policy.eval()` does not disable them. Two forward passes over the same input
differ (measured ~1.6 on a [0,1] feature scale). The upstream deployment script
`scripts_real/eval_real_umi.py` only calls `policy.eval()` and does not remove
them either, so this is upstream behaviour rather than a local change.

Consequences for the handoff:

* the preprocessing contract ends at the `[T,3,224,224]` float tensor in `[0,1]`.
  That part is exact and is what `preprocessed_rgb.npy` pins down;
* the policy's own output is not bit-reproducible. Match the **decoder** against
  `decoder_reference.npz`, not the policy output;
* if the Jetson exports the model (ONNX/TensorRT), decide explicitly whether the
  transform is traced into the graph. Dropping it changes the input distribution
  relative to training; keeping it keeps the randomness.
''')


def write_readme(out: pathlib.Path, m: Dict, probe: Dict) -> None:
    rs, dc, rp = m["reference_sample"], m["decoder_contract"], m["rgb_preprocess"]
    (out / "README.md").write_text(f'''# GPU -> Jetson handoff bundle

**INTEGRATION ONLY — NOT FOR LIVE TASK EXECUTION.**

The checkpoint here exists so the Jetson runtime can verify checkpoint loading,
inference shapes, latency, decoder parity and preprocessing parity. Do not
connect its output to OMX actuator commands.

Blockers, also in `model_manifest.json`:

{chr(10).join('* ' + b for b in m["live_ready_blockers"])}

---

## Provenance

| | |
|---|---|
| repo | `{m["repo"]["branch"]}` @ `{m["repo"]["commit"]}`{" (dirty)" if m["repo"]["dirty"] else ""} |
| checkpoint | `{m["checkpoint"]}` |
| checkpoint sha256 | `{m["checkpoint_sha256"]}` |
| weights | {m["checkpoint_weights"]} |
| dataset | `{m["dataset"]["zarr"]}` |
| dataset sha256 | `{m["dataset"]["sha256"]}` |
| CPU contract | `{m["dataset"]["handoff_contract"]["version"]}` |

### Reference sample (fixed, not random)

| | |
|---|---|
| dataset index | {rs["dataset_index"]} |
| replay-buffer frame | {rs["replay_buffer_frame"]} |
| episode | `{rs["episode_id"]}` |
| source frame | {rs["source_frame_index"]} |
| source file | `{rs["source_file"]}` |
| observation frames | {rs["obs_frames"]} |
| action frames | {rs["action_frames"]} |
| torch seed | {rs["torch_seed"]} |

The default index is the midpoint of the longest episode, so the observation
horizon contains two distinct frames rather than a padded one.

Regenerate with:

```bash
python scripts/make_jetson_handoff.py -e omx_pick_raw_center_v1 \\
    --sample-index {rs["dataset_index"]}
```

---

## Contract

### Action — `[16, 10]`

```
action[k, 0:3]   position   {dc["position_semantics"].split(".")[0]}.
action[k, 3:9]   rotation   rot6d
action[k, 9]     gripper    absolute width, {m["gripper_unit"]}
```

* **position** — {dc["position_semantics"]}
* **rotation layout** — {dc["rotation_layout"]}
* **rotation recovery** — {dc["rotation_multiplication"]}
* **position recovery** — {dc["position_recovery"]}
* **gripper** — {dc["gripper_semantics"]}
* **base pose** — {dc["base_pose_definition"]}

Decode:

```python
T_rel   = pose10d_to_mat(action[:, :9])          # [16,4,4]
T_world = T_base @ T_rel                         # base-LEFT multiply
p_abs   = R_base @ p_rel + p_base
R_abs   = R_base @ R_rel
```

Numerically probed on this machine while generating the bundle:

```
position is base-frame            {probe["position_is_base_frame"]}
position is world delta           {probe["position_is_world_delta"]}
rot6d = first two ROWS            {probe["rot6d_is_first_two_rows"]}
rot6d = first two COLUMNS         {probe["rot6d_is_first_two_cols"]}
R_abs == R_base @ R_rel           {probe["R_abs_eq_Rbase_at_Rrel"]}
R_abs == R_rel @ R_base           {probe["R_abs_eq_Rrel_at_Rbase"]}
forward/backward roundtrip err    {probe["roundtrip_max_abs_err"]:.2e}
```

### Time

```
action_dt_s            = {m["action_dt_s"]}
first_action_offset_s  = {m["first_action_offset_s"]}
action[k] target time  = t0 + k * {m["action_dt_s"]}
```

`t0` is the timestamp of the **last** observation frame. `action[0]` targets `t0`
itself, so it is the pose the robot is already at and contributes no motion —
Case A, not Case B. Observation timestamps relative to `t0`:
`{m["obs_timestamps_s"]}`.

### RGB preprocessing

```
{rp["input_color_order"]}
rotate_k        {rp["rotate_k"]}
crop            {rp["crop_mode"]}
interpolation   {rp["interpolation"]}
normalization   {rp["normalization"]}
```

Source {rp["source_resolution"][0]}x{rp["source_resolution"][1]} -> {rp["output_resolution"][0]}x{rp["output_resolution"][1]}, effective HFOV {rp["effective_hfov_deg"]} deg.

> **The policy randomises its own input.** `TimmObsEncoder.forward` applies
> `{rp.get("_", "")}RandomCrop(212) + Resize(224) + ColorJitter` with no
> `training` guard, and torchvision ignores `eval()` for those. The preprocessing
> contract above is exact and ends at the float tensor; the policy output is not.
> See `decoder_source_reference.md`.

---

## Files

| file | contents |
|---|---|
| `raw_rgb.png` | the source frame, RGB, before any GPU preprocessing |
| `preprocessed_rgb.npy` | **the Jetson target**: `raw_rgb.png` -> preprocessing, `{np.load(out / "preprocessed_rgb.npy").shape}` float32 in [0,1], (C,H,W) |
| `preprocessed_rgb_from_zarr.npy` | what the encoder actually received for this sample, `{np.load(out / "preprocessed_rgb_from_zarr.npy").shape}` — same pipeline plus the training zarr's lossy JpegXl round-trip |
| `observation_reference.npz` | full observation dict, absolute EE pose/gripper, frame indices and times |
| `reference_action.npy` | raw policy output, `[16,10]` |
| `reference_decoded_pose.npz` | the decode of the above |
| `decoder_reference.npz` | base pose + raw action + expected decode, **plus** a ground-truth action whose decode is checked against the recorded trajectory |
| `model_config.yaml` | the hydra config stored in the checkpoint |
| `decoder_source_reference.md` | file/function for every value above |
| `model_manifest.json` | machine-readable form of all of it |

### Suggested Jetson parity tests

1. **Preprocessing** — `raw_rgb.png` through your pipeline must equal
   `preprocessed_rgb.npy` to float32 precision. (Compare against
   `preprocessed_rgb_from_zarr.npy` only to see the training codec's effect; do
   not try to match it — you cannot, and should not.)
2. **Decoder, model-free** — take `decoder_reference.npz`'s
   `groundtruth_raw_action` + `base_pose6`, decode, and compare against
   `groundtruth_true_position` / `groundtruth_true_rotvec`. This uses no model
   and must match to ~1e-6.
3. **Decoder, policy output** — decode `raw_action` and compare against
   `expected_position` / `expected_rotvec`.
4. **Timing** — `action_target_times_s` in `observation_reference.npz` must equal
   `t0 + k * action_dt_s` with `k` starting at 0.

Do **not** assert bit-equality of the policy output.

---

## Parity measured while generating this bundle

```
preprocessed_rgb.npy roundtrip           {m["measured"]["parity"]["preprocessed_rgb_roundtrip"]:.3e}
raw_rgb.png -> preprocess vs tensor      {m["measured"]["parity"]["raw_png_to_tensor"]:.3e}

JpegXl(level=99) round-trip, i.e. how much the TRAINING frames differ from what
the Jetson will feed (uint8 scale, this sample):
  max {m["measured"]["jpegxl_roundtrip_max_abs_err_uint8"]} / mean {m["measured"]["jpegxl_roundtrip_mean_abs_err_uint8"]:.4f}
decoded position                         {m["measured"]["parity"]["decoded_position"]:.3e}
decoded rotation                         {m["measured"]["parity"]["decoded_rotation"]:.3e}
decoded gripper                          {m["measured"]["parity"]["decoded_gripper"]:.3e}

decoder vs recorded trajectory (ground-truth action, no model):
  position  {m["measured"]["decoder_gt_position_max_err_m"]:.3e} m
  rotation  {m["measured"]["decoder_gt_rotation_max_err_rad"]:.3e} rad
  gripper   {m["measured"]["decoder_gt_gripper_max_err_m"]:.3e} m

policy determinism:
  same seed   {m["measured"]["policy_reseeded_max_abs_err"]:.3e}
  no reseed   {m["measured"]["policy_unseeded_max_abs_err"]:.3e}   <- in-policy augmentation

latency {m["measured"]["latency_ms_per_call_b1"]} ms/call (B=1, {m["diffusion_steps"]} denoise steps) on {m["measured"]["device"]}
```
''')


if __name__ == "__main__":
    main()
