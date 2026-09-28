"""Open a sim zarr through the real UMI stack and report what it actually holds.

Two checks that are easy to skip and expensive to skip:

  * the zarr reopens through ReplayBuffer with the keys UmiDataset reads;
  * every action dimension carries signal.

The second one matters because a demonstration set can be perfectly valid and
still teach nothing along an axis. The first sim dataset had six rot6d
dimensions and x flat to 2e-4 -- a policy trained on it would emit constants
there, score well, and fail the moment the task needed rotation.

    python sim_umi/scripts/verify_dataset.py sim_umi/data/sim_umi_train.zarr.zip
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import click
import numpy as np
import zarr
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
from diffusion_policy.common.replay_buffer import ReplayBuffer

register_codecs()
OmegaConf.register_new_resolver("eval", eval, replace=True)

DIMS = ["px", "py", "pz", "r6_0", "r6_1", "r6_2", "r6_3", "r6_4", "r6_5", "grip"]
SIGNAL_TOL = 1e-3

#: rot6d is the first two ROWS of the rotation matrix, row-major:
#:     [R00 R01 R02 R10 R11 R12]
#: A yaw-only wrist gives R = [[c,-s,0],[s,c,0],[0,0,1]], so R02 and R12 are
#: zero by construction -- no amount of extra demonstration changes that. They
#: only move if the wrist tilts out of the horizontal plane, which a 5DoF OMX
#: cannot do and a top-down pick-and-place does not need. Flag them as expected
#: rather than as a hole in the data.
YAW_ONLY_ZERO = {"r6_2", "r6_5"}


@click.command()
@click.argument("zarr_path")
@click.option("--config", default="train_diffusion_unet_timm_omx_workspace")
@click.option("--max-samples", default=400, type=int)
def main(zarr_path, config, max_samples):
    fail = []

    click.echo("=" * 72)
    click.echo(f"[1] ReplayBuffer reopen  {zarr_path}")
    with zarr.ZipStore(zarr_path, mode="r") as s:
        rb = ReplayBuffer.copy_from_store(src_store=s, store=zarr.MemoryStore())
    required = {"camera0_rgb", "robot0_eef_pos", "robot0_eef_rot_axis_angle",
                "robot0_gripper_width", "robot0_demo_start_pose",
                "robot0_demo_end_pose"}
    missing = required - set(rb.keys())
    click.echo(f"  episodes {rb.n_episodes}   steps {rb.n_steps}")
    if missing:
        fail.append(f"missing keys: {sorted(missing)}")
        click.secho(f"  MISSING {sorted(missing)}", fg="red")
    for k in sorted(rb.keys()):
        a = rb[k][:]
        ok = a.dtype == np.uint8 or bool(np.isfinite(a).all())
        if not ok:
            fail.append(f"{k} not finite")
        click.echo(f"  {'ok ' if ok else 'BAD'}  {k:28s} {str(a.shape):20s} {a.dtype}")

    click.echo(f"\n[2] UmiDataset sampling")
    cfgdir = os.path.join(ROOT, "diffusion_policy", "config")
    with initialize_config_dir(config_dir=cfgdir, version_base=None):
        cfg = compose(config_name=config)
    from diffusion_policy.dataset.umi_dataset import UmiDataset
    ds = UmiDataset(shape_meta=OmegaConf.to_container(cfg.task.shape_meta, resolve=True),
                    dataset_path=zarr_path,
                    pose_repr=OmegaConf.to_container(cfg.task.pose_repr, resolve=True),
                    action_padding=False, val_ratio=0.0, seed=42)
    click.echo(f"  samples {len(ds)}")
    s0 = ds[0]
    for k, v in s0["obs"].items():
        a = v.numpy()
        if not np.isfinite(a).all():
            fail.append(f"obs/{k} not finite")
        click.echo(f"  obs/{k:42s} {str(tuple(a.shape)):18s} {a.dtype}")
    a0 = s0["action"].numpy()
    click.echo(f"  {'action':46s} {str(tuple(a0.shape)):18s} {a0.dtype}")
    if a0.shape != (16, 10):
        fail.append(f"action shape {a0.shape}, expected (16, 10)")

    n = min(len(ds), max_samples)
    idx = np.linspace(0, len(ds) - 1, n).astype(int)
    A = np.stack([ds[int(i)]["action"].numpy() for i in idx])
    if not np.isfinite(A).all():
        fail.append("action not finite across samples")

    click.echo(f"\n[3] action signal over {n} samples")
    click.echo(f"  {'dim':6s} {'std':>12s} {'min':>10s} {'max':>10s}   verdict")
    flat = []
    for i, name in enumerate(DIMS):
        v = A[:, :, i]
        ok = v.std() > SIGNAL_TOL
        if not ok and name not in YAW_ONLY_ZERO:
            flat.append(name)
        verdict = ("signal" if ok else
                   "zero by construction (yaw-only wrist)" if name in YAW_ONLY_ZERO
                   else "FLAT")
        click.echo(f"  {name:6s} {v.std():12.6f} {v.min():10.4f} {v.max():10.4f}   "
                   f"{verdict}")
    if flat:
        click.secho(f"\n  {len(flat)}/10 dimensions carry no signal: {flat}", fg="yellow")
        click.secho("  A policy will learn constants there. That is correct given "
                    "the data,\n  and invisible in the loss.", fg="yellow")

    click.echo("\n" + "=" * 72)
    if fail:
        click.secho(f"FAILED ({len(fail)}):", fg="red")
        for f in fail:
            click.secho(f"  - {f}", fg="red")
        raise SystemExit(1)
    click.secho("ALL CHECKS PASSED" + (f"  ({len(flat)} unexpectedly flat dims "
                                       f"-- see above)" if flat else ""), fg="green")


if __name__ == "__main__":
    main()
