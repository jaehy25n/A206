"""Validate the GPU-local mirror of the CPU processed_v1 dataset.

Run this after ``scripts/sync_processed_from_cpu.sh`` and before building a zarr.
It checks the transfer and the frame-level alignment, and then states plainly
whether the dataset is good enough to train on or only to integrate against.

    python scripts/inspect_synced_processed.py --root ~/omx_data/processed/v1
    python scripts/inspect_synced_processed.py            # uses OMX_PROCESSED_ROOT

Exit code is non-zero when a hard check fails, so it can gate a pipeline.
A placeholder calibration or a missing gripper column is NOT a hard failure --
it downgrades the reported training status instead.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import csv
import json
import pathlib
from typing import Dict, List, Optional, Tuple

import click
import numpy as np

from omx import config as omx_config
from omx.collector_config import load_collector_config
from omx.data.contract import ContractError
from omx.data.processed_v1 import FRAMES_CSV, RGB_DIRNAME, ProcessedV1Reader
from omx.data.build import (min_source_frames, min_stored_frames,
                            stored_frames_for)
from omx.data.handoff_contract import (collect_session_contracts,
                                       validate_contracts)
from omx.data.validity import (check_pose_provenance,
                               compute_effective_pose_validity)

READY = "READY"
GPU_SYNCED = "GPU_SYNCED"


class EpisodeCheck:
    def __init__(self, session: str, episode: str, path: pathlib.Path):
        self.session, self.episode, self.path = session, episode, path
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.n_rows = 0
        self.n_images = 0
        self.duration_s = 0.0
        self.fps: Optional[float] = None
        self.has_gripper = False
        self.has_quality = False
        self.n_invalid = 0          # frames failing effective validity
        self.n_interpolated = 0     # frames the CPU repaired
        self.has_provenance = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def label(self) -> str:
        return f"{self.session[:8]}../{self.episode[:8]}.."


def check_episode(session: str, ep_dir: pathlib.Path,
                  field_map: Dict[str, object], cfg, strict: bool = True,
                  min_stored: int = 0) -> EpisodeCheck:
    """Strict final gate on one episode.

    Reads through ``ProcessedV1Reader`` and judges with
    ``compute_effective_pose_validity`` -- the exact code the converter uses --
    so this cannot pass an episode the build would then reject.

    The GPU side never repairs CPU output: a blank pose cell, a surviving
    pose_valid=false row, a non-tracking row that was NOT interpolated, or a
    segment too short to train on all mean the CPU processed_v1 contract was
    broken. Nothing here ever substitutes a numeric default.
    """
    c = EpisodeCheck(session, ep_dir.name, ep_dir)
    reader = ProcessedV1Reader(ep_dir, f"{session}__{ep_dir.name}", field_map=field_map)

    try:
        low = reader.read_lowdim()
    except ContractError as e:
        c.errors.append(str(e).replace("\n", " ").strip())
        return c
    c.n_rows = low.n_frames

    # --- blank / unparseable cells ----------------------------------------- #
    # This is the failure mode that used to crash the inspector with float('').
    # It must fail loudly, never be filled in with 0.
    unparseable = low.extra.get("_unparseable") or {}
    if unparseable:
        c.errors.append(
            "blank/unparseable cells -- CPU processed contract violation: "
            + "; ".join(f"{k} ({v})" for k, v in unparseable.items()))

    # --- rgb <-> csv alignment --------------------------------------------- #
    rgb_dir = ep_dir / RGB_DIRNAME
    if rgb_dir.is_dir():
        c.n_images = sum(1 for p in rgb_dir.iterdir()
                         if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    else:
        c.errors.append(f"missing {RGB_DIRNAME}/")
    if c.n_images and c.n_images != c.n_rows:
        c.errors.append(f"{c.n_images} images but {c.n_rows} csv rows")
    try:
        reader.frame_paths()          # resolves every rgb_path, or raises
    except ContractError as e:
        c.errors.append(str(e).split("] ", 1)[-1])

    # --- frame_idx continuity ---------------------------------------------- #
    fidx = low.extra.get("frame_idx")
    if fidx is None:
        c.warnings.append("no frame_idx column")
    else:
        idx = np.asarray(fidx)
        if idx.size and idx[0] != 0:
            c.warnings.append(f"frame_idx starts at {idx[0]}, not 0")
        d = np.diff(idx)
        if d.size and not np.all(d == 1):
            c.errors.append(f"frame_idx is not contiguous ({int((d != 1).sum())} gaps)")

    # --- timestamps --------------------------------------------------------- #
    ts = low.timestamp
    if ts.size > 1:
        dt = np.diff(ts)
        if np.any(dt <= 0):
            c.errors.append(f"timestamp is not strictly increasing "
                            f"({int((dt <= 0).sum())} non-positive steps)")
        else:
            c.fps = float(1.0 / np.median(dt))
            c.duration_s = float(ts[-1] - ts[0])
            if np.max(dt) / np.min(dt) > 3.0:
                c.warnings.append(
                    f"frame interval jitter max/min = {np.max(dt)/np.min(dt):.1f}")

    # --- effective validity (the shared contract) --------------------------- #
    result = compute_effective_pose_validity(
        position=low.position, rotation=low.rotation,
        rotation_format=low.rotation_format,
        pose_valid=low.extra.get("pose_valid"),
        tracking_state=low.extra.get("tracking_state"),
        pose_interpolated=low.extra.get("pose_interpolated"),
        usable_tracking_states=cfg.validity.good_tracking_states,
        use_pose_valid=cfg.validity.use_pose_valid,
        use_tracking_state=cfg.validity.use_tracking_state)
    c.n_invalid = result.n_invalid
    c.n_interpolated = int(result.interpolated.sum())

    numeric_keys = ("non_finite_position", "non_finite_rotation", "quaternion_norm")
    for key in numeric_keys:
        if result.counts.get(key) and not unparseable:
            c.errors.append(f"{key}: {result.counts[key]} row(s) "
                            f"({result.detail.get(key, '')})")

    # These three are what CPU preprocessing is supposed to have removed, so in
    # strict mode they are contract violations rather than observations.
    for key, text in (
        ("pose_valid_false",
         "rows have pose_valid=false. CPU preprocessing should have trimmed, "
         "interpolated or split these out before writing READY"),
        ("tracking_bad_not_interpolated",
         "rows have a non-tracking tracking_state and are NOT marked "
         "pose_interpolated. An interpolated row keeps its original "
         "tracking_state and is accepted; these were never repaired"),
    ):
        n = result.counts.get(key, 0)
        if n:
            msg = f"{n}/{c.n_rows} {text} ({result.detail.get(key, '')})"
            (c.errors if strict else c.warnings).append(msg)
    if result.counts.get("pose_valid_unparseable"):
        c.errors.append(f"pose_valid has {result.counts['pose_valid_unparseable']} "
                        f"unparseable value(s) "
                        f"({result.detail.get('pose_valid_unparseable', '')})")

    stored = stored_frames_for(c.n_rows, cfg.timing.converter_stride)
    if min_stored and stored < min_stored:
        msg = (f"only {c.n_rows} source frames -> {stored} at "
               f"{cfg.timing.policy_hz:g} Hz (< {min_stored} needed); too short to "
               f"yield a single training sample, CPU should have rejected this "
               f"segment")
        (c.errors if strict else c.warnings).append(msg)

    # --- provenance bookkeeping (GPU-3) ------------------------------------- #
    c.has_provenance = ("pose_interpolated" in low.extra
                        or "pose_valid_original" in low.extra)
    for problem in check_pose_provenance(
            pose_valid=low.extra.get("pose_valid"),
            pose_valid_original=low.extra.get("pose_valid_original"),
            pose_interpolated=low.extra.get("pose_interpolated"),
            tracking_state=low.extra.get("tracking_state"),
            usable_tracking_states=cfg.validity.good_tracking_states):
        (c.errors if strict else c.warnings).append(f"provenance: {problem}")
    # --- gripper / quality --------------------------------------------------- #
    grip = np.asarray(low.gripper, dtype=np.float64)
    c.has_gripper = bool(grip.size and np.all(np.isfinite(grip)))
    if c.has_gripper and float(grip.max() - grip.min()) < 1e-9:
        c.warnings.append(f"gripper column is constant ({grip[0]:.4f})")
    c.has_quality = (ep_dir / "quality.json").is_file()
    return c


@click.command()
@click.option("--root", default=None, help=f"Default: {omx_config.PROCESSED_ROOT}")
@click.option("-c", "--collector-config", default=omx_config.DEFAULT_COLLECTOR_CONFIG)
@click.option("--min-frames", type=int, default=None,
              help="Override the minimum episode length, in STORED (post-"
                   "decimation) frames. Default: the value the converter "
                   "requires, derived from action_horizon.")
@click.option("--strict/--no-strict", default=True,
              help="Strict (default) is the real contract: surviving "
                   "pose_valid=false rows, non-tracking states and too-short "
                   "episodes are failures, because CPU preprocessing owns "
                   "trimming/interpolation/splitting/rejection. --no-strict "
                   "downgrades those three to warnings for triage only.")
@click.option("-v", "--verbose", is_flag=True, help="One line per episode.")
def main(root, collector_config, min_frames, strict, verbose):
    root = pathlib.Path(os.path.expanduser(root or omx_config.PROCESSED_ROOT))
    click.echo("=" * 78)
    click.echo(f"synced processed_v1 mirror: {root}")
    click.echo("=" * 78)
    if not root.is_dir():
        raise click.ClickException(
            f"{root} does not exist.\n"
            f"  Pull it first: ./scripts/sync_processed_from_cpu.sh\n"
            f"  Or point --root / OMX_PROCESSED_ROOT somewhere else.")

    cfg = load_collector_config(collector_config)
    # exactly what the converter requires, expressed in stored (post-decimation)
    # frames, so the two tools cannot disagree about "too short"
    min_stored = min_stored_frames(16, cfg.timing.task_down_sample_steps)
    if min_frames is not None:
        min_stored = int(min_frames)
    min_source_equiv = min_source_frames(min_stored, cfg.timing.converter_stride)

    sessions = sorted(p for p in root.iterdir()
                      if p.is_dir() and not p.name.startswith("."))
    if not sessions:
        raise click.ClickException(f"no session directories under {root}")

    staging = root / ".incoming"
    if staging.is_dir():
        partials = sorted(p.name for p in staging.iterdir() if p.is_dir())
        if partials:
            click.secho(f"  note: {len(partials)} transfer(s) still in .incoming/ "
                        f"(never read by the converter): {partials[:3]}", fg="yellow")

    superseded = root / ".superseded"
    if superseded.is_dir():
        old_copies = sorted(p.name for p in superseded.iterdir() if p.is_dir())
        if old_copies:
            click.secho(f"  note: {len(old_copies)} replaced session copy/copies in "
                        f".superseded/ (never read by the converter). Remove them "
                        f"once the new data checks out: rm -rf {superseded}",
                        fg="yellow")

    hard_fail = False
    n_ready = n_not_ready = 0
    all_checks: List[EpisodeCheck] = []
    contract_problems: List[str] = []
    contract_notes: List[str] = []
    contracts_ok = 0

    click.secho("\n[sessions]", bold=True)
    for s in sessions:
        ready = (s / READY).is_file()
        synced = (s / GPU_SYNCED).is_file()
        eps = sorted(p for p in s.iterdir() if p.is_dir() and not p.name.startswith("."))
        if not ready:
            n_not_ready += 1
            click.secho(f"  {s.name}  NO READY marker -- the converter will skip "
                        f"this session ({len(eps)} episode dir(s))", fg="yellow")
            continue
        n_ready += 1

        found, read_errs = collect_session_contracts(s, eps)
        probs, cnotes, contract = validate_contracts(
            found, cfg.timing.source_fps, cfg.timing.policy_hz, 16, min_source_equiv)
        probs = read_errs + probs
        if probs:
            contract_problems.extend(f"[{s.name}] {x}" for x in probs)
        else:
            contracts_ok += 1
            if contract and contract.describe() not in contract_notes:
                contract_notes.append(contract.describe())
            for n in cnotes[1:]:
                if n not in contract_notes:
                    contract_notes.append(n)

        checks = [check_episode(s.name, e, cfg.field_map, cfg,
                                strict=strict, min_stored=min_stored) for e in eps]
        all_checks.extend(checks)
        bad = sum(1 for c in checks if not c.ok)
        frames = sum(c.n_rows for c in checks)
        colour = "red" if bad else "green"
        click.secho(f"  {s.name}  READY{' SYNCED' if synced else ''}  "
                    f"{len(checks)} episodes, {frames} frames"
                    f"{f', {bad} FAILING' if bad else ''}", fg=colour)
        if bad:
            hard_fail = True

    if not all_checks:
        raise click.ClickException("no READY session contained any episode")

    click.secho("\n[handoff contract]", bold=True)
    click.echo(f"  GPU requires          : source {cfg.timing.source_fps:g} Hz -> "
               f"policy {cfg.timing.policy_hz:g} Hz, action_horizon 16, "
               f">= {min_source_equiv} source frames per segment")
    if contract_problems:
        for x in contract_problems:
            for i, line in enumerate(str(x).splitlines()):
                click.secho(("  FAIL " if i == 0 else "       ") + line, fg="red")
    else:
        for n in contract_notes:
            click.secho(f"  ok   {n}", fg="green")
        click.echo(f"  sessions validated    : {contracts_ok}/{n_ready}")

    click.secho("\n[episodes]", bold=True)
    fps = [c.fps for c in all_checks if c.fps]
    lens = np.array([c.n_rows for c in all_checks])
    click.echo(f"  count                 : {len(all_checks)}")
    click.echo(f"  total frames          : {int(lens.sum())}")
    click.echo(f"  length (source rate)  : min={lens.min()} max={lens.max()} "
               f"mean={lens.mean():.1f}")
    if fps:
        click.echo(f"  measured fps          : min={min(fps):.2f} max={max(fps):.2f} "
                   f"median={np.median(fps):.2f}  (config says {cfg.timing.source_fps})")
        if abs(np.median(fps) - cfg.timing.source_fps) > 1.0:
            click.secho(f"  ! measured fps disagrees with collector config "
                        f"timing.source_fps={cfg.timing.source_fps}; "
                        f"the 30->10 Hz decimation would be wrong", fg="yellow")
    click.echo(f"  min usable length     : {min_stored} stored frames "
               f"(~{min_source_equiv} source frames; action_horizon 16 at "
               f"{cfg.timing.policy_hz:g} Hz)")
    n_interp = sum(c.n_interpolated for c in all_checks)
    n_with_prov = sum(1 for c in all_checks if c.has_provenance)
    total_rows = int(lens.sum())
    if n_with_prov:
        click.echo(f"  CPU-interpolated      : {n_interp}/{total_rows} frames "
                   f"({100*n_interp/max(total_rows,1):.1f}%) across {n_with_prov} "
                   f"episode(s) carrying provenance columns")
    else:
        click.secho("  ! no pose_interpolated / pose_valid_original column: this "
                    "export predates the CPU repair contract, so a repaired row "
                    "cannot be told from a broken one", fg="yellow")
    if not strict:
        click.secho("  ! --no-strict: pose_valid=false, non-tracking states and "
                    "short episodes are downgraded to warnings", fg="yellow")

    if verbose:
        for c in all_checks:
            mark = click.style("ok  ", fg="green") if c.ok else click.style("FAIL", fg="red")
            click.echo(f"    {mark} {c.label()}  rows={c.n_rows:5d} imgs={c.n_images:5d} "
                       f"{c.duration_s:6.1f}s {c.fps or 0:5.1f}fps "
                       f"invalid={c.n_invalid:4d} interp={c.n_interpolated:4d} "
                       f"gripper={'y' if c.has_gripper else 'n'}")
            for e in c.errors:
                click.secho(f"         error: {e}", fg="red")
            for w in c.warnings:
                click.secho(f"         warn : {w}", fg="yellow")
    else:
        for c in all_checks:
            for e in c.errors:
                click.secho(f"  FAIL {c.label()}: {e}", fg="red")
        shown = set()
        for c in all_checks:
            for w in c.warnings:
                if w not in shown:
                    click.secho(f"  warn {c.label()}: {w}", fg="yellow")
                    shown.add(w)

    # ------------------------------------------------------------ status --- #
    n_gripper = sum(1 for c in all_checks if c.has_gripper)
    n_quality = sum(1 for c in all_checks if c.has_quality)
    align_ok = all(c.ok for c in all_checks)

    transfer = "OK" if (n_ready and not n_not_ready) else (
        "OK (some sessions not READY)" if n_ready else "FAIL")
    align = "OK" if align_ok else "FAIL"
    if contract_problems:
        contract_status = "FAIL"
    elif contracts_ok == n_ready and n_ready:
        contract_status = "OK"
    else:
        contract_status = "PARTIAL"
    contract_blocks = bool(contract_problems) and cfg.validity.contract_policy == "error"
    if cfg.camera_to_ee.status == "calibrated" and not cfg.camera_to_ee.is_identity():
        c2e = f"OK ({cfg.camera_to_ee.calibration_version})"
    else:
        c2e = "PLACEHOLDER"
    if n_gripper == 0:
        grip = "MISSING"
    elif n_gripper < len(all_checks):
        grip = f"PARTIAL ({n_gripper}/{len(all_checks)} episodes)"
    elif cfg.gripper.status != "calibrated":
        grip = "PRESENT (calibration not marked final)"
    else:
        grip = f"OK ({cfg.gripper.representation}, {cfg.gripper.unit})"

    training_ready = (align_ok and contract_status == "OK"
                      and c2e.startswith("OK") and grip.startswith("OK"))
    blocked = (not align_ok) or contract_blocks
    status = "READY" if training_ready else ("BLOCKED" if blocked else "INTEGRATION ONLY")

    click.echo("\n" + "=" * 78)
    click.secho("DATASET STATUS", bold=True)
    click.echo("-" * 14)
    click.echo(f"Transfer         : {transfer}")
    click.echo(f"RGB/Pose Align   : {align}")
    click.echo(f"Handoff Contract : {contract_status}")
    click.echo(f"T_camera_EE      : {c2e}")
    click.echo(f"Gripper Width    : {grip}")
    click.secho(f"Training Status  : {status}",
                fg="green" if status == "READY" else
                   ("yellow" if status == "INTEGRATION ONLY" else "red"), bold=True)
    click.echo("=" * 78)

    if status == "BLOCKED":
        # GPU-11: a block is a CPU action item, not a GPU one. Print it in a form
        # that can be pasted straight into the CPU ticket.
        click.echo("\n" + "=" * 78)
        click.secho("CPU ACTION ITEMS", fg="red", bold=True)
        click.echo("=" * 78)
        click.echo(f"root   : {root}")
        click.echo(f"config : {collector_config}  "
                   f"(source_fps={cfg.timing.source_fps:g}, "
                   f"policy_hz={cfg.timing.policy_hz:g}, "
                   f"min {min_stored} stored / {min_source_equiv} source frames)")
        for c in all_checks:
            if c.ok:
                continue
            click.echo(f"\nsession = {c.session}")
            click.echo(f"episode = {c.episode}")
            click.echo(f"  rows={c.n_rows} images={c.n_images} "
                       f"duration={c.duration_s:.1f}s fps={c.fps or 0:.2f} "
                       f"interpolated={c.n_interpolated}")
            for e in c.errors:
                for i, line in enumerate(str(e).split("; ")):
                    click.echo(("  - " if i == 0 else "    ") + line)
        click.echo("\n" + "=" * 78)

        click.secho("\nThe CPU processed_v1 contract is violated. The GPU side is the "
                    "final gate, not a repair step:", fg="red")
        click.echo("  - blank pose cells are never filled in with 0")
        click.echo("  - invalid frames are never silently dropped")
        click.echo("  Fix CPU preprocessing (trim / interpolate short gaps / split "
                   "long gaps / reject unusable segments, then write READY) and "
                   "re-sync.")
        click.echo("  `--no-strict` only changes this report; the converter still "
                   "refuses the build.")
        click.echo("\n  Accepted by design, so these are NOT failures:")
        click.echo("    - tracking_state=PAUSED/MISSING when pose_interpolated=true")
        click.echo("    - T_camera_EE / gripper placeholders (Stage A)")

    if status == "INTEGRATION ONLY":
        click.echo("\nStill needed for a reportable baseline:")
        if not c2e.startswith("OK"):
            click.echo("  - real T_camera_EE -> configs/collector/default.yaml "
                       "(camera_to_ee.status: calibrated + calibration_version)")
        if not grip.startswith("OK"):
            click.echo("  - marker-derived gripper width in metres in frames.csv, "
                       "then gripper.status: calibrated")
        if contract_status != "OK":
            click.echo("  - handoff_contract in session and segment metadata")
        click.echo("  Neither needs re-collection: re-run the converter and the "
                   "dataset is rebuilt from the same raw ARCore poses.")
    if hard_fail or status == "BLOCKED":
        sys.exit(1)

    click.echo("\nnext: python -m omx.cli build omx_pick_raw_center_v1")


if __name__ == "__main__":
    main()
