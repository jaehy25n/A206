"""Separate the layers of the pivot-gripper transport failure.

Order matters. A static hold that already creeps means the geometry or the
preload is wrong, and no trajectory tuning will save it. Only if the hold is
solid does acceleration become the suspect. Friction is adjusted last, and
only once the contact geometry is known to be right -- raising it first buys a
passing number and hides the cause.

    python sim_umi/scripts/diagnose_grasp.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import click
import mujoco
import numpy as np

from collector import Collector, EpisodeSpec, yaw_quat
from scene import SceneConfig, write_scene


def rel_transform(d, obj_bid, tcp_sid):
    """Object pose expressed in the TCP frame. Constant while truly gripped."""
    R = np.asarray(d.site_xmat[tcp_sid]).reshape(3, 3)
    p = np.asarray(d.site_xpos[tcp_sid])
    return R.T @ (np.asarray(d.xpos[obj_bid]) - p)


def contacts_with(m, d, body_id, other_id):
    out = []
    for i in range(d.ncon):
        c = d.contact[i]
        b1 = m.geom_bodyid[c.geom1]
        b2 = m.geom_bodyid[c.geom2]
        if {b1, b2} != {body_id, other_id}:
            continue
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        out.append({
            "geom1": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom1),
            "geom2": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom2),
            "pos": c.pos.copy(),
            "normal": np.asarray(c.frame[:3]).copy(),
            "dist": float(c.dist),
            "f_normal": float(f[0]),
            "f_tan": float(np.linalg.norm(f[1:3])),
        })
    return out


@click.command()
@click.option("--hold", default=3.0, type=float)
def main(hold):
    cfg = SceneConfig()
    col = Collector(str(write_scene(cfg)), cfg=cfg)
    m, d = col.model, col.data
    spec = EpisodeSpec()

    jadr = [m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, j)]
            for j in ("left_slide", "right_slide")]
    finger_bids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b)
                   for b in ("left_finger", "right_finger")]

    def settle(n):
        for _ in range(n):
            mujoco.mj_step(m, d)

    def goto(tcp, yaw, dur, grip):
        p0 = d.mocap_pos[col.mocap_id].copy()
        p1 = col.mocap_for_tcp(tcp, yaw)
        n = int(dur / m.opt.timestep)
        g0 = (col.grip_hi - d.ctrl[col.left_act]) / col.grip_span
        for i in range(n):
            a = (i + 1) / n
            d.mocap_pos[col.mocap_id] = (1 - a) * p0 + a * p1
            d.mocap_quat[col.mocap_id] = yaw_quat(yaw)
            col._set_gripper((1 - a) * g0 + a * grip)
            mujoco.mj_step(m, d)

    # ---------------------------------------------------------- setup ---- #
    mujoco.mj_resetData(m, d)
    ox, oy = spec.object_xy
    d.qpos[col.obj_qadr:col.obj_qadr + 3] = [ox, oy, spec.grasp_z]
    d.qpos[col.obj_qadr + 3:col.obj_qadr + 7] = yaw_quat(0.0)
    bx, by = spec.bin_xy
    d.qpos[col.bin_qadr:col.bin_qadr + 3] = [bx, by, 0.0]
    start = col.mocap_for_grasp([ox, oy, spec.carry_z], 0.0)
    d.qpos[col.col_qadr:col.col_qadr + 3] = start
    mujoco.mj_forward(m, d)
    d.mocap_pos[col.mocap_id] = start
    d.mocap_quat[col.mocap_id] = yaw_quat(0.0)
    col._set_gripper(0.0)
    settle(300)

    ga = col.grasp_alpha_for(spec)
    target_theta = col.grip_hi + (col.grip_lo - col.grip_hi) * ga
    target_gap = 2 * spec.object_size_xy - spec.grasp_squeeze
    click.echo(f"object {2*spec.object_size_xy*1000:.0f} mm   "
               f"commanded jaw {target_gap*1000:.1f} mm   "
               f"-> alpha {ga:.3f}, theta {target_theta:.4f} rad")

    goto([ox, oy, spec.grasp_z], 0.0, 0.6, 0.0)     # descend, open
    goto([ox, oy, spec.grasp_z], 0.0, 0.8, ga)      # close

    # ------------------------------------------------- preload check ----- #
    click.echo("\n[1] commanded vs actual, right after the close")
    click.echo(f"  commanded theta {target_theta:.5f} rad")
    click.echo(f"  actual   theta  L {d.qpos[jadr[0]]:.5f}  R {d.qpos[jadr[1]]:.5f}")
    click.echo(f"  commanded gap   {target_gap*1000:6.2f} mm")
    click.echo(f"  actual tip gap  {col._gripper_width()*1000:6.2f} mm")
    err = abs(d.qpos[jadr[0]] - target_theta)
    click.echo(f"  -> the jaw stops {err:.5f} rad short of its command; that "
               f"deficit IS the preload\n     (zero would mean it closed freely "
               f"and is touching nothing)")

    click.echo("\n[2] finger<->object contacts while gripped")
    cs = []
    for bid, nm in zip(finger_bids, ("left", "right")):
        for c in contacts_with(m, d, bid, col.object_bid):
            cs.append((nm, c))
    if not cs:
        click.secho("  NO finger-object contact at all", fg="red")
    for nm, c in cs:
        click.echo(f"  {nm:5s} pos {np.round(c['pos'],4)}  normal "
                   f"{np.round(c['normal'],3)}  pen {c['dist']*1000:+.3f} mm  "
                   f"Fn {c['f_normal']:7.2f} N  Ft {c['f_tan']:6.2f} N")
    if cs:
        # A jaw that grips has normals pointing along the closing axis (x here).
        nx = [abs(c["normal"][0]) for _, c in cs]
        click.echo(f"  |normal.x| = {np.round(nx,3).tolist()}   "
                   f"(1.0 = squarely across the jaw, 0 = sliding along it)")

    # ------------------------------------------------- static hold ------- #
    goto([ox, oy, spec.carry_z], 0.0, 0.6, ga)
    r0 = rel_transform(d, col.object_bid, col.tcp_sid)
    z0 = float(d.xpos[col.object_bid][2])
    click.echo(f"\n[3] static hold {hold:.0f}s at carry height "
               f"(no motion, no rotation)")
    click.echo(f"  {'t':>5s} {'drift_x':>9s} {'drift_y':>9s} {'drift_z':>9s} "
               f"{'obj_z':>8s} {'gap mm':>8s} {'Fn':>7s}")
    n = int(hold / m.opt.timestep)
    for i in range(n):
        mujoco.mj_step(m, d)
        if i % int(0.5 / m.opt.timestep) == 0 or i == n - 1:
            dr = rel_transform(d, col.object_bid, col.tcp_sid) - r0
            fn = sum(c["f_normal"] for b in finger_bids
                     for c in contacts_with(m, d, b, col.object_bid))
            click.echo(f"  {i*m.opt.timestep:5.2f} {dr[0]*1000:8.3f}m "
                       f"{dr[1]*1000:8.3f}m {dr[2]*1000:8.3f}m "
                       f"{d.xpos[col.object_bid][2]:8.4f} "
                       f"{col._gripper_width()*1000:8.2f} {fn:7.2f}")
    drift = rel_transform(d, col.object_bid, col.tcp_sid) - r0
    slipped = float(np.linalg.norm(drift))
    fell = z0 - float(d.xpos[col.object_bid][2])
    # A couple of millimetres as the object seats into the cavity is not a
    # slip. What matters is whether it keeps going: compare the first half
    # second against the rest.
    creeping = abs(drift[2]) > 0.02 or fell > 0.005
    click.echo(f"\n  total drift {slipped*1000:.3f} mm  "
               f"(object fell {(z0 - float(d.xpos[col.object_bid][2]))*1000:+.2f} mm)")
    verdict = ("HOLD FAILS -- geometry / contact normal / preload, not trajectory"
               if creeping else
               f"hold is solid ({slipped*1000:.1f} mm of seating, then flat) -- "
               f"any remaining failure is in the motion")
    click.secho(f"  => {verdict}", fg="red" if creeping else "green")
    col.close()


if __name__ == "__main__":
    main()
