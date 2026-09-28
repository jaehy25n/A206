"""What the trained policy predicts, against what the demonstration did.

    python sim_umi/scripts/eval_policy_offline.py \
        --checkpoint data/omx/train/omx_sim_pick_v1/.../checkpoints/latest.ckpt \
        --zarr sim_umi/data/omx_sim_val.zarr.zip

Open loop and in real units. The training log reports one mean squared error
over a normalised 10-vector, which cannot say whether 5 mm of position or half
a degree of wrist roll is what it got wrong. This splits the action apart --
position in millimetres, rotation in degrees, gripper width in millimetres --
and reports it per step of the 16-step horizon, because a policy that is right
about the next action and wrong about the sixteenth is a different animal from
one that is uniformly mediocre.

Run it on the training zarr too. The gap between the two is the only thing that
says whether the policy learned the task or the episodes.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import click
import dill
import hydra
import numpy as np
import torch
from omegaconf import OmegaConf, open_dict

from diffusion_policy.workspace.base_workspace import BaseWorkspace
from diffusion_policy.common.pytorch_util import dict_apply


def rot6d_to_matrix(a):
    """The contract's rotation: the first two ROWS of R, row-major."""
    a = np.asarray(a, float).reshape(*a.shape[:-1], 2, 3)
    r0 = a[..., 0, :] / np.linalg.norm(a[..., 0, :], axis=-1, keepdims=True)
    r1 = a[..., 1, :] - (a[..., 1, :] * r0).sum(-1, keepdims=True) * r0
    r1 = r1 / np.linalg.norm(r1, axis=-1, keepdims=True)
    r2 = np.cross(r0, r1)
    return np.stack([r0, r1, r2], axis=-2)


def angle_between(Ra, Rb):
    """Geodesic angle between two rotations, in degrees."""
    R = np.einsum("...ij,...kj->...ik", Ra, Rb)
    t = (np.trace(R, axis1=-2, axis2=-1) - 1.0) / 2.0
    return np.degrees(np.arccos(np.clip(t, -1.0, 1.0)))


@click.command()
@click.option("--checkpoint", required=True)
@click.option("--zarr", "zarr_path", required=True)
@click.option("--device", default="cuda:0")
@click.option("--batch-size", default=32, type=int)
@click.option("--max-batches", default=0, type=int, help="0 = the whole set")
@click.option("--spread", is_flag=True,
              help="predict twice per observation and report how far the two "
                   "samples fall apart, which is the part of the error that is "
                   "diffusion sampling rather than a policy that did not learn")
def main(checkpoint, zarr_path, device, batch_size, max_batches, spread):
    payload = torch.load(pathlib.Path(checkpoint).open("rb"), pickle_module=dill,
                         map_location="cpu")
    cfg = payload["cfg"]
    ws: BaseWorkspace = hydra.utils.get_class(cfg._target_)(
        cfg, output_dir=str(ROOT / "sim_umi" / "outputs" / "eval_offline"))
    ws.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = ws.model
    weights = "raw"
    if cfg.training.use_ema and getattr(ws, "ema_model", None) is not None:
        policy = ws.ema_model
        weights = "ema"
    policy.to(device).eval()

    # The dataset is built from the checkpoint's own task config, so the
    # horizons, the pose representation and the rotation format are the ones
    # the policy was trained under and not a fresh guess at them.
    with open_dict(cfg):
        cfg.task.dataset.dataset_path = str(pathlib.Path(zarr_path).resolve())
        cfg.task.dataset.val_ratio = 0.0
    ds = hydra.utils.instantiate(cfg.task.dataset)
    click.secho(f"checkpoint {checkpoint}", bold=True)
    click.echo(f"  weights {weights}   epoch {payload.get('state_dicts', {}) and ''}"
               f"{ws.epoch}   diffusion steps "
               f"{cfg.policy.num_inference_steps}")
    click.echo(f"  {pathlib.Path(zarr_path).name}: {len(ds)} samples "
               f"over {ds.replay_buffer.n_episodes} episodes")

    loader = torch.utils.data.DataLoader(ds, batch_size=batch_size, shuffle=False,
                                         num_workers=4, pin_memory=True)
    ep, er, ew, sp = [], [], [], []
    with torch.no_grad():
        for i, batch in enumerate(loader):
            if max_batches and i >= max_batches:
                break
            obs = dict_apply(batch["obs"], lambda x: x.to(device, non_blocking=True))
            gt = batch["action"].numpy()
            pred = policy.predict_action(obs, None)["action_pred"].cpu().numpy()
            ep.append(np.linalg.norm(pred[..., :3] - gt[..., :3], axis=-1))
            er.append(angle_between(rot6d_to_matrix(pred[..., 3:9]),
                                    rot6d_to_matrix(gt[..., 3:9])))
            ew.append(np.abs(pred[..., 9] - gt[..., 9]))
            if spread:
                p2 = policy.predict_action(obs, None)["action_pred"].cpu().numpy()
                sp.append(np.linalg.norm(p2[..., :3] - pred[..., :3], axis=-1))
    ep = np.concatenate(ep) * 1000.0          # mm
    er = np.concatenate(er)                   # deg
    ew = np.concatenate(ew) * 1000.0          # mm

    click.secho("\n  over every sample and every step of the horizon", bold=True)
    for name, v, unit in (("position", ep, "mm"), ("rotation", er, "deg"),
                          ("width", ew, "mm")):
        click.echo(f"    {name:9s} mean {v.mean():7.3f}  p95 {np.percentile(v, 95):7.3f}"
                   f"  max {v.max():8.3f} {unit}")

    sp = np.concatenate(sp) * 1000.0 if sp else None
    if sp is not None:
        click.secho("\n  two samples from the same observation, how far apart",
                    bold=True)
        click.echo(f"    position  mean {sp.mean():7.3f}  p95 "
                   f"{np.percentile(sp, 95):7.3f} mm")

    click.secho("\n  by step of the 16-step horizon (mean)", bold=True)
    head = f"    {'step':>4s} {'pos mm':>8s} {'rot deg':>8s} {'width mm':>9s}"
    click.echo(head + ("" if sp is None else f" {'spread mm':>10s}"))
    for k in range(ep.shape[1]):
        line = (f"    {k:4d} {ep[:, k].mean():8.3f} {er[:, k].mean():8.3f} "
                f"{ew[:, k].mean():9.3f}")
        click.echo(line + ("" if sp is None else f" {sp[:, k].mean():10.3f}"))


if __name__ == "__main__":
    main()
