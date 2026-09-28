"""Does the claw actually hold a small object by its tips? One regression run.

    python sim_umi/scripts/check_tip_grasp.py

The sweeps established the geometry: this claw cannot take a tabletop object
into its cavity (the lower half of the claw is inside the table), so it grasps
with the tips, pitched down. This does not extend that analysis -- it runs the
grasp in the physics and reports what the contacts do.

Approach, close, lift, hold. Reported per run: whether the object left the
table, how far it slipped along the fingers, the normal force at the tips, the
gripper's clearance over the table, and every collision MuJoCo saw, split by
the pairs ROBOTIS's own SRDF says are real.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "scripts"))

import math
import pathlib

import click
import cv2
import mujoco
import numpy as np

from collector import Collector, rot_x, rot_z, sample_spec
from scene import SceneConfig, write_scene
from sweep_grasp_pitch import azimuth, classify, gripper_table_clearance

SIM = pathlib.Path(ROOT) / "sim_umi"


def grasp_pose(cfg, obj_xy, z, pitch, depth):
    """TCP pose that puts the point `depth` along the finger axis on the object."""
    yaw = azimuth(cfg, *obj_xy)
    R = rot_z(yaw) @ rot_x(-pitch)
    p = np.array([obj_xy[0], obj_xy[1], z]) + R @ (np.array(cfg.tcp_offset)
                                                   - np.array([0.0, depth, 0.0]))
    return p, R, yaw


@click.command()
@click.option("-n", "--n-poses", default=6, type=int)
@click.option("--seed", default=21, type=int)
@click.option("--pitch-deg", default=40.0, type=float)
@click.option("--depth", default=0.095, type=float, help="along the finger axis")
@click.option("--video/--no-video", default=True)
def main(n_poses, seed, pitch_deg, depth, video):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg, width=640, height=480)
    m, d = col.model, col.data
    pitch = math.radians(pitch_deg)
    col.enable_overview(width=640, height=480, azimuth=110, elevation=-20,
                        distance=0.85, lookat=(0.0, -0.18, 0.08))
    rng = np.random.default_rng(seed)
    frames, rows = [], []

    for i in range(n_poses):
        sp = sample_spec(rng, seed + i, cfg)
        ox, oy = sp.object_xy
        mujoco.mj_resetData(m, d)
        d.qpos[col.obj_qadr:col.obj_qadr + 3] = [ox, oy, cfg.object_size[2]]
        d.qpos[col.bin_qadr:col.bin_qadr + 3] = [sp.bin_xy[0], sp.bin_xy[1], 0.0]
        gz = float(cfg.object_size[2])

        pg, R, yaw = grasp_pose(cfg, (ox, oy), gz, pitch, depth)
        approach = pg + R @ np.array([0.0, -0.05, 0.0]) + np.array([0, 0, 0.05])
        lift = pg + np.array([0.0, 0.0, 0.12])

        q0, e0, _, _ = col.solve_ik_best(approach, pitch)
        for a, v in zip(col.arm_qadr, q0):
            d.qpos[a] = v
        col._set_gripper(0.0)
        for a, v in zip(col.arm_acts, q0):
            d.ctrl[a] = v
        mujoco.mj_forward(m, d)

        worst_clear, cols = 9.0, {"self": 0, "arm_table": 0, "arm_bin": 0,
                                  "grip_bin": 0, "grip_table": 0}
        rec = []

        def go(target, grip, seconds, tag):
            nonlocal worst_clear
            p0 = np.array([d.site_xpos[col.tcp_sid]]).ravel().copy()
            g0 = (col.grip_hi - d.ctrl[col.left_act]) / col.grip_span
            n = int(seconds / m.opt.timestep)
            for k in range(n):
                a = (k + 1) / n
                p = (1 - a) * p0 + a * np.asarray(target)
                q, ep, er, _ = col.solve_ik_best(p, pitch)
                for act, v in zip(col.arm_acts, q):
                    d.ctrl[act] = v
                col._set_gripper((1 - a) * g0 + a * grip)
                mujoco.mj_step(m, d)
                if k % 15 == 0:
                    worst_clear = min(worst_clear, gripper_table_clearance(col))
                    c = classify(m, d)
                    for key in cols:
                        cols[key] += c[key]
                    if video and k % 30 == 0:
                        col.overview["renderer"].update_scene(
                            d, col.overview["camera"])
                        f = col.overview["renderer"].render().copy()
                        col.renderer.update_scene(d, camera="wrist")
                        w = cv2.resize(col.renderer.render(), (480, 360))
                        pane = np.zeros((480, 640 + 480, 3), np.uint8)
                        pane[:480, :640] = f
                        pane[:360, 640:] = w
                        txt = (f"ep{i} {tag}  jaw {col._gripper_width()*1000:5.1f}mm"
                               f"  obj z {d.xpos[col.object_bid][2]*1000:5.1f}mm"
                               f"  table clr {gripper_table_clearance(col)*1000:+6.1f}mm")
                        for c2, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                            cv2.putText(pane, txt, (8, 470),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, c2, th,
                                        cv2.LINE_AA)
                        frames.append(pane)

        go(pg, 0.0, 1.2, "approach")
        go(pg, 1.0, 1.0, "close")
        go(lift, 1.0, 1.2, "lift")
        go(lift, 1.0, 0.8, "hold")

        objp = d.xpos[col.object_bid].copy()
        lifted = bool(objp[2] > gz + 0.04)
        # where along the fingers did it end up?
        R5 = np.asarray(d.xmat[col.collector_bid]).reshape(3, 3)
        local = R5.T @ (objp - d.xpos[col.collector_bid])
        fn = 0.0
        for ci in range(d.ncon):
            c = d.contact[ci]
            b = {m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]}
            if col.object_bid in b and (set(col.finger_bids) & b):
                f6 = np.zeros(6)
                mujoco.mj_contactForce(m, d, ci, f6)
                fn += abs(f6[0])
        rows.append((lifted, objp[2] * 1000, local[1] * 1000, fn,
                     worst_clear * 1000, cols["self"],
                     cols["arm_table"] + cols["grip_table"],
                     cols["arm_bin"] + cols["grip_bin"]))
        click.secho(
            f"  ep{i}: lifted={lifted}  obj z {objp[2]*1000:6.1f} mm  "
            f"seated at {local[1]*1000:5.1f} mm along the fingers  "
            f"Fn {fn:6.2f} N  table clr {worst_clear*1000:+6.2f} mm  "
            f"coll self/table/bin {cols['self']}/"
            f"{cols['arm_table']+cols['grip_table']}/"
            f"{cols['arm_bin']+cols['grip_bin']}",
            fg="green" if lifted and worst_clear > 0 else "red")
    col.close()

    a = np.array([[float(v) for v in r] for r in rows])
    click.secho(f"\nlifted {int(a[:,0].sum())}/{len(a)}   "
                f"seated {a[:,2].mean():.1f} +- {a[:,2].std():.1f} mm along the "
                f"fingers (tip is 95)   min table clearance {a[:,4].min():+.2f} mm   "
                f"self-collisions {int(a[:,5].sum())}", bold=True)
    if video and frames:
        out = SIM / "outputs" / "tip_grasp.mp4"
        h, w = frames[0].shape[:2]
        vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
        for f in frames:
            vw.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        vw.release()
        cv2.imwrite(str(SIM / "outputs" / "tip_grasp.png"),
                    cv2.cvtColor(np.concatenate(
                        [frames[len(frames)//4], frames[len(frames)//2],
                         frames[-1]], axis=0), cv2.COLOR_RGB2BGR))
        click.echo(f"-> {out}  and tip_grasp.png")


if __name__ == "__main__":
    main()
