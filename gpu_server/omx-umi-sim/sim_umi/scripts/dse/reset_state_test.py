"""Is the canonical ResetWorld start really the same twice? (15-minute timebox test)

    source sim_umi/ros/env_overlay.sh
    python sim_umi/scripts/dse/reset_state_test.py --out <dir>

Twice: arm hold goal at HOME and gripper open goal installed (paused), ResetWorld with arm
HOME, both fingers 0.47 rad, zero velocity, ball and bin at nominal episode 0's placement,
zero twist. Then 60 ticks, one per call. Compared rep 1 vs rep 2 at the same ticks after the
reset: the joint snapshot (all 7 hinge joints: arm, gripper, the coupled finger 2 -- q and
qd), the free bodies (ball, bin: pose and twist, from the free-joint publisher), the camera
frames (raw RGB) at the captures reset + 0, 25, 50. The capture at reset + 0 is rendered
from the reset state itself -- identical by construction -- so an RGB difference there
with identical state is the renderer's.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import click
import numpy as np
from control_msgs.action import GripperCommand
from rclpy.action import ActionClient
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image, JointState

import step_audit as sa

ROOT = pathlib.Path(__file__).resolve().parents[3]


def ns(s):
    return s.sec * 1_000_000_000 + s.nanosec


@click.command()
@click.option("--out", required=True)
@click.option("--ticks", default=60)
@click.option("--different-prior", is_flag=True,
              help="rep 0 first drives the arm away (joint1 +0.6 rad, joint2 +0.3) and back to nothing; "
                   "rep 1 holds HOME -- the reset must erase the difference")
@click.option("--rep1-batch", default=1, help="rep 1 steps this many ticks per call, back to back (rep 0: one per call)")
def main(out, ticks, different_prior, rep1_batch):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=False)
    from mujoco_ros2_control_msgs.msg import FreeJointState, FreeJointStateArray
    from mujoco_ros2_control_msgs.srv import ResetWorld
    sys.path.insert(0, str(ROOT / "sim_umi/ros"))
    from collect_demos import quat_from_yaw
    spec = json.loads(str(np.load(sorted((ROOT / "sim_umi/data/demos/train").glob("episode_*.npz"))[0],
                                  allow_pickle=True)["spec"]))
    a = sa.Audit()
    grip = ActionClient(a.n, GripperCommand, "/gripper_controller/gripper_cmd")
    assert grip.wait_for_server(timeout_sec=10)
    frames, snaps, free = {}, {}, {}
    q = QoSProfile(depth=5000, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)

    def on_img(m):
        with a.lock:
            frames[ns(m.header.stamp)] = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, 3).copy()

    def on_snap(m):
        with a.lock:
            snaps[ns(m.header.stamp)] = (list(m.name), list(m.position), list(m.velocity))

    def on_free(m):
        with a.lock:
            free[ns(m.header.stamp) if m.header.stamp.sec else time.time_ns()] = [
                (e.name, [e.pose.pose.position.x, e.pose.pose.position.y, e.pose.pose.position.z,
                          e.pose.pose.orientation.x, e.pose.pose.orientation.y, e.pose.pose.orientation.z,
                          e.pose.pose.orientation.w],
                 [e.twist.twist.linear.x, e.twist.twist.linear.y, e.twist.twist.linear.z,
                  e.twist.twist.angular.x, e.twist.twist.angular.y, e.twist.twist.angular.z]) for e in m.free_joints]
    a.n.create_subscription(Image, "/wrist_camera/image_raw", on_img, q)
    a.n.create_subscription(JointState, "/wrist_camera/joint_snapshot", on_snap, q)
    a.n.create_subscription(FreeJointStateArray, "/free_joint_state_publisher/free_joint_states", on_free, q)
    time.sleep(1.0)
    reps = []
    assert a.pause(True)
    try:
        for rep in range(2):
            if different_prior:
                away = list(sa.HOME_Q)
                if rep == 0:
                    away[0] += 0.6
                    away[1] += 0.3
                a.goal([(0.3, away)])
                a.t_sim = a.now()
                for _ in range(200):
                    a.step(5, 0.0) if False else a.step(1, 0.0)
            a.goal([(0.1, sa.HOME_Q)])
            g = GripperCommand.Goal()
            g.command.position, g.command.max_effort = 0.47, 0.5
            h = a.wait(grip.send_goal_async(g))
            time.sleep(0.1)
            req = ResetWorld.Request()
            js = req.state_overrides.joint_states
            js.name = sa.ARM + ["gripper_joint_1", "gripper_joint_2"]
            js.position = list(sa.HOME_Q) + [0.47, 0.47]
            js.velocity = [0.0] * 7
            for name, xy, z, yaw in (("object", spec["object_xy"], spec["ball_r"], 0.0),
                                     ("bin", spec["bin_xy"], 0.0, spec["bin_yaw"])):
                s_ = FreeJointState()
                s_.name = name
                s_.pose.pose.position.x, s_.pose.pose.position.y, s_.pose.pose.position.z = float(xy[0]), float(xy[1]), float(z)
                (s_.pose.pose.orientation.x, s_.pose.pose.orientation.y, s_.pose.pose.orientation.z,
                 s_.pose.pose.orientation.w) = quat_from_yaw(yaw)
                req.state_overrides.free_joints.append(s_)
            r = a.wait(a.reset_c.call_async(req))
            assert r.success, r.message
            a.drain_clock()
            with a.lock:
                R = int(round(a.clock[-1][0] * 1e9))
            a.t_sim = R * 1e-9
            if rep == 1 and rep1_batch > 1:
                done = 0
                while done < ticks:
                    n = min(rep1_batch, ticks - done)
                    a.step(n, 0.0)
                    done += n
            else:
                for _ in range(ticks):
                    a.step(1, 2.0)
            time.sleep(1.0)
            with a.lock:
                F = {k - R: v for k, v in frames.items() if R - 100_000 <= k <= R + (ticks + 1) * 2_000_000}
                S = {k - R: v for k, v in snaps.items() if R - 100_000 <= k <= R + (ticks + 1) * 2_000_000}
                W = {k - R: v for k, v in free.items() if R - 100_000 <= k <= R + (ticks + 1) * 2_000_000}
            reps.append({"reset_ns": R, "F": F, "S": S, "W": W, "grip_accepted": bool(h.accepted)})
    finally:
        a.pause(False)
    A, B = reps
    rel = lambda d: {int(round(k / 2_000_000)): v for k, v in d.items()}
    FA, FB, SA, SB, WA, WB = rel(A["F"]), rel(B["F"]), rel(A["S"]), rel(B["S"]), rel(A["W"]), rel(B["W"])
    res = {"capture_ticks": (sorted(FA), sorted(FB))}
    for k in sorted(set(FA) & set(FB)):
        d = np.abs(FA[k].astype(int) - FB[k].astype(int))
        m = d.sum(-1) > 0
        ys, xs = np.nonzero(m)
        res[f"rgb_tick_{k}"] = {"changed_px": int(m.sum()), "max_abs": int(d.max()),
                                "bbox": [int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())] if len(ys) else None}
    for k in sorted(set(SA) & set(SB)):
        nA, qA, vA = SA[k]
        nB, qB, vB = SB[k]
        res[f"joints_tick_{k}"] = {"names": nA, "q_equal": qA == qB, "qd_equal": vA == vB,
                                   "max_abs_dq": max(abs(x - y) for x, y in zip(qA, qB)),
                                   "max_abs_dqd": max(abs(x - y) for x, y in zip(vA, vB)),
                                   "finger2_minus_finger1": qA[nA.index("gripper_joint_2")] - qA[nA.index("gripper_joint_1")]}
    wk = sorted(set(WA) & set(WB))
    res["free_body_ticks_common"] = wk[:10]
    # the free-joint publisher's instants differ between reps: compare the LAST message of each
    lastA, lastB = WA[max(WA)], WB[max(WB)]
    res["free_last_msg_ticks"] = (max(WA), max(WB))
    res["free_last"] = {n: {"pose_equal": pa == pb, "twist_equal": ta == tb,
                            "max_abs_dpose": max(abs(x - y) for x, y in zip(pa, pb)),
                            "max_abs_dtwist": max(abs(x - y) for x, y in zip(ta, tb))}
                        for (n, pa, ta), (_, pb, tb) in zip(lastA, lastB)}
    for k in wk[:5]:
        res[f"free_tick_{k}"] = {n: {"pose_equal": pa == pb, "twist_equal": ta == tb,
                                     "max_abs_dpose": max(abs(x - y) for x, y in zip(pa, pb)),
                                     "max_abs_dtwist": max(abs(x - y) for x, y in zip(ta, tb))}
                                 for (n, pa, ta), (_, pb, tb) in zip(WA[k], WB[k])}
    (out / "reset_state_test.json").write_text(json.dumps(res, indent=1, default=str))
    np.savez_compressed(out / "frames.npz", **{f"rep{j}_tick{k}": v for j, D in enumerate((FA, FB)) for k, v in D.items()})
    for k, v in res.items():
        print(k, v)
    a.goal([(0.5, sa.HOME_Q)])
    a.ex.shutdown()
    a.n.destroy_node()
    sa.rclpy.shutdown()


if __name__ == "__main__":
    main()
