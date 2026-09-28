"""Check the scripted policy across sampled poses BEFORE collecting a dataset.

Randomising and then collecting hundreds of episodes hides where the script
breaks. This draws from the same sampler the collector uses and reports the
failure distribution by pose, so the ranges can be adjusted from evidence.

    python sim_umi/scripts/sweep_poses.py -n 40
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import collections
import json
import math
import pathlib
import time

import click
import numpy as np

from collector import Collector, sample_spec
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


@click.command()
@click.option("-n", "--n-samples", default=40, type=int)
@click.option("--seed", default=7777, type=int)
@click.option("--out", default=None)
def main(n_samples, seed, out):
    cfg = SceneConfig()
    xml = write_scene(cfg)
    col = Collector(str(xml), cfg=cfg)
    rng = np.random.default_rng(seed)

    rows, t0 = [], time.time()
    for i in range(n_samples):
        spec = sample_spec(rng, seed + i, cfg)
        r = col.run(spec)
        rows.append({**spec.to_meta(), "arrangement": spec.arrangement,
                     "success": r["success"], "lifted": r["lifted"],
                     "in_bin": r["in_bin"], "settled": r["settled"],
                     "no_wall_penetration": r["no_wall_penetration"],
                     "bin_touch_frames": r["bin_touch_frames"],
                     "bin_penetration_mm": r["bin_penetration_mm"],
                     "bin_min_clearance_mm": r["bin_min_clearance_mm"],
                     "max_object_z": round(r["max_object_z"], 5),
                     "bin_local_xy": r["bin_local_xy"],
                     "final_z": round(float(r["final_object_pos"][2]), 5),
                     "n_frames": int(len(r["timestamps"]))})
        if not r["success"]:
            click.secho(f"  [{i:3d}] FAIL lift={r['lifted']} in_bin={r['in_bin']} "
                        f"settled={r['settled']} "
                        f"clean={r['no_wall_penetration']}"
                        f"({r['bin_min_clearance_mm']:+.1f}mm)  obj=({spec.object_xy[0]:+.3f},"
                        f"{spec.object_xy[1]:+.3f}) bin=({spec.bin_xy[0]:+.3f},"
                        f"{spec.bin_xy[1]:+.3f}) yaw={math.degrees(spec.object_yaw):+.0f}"
                        f"/{math.degrees(spec.bin_yaw):+.0f}", fg="yellow")
    col.close()

    n_ok = sum(r["success"] for r in rows)
    click.echo(f"\nsuccess {n_ok}/{n_samples} = {100*n_ok/n_samples:.0f}%  "
               f"({time.time()-t0:.0f}s)")
    for stage in ("lifted", "in_bin", "settled", "no_wall_penetration"):
        k = sum(r[stage] for r in rows)
        click.echo(f"  {stage:9s} {k}/{n_samples}")

    clr = [r["bin_min_clearance_mm"] for r in rows]
    click.echo(f"  bin clearance   min {min(clr):+.2f} mm  median "
               f"{float(np.median(clr)):+.2f} mm   "
               f"(negative = through a wall; magnitude caps at 1.5 mm)")

    click.echo("\nby arrangement:")
    by = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["arrangement"]][0] += r["success"]; by[r["arrangement"]][1] += 1
    for k in sorted(by):
        ok, tot = by[k]
        click.echo(f"  {k:26s} {ok}/{tot}")

    if any(not r["success"] for r in rows):
        f = [r for r in rows if not r["success"]]
        click.echo("\nfailure pose range:")
        for key in ("object_x", "object_y", "bin_x", "bin_y",
                    "object_yaw_deg", "bin_yaw_deg"):
            v = [r[key] for r in f]
            click.echo(f"  {key:16s} [{min(v):+.3f}, {max(v):+.3f}]")

    click.echo("\nsampled pose range (all):")
    for key in ("object_x", "object_y", "bin_x", "bin_y",
                "object_yaw_deg", "bin_yaw_deg"):
        v = [r[key] for r in rows]
        click.echo(f"  {key:16s} [{min(v):+.3f}, {max(v):+.3f}]")

    p = pathlib.Path(out or (SIM / "outputs" / "pose_sweep.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"n": n_samples, "seed": seed, "n_success": n_ok,
                             "scene": cfg.to_dict(), "rows": rows}, indent=2))
    click.echo(f"\n-> {p}")


if __name__ == "__main__":
    main()
