"""Collect randomised scripted demonstrations.

    python sim_umi/scripts/collect_episodes.py -n 60 --split train
    python sim_umi/scripts/collect_episodes.py -n 20 --split heldout

Train and held-out draw from the SAME distribution but from disjoint seed
streams, so a held-out pose is one the policy has not seen rather than one
outside the range it was taught.

Yaw is capped at +-40 deg on purpose. The block is a cube, so yaw t and
t +- 90 deg render identically; teaching both would hand the policy two
different gripper angles for the same picture.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import json
import math
import pathlib
import time

import click
import numpy as np

from collector import Collector, EpisodeSpec, sample_spec
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"
SEED_BASE = {"train": 0, "heldout": 1_000_000, "val": 2_000_000}


@click.command()
@click.option("-n", "--n-episodes", default=60, type=int)
@click.option("--split", type=click.Choice(["train", "heldout", "val"]), default="train")
@click.option("--out-dir", default=None)
@click.option("--yaw-deg", default="-40,40")
@click.option("--bin-yaw-deg", default="-40,40")
@click.option("--min-separation", default=0.20, type=float)
@click.option("--edge-clearance", default=0.06, type=float)
@click.option("--object-type", default="box")
@click.option("--keep-failures", is_flag=True,
              help="Save unsuccessful episodes too (default: drop them).")
def main(n_episodes, split, out_dir, yaw_deg, bin_yaw_deg,
         min_separation, edge_clearance, object_type, keep_failures):
    rng_of = lambda s: tuple(float(v) for v in s.split(","))
    out = pathlib.Path(out_dir or (SIM / "data" / split))
    out.mkdir(parents=True, exist_ok=True)

    cfg = SceneConfig(object_type=object_type)
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    rng = np.random.default_rng(SEED_BASE[split])

    kept, failed, metas = 0, 0, []
    t0 = time.time()
    for i in range(n_episodes):
        spec = sample_spec(rng, SEED_BASE[split] + i, cfg,
                           yaw_range_deg=rng_of(yaw_deg),
                           bin_yaw_range_deg=rng_of(bin_yaw_deg),
                           min_separation=min_separation,
                           edge_clearance=edge_clearance,
                           object_type=object_type)
        r = col.run(spec)
        meta = {"index": i, "split": split, **spec.to_meta(),
                "n_frames": int(len(r["timestamps"])),
                "arrangement": spec.arrangement,
                "success": r["success"], "lifted": r["lifted"],
                "in_bin": r["in_bin"], "settled": r["settled"],
                "no_wall_penetration": r["no_wall_penetration"],
                "bin_touch_frames": r["bin_touch_frames"],
                "bin_penetration_mm": r["bin_penetration_mm"],
                "bin_min_clearance_mm": r["bin_min_clearance_mm"],
                "max_object_z": round(r["max_object_z"], 5),
                "gripper_width_rmse_mm": round(float(
                    np.sqrt((r["gripper_width_error"] ** 2).mean()) * 1000), 4),
                "gripper_width_max_err_mm": round(float(
                    np.abs(r["gripper_width_error"]).max() * 1000), 4),
                "final_object_pos": [round(float(v), 5) for v in r["final_object_pos"]]}
        metas.append(meta)
        if not r["success"]:
            failed += 1
            click.secho(f"  [{i:3d}] FAIL lifted={r['lifted']} in_bin={r['in_bin']} "
                        f"settled={r['settled']} clean={r['no_wall_penetration']} "
                        f"z={r['final_object_pos'][2]:.4f}",
                        fg="yellow")
            if not keep_failures:
                continue
        np.savez_compressed(
            out / f"episode_{kept:04d}.npz",
            timestamps=r["timestamps"], rgb=r["rgb"], tcp_pos=r["tcp_pos"],
            tcp_quat_wxyz=r["tcp_quat_wxyz"],
            gripper_width=r["gripper_width"],           # vision estimate
            gripper_width_gt=r["gripper_width_gt"],     # MuJoCo truth
            gripper_width_error=r["gripper_width_error"],
            object_pos=r["object_pos"])
        meta["file"] = f"episode_{kept:04d}.npz"
        kept += 1
        if (i + 1) % 10 == 0:
            click.echo(f"  {i+1}/{n_episodes}  kept={kept} failed={failed} "
                       f"({time.time()-t0:.0f}s)")

    # Which calibration produced `gripper_width` is part of the dataset, not
    # a detail of the run: the column is a vision estimate, and a reader who
    # cannot tell which line was used cannot tell what the number means.
    cal_path = SIM / "assets" / "gripper_calibration.json"
    cal = json.loads(cal_path.read_text()) if cal_path.is_file() else None
    (out / "episodes.json").write_text(json.dumps(
        {"split": split, "n_requested": n_episodes, "n_kept": kept,
         "n_failed": failed, "seed_base": SEED_BASE[split],
         "gripper_calibration": ({"status": "frozen",
                                  "file": cal_path.name,
                                  "scale": cal["scale"],
                                  "fit_seed": cal["fit_seed"],
                                  "holdout_seed": cal["holdout_seed"],
                                  "holdout_rmse_m": cal["holdout_rmse_m"]}
                                 if cal else {"status": "none -- "
                                              "gripper_width is ground truth"}),
         "episodes": metas}, indent=2))
    col.close()
    click.echo(f"\n{split}: kept {kept}/{n_episodes}  failed {failed}  "
               f"({time.time()-t0:.0f}s)")
    click.echo(f"-> {out}")


if __name__ == "__main__":
    main()
