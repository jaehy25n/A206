"""One entry point for the whole OMX GPU workflow.

    python -m omx.cli list
    python -m omx.cli build   omx_pick_raw_center_v1 [--dry-run]
    python -m omx.cli inspect omx_pick_raw_center_v1
    python -m omx.cli train   omx_pick_raw_center_v1 --profile smoke
    python -m omx.cli train   omx_pick_raw_center_v1
    python -m omx.cli infer   omx_pick_raw_center_v1
    python -m omx.cli ab      omx_pick_raw_center_v1 omx_pick_matched_center_v1
    python -m omx.cli env

Everything runs on physical GPU 5 only (``CUDA_VISIBLE_DEVICES``), which the
process then sees as ``cuda:0``.

``train`` reads ``umi_task_requirements`` out of the zarr metadata and forces the
matching ``obs_down_sample_steps``, so the dataset can never be decimated twice,
and stamps dataset/calibration/git provenance into ``meta.*`` -- which
``accelerator.init_trackers`` logs verbatim into the W&B run config.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional

import click

from omx import config as omx_config

REPO = omx_config.REPO_ROOT
PY = sys.executable


def _run(cmd: List[str], env: Optional[Dict[str, str]] = None, dry: bool = False) -> int:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    shown = " ".join(f"{k}={v}" for k, v in (env or {}).items())
    click.secho(f"\n$ {shown} {' '.join(cmd)}\n", fg="cyan")
    if dry:
        return 0
    return subprocess.call(cmd, cwd=str(REPO), env=full_env)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(("git",) + args, cwd=str(REPO),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def _zarr_metadata(path: pathlib.Path) -> Optional[dict]:
    side = path.with_suffix("").with_suffix(".meta.json")
    if side.is_file():
        return json.loads(side.read_text())
    try:
        import zarr
        from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
        register_codecs()
        with zarr.ZipStore(str(path), mode="r") as zs:
            return zarr.group(zs)["meta"].attrs.get("omx")
    except Exception:
        return None


@click.group()
def cli():
    """OMX-UMI GPU workflow."""


# --------------------------------------------------------------------------- #
@cli.command("list")
def list_cmd():
    """Show every registered experiment and whether its dataset is built."""
    click.echo(f"GPU                : {omx_config.GPU_DEVICE} (physical)")
    click.echo(f"processed_v1 root  : {omx_config.PROCESSED_ROOT}"
               f"{'' if pathlib.Path(omx_config.PROCESSED_ROOT).exists() else '   [NOT PRESENT]'}")
    click.echo(f"data root          : {omx_config.DATA_ROOT}")
    click.echo(f"W&B project        : {omx_config.WANDB_PROJECT}\n")
    for e in omx_config.list_experiments():
        z = e.zarr_path
        mark = click.style("built", fg="green") if z.is_file() else click.style("not built", fg="yellow")
        size = f"{z.stat().st_size/1e6:8.1f} MB" if z.is_file() else " " * 11
        click.echo(f"  {e.name:32s} rgb={e.dataset.rgb_mode:20s} {mark:>22s} {size}")
        if e.notes:
            click.echo(f"      {e.notes.splitlines()[0]}")


# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("experiment")
@click.option("--dry-run", is_flag=True)
@click.option("--overwrite", is_flag=True)
@click.argument("extra", nargs=-1)
def build(experiment, dry_run, overwrite, extra):
    """Build the experiment's zarr from the processed_v1 tree."""
    omx_config.ensure_dirs()
    cmd = [PY, "scripts/convert_processed_to_umi_zarr.py", "-e", experiment]
    if dry_run:
        cmd.append("--dry-run")
    if overwrite:
        cmd.append("--overwrite")
    cmd.extend(extra)
    sys.exit(_run(cmd))


@cli.command()
@click.argument("experiment")
@click.argument("extra", nargs=-1)
def inspect(experiment, extra):
    """Run every dataset check and export plots/samples."""
    omx_config.ensure_dirs()
    sys.exit(_run([PY, "scripts/inspect_umi_zarr.py", "-e", experiment, *extra]))


# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("experiment")
@click.option("--profile", type=click.Choice(sorted(omx_config.TRAIN_PROFILES)),
              default="full", show_default=True)
@click.option("--resume", is_flag=True)
@click.option("--dry-run", is_flag=True, help="Print the command without running it.")
@click.option("--no-hash", is_flag=True, help="Skip the dataset sha256 (faster start).")
@click.argument("extra", nargs=-1)
def train(experiment, profile, resume, dry_run, no_hash, extra):
    """Launch training on GPU 5 with full provenance."""
    exp = omx_config.get(experiment)
    omx_config.ensure_dirs()
    zp = exp.zarr_path
    if not zp.is_file():
        raise click.ClickException(
            f"dataset not built: {zp}\n  run: python -m omx.cli build {experiment}")

    meta = _zarr_metadata(zp)
    if meta is None:
        raise click.ClickException(
            f"{zp} has no omx metadata. Rebuild it with "
            f"scripts/convert_processed_to_umi_zarr.py so the run is traceable.")

    req = meta.get("umi_task_requirements", {})
    ds_steps = int(req.get("obs_down_sample_steps", 1))
    cc = meta["collector_config"]
    d = meta["dataset"]

    if d.get("synthetic"):
        click.secho(f"  ! {d.get('n_synthetic_episodes', '?')} SYNTHETIC episode(s) in "
                    f"this dataset. Logged as dataset_synthetic=true in W&B.",
                    fg="yellow", bold=True)
    if meta["camera_to_ee_status"] != "calibrated" or meta["gripper"]["status"] != "calibrated":
        click.secho(
            "  ! This dataset uses PLACEHOLDER calibration "
            f"(camera_to_ee={meta['camera_to_ee_status']}, "
            f"gripper={meta['gripper']['status']}). Fine for a Stage A integration "
            "run; not a reportable baseline.", fg="yellow")

    overrides = [
        f"task.dataset_path={zp.resolve()}",
        f"task.obs_down_sample_steps={ds_steps}",
        f"task.dataset.seed={exp.seed}",
        f"task.dataset.val_ratio={exp.val_ratio}",
        f"training.seed={exp.seed}",
        f"exp_name={exp.name}",
        f"logging.project={omx_config.WANDB_PROJECT}",
        "training.device=cuda:0",
    ]
    if resume:
        overrides.append("training.resume=True")
    overrides.extend(omx_config.TRAIN_PROFILES[profile])
    overrides.extend(exp.train_overrides)

    prov = {
        "experiment": exp.name,
        "dataset_name": d["name"],
        "dataset_zarr": str(zp.resolve()),
        "dataset_sha256": "skipped" if no_hash else _sha256(zp),
        "dataset_n_episodes": d["n_episodes"],
        "dataset_n_frames": d["n_frames"],
        "dataset_stored_fps": d["stored_fps"],
        "dataset_synthetic": bool(d.get("synthetic", False)),
        "rgb_mode": meta["rgb_preprocess"]["mode"],
        "rgb_out_res": "x".join(str(v) for v in meta["rgb_preprocess"]["out_res"]),
        "camera_to_ee_calibration_version": meta["camera_to_ee_calibration_version"],
        "camera_to_ee_status": meta["camera_to_ee_status"],
        "gripper_status": meta["gripper"]["status"],
        "gripper_representation": meta["gripper"]["representation"],
        "collector_calibration_version": cc["calibration_version"],
        "policy_hz": cc["timing"]["policy_hz"],
        "obs_down_sample_steps": ds_steps,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "cuda_visible_devices": omx_config.GPU_DEVICE,
        "train_profile": profile,
    }
    overrides.extend(f"meta.{k}={json.dumps(v) if isinstance(v, bool) else v}"
                     for k, v in prov.items())
    overrides.extend(extra)

    if prov["git_dirty"]:
        click.secho("  ! working tree is dirty; the logged git commit will not fully "
                    "describe this run.", fg="yellow")

    env = {"CUDA_VISIBLE_DEVICES": omx_config.GPU_DEVICE}
    if exp.mixed_precision != "no":
        env["ACCELERATE_MIXED_PRECISION"] = exp.mixed_precision
        click.secho(f"  mixed precision: {exp.mixed_precision} "
                    f"(V100 has no bf16/TF32, so fp16 is the only speedup available)",
                    fg="cyan")

    click.echo(f"\nexperiment  : {exp.name}   profile: {profile}")
    click.echo(f"dataset     : {zp.name}  {d['n_episodes']} episodes / "
               f"{d['n_frames']} frames @ {d['stored_fps']} Hz")
    click.echo(f"rgb mode    : {prov['rgb_mode']} {prov['rgb_out_res']}")
    click.echo(f"calibration : camera_to_ee={prov['camera_to_ee_calibration_version']} "
               f"gripper={prov['gripper_status']}")

    cmd = [PY, "train.py", "--config-name=train_diffusion_unet_timm_omx_workspace", *overrides]
    sys.exit(_run(cmd, env=env, dry=dry_run))


# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("experiment")
@click.argument("extra", nargs=-1)
def infer(experiment, extra):
    """Run offline inference from the experiment's latest checkpoint."""
    omx_config.ensure_dirs()
    sys.exit(_run([PY, "scripts/offline_infer_omx.py", "-e", experiment, *extra],
                  env={"CUDA_VISIBLE_DEVICES": omx_config.GPU_DEVICE}))


LOWDIM_KEYS = ("robot0_eef_pos", "robot0_eef_rot_axis_angle", "robot0_gripper_width",
               "robot0_demo_start_pose", "robot0_demo_end_pose")


@cli.command()
@click.argument("experiment_a")
@click.argument("experiment_b")
def ab(experiment_a, experiment_b):
    """Check that two experiments form a fair A/B pair (handoff doc section 25).

    Checks the registry declarations AND, when both zarrs exist, that their
    low-dim streams and episode boundaries are byte-identical while the images
    actually differ.
    """
    import numpy as np

    a, b = omx_config.get(experiment_a), omx_config.get(experiment_b)
    problems = omx_config.check_ab_comparable(a, b)
    click.echo(f"A: {a.name}  rgb={a.dataset.rgb_mode}  {a.zarr_path.name}")
    click.echo(f"B: {b.name}  rgb={b.dataset.rgb_mode}  {b.zarr_path.name}")

    if a.zarr_path.is_file() and b.zarr_path.is_file():
        import zarr
        from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
        from diffusion_policy.common.replay_buffer import ReplayBuffer
        register_codecs()

        def load(p):
            with zarr.ZipStore(str(p), mode="r") as zs:
                return ReplayBuffer.copy_from_store(src_store=zs, store=zarr.MemoryStore())

        click.echo("\nchecking the built datasets...")
        ra, rb_ = load(a.zarr_path), load(b.zarr_path)
        if not np.array_equal(ra.episode_ends[:], rb_.episode_ends[:]):
            problems.append("episode_ends differ between the built zarrs")
        else:
            click.echo(f"  episode_ends            identical ({ra.n_episodes} episodes, "
                       f"{ra.n_steps} frames)")
        for k in LOWDIM_KEYS:
            if k not in ra or k not in rb_:
                problems.append(f"{k} missing from one of the zarrs")
            elif not np.array_equal(ra[k][:], rb_[k][:]):
                problems.append(f"{k} differs between the built zarrs -- "
                                f"the trajectories are not the same data")
            else:
                click.echo(f"  {k:24s} identical")
        n = min(8, ra.n_steps)
        if np.array_equal(ra["camera0_rgb"][:n], rb_["camera0_rgb"][:n]):
            problems.append("camera0_rgb is identical -- the two variants are the "
                            "same dataset, so there is nothing to compare")
        else:
            click.echo("  camera0_rgb              differs (as intended)")
    else:
        click.secho("\n(build both datasets to also verify their contents)", fg="yellow")

    if not problems:
        click.secho("\nFAIR: only the RGB pipeline differs. Episodes, poses, gripper, "
                    "seed and train/val split are identical.", fg="green")
        return
    click.secho("\nNOT a fair comparison:", fg="red", bold=True)
    for p in problems:
        click.secho(f"  - {p}", fg="red")
    sys.exit(1)


@cli.command()
def env():
    """Report the GPU, environment and W&B login state."""
    click.echo(f"python        : {sys.executable}")
    try:
        import torch
        click.echo(f"torch         : {torch.__version__}  cuda={torch.version.cuda}")
        if torch.cuda.is_available():
            i = 0
            cap = torch.cuda.get_device_capability(i)
            click.echo(f"device[0]     : {torch.cuda.get_device_name(i)}  sm_{cap[0]}{cap[1]}")
            click.echo(f"bf16 support  : {torch.cuda.is_bf16_supported()}  "
                       f"(sm_70 has neither bf16 nor TF32; fp16 is the only speedup)")
    except Exception as e:
        click.secho(f"torch         : {e}", fg="red")

    click.echo(f"CUDA_VISIBLE_DEVICES (this shell): "
               f"{os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')}")
    click.echo(f"omx will use  : CUDA_VISIBLE_DEVICES={omx_config.GPU_DEVICE}")
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu",
             "--format=csv,noheader"]).decode().strip().splitlines()
        for line in out:
            idx = line.split(",")[0].strip()
            marker = "  <-- ours" if idx == str(omx_config.GPU_DEVICE) else ""
            click.echo(f"  gpu {line}{marker}")
    except (subprocess.CalledProcessError, OSError):
        pass

    key = bool(os.environ.get("WANDB_API_KEY"))
    netrc = pathlib.Path.home() / ".netrc"
    click.echo(f"\nW&B project   : {omx_config.WANDB_PROJECT}")
    try:
        import wandb
        from packaging.version import Version
        wv = wandb.__version__
        # wandb < 0.22.3 hard-rejects the newer `wandb_v1_...` API keys with
        # "API key must be 40 characters long", which reads like a bad key.
        old_client = Version(wv) < Version("0.22.3")
        click.echo(f"wandb         : {wv}"
                   + ("   <-- too old for wandb_v1_ keys (need >= 0.22.3)"
                      if old_client else ""))
        if old_client:
            click.secho("  ! Upgrade before logging in, or the new key format fails "
                        "with a misleading length error: "
                        "pip install 'wandb>=0.22.3'", fg="yellow")
    except Exception as e:                                   # pragma: no cover
        click.secho(f"wandb         : {e}", fg="red")
    click.echo(f"WANDB_API_KEY : {'set in this shell' if key else 'not set in this shell'}")
    click.echo(f"~/.netrc      : {'present' if netrc.is_file() else 'absent'}")

    logged_in = False
    try:
        import wandb
        entity = wandb.Api().default_entity
        if entity:
            logged_in = True
            click.secho(f"logged in as  : {entity}", fg="green")
    except Exception:
        pass
    if not logged_in and not key:
        click.secho("  ! No usable W&B credential. Training falls back to "
                    "offline/anonymous mode. Run `wandb login` once.", fg="yellow")


if __name__ == "__main__":
    cli()
