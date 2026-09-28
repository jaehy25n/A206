"""Does the gripper close, and do its collision boxes stay inside the part?

    python sim_umi/scripts/check_gripper.py

Three questions, all answered from the compiled model rather than from the
config that generated it:

  1. self-collision across the stroke -- the two fingers are a meshed gear
     pair, so any box that bridges the 0.04-0.12 mm gap at the hinge holds the
     jaw open. Commanded shut, the joint used to stall at 0.025 rad.
  2. the jaw gap in mm at fully open / half / fully closed, driven through the
     actuators, not read off the joint command.
  3. whether each collision pad sits INSIDE the finger mesh, by point-in-mesh
     parity against the mesh triangles.

Writes outputs/check_gripper.png: the wrist view at the three commands.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import pathlib

import click
import cv2
import mujoco
import numpy as np

from collector import Collector
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"


def mesh_arrays(m, geom_name):
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, geom_name)
    mid = m.geom_dataid[g]
    va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
    fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
    v = m.mesh_vert[va:va + vn].astype(np.float64)
    f = m.mesh_face[fa:fa + fn].astype(np.int64)
    # into the geom's own frame, so pad coordinates (body frame) compare
    q = m.geom_quat[g]
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, q)
    return v @ R.reshape(3, 3).T + m.geom_pos[g], f


def x_span(m, d, gid, bp, y, z, exclude=-1, reach=0.05):
    """Where the finger's material starts and ends along x at this (y, z).

    Casts MuJoCo's own ray at the mesh from both sides. A parity test against
    the triangles was tried first and is not usable here: these STLs are not
    watertight, and it reported the blade as solid only in isolated 16 mm
    bands. First-hit ray casting has no such failure mode.
    """
    gout = np.zeros(1, np.int32)
    gg = np.array([0, 1, 0, 0, 0, 0], np.uint8)
    lo = mujoco.mj_ray(m, d, np.array([bp[0] - reach, bp[1] + y, bp[2] + z]),
                       np.array([1.0, 0.0, 0.0]), gg, 1, exclude, gout)
    if lo < 0 or gout[0] != gid:
        return None
    hi = mujoco.mj_ray(m, d, np.array([bp[0] + reach, bp[1] + y, bp[2] + z]),
                       np.array([-1.0, 0.0, 0.0]), gg, 1, exclude, gout)
    if hi < 0 or gout[0] != gid:
        return None
    return (-reach + lo, reach - hi)


@click.command()
@click.option("--n-samples", default=5, type=int, help="grid per pad axis")
def main(n_samples):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    m, d = col.model, col.data
    jl = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "gripper_joint_1")]
    jr = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "gripper_joint_2")]

    click.secho("\n1. stroke scan (kinematic)", bold=True)
    widths, bad = [], 0
    for q in np.linspace(*cfg.hinge_range, 21):
        mujoco.mj_resetData(m, d)
        d.qpos[jl] = d.qpos[jr] = q
        mujoco.mj_forward(m, d)
        ff = 0
        for i in range(d.ncon):
            n1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, d.contact[i].geom1) or ""
            n2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, d.contact[i].geom2) or ""
            if ("left_" in n1 and "right_" in n2) or ("right_" in n1 and "left_" in n2):
                ff += 1
        bad += ff
        widths.append(col._gripper_width())
    mono = bool(np.all(np.diff(widths) > 0))
    click.echo(f"   finger-to-finger contacts over the stroke: {bad}   (want 0)")
    click.echo(f"   width {widths[0]*1000:.2f} -> {widths[-1]*1000:.2f} mm, "
               f"monotone: {mono}")

    click.secho("\n2. commanded jaw gap (through the actuators, no object)", bold=True)
    mujoco.mj_resetData(m, d)
    d.qpos[col.col_qadr:col.col_qadr + 3] = col.mocap_for_grasp([0.0, -0.30, 0.25], 0.0)
    d.mocap_pos[col.mocap_id] = d.qpos[col.col_qadr:col.col_qadr + 3]
    d.qpos[col.obj_qadr:col.obj_qadr + 3] = [0.6, 0.6, 0.01]
    mujoco.mj_forward(m, d)
    shots = []
    for name, alpha in (("fully open", 0.0), ("half close", 0.5), ("fully close", 1.0)):
        col._set_gripper(alpha)
        for _ in range(1500):
            mujoco.mj_step(m, d)
        gap = col._gripper_width() * 1000
        click.echo(f"   {name:12s} cmd {d.ctrl[col.left_act]:6.4f}  "
                   f"q {d.qpos[jl]:+.5f}/{d.qpos[jr]:+.5f}   JAW {gap:6.2f} mm")
        col.renderer.update_scene(d, camera="wrist")
        f = col.renderer.render().copy()
        cv2.putText(f, f"{name}  {gap:.2f} mm", (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(f, f"{name}  {gap:.2f} mm", (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (255, 255, 255), 1, cv2.LINE_AA)
        shots.append(f)

    click.secho("\n3. how far do the collision pads stick out of the finger?",
                bold=True)
    mujoco.mj_resetData(m, d)
    mujoco.mj_forward(m, d)
    worst_all = 0.0
    for side, mesh in (("left", "finger_a_visual"), ("right", "finger_b_visual")):
        gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, mesh)
        bp = d.xpos[m.geom_bodyid[gid]].copy()
        # the ray would otherwise hit the OTHER finger first and be discarded
        other = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY,
                                  "right_finger" if side == "left" else "left_finger")
        for i in range(len(cfg.pad_stations)):
            g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{side}_pad_{i}")
            pos, sz = m.geom_pos[g], m.geom_size[g]
            R = np.zeros(9)
            mujoco.mju_quat2Mat(R, m.geom_quat[g])
            R = R.reshape(3, 3)
            t = np.linspace(-1, 1, n_samples)
            grid = np.array([[a, b, c] for a in t for b in t for c in t]) * sz
            pts = grid @ R.T + pos
            worst, off = 0.0, 0
            for pt in pts:
                span = x_span(m, d, gid, bp, pt[1], pt[2], exclude=other)
                if span is None:
                    off += 1
                    continue
                worst = max(worst, span[0] - pt[0], pt[0] - span[1])
            worst_all = max(worst_all, worst)
            click.secho(f"   {side}_pad_{i}: sticks out by at most "
                        f"{worst*1000:5.2f} mm in x; {off}/{len(pts)} sample points "
                        f"beyond the part in (y, z)",
                        fg="green" if worst < 0.001 else "yellow"
                        if worst < 0.003 else "red")
    click.echo(f"   worst pad protrusion overall: {worst_all*1000:.2f} mm")
    col.close()

    out = SIM / "outputs" / "check_gripper.png"
    cv2.imwrite(str(out), cv2.cvtColor(np.concatenate(shots, axis=1),
                                       cv2.COLOR_RGB2BGR))
    click.echo(f"\n-> {out}")


if __name__ == "__main__":
    main()
