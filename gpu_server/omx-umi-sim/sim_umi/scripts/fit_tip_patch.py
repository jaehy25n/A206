"""Where can the camera still see a patch while the jaw holds the ball?

    python sim_umi/scripts/fit_tip_patch.py

The gripper width in the observation is read off two magenta patches on the
fingertips. With a 50 mm ball held between tips that close to 31.5 mm, the
ball's silhouette is wider than the tips are apart, and in the wrist camera it
covers them: a third of the recorded samples had no measurement at all, and the
estimate held "open" through the whole carry.

So the patch has to move somewhere the held ball cannot cover. This measures
that directly. It poses the arm at a real grasp, closes the jaw on the ball,
and then, for a grid of candidate spots on the finger, casts a ray from the
camera to the spot and asks what it hits first. A spot is visible only if the
first thing on the way is the finger that carries it.

Sensitivity is reported with it, because visibility alone is not enough: a
patch close to the hinge barely moves when the jaw opens, and a gap that hardly
changes cannot measure a width. The number printed is the change in pixel gap
per millimetre of jaw opening, measured by opening the jaw and re-projecting.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import click
import mujoco
import numpy as np

from collector import Collector
from scene import SceneConfig, write_scene


def settle(col, n=400):
    for _ in range(n):
        mujoco.mj_step(col.model, col.data)


def pose_grasp(col, cfg, obj_xy, pitch=0.20, depth=0.065, standoff=0.070):
    """Arm at the object, jaw shut on it, everything settled.

    The ball is 50 mm across and the jaw opens to 52, so there is a millimetre
    of air on each side: teleporting the arm onto a ball already on the table
    puts a finger through it and the solver throws it clear. So the approach is
    the real one -- hold above, then descend to the grasp -- and the jaw closes
    only once the arm has arrived.
    """
    m, d = col.model, col.data
    r = float(cfg.object_size[0])
    d.qpos[col.obj_qadr:col.obj_qadr + 3] = [obj_xy[0], obj_xy[1], r]
    col._set_gripper(0.0)                       # open

    def solve(z):
        tcp = col.grasp_tcp_target(obj_xy, z, pitch, depth)
        q, ep, er, oo = col.solve_ik_best(tcp, pitch)
        if q is None or ep > 0.003:
            raise click.ClickException(
                f"no IK at z {z*1000:.0f} mm (position error {ep*1000:.1f} mm)")
        return np.asarray(q, float)

    def where(tag):
        click.echo(f"    {tag:12s} ball {np.round(d.xpos[col.object_bid]*1000,1)} mm"
                   f"   jaw {col._gripper_width()*1000:6.2f} mm")

    q_hi, q_lo = solve(r + standoff), solve(r)
    # Drive the arm through its actuators, as the controller does. Writing qpos
    # every step instead teleports the fingers through a ball they clear by a
    # millimetre, and the solver answers the penetration by throwing it off the
    # table -- which is exactly what happened: the ball left at 1.3 m.
    def hold(q, n):
        for a, v in zip(col.arm_acts, q):
            d.ctrl[a] = v
        for _ in range(n):
            mujoco.mj_step(m, d)
    for a, v in zip(col.arm_qadr, q_hi):
        d.qpos[a] = v
    mujoco.mj_forward(m, d)
    hold(q_hi, 600)
    where("at standoff")
    n = 30
    for i in range(n):
        hold(q_hi + (q_lo - q_hi) * (i + 1) / n, 60)
    where("at grasp")
    col._set_gripper(1.0)                       # close on the ball
    hold(q_lo, 2500)
    where("closed")
    return q_lo


def surface_z(m, d, gid, body_pos, body_mat, x, y, exclude):
    """Top of the finger mesh at (x, y) in the finger frame, or None."""
    p_local = np.array([x, y, 0.030])
    p = body_pos + body_mat @ p_local
    v = body_mat @ np.array([0.0, 0.0, -1.0])
    gidout = np.zeros(1, np.int32)
    geomgroup = np.ones(6, np.uint8)
    dist = mujoco.mj_ray(m, d, p, v, geomgroup, 0, exclude, gidout)
    if gidout[0] != gid or dist < 0:
        return None
    hit = p + v * dist
    return float((body_mat.T @ (hit - body_pos))[2])


def visible(m, d, cam_pos, target, want_gid, ignore_body):
    """Does the ray from the camera to `target` reach it, or hit something?"""
    v = target - cam_pos
    n = float(np.linalg.norm(v))
    v = v / n
    gidout = np.zeros(1, np.int32)
    geomgroup = np.ones(6, np.uint8)
    dist = mujoco.mj_ray(m, d, cam_pos, v, geomgroup, 0, ignore_body, gidout)
    if dist < 0:
        return False, 1e9, -1
    return bool(gidout[0] == want_gid and dist >= n - 0.002), float(dist - n), int(gidout[0])


#: The grasps the collector actually draws: pitch 6..16 deg, standoff 55..90 mm,
#: depth 60..70 mm, objects anywhere on the paper. A patch is only worth moving
#: to if it survives all of them, not one.
POSES = (
    ((0.060, -0.140), 0.105, 0.060, 0.055),
    ((0.060, -0.140), 0.280, 0.070, 0.090),
    ((-0.090, -0.170), 0.200, 0.065, 0.070),
    ((0.120, -0.090), 0.200, 0.065, 0.070),
    ((0.000, -0.060), 0.160, 0.062, 0.080),
)


@click.command()
@click.option("--step-mm", default=1.0, type=float)
def main(step_mm):
    # Map the bare finger: with the patches on, a ray cast at the spot they
    # already occupy hits the patch and the surface reads as missing.
    cfg = SceneConfig(use_magenta_tips=False)
    col = Collector(write_scene(cfg), cfg=cfg, render=False)
    m, d = col.model, col.data

    cam = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
    left_bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "left_finger")
    right_bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "right_finger")
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "finger_a_visual")
    step = step_mm / 1000.0
    grid = [(round(y, 5), round(x, 5))
            for y in np.arange(0.046, 0.0661, step)
            for x in np.arange(-0.004, 0.0101, step)]

    W, H = cfg.wrist_cam_resolution
    fovy = m.cam_fovy[cam]
    f = 0.5 * H / np.tan(np.deg2rad(fovy) / 2)

    def project(p, c, R):
        q = R.T @ (p - c)                      # camera frame, -z forward
        if -q[2] <= 1e-6:
            return None
        return np.array([W / 2 + f * q[0] / -q[2], H / 2 - f * q[1] / -q[2]])

    seen = {k: 0 for k in grid}
    seen_open = {k: 0 for k in grid}
    zs = {}
    gaps = {}
    n_grasped = 0
    for obj_xy, pitch, depth, standoff in POSES:
        mujoco.mj_resetData(m, d)
        mujoco.mj_forward(m, d)
        click.secho(f"\npose {obj_xy} pitch {np.rad2deg(pitch):.0f} deg "
                    f"depth {depth*1000:.0f} standoff {standoff*1000:.0f} mm", bold=True)
        pose_grasp(col, cfg, obj_xy, pitch=pitch, depth=depth, standoff=standoff)
        w_closed = col._gripper_width()
        if not 0.028 <= w_closed <= 0.036:
            # The jaw shut on nothing, so this pose says nothing about what a
            # held ball hides. Counting it would demand visibility in a grasp
            # that never happened and leave no candidate anywhere.
            click.secho(f"  no grasp here (jaw {w_closed*1000:.2f} mm) -- skipped",
                        fg="yellow")
            continue
        bp = d.xpos[left_bid].copy()
        bm = np.asarray(d.xmat[left_bid]).reshape(3, 3)
        cam_pos = d.cam_xpos[cam].copy()
        cam_mat = np.asarray(d.cam_xmat[cam]).reshape(3, 3)
        n_vis = 0
        for (y, x) in grid:
            z = surface_z(m, d, gid, bp, bm, x, y, exclude=right_bid)
            if z is None:
                continue
            zs.setdefault((y, x), []).append(z)
            p = bp + bm @ np.array([x, y, z + 0.0002])
            ok, _, hitg = visible(m, d, cam_pos, p, gid, ignore_body=-1)
            seen[(y, x)] += int(ok)
            n_vis += int(ok)
            u = project(p, cam_pos, cam_mat)
            if u is not None:
                gaps.setdefault((y, x), []).append(("closed", w_closed,
                                                    2 * abs(u[0] - W / 2)))
        # the same spots with the jaw open, for the sensitivity
        col._set_gripper(0.0)
        for _ in range(1500):
            mujoco.mj_step(m, d)
        w_open = col._gripper_width()
        bp = d.xpos[left_bid].copy()
        bm = np.asarray(d.xmat[left_bid]).reshape(3, 3)
        cam_pos = d.cam_xpos[cam].copy()
        cam_mat = np.asarray(d.cam_xmat[cam]).reshape(3, 3)
        for (y, x) in grid:
            if (y, x) not in zs:
                continue
            p = bp + bm @ np.array([x, y, zs[(y, x)][-1] + 0.0002])
            # A spot that only shows while the jaw is shut is no use either:
            # the stroke has to be visible end to end.
            ok, _, _ = visible(m, d, cam_pos, p, gid, ignore_body=-1)
            seen_open[(y, x)] += int(ok)
            u = project(p, cam_pos, cam_mat)
            if u is not None:
                gaps[(y, x)].append(("open", w_open, 2 * abs(u[0] - W / 2)))
        n_grasped += 1
        click.echo(f"  jaw {w_closed*1000:.2f} -> {w_open*1000:.2f} mm, "
                   f"{n_vis} spots visible while holding")

    always = [k for k in grid if seen.get(k, 0) == n_grasped
              and seen_open.get(k, 0) == n_grasped]
    click.secho(f"\nvisible in all {n_grasped} grasps that held the ball: "
                f"{len(always)} spots", bold=True)
    if not always:
        click.secho("  none -- the patch cannot stay on the fingertip", fg="red")
        return
    # A patch is not a point. What matters is how much of the square still
    # reaches the camera, because that is how many pixels the detector gets --
    # and a patch half off the material is the floating-sticker bug again.
    xs = sorted({k[1] for k in grid})
    ys = sorted({k[0] for k in grid})
    click.secho("\n  visible in every grasp and both jaw states (#), "
                "hidden in some (.), no material ( )", bold=True)
    click.echo("      x " + " ".join(f"{v*1000:+5.1f}" for v in xs[::2]))
    for y in ys[::2]:
        line = []
        for x in xs[::2]:
            k = (y, x)
            if k not in zs:
                line.append("     ")
            else:
                both = (seen.get(k, 0) == n_grasped
                        and seen_open.get(k, 0) == n_grasped)
                line.append("    #" if both else "    .")
        click.echo(f"  y {y*1000:4.1f} " + " ".join(line))

    def coverage(cy, cx, half):
        """Fraction of the patch that is on the finger AND visible throughout."""
        pts = [k for k in grid
               if abs(k[0] - cy) <= half + 1e-9 and abs(k[1] - cx) <= half + 1e-9]
        if not pts:
            return 0.0, 0.0
        on = [k for k in pts if k in zs]
        good = [k for k in on if seen.get(k, 0) == n_grasped
                and seen_open.get(k, 0) == n_grasped]
        return len(on) / len(pts), len(good) / len(pts)

    click.secho("\n  patch centres, by how much of the square survives", bold=True)
    for half_mm in (1.5, 1.0):
        rows = []
        for cy in ys:
            for cx in xs:
                on, good = coverage(cy, cx, half_mm / 1000.0)
                if good <= 0.0:
                    continue
                g = gaps.get((cy, cx), [])
                cl = [v for t, w, v in g if t == "closed"]
                op = [v for t, w, v in g if t == "open"]
                if not cl or not op:
                    continue
                wc = np.mean([w for t, w, v in g if t == "closed"])
                wo = np.mean([w for t, w, v in g if t == "open"])
                s_px = (np.mean(op) - np.mean(cl)) / ((wo - wc) * 1000)
                rows.append((good, on, s_px, cy, cx, float(np.mean(zs[(cy, cx)]))))
        rows.sort(reverse=True)
        click.secho(f"\n    {half_mm*2:.0f} x {half_mm*2:.0f} mm patch", bold=True)
        click.echo(f"    {'y':>5s} {'x':>6s} {'z':>6s} {'on mesh':>8s} "
                   f"{'visible':>8s} {'px/mm':>6s}")
        for good, on, s_px, cy, cx, z in rows[:8]:
            click.echo(f"    {cy*1000:5.1f} {cx*1000:+6.1f} {z*1000:6.2f} "
                       f"{on*100:7.0f}% {good*100:7.0f}% {s_px:6.2f}")
    click.secho("\n  current patch: x +6.00  y 61.00  z 8.71, half 1.5 mm", fg="yellow")
    on, good = coverage(0.061, 0.006, 0.0015)
    click.secho(f"    on mesh {on*100:.0f}%, visible throughout {good*100:.0f}%",
                fg="yellow")
    col.close()


if __name__ == "__main__":
    main()
