"""Inspect an OMX UMI zarr and prove it is trainable (handoff doc section 15).

Prints the dataset statistics, exports RGB samples and trajectory plots, then
actually builds ``UmiDataset`` and pulls ``dataset[0]`` so the P0 completion
criteria are checked rather than assumed.

    python scripts/inspect_umi_zarr.py data/omx/zarr/omx_pick_raw_center_v1.zarr.zip
    python scripts/inspect_umi_zarr.py -e omx_pick_raw_center_v1

Exit code is non-zero if any hard check fails, so it works in CI.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import json
import pathlib
from typing import Dict, List, Optional

import click
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import zarr

from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
from diffusion_policy.common.replay_buffer import ReplayBuffer
from diffusion_policy.common.sampler import get_val_mask
from omx import config as omx_config

register_codecs()

REQUIRED_KEYS = ("camera0_rgb", "robot0_eef_pos", "robot0_eef_rot_axis_angle",
                 "robot0_gripper_width", "robot0_demo_start_pose", "robot0_demo_end_pose")
UPSTREAM_GRIPPER_THRESHOLD = 0.08     # SequenceSampler's before_first_grasp heuristic


class Report:
    def __init__(self):
        self.failures: List[str] = []
        self.warnings: List[str] = []

    def check(self, ok: bool, msg: str) -> bool:
        if ok:
            click.secho(f"  [ok]   {msg}", fg="green")
        else:
            click.secho(f"  [FAIL] {msg}", fg="red", bold=True)
            self.failures.append(msg)
        return ok

    def warn(self, msg: str) -> None:
        click.secho(f"  [warn] {msg}", fg="yellow")
        self.warnings.append(msg)


def _stats_row(name: str, arr: np.ndarray) -> str:
    a = np.asarray(arr, dtype=np.float64).reshape(len(arr), -1) if arr.ndim > 1 \
        else np.asarray(arr, dtype=np.float64).reshape(-1, 1)
    nan = int(np.isnan(a).sum())
    inf = int(np.isinf(a).sum())
    finite = a[np.isfinite(a)]
    lo = finite.min() if finite.size else float("nan")
    hi = finite.max() if finite.size else float("nan")
    mu = finite.mean() if finite.size else float("nan")
    return (f"  {name:28s} {str(tuple(arr.shape)):>20s} {str(arr.dtype):>8s}  "
            f"min={lo:+10.5f} max={hi:+10.5f} mean={mu:+10.5f}  nan={nan} inf={inf}")


@click.command()
@click.argument("zarr_path", required=False)
@click.option("-e", "--experiment", default=None, help="Use the registered experiment's zarr.")
@click.option("-o", "--out-dir", default=None, help="Where plots/samples go.")
@click.option("--n-rgb-samples", type=int, default=12)
@click.option("--no-dataset", is_flag=True, help="Skip the UmiDataset construction.")
@click.option("--no-plots", is_flag=True)
def main(zarr_path, experiment, out_dir, n_rgb_samples, no_dataset, no_plots):
    if experiment:
        exp = omx_config.get(experiment)
        zarr_path = zarr_path or str(exp.zarr_path)
        out_dir = out_dir or str(omx_config.INSPECT_DIR / exp.name)
    if not zarr_path:
        raise click.UsageError("give a zarr path or --experiment")
    zp = pathlib.Path(zarr_path)
    if not zp.is_file():
        raise click.ClickException(f"not found: {zp}")
    out = pathlib.Path(out_dir or (omx_config.INSPECT_DIR / zp.name.split(".")[0]))
    out.mkdir(parents=True, exist_ok=True)

    rep = Report()
    click.echo("=" * 78)
    click.echo(f"inspect {zp}  ({zp.stat().st_size / 1e6:.1f} MB)")
    click.echo("=" * 78)

    with zarr.ZipStore(str(zp), mode="r") as zs:
        rb = ReplayBuffer.copy_from_store(src_store=zs, store=zarr.MemoryStore())
    meta: Optional[Dict] = rb.root["meta"].attrs.get("omx")

    # ------------------------------------------------------------ provenance #
    click.secho("\n[provenance]", bold=True)
    side = zp.with_suffix("").with_suffix(".meta.json")
    if meta is None and side.is_file():
        meta = json.loads(side.read_text())
        click.echo(f"  (from sidecar {side.name})")
    if meta is None:
        rep.warn("no omx metadata -- this zarr was not produced by "
                 "scripts/convert_processed_to_umi_zarr.py; provenance is unknown")
        task_req = {}
    else:
        d, g = meta["dataset"], meta["gripper"]
        cc = meta["collector_config"]
        click.echo(f"  schema                : {meta['schema']}")
        click.echo(f"  created               : {meta['created_utc']}")
        click.echo(f"  git                   : {meta['git']['branch']}@{meta['git']['commit'][:10]}"
                   f"{' (dirty)' if meta['git']['dirty'] else ''}")
        click.echo(f"  rgb mode              : {meta['rgb_preprocess']['mode']} -> "
                   f"{meta['rgb_preprocess']['out_res']}  "
                   f"HFOV {meta['rgb_preprocess'].get('effective_hfov_deg', '?')} deg")
        click.echo(f"  collector calibration : {cc['calibration_version']}")
        click.echo(f"  camera_to_ee          : {meta['camera_to_ee_status']} / "
                   f"{meta['camera_to_ee_calibration_version']}")
        click.echo(f"  gripper               : {g['representation']} [{g['unit']}] "
                   f"status={g['status']} source={g['source']}")
        click.echo(f"  timing                : {cc['timing']['source_fps']} Hz -> "
                   f"{cc['timing']['policy_hz']} Hz, stored at {d['stored_fps']} Hz")
        click.echo(f"  pose frame            : {cc['pose']['pose_frame']}  "
                   f"world_axis_remap={cc['pose']['world_axis_remap']}")
        task_req = meta.get("umi_task_requirements", {})
        if meta["camera_to_ee_status"] != "calibrated":
            rep.warn("T_camera_to_ee is a PLACEHOLDER -- EE poses are not physically "
                     "calibrated. Fine for integration, not for a reported result.")
        if g["status"] != "calibrated":
            rep.warn("gripper widths are PLACEHOLDERS.")
        if d.get("synthetic"):
            rep.warn(f"{d.get('n_synthetic_episodes', '?')} episode(s) are SYNTHETIC "
                     f"(metadata.json synthetic: true) -- pipeline fixture, not a result.")
        for w in meta.get("warnings", [])[:10]:
            click.echo(f"    build note: {w}")

    # -------------------------------------------------------------- structure #
    click.secho("\n[structure]", bold=True)
    ends = rb.episode_ends[:]
    lengths = np.diff(np.concatenate([[0], ends]))
    click.echo(f"  episodes              : {rb.n_episodes}")
    click.echo(f"  total frames          : {rb.n_steps}")
    click.echo(f"  episode length        : min={lengths.min()} max={lengths.max()} "
               f"mean={lengths.mean():.1f} median={np.median(lengths):.1f}")
    rep.check(sorted(rb.keys()) == sorted(REQUIRED_KEYS),
              f"keys == required set (got {sorted(rb.keys())})")
    rep.check(bool(np.all(np.diff(ends) > 0)) and ends[-1] == rb.n_steps,
              "episode_ends is strictly increasing and matches n_steps")

    # -------------------------------------------------------------- per key #
    click.secho("\n[arrays]", bold=True)
    total_bad = 0
    for k in sorted(rb.keys()):
        arr = rb[k]
        if k == "camera0_rgb":
            sub = arr[:: max(1, rb.n_steps // 64)]
            click.echo(f"  {k:28s} {str(tuple(arr.shape)):>20s} {str(arr.dtype):>8s}  "
                       f"sampled min={sub.min()} max={sub.max()} mean={sub.mean():.1f}")
            rep.check(arr.dtype == np.uint8, "camera0_rgb dtype is uint8")
            rep.check(tuple(arr.shape[1:]) == (224, 224, 3),
                      f"camera0_rgb frame shape is (224,224,3) (got {tuple(arr.shape[1:])})")
            continue
        a = arr[:]
        click.echo(_stats_row(k, a))
        total_bad += int((~np.isfinite(a)).sum())
    rep.check(total_bad == 0, f"no NaN/Inf in any low-dim array (found {total_bad})")

    pos = rb["robot0_eef_pos"][:]
    rot = rb["robot0_eef_rot_axis_angle"][:]
    grip = rb["robot0_gripper_width"][:, 0]
    click.echo(f"\n  position XYZ range    : "
               f"x[{pos[:,0].min():+.4f},{pos[:,0].max():+.4f}] "
               f"y[{pos[:,1].min():+.4f},{pos[:,1].max():+.4f}] "
               f"z[{pos[:,2].min():+.4f},{pos[:,2].max():+.4f}]  (m)")
    span = float(np.abs(pos).max())
    if span > 5.0:
        rep.warn(f"|position| reaches {span:.2f} m -- check the unit "
                 f"(mm/cm would show up as a 100-1000x inflation)")
    if span < 1e-4:
        rep.warn("positions are essentially all zero")
    rn = np.linalg.norm(rot, axis=-1)
    click.echo(f"  rotation |rotvec|     : min={rn.min():.5f} max={rn.max():.5f} "
               f"mean={rn.mean():.5f} rad  (pi = {np.pi:.4f})")

    # -------------------------------------------------------------- gripper #
    click.secho("\n[gripper]", bold=True)
    uniq = np.unique(np.round(grip, 6))
    click.echo(f"  range                 : [{grip.min():.5f}, {grip.max():.5f}] m, "
               f"{len(uniq)} unique value(s)")
    if len(uniq) <= 8:
        click.echo(f"  values                : {uniq.tolist()}")
    gripper_status = (meta or {}).get("gripper", {}).get("status", "unknown")
    if float(grip.max() - grip.min()) > 1e-6:
        rep.check(True, "gripper_width varies (the gripper action dimension carries signal)")
    elif gripper_status == "calibrated":
        rep.check(False,
                  "gripper_width is constant even though gripper.status=calibrated -- "
                  "the gripper action dimension is dead")
    else:
        # Stage A: the CPU does not emit gripper_width_m yet and the collector
        # config declares it a placeholder. Constant is the intended state, so it
        # downgrades the dataset rather than failing it.
        rep.warn(f"gripper_width is constant ({grip[0]:.4f} m) and gripper.status="
                 f"{gripper_status!r}. The gripper action dimension carries no "
                 f"signal; this dataset is integration-only.")
    n_below = int((grip < UPSTREAM_GRIPPER_THRESHOLD).sum())
    click.echo(f"  < {UPSTREAM_GRIPPER_THRESHOLD} m (upstream sampler threshold): "
               f"{n_below}/{len(grip)} frames ({100*n_below/len(grip):.1f}%)")
    click.echo( "  note                  : that threshold only affects repeat-frame "
                "augmentation, which is off (repeat_frame_prob=0). Calibrate it for "
                "our gripper before ever enabling it.")

    # ---------------------------------------------------------------- split #
    click.secho("\n[train/val split]", bold=True)
    val_mask = get_val_mask(n_episodes=rb.n_episodes,
                            val_ratio=omx_config.VAL_RATIO, seed=omx_config.SEED)
    click.echo(f"  seed={omx_config.SEED} val_ratio={omx_config.VAL_RATIO} -> "
               f"{int(val_mask.sum())} val / {int((~val_mask).sum())} train episodes")
    click.echo(f"  val episode indices   : {np.flatnonzero(val_mask).tolist()}")
    if meta and meta.get("episodes"):
        ids = [e["episode_id"] for e in meta["episodes"]]
        click.echo(f"  val episode ids       : "
                   f"{[ids[i] for i in np.flatnonzero(val_mask)][:5]}")

    # --------------------------------------------------- usable-sample check #
    click.secho("\n[sampler feasibility]", bold=True)
    ds_steps = int(task_req.get("obs_down_sample_steps", 1))
    horizon = int(task_req.get("action_horizon", 16))
    need = (horizon - 1) * ds_steps + 1
    too_short = int((lengths < need).sum())
    click.echo(f"  action_horizon={horizon} obs_down_sample_steps={ds_steps} "
               f"-> an episode needs >= {need} frames")
    rep.check(too_short == 0,
              f"{too_short} episode(s) are shorter than {need} frames and would be "
              f"silently dropped by SequenceSampler(action_padding=False)")
    n_samples = int(np.sum(np.maximum(0, lengths - (horizon - 1) * ds_steps)))
    click.echo(f"  usable samples        : ~{n_samples}")

    # ----------------------------------------------------------- rgb export #
    if not no_plots:
        click.secho("\n[exports]", bold=True)
        idx = np.linspace(0, rb.n_steps - 1, min(n_rgb_samples, rb.n_steps)).astype(int)
        imgs = rb["camera0_rgb"][:][idx]
        cols = 4
        rows = int(np.ceil(len(idx) / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(3 * cols, 3 * rows))
        for ax, i, im in zip(np.ravel(axes), idx, imgs):
            ax.imshow(im); ax.set_title(f"frame {i}", fontsize=8); ax.axis("off")
        for ax in np.ravel(axes)[len(idx):]:
            ax.axis("off")
        fig.suptitle(f"{zp.name} -- stored RGB (what the encoder sees before augmentation)")
        fig.tight_layout(); fig.savefig(out / "rgb_samples.png", dpi=110); plt.close(fig)

        # Section 11: preprocessing + training augmentation can compound. Show it.
        ratio = 0.95
        side = int(round(224 * ratio))
        o = (224 - side) // 2
        fig, axes = plt.subplots(2, 3, figsize=(10, 7))
        for col, i in enumerate(idx[:3]):
            im = rb["camera0_rgb"][int(i)]
            axes[0, col].imshow(im); axes[0, col].set_title(f"stored  frame {i}", fontsize=9)
            crop = im[o:o + side, o:o + side]
            axes[1, col].imshow(crop)
            axes[1, col].set_title(f"after RandomCrop(ratio={ratio}) worst case\n"
                                   f"{side}x{side} of 224x224", fontsize=9)
            for r in (0, 1):
                axes[r, col].axis("off")
        fig.suptitle("Visible FOV after training-time augmentation "
                     "(config also applies ColorJitter)")
        fig.tight_layout(); fig.savefig(out / "rgb_augmentation_preview.png", dpi=110)
        plt.close(fig)

        # trajectories
        starts = np.concatenate([[0], ends[:-1]])
        fig = plt.figure(figsize=(14, 4.5))
        ax3 = fig.add_subplot(1, 3, 1, projection="3d")
        for s, e in zip(starts, ends):
            ax3.plot(pos[s:e, 0], pos[s:e, 1], pos[s:e, 2], lw=1.0)
        ax3.set_xlabel("x"); ax3.set_ylabel("y"); ax3.set_zlabel("z")
        ax3.set_title("EE position (episode-relative)")
        axp = fig.add_subplot(1, 3, 2)
        for a, lbl in zip(range(3), "xyz"):
            for s, e in zip(starts, ends):
                axp.plot(np.arange(e - s), pos[s:e, a], lw=0.8,
                         color=f"C{a}", alpha=0.7,
                         label=lbl if (s == 0) else None)
        axp.set_xlabel("frame"); axp.set_ylabel("m"); axp.legend(); axp.grid(alpha=.3)
        axp.set_title("per-axis position")
        axg = fig.add_subplot(1, 3, 3)
        for s, e in zip(starts, ends):
            axg.plot(np.arange(e - s), grip[s:e], lw=0.9, alpha=0.8)
        axg.axhline(UPSTREAM_GRIPPER_THRESHOLD, ls="--", c="k", lw=1,
                    label=f"upstream {UPSTREAM_GRIPPER_THRESHOLD} m")
        axg.set_xlabel("frame"); axg.set_ylabel("gripper width (m)")
        axg.legend(); axg.grid(alpha=.3); axg.set_title("gripper")
        fig.tight_layout(); fig.savefig(out / "trajectories.png", dpi=110); plt.close(fig)

        # per-frame jump detector -- catches scale/handedness/alignment errors
        d = np.linalg.norm(np.diff(pos, axis=0), axis=-1)
        d[ends[:-1] - 1] = np.nan               # ignore inter-episode boundaries
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.plot(d, lw=0.8); ax.set_ylabel("|dp| per frame (m)"); ax.set_xlabel("frame")
        ax.grid(alpha=.3); ax.set_title("frame-to-frame displacement (spikes = tracking jumps)")
        fig.tight_layout(); fig.savefig(out / "step_size.png", dpi=110); plt.close(fig)

        dfin = d[np.isfinite(d)]
        p99 = float(np.percentile(dfin, 99)) if dfin.size else 0.0
        click.echo(f"  frame-to-frame |dp|   : median={np.median(dfin):.5f} "
                   f"p99={p99:.5f} max={dfin.max():.5f} m")
        if dfin.size and dfin.max() > max(10 * p99, 0.05):
            rep.warn(f"a frame-to-frame jump of {dfin.max():.4f} m is far above p99 "
                     f"({p99:.4f}) -- likely an ARCore relocalisation")
        click.echo(f"  wrote                 : {out}/")

    # -------------------------------------------------------------- dataset #
    if not no_dataset:
        click.secho("\n[UmiDataset]", bold=True)
        import hydra
        from hydra import compose, initialize_config_dir
        from omegaconf import OmegaConf
        OmegaConf.register_new_resolver("eval", eval, replace=True)
        cdir = str((pathlib.Path(ROOT_DIR) / "diffusion_policy" / "config").resolve())
        ovr = [f"task.dataset_path={zp.resolve()}"]
        if task_req.get("obs_down_sample_steps") is not None:
            ovr.append(f"task.obs_down_sample_steps={task_req['obs_down_sample_steps']}")
        with initialize_config_dir(config_dir=cdir, version_base=None):
            cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace", overrides=ovr)
        OmegaConf.resolve(cfg)
        rep.check(int(cfg.task.obs_down_sample_steps) == ds_steps,
                  f"task obs_down_sample_steps ({cfg.task.obs_down_sample_steps}) matches "
                  f"what the converter recorded ({ds_steps})")

        dataset = hydra.utils.instantiate(cfg.task.dataset)
        val = dataset.get_validation_dataset()
        click.echo(f"  train samples         : {len(dataset)}")
        click.echo(f"  val samples           : {len(val)}")
        rep.check(len(dataset) > 0, "training set is non-empty")
        rep.check(len(val) > 0, "validation set is non-empty")

        s = dataset[0]
        for k, v in s["obs"].items():
            click.echo(f"    obs[{k:36s}] {tuple(v.shape)}")
        click.echo(f"    {'action':41s} {tuple(s['action'].shape)}")
        rep.check(tuple(s["action"].shape) == (horizon, 10),
                  f"action shape == ({horizon}, 10)")
        rep.check(tuple(s["obs"]["camera0_rgb"].shape) == (2, 3, 224, 224),
                  "camera0_rgb obs shape == (2, 3, 224, 224)")
        rep.check(tuple(s["obs"]["robot0_eef_rot_axis_angle"].shape) == (2, 6),
                  "robot0_eef_rot_axis_angle obs shape == (2, 6) (rotation_6d)")
        allf = all(bool(np.isfinite(v.numpy()).all()) for v in s["obs"].values()) \
            and bool(np.isfinite(s["action"].numpy()).all())
        rep.check(allf, "dataset[0] is entirely finite")

        rgb = s["obs"]["camera0_rgb"].numpy()
        rep.check(0.0 <= rgb.min() and rgb.max() <= 1.0,
                  f"camera0_rgb is scaled to [0,1] (got [{rgb.min():.3f}, {rgb.max():.3f}])")

        n = min(200, len(dataset))
        acts = np.stack([dataset[i]["action"].numpy()
                         for i in np.linspace(0, len(dataset) - 1, n).astype(int)])
        click.echo(f"\n  action stats over {n} samples "
                   f"(0:3 rel pos | 3:9 rot6d | 9 gripper)")
        click.echo(f"    pos     min={acts[...,:3].min():+.4f} max={acts[...,:3].max():+.4f} "
                   f"mean={acts[...,:3].mean():+.4f}")
        click.echo(f"    rot6d   min={acts[...,3:9].min():+.4f} max={acts[...,3:9].max():+.4f}")
        click.echo(f"    gripper min={acts[...,9].min():+.4f} max={acts[...,9].max():+.4f}")
        rep.check(bool(np.isfinite(acts).all()), "all sampled actions are finite")
        rep.check(bool(np.allclose(acts[:, 0, :3], 0, atol=1e-5)),
                  "action[0] position is ~0 (first target is the current EE pose; "
                  "relative-to-observation semantics)")

    # --------------------------------------------------------------- verdict #
    click.echo("\n" + "=" * 78)
    if rep.failures:
        click.secho(f"FAILED {len(rep.failures)} check(s):", fg="red", bold=True)
        for f in rep.failures:
            click.secho(f"  - {f}", fg="red")
        sys.exit(1)
    click.secho(f"ALL CHECKS PASSED ({len(rep.warnings)} warning(s))", fg="green", bold=True)
    for w in rep.warnings:
        click.secho(f"  - {w}", fg="yellow")


if __name__ == "__main__":
    main()
