"""Render the wrist view under a grid of camera settings, labelled, to choose from.

Iterating one setting at a time was guesswork; this puts the options side by
side with their parameters written on them.

    python sim_umi/scripts/camera_variations.py

The pose is fixed and staged so the answer is visible: the gripper stands off
from the block with the bin beyond it, which is the moment the policy has to be
able to see. Each tile reports whether the block and the bin are actually in
frame, so the choice is not purely by eye.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import itertools
import pathlib

import click
import cv2
import mujoco
import numpy as np

from collector import Collector, EpisodeSpec, yaw_quat
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


def staged(cfg, cam_y, cam_z, pitch, w=680, h=382, standoff=0.20,
           grip=0.0):
    c = Collector(str(write_scene(cfg)), cfg=cfg, width=w, height=h)
    m, d = c.model, c.data
    sp = EpisodeSpec(object_xy=(-0.02, -0.16), bin_xy=(0.10, -0.30))
    mujoco.mj_resetData(m, d)
    ox, oy = sp.object_xy
    d.qpos[c.obj_qadr:c.obj_qadr + 3] = [ox, oy, sp.grasp_z]
    bx, by = sp.bin_xy
    d.qpos[c.bin_qadr:c.bin_qadr + 3] = [bx, by, 0.0]
    # gripper standing off, block ahead, bin beyond
    start = c.mocap_for_grasp([ox, oy - standoff, sp.carry_z], 0.0)
    d.qpos[c.col_qadr:c.col_qadr + 3] = start
    d.qpos[c.col_qadr + 3:c.col_qadr + 7] = yaw_quat(0.0)
    mujoco.mj_forward(m, d)
    d.mocap_pos[c.mocap_id] = start
    d.mocap_quat[c.mocap_id] = yaw_quat(0.0)
    c._set_gripper(grip)
    for _ in range(150):
        mujoco.mj_step(m, d)
    c.renderer.update_scene(d, camera="wrist")
    im = c.renderer.render().copy()
    c.close()
    return im


def seen(im):
    blue = ((im[:, :, 2].astype(int) - im[:, :, 0]) > 40).mean()
    hsv = cv2.cvtColor(im, cv2.COLOR_RGB2HSV)
    hh = im.shape[0]
    white = ((hsv[:, :, 1] < 45) & (hsv[:, :, 2] > 135)).astype(np.uint8)
    white[int(hh * 0.62):] = 0                      # ignore the gripper itself
    n, _, st, _ = cv2.connectedComponentsWithStats(white, 8)
    binpx = max((st[i, cv2.CC_STAT_AREA] for i in range(1, n)), default=0)
    grip = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 150)).mean()
    return blue, binpx / im[:, :, 0].size, grip


@click.command()
@click.option("--pitch", default="28,34,40,46")
@click.option("--cam-z", default="0.06,0.10,0.14")
@click.option("--cam-y", default="-0.02",
              help="Comma-separated, like the other axes.")
@click.option("--out", default=None)
@click.option("--grip", type=click.Choice(["open", "closed"]), default="open",
              help="Jaw state to stage. Closed shows the crescents met, which "
                   "is the silhouette that matters when carrying.")
@click.option("--save-each/--no-save-each", default=True,
              help="Also write each option as its own numbered file.")
def main(pitch, cam_z, cam_y, out, grip, save_each):
    pitches = [float(v) for v in pitch.split(",")]
    zs = [float(v) for v in cam_z.split(",")]
    ys = [float(v) for v in str(cam_y).split(",")]
    rows = []
    outdir = (pathlib.Path(out).parent if out else (SIM / "outputs")) / "cam_options"
    if save_each:
        outdir.mkdir(parents=True, exist_ok=True)
        for f in outdir.glob("opt_*.png"):
            f.unlink()
    opt = 0
    click.echo(f"{'no':>3s}  {'설정':26s} {'물체%':>7s} {'빈%':>7s} {'그리퍼%':>8s}")
    for z in zs:
        tiles = []
        for cam_y, p in itertools.product(ys, pitches):
            opt += 1
            cfg = SceneConfig(wrist_cam_pos=(0.0, cam_y, z), wrist_cam_pitch_deg=p)
            im = staged(cfg, cam_y, z, p, grip=(1.0 if grip == "closed" else 0.0))
            b, bn, g = seen(im)
            label = f"[{opt}]  y{cam_y:+.2f} z{z:.2f} pitch{p:.0f}  {grip}"
            for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                cv2.putText(im, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .62, col, th)
                cv2.putText(im, f"obj {b*100:.2f}%  bin {bn*100:.1f}%  grip {g*100:.1f}%",
                            (8, 46), cv2.FONT_HERSHEY_SIMPLEX, .52, col, th)
            cv2.rectangle(im, (0, 0), (im.shape[1]-1, im.shape[0]-1), (90, 90, 90), 1)
            tiles.append(im)
            if save_each:
                cv2.imwrite(str(outdir / f"opt_{opt:02d}_z{z:.2f}_p{p:.0f}_{grip}.png"),
                            cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
            click.echo(f"{opt:3d}  y{cam_y:+.2f} z{z:.2f} pitch{p:.0f}".ljust(31)
                       + f"{b*100:7.2f} {bn*100:7.1f} {g*100:8.1f}")
        rows.extend(tiles)
    # Chunk to at most 3 across; a single long row makes every tile too small
    # to judge, which is the whole point of the grid.
    per = 3
    chunks = [rows[i:i + per] for i in range(0, len(rows), per)]
    if len(chunks[-1]) < per:
        pad = np.zeros_like(chunks[0][0])
        chunks[-1] += [pad] * (per - len(chunks[-1]))
    grid = np.concatenate([np.concatenate(ch, 1) for ch in chunks], 0)
    q = pathlib.Path(out or (SIM / "outputs" / "camera_variations.png"))
    cv2.imwrite(str(q), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    click.echo(f"\n{grid.shape[1]}x{grid.shape[0]} -> {q}")


if __name__ == "__main__":
    main()
