"""Where should the arm start, and how should it look around?

    python sim_umi/scripts/design_search.py

The wrist camera sees 39.8 degrees once the centre square is taken, and the
paper is 500 mm across. A demonstration that starts anywhere and drives
straight at a ball it has never seen is not explainable from its own
observations, so the expert has to look first. That means two things have to
be chosen and neither can be guessed:

    HOME    one deterministic pose every episode starts from, placed so the
            camera already covers part of the workspace
    SCAN    a sweep that is the same in every episode -- it cannot depend on
            where the ball is, or the search is target-directed after all

This measures both. It samples ball and bin placements from the same
distribution the collector draws, walks each candidate scan pose by pose, and
reports what fraction of placements enter the centre crop and how far into the
sweep. Every pose is put through the same planar IK and joint limits the
demonstrations use, so a sweep that cannot be flown is reported as such rather
than proposed.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import click
import mujoco
import numpy as np

from collector import Collector
from scene import SceneConfig, write_scene


class Eye:
    """The wrist camera, as a projection from a tool pose."""

    def __init__(self, cfg, model, data):
        cam = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
        tcp = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "tcp")
        mujoco.mj_resetData(model, data)
        mujoco.mj_forward(model, data)
        Rt = np.asarray(data.site_xmat[tcp]).reshape(3, 3)
        Rc = np.asarray(data.cam_xmat[cam]).reshape(3, 3)
        self.R_tc = Rt.T @ Rc
        self.p_tc = Rt.T @ (data.cam_xpos[cam] - data.site_xpos[tcp])
        self.W, self.H = cfg.wrist_cam_resolution
        self.f = 0.5 * self.H / math.tan(math.radians(model.cam_fovy[cam]) / 2)
        self.side = min(self.W, self.H)
        self.x0 = (self.W - self.side) // 2

    def sees(self, tcp_pos, tcp_rot, target):
        """Is `target` inside the square the policy is given?"""
        cam_p = np.asarray(tcp_pos) + tcp_rot @ self.p_tc
        q = (tcp_rot @ self.R_tc).T @ (np.asarray(target) - cam_p)
        if -q[2] <= 1e-6:
            return False
        u = self.W / 2 + self.f * q[0] / -q[2]
        v = self.H / 2 - self.f * q[1] / -q[2]
        return self.x0 <= u < self.x0 + self.side and 0 <= v < self.H


def tool_pose(kin, cfg, azimuth, radius, z, pitch):
    """A tool pose on the arc at `azimuth` about the base, nose pitched down."""
    bx, by = cfg.robot_base_xy
    x, y = bx + radius * math.sin(azimuth), by + radius * math.cos(azimuth)
    R = np.array([[math.cos(azimuth), -math.sin(azimuth), 0.0],
                  [math.sin(azimuth), math.cos(azimuth), 0.0],
                  [0.0, 0.0, 1.0]]) @ np.array(
        [[1.0, 0.0, 0.0],
         [0.0, math.cos(-pitch), -math.sin(-pitch)],
         [0.0, math.sin(-pitch), math.cos(-pitch)]])
    return np.array([x, y, z]), R


def flyable(kin, pos, pitch, seed=None):
    """The same gates the demonstrations use, so a proposal is a real one."""
    if seed is not None:
        for a, v in zip(kin.arm_qadr, seed):
            kin.data.qpos[a] = v
    q, ep, er, _ = kin.solve_ik_planar(pos, pitch, iters=60)
    if ep > 0.002 or abs(er) > math.radians(3):
        return None
    lo, hi = kin.arm_range[:, 0], kin.arm_range[:, 1]
    if float(np.minimum(q - lo, hi - q).min()) < math.radians(2):
        return None
    return np.asarray(q, float)


def placements(cfg, n, rng):
    """Ball and bin positions, drawn the way the collector draws them."""
    bx, by = cfg.robot_base_xy
    out = []
    while len(out) < n:
        r = math.sqrt(rng.uniform(0.16 ** 2, 0.30 ** 2))
        th = rng.uniform(-math.pi / 3, math.pi / 3)
        x, y = bx + r * math.sin(th), by + r * math.cos(th)
        if cfg.on_paper(x, y, 0.09) and cfg.reachable(x, y, 0.06):
            out.append((x, y))
    return out


def sweep(kin, cfg, eye, legs, targets, ball_r):
    """Fly a scan and report where each target first enters the crop."""
    poses, qs, seed = [], [], None
    for (az, rad, z, pitch) in legs:
        pos, R = tool_pose(kin, cfg, az, rad, z, pitch)
        q = flyable(kin, pos, pitch, seed)
        if q is None:
            return None, f"cannot fly ({math.degrees(az):+.0f} deg, r {rad*1000:.0f}, z {z*1000:.0f})"
        seed = q
        poses.append((pos, R))
        qs.append(q)
    first = []
    for (tx, ty) in targets:
        tgt = np.array([tx, ty, ball_r])
        k = next((i for i, (p, R) in enumerate(poses) if eye.sees(p, R, tgt)), None)
        first.append(k)
    return (poses, qs, first), None


def report(name, first, n_legs):
    seen = [k for k in first if k is not None]
    pct = 100.0 * len(seen) / len(first)
    click.secho(f"  {name:34s} {pct:5.1f}% found", bold=pct > 95,
                fg="green" if pct > 95 else ("yellow" if pct > 70 else "red"))
    if seen:
        click.echo(f"      first seen at leg {min(seen):2d} / median "
                   f"{int(np.median(seen)):2d} / worst {max(seen):2d}  of {n_legs}")
    return pct


@click.command()
@click.option("--n-targets", default=400, type=int)
@click.option("--seed", default=5, type=int)
def main(n_targets, seed):
    cfg = SceneConfig()
    kin = Collector(str(write_scene(cfg)), cfg=cfg, render=False)
    eye = Eye(cfg, kin.model, kin.data)
    ball_r = float(cfg.object_size[0])
    rng = np.random.default_rng(seed)
    tgts = placements(cfg, n_targets, rng)

    click.secho(f"wrist camera {eye.W}x{eye.H}, centre square {eye.side} px, "
                f"f {eye.f:.1f} px", bold=True)
    click.echo(f"  crop covers {2*math.degrees(math.atan(eye.side/2/eye.f)):.1f} "
               f"deg across\n")

    click.secho("what one static pose can see", bold=True)
    best = None
    for z in (0.22, 0.26, 0.30, 0.34):
        for pitch_deg in (35, 45, 55, 65, 75):
            for rad in (0.10, 0.14, 0.18):
                pitch = math.radians(pitch_deg)
                pos, R = tool_pose(kin, cfg, 0.0, rad, z, pitch)
                if flyable(kin, pos, pitch) is None:
                    continue
                pct = 100.0 * sum(eye.sees(pos, R, np.array([x, y, ball_r]))
                                  for x, y in tgts) / len(tgts)
                if best is None or pct > best[0]:
                    best = (pct, z, pitch_deg, rad)
    if best is None:
        click.secho("  no static pose is flyable at all", fg="red")
        return
    click.echo(f"  best single viewpoint: z {best[1]*1000:.0f} mm, "
               f"pitch {best[2]} deg, radius {best[3]*1000:.0f} mm "
               f"-> {best[0]:.1f}% of placements\n")

    click.secho("what a yaw sweep can see", bold=True)
    results = []
    for z, pitch_deg, rad in ((best[1], best[2], best[3]),
                              (0.26, 55, 0.14), (0.30, 55, 0.14),
                              (0.30, 45, 0.16), (0.34, 45, 0.16),
                              (0.30, 60, 0.12), (0.26, 45, 0.16)):
        pitch = math.radians(pitch_deg)
        for span_deg, n in ((50, 9), (70, 13), (90, 17)):
            legs = [(math.radians(a), rad, z, pitch)
                    for a in np.linspace(-span_deg / 2, span_deg / 2, n)]
            out, why = sweep(kin, cfg, eye, legs, tgts, ball_r)
            if out is None:
                continue
            _, _, first = out
            pct = report(f"z {z*1000:.0f} pitch {pitch_deg} r {rad*1000:.0f} "
                         f"span {span_deg} ({n} legs)", first, n)
            results.append((pct, z, pitch_deg, rad, span_deg, n))
    if results:
        results.sort(reverse=True)
        pct, z, pitch_deg, rad, span_deg, n = results[0]
        click.secho(f"\nbest sweep: z {z*1000:.0f} mm, pitch {pitch_deg} deg, "
                    f"radius {rad*1000:.0f} mm, {span_deg} deg in {n} legs "
                    f"-> {pct:.1f}%", bold=True, fg="green")
    kin.close()


if __name__ == "__main__":
    main()
