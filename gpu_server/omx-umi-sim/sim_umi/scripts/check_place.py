"""Look at the place, close up: does the gripper go over the rim or through it?

    python sim_umi/scripts/check_place.py --seed 31337

The sweep reports a clearance number per episode; this renders the frames that
number comes from, from a camera parked on the bin, so the number can be
checked against the picture. Writes outputs/check_place.png.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import pathlib

import click
import cv2
import numpy as np

from collector import Collector, sample_spec
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


@click.command()
@click.option("--seed", default=31337, type=int)
@click.option("--episode", default=0, type=int)
@click.option("--n-frames", default=8, type=int)
def main(seed, episode, n_frames):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    rng = np.random.default_rng(seed)
    for _ in range(episode + 1):
        spec = sample_spec(rng, seed, cfg)
    bx, by = spec.bin_xy
    col.enable_overview(width=480, height=360, azimuth=115.0, elevation=-18.0,
                        distance=0.62, lookat=(bx, by, 0.10))
    r = col.run(spec)
    col.close()

    z = r["tcp_pos"][:, 2]
    near = np.hypot(r["tcp_pos"][:, 0] - bx, r["tcp_pos"][:, 1] - by) < 0.05
    if not near.any():
        raise SystemExit("the gripper never came near the bin")
    i0, i1 = int(np.argmax(near)), len(z) - 1 - int(np.argmax(near[::-1]))
    idxs = np.linspace(i0 - 8, min(i1 + 8, len(z) - 1), n_frames).astype(int)

    panels = []
    for k in idxs:
        f = r["overview"][k].copy()
        c = r["bin_clearance"][k] * 1000
        for txt, y, col_ in ((f"t {r['timestamps'][k]:5.2f}s   tcp z {z[k]*1000:5.1f} mm", 20,
                              (255, 255, 255)),
                             (f"wall clearance {c:+6.2f} mm", 40,
                              (255, 90, 90) if c < 0 else (120, 255, 120))):
            cv2.putText(f, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3,
                        cv2.LINE_AA)
            cv2.putText(f, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col_, 1,
                        cv2.LINE_AA)
        panels.append(f)
    cols = 4
    rows = [np.concatenate(panels[k:k + cols], axis=1)
            for k in range(0, len(panels), cols)]
    sheet = np.concatenate(rows, axis=0)
    out = SIM / "outputs" / "check_place.png"
    cv2.imwrite(str(out), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    click.echo(f"bin ({bx:+.3f}, {by:+.3f})  success={r['success']}  "
               f"touch={r['bin_touch_frames']}  pen={r['bin_penetration_mm']} mm  "
               f"min clearance={r['bin_min_clearance_mm']} mm")
    click.echo(f"-> {out}")


if __name__ == "__main__":
    main()
