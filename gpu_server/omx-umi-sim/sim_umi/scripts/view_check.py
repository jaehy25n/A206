"""Render the policy's view across many poses, to see whether it holds up.

One flattering frame proves nothing. This walks several episodes and samples
the same phases in each, so the framing can be judged where it is hardest --
reaching wide, turning the wrist, descending into the bin.

    python sim_umi/scripts/view_check.py -n 4
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import math
import pathlib

import click
import cv2
import numpy as np

from collector import Collector, sample_spec
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"
PHASES = [("approach", .05), ("align", .16), ("grasp", .28), ("lift", .38),
          ("carry", .58), ("lower", .74), ("release", .84), ("done", .97)]


def tag(im, lines):
    for i, t in enumerate(lines):
        for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
            cv2.putText(im, t, (7, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX,
                        .46, col, th)
    return im


@click.command()
@click.option("-n", "--n-episodes", default=4, type=int)
@click.option("--seed", default=31337, type=int)
@click.option("--width", default=400, type=int)
def main(n_episodes, seed, width):
    cfg = SceneConfig()
    h = int(width * 9 / 16)
    col = Collector(str(write_scene(cfg)), cfg=cfg, width=width, height=h)
    rng = np.random.default_rng(seed)
    out = SIM / "outputs"
    out.mkdir(exist_ok=True)

    click.echo(f"camera: pos {cfg.wrist_cam_pos}  pitch {cfg.wrist_cam_pitch_deg}"
               f"  fovy {cfg.wrist_cam_fovy}")
    rows, summary = [], []
    for i in range(n_episodes):
        spec = sample_spec(rng, seed + i, cfg)
        r = col.run(spec)
        n = len(r["rgb"])
        tiles = []
        vis = 0
        for nm, f in PHASES:
            im = r["rgb"][int(f * (n - 1))].copy()
            blue = ((im[:, :, 2].astype(int) - im[:, :, 0]) > 40).mean()
            hsv = cv2.cvtColor(im, cv2.COLOR_RGB2HSV)
            grip = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 150)).mean()
            vis += blue > 2e-4
            tiles.append(tag(im, [f"ep{i} {nm}",
                                  f"obj {blue*100:.2f}%  grip {grip*100:.1f}%"]))
        rows.append(np.concatenate(tiles[:4], 1))
        rows.append(np.concatenate(tiles[4:], 1))
        summary.append((i, spec.arrangement, r["success"], vis,
                        math.degrees(spec.object_yaw), math.degrees(spec.bin_yaw)))
        click.echo(f"  ep{i} {spec.arrangement:26s} success={r['success']} "
                   f"obj visible {vis}/8  yaw {math.degrees(spec.object_yaw):+.0f}/"
                   f"{math.degrees(spec.bin_yaw):+.0f}")
    col.close()

    grid = np.concatenate(rows, 0)
    p = out / "view_check.png"
    cv2.imwrite(str(p), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    ok = sum(s[2] for s in summary)
    click.echo(f"\n{ok}/{n_episodes} success   "
               f"obj visible {sum(s[3] for s in summary)}/{8*n_episodes} frames")
    click.echo(f"{grid.shape[1]}x{grid.shape[0]} -> {p}")


if __name__ == "__main__":
    main()
