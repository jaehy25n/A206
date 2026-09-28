"""The policy driving the arm, start to finish, with nothing scripted.

    python sim_umi/ros/policy_rollout.py --episodes 5 --from-demos train

policy_bridge.py closes one loop and prints every number in it. This runs the
loop until the task is done or the clock runs out, and answers a different
question: does the trained checkpoint actually pick the ball up and put it in
the bin, under the conditions it was trained on?

Nothing scripted is mixed in. The arm is put at HOME and the bodies are placed
-- that is the reset, not the demonstration -- and from there every joint
command comes from the policy's own output, decoded through the handoff
contract and projected onto the five axes the arm has. The simulator's true
ball pose is read only to say afterwards whether the ball ended up in the bin.

The projection correction is the other thing measured here. The policy was
trained on a 6-DoF action and the arm has five, so every action is moved to
the nearest pose the arm can hold. How far it has to move is the evidence for
whether that damage was taken out at the data stage or is still being paid at
run time.
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
from control_msgs.action import FollowJointTrajectory, GripperCommand
from trajectory_msgs.msg import JointTrajectoryPoint

import mujoco  # noqa: E402
import scene_objects  # noqa: E402
from policy_bridge import ARM, Bridge, decode_action
from rolling_executor import GraspLatch, RollingExecutor  # noqa: E402
from collect_demos import (HOME_Q, MAX_JOINT_VEL, depth_for,  # noqa: E402
                           quat_from_yaw)

#: One pose every reset passes through, so the last leg to HOME is
#: always the same one. The centre of the scan arc: azimuth 0 at
#: radius 160 mm, height 260 mm, nose 45 degrees down -- 42 degrees
#: of base rotation from HOME, and reachable from the whole arc.
PRE_HOME_Q = np.radians([-0.535, -26.496, -25.708, 97.204, 0.0])


class Rollout(Bridge):
    """A bridge that can also reset the scene and judge the result."""

    def __init__(self, sock_path):
        super().__init__(sock_path)
        from mujoco_ros2_control_msgs.msg import FreeJointState, FreeJointStateArray
        from mujoco_ros2_control_msgs.srv import SetFreeJointState
        self.FreeJointState = FreeJointState
        self.SetFreeJointState = SetFreeJointState
        self.free = None
        self._seg = None
        self.create_subscription(
            FreeJointStateArray,
            "/free_joint_state_publisher/free_joint_states",
            lambda m: setattr(self, "free", m), 1)
        self.setter = self.create_client(
            SetFreeJointState, "/mujoco_ros2_control_node/set_free_joint_state")
        assert self.setter.wait_for_service(timeout_sec=30)

    # ------------------------------------------------------------- resetting --
    def place(self, obj_xy, obj_z, bin_xy, bin_yaw):
        req = self.SetFreeJointState.Request()
        for name, xy, z, yaw in (("object", obj_xy, obj_z, 0.0),
                                 ("bin", bin_xy, 0.0, bin_yaw)):
            s = self.FreeJointState()
            s.name = name
            s.pose.pose.position.x = float(xy[0])
            s.pose.pose.position.y = float(xy[1])
            s.pose.pose.position.z = float(z)
            (s.pose.pose.orientation.x, s.pose.pose.orientation.y,
             s.pose.pose.orientation.z, s.pose.pose.orientation.w) = quat_from_yaw(yaw)
            req.free_joints.append(s)
        fut = self.setter.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10)
        r = fut.result()
        return r is not None and r.success

    def go_home(self):
        q0 = self.q_now()
        n = max(2, int(math.ceil(float(np.abs(HOME_Q - q0).max()) / math.radians(10))))
        qs = [q0 + (HOME_Q - q0) * (k + 1) / n for k in range(n)]
        times, prev = [], q0
        for q in qs:
            times.append(max(0.20, float(np.abs(q - prev).max()) / MAX_JOINT_VEL))
            prev = q
        self.open_jaw()
        if not self.send_arm(qs, times):
            return False
        for _ in range(20):
            self.spin(0.05)
        return True

    def settled(self, tol_q_deg=0.01, tol_ee_mm=0.05, tol_jaw_mm=0.02,
                window=8, dwell=0.6, timeout=8.0):
        """Wait until the arm has stopped, and say whether it did.

        The command is already being held; this only watches. What counts as
        stopped is that over a window of samples the joints, the tool pose and
        the jaw all stay inside a band, and that the window is at least a
        fraction of a second long -- one quiet sample is not stillness.
        """
        qs, ees, jaws, t0 = [], [], [], time.time()
        while time.time() - t0 < timeout:
            self.spin(0.05)
            if self.state is None:
                continue
            q = self.q_now()
            ee, _ = self.ee_now()
            qs.append(q)
            ees.append(ee)
            jaws.append(self.jaw_now_gt())
            if len(qs) < window or time.time() - t0 < dwell:
                continue
            Q = np.array(qs[-window:])
            E = np.array(ees[-window:])
            J = np.array(jaws[-window:])
            if (np.degrees(np.ptp(Q, 0)).max() < tol_q_deg
                    and (np.ptp(E, 0).max() * 1000) < tol_ee_mm
                    and (np.ptp(J) * 1000) < tol_jaw_mm):
                return True, {"seconds": round(time.time() - t0, 2),
                              "q_band_deg": float(np.degrees(np.ptp(Q, 0)).max()),
                              "ee_band_mm": float(np.ptp(E, 0).max() * 1000),
                              "jaw_band_mm": float(np.ptp(J) * 1000)}
        Q = np.array(qs[-window:]) if len(qs) >= window else np.array(qs)
        return False, {"seconds": round(time.time() - t0, 2),
                       "q_band_deg": float(np.degrees(np.ptp(Q, 0)).max())
                       if len(Q) > 1 else float("nan")}

    def leg(self, q_from, q_to, step_deg=10.0, min_time=0.20):
        """A joint-space leg with waypoints and timing fixed by its ENDS.

        Timing taken from the measured pose would make the last leg of a reset
        depend on where the arm happened to be, which is the thing a reset is
        supposed to remove.
        """
        q_from = np.asarray(q_from, float)
        q_to = np.asarray(q_to, float)
        n = max(2, int(math.ceil(float(np.abs(q_to - q_from).max())
                                 / math.radians(step_deg))))
        qs = [q_from + (q_to - q_from) * (k + 1) / n for k in range(n)]
        times, prev = [], q_from
        for q in qs:
            times.append(max(min_time,
                             float(np.abs(q - prev).max()) / MAX_JOINT_VEL))
            prev = q
        return qs, times

    def deterministic_reset(self):
        """Arrive at HOME the same way every time, and prove it has stopped.

        Interpolating to HOME from wherever the arm happens to be gives a
        different approach every run, and the pose it settles at follows the
        approach: three resets measured 0.15 degrees apart at joint 1 and
        0.46 mm apart at the tool, which is enough to change the picture and
        with it everything downstream. So every reset passes through one fixed
        pose, and the leg from there to HOME is the same waypoints at the same
        times whatever came before. Nothing about the controller changes.
        """
        report = {}
        self.open_jaw()
        # 1. to the fixed waypoint, by whatever route is needed from here
        qs, times = self.leg(self.q_now(), PRE_HOME_Q)
        if not self.send_arm(qs, times):
            return False, {"stage": "to PRE_HOME", "why": "controller refused"}
        ok, info = self.settled()
        report["pre_home"] = info
        if not ok:
            return False, {"stage": "settle at PRE_HOME", **info}
        report["pre_home_q_deg"] = np.degrees(self.q_now()).round(4).tolist()
        # 2. the same leg to HOME every time: ends fixed, so waypoints and
        #    times are fixed too
        qs, times = self.leg(PRE_HOME_Q, HOME_Q)
        if not self.send_arm(qs, times):
            return False, {"stage": "to HOME", "why": "controller refused"}
        # 3. hold the command and wait for it to be still
        ok, info = self.settled()
        report["home"] = info
        report["home_q_deg"] = np.degrees(self.q_now()).round(4).tolist()
        if not ok:
            return False, {"stage": "settle at HOME", **info}
        return True, report

    def open_jaw(self):
        g = GripperCommand.Goal()
        g.command.position = float(self.kin.grip_hi)
        g.command.max_effort = 0.5
        fut = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        h = fut.result()
        if h is not None and h.accepted:
            rf = h.get_result_async()
            rclpy.spin_until_future_complete(self, rf, timeout_sec=10)

    def send_arm(self, qs, times):
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = ARM
        t = 0.0
        for q, dt in zip(qs, times):
            t += dt
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start.sec = int(t)
            pt.time_from_start.nanosec = int((t % 1) * 1e9)
            traj.trajectory.points.append(pt)
        fa = self.arm.send_goal_async(traj)
        rclpy.spin_until_future_complete(self, fa, timeout_sec=5.0)
        h = fa.result()
        if h is None or not h.accepted:
            return False
        rf = h.get_result_async()
        t0 = time.time()
        while time.time() - t0 < t + 6.0:
            rclpy.spin_once(self, timeout_sec=0.005)
            if rf.done():
                break
        res = rf.result()
        return res is not None and res.result.error_code == 0

    def jaw_async(self, width):
        theta = float(np.interp(width, self.kin._width_tab, self.kin._theta_tab))
        g = GripperCommand.Goal()
        g.command.position = theta
        g.command.max_effort = 0.5
        self.grip.send_goal_async(g)
        return theta

    def target_visible(self, name, min_px=12):
        """Evaluation only: is the thing inside the square the policy is given?

        Rendered from the kinematics mirror and never fed to the policy. It is
        here so a rollout can be read -- whether the arm searched, found the
        ball and only then went for it -- which the policy's own output cannot
        say on its own.
        """
        if self._seg is None:
            W, H = self.cfg.wrist_cam_resolution
            self._seg = mujoco.Renderer(self.kin.model, height=H, width=W)
            self._seg.enable_segmentation_rendering()
            self._crop = ((W - min(W, H)) // 2, (W - min(W, H)) // 2 + min(W, H))
            self._gids = {}
            for n in ("object", "bin"):
                bid = mujoco.mj_name2id(self.kin.model, mujoco.mjtObj.mjOBJ_BODY, n)
                self._gids[n] = set(range(
                    self.kin.model.body_geomadr[bid],
                    self.kin.model.body_geomadr[bid]
                    + self.kin.model.body_geomnum[bid]))
        self.pose_mirror()
        d = self.kin.data
        self._seg.update_scene(d, camera="wrist")
        seg = self._seg.render()[:, :, 0]
        x0, x1 = self._crop
        return bool(np.isin(seg[:, x0:x1], list(self._gids[name])).sum() >= min_px)

    def pose_mirror(self):
        """Put the kinematics copy where the plant is, bodies included.

        Evaluation only. The arm from the measured joints, the ball and bin
        from the free-joint publisher -- which is the ground truth the policy
        is never given, and is why this is used for looking and scoring and
        nothing else.
        """
        k, d = self.kin, self.kin.data
        names = list(self.state.name)
        for adr, j in zip(k.arm_qadr, ARM):
            d.qpos[adr] = self.state.position[names.index(j)]
        if "gripper_joint_1" in names:
            g = self.state.position[names.index("gripper_joint_1")]
            for jid in range(k.model.njnt):
                nm = mujoco.mj_id2name(k.model, mujoco.mjtObj.mjOBJ_JOINT, jid)
                if nm and nm.startswith("gripper_joint"):
                    d.qpos[k.model.jnt_qposadr[jid]] = g
        for nm, adr in (("object", k.obj_qadr), ("bin", k.bin_qadr)):
            xyz = self.body_xyz(nm)
            if xyz is not None:
                d.qpos[adr:adr + 3] = xyz
        mujoco.mj_forward(k.model, d)

    # -------------------------------------------------------------- judging --
    def body_pose(self, name):
        """Position (mm) and quaternion (x, y, z, w) of a free body, from the
        last free-joint message. A lookup, no rendering: safe in the loop."""
        if self.free is None:
            return None
        for e in self.free.free_joints:
            if e.name == name:
                p, o = e.pose.pose.position, e.pose.pose.orientation
                return {"xyz_mm": [round(p.x * 1000, 3), round(p.y * 1000, 3), round(p.z * 1000, 3)],
                        "quat_xyzw": [round(o.x, 6), round(o.y, 6), round(o.z, 6), round(o.w, 6)]}
        return None

    def body_xyz(self, name):
        if self.free is None:
            return None
        for e in self.free.free_joints:
            if e.name == name:
                p = e.pose.pose.position
                return np.array([p.x, p.y, p.z])
        return None


class Recorder:
    """The wrist frame the policy is given, beside a view of what happened.

    The right pane is the picture that actually went into the encoder, after
    the magenta patches are painted out -- the real arm has no patches, so the
    policy must never see them. The left pane is a debug camera on the
    kinematics copy, posed from the measured joints and the true ball and bin.
    That pane is ground truth and exists so a failure can be watched; nothing
    in it reaches the policy.
    """

    W, H = 640, 480

    def __init__(self, bridge, path, index):
        import cv2
        self.cv2 = cv2
        self.b = bridge
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.file = self.path / f"rollout_{index}.mp4"
        cam = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(cam)
        cam.azimuth, cam.elevation, cam.distance = 110.0, -25.0, 0.95
        cam.lookat[:] = (0.0, -0.18, 0.06)
        self.cam = cam
        self.ren = mujoco.Renderer(bridge.kin.model, height=self.H, width=self.W)
        self.vw = None
        self.last = None
        self.n = 0

    def maybe(self, ex, stage, ball, ball_r):
        if self.b.frame_stamp == self.last or self.b.frame is None:
            return
        self.last = self.b.frame_stamp
        from gripper_vision import mask_magenta
        cv2 = self.cv2
        self.b.pose_mirror()
        self.ren.update_scene(self.b.kin.data, self.cam)
        left = self.ren.render().copy()
        # the centre square the contract crops to, at the resolution the
        # encoder is given, then upscaled for viewing. Showing the whole
        # 320x180 frame instead would put things on screen that never reach
        # the policy -- the crop throws away the outer thirds.
        masked = mask_magenta(self.b.frame, self.b.tip_cfg)
        h, w = masked.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        right = cv2.resize(
            cv2.resize(masked[y0:y0 + side, x0:x0 + side], (224, 224),
                       interpolation=cv2.INTER_AREA),
            (self.H, self.H), interpolation=cv2.INTER_NEAREST)
        w_obs, ok = self.b.width_sample()
        lat = ex.latch is not None and ex.latch.latched
        p, R = self.b.ee_now()
        pit = math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))
        lift = None
        if ex.plans and ex.plans[-1].get("plan_abs"):
            z = [x["p"][2] for x in ex.plans[-1]["plan_abs"]]
            lift = next((j for j in range(1, len(z)) if z[j] - z[j - 1] > 0.3), None)
        gap = (np.linalg.norm(p - ball) * 1000) if ball is not None else float("nan")
        _label(left, [
            f"tick {ex.ticks:3d}   {stage}",
            f"tool  z {p[2]*1000:6.1f} mm   pitch {pit:6.1f} deg"
            f"   (demos 7.9..46.3)",
            f"jaw   seen {('%.1f' % (w_obs*1000)) if ok else ' -- '} mm"
            f"   told {('%.1f' % (ex.jaw_commanded*1000)) if ex.jaw_commanded else ' -- '}"
            f"{'   HELD' if lat else ''}",
            f"ball  {gap:6.1f} mm away"
            + (f"   z {ball[2]*1000:5.1f} mm" if ball is not None else ""),
            f"plan  rises at step {lift if lift is not None else '--'} of 16"
            f"   (only 3..10 is ever sent)"])
        _label(right, ["what the policy sees: the 224 crop, upscaled"], (10, 22))
        frame = np.hstack([left, right])
        if self.vw is None:
            self.vw = cv2.VideoWriter(str(self.file),
                                      cv2.VideoWriter_fourcc(*"mp4v"), 20,
                                      (frame.shape[1], frame.shape[0]))
        self.vw.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        self.n += 1

    def close(self):
        if self.vw is not None:
            self.vw.release()
            click.echo(f"      wrote {self.file} ({self.n} frames)")
        self.ren.close()


def _label(img, lines, org=(10, 22)):
    import cv2
    for i, t in enumerate(lines):
        for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
            cv2.putText(img, t, (org[0], org[1] + 21 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, th, cv2.LINE_AA)


#: how far a rollout got, in the order the task goes
ORDER = ["SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP", "LIFT", "SEARCH_BIN",
         "TRANSPORT", "PLACE", "AFTER_RELEASE"]


def in_bin(cfg, ball, bin_xy, bin_yaw):
    c, s = math.cos(-bin_yaw), math.sin(-bin_yaw)
    d = ball[:2] - np.asarray(bin_xy)
    local = np.array([c * d[0] - s * d[1], s * d[0] + c * d[1]])
    return bool(abs(local[0]) < cfg.bin_inner / 2
                and abs(local[1]) < cfg.bin_inner / 2
                and 0.005 < ball[2] < cfg.bin_outer), local


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--from-demos", default="train",
              help="take the ball and bin placements from this split, so the "
                   "rollout is under a condition the policy was trained on")
@click.option("--episodes", default=5, type=int)
@click.option("--start-perturbed/--start-home", default=False,
              help="put the arm at the episode's own perturbed pre-grasp pose "
                   "before handing over, instead of starting from HOME. This "
                   "is what the corrective set was built for: the question is "
                   "not whether the policy can approach, it is whether it can "
                   "come back from somewhere the clean demonstrations never "
                   "went.")
@click.option("--video", default=None,
              help="write an mp4 per rollout: the wrist frame the policy is "
                   "given beside a third-person view. Rendering costs loop "
                   "time, so a recorded run is not the same run as one "
                   "without it -- this closed loop is that sensitive.")
@click.option("--latch-require-intent/--latch-no-intent", default=False,
              help="also require the policy to be asking for narrower than "
                   "the fingers have got")
@click.option("--latch/--no-latch", default=False,
              help="once the camera says the jaw has actually shut on "
                   "something, hold the gripper command there. Diagnostic: it "
                   "changes what the gripper is told, never what the policy "
                   "is shown.")
@click.option("--only", default=None,
              help="run just these placements, comma separated, by index")
@click.option("--horizon-steps", default=8, type=int,
              help="how many future waypoints to keep in flight. The chunk has to outlast inference, which measured 0.13 to 0.58 s, or the arm stands still between plans: 8 of them is 0.8 s.")
@click.option("--max-ticks", default=600, type=int,
              help="executed actions, which at 0.1 s each is the policy's own "
                   "clock. The experts run 295 to 369 ticks, p95 361, so 600 "
                   "leaves room to be slow without running forever. The wall "
                   "clock is not the task's clock: a 60 second wall limit cut "
                   "every rollout off at 234 to 271 ticks, shorter than the "
                   "shortest demonstration.")
@click.option("--wall-limit", default=900.0, type=float,
              help="a safety net only; if it fires the rollout says so")
@click.option("--out", default=None)
@click.option("--frames-dir", default=None,
              help="where the frames the policy was given are saved, per episode, "
                   "lossless (default: <out stem>_frames next to --out)")
def main(socket_path, from_demos, episodes, start_perturbed, video,
         latch_require_intent, latch, only, horizon_steps, max_ticks,
         wall_limit, out, frames_dir):
    rclpy.init()
    b = Rollout(socket_path)
    b.spin(1.5)
    cfg = b.cfg
    dt = b.meta["action_dt_s"]
    horizon = b.meta["action_horizon"]
    paths = sorted((SIM / "data" / "demos" / from_demos).glob("episode_*.npz"))
    pick = ([int(x) for x in only.split(",")] if only
            else list(range(min(episodes, len(paths)))))
    specs = [(k, json.loads(str(np.load(paths[k], allow_pickle=True)["spec"])))
             for k in pick]
    if not specs:
        raise click.ClickException(f"no episodes under data/demos/{from_demos}")
    click.secho(f"{len(specs)} rollouts from {from_demos} placements   "
                f"{horizon_steps} future waypoints in flight, rolling   "
                f"up to {max_ticks} ticks = {max_ticks*dt:.0f} s of policy time",
                bold=True)

    rows, infra_failed = [], []
    frames_path = pathlib.Path(frames_dir) if frames_dir else (
        pathlib.Path(out).with_name(pathlib.Path(out).stem + "_frames") if out else None)
    if frames_path is not None:
        frames_path.mkdir(parents=True, exist_ok=True)
    click.secho(f"image geometry {b.rgb_geometry}   server "
                f"{(b.server_meta or {}).get('checkpoint', 'no sidecar (G0 server)')}", bold=True)
    for i, ep in specs:
        r = float(ep["ball_r"])

        def joint_clock():
            st = b.state
            return None if st is None else st.header.stamp.sec + st.header.stamp.nanosec * 1e-9

        def bodies_where_placed(ball_tol_mm=2.0, tol_mm=2.0, tol_yaw_deg=1.0,
                                still_mm=0.2):
            """Both free bodies at the pose the placement asked for, and at
            rest. Read from the free-joint publisher -- ground truth, used
            only to decide whether a start is valid, never given to the
            policy. Only messages that arrived after this call are used."""
            b.free = None
            t0 = time.time()
            while b.free is None and time.time() - t0 < 3.0:
                b.spin(0.05)
            if b.free is None:
                return False, {"why": "no free-joint state"}
            b.spin(0.3)
            a = {nm: b.body_xyz(nm) for nm in ("object", "bin")}
            b.spin(0.3)
            c = {nm: b.body_xyz(nm) for nm in ("object", "bin")}
            want = {"object": np.array([ep["object_xy"][0], ep["object_xy"][1], r]),
                    "bin": np.array([ep["bin_xy"][0], ep["bin_xy"][1], 0.0])}
            rep, why = {}, []
            for nm in ("object", "bin"):
                if a[nm] is None or c[nm] is None:
                    why.append(f"{nm} missing")
                    continue
                dev = float(np.linalg.norm(c[nm] - want[nm]) * 1000)
                moved = float(np.linalg.norm(c[nm] - a[nm]) * 1000)
                rep[nm] = {"xyz_mm": (c[nm] * 1000).round(2).tolist(),
                           "dev_mm": round(dev, 3), "moved_0.3s_mm": round(moved, 3)}
                if dev > (ball_tol_mm if nm == "object" else tol_mm):
                    why.append(f"{nm} {dev:.1f} mm from its placement")
                if moved > still_mm:
                    why.append(f"{nm} still moving ({moved:.2f} mm in 0.3 s)")
            for e in b.free.free_joints:
                if e.name == "bin":
                    o = e.pose.pose.orientation
                    yaw = math.degrees(math.atan2(2 * (o.w * o.z + o.x * o.y),
                                                  1 - 2 * (o.y * o.y + o.z * o.z)))
                    dyaw = (yaw - math.degrees(ep["bin_yaw"]) + 180) % 360 - 180
                    rep.setdefault("bin", {})["yaw_dev_deg"] = round(dyaw, 3)
                    if abs(dyaw) > tol_yaw_deg:
                        why.append(f"bin yaw {dyaw:+.1f} deg off")
            rep["why"] = "; ".join(why)
            return not why, rep

        def prepare_start():
            """Everything before the policy's first observation. A failure in
            here is infrastructure, never a task outcome: the policy has not
            been asked anything yet."""
            info = {}
            # The arm goes home FIRST, with the bodies wherever the last
            # episode left them, and only then are the bodies placed. Placing
            # first let the arm, travelling back from where the previous
            # rollout ended, sweep through the ball or bin it had just been
            # given: nominal episode 3 began with its ball 158 to 397 mm from
            # its placement in every job, and episode 1's bin was pushed into
            # the camera's view. The collector has always homed before placing.
            ok_reset, rinfo = b.deterministic_reset()
            if not ok_reset:
                return False, {"why": f"reset failed: {rinfo}"}
            if not b.place(ep["object_xy"], r, ep["bin_xy"], ep["bin_yaw"]):
                return False, {"why": "could not place the bodies"}
            # Keep MoveIt's idea of the bin in step with the plant's, even
            # though the rollout projects rather than plans.
            try:
                scene_objects.apply(b, cfg, timeout=8.0,
                                    bin_xy=ep["bin_xy"], bin_yaw=ep["bin_yaw"])
            except RuntimeError:
                info["planning_scene"] = "apply failed"
            ok_b, binfo = bodies_where_placed()
            info["bodies_after_place"] = binfo
            if not ok_b:
                return False, {**info, "why": f"bodies not where placed: {binfo['why']}"}
            info["perturbed"] = None
            if start_perturbed and "perturb_pitch_deg" in ep:
                z_re = r + ep["standoff"] * ep["reentry_frac"]
                pp = math.radians(ep["perturb_pitch_deg"])
                pdep = depth_for(b.kin, ep["object_xy"], r, z_re, pp,
                                 ep["perturb_tool_depth_mm"], ep["depth"])
                if pdep is None:
                    return False, {"why": "the perturbed pose is unreachable"}
                p_w = b.kin.grasp_tcp_target(ep["object_xy"], z_re, pp, pdep)
                q_w, ep_err, _, _ = b.kin.solve_ik_planar(p_w, pp, iters=60)
                if ep_err > 0.002:
                    return False, {"why": f"perturbed pose misses by {ep_err*1000:.1f} mm"}
                qs, times = b.leg(b.q_now(), q_w)
                if not b.send_arm(qs, times):
                    return False, {"why": "could not reach the perturbed pose"}
                ok_set, _ = b.settled()
                pit_now = math.degrees(math.asin(max(-1.0, min(1.0,
                    -b.ee_now()[1][:, 1][2]))))
                info["perturbed"] = {"asked_pitch": ep["perturb_pitch_deg"],
                                     "asked_depth_mm": ep["perturb_tool_depth_mm"],
                                     "realized_pitch": round(pit_now, 2),
                                     "settled": bool(ok_set)}
                # The move to the perturbed pose nudges the ball, and so did
                # every demonstration that taught it: the v2_val demos had it
                # 2.4 to 16.0 mm off its placement at this very pose, the clean
                # ones 3.1 to 8.9 mm before the grasp. So the nudge is part of
                # the perturbed start and is recorded, not refused; only a
                # knock well past anything demonstrated, a ball still rolling,
                # or a bin that moved makes the start invalid.
                ok_b, binfo = bodies_where_placed(ball_tol_mm=25.0)
                info["bodies_after_perturb"] = binfo
                if not ok_b:
                    return False, {**info, "why": f"bodies disturbed by the move to the "
                                                  f"perturbed pose: {binfo['why']}"}
            # Fresh-observation gate. The first observation has to be a
            # picture taken AFTER the start pose was reached and settled, and
            # a joint state from after that too -- not whatever frame
            # happened to be buffered from the end of the previous rollout --
            # and the magenta tips have to be readable on it. Nothing is
            # substituted if they are not; the start is simply not ready.
            t_ready = joint_clock()
            f0 = b.frame_stamp
            info.update({"t_ready": t_ready, "frame_stamp_at_gate": f0,
                         "frame_age_at_gate_s": (None if (t_ready is None or f0 is None)
                                                 else round(t_ready - f0, 4))})
            new_frames, last, t0 = 0, f0, time.time()
            while time.time() - t0 < 5.0:
                b.spin(0.05)
                if b.frame_stamp != last:
                    new_frames += 1
                    last = b.frame_stamp
                js = joint_clock()
                if (b.frame_stamp is not None and t_ready is not None
                        and b.frame_stamp > t_ready and js is not None and js > t_ready):
                    w_chk, ok_chk = b.width_sample()
                    if ok_chk:
                        info.update({"fresh": True, "new_frames": new_frames,
                                     "wait_s": round(time.time() - t0, 3),
                                     "width_mm": round(w_chk * 1000, 3)})
                        return True, info
            info.update({"fresh": False, "why": "no fresh frame with readable tips in 5 s",
                         "new_frames": new_frames, "wait_s": round(time.time() - t0, 3),
                         "last_frame_after_ready": bool(b.frame_stamp is not None
                                                        and t_ready is not None
                                                        and b.frame_stamp > t_ready),
                         # root-cause evidence: what the camera was actually
                         # looking at, and the jaw and arm it was looking at
                         "jaw_gt_mm": round(b.jaw_now_gt() * 1000, 3),
                         "q_deg": np.degrees(b.q_now()).round(3).tolist(),
                         "object_in_crop": bool(b.target_visible("object")),
                         "bin_in_crop": bool(b.target_visible("bin"))})
            try:
                import cv2
                shot = pathlib.Path(out or ".").parent / (
                    f"{pathlib.Path(out).stem if out else 'rollout'}_notready_ep{i}_"
                    f"{len(infra_log) + 1}.png")
                if b.frame is not None:
                    cv2.imwrite(str(shot), cv2.cvtColor(b.frame, cv2.COLOR_RGB2BGR))
                    info["frame_file"] = shot.name
            except Exception as ex_:
                info["frame_file_error"] = str(ex_)
            return False, info

        infra_log, ok_start = [], False
        for attempt in range(1, 4):
            ok_start, sinfo = prepare_start()
            infra_log.append(sinfo)
            if ok_start:
                break
            click.secho(f"  [{i}] start attempt {attempt} not ready (infrastructure): "
                        f"{sinfo.get('why')}  new frames {sinfo.get('new_frames')}  "
                        f"frame age at gate {sinfo.get('frame_age_at_gate_s')}", fg="yellow")
        if not ok_start:
            import cv2
            # named after the job, so one job's evidence cannot replace another's
            shot = pathlib.Path(out or ".").parent / (
                f"{pathlib.Path(out).stem if out else 'rollout'}_infra_fail_ep{i}.png")
            if b.frame is not None:
                cv2.imwrite(str(shot), cv2.cvtColor(b.frame, cv2.COLOR_RGB2BGR))
            click.secho(f"  [{i}] INFRA FAILURE after {len(infra_log)} start attempts; "
                        f"not counted as a task outcome", fg="red")
            infra_failed.append({"episode": i, "infra_log": infra_log,
                                 "frame": shot.name})
            continue
        perturbed_ok = infra_log[-1].get("perturbed")
        if perturbed_ok:
            click.echo(f"      placed at pitch {perturbed_ok['realized_pitch']:.2f} deg "
                       f"(asked {perturbed_ok['asked_pitch']:.1f}), depth asked "
                       f"{perturbed_ok['asked_depth_mm']:+.1f} mm")
        if len(infra_log) > 1:
            click.echo(f"      ready after {len(infra_log)-1} infrastructure retries")
        b.start_pose = None
        b.last_width = None
        b.frame_log = {}        # only frames the policy is given in THIS rollout
        obs_wait = sum(float(x.get("wait_s", 0.0)) for x in infra_log)
        corr_p, corr_r, ik_fail, steps = [], [], 0, 0
        chunks_tried, consecutive = 0, 0
        ik_attempts, ik_refusals = 0, 0
        stage_ticks, reached, ever_held = {}, [], False
        stage_events = []
        dropped, was_released = [], False
        stopped = "ran out of ticks"
        trace = []
        t0 = time.time()
        grasped_once = False
        # Rolling horizon: a goal stays in flight while the next prediction
        # is computed. Waypoints carry the absolute time the contract gives
        # them -- obs_t + k*dt -- and anything already past when the answer
        # arrives is dropped, action[0] always among it, because action[0] is
        # the observation's own pose.
        ee_track, last_state = [], None
        vid = Recorder(b, video, i) if video else None
        ex = RollingExecutor(b, horizon_steps=horizon_steps, dt=dt)
        if latch:
            ex.latch = GraspLatch(require_intent=latch_require_intent)
        last_frame = None
        ex.start_inference()
        seen_ticks = 0
        while ex.ticks < max_ticks and time.time() - t0 < wall_limit:
            rclpy.spin_once(b, timeout_sec=0.002)
            ex.retire()
            # how many action ticks actually went by since the last pass. The
            # loop spins at the rate the joint states arrive, which is not the
            # action rate: counting a stage once per pass counted 15855 ticks
            # of an APPROACH that was 0.1 s a tick.
            new_ticks, seen_ticks = ex.ticks - seen_ticks, ex.ticks
            # the camera's own rate, not the replan rate: judging whether
            # the jaw has settled needs more than two readings every half
            # second. This only watches; the width the policy is given is
            # still built in observe(), from the same camera, unchanged.
            if ex.latch is not None and b.frame_stamp != last_frame:
                last_frame = b.frame_stamp
                w_obs, w_ok = b.width_sample()
                was = ex.latch.latched
                ex.latch.sample(b.frame_stamp, w_obs, w_ok, ex.jaw_commanded,
                                asked=ex.jaw_asked)
                if ex.latch.latched and not was:
                    # do not wait for the next action to come due
                    ex.jaw_commanded = ex.latch.latched_width
                    b.jaw_async(ex.latch.latched_width)
                    click.secho(f"      latched at "
                                f"{ex.latch.latched_width*1000:.2f} mm, "
                                f"tick {ex.ticks}", fg="cyan")
            ex.service_jaw()
            if ex.pending is not None and ex.pending[0].done():
                try:
                    got = ex.collect()
                except RuntimeError as e:
                    click.secho(f"  [{i}] {e}", fg="red")
                    stopped = str(e)[:40]
                    break
                if got:
                    ex.send()
                    # send() blocks until the goal is accepted and
                    # start_inference captures two frames; the jaw's own
                    # moments pass during both, so it is serviced around them
                    ex.service_jaw()
                    consecutive = 0
                else:
                    consecutive += 1
                    if consecutive >= 8:
                        stopped = "eight plans in a row the arm could not reach"
                        break
                ex.start_inference()
                ex.service_jaw()
            ball_now = b.body_xyz("object")
            jaw = b.jaw_now_gt()
            closed = jaw < 0.045
            lifted = ball_now is not None and ball_now[2] > r + 0.02
            holding = bool(closed and lifted)
            if holding:
                ever_held = True
            p_now, R_now = b.ee_now()
            # the tool as it actually moved, at the rate the joint states
            # arrive. Commanded motion and executed motion are different
            # numbers and the gap between them is the controller's, not the
            # policy's -- it cannot be recovered from the plans afterwards.
            if b.state is not last_state:
                last_state = b.state
                # the joints too, and the tool pitch they give. The signed-axis
                # audit could follow z through all five layers but had to stop
                # at the tool's orientation, because only its position was
                # kept. This changes nothing the arm does.
                ee_track.append([round(b.state.header.stamp.sec
                                       + b.state.header.stamp.nanosec * 1e-9, 5)]
                                + (p_now * 1000).round(3).tolist()
                                + [round(math.degrees(math.asin(max(-1.0, min(
                                    1.0, -R_now[:, 1][2])))), 4)]
                                + np.degrees(b.q_now()).round(4).tolist()
                                # EVALUATION ONLY. The true ball, so the tool
                                # frame offset can be reconstructed afterwards.
                                # It reaches no observation and no command.
                                + ((ball_now * 1000).round(3).tolist()
                                   if ball_now is not None else [None] * 3)
                                # EVALUATION ONLY: the simulator's jaw width
                                + [round(float(jaw) * 1000, 3)])
            near_bin = (np.linalg.norm(np.asarray(ep["bin_xy"]) - p_now[:2]) < 0.06)
            seen_o = ex.plans[-1]["object_visible"] if ex.plans else False
            seen_b = ex.plans[-1]["bin_visible"] if ex.plans else False
            if ever_held and not holding:
                if not was_released:
                    ok_here, _ = (in_bin(cfg, ball_now, ep["bin_xy"], ep["bin_yaw"])
                                  if ball_now is not None else (False, None))
                    dropped.append({"tick": ex.ticks, "over_the_bin": bool(ok_here),
                                    "ee_mm": (p_now * 1000).round(1).tolist(),
                                    "ball_mm": (ball_now * 1000).round(1).tolist()
                                    if ball_now is not None else None})
                    was_released = True
                stage = "AFTER_RELEASE"
            elif holding:
                stage = ("PLACE" if near_bin and seen_b else
                         "TRANSPORT" if seen_b else
                         "LIFT" if p_now[2] < 0.22 else "SEARCH_BIN")
            elif closed and ball_now is not None and not lifted:
                stage = "GRASP"
            elif seen_o:
                stage = "APPROACH_OBJECT"
            else:
                stage = "SEARCH_OBJECT"
            if stage != (reached[-1] if reached else None):
                reached.append(stage)
                # when each phase began, on the plant's clock -- so a close is
                # measured at the actual GRASP entry, not at whatever moment a
                # jaw reading happened to cross a threshold
                stage_events.append({"t": joint_clock(), "tick": int(ex.ticks),
                                     "stage": stage})
            if vid is not None:
                vid.maybe(ex, stage, ball_now, r)
            if new_ticks:
                stage_ticks[stage] = stage_ticks.get(stage, 0) + new_ticks
            # stamp the plan that is currently in flight with what an
            # evaluator can see and the policy cannot: which phase this is,
            # and where the tool is relative to the true ball
            if ex.plans and "stage" not in ex.plans[-1]:
                pl = ex.plans[-1]
                pl["stage"] = stage
                pl["tick"] = ex.ticks
                pl["jaw_gt_mm"] = round(float(jaw) * 1000, 3)
                if ball_now is not None:
                    gap = p_now - ball_now
                    pl["tcp_to_ball_mm"] = round(float(np.linalg.norm(gap)) * 1000, 2)
                    pl["tcp_to_ball_xy_mm"] = round(
                        float(np.linalg.norm(gap[:2])) * 1000, 2)
                    pl["tcp_to_ball_z_mm"] = round(float(gap[2]) * 1000, 2)
            if ball_now is not None and in_bin(cfg, ball_now, ep["bin_xy"],
                                               ep["bin_yaw"])[0] and jaw > 0.045:
                stopped = "the ball is in the bin"
                break
        if vid is not None:
            vid.close()
        steps = ex.ticks
        if ex.plans and ex.plans[-1].get("executed") is None:
            ex.plans[-1]["executed"] = ex.ticks - ex._ticks_at_send
        chunks_tried = len(ex.plans)
        ik_attempts, ik_refusals = ex.ik_attempts, ex.ik_refusals
        grasped_once = ever_held
        trace = ex.plans
        corr_p = [x["moved_by_projection_mm"] for pl in ex.plans for x in pl["sent"]]
        corr_r = [x["turned_by_projection_deg"] for pl in ex.plans
                  for x in pl["sent"]]

        if time.time() - t0 >= wall_limit:
            stopped = "the wall-clock safety net, not the task's clock"
        b.spin(1.5)
        ball = b.body_xyz("object")
        ok, local = in_bin(cfg, ball, ep["bin_xy"], ep["bin_yaw"]) \
            if ball is not None else (False, np.array([np.nan, np.nan]))
        if frames_path is not None and b.frame_log:
            st_ = sorted(b.frame_log)
            extra = {}
            if all(b.frame_log[t][1] is not None for t in st_):
                extra["canvas"] = np.stack([b.frame_log[t][1] for t in st_])
            # G0 keeps no canvas in the loop (rgb_geometry.apply on the masked
            # frame reproduces it exactly, afterwards)
            np.savez_compressed(frames_path / f"ep{i:02d}.npz",
                                image_stamp_s=np.array(st_, np.float64),
                                masked=np.stack([b.frame_log[t][0] for t in st_]),
                                geometry=np.array(b.rgb_geometry), **extra)
        rows.append({"episode": i, "success": ok, "steps": steps,
                     "chunks_tried": chunks_tried,
                     # every waypoint of every plan is projected, so the rate
                     # is per waypoint. The old figure assumed one attempt per
                     # chunk and went negative once a plan carried eight.
                     "ik_attempts": ik_attempts,
                     "ik_refusals": ik_refusals,
                     "ik_reachable_rate":
                         round(1.0 - ik_refusals / max(ik_attempts, 1), 4),
                     "stopped_because": stopped,
                     "stage_ticks": stage_ticks,
                     "let_go": dropped,
                     "furthest_stage": (max(reached, key=lambda s_: ORDER.index(s_))
                                        if reached else "none"),
                     "seconds": round(time.time() - t0, 1),
                     "grasped": grasped_once, "ik_failures": ik_fail,
                     "correction_pos_mm": corr_p, "correction_rot_deg": corr_r,
                     "trace": trace, "ee_track": ee_track,
                     "obs_wait_s": round(obs_wait, 3),
                     "infra_retries": len(infra_log) - 1,
                     "infra_log": infra_log,
                     "stage_events": stage_events,
                     "started_perturbed": perturbed_ok,
                     "jaw_log": ex.jaw_log,
                     "latch_log": (ex.latch.log if ex.latch else []),
                     "latched_width_mm": (
                         None if not ex.latch or ex.latch.latched_width is None
                         else round(ex.latch.latched_width * 1000, 3)),
                     "latched_at_s": (ex.latch.latched_at if ex.latch else None),
                     "ball_final_mm": (ball * 1000).tolist() if ball is not None else None,
                     "offset_from_bin_mm": (local * 1000).tolist()})
        click.secho(f"  [{i}] {'SUCCESS' if ok else 'failed'}   "
                    f"{steps:3d} actions in {rows[-1]['seconds']:5.1f}s   "
                    f"grasped {grasped_once}   waypoints reachable "
                    f"{rows[-1]['ik_reachable_rate']*100:5.1f}% of "
                    f"{ik_attempts}   "
                    f"ball {np.round(local*1000,1)} mm from the bin centre",
                    fg="green" if ok else "yellow")

    n_ok = sum(r["success"] for r in rows)
    allp = np.concatenate([r["correction_pos_mm"] for r in rows
                           if r["correction_pos_mm"]]) if rows else np.zeros(1)
    allr = np.concatenate([r["correction_rot_deg"] for r in rows
                           if r["correction_rot_deg"]]) if rows else np.zeros(1)
    tried = sum(r["chunks_tried"] for r in rows)
    att = sum(r["ik_attempts"] for r in rows)
    ref = sum(r["ik_refusals"] for r in rows)
    click.secho(f"\n{n_ok}/{len(rows)} rollouts put the ball in the bin; "
                f"{sum(r['grasped'] for r in rows)} grasped it", bold=True)
    click.secho("the two failures are different things", bold=True)
    click.echo(f"  waypoints the arm can reach: {(1-ref/max(att,1))*100:5.1f}% of "
               f"{att}   ({ref} refused by the IK gate, over {tried} plans)")
    click.echo(f"  rollouts stopped by: " + ", ".join(
        f"{r['episode']}:{r['stopped_because']}" for r in rows))
    click.secho("\nwhere each rollout spent its ticks, and how far it got",
                bold=True)
    click.echo(f"  {'ep':>3s} {'furthest':>15s}  " +
               "".join(f"{s_[:8]:>9s}" for s_ in ORDER))
    for r_ in rows:
        click.echo(f"  {r_['episode']:3d} {r_['furthest_stage']:>15s}  " +
                   "".join(f"{r_['stage_ticks'].get(s_, 0):9d}" for s_ in ORDER))
    lets = [(r_["episode"], g) for r_ in rows for g in r_["let_go"]]
    click.secho("\nwhere the ball was let go", bold=True)
    if not lets:
        click.echo("  never -- no rollout ever had it")
    for epi, g in lets:
        click.echo(f"  rollout {epi}: tick {g['tick']:3d}, "
                   f"{'over the bin' if g['over_the_bin'] else 'DROPPED'}, "
                   f"ball at {g['ball_mm']} mm")
    click.secho("raw policy pose -> nearest pose the 5-DoF arm can hold", bold=True)
    click.echo(f"  position  mean {allp.mean():6.3f}  p95 "
               f"{np.percentile(allp, 95):6.3f}  max {allp.max():6.3f} mm")
    click.echo(f"  rotation  mean {allr.mean():6.3f}  p95 "
               f"{np.percentile(allr, 95):6.3f}  max {allr.max():6.3f} deg")
    if out:
        pathlib.Path(out).write_text(json.dumps(
            {"from_demos": from_demos, "horizon_steps": horizon_steps,
             "rgb_geometry": b.rgb_geometry, "server_meta": b.server_meta,
             "frames_dir": str(frames_path) if frames_path else None,
             "successes": n_ok, "rollouts": len(rows),
             "ee_track_columns": ["stamp_s", "x_mm", "y_mm", "z_mm",
                                  "pitch_deg", "j1_deg", "j2_deg", "j3_deg",
                                  "j4_deg", "j5_deg",
                                  "ball_x_mm", "ball_y_mm", "ball_z_mm",
                                  "jaw_gt_mm"],
             "infra_failed": infra_failed,
             "correction_pos_mm_mean": float(allp.mean()),
             "correction_rot_deg_mean": float(allr.mean()),
             "episodes": rows}, indent=2))
        click.echo(f"wrote {out}")
    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
