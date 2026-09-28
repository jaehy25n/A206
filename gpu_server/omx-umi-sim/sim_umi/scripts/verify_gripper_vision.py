"""Score the camera-based jaw estimate against MuJoCo's true width.

    python sim_umi/scripts/verify_gripper_vision.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import json
import pathlib

import click
import cv2
import numpy as np

from collector import Collector, EpisodeSpec, sample_spec
from gripper_vision import (TipDetectorConfig, detect_tips, fit_scale,
                            mask_magenta)
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


@click.command()
@click.option("-n", "--n-episodes", default=6, type=int)
@click.option("--seed", default=4242, type=int)
@click.option("--holdout-seed", default=999001, type=int,
              help="Separate seed stream the calibration is NOT fitted on.")
@click.option("--freeze/--no-freeze", default=False,
              help="Write the fitted scale to assets/gripper_calibration.json.")
def main(n_episodes, seed, holdout_seed, freeze):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    det = TipDetectorConfig()
    rng = np.random.default_rng(seed)

    def collect(base_seed, n, keep_frames=False):
        g, t, fr, miss = [], [], [], 0
        rr = np.random.default_rng(base_seed)
        for i in range(n):
            r = col.run(sample_spec(rr, base_seed + i, cfg))
            # Fit on the RAW frames: `rgb` has already had the magenta painted
            # out, so the detector finds nothing there. And score against
            # `gripper_width_gt`: once a calibration is frozen the collector
            # fills `gripper_width` with this same estimate, and fitting a line
            # to its own output is a fit to nothing.
            for k in range(0, len(r["rgb_raw"]), 3):
                d = detect_tips(r["rgb_raw"][k], det)
                if d["pixel_gap"] is None:
                    miss += 1
                    continue
                g.append(d["pixel_gap"])
                t.append(float(r["gripper_width_gt"][k]))
                if keep_frames and len(fr) < 4 and k > len(r["rgb_raw"]) // 3:
                    fr.append(r["rgb_raw"][k])
        return g, t, fr, miss

    gaps, trues, frames, n_missing = collect(seed, n_episodes, keep_frames=True)
    total = len(gaps) + n_missing
    click.echo(f"[fit]     both tips found {len(gaps)}/{total} "
               f"({100*len(gaps)/max(1,total):.0f}%)")
    if len(gaps) < 10:
        raise click.ClickException("not enough detections to fit a scale")

    s = fit_scale(gaps, trues)
    click.echo(f"\nwidth = {s['a']:.6f} * pixel_gap + {s['b']:+.6f}   (n={s['n']})")
    click.echo(f"  [fit]     RMSE {s['rmse_m']*1000:6.3f} mm   "
               f"max {s['max_abs_err_m']*1000:6.3f} mm")

    # The fit numbers are optimistic by construction -- same frames. Score the
    # frozen line on a seed stream it never saw.
    hg, ht, _, hmiss = collect(holdout_seed, max(3, n_episodes // 2))
    htot = len(hg) + hmiss
    pred = s["a"] * np.asarray(hg) + s["b"]
    err = pred - np.asarray(ht)
    click.echo(f"  [holdout] RMSE {np.sqrt((err**2).mean())*1000:6.3f} mm   "
               f"max {np.abs(err).max()*1000:6.3f} mm   "
               f"(n={len(hg)}, detect {100*len(hg)/max(1,htot):.0f}%)")
    click.echo(f"  true width {min(trues)*1000:.1f} .. {max(trues)*1000:.1f} mm")

    # Linear against quadratic, both scored on the holdout. A pivot jaw swings
    # its tips on an arc, so the pixel gap need not be linear in the width --
    # worth checking rather than assuming, and worth rejecting if the second
    # term does not pay for itself out of sample.
    q = np.polyfit(gaps, trues, 2)
    qerr = np.polyval(q, np.asarray(hg)) - np.asarray(ht)
    click.echo(f"  [holdout, quadratic] RMSE {np.sqrt((qerr**2).mean())*1000:6.3f} mm"
               f"   max {np.abs(qerr).max()*1000:6.3f} mm")
    col.close()

    out = SIM / "outputs"
    out.mkdir(exist_ok=True)
    if frames:
        tiles = []
        for f in frames:
            masked = mask_magenta(f, det)
            tiles.append(np.concatenate([f, masked], axis=0))
        cv2.imwrite(str(out / "magenta_mask.png"),
                    cv2.cvtColor(np.concatenate(tiles, axis=1), cv2.COLOR_RGB2BGR))
        resid = np.abs(np.asarray([mask_magenta(f, det) for f in frames], float)
                       - np.asarray(frames, float)).max()
        click.echo(f"\nmask changes at most {resid:.0f} levels per channel "
                   f"(0 would mean nothing was painted)")
        left = sum(detect_tips(mask_magenta(f, det), det)["n_blobs"] for f in frames)
        click.echo(f"magenta blobs surviving the mask: {left}  (want 0)")
        click.echo(f"-> {out/'magenta_mask.png'}  (top raw / bottom masked)")

    report = {"scale": s, "detector": det.__dict__,
              "quadratic_holdout_rmse_m": float(np.sqrt((qerr ** 2).mean())),
              "fit_seed": seed, "holdout_seed": holdout_seed,
              "detection_rate_fit": len(gaps) / max(1, total),
              "detection_rate_holdout": len(hg) / max(1, htot),
              "holdout_rmse_m": float(np.sqrt((err ** 2).mean())),
              "holdout_max_abs_err_m": float(np.abs(err).max())}
    (out / "gripper_vision_fit.json").write_text(
        json.dumps(report, indent=2, default=str))
    if freeze:
        cal = SIM / "assets" / "gripper_calibration.json"
        cal.write_text(json.dumps(report, indent=2, default=str))
        click.secho(f"\nfrozen -> {cal}", fg="green")


if __name__ == "__main__":
    main()
