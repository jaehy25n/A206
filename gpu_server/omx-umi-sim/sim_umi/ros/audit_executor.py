"""What happens to a chunk between the policy and the joints.

    python sim_umi/ros/audit_executor.py --boundaries 5

The policy asks for 4.84 mm of tool motion per tick, the expert's own figure,
and the arm manages 2.52. Part of that is arithmetic: action[0] is the pose the
arm is already in -- measured on the training set, 0.000034 mm from it -- and
the executor was sending it as the first trajectory point and then giving every
point one dt more than it should have, so 0.3 s of motion was being spread over
0.4 s. That accounts for a quarter. This measures where the rest goes.

At each replan boundary it records the same stretch of time five ways:

    the raw 16-step plan, in absolute tool pose
    the same after projection onto the five axes the arm has
    the joint targets the IK returned, and the tool pose their FK gives back
    the trajectory points actually sent, with their time_from_start
    the joints as they actually moved, sampled as fast as the state arrives

and, around the boundary itself, whether the previous goal finished or was
preempted, whether the controller was given the current pose as a starting
point, and whether the tool comes to a stop between one chunk and the next.
"""
import json
import math
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint

from policy_bridge import ARM, decode_action
from policy_rollout import Rollout


class Audited(Rollout):
    """A rollout that watches its own arm while it moves."""

    def send_watched(self, qs, times):
        """Send one chunk and sample the joints all the way through it."""
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = ARM
        t, pts = 0.0, []
        for q, dt in zip(qs, times):
            t += dt
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start.sec = int(t)
            pt.time_from_start.nanosec = int((t % 1) * 1e9)
            traj.trajectory.points.append(pt)
            pts.append({"time_from_start_s": round(t, 4),
                        "q_deg": np.degrees(q).round(4).tolist(),
                        "has_velocity": bool(len(pt.velocities)),
                        "has_acceleration": bool(len(pt.accelerations))})
        fa = self.arm.send_goal_async(traj)
        rclpy.spin_until_future_complete(self, fa, timeout_sec=5.0)
        h = fa.result()
        if h is None or not h.accepted:
            return False, pts, [], {"accepted": False}
        rf = h.get_result_async()
        t0, track = time.time(), []
        last = None
        while time.time() - t0 < t + 4.0:
            rclpy.spin_once(self, timeout_sec=0.002)
            if self.state is not None and self.state is not last:
                last = self.state
                q = self.q_now()
                ee, _ = self.ee_now()
                track.append({
                    "stamp_s": round(self.state.header.stamp.sec
                                     + self.state.header.stamp.nanosec * 1e-9, 5),
                    "q_deg": np.degrees(q).round(4).tolist(),
                    "ee_mm": (ee * 1000).round(4).tolist()})
            if rf.done():
                break
        res = rf.result()
        info = {"accepted": True,
                "duration_commanded_s": round(t, 4),
                "duration_actual_s": round(time.time() - t0, 4),
                "error_code": (None if res is None else int(res.result.error_code)),
                "samples": len(track)}
        return (res is not None and res.result.error_code == 0), pts, track, info


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--from-demos", default="train")
@click.option("--episode", default=0, type=int)
@click.option("--exec-steps", default=4, type=int)
@click.option("--boundaries", default=5, type=int,
              help="how many consecutive replans to keep once APPROACH begins")
@click.option("--max-ticks", default=400, type=int)
@click.option("--out", default=None)
def main(socket_path, from_demos, episode, exec_steps, boundaries, max_ticks,
         out):
    rclpy.init()
    b = Audited(socket_path)
    b.spin(1.5)
    cfg = b.cfg
    dt = b.meta["action_dt_s"]
    horizon = b.meta["action_horizon"]
    p = sorted((SIM / "data" / "demos" / from_demos).glob("episode_*.npz"))[episode]
    ep = json.loads(str(np.load(p, allow_pickle=True)["spec"]))
    r = float(ep["ball_r"])
    if not b.place(ep["object_xy"], r, ep["bin_xy"], ep["bin_yaw"]):
        raise click.ClickException("could not place the bodies")
    ok, info = b.deterministic_reset()
    if not ok:
        raise click.ClickException(f"reset failed: {info}")
    click.secho(f"{p.name}: ball {np.round(np.array(ep['object_xy'])*1000,1)} mm, "
                f"executing {exec_steps} of {horizon} per replan", bold=True)

    kept, steps, seen_ball = [], 0, False
    while steps < max_ticks and len(kept) < boundaries:
        frames = []
        try:
            for k in range(b.meta["obs_horizon"]):
                f, _ = b.observe()
                frames.append(f)
                if k + 1 < b.meta["obs_horizon"]:
                    b.spin(dt)
        except RuntimeError as e:
            click.secho(f"  {e}", fg="red")
            break
        obs_stamp = float(b.frame_stamp)
        act, _ = b.infer(frames)
        p0, R0 = b.ee_now()
        ball_seen = b.target_visible("object")

        raw, proj, iks = [], [], []
        for k in range(horizon):
            pk, Rk, gk = decode_action(act[0, k], p0, R0)
            raw.append({"k": k, "t_s": round(obs_stamp + k * dt, 4),
                        "p_mm": (pk * 1000).round(4).tolist(),
                        "g_mm": round(float(gk) * 1000, 3)})
        qs, times, widths, refused = [], [], [], None
        for k in range(min(exec_steps, horizon)):
            pk, Rk, gk = decode_action(act[0, k], p0, R0)
            q, p_got, R_got, err = b.project_5dof(pk, Rk)
            proj.append({"k": k, "p_mm": (p_got * 1000).round(4).tolist(),
                         "moved_by_projection_mm": round(
                             float(np.linalg.norm(p_got - pk)) * 1000, 4),
                         "ik_pos_err_mm": round(err["pos_err_mm"], 5)})
            if err["pos_err_mm"] > 2.0:
                refused = k
                break
            d = b.kin._ik
            d.qpos[:] = b.kin.data.qpos
            for a, v in zip(b.kin.arm_qadr, q):
                d.qpos[a] = v
            import mujoco
            mujoco.mj_kinematics(b.kin.model, d)
            fk = d.site_xpos[b.kin.tcp_sid].copy()
            iks.append({"k": k, "q_deg": np.degrees(q).round(4).tolist(),
                        "fk_mm": (fk * 1000).round(4).tolist()})
            qs.append(q)
            widths.append(float(np.clip(gk, b.kin._width_tab.min(),
                                        b.kin._width_tab.max())))
            times.append(dt)
        if not qs:
            b.spin(dt)
            continue
        theta = b.jaw_async(widths[-1])
        good, pts, track, info = b.send_watched(qs, times)
        steps += len(qs)
        row = {"obs_stamp_s": round(obs_stamp, 4), "tick": steps,
               "ball_visible": ball_seen,
               "ee_at_obs_mm": (p0 * 1000).round(4).tolist(),
               "raw_plan": raw, "projected": proj, "ik": iks,
               "sent": pts, "actual": track, "goal": info,
               "jaw_cmd_mm": round(widths[-1] * 1000, 2),
               "jaw_gt_mm": round(b.jaw_now_gt() * 1000, 2),
               "ik_refused_at_k": refused}
        if ball_seen:
            seen_ball = True
        if seen_ball:
            kept.append(row)
        click.echo(f"  tick {steps:4d}  ball {'Y' if ball_seen else '.'}  "
                   f"commanded {info['duration_commanded_s']}s took "
                   f"{info['duration_actual_s']}s  {info['samples']} samples  "
                   f"{'kept' if seen_ball else 'waiting for the ball'}")
    out = out or str(SIM / "outputs" / "executor_audit.json")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(
        {"exec_steps": exec_steps, "dt": dt, "horizon": horizon,
         "episode": ep, "boundaries": kept}, indent=1))
    click.secho(f"\nwrote {len(kept)} boundaries to {out}", bold=True)
    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
