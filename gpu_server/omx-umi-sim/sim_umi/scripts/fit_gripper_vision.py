"""Fit the jaw-width estimate the way the collector gets it: from the camera.

    python sim_umi/scripts/fit_gripper_vision.py --freeze

The policy was trained on a width ESTIMATED from the magenta patches in the
wrist frame, not on an encoder reading. So the runtime has to produce the same
kind of number, which means a calibration from pixel gap to metres, measured at
the geometry and resolution actually in use -- the patches moved to the
fingertip and the stream went to 320x180 since the last one, which is why the
old file is parked as gripper_calibration.STALE_patch_moved.json.

Fit and holdout are separate ARM poses, not just separate jaw angles: an
estimate that only works where it was fitted is not an estimate.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import json
import math
import pathlib

import click
import mujoco
import numpy as np

from collector import Collector
from gripper_vision import TipDetectorConfig, detect_tips, fit_scale
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


def samples(col, cfg, poses, jaws, det):
    """(pixel gap, true width) at every pose x jaw, plus how often it was seen."""
    m, d = col.model, col.data
    gaps, widths, misses = [], [], 0
    for (xy, z, pitch) in poses:
        q, err, _, _ = col.solve_ik_best(
            col.grasp_tcp_target(xy, z, math.radians(pitch), 0.065),
            math.radians(pitch))
        if err > 0.001:
            continue
        for a in jaws:
            mujoco.mj_resetData(m, d)
            for adr, v in zip(col.arm_qadr, q):
                d.qpos[adr] = v
            col._set_gripper(a)
            mujoco.mj_forward(m, d)
            for _ in range(400):
                mujoco.mj_step(m, d)
            col.renderer.update_scene(d, camera="wrist")
            raw = col.renderer.render().copy()
            det_out = detect_tips(raw, det)
            if det_out["pixel_gap"] is None:
                misses += 1
                continue
            gaps.append(det_out["pixel_gap"])
            widths.append(col._gripper_width())
    return np.array(gaps), np.array(widths), misses


@click.command()
@click.option("--freeze/--no-freeze", default=False)
def main(freeze):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    det = TipDetectorConfig()
    ox, oy = cfg.object_start_xy
    jaws = np.linspace(0.0, 1.0, 21)
    fit_poses = [((ox, oy), 0.025, 10), ((ox, oy), 0.10, 10), ((ox, oy), 0.16, 25),
                 ((ox - 0.08, oy + 0.04), 0.09, 15), ((ox + 0.06, oy - 0.03), 0.13, 5)]
    hold_poses = [((ox - 0.04, oy - 0.05), 0.07, 20), ((ox + 0.09, oy + 0.02), 0.15, 0),
                  ((ox, oy - 0.08), 0.12, 30)]

    g, w, miss = samples(col, cfg, fit_poses, jaws, det)
    click.echo(f"[fit]     {len(g)} samples over {len(fit_poses)} poses, "
               f"{miss} frames with no tips")
    if len(g) < 20:
        raise click.ClickException("not enough detections to fit")
    s = fit_scale(g, w)
    click.echo(f"\nwidth = {s['a']:.6f} * pixel_gap + {s['b']:+.6f}   (n={s['n']})")
    click.echo(f"  [fit]     RMSE {s['rmse_m']*1000:6.3f} mm   "
               f"max {s['max_abs_err_m']*1000:6.3f} mm")

    hg, hw, hmiss = samples(col, cfg, hold_poses, jaws, det)
    pred = s["a"] * hg + s["b"]
    err = pred - hw
    click.echo(f"  [holdout] RMSE {np.sqrt((err**2).mean())*1000:6.3f} mm   "
               f"max {np.abs(err).max()*1000:6.3f} mm   "
               f"(n={len(hg)} over {len(hold_poses)} unseen poses, {hmiss} missed)")
    click.echo(f"  true width spans {w.min()*1000:.1f} .. {w.max()*1000:.1f} mm")
    col.close()

    report = {"scale": s, "detector": det.__dict__,
              "resolution": list(cfg.wrist_cam_resolution),
              "fit_poses": [[list(p[0]), p[1], p[2]] for p in fit_poses],
              "holdout_poses": [[list(p[0]), p[1], p[2]] for p in hold_poses],
              "holdout_rmse_m": float(np.sqrt((err ** 2).mean())),
              "holdout_max_abs_err_m": float(np.abs(err).max()),
              "detection_rate_fit": len(g) / max(1, len(g) + miss),
              "detection_rate_holdout": len(hg) / max(1, len(hg) + hmiss)}
    out = SIM / "outputs" / "gripper_vision_fit.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    click.echo(f"\n-> {out}")
    if freeze:
        cal = SIM / "assets" / "gripper_calibration.json"
        cal.write_text(json.dumps(report, indent=2, default=str))
        click.secho(f"frozen -> {cal}", fg="green")


if __name__ == "__main__":
    main()
