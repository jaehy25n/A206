"""Convert the EC2 processed_v1 dataset into a UMI-compatible zarr ReplayBuffer.

This is the adapter the GPU server owns (handoff doc section 4).  The upstream
``scripts_slam_pipeline/07_generate_replay_buffer.py`` is deliberately NOT used:
it assumes ``dataset_plan.pkl``, GoPro fisheye intrinsics and SLAM-derived TCP
poses, none of which exist in this project.

Usage
-----
    # by registered experiment (recommended -- output path and rgb mode come
    # from omx/config.py, so variants can never drift apart)
    python scripts/convert_processed_to_umi_zarr.py -e omx_pick_raw_center_v1

    # or fully explicit
    python scripts/convert_processed_to_umi_zarr.py \
        -i /srv/processed/v1 \
        -o data/omx/zarr/omx_pick_raw_center_v1.zarr.zip \
        --rgb-mode center_crop

    # scan without writing anything
    python scripts/convert_processed_to_umi_zarr.py -e omx_pick_raw_center_v1 --dry-run

Only the RGB pipeline differs between variants; pose, gripper, episode order and
episode boundaries are byte-identical, which is what makes the section 25 A/B
comparison fair.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import concurrent.futures
import datetime
import json
import pathlib
import subprocess
import threading
from typing import Dict, List, Optional, Tuple

import click
import cv2
import numpy as np
import zarr
from tqdm import tqdm

from diffusion_policy.codecs.imagecodecs_numcodecs import JpegXl, register_codecs
from diffusion_policy.common.replay_buffer import ReplayBuffer
from omx import config as omx_config
from omx.collector_config import GRIPPER_MODES, load_collector_config
from omx.data.contract import ContractError
from omx.data.build import min_source_frames
from omx.data.handoff_contract import (collect_session_contracts,
                                       validate_contracts)
from omx.data.build import Segment, build_segments, min_stored_frames
from omx.data.processed_v1 import ProcessedV1Reader, discover_processed_v1
from omx.data import rgb_preprocess
from omx.data.rgb_preprocess import RGB_MODES, build_preprocessor

register_codecs()

#: Must match diffusion_policy/config/task/umi*.yaml -- the shortest usable
#: episode is derived from it.
ACTION_HORIZON = 16
SCHEMA_VERSION = "omx-umi-zarr/1"


def _git_info() -> Dict[str, object]:
    def run(*args):
        try:
            return subprocess.check_output(args, cwd=ROOT_DIR,
                                           stderr=subprocess.DEVNULL).decode().strip()
        except (subprocess.CalledProcessError, OSError):
            return ""
    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run("git", "status", "--porcelain")),
    }


def _fmt_stats(name: str, arr: np.ndarray) -> str:
    a = np.asarray(arr, dtype=np.float64)
    return (f"    {name:28s} {str(arr.shape):>18s} {str(arr.dtype):>8s}  "
            f"min={a.min():+.5f} max={a.max():+.5f} mean={a.mean():+.5f}")


@click.command()
@click.option("-e", "--experiment", default=None,
              help="Registered experiment name from omx/config.py. Supplies "
                   "--output, --rgb-mode, --out-res, --collector-config and inputs.")
@click.option("-i", "--input", "inputs", multiple=True,
              help="processed_v1 root(s), or a single episode directory. "
                   f"Default: {omx_config.PROCESSED_ROOT}")
@click.option("-o", "--output", default=None, help="Output .zarr.zip path.")
@click.option("-m", "--rgb-mode", type=click.Choice(RGB_MODES), default=None)
@click.option("--out-res", default=None, help="WIDTH,HEIGHT. Default 224,224.")
@click.option("-c", "--collector-config", default=None,
              help=f"Default: {omx_config.DEFAULT_COLLECTOR_CONFIG}")
@click.option("--episode-pattern", default=None,
              help="Regex filter on '<session>__<episode>'.")
@click.option("--max-episodes", type=int, default=None)
@click.option("--gripper-mode", type=click.Choice(GRIPPER_MODES), default=None,
              help="Override collector config. Use 'constant' for a Stage A build "
                   "where marker-derived widths do not exist yet.")
@click.option("--source-fps", type=float, default=None)
@click.option("--policy-hz", type=float, default=None)
@click.option("--invalid-policy",
              type=click.Choice(["error", "trim", "split", "keep"]), default=None)
@click.option("-n", "--num-workers", type=int, default=None)
@click.option("-cl", "--compression-level", type=int, default=99)
@click.option("--verify-trajectory/--no-verify-trajectory", default=True,
              help="Cross-check frames.csv poses against trajectory.npz.")
@click.option("--require-ready/--no-require-ready", default=True,
              help="Only use sessions carrying a READY marker (CPU->GPU contract). "
                   "--no-require-ready is for hand-assembled test trees only.")
@click.option("--source-aspect", type=float, default=None,
              help="Source aspect this build must see (e.g. 1.7778 for 16:9). "
                   "Default: the experiment's declared value. Pass 0 to disable.")
@click.option("--allow-aspect-mismatch", is_flag=True,
              help="Build even when the frames' aspect differs from the "
                   "experiment's. Stamped into the zarr metadata so a run made "
                   "this way is never mistaken for the real arm.")
@click.option("--dry-run", is_flag=True, help="Scan and report; write nothing.")
@click.option("--overwrite", is_flag=True)
def main(experiment, inputs, output, rgb_mode, out_res, collector_config,
         episode_pattern, max_episodes, gripper_mode, source_fps, policy_hz,
         invalid_policy, num_workers, compression_level, verify_trajectory,
         require_ready, source_aspect, allow_aspect_mismatch,
         dry_run, overwrite):
    variant = None
    if experiment is not None:
        exp = omx_config.get(experiment)
        variant = exp.dataset
        inputs = inputs or variant.roots
        output = output or str(variant.zarr_path)
        rgb_mode = rgb_mode or variant.rgb_mode
        out_res = out_res or f"{variant.out_res[0]},{variant.out_res[1]}"
        collector_config = collector_config or variant.collector_config
        episode_pattern = episode_pattern or variant.episode_pattern
        max_episodes = max_episodes if max_episodes is not None else variant.max_episodes
        compression_level = variant.jpegxl_level if compression_level == 99 else compression_level

    inputs = tuple(inputs) or (omx_config.PROCESSED_ROOT,)
    rgb_mode = rgb_mode or "center_crop"
    out_res_t = tuple(int(x) for x in (out_res or "224,224").split(","))
    collector_config = collector_config or omx_config.DEFAULT_COLLECTOR_CONFIG
    if output is None and not dry_run:
        raise click.UsageError("--output (or --experiment) is required")
    if num_workers is None:
        num_workers = min(16, (os.cpu_count() or 8))
    cv2.setNumThreads(1)

    # ---------------------------------------------------------------- config #
    overrides: Dict[str, object] = {}
    if gripper_mode:
        overrides.setdefault("gripper", {})["mode"] = gripper_mode          # type: ignore[index]
    if source_fps:
        overrides.setdefault("timing", {})["source_fps"] = source_fps       # type: ignore[index]
    if policy_hz:
        overrides.setdefault("timing", {})["policy_hz"] = policy_hz         # type: ignore[index]
    if invalid_policy:
        overrides.setdefault("validity", {})["invalid_policy"] = invalid_policy  # type: ignore[index]

    cfg = load_collector_config(collector_config, overrides)
    cfg_warnings = cfg.validate()

    task_ds = cfg.timing.task_down_sample_steps
    min_frames = cfg.validity.min_segment_frames or min_stored_frames(ACTION_HORIZON, task_ds)

    click.echo("=" * 78)
    click.echo("OMX processed_v1 -> UMI zarr")
    click.echo("=" * 78)
    click.echo(cfg.summary())
    click.echo(f"  rgb mode            : {rgb_mode}  -> {out_res_t[0]}x{out_res_t[1]}")
    click.echo(f"  inputs              : {list(inputs)}")
    click.echo(f"  output              : {output}")
    click.echo(f"  min stored frames   : {min_frames} "
               f"(action_horizon {ACTION_HORIZON} x obs_down_sample_steps {task_ds})")
    for w in cfg_warnings:
        click.secho(f"  ! {w}", fg="yellow")
    click.echo()

    if output and pathlib.Path(output).exists() and not overwrite and not dry_run:
        click.confirm(f"{output} exists. Overwrite?", abort=True)

    # ------------------------------------------------------------- discovery #
    notes_pre: List[str] = []
    not_ready: List[str] = []
    readers = discover_processed_v1(inputs, field_map=cfg.field_map,
                                    pattern=episode_pattern,
                                    require_ready=require_ready,
                                    skipped=not_ready)
    if not_ready:
        click.secho(f"  ! skipped {len(not_ready)} episode(s) whose session has no "
                    f"READY marker (CPU preprocessing may still be running): "
                    f"{not_ready[:3]}{' ...' if len(not_ready) > 3 else ''}", fg="yellow")
    if max_episodes:
        readers = readers[:max_episodes]
    if not readers:
        hint = ("\n  Every candidate was skipped for having no READY marker. The CPU "
                "side writes READY last, after validation." if not_ready else
                "\n  An episode directory is one that contains frames.csv.")
        raise click.ClickException(
            f"no usable processed_v1 episodes under {list(inputs)}.{hint}")
    click.echo(f"found {len(readers)} episode(s)")

    # ------------------------------------------------ handoff contract ----- #
    # Validated per session, with exactly the rules the inspector applies.
    required_min_source = min_source_frames(min_frames, cfg.timing.converter_stride)
    sessions: Dict[str, List[ProcessedV1Reader]] = {}
    for r in readers:
        sessions.setdefault(str(r.session_dir or r.path.parent), []).append(r)

    contract_problems: List[str] = []
    contract_seen = {}
    click.echo(f"\nhandoff contract (GPU requires >= {required_min_source} source "
               f"frames, {cfg.timing.source_fps:g} -> {cfg.timing.policy_hz:g} Hz, "
               f"action_horizon {ACTION_HORIZON})")
    for sdir, rs in sorted(sessions.items()):
        sname = pathlib.Path(sdir).name
        found, read_errs = collect_session_contracts(
            pathlib.Path(sdir), [r.path for r in rs])
        probs, cnotes, contract = validate_contracts(
            found, cfg.timing.source_fps, cfg.timing.policy_hz,
            ACTION_HORIZON, required_min_source)
        probs = read_errs + probs
        if probs:
            contract_problems.extend(f"[{sname}] {x}" for x in probs)
            click.secho(f"  FAIL {sname[:8]}..  " + probs[0].splitlines()[0], fg="red")
        else:
            contract_seen[sname] = contract
            click.secho(f"  ok   {sname[:8]}..  {contract.describe()}", fg="green")
            for n in cnotes[1:]:
                click.echo(f"         {n}")

    if contract_problems:
        if cfg.validity.contract_policy == "error":
            click.echo()
            click.secho("=" * 78, fg="red")
            click.secho("HANDOFF CONTRACT VIOLATION", fg="red", bold=True)
            click.secho("=" * 78, fg="red")
            for x in contract_problems:
                click.secho(f"  - {x}", fg="red")
            raise click.ClickException(
                "the CPU handoff contract does not match this GPU config. Nothing "
                "was written. Fix whichever side is wrong -- a Hz or horizon "
                "mismatch silently corrupts every downstream timing.")
        for x in contract_problems:
            notes_pre.append(f"handoff contract: {x}")

    # --------------------------------------------------------------- pass 1 #
    # lowdim only: cheap, and it establishes episode boundaries + buffer offsets
    out_rb = ReplayBuffer.create_empty_zarr(storage=zarr.MemoryStore())
    all_segments: List[Tuple[ProcessedV1Reader, Segment]] = []
    notes: List[str] = list(cfg_warnings) + notes_pre
    ep_meta: List[Dict[str, object]] = []
    buffer_start = 0
    in_res: Optional[Tuple[int, int]] = None
    n_synthetic = 0

    violations: List[str] = []

    for reader in tqdm(readers, desc="lowdim"):
        try:
            low = reader.read_lowdim()
        except ContractError as e:
            violations.append(str(e))
            continue
        ep_json = reader.read_metadata()
        # Trust the data, not the path: a synthetic fixture copied into the real
        # mirror would still be flagged.
        is_synth = bool(ep_json.get("metadata", {}).get("synthetic", False))
        n_synthetic += int(is_synth)
        n_rgb = len(reader.frame_paths())
        try:
            segs, seg_notes = build_segments(
                low, cfg, reader.episode_id, str(reader.path), min_frames,
                n_rgb_frames=n_rgb)
        except ContractError as e:
            # Collect every violation before failing: a CPU-side fix round trip
            # is expensive, so report the whole dataset at once.
            violations.append(str(e))
            continue
        notes.extend(seg_notes)

        verify: Dict[str, object] = {"checked": False}
        if verify_trajectory:
            verify = reader.verify_against_trajectory_npz(
                T_camera_ee=cfg.camera_to_ee.matrix(),
                pose_frame=cfg.pose.pose_frame)
            if verify.get("checked") and not verify.get("ok", True):
                notes.append(f"[{reader.episode_id}] frames.csv vs trajectory.npz "
                             f"MISMATCH: {verify.get('failed')}")
            for note in verify.get("notes", []):
                notes.append(f"[{reader.episode_id}] {note}")

        if in_res is None and segs:
            h, w = reader.probe_rgb_shape()
            in_res = (w, h)

        for seg in segs:
            out_rb.add_episode(data=seg.episode_data(), compressors=None)
            ep_meta.append({
                "episode_id": seg.episode_id,
                "source_path": seg.source_path,
                "buffer_start": buffer_start,
                "buffer_end": buffer_start + seg.n_frames,
                "timestamp_start": float(seg.timestamp[0]),
                "timestamp_end": float(seg.timestamp[-1]),
                "trajectory_npz_check": verify,
                "synthetic": is_synth,
                **seg.info,
            })
            all_segments.append((reader, seg))
            buffer_start += seg.n_frames

    if violations:
        click.echo()
        click.secho("=" * 78, fg="red")
        click.secho(f"CPU processed_v1 CONTRACT VIOLATION in {len(violations)} of "
                    f"{len(readers)} episode(s)", fg="red", bold=True)
        click.secho("=" * 78, fg="red")
        for v in violations:
            click.secho("\n" + v, fg="red")
        click.echo()
        raise click.ClickException(
            f"{len(violations)} episode(s) violate the processed_v1 contract. "
            f"Nothing was written. Each message above says what to change: the CPU "
            f"output (re-preprocess and re-sync -- the GPU does not repair tracking "
            f"data), or configs/collector where the value is a known Stage A "
            f"placeholder.")

    if not all_segments:
        for n in notes:
            click.secho(f"  ! {n}", fg="yellow")
        raise click.ClickException("no usable episodes survived filtering")

    total_frames = buffer_start
    lengths = np.array([s.n_frames for _, s in all_segments])
    click.echo(f"\n{len(all_segments)} episode(s), {total_frames} frames "
               f"@ {cfg.timing.stored_fps:g} Hz "
               f"({total_frames / cfg.timing.stored_fps:.1f} s total)")
    click.echo(f"  episode length  min={lengths.min()} max={lengths.max()} "
               f"mean={lengths.mean():.1f}")
    n_samples = int(np.sum(np.maximum(0, lengths - (ACTION_HORIZON - 1) * task_ds)))
    click.echo(f"  usable training samples (action_padding=False): ~{n_samples}")

    for key in ("robot0_eef_pos", "robot0_eef_rot_axis_angle", "robot0_gripper_width"):
        click.echo(_fmt_stats(key, out_rb[key][:]))

    grip = out_rb["robot0_gripper_width"][:, 0]
    if float(grip.max() - grip.min()) < 1e-6:
        click.secho(f"  ! gripper_width is constant ({grip[0]:.4f} m): the gripper "
                    f"action dimension carries no signal in this dataset.", fg="yellow")
    n_below = int((grip < 0.08).sum())
    click.echo(f"    gripper < 0.08 m (upstream sampler threshold): "
               f"{n_below}/{len(grip)} frames -- inert while repeat_frame_prob=0")

    # Settle the aspect question before the dry-run exit: a check a dry run
    # cannot reach is not a check.
    if source_aspect == 0:
        source_aspect = None
    elif source_aspect is None:
        source_aspect = getattr(variant, "source_aspect", None)
    allow_aspect_mismatch = allow_aspect_mismatch or getattr(
        variant, "allow_aspect_mismatch", False)
    if source_aspect is not None and in_res is not None:
        actual = in_res[0] / in_res[1]
        if abs(actual - source_aspect) > rgb_preprocess.ASPECT_TOL:
            msg = (f"source frames are {in_res[0]}x{in_res[1]} (aspect "
                   f"{actual:.4f}) but this experiment declares "
                   f"{source_aspect:.4f}. rgb_mode={rgb_mode!r} would still run "
                   f"and would still produce a zarr -- it would just be a "
                   f"different experiment than the one the notes describe.")
            if not allow_aspect_mismatch:
                raise click.ClickException(
                    msg + "\n  --allow-aspect-mismatch  build anyway (stamped into "
                          "the zarr metadata)\n  --source-aspect 0        drop the "
                          "requirement for this build")
            notes.append(f"source_aspect_mismatch: {msg}")

    for n in notes:
        click.secho(f"  ! {n}", fg="yellow")

    if dry_run:
        click.echo("\n--dry-run: nothing written")
        return

    # --------------------------------------------------------------- pass 2 #
    pre_warnings: List[str] = []
    pre = build_preprocessor(
        rgb_mode, in_res=in_res, out_res=out_res_t,
        warnings=pre_warnings,
        collector_intrinsics=cfg.camera.collector_intrinsics,
        robot_intrinsics=cfg.camera.robot_intrinsics,
        matched_fov_deg=cfg.camera.matched_fov_deg,
        matched_fov_axis=cfg.camera.matched_fov_axis)
    click.echo(f"\nrgb: {in_res[0]}x{in_res[1]} --{rgb_mode}--> "
               f"{out_res_t[0]}x{out_res_t[1]}  {pre.describe()}")
    for w in pre_warnings:
        click.secho(f"  ! {w}", fg="yellow")
        notes.append(f"rgb preprocess: {w}")

    img_compressor = JpegXl(level=compression_level, numthreads=1)
    img_array = out_rb.data.require_dataset(
        name="camera0_rgb",
        shape=(total_frames, out_res_t[1], out_res_t[0], 3),
        chunks=(1, out_res_t[1], out_res_t[0], 3),
        compressor=img_compressor,
        dtype=np.uint8)

    lock = threading.Lock()
    def write_segment(reader: ProcessedV1Reader, seg: Segment, start: int) -> int:
        n = 0
        for offset, frame in enumerate(reader.read_rgb_indices(seg.source_indices)):
            img_array[start + offset] = pre(frame)
            n += 1
        if n != seg.n_frames:
            raise RuntimeError(
                f"[{seg.episode_id}] wrote {n} frames, expected {seg.n_frames}")
        return n

    starts = [m["buffer_start"] for m in ep_meta]
    with tqdm(total=total_frames, desc="rgb", unit="frame") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as ex:
            futures = {ex.submit(write_segment, r, s, st): s
                       for (r, s), st in zip(all_segments, starts)}
            for fut in concurrent.futures.as_completed(futures):
                pbar.update(fut.result())

    # ------------------------------------------------------------- metadata #
    metadata = {
        "schema": SCHEMA_VERSION,
        "created_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "git": _git_info(),
        "converter": {
            "script": "scripts/convert_processed_to_umi_zarr.py",
            "argv": sys.argv[1:],
            "action_horizon_assumed": ACTION_HORIZON,
            "min_stored_frames": min_frames,
        },
        "dataset": {
            "name": (variant.name if variant else pathlib.Path(output).stem.split(".")[0]),
            "experiment": experiment,
            "inputs": [str(i) for i in inputs],
            "episode_pattern": episode_pattern,
            "require_ready": require_ready,
            "episodes_skipped_not_ready": len(not_ready),
            "n_episodes": len(all_segments),
            "n_frames": int(total_frames),
            "stored_fps": cfg.timing.stored_fps,
            "episode_length_min": int(lengths.min()),
            "episode_length_max": int(lengths.max()),
            "episode_length_mean": float(lengths.mean()),
            "approx_training_samples": n_samples,
            "synthetic": n_synthetic > 0,
            "n_synthetic_episodes": n_synthetic,
        },
        "rgb_preprocess": pre.describe(),
        "collector_config": cfg.to_dict(),
        "collector_config_path": collector_config,
        "gripper": {
            "zarr_key": "robot0_gripper_width",
            "representation": cfg.gripper.representation,
            "unit": cfg.gripper.unit,
            "status": cfg.gripper.status,
            "source": cfg.gripper.source,
            "closed_width_m": cfg.gripper.closed_width_m,
            "open_width_m": cfg.gripper.open_width_m,
            "observed_min_m": float(grip.min()),
            "observed_max_m": float(grip.max()),
            "frames_below_upstream_threshold_0p08": n_below,
        },
        "handoff_contract": {
            k: (v.to_dict() if v else None) for k, v in contract_seen.items()},
        "handoff_contract_required_min_source_frames": required_min_source,
        "camera_to_ee_calibration_version": cfg.camera_to_ee.calibration_version,
        "camera_to_ee_status": cfg.camera_to_ee.status,
        # What the hydra task config MUST be set to for this zarr.  Reading these
        # back is how omx/cli.py guarantees the policy really runs at policy_hz.
        "umi_task_requirements": {
            "obs_down_sample_steps": task_ds,
            "action_horizon": ACTION_HORIZON,
            "dataset_frequeny": 0,
            "note": "latency_steps are zero because the CPU layer already "
                    "timestamp-aligned every stream",
        },
        "episodes": ep_meta,
        "warnings": notes,
    }

    try:
        out_rb.root["meta"].attrs["omx"] = metadata
    except Exception as e:                                  # pragma: no cover
        notes.append(f"could not attach metadata to zarr attrs: {e}")

    if n_synthetic:
        click.secho(f"  ! {n_synthetic}/{len(all_segments)} episode(s) are SYNTHETIC "
                    f"(metadata.json says synthetic: true). This dataset is a "
                    f"pipeline fixture, not a result.", fg="yellow", bold=True)

    out_path = pathlib.Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    click.echo(f"\nsaving -> {out_path}")
    with zarr.ZipStore(str(out_path), mode="w") as zip_store:
        out_rb.save_to_store(store=zip_store)

    meta_path = out_path.with_suffix("").with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    size_mb = out_path.stat().st_size / 1e6
    click.secho(f"done: {out_path} ({size_mb:.1f} MB)", fg="green")
    click.echo(f"      {meta_path}")
    click.echo(f"\nnext: python scripts/inspect_umi_zarr.py {out_path}")


if __name__ == "__main__":
    main()
