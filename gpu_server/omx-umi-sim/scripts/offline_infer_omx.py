"""Offline inference + the GPU->robot handoff artefact (handoff doc sections 20-24).

    python -m omx.cli infer omx_pick_raw_center_v1
    python scripts/offline_infer_omx.py -e omx_pick_raw_center_v1 -n 4

Loads a checkpoint, feeds it real observations drawn from the dataset, runs
``predict_action()`` and writes both

  * the raw policy output, ``[B, 16, 10]``, exactly as the policy returns it, and
  * the decoded Cartesian targets, so the robot side can sanity-check its own
    decoder against ours.

Action semantics -- state these to the robot side verbatim:

    action[t, 0:3]  relative EE position     (metres)
    action[t, 3:9]  relative EE rotation     (6D, first two rows of R)
    action[t, 9]    gripper width            (metres, physical opening)

The 16 entries are 16 future targets expressed relative to the EE pose at the
*inference instant*.  They are NOT frame-to-frame deltas: target k is
``T_now @ T_rel[k]``, not ``target[k-1] @ delta``.  The policy always returns all
16; how many to execute before re-observing is the robot layer's decision
(``n_action_steps: 8`` in the config is not applied on this code path).
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import json
import pathlib
import time
from typing import Dict, List, Optional

import click
import dill
import hydra
import numpy as np
import torch
from omegaconf import OmegaConf

from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
from diffusion_policy.common.pose_repr_util import convert_pose_mat_rep
from diffusion_policy.workspace.base_workspace import BaseWorkspace
from omx import config as omx_config
from umi.common.pose_util import mat_to_pose, pose10d_to_mat, pose_to_mat

register_codecs()
OmegaConf.register_new_resolver("eval", eval, replace=True)


def find_latest_checkpoint(experiment: str) -> pathlib.Path:
    root = omx_config.TRAIN_DIR / experiment
    ckpts = sorted(root.glob("**/checkpoints/latest.ckpt"),
                   key=lambda p: p.stat().st_mtime)
    if not ckpts:
        ckpts = sorted(root.glob("**/checkpoints/*.ckpt"),
                       key=lambda p: p.stat().st_mtime)
    if not ckpts:
        raise click.ClickException(
            f"no checkpoint under {root}. Train first: "
            f"python -m omx.cli train {experiment}")
    return ckpts[-1]


@click.command()
@click.option("-e", "--experiment", default=None)
@click.option("-c", "--checkpoint", default=None, help="Explicit .ckpt path.")
@click.option("-d", "--dataset-path", default=None,
              help="Zarr to draw observations from. Defaults to the experiment's.")
@click.option("-o", "--out-dir", default=None)
@click.option("-n", "--num-samples", type=int, default=4)
@click.option("--sample-indices", default=None, help="Comma-separated dataset indices.")
@click.option("--device", default="cuda:0",
              help="Physical GPU selection is by CUDA_VISIBLE_DEVICES, not here.")
@click.option("--use-ema/--no-use-ema", default=True)
@click.option("--benchmark", type=int, default=0,
              help="Timed predict_action() repetitions (0 = skip).")
def main(experiment, checkpoint, dataset_path, out_dir, num_samples, sample_indices,
         device, use_ema, benchmark):
    if checkpoint is None:
        if experiment is None:
            raise click.UsageError("give --experiment or --checkpoint")
        checkpoint = find_latest_checkpoint(experiment)
    ckpt = pathlib.Path(checkpoint)
    out = pathlib.Path(out_dir or (omx_config.INFER_DIR / (experiment or ckpt.parent.parent.name)))
    out.mkdir(parents=True, exist_ok=True)

    click.echo("=" * 78)
    click.echo(f"checkpoint : {ckpt}")

    payload = torch.load(ckpt.open("rb"), pickle_module=dill, map_location="cpu")
    cfg = payload["cfg"]
    cls = hydra.utils.get_class(cfg._target_)
    workspace: BaseWorkspace = cls(cfg, output_dir=str(out))
    workspace.load_payload(payload, exclude_keys=None, include_keys=None)

    policy = workspace.model
    if use_ema and cfg.training.use_ema and getattr(workspace, "ema_model", None) is not None:
        policy = workspace.ema_model
        click.echo("weights    : EMA")
    else:
        click.echo("weights    : raw (non-EMA)")

    dev = torch.device(device)
    policy.to(dev).eval()
    policy.num_inference_steps = cfg.policy.num_inference_steps

    if dataset_path is None:
        dataset_path = cfg.task.dataset_path
    click.echo(f"dataset    : {dataset_path}")
    click.echo(f"device     : {dev}  (CUDA_VISIBLE_DEVICES="
               f"{os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')})")

    ds_cfg = OmegaConf.to_container(cfg.task.dataset, resolve=True)
    ds_cfg["dataset_path"] = str(dataset_path)
    dataset = hydra.utils.instantiate(OmegaConf.create(ds_cfg))
    click.echo(f"samples    : {len(dataset)}")

    if sample_indices:
        idxs = [int(x) for x in sample_indices.split(",")]
    else:
        idxs = np.linspace(0, len(dataset) - 1,
                           min(num_samples, len(dataset))).astype(int).tolist()

    # Absolute EE poses live in the replay buffer, not in the dataset sample
    # (the sample is already relative), so pull the base pose from there.
    rb = dataset.replay_buffer
    abs_pos = rb["robot0_eef_pos"][:]
    abs_rot = rb["robot0_eef_rot_axis_angle"][:]

    batch_obs: Dict[str, torch.Tensor] = {}
    base_poses: List[np.ndarray] = []
    for i in idxs:
        s = dataset[int(i)]
        for k, v in s["obs"].items():
            batch_obs.setdefault(k, []).append(v)
        current_idx = dataset.sampler.indices[int(i)][0]
        base_poses.append(np.concatenate([abs_pos[current_idx], abs_rot[current_idx]]))
    obs = {k: torch.stack(v).to(dev) for k, v in batch_obs.items()}
    base_poses_arr = np.stack(base_poses)

    click.echo("\n[input observation schema]")
    for k, v in obs.items():
        click.echo(f"  {k:38s} {tuple(v.shape)}  {v.dtype}")

    with torch.no_grad():
        t0 = time.perf_counter()
        result = policy.predict_action(obs, None)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
    action = result["action"].detach().cpu().numpy()

    click.echo("\n[policy output]")
    click.echo(f"  action                                 {action.shape}  {action.dtype}")
    click.echo(f"  first predict_action (incl. warmup)    {dt*1e3:.1f} ms "
               f"for B={action.shape[0]}")
    B, H, D = action.shape
    if (H, D) != (16, 10):
        raise click.ClickException(f"expected [B,16,10], got {action.shape}")
    if not np.isfinite(action).all():
        raise click.ClickException("policy produced non-finite actions")
    click.echo(f"  finite                                 True")
    click.echo(f"  pos     [m]     min={action[...,:3].min():+.5f} max={action[...,:3].max():+.5f}")
    click.echo(f"  rot6d           min={action[...,3:9].min():+.5f} max={action[...,3:9].max():+.5f}")
    click.echo(f"  gripper [m]     min={action[...,9].min():+.5f} max={action[...,9].max():+.5f}")

    if benchmark:
        with torch.no_grad():
            for _ in range(2):
                policy.predict_action(obs, None)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            for _ in range(benchmark):
                policy.predict_action(obs, None)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            per = (time.perf_counter() - t0) / benchmark
        click.echo(f"  steady-state latency                  {per*1e3:.1f} ms "
                   f"/ call (B={B}, {cfg.policy.num_inference_steps} denoise steps)")

    # ------------------------------------------------------- decode to SE(3) #
    # Same maths UmiDataset used to build the target, run backwards.
    decoded = []
    for b in range(B):
        rel_mat = pose10d_to_mat(action[b, :, :9])
        base_mat = pose_to_mat(base_poses_arr[b])
        world_mat = convert_pose_mat_rep(
            rel_mat, base_pose_mat=base_mat,
            pose_rep=dataset.action_pose_repr, backward=True)
        decoded.append(mat_to_pose(world_mat))          # [16, 6] pos + rotvec
    decoded = np.stack(decoded)

    click.echo("\n[decoded cartesian targets]  (pos + axis-angle, dataset pose frame)")
    click.echo(f"  decoded_pose6                          {decoded.shape}")
    click.echo(f"  sample 0 base pose                     "
               f"pos={base_poses_arr[0][:3].round(5).tolist()} "
               f"rotvec={base_poses_arr[0][3:].round(5).tolist()}")
    for t in (0, 1, H // 2, H - 1):
        click.echo(f"    t={t:2d}  pos={decoded[0, t, :3].round(5).tolist()}  "
                   f"rotvec={decoded[0, t, 3:].round(5).tolist()}  "
                   f"grip={action[0, t, 9]:.5f}")
    d0 = float(np.linalg.norm(decoded[0, 0, :3] - base_poses_arr[0][:3]))
    click.echo(f"  |decoded[0].pos - base.pos|            {d0:.6f} m")
    click.echo( "    (diagnostic only: ~0 for a converged policy, large for an "
                "under-trained checkpoint. The decoder itself is checked below.)")

    # ------------------------------------------------ decoder self-check ---- #
    # Model-independent proof that the documented decode procedure is right:
    # take the GROUND TRUTH action the dataset built, decode it the same way, and
    # compare against the actual future EE poses in the replay buffer.  If this
    # passes, the robot side can trust the recipe in sample_prediction.json.
    gt_err_pos, gt_err_rot = [], []
    act_ds = dataset.key_down_sample_steps["action"]
    for b, i in enumerate(idxs):
        gt = dataset[int(i)]["action"].numpy()
        cur, _, end, _ = dataset.sampler.indices[int(i)]
        gt_world = mat_to_pose(convert_pose_mat_rep(
            pose10d_to_mat(gt[:, :9]),
            base_pose_mat=pose_to_mat(base_poses_arr[b]),
            pose_rep=dataset.action_pose_repr, backward=True))
        tgt_idx = np.arange(cur, min(end, cur + (H - 1) * act_ds + 1), act_ds)
        k = len(tgt_idx)
        gt_err_pos.append(np.abs(gt_world[:k, :3] - abs_pos[tgt_idx]).max())
        ref_rot = abs_rot[tgt_idx]
        # compare rotations as matrices; axis-angle is 2*pi-ambiguous
        import scipy.spatial.transform as _st
        dR = (_st.Rotation.from_rotvec(gt_world[:k, 3:])
              * _st.Rotation.from_rotvec(ref_rot).inv()).magnitude()
        gt_err_rot.append(float(np.max(dR)))
    max_p, max_r = float(np.max(gt_err_pos)), float(np.max(gt_err_rot))
    click.echo("\n[decoder self-check]  ground-truth action -> decode -> replay buffer")
    click.echo(f"  max position error                     {max_p:.3e} m")
    click.echo(f"  max rotation error                     {max_r:.3e} rad")
    decoder_ok = max_p < 1e-4 and max_r < 1e-4
    if decoder_ok:
        click.secho("  decoder is correct: the documented recipe reproduces the "
                    "recorded EE trajectory exactly.", fg="green")
    else:
        click.secho("  DECODER MISMATCH -- do not hand this recipe to the robot side.",
                    fg="red", bold=True)

    # -------------------------------------------------------------- persist #
    np.save(out / "sample_prediction.npy", action)
    np.savez(out / "sample_prediction_full.npz",
             action=action,
             relative_position=action[..., :3],
             rotation_6d=action[..., 3:9],
             gripper=action[..., 9],
             decoded_pose6=decoded,
             base_pose6=base_poses_arr,
             dataset_indices=np.array(idxs))

    handoff = {
        "schema": "omx-policy-output/1",
        "checkpoint": str(ckpt),
        "dataset": str(dataset_path),
        "weights": "ema" if policy is getattr(workspace, "ema_model", None) else "raw",
        "epoch": int(payload.get("epoch", -1)) if isinstance(payload.get("epoch", -1), int) else -1,
        "action_shape": list(action.shape),
        "action_layout": {
            "0:3": "relative EE position (metres)",
            "3:9": "relative EE rotation, 6D (first two rows of the rotation matrix)",
            "9": "gripper width (metres, physical finger opening)",
        },
        "semantics": (
            "16 future EE targets, each expressed RELATIVE TO THE EE POSE AT THE "
            "INFERENCE INSTANT. NOT frame-to-frame deltas: "
            "T_world_target[k] = T_world_now @ T_rel[k]."
        ),
        "normalization": "already un-normalized; these are physical units",
        "pose_repr": {"obs": dataset.obs_pose_repr, "action": dataset.action_pose_repr},
        "policy_hz": None,
        "observation_schema": {k: list(v.shape) for k, v in obs.items()},
        "n_action_steps_config": int(getattr(cfg, "n_action_steps", -1)),
        "n_action_steps_applied": False,
        "decoder_self_check": {
            "max_position_error_m": max_p,
            "max_rotation_error_rad": max_r,
            "passed": bool(decoder_ok),
            "recipe": ("T_rel = pose10d_to_mat(action[..., :9]); "
                       "T_world_target = T_world_now @ T_rel"),
        },
        "samples": [],
    }
    meta_side = pathlib.Path(str(dataset_path)).with_suffix("").with_suffix(".meta.json")
    if meta_side.is_file():
        m = json.loads(meta_side.read_text())
        handoff["policy_hz"] = m["collector_config"]["timing"]["policy_hz"]
        handoff["rgb_preprocess"] = m["rgb_preprocess"]
        handoff["camera_to_ee_calibration_version"] = m["camera_to_ee_calibration_version"]
        handoff["camera_to_ee_status"] = m["camera_to_ee_status"]
        handoff["gripper"] = {k: m["gripper"][k] for k in
                              ("representation", "unit", "closed_width_m", "open_width_m", "status")}
        handoff["pose_frame"] = m["collector_config"]["pose"]["pose_frame"]
        handoff["world_axis_remap"] = m["collector_config"]["pose"]["world_axis_remap"]

    for b in range(B):
        handoff["samples"].append({
            "dataset_index": int(idxs[b]),
            "base_pose6": base_poses_arr[b].round(6).tolist(),
            "relative_position": action[b, :, :3].round(6).tolist(),
            "rotation_6d": action[b, :, 3:9].round(6).tolist(),
            "gripper": action[b, :, 9].round(6).tolist(),
            "decoded_pose6": decoded[b].round(6).tolist(),
        })
    with open(out / "sample_prediction.json", "w") as f:
        json.dump(handoff, f, indent=2)

    click.secho(f"\nwrote {out}/", fg="green")
    for n in ("sample_prediction.npy", "sample_prediction_full.npz", "sample_prediction.json"):
        click.echo(f"  {n}")


if __name__ == "__main__":
    main()
