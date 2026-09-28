"""Fit the finger's collision boxes to the finger, by measuring the mesh.

    python sim_umi/scripts/fit_finger_pads.py

Prints a table to paste into SceneConfig.finger_pad_boxes. Every number comes
from casting MuJoCo's own rays at the visual mesh and reading where the
material starts and stops; none of it is read off a drawing or inferred from
the STL's bounding box, both of which have already produced boxes that were
8 mm larger than the part and a magenta patch sitting beside it.

The boxes are axis-aligned in the finger frame and short in y, so the stack
follows the curve as a staircase. A longer box turned to the local tangent
covers the same curve with fewer parts, but its corners then leave the
material, and at the tip that overlap held the jaw 1.6 mm open.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "scripts"))

import click
import mujoco
import numpy as np

from check_gripper import x_span
from scene import SceneConfig, write_scene


@click.command()
@click.option("--y0", default=0.015, type=float)
@click.option("--y1", default=0.065, type=float)
@click.option("--n-bands", default=8, type=int)
@click.option("--clearance", default=0.0003, type=float,
              help="how far inside the surface every box face is kept (m)")
def main(y0, y1, n_bands, clearance):
    cfg = SceneConfig()
    m = mujoco.MjModel.from_xml_path(str(write_scene(cfg)))
    d = mujoco.MjData(m)
    mujoco.mj_resetData(m, d)
    mujoco.mj_forward(m, d)
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "finger_a_visual")
    bp = d.xpos[m.geom_bodyid[gid]].copy()
    other = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "right_finger")

    edges = np.linspace(y0, y1, n_bands + 1)
    zs = np.arange(-0.024, 0.0241, 0.00025)
    rows = []
    for b in range(n_bands):
        ya, yb = edges[b], edges[b + 1]
        ys = np.linspace(ya + 1e-4, yb - 1e-4, 5)
        ok = np.ones(len(zs), bool)
        xin = np.full(len(zs), +9.0)
        xout = np.full(len(zs), -9.0)
        for y in ys:
            for k, z in enumerate(zs):
                sp = x_span(m, d, gid, bp, y, z, exclude=other)
                if sp is None:
                    ok[k] = False
                    continue
                xout[k] = max(xout[k], sp[0])
                xin[k] = min(xin[k], sp[1])
        # EVERY run of z where every y in the band has material. The finger is
        # a frame, not a plate: at mid-span the only thing crossing a whole
        # band is the horizontal member at z = 0, with an X of ribs above and
        # below it and air in between. Taking one run per band would model the
        # air as solid.
        runs, run, k = [], 0, 0
        for k, v in enumerate(list(ok) + [False]):
            if v:
                run += 1
            else:
                if run:
                    runs.append((k - run, k - 1))
                run = 0
        found = 0
        for k0, k1 in runs:
            z_lo, z_hi = zs[k0], zs[k1]
            x_out = xout[k0:k1 + 1].max()
            x_in = xin[k0:k1 + 1].min()
            half_t = (x_in - x_out) / 2 - clearance
            half_h = (z_hi - z_lo) / 2 - clearance
            if half_t < 0.0003 or half_h < 0.0002:
                continue
            rows.append(((ya + yb) / 2, (yb - ya) / 2 - clearance,
                         (x_in + x_out) / 2, half_t, (z_lo + z_hi) / 2, half_h))
            found += 1
            click.echo(f"  band {ya*1000:5.1f}-{yb*1000:5.1f} mm   "
                       f"x {x_out*1000:+6.2f}..{x_in*1000:+6.2f}   "
                       f"z {z_lo*1000:+6.2f}..{z_hi*1000:+6.2f}")
        if not found:
            click.secho(f"  band {ya*1000:5.1f}-{yb*1000:5.1f} mm: nothing "
                        f"crosses it", fg="yellow")

    click.secho("\n    #: (y_centre, half_len, x_centre, half_thick, "
                "z_centre, half_height)", bold=True)
    click.echo("    finger_pad_boxes: Tuple[Tuple[float, ...], ...] = (")
    for r in rows:
        click.echo("        (" + ", ".join(f"{v:.5f}" for v in r) + "),")
    click.echo("    )")


if __name__ == "__main__":
    main()
