"""Which grasp orientations can this arm actually hold, and at what cost?

    python sim_umi/scripts/sweep_grasp_pitch.py

Two questions, both answered with numbers rather than with a chosen value.

1. WHICH ORIENTATION FREEDOM IS MISSING.  Five joints, three of them spent on
   position, leave a two-dimensional set of tool orientations at a given
   point. This finds the one direction that is NOT in it: the null space of
   the position Jacobian is mapped through the rotation Jacobian, and what is
   left over is the axis the wrist cannot turn about. It is reported in the
   world and in the tool frame, together with what Joint5 alone turns.

2. WHAT PITCH TO GRASP AT.  A sweep over nose-down pitch at representative
   object and bin placements, measuring IK success, position error, how close
   each joint sits to its limit, the gripper's clearance over the table,
   collisions against the table, the bin and the arm itself (using ROBOTIS's
   own disable_collisions matrix from omx_f.srdf), and whether the object is
   still in the wrist camera.

The pitch is not fixed here. If one band is good everywhere, its middle is the
default; if the good band moves with the pose, the caller picks per pose.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import json
import math
import pathlib

import click
import mujoco
import numpy as np

from collector import Collector, sample_spec
from scene import SceneConfig, write_scene

SIM = pathlib.Path(ROOT) / "sim_umi"

#: open_manipulator_moveit_config/config/omx_f/omx_f.srdf. Pairs ROBOTIS
#: declare cannot collide -- adjacency, plus link2/link4 which they mark
#: "Never". Everything else is a real self-collision.
SRDF_ALLOWED = {frozenset(p) for p in (
    ("link0", "link1"), ("link1", "link2"), ("link2", "link3"),
    ("link2", "link4"), ("link3", "link4"), ("link4", "link5"),
    ("link5", "left_finger"), ("link5", "right_finger"),
    ("left_finger", "right_finger"),
    ("link5", "collector"), ("collector", "left_finger"),
    ("collector", "right_finger"),
)}
ARM_BODIES = {"link0", "link1", "link2", "link3", "link4", "link5"}
GRIP_BODIES = {"collector", "left_finger", "right_finger"}
TABLE_GEOMS = {"desk", "black_paper", "room_floor"}


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def target_R(yaw, pitch):
    """Fingers along +y at yaw = 0; pitch tips them nose-down."""
    return rot_z(yaw) @ rot_x(-pitch)


def azimuth(cfg, x, y):
    """The base angle that points the gripper at (x, y)."""
    bx, by = cfg.robot_base_xy
    return math.atan2(-(x - bx), y - by)


def classify(m, d):
    """Contacts, split the way the question is asked."""
    out = {"self": 0, "arm_table": 0, "arm_bin": 0, "grip_bin": 0,
           "grip_table": 0}
    for i in range(d.ncon):
        c = d.contact[i]
        b1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[c.geom1])
        b2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[c.geom2])
        g1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom1)
        g2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom2)
        robot = {b1, b2} & (ARM_BODIES | GRIP_BODIES)
        if not robot:
            continue
        other_g = g2 if b1 in robot and b2 not in robot else g1
        other_b = b2 if b1 in robot else b1
        pair = frozenset((b1, b2))
        if b1 in (ARM_BODIES | GRIP_BODIES) and b2 in (ARM_BODIES | GRIP_BODIES):
            if pair not in SRDF_ALLOWED:
                out["self"] += 1
            continue
        arm_side = "arm" if (robot & ARM_BODIES) else "grip"
        if other_g in TABLE_GEOMS:
            out[f"{arm_side}_table"] += 1
        elif other_b == "bin":
            out[f"{arm_side}_bin"] += 1
    return out


@click.command()
@click.option("-n", "--n-poses", default=16, type=int)
@click.option("--seed", default=21, type=int)
@click.option("--pitches", default="0,10,20,30,40,50,60,70,80,90")
@click.option("--grasp-z", default=0.010, type=float)
def main(n_poses, seed, pitches, grasp_z):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    m, d = col.model, col.data
    if not col.has_arm:
        raise click.ClickException("this scene has no arm")
    rng = np.random.default_rng(seed)
    specs = [sample_spec(rng, seed + i, cfg) for i in range(n_poses)]

    # ---------------------------------------------------------------- part 1
    click.secho("1. which orientation direction the wrist cannot reach", bold=True)
    missing, roll_axis = [], []
    for sp in specs:
        ox, oy = sp.object_xy
        yaw = azimuth(cfg, ox, oy)
        q, ep, er, _ = col.solve_ik_best([ox, oy, 0.12], math.radians(30))
        set_arm(col, q)
        jacp = np.zeros((3, m.nv))
        jacr = np.zeros((3, m.nv))
        mujoco.mj_jacSite(m, d, jacp, jacr, col.tcp_sid)
        Jp = jacp[:, col.arm_dofs]
        Jr = jacr[:, col.arm_dofs]
        _, _, Vt = np.linalg.svd(Jp)
        null = Vt[3:].T                      # 5 x 2, joint motions that hold position
        span = Jr @ null                     # 3 x 2, the angular velocities left
        u, s, _ = np.linalg.svd(span)
        missing.append(u[:, 2])              # orthogonal to both
        R = np.asarray(d.site_xmat[col.tcp_sid]).reshape(3, 3)
        roll_axis.append(R.T @ Jr[:, 4] / (np.linalg.norm(Jr[:, 4]) + 1e-12))
    missing = np.array([v * np.sign(v[2] if abs(v[2]) > 1e-9 else 1) for v in missing])
    click.echo(f"   unreachable rotation axis, world frame: "
               f"mean {np.round(missing.mean(0), 4)}  "
               f"(spread {np.round(missing.std(0), 4)})")
    click.echo(f"   its angle from vertical: "
               f"{np.degrees(np.arccos(np.clip(np.abs(missing @ [0,0,1.0]), 0, 1))).mean():.2f} deg")
    ra = np.array(roll_axis)
    click.echo(f"   Joint5 turns the tool about, in the TOOL frame: "
               f"{np.round(ra.mean(0), 4)}   (tool +y is the finger axis)")
    click.echo("   -> the locked freedom is rotation about the world vertical:"
               " the tool's yaw is the base angle. Joint5 rolls about the"
               " finger axis, which for a two-finger claw only turns the jaw"
               " plane, and joints 2-4 set the pitch freely.")

    # ---------------------------------------------------------------- part 2
    click.secho("\n2. pitch sweep", bold=True)
    rows = []
    plist = [float(p) for p in pitches.split(",")]
    for pitch_deg in plist:
        pitch = math.radians(pitch_deg)
        rec = []
        for sp in specs:
            ox, oy = sp.object_xy
            bx, by = sp.bin_xy
            place(col, sp, grasp_z)
            yaw = azimuth(cfg, ox, oy)
            gp = np.array(cfg.grasp_point_offset)
            R = target_R(yaw, pitch)
            # put the CAVITY on the object, as the demonstration does
            tcp_goal = np.array([ox, oy, grasp_z]) + R @ (np.array(cfg.tcp_offset) - gp)
            q, ep, er, oop = col.solve_ik_best(tcp_goal, pitch)
            set_arm(col, q)
            mujoco.mj_forward(m, d)
            margin = np.degrees(min(
                min(q[k] - col.arm_range[k][0], col.arm_range[k][1] - q[k])
                for k in range(5)))
            clear = gripper_table_clearance(col)
            con = classify(m, d)
            vis = object_pixels(col)
            bx0, by0 = col.arm_pivot_xy
            rec.append((ep * 1000, math.degrees(er), margin, clear * 1000,
                        con["self"], con["arm_table"] + con["grip_table"],
                        con["arm_bin"] + con["grip_bin"], vis,
                        math.hypot(ox - bx0, oy - by0) * 1000))
        a = np.array(rec, float)
        ok = (a[:, 0] < 1.0) & (a[:, 1] < 2.0)
        bad_r = np.sort(a[~ok][:, 8]) if (~ok).any() else np.array([])
        rows.append({
            "pitch_deg": pitch_deg, "ik_ok": int(ok.sum()), "n": len(a),
            "pos_err_mm_max": float(a[:, 0].max()),
            "rot_err_deg_max": float(a[:, 1].max()),
            "limit_margin_deg_min": float(a[:, 2].min()),
            "table_clearance_mm_min": float(a[:, 3].min()),
            "self_collisions": int(a[:, 4].sum()),
            "table_collisions": int(a[:, 5].sum()),
            "bin_collisions": int(a[:, 6].sum()),
            "object_pixels_median": float(np.median(a[:, 7])),
            "object_seen": int((a[:, 7] > 20).sum()),
            "unreachable_radius_mm": [round(float(v)) for v in bad_r],
        })
        r = rows[-1]
        click.secho(
            f"  pitch {pitch_deg:5.1f}  IK {r['ik_ok']:2d}/{r['n']:2d}  "
            f"pos<={r['pos_err_mm_max']:6.2f}mm rot<={r['rot_err_deg_max']:5.1f}deg  "
            f"limit>={r['limit_margin_deg_min']:6.1f}deg  "
            f"table clr>={r['table_clearance_mm_min']:7.2f}mm  "
            f"coll self/table/bin {r['self_collisions']:2d}/{r['table_collisions']:2d}/"
            f"{r['bin_collisions']:2d}  obj seen {r['object_seen']:2d}/{r['n']}"
            + (f"  unreachable at r={r['unreachable_radius_mm']} mm"
               if r["unreachable_radius_mm"] else ""),
            fg=("green" if (r["ik_ok"] == r["n"] and r["self_collisions"] == 0
                            and r["table_collisions"] == 0
                            and r["bin_collisions"] == 0
                            and r["table_clearance_mm_min"] > 0
                            and r["object_seen"] == r["n"]) else "yellow"))
    col.close()
    out = SIM / "outputs" / "grasp_pitch_sweep.json"
    out.write_text(json.dumps({"seed": seed, "n_poses": n_poses,
                               "grasp_z": grasp_z, "rows": rows}, indent=2))
    good = [r for r in rows
            if r["ik_ok"] == r["n"] and r["self_collisions"] == 0
            and r["table_collisions"] == 0 and r["bin_collisions"] == 0
            and r["table_clearance_mm_min"] > 0 and r["object_seen"] == r["n"]]
    click.secho("\nclean band: "
                + (f"{good[0]['pitch_deg']:.0f} .. {good[-1]['pitch_deg']:.0f} deg"
                   f"   -> middle {np.median([g['pitch_deg'] for g in good]):.0f} deg"
                   if good else "none of the sampled pitches is clean everywhere"),
                bold=True)
    click.echo(f"-> {out}")


def quat_of(R):
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, float).reshape(-1))
    return q


def set_arm(col, q):
    for a, v in zip(col.arm_qadr, q):
        col.data.qpos[a] = v
    mujoco.mj_forward(col.model, col.data)


def place(col, spec, grasp_z):
    m, d = col.model, col.data
    mujoco.mj_resetData(m, d)
    ox, oy = spec.object_xy
    bx, by = spec.bin_xy
    d.qpos[col.obj_qadr:col.obj_qadr + 3] = [ox, oy, grasp_z]
    d.qpos[col.bin_qadr:col.bin_qadr + 3] = [bx, by, 0.0]
    col._set_gripper(0.0)
    for a in col.arm_qadr:
        d.qpos[a] = 0.0
    mujoco.mj_forward(m, d)


def gripper_table_clearance(col):
    """Lowest point of either finger mesh, above the paper."""
    m, d = col.model, col.data
    lo = 9.0
    for name in ("finger_a_visual", "finger_b_visual"):
        g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, name)
        mid = m.geom_dataid[g]
        a, n = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        v = m.mesh_vert[a:a + n].astype(float)
        w = d.geom_xpos[g] + v @ np.asarray(d.geom_xmat[g]).reshape(3, 3).T
        lo = min(lo, float(w[:, 2].min()))
    return lo - 0.001


def object_pixels(col):
    col.renderer.update_scene(col.data, camera="wrist")
    img = col.renderer.render()
    b = img.astype(np.int16)
    return int((((b[:, :, 2] - b[:, :, 0]) > 40) & (b[:, :, 2] > 90)).sum())


if __name__ == "__main__":
    main()
