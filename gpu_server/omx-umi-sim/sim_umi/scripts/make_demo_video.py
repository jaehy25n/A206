"""Render episodes to video: third-person beside what the policy actually sees.

    python sim_umi/scripts/make_demo_video.py -n 4

The left pane is a debug camera. The right pane is camera0_rgb -- the masked
wrist frame the encoder is trained on, upscaled for viewing only.
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


def label(img, lines, org=(10, 22)):
    for i, t in enumerate(lines):
        cv2.putText(img, t, (org[0], org[1] + 20 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, t, (org[0], org[1] + 20 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, (255, 255, 255), 1, cv2.LINE_AA)


@click.command()
@click.option("-n", "--n-episodes", default=4, type=int)
@click.option("--seed", default=31337, type=int)
@click.option("--out", default=None)
@click.option("--fps", default=30, type=int)
def main(n_episodes, seed, out, fps):
    """Writes three files, kept separate on purpose:

        demo.mp4                 overview beside the policy input
        collector_raw_rgb.mp4    straight off the wrist camera -- the magenta
                                 tips MUST be visible here
        collector_policy_rgb.mp4 after mask_magenta() -- no magenta may survive,
                                 because the real OMX has no patches and the
                                 encoder must not learn to look for them
    """
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    col.enable_overview()
    rng = np.random.default_rng(seed)

    H = 480
    frames, raws, policies = [], [], []
    for i in range(n_episodes):
        spec = sample_spec(rng, seed + i, cfg)
        r = col.run(spec)
        ov, wr, rawf = r["overview"], r["rgb"], r["rgb_raw"]
        raws.extend(rawf)
        policies.extend(wr)
        for k in range(len(wr)):
            left = ov[k].copy()
            right = cv2.resize(wr[k], (H * wr.shape[2] // wr.shape[1], H),
                               interpolation=cv2.INTER_NEAREST)
            label(left, [f"episode {i}   {spec.arrangement}",
                         f"object ({spec.object_xy[0]:+.3f}, {spec.object_xy[1]:+.3f})"
                         f"  yaw {math.degrees(spec.object_yaw):+.0f}",
                         f"bin    ({spec.bin_xy[0]:+.3f}, {spec.bin_xy[1]:+.3f})"
                         f"  yaw {math.degrees(spec.bin_yaw):+.0f}",
                         f"success {r['success']}   "
                         f"wall clear {r['bin_clearance'][k]*1000:+5.1f} mm"
                         f"{'  *** THROUGH THE WALL ***' if r['bin_clearance'][k] < 0 else ''}"])
            label(right, ["camera0_rgb (policy input, magenta masked)",
                          f"jaw {r['gripper_width_gt'][k]*1000:5.1f} mm"], (10, 22))
            frames.append(np.concatenate([left, right], axis=1))
        click.echo(f"  episode {i}: {len(wr)} frames  success={r['success']}  "
                   f"{spec.arrangement}")
    col.close()

    outdir = pathlib.Path(out).parent if out else (SIM / "outputs")
    outdir.mkdir(parents=True, exist_ok=True)

    def write(name, seq, scale=1):
        q = outdir / name
        h, w = seq[0].shape[:2]
        if scale != 1:
            h, w = h * scale, w * scale
        vw = cv2.VideoWriter(str(q), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for f in seq:
            if scale != 1:
                f = cv2.resize(f, (w, h), interpolation=cv2.INTER_NEAREST)
            vw.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        vw.release()
        click.echo(f"  {name:26s} {len(seq):4d} frames  "
                   f"{q.stat().st_size/1e6:5.1f} MB")
        return q

    click.echo("")
    write(pathlib.Path(out).name if out else "demo.mp4", frames)
    write("collector_raw_rgb.mp4", raws, scale=2)
    write("collector_policy_rgb.mp4", policies, scale=2)

    # The masked video is only useful if it is actually clean.
    from gripper_vision import TipDetectorConfig, detect_tips
    det = TipDetectorConfig()
    left = sum(detect_tips(f, det)["n_blobs"] for f in policies[::7])
    seen = sum(detect_tips(f, det)["n_blobs"] > 0 for f in raws[::7])
    click.echo(f"\n  raw     : magenta detected in {seen}/{len(raws[::7])} "
               f"sampled frames   (want all of them)")
    click.secho(f"  policy  : {left} magenta blobs survive the mask   (want 0)",
                fg="green" if left == 0 else "red")


if __name__ == "__main__":
    main()
