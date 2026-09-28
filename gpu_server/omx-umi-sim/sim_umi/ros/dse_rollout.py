"""The policy closed loop on the SIMULATION clock: a TIMING-CONTROLLED evaluator (file
names keep the earlier "DSE") for policy / representation A-B comparison.

Definition (user, ~20:52): every timing and scheduling contract is deterministic -- paused
tick stepping, observation ticks, virtual latency, takeover tick, jaw and waypoint ticks,
integer-tick time_from_start -- and verified per plan by hard gates. It is NOT a strictly
deterministic evaluator: the renderer's +-1-level pixel nondeterminism (a few pixels, policy
output ~1e-7) remains and can be amplified by the closed loop, so two runs can part after
many plans. Outcome variance is therefore characterised by repeats, not assumed zero.

    python sim_umi/ros/dse_rollout.py --episodes 5 --out <file.json>
    python sim_umi/ros/dse_rollout.py --from-demos v2_val --episodes 18 --start-perturbed \
        --max-ticks 400 --out <file.json>

Design and the decisions it implements: sim_umi/train_results/2026-09-27_fov/DSE_DESIGN.md.
The asynchronous evaluator (policy_rollout.py + rolling_executor.py) is not touched and
stays the runtime-robustness evaluator.

The plant is PAUSED for the whole run. Sim time advances only through StepSimulation
calls made here, so every event happens at a chosen tick (0.002 s) and wall time --
inference, IK, CPU load -- decides nothing:

  observation at a camera tick t     frames stamped t - 0.1 and t, and the simulator's
                                     own state at those two ticks (controller-manager
                                     cycle messages; interpolated across the two
                                     neighbouring cycles only where the cycle was absent)
  inference                          while paused at t; its wall time is recorded, unused
  t .. T_d = t + L_v                 the plan in flight keeps executing and its jaw events
                                     fire at their ticks (L_v = 0.216 s, the compute
                                     latency; no stale-clock delay -- decision A)
  at T_d                             collect with now = T_d (the executor's own k* rule),
                                     send the goal with time_from_start against the TRUE
                                     start tick (installation is the next update, T_d + 1
                                     tick), confirm it installed before stepping on
  next observation                   the executor's rule: first frame >= (newest frame at
                                     T_d) + 0.1; the resulting cadence is recorded

Start: ResetWorld to the episode's start configuration (HOME, or the perturbed pose set
directly -- decision 3) with zero velocity and the bodies at their placement, a hold goal
and an open-jaw goal installed beforehand, then a fixed settle. The controller manager's
1-ns-short-tick skips (every ~146 ticks) are accepted and recorded (decision 4).

Evaluation-only ground truth (ball, bin, true jaw) is used exactly as in policy_rollout.py
and never reaches the policy.
"""
import bisect
import json
import math
import pathlib
import sys
import time
from concurrent.futures import Future

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import numpy as np
import rclpy
from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory, GripperCommand
from control_msgs.msg import JointTrajectoryControllerState
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectoryPoint

from collect_demos import HOME_Q, depth_for  # noqa: E402
from policy_bridge import ARM, _AlignedState  # noqa: E402
from policy_rollout import ORDER, Rollout, in_bin  # noqa: E402
from rolling_executor import RollingExecutor, _pitch, _six_to_R  # noqa: E402

DT_NS = 2_000_000                 # physics timestep 0.002 s
PHYSICS_DT_NS = DT_NS
PHYSICS_DT = PHYSICS_DT_NS * 1e-9


def exact_ticks(seconds):
    """A duration the executor defines in seconds, as a whole number of physics ticks --
    refused if it is not one (the tick grid is the DSE's source of truth)."""
    r = seconds / PHYSICS_DT
    k = int(round(r))
    if abs(r - k) > 1e-6:
        raise ValueError(f"{seconds} s is not a whole number of {PHYSICS_DT} s physics ticks")
    return k
CAM_TICKS = 25                    # camera 20 Hz
SIM_NODE = "/mujoco_ros2_control_node"
GRIP_OPEN = 0.47                  # gripper_joint_1 = gripper_joint_2 (MJCF equality) when open
KP1, KV1, FMAX = 50.0, 4.86944, 3.5   # joint1 servo, for the offline lock check


class DSEBridge(Rollout):
    """The rollout bridge, driven tick by tick."""

    def __init__(self, sock_path):
        super().__init__(sock_path)
        deep = QoSProfile(depth=2000, history=HistoryPolicy.KEEP_LAST,
                          reliability=ReliabilityPolicy.RELIABLE)
        # the base keeps only the newest image / joint state; here every frame and every
        # controller cycle of the episode is kept, by its simulation stamp (ns)
        for s in list(self.subscriptions):
            if s.topic_name in ("/wrist_camera/image_raw", "/joint_states"):
                self.destroy_subscription(s)
        self.frames = {}            # ns -> raw rgb
        self.cycles = {}            # ns -> actuator-state message (the hardware read())
        self.cycle_keys = []        # the same stamps, in arrival (= time) order
        self.cstate = {}            # ns -> (reference tfs, output positions)
        self.clock_ns = []          # every /clock tick received, in order
        self.create_subscription(Image, "/wrist_camera/image_raw", self._on_image, deep)
        self.create_subscription(JointState, "/mujoco_actuators_states", self._on_cycle, deep)
        self.create_subscription(JointTrajectoryControllerState, "/arm_controller/controller_state",
                                 self._on_cstate, deep)
        self.create_subscription(Clock, "/clock", self._on_clock, deep)
        # the patched camera plugin's joint state of the SAME snapshot as each frame, with the
        # SAME stamp (overlay_patches/camera_sim_state_trigger.patch; DSE plugin config)
        self.snaps = {}             # ns -> JointState
        self.create_subscription(JointState, "/wrist_camera/joint_snapshot", self._on_snap, deep)
        from mujoco_ros2_control_msgs.srv import ResetWorld, SetPause, StepSimulation
        self.ResetWorld, self.SetPause, self.StepSimulation = ResetWorld, SetPause, StepSimulation
        self.pause_c = self.create_client(SetPause, f"{SIM_NODE}/set_pause")
        self.step_c = self.create_client(StepSimulation, f"{SIM_NODE}/step_simulation")
        self.reset_c = self.create_client(ResetWorld, f"{SIM_NODE}/reset_world")
        for c in (self.pause_c, self.step_c, self.reset_c):
            assert c.wait_for_service(timeout_sec=30), c.srv_name
        self.ns_now = None          # sim time of the last completed step (ns)
        self.call_timing = []
        self.steps_issued = 0       # physics steps asked of the plant, ever (the camera counts these)
        self.reset_steps, self.reset_ns = 0, None
        self.skips = []             # ticks (ns) whose controller cycle was absent as expected
        self.anomalies = []         # anything outside the contract, listed, never mended

    # ------------------------------------------------------------ callbacks --
    # (named _on_*: rclpy.Node keeps its own _clock and friends)
    @staticmethod
    def _ns(stamp):
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    def _on_image(self, msg):
        if msg.encoding != "rgb8":
            raise RuntimeError(f"expected rgb8 from the camera, got {msg.encoding}")
        f = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.width, 3).copy()
        ns = self._ns(msg.header.stamp)
        self.frames[ns] = f
        if len(self.frames) > 200:
            for k in sorted(self.frames)[:-200]:
                del self.frames[k]

    def _on_cycle(self, msg):
        k = self._ns(msg.header.stamp)
        self.cycles[k] = msg
        self.cycle_keys.append(k)

    # ---- reset-relative integer ticks: the DSE's source of truth for time -------------
    def anchor_reset(self):
        """At a ResetWorld: tick 0 is the reset tick; the tick count is the number of physics
        steps issued since (the camera plugin counts the same steps)."""
        self.reset_steps, self.reset_ns = self.steps_issued, self.ns_now

    def tick_now(self):
        return self.steps_issued - self.reset_steps

    def tick_of_ns(self, ns):
        return int(round((ns - self.reset_ns) / PHYSICS_DT_NS))

    def tick_of_s(self, t):
        return int(round((t * 1e9 - self.reset_ns) / PHYSICS_DT_NS))

    def time_of_tick(self, k):
        """A tick's nominal time, float seconds (for code that works in seconds)."""
        return (self.reset_ns + k * PHYSICS_DT_NS) * 1e-9

    def reset_records(self):
        self.call_timing = []       # per StepSimulation call: (steps, service s, clock wait s, cycle wait s)
        self.cycles, self.cycle_keys, self.cstate = {}, [], {}
        self.skips, self.anomalies = [], []

    def _on_cstate(self, m):
        self.cstate[self._ns(m.header.stamp)] = (
            m.reference.time_from_start.sec + m.reference.time_from_start.nanosec * 1e-9,
            list(m.output.positions))

    def _on_snap(self, m):
        self.snaps[self._ns(m.header.stamp)] = m
        if len(self.snaps) > 400:
            for k in sorted(self.snaps)[:-400]:
                del self.snaps[k]

    def _on_clock(self, m):
        self.clock_ns.append(self._ns(m.clock))

    # -------------------------------------------------------------- clock ----
    @property
    def t_now(self):
        return None if self.ns_now is None else self.ns_now * 1e-9

    def call(self, client, req, timeout=30.0):
        fut = client.call_async(req)
        t0 = time.time()
        while not fut.done():
            rclpy.spin_once(self, timeout_sec=0.001)
            if time.time() - t0 > timeout:
                raise RuntimeError(f"{client.srv_name}: no answer in {timeout} s")
        return fut.result()

    def pause(self, paused):
        r = self.call(self.pause_c, self.SetPause.Request(paused=paused))
        # barrier: the /clock messages of the realtime run before the pause may still be queued
        # here; the paused plant publishes no new tick, so drain until 0.3 s pass with none new
        t0 = time.time()
        last_n, quiet_since = len(self.clock_ns), time.time()
        while time.time() - t0 < 10.0:
            rclpy.spin_once(self, timeout_sec=0.005)
            if len(self.clock_ns) != last_n:
                last_n, quiet_since = len(self.clock_ns), time.time()
            elif time.time() - quiet_since > 0.3:
                break
        if paused:
            self.ns_now = max(self.clock_ns) if self.clock_ns else None
        return bool(r.success)

    def step(self, n):
        """n physics steps; returns the new ticks (ns). Waits for each tick's controller
        cycle, or records its absence where the tick is 1 ns short (the controller
        manager cannot wake on it) -- anything else is an anomaly."""
        before = self.ns_now
        w0 = time.time()
        r = self.call(self.step_c, self.StepSimulation.Request(steps=int(n)))
        if not r.success:
            raise RuntimeError(f"StepSimulation({n}) failed: {r.message}")
        w1 = time.time()
        self.steps_issued += int(n)
        # the plant has done n steps; its /clock is try-published, so a tick's message can be
        # missing. Wait for the LAST tick by value (n ticks on, within half a tick), then take
        # whatever ticks arrived; a missing one is recorded -- the controller manager, which
        # also runs on /clock, may have missed that tick too.
        t0 = time.time()
        i0 = bisect.bisect_right(self.clock_ns, before)
        target = before + n * DT_NS - DT_NS // 2
        while time.time() - t0 < 1.0 and not (self.clock_ns and self.clock_ns[-1] >= target):
            rclpy.spin_once(self, timeout_sec=0.001)
        new = [c for c in self.clock_ns[i0:] if c <= before + n * DT_NS + DT_NS // 2]
        if len(new) < n:
            have = [before] + new
            gaps = [(a_, b_) for a_, b_ in zip(have, have[1:]) if b_ - a_ > DT_NS + DT_NS // 2]
            self.anomalies.append({"what": "clock message(s) missing", "after_ns": before, "got": len(new),
                                   "asked": n, "gaps_ns": gaps[:5],
                                   "last_ok": bool(new) and new[-1] >= target})
            if not new or new[-1] < target:
                new = new + [before + DT_NS * (k + 1) for k in range(len(new), n)]
        w2 = time.time()
        prev = before
        expect, short = [], []
        for c in new:
            (short if c - prev < DT_NS else expect).append(c)
            prev = c
        t0 = time.time()
        while time.time() - t0 < 1.0 and not all(c in self.cycles for c in expect):
            rclpy.spin_once(self, timeout_sec=0.001)
        miss = [c for c in expect if c not in self.cycles]
        if miss:
            self.anomalies.append({"what": "controller cycle absent on a full-length tick",
                                   "ticks_ns": miss})
        for c in short:
            if c in self.cycles:
                self.anomalies.append({"what": "controller cycle present on a short tick",
                                       "tick_ns": c})
            else:
                self.skips.append(c)
        self.call_timing.append((int(n), w1 - w0, w2 - w1, time.time() - w2))
        self.ns_now = new[-1]
        if self.cycle_keys:
            self.state = self.cycles[self.cycle_keys[-1]]
        return new

    def step_until(self, ns_target, batch):
        """Step to exactly ns_target (a tick), at most `batch` steps per call."""
        out = []
        while self.ns_now < ns_target - DT_NS // 2:
            n = max(1, min(batch, int(round((ns_target - self.ns_now) / DT_NS))))
            out += self.step(n)
        if abs(self.ns_now - ns_target) > DT_NS // 2:
            raise RuntimeError(f"overshot the tick: at {self.ns_now}, wanted {ns_target}")
        return out

    def wait_frame(self, ns, timeout=2.0):
        """The camera renders on its own thread after snapshotting the tick."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            hit = self.frame_at(ns)
            if hit is not None:
                return hit
            rclpy.spin_once(self, timeout_sec=0.002)
        return None

    def frame_at(self, ns):
        k = min(self.frames, key=lambda x: abs(x - ns), default=None)
        return k if k is not None and abs(k - ns) < 100_000 else None     # within 0.1 ms

    # ------------------------------------------------- the Bridge's sensing ----
    def obs_frames(self):
        return [(k * 1e-9, self.frames[k]) for k in sorted(self.frames)]

    def state_at_aligned(self, stamp):
        """The simulator's own state at the tick of an image. First choice: the joint
        snapshot the camera plugin took from the SAME mjData as the image, with the SAME
        stamp -- exact by construction. If it is missing (an anomaly, recorded) the tick's
        controller cycle is used, or the two neighbouring cycles interpolated."""
        img_ns = self.frame_at(int(round(stamp * 1e9)))
        if img_ns is not None and img_ns in self.snaps:
            m = self.snaps[img_ns]
            return m, {"mode": "exact", "source": "rgb_snapshot", "state_stamp_s": img_ns * 1e-9,
                       "skew_s": 0.0}
        self.anomalies.append({"what": "no joint snapshot with the image's stamp", "stamp_s": stamp})
        want = int(round(stamp * 1e9))
        ks = self.cycle_keys
        j = bisect.bisect_left(ks, want)
        near = [ks[x] for x in (j - 1, j) if 0 <= x < len(ks)]
        ns = min(near, key=lambda c: abs(c - want)) if near else None
        if ns is not None and abs(ns - want) < 100_000:
            return self.cycles[ns], {"mode": "exact", "source": "dse_cycle",
                                     "state_stamp_s": ns * 1e-9, "skew_s": 0.0}
        lo = max((c for c in near if c < want), default=None)
        hi = min((c for c in near if c > want), default=None)
        if lo is None or hi is None:
            raise RuntimeError(f"no controller cycle around the image stamp {stamp:.6f}")
        a = (want - lo) / (hi - lo)
        L, H = self.cycles[lo], self.cycles[hi]
        h = dict(zip(H.name, H.position))
        pos = [v + (h[n] - v) * a for n, v in zip(L.name, L.position)]
        return _AlignedState(list(L.name), pos), {
            "mode": "interp", "source": "dse_cycle", "state_stamp_s": stamp, "skew_s": 0.0,
            "bracket_s": [lo * 1e-9, hi * 1e-9]}

    def _state(self, msg):          # /joint_states is not used for state here
        pass

    # ------------------------------------------------------------ commanding --
    def install(self, client, goal, what, timeout=10.0):
        """Send a goal while paused and return only once the controller has installed
        it: acceptance comes back BEFORE the accepted callback that installs the
        trajectory runs, so EXECUTING is waited for, then a moment more."""
        fut = client.send_goal_async(goal)
        t0 = time.time()
        while not fut.done():
            rclpy.spin_once(self, timeout_sec=0.001)
            if time.time() - t0 > timeout:
                raise RuntimeError(f"{what}: no goal response")
        h = fut.result()
        if h is None or not h.accepted:
            return None
        t0 = time.time()
        while h.status != GoalStatus.STATUS_EXECUTING:
            rclpy.spin_once(self, timeout_sec=0.001)
            if time.time() - t0 > timeout:
                self.anomalies.append({"what": f"{what}: accepted but never EXECUTING",
                                       "status": int(h.status)})
                return h
        t0 = time.time()
        while time.time() - t0 < 0.02:
            rclpy.spin_once(self, timeout_sec=0.002)
        return h

    def jaw_async(self, width):
        theta = float(np.interp(width, self.kin._width_tab, self.kin._theta_tab))
        g = GripperCommand.Goal()
        g.command.position = theta
        g.command.max_effort = 0.5
        self.install(self.grip, g, "gripper")
        return theta

    def hold_goal(self, q, tfs=0.1):
        g = FollowJointTrajectory.Goal()
        g.trajectory.joint_names = ARM
        p = JointTrajectoryPoint()
        p.positions = [float(v) for v in q]
        p.time_from_start.sec, p.time_from_start.nanosec = 0, int(tfs * 1e9)
        g.trajectory.points.append(p)
        return self.install(self.arm, g, "hold")

    def reset_to(self, q_arm, obj_xy, obj_z, bin_xy, bin_yaw):
        from mujoco_ros2_control_msgs.msg import FreeJointState
        from collect_demos import quat_from_yaw
        req = self.ResetWorld.Request()
        js = req.state_overrides.joint_states
        js.name = ARM + ["gripper_joint_1", "gripper_joint_2"]
        js.position = [float(v) for v in q_arm] + [GRIP_OPEN, GRIP_OPEN]
        js.velocity = [0.0] * len(js.name)
        for name, xy, z, yaw in (("object", obj_xy, obj_z, 0.0), ("bin", bin_xy, 0.0, bin_yaw)):
            s = FreeJointState()
            s.name = name
            s.pose.pose.position.x, s.pose.pose.position.y, s.pose.pose.position.z = (
                float(xy[0]), float(xy[1]), float(z))
            (s.pose.pose.orientation.x, s.pose.pose.orientation.y,
             s.pose.pose.orientation.z, s.pose.pose.orientation.w) = quat_from_yaw(yaw)
            req.state_overrides.free_joints.append(s)
        r = self.call(self.reset_c, req)
        return bool(r.success), r.message


class DSEExecutor(RollingExecutor):
    """The rolling executor's plan logic (decode, projection, k*, jaw merge) on the
    simulation clock: now() IS the paused plant's time."""

    def setup_ticks(self):
        """The executor's own durations, as whole physics ticks (refused otherwise)."""
        self.ticks_per_action = exact_ticks(self.dt)                   # action grid spacing
        self.robot_latency_ticks = exact_ticks(self.robot_latency)     # arm commanded this early
        self.gripper_latency_ticks = exact_ticks(self.gripper_latency) # jaw commanded this early
        self.min_lead_ticks = exact_ticks(0.02)                        # RollingExecutor.send: points
                                                                       # within 20 ms are not sent

    def now(self):
        """The current tick's time, exactly on the tick grid (no tolerance)."""
        return self.b.time_of_tick(self.b.tick_now())

    def retire(self):
        """As RollingExecutor.retire, on integer ticks."""
        cur = self.b.tick_now()
        while self.plan and self.b.tick_of_s(self.plan[0][0]) <= cur:
            self.plan.pop(0)
            self.ticks += 1

    def jaw_tick(self, ev):
        return self.b.tick_of_s(ev["t"])

    def service_jaw(self):
        """As RollingExecutor.service_jaw, firing an event on its own integer tick."""
        cur = self.b.tick_now()
        now = self.now()
        while self.jaw_events and self.jaw_tick(self.jaw_events[0]) <= cur:
            ev = self.jaw_events.pop(0)
            asked = ev["w"]
            self.jaw_asked = asked
            w = self.latch.command(asked) if self.latch else asked
            big = (self.jaw_commanded is None or abs(w - self.jaw_commanded) > self.jaw_threshold)
            due_tick = self.jaw_tick(ev)
            row = {"t_due_s": round(ev["t"], 6), "t_fired_s": round(now, 6),
                   "due_tick": due_tick, "fired_tick": cur,
                   "late_s": round((cur - due_tick) * PHYSICS_DT, 6),
                   "reach_t_s": round(ev.get("reach_t", ev["t"]), 6),
                   "asked_mm": round(asked * 1000, 3), "width_mm": round(w * 1000, 3),
                   "held": bool(self.latch is not None and self.latch.latched),
                   "committed": ev["committed"], "from_plan": ev["plan"], "sent": bool(big),
                   "actual_width_mm": round(self.b.jaw_now_gt() * 1000, 3)}
            if big:
                self.jaw_commanded = w
                self.b.jaw_async(w)
            self.jaw_log.append(row)

    def observe(self, t_obs):
        """The observation at camera tick t_obs, and the request, while paused.
        The frame / state bookkeeping mirrors RollingExecutor.start_inference so the
        trace reads the same; nothing here waits on wall time except the frames'
        arrival from the render thread."""
        H = self.b.meta["obs_horizon"]
        wanted = [t_obs - (H - 1 - i) * self.dt for i in range(H)]
        frames, shots, aligned = [], [], []
        for s_ in wanted:
            miss0 = self.b.width_misses
            f, _, info, st = self.b.observe_at(s_)
            frames.append(f)
            aligned.append(st)
            _, R_f = self.b.ee_now(st)
            shots.append({
                "image_stamp_s": round(float(info["image_stamp_s"]), 6),
                "requested_stamp_s": round(float(s_), 6),
                "frame_exact": bool(info["frame_exact"]),
                "state_mode": info["mode"], "state_source": info.get("source"),
                "joint_stamp_s": round(float(info["state_stamp_s"]), 6),
                "image_state_skew_s": info["skew_s"],
                "state_bracket_s": (None if "bracket_s" not in info
                                    else round(info["bracket_s"][1] - info["bracket_s"][0], 6)),
                "input_width_mm": round(float(f["grip"]) * 1000, 3),
                "gt_width_mm": round(float(f["_gt_width"]) * 1000, 3),
                "pixel_gap": f["_pixel_gap"],
                "width_is_stale": bool(self.b.width_misses > miss0),
                "fk_pitch_deg": round(_pitch(R_f), 4)})
        obs_t = float(shots[-1]["image_stamp_s"])
        self.obs_t_exact = obs_t
        self.obs_tick = self.b.tick_of_s(obs_t)
        p0, R0 = self.b.ee_now(aligned[-1])
        seen = {n: self.b.target_visible(n) for n in ("object", "bin")}
        batch = self.b.build_batch(frames)
        sp, sR = self.b.start_pose
        w = np.asarray(batch["robot0_eef_rot_axis_angle_wrt_start"][0, -1])
        obs_audit = {
            "frames": shots,
            "obs_dt_s": round(shots[-1]["image_stamp_s"] - shots[0]["image_stamp_s"], 6),
            "obs_pair_exact": bool(all(x["frame_exact"] for x in shots)
                                   and all(x["state_mode"] in ("exact", "interp") for x in shots)),
            "obs_wait_s": 0.0, "obs_extra_wait_frames": 0,
            "frames_distinct": bool(len({s["image_stamp_s"] for s in shots}) == len(shots)),
            "input_width_mm": round(float(batch["robot0_gripper_width"][0, -1, 0]) * 1000, 3),
            "jaw_commanded_mm": (None if self.jaw_commanded is None
                                 else round(self.jaw_commanded * 1000, 3)),
            "fk_pitch_deg": round(_pitch(R0), 4),
            "input_pitch_deg": round(_pitch(sR @ _six_to_R(w)), 4),
            "width_misses_total": self.b.width_misses}
        rid = getattr(self.b, "req_id", 0) + 1
        self.b.req_id = rid
        obs_audit["req_id"] = rid
        obs_audit["bin_gt"] = self.b.body_pose("bin")
        w0 = time.time()
        result = self.b.infer(frames, rid)             # the plant is paused meanwhile
        obs_audit["dse_inference_wall_s"] = round(time.time() - w0, 4)
        # the policy's exact input and output, for repeat-vs-repeat comparison: the sha1 of
        # every input array's bytes, the low-dim arrays themselves, and the raw action array
        import hashlib
        act, sent_batch = result
        h = hashlib.sha1()
        for k_ in sorted(sent_batch):
            h.update(k_.encode())
            h.update(np.ascontiguousarray(sent_batch[k_]).tobytes())
        obs_audit["policy_input_sha1"] = h.hexdigest()
        obs_audit["policy_output_sha1"] = hashlib.sha1(np.ascontiguousarray(act).tobytes()).hexdigest()
        self.policy_io.append({"req_id": rid, "t_obs": t_obs,
                               "lowdim": {k_: np.asarray(v) for k_, v in sent_batch.items() if k_ != "camera0_rgb"},
                               "rgb_sha1": hashlib.sha1(np.ascontiguousarray(sent_batch["camera0_rgb"]).tobytes()).hexdigest(),
                               "action": np.asarray(act)})
        fut = Future()
        fut.set_result(result)
        self.pending = (fut, obs_t, p0, R0, seen, obs_audit)

    def send(self):
        """As RollingExecutor.send, with every time on the reset-relative integer tick grid:
        waypoint k is due at action tick obs_tick + k * ticks_per_action, commanded
        robot_latency_ticks earlier (send tick); the trajectory is taken over at the next
        controller update after delivery (takeover tick = delivery tick + 1); its
        time_from_start is (send tick - takeover tick) * PHYSICS_DT_NS, an exact integer.
        No floating-point subtraction of absolute times, no tolerance."""
        if not self.plan:
            return False
        deliver_tick = self.b.tick_now()
        takeover_tick = deliver_tick + 1
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = list(ARM)
        send_ticks = []
        for t_k, _, q, _ in self.plan:
            k = int(round((t_k - self.obs_t_exact) / self.dt))
            action_tick = self.obs_tick + k * self.ticks_per_action
            send_tick = action_tick - self.robot_latency_ticks
            lead = send_tick - takeover_tick
            if lead <= self.min_lead_ticks:
                continue
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            tfs_ns = lead * PHYSICS_DT_NS
            pt.time_from_start.sec, pt.time_from_start.nanosec = tfs_ns // 1_000_000_000, tfs_ns % 1_000_000_000
            traj.trajectory.points.append(pt)
            send_ticks.append(send_tick)
        if not send_ticks:
            return False
        pl = self.plans[-1]
        pl["goal_deliver_tick"], pl["goal_takeover_tick"] = deliver_tick, takeover_tick
        pl["goal_send_ticks"] = send_ticks
        pl["first_point_tick"], pl["last_point_tick"] = send_ticks[0], send_ticks[-1]
        pl["goal_sent_at_s"] = round(self.b.time_of_tick(deliver_tick), 6)
        pl["goal_start_tick_s"] = round(self.b.time_of_tick(takeover_tick), 6)
        pl["first_point_commanded_s"] = round(self.b.time_of_tick(send_ticks[0]), 6)
        pl["goal_points"] = len(send_ticks)
        pl["goal_span_s"] = round((send_ticks[-1] - deliver_tick) * PHYSICS_DT, 6)
        h = self.b.install(self.b.arm, traj, "arm")
        ok = h is not None and h.accepted
        pl["goal_accepted"] = bool(ok)
        pl["send_end_wall"] = time.time()
        return ok


def timeline_checks(plans, cstate, tick_of_ns, lv_ticks, jaw_log, skips_ticks, ticks_per_action, robot_latency_ticks):
    """Per plan, on reset-relative integer ticks: L_v entered exactly once, the plan in
    flight ran through it, the JTC took the new goal over on the next update, the first
    commanded point is the executor's own send tick; any JTC trajectory restart inside the
    L_v window is allowed only ON or AFTER the in-flight trajectory's last point tick (the
    JTC then holds that point); one before it fails. Returns (per-plan rows, summary counts)."""
    cs = sorted((tick_of_ns(k), v[0]) for k, v in cstate.items())
    cs_ticks = [t for t, _ in cs]
    rows = []
    for n, pl in enumerate(plans):
        d = pl.get("dse")
        if not d:
            continue
        ot, dtk = d["obs_tick"], d["deliver_tick"]
        r = {"plan": n, "obs_tick": ot, "deliver_tick": dtk,
             "collect_is_t_plus_Lv": dtk - ot == lv_ticks and d.get("collect_tick") == dtk}
        lo = bisect.bisect_right(cs_ticks, ot)
        hi = bisect.bisect_right(cs_ticks, dtk)
        inside = cs[lo:hi]
        r["cycles_in_Lv"] = len(inside)
        restarts = [inside[j][0] for j in range(len(inside))
                    if inside[j][1] < 1e-9 or (j and inside[j][1] <= inside[j - 1][1])]
        prev = next((plans[m] for m in range(n - 1, -1, -1) if plans[m].get("goal_accepted")), None)
        end_tick = None if prev is None else prev.get("last_point_tick")
        r["in_flight_end_tick"], r["restart_ticks_in_Lv"] = end_tick, restarts
        # a restart ON or after the in-flight trajectory's end tick is the JTC holding its last
        # point (user, ~20:52: restart_tick >= trajectory_end_tick is a normal hold transition);
        # only a restart BEFORE the end tick fails
        r["hold_after_end"] = [t for t in restarts if end_tick is not None and t >= end_tick]
        r["restart_before_end"] = [t for t in restarts if end_tick is None or t < end_tick]
        r["old_plan_ran_through_Lv"] = bool(inside) and not r["restart_before_end"]
        if pl.get("goal_accepted"):
            r["takeover_tick_expected"] = pl["goal_takeover_tick"]
            r["start_is_Lv_plus_1tick"] = pl["goal_takeover_tick"] - ot == lv_ticks + 1
            j = bisect.bisect_right(cs_ticks, dtk)
            take = next((cs[i][0] for i in range(j, len(cs)) if cs[i][1] < 1e-9), None)
            r["takeover_tick_observed"] = take
            skipped = (dtk + 1) in skips_ticks
            r["takeover_ok"] = take is not None and (take == dtk + 1 or (take == dtk + 2 and skipped))
            k_first = pl["sent"][0]["k"] if pl.get("sent") else None
            if k_first is not None:
                want = ot + k_first * ticks_per_action - robot_latency_ticks
                r["first_point_tick"], r["first_point_tick_expected"] = pl.get("first_point_tick"), want
                r["first_point_is_tk_minus_latency"] = pl.get("first_point_tick") == want
        fired = [x for x in jaw_log if ot < x["fired_tick"] <= dtk]
        r["jaw_fired_in_Lv"] = len(fired)
        r["jaw_in_Lv_from_older_plans"] = all(x["from_plan"] < n for x in fired)
        r["jaw_in_Lv_on_time"] = all(x["fired_tick"] == x["due_tick"] for x in fired)
        rows.append(r)
    keys_ok = ["collect_is_t_plus_Lv", "old_plan_ran_through_Lv", "start_is_Lv_plus_1tick", "takeover_ok",
               "first_point_is_tk_minus_latency", "jaw_in_Lv_from_older_plans", "jaw_in_Lv_on_time"]
    summ = {k: f"{sum(1 for r in rows if r.get(k) is True)}/{sum(1 for r in rows if k in r)}" for k in keys_ok}
    summ["plans_with_hold_after_end"] = sum(1 for r in rows if r["hold_after_end"])
    return rows, summ


def episode_gates(row):
    """Hard gates, judged before any task outcome is looked at. All must hold."""
    d, tr = row["dse"], row["trace"]
    tl = d["timeline"]["summary"]
    g = {}
    g["timeline_invariants"] = all(v.split("/")[0] == v.split("/")[1] for k, v in tl.items() if isinstance(v, str))
    g["arm_continuity"] = (d["lock_check"]["n_violations"] == 0 and d["lock_check"]["ticks_checked"] > 0
                           and tl["old_plan_ran_through_Lv"].split("/")[0] == tl["old_plan_ran_through_Lv"].split("/")[1])
    g["jaw_continuity"] = all(j["fired_tick"] == j["due_tick"] for j in row["jaw_log"])
    frames = [f for pl in tr for f in (pl.get("obs") or {}).get("frames", [])]
    g["exact_observation_ticks"] = (
        bool(frames) and all(f["frame_exact"] for f in frames)
        and all(abs((pl.get("obs") or {}).get("obs_dt_s", 0) - 0.1) < 1e-5 for pl in tr)
        and all(f["state_mode"] == "exact" or (f["state_mode"] == "interp" and f.get("state_bracket_s") is not None
                                              and f["state_bracket_s"] <= 0.0041) for f in frames)
        and d["camera_checks"]["frames_checked"] > 0
        and d["camera_checks"]["frames_checked"] == d["camera_checks"]["on_predicted_tick"])
    g["jtc_takeover_step"] = tl["takeover_ok"].split("/")[0] == tl["takeover_ok"].split("/")[1]
    g["no_anomalies"] = len(d["anomalies"]) == 0
    g["all"] = all(g.values())
    return g


def lock_check(cycles, cstate, t0_ns):
    """Offline: was the command in effect in each physics step the previous update's
    output (offset 1)? joint1's servo is inverted from the simulator's own state."""
    ks = sorted(cycles)
    bad, checked = [], 0
    for a, b_ in zip(ks, ks[1:]):
        if b_ - a > DT_NS or a not in cstate:
            continue
        A, B = cycles[a], cycles[b_]
        ia = list(A.name).index("joint1")
        eff = B.effort[ia]
        if abs(eff) >= FMAX - 1e-6:
            continue
        u = (eff + KP1 * A.position[ia] + KV1 * A.velocity[ia]) / KP1
        out = cstate[a][1]
        if not out:
            continue
        checked += 1
        if abs(u - out[0]) > 1e-7:
            bad.append({"tick": int(round((b_ - t0_ns) / DT_NS)), "residual": abs(u - out[0])})
    return checked, bad


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--from-demos", default="train")
@click.option("--episodes", default=5, type=int)
@click.option("--start-perturbed/--start-home", default=False)
@click.option("--only", default=None)
@click.option("--horizon-steps", default=8, type=int)
@click.option("--max-ticks", default=600, type=int)
@click.option("--wall-limit", default=1800.0, type=float,
              help="per episode, a safety net only")
@click.option("--lv", default=0.216, type=float, help="virtual compute latency L_v (s)")
@click.option("--settle-ticks", default=250, type=int)
@click.option("--batch", default=5, type=int, help="physics steps per StepSimulation call between events")
@click.option("--steps-per-inference", default=6, type=int,
              help="action steps executed per inference -- the replanning cadence (UMI eval_real.py default 6 = 0.6 s)")
@click.option("--out", required=True)
@click.option("--frames-dir", default=None)
def main(socket_path, from_demos, episodes, start_perturbed, only, horizon_steps, max_ticks,
         wall_limit, lv, settle_ticks, batch, steps_per_inference, out, frames_dir):
    rclpy.init()
    b = DSEBridge(socket_path)
    t_w = time.time()
    while time.time() - t_w < 1.5:
        rclpy.spin_once(b, timeout_sec=0.01)
    cfg = b.cfg
    dt = b.meta["action_dt_s"]
    lv_ns = int(round(lv / (DT_NS * 1e-9))) * DT_NS
    paths = sorted((SIM / "data" / "demos" / from_demos).glob("episode_*.npz"))
    pick = ([int(x) for x in only.split(",")] if only else list(range(min(episodes, len(paths)))))
    specs = [(k, json.loads(str(np.load(paths[k], allow_pickle=True)["spec"]))) for k in pick]
    frames_path = pathlib.Path(frames_dir) if frames_dir else (
        pathlib.Path(out).with_name(pathlib.Path(out).stem + "_frames"))
    frames_path.mkdir(parents=True, exist_ok=True)
    click.secho(f"DSE: {len(specs)} rollouts from {from_demos}, L_v {lv_ns / 1e9:.3f} s, settle "
                f"{settle_ticks} ticks, batch {batch}, {steps_per_inference} action steps per inference; image geometry {b.rgb_geometry}; server "
                f"{(b.server_meta or {}).get('checkpoint', 'no sidecar (G0 server)')}", bold=True)
    rows, invalid = [], []

    def write_out(rows_, invalid_, partial):
        """Written after every episode (partial) and at the end, so a run that stops early
        still leaves every finished episode on disk."""
        allp_ = np.concatenate([r_["correction_pos_mm"] for r_ in rows_ if r_["correction_pos_mm"]]) \
            if any(r_["correction_pos_mm"] for r_ in rows_) else np.zeros(1)
        allr_ = np.concatenate([r_["correction_rot_deg"] for r_ in rows_ if r_["correction_rot_deg"]]) \
            if any(r_["correction_rot_deg"] for r_ in rows_) else np.zeros(1)
        pathlib.Path(out).write_text(json.dumps(
            {"evaluator": "dse", "evaluator_definition": "timing-controlled (timing / scheduling deterministic; renderer +-1 pixel noise not controlled)",
             "partial": partial, "from_demos": from_demos, "horizon_steps": horizon_steps,
             "gates_all_pass": bool(rows_) and all(r_["dse"]["gates"]["all"] for r_ in rows_),
             "rgb_geometry": b.rgb_geometry, "server_meta": b.server_meta,
             "frames_dir": str(frames_path), "successes": sum(r_["success"] for r_ in rows_), "rollouts": len(rows_),
             "dse": {"L_v_s": lv_ns / 1e9, "settle_ticks": settle_ticks, "batch": batch,
                     "steps_per_inference": steps_per_inference,
                     "start": "ResetWorld direct set" + (" (perturbed)" if start_perturbed else " (HOME)")},
             "ee_track_columns": ["stamp_s", "x_mm", "y_mm", "z_mm", "pitch_deg", "j1_deg", "j2_deg",
                                  "j3_deg", "j4_deg", "j5_deg", "ball_x_mm", "ball_y_mm", "ball_z_mm",
                                  "jaw_gt_mm"],
             "infra_failed": invalid_,
             "correction_pos_mm_mean": float(allp_.mean()), "correction_rot_deg_mean": float(allr_.mean()),
             "episodes": rows_}, indent=1))

    if not b.pause(True):
        raise click.ClickException("could not pause the plant")
    # Sensor-ready barrier, followed for the whole run: the camera's trigger chain runs on
    # continuously (ResetWorld keeps sim time), so it is tracked from the last frame
    # published before the pause, through every settle and every episode.
    # Camera schedule (patched plugin, trigger sim_state): a capture as every 25th physics
    # step begins, counted from the last world reset -- i.e. of the ticks reset + 25k. The
    # frame of tick c is taken when the step c -> c+1 starts; the barrier then holds until
    # that frame AND its joint snapshot (same stamp) are in. Expected vs actual is recorded;
    # a frame stamped otherwise is an anomaly, never a substitute.
    cam = {"reset_steps": None, "reset_ns": None, "next_k": 0, "checks": [], "anomalies": 0}

    def camera_anchor():
        """At a ResetWorld: the plugin's step counter restarts. Counted here in physics steps
        ISSUED (not in /clock messages received, which can be missing), from the reset tick."""
        b.anchor_reset()
        cam["reset_steps"], cam["reset_ns"], cam["next_k"] = b.reset_steps, b.reset_ns, 0

    def camera_after_step():
        if cam["reset_steps"] is None:
            return
        done = b.steps_issued - cam["reset_steps"]
        while True:
            m = 25 * cam["next_k"]
            if m + 1 > done:                 # the step that starts at capture tick m has not run
                return
            want = cam["reset_ns"] + m * DT_NS
            t0 = time.time()
            got = None
            while time.time() - t0 < 2.0:
                f = b.frame_at(want)
                if f is not None and f in b.snaps:
                    got = f
                    break
                rclpy.spin_once(b, timeout_sec=0.001)
            rec = {"k": cam["next_k"], "tick": m, "tick_ns": want, "frame_ns": got,
                   "ok": got is not None and got in b.snaps}
            if not rec["ok"]:
                other = sorted(x for x in b.frames if abs(x - want) < 30 * DT_NS)
                rec["frames_near"] = other
                rec["snapshot"] = got is not None and got in b.snaps
                b.anomalies.append({"what": "frame / snapshot not on the expected capture tick", **rec})
                cam["anomalies"] += 1
            cam["checks"].append(rec)
            cam["next_k"] += 1

    def camera_step_guard():
        return batch

    def step_to_tracked(tick_target):
        """Step to exactly tick_target (reset-relative) with the camera barrier and nothing
        else (settles)."""
        while b.tick_now() < tick_target:
            b.step(max(1, min(batch, tick_target - b.tick_now())))
            camera_after_step()

    try:
        for i, ep in specs:
            r = float(ep["ball_r"])
            b.reset_records()
            # ---- start state -------------------------------------------------------
            q_start, pert = np.array(HOME_Q, float), None
            if start_perturbed and "perturb_pitch_deg" in ep:
                z_re = r + ep["standoff"] * ep["reentry_frac"]
                pp = math.radians(ep["perturb_pitch_deg"])
                pdep = depth_for(b.kin, ep["object_xy"], r, z_re, pp,
                                 ep["perturb_tool_depth_mm"], ep["depth"])
                if pdep is None:
                    invalid.append({"episode": i, "why": "the perturbed pose is unreachable"})
                    continue
                p_w = b.kin.grasp_tcp_target(ep["object_xy"], z_re, pp, pdep)
                q_w, ep_err, _, _ = b.kin.solve_ik_planar(p_w, pp, iters=60)
                if ep_err > 0.002:
                    invalid.append({"episode": i, "why": f"perturbed pose misses by {ep_err*1000:.1f} mm"})
                    continue
                q_start = np.asarray(q_w, float)
            h_hold = b.hold_goal(q_start)
            b.jaw_async(float(b.kin._width_tab.max()))
            ok_r, msg = b.reset_to(q_start, ep["object_xy"], r, ep["bin_xy"], ep["bin_yaw"])
            if not (ok_r and h_hold is not None):
                invalid.append({"episode": i, "why": f"reset failed: {msg}"})
                continue
            ns_reset = b.ns_now
            camera_anchor()
            step_to_tracked(settle_ticks)
            # evaluation-only validity: bodies where placed and at rest (same tolerances
            # as the asynchronous evaluator's start check)
            ball0, bin0 = b.body_xyz("object"), b.body_xyz("bin")
            dev_b = float(np.linalg.norm(ball0 - np.array([*ep["object_xy"], r])) * 1000) if ball0 is not None else None
            dev_n = float(np.linalg.norm(bin0[:2] - np.array(ep["bin_xy"])) * 1000) if bin0 is not None else None
            start_info = {"q_start_deg": np.degrees(q_start).round(4).tolist(),
                          "q_after_settle_deg": np.degrees(b.q_now()).round(5).tolist(),
                          "ball_dev_mm": dev_b, "bin_dev_mm": dev_n,
                          "reset_tick_ns": ns_reset, "settle_ticks": settle_ticks}
            if dev_b is None or dev_n is None or dev_b > 2.0 or dev_n > 2.0:
                invalid.append({"episode": i, "why": "bodies not where placed after the settle",
                                **start_info})
                continue
            if start_perturbed and "perturb_pitch_deg" in ep:
                pert = {"asked_pitch": ep["perturb_pitch_deg"],
                        "asked_depth_mm": ep["perturb_tool_depth_mm"],
                        "realized_pitch": round(math.degrees(math.asin(max(-1.0, min(1.0,
                            -b.ee_now()[1][:, 1][2])))), 2), "settled": True, "set_by": "ResetWorld"}
            b.start_pose, b.last_width, b.frame_log, b.req_id = None, None, {}, 0
            ns_settled = b.ns_now
            ex = DSEExecutor(b, horizon_steps=horizon_steps, dt=dt)
            ex.setup_ticks()
            ex.policy_io = []
            ee_track, stage_events, stage_ticks, reached = [], [], {}, []
            dropped, was_released, ever_held = [], False, False
            stopped, consecutive, seen_ticks = "ran out of ticks", 0, 0
            cadence, t_wall0 = [], time.time()
            ee_ptr = [0]
            episode_t0 = ns_reset

            def evaluate():
                """The asynchronous rollout's per-pass bookkeeping (stage, ee_track, the
                plan's stamps, termination), on the current tick. Evaluation only."""
                nonlocal ever_held, was_released, seen_ticks, stopped
                ex.retire()
                new_ticks, seen_ticks = ex.ticks - seen_ticks, ex.ticks
                ball_now = b.body_xyz("object")
                jaw = b.jaw_now_gt()
                closed = jaw < 0.045
                lifted = ball_now is not None and ball_now[2] > r + 0.02
                holding = bool(closed and lifted)
                if holding:
                    ever_held = True
                p_now, R_now = b.ee_now()
                # ee_track at 100 Hz of plant time, from the cycles stepped over
                keys = b.cycle_keys
                while ee_ptr[0] < len(keys) and keys[ee_ptr[0]] <= b.ns_now:
                    c = keys[ee_ptr[0]]
                    ee_ptr[0] += 1
                    if c <= episode_t0 or int(round((c - episode_t0) / DT_NS)) % 5:
                        continue
                    st = b.cycles[c]
                    pc, Rc = b.ee_now(st)
                    ee_track.append([round(c * 1e-9, 6)] + (pc * 1000).round(3).tolist()
                                    + [round(math.degrees(math.asin(max(-1.0, min(1.0, -Rc[:, 1][2])))), 4)]
                                    + np.degrees(b.q_now(st)).round(4).tolist()
                                    + ((ball_now * 1000).round(3).tolist() if ball_now is not None else [None] * 3)
                                    + [round(float(np.interp(st.position[list(st.name).index("gripper_joint_1")],
                                                             b.kin._theta_tab, b.kin._width_tab)) * 1000, 3)])
                near_bin = np.linalg.norm(np.asarray(ep["bin_xy"]) - p_now[:2]) < 0.06
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
                    stage = ("PLACE" if near_bin and seen_b else "TRANSPORT" if seen_b else
                             "LIFT" if p_now[2] < 0.22 else "SEARCH_BIN")
                elif closed and ball_now is not None and not lifted:
                    stage = "GRASP"
                elif seen_o:
                    stage = "APPROACH_OBJECT"
                else:
                    stage = "SEARCH_OBJECT"
                if stage != (reached[-1] if reached else None):
                    reached.append(stage)
                    stage_events.append({"t": b.t_now, "tick": int(ex.ticks), "stage": stage})
                if new_ticks:
                    stage_ticks[stage] = stage_ticks.get(stage, 0) + new_ticks
                if ex.plans and "stage" not in ex.plans[-1]:
                    pl = ex.plans[-1]
                    pl["stage"], pl["tick"] = stage, ex.ticks
                    pl["jaw_gt_mm"] = round(float(jaw) * 1000, 3)
                    if ball_now is not None:
                        gap = p_now - ball_now
                        pl["tcp_to_ball_mm"] = round(float(np.linalg.norm(gap)) * 1000, 2)
                        pl["tcp_to_ball_xy_mm"] = round(float(np.linalg.norm(gap[:2])) * 1000, 2)
                        pl["tcp_to_ball_z_mm"] = round(float(gap[2]) * 1000, 2)
                if ball_now is not None and in_bin(cfg, ball_now, ep["bin_xy"], ep["bin_yaw"])[0] and jaw > 0.045:
                    stopped = "the ball is in the bin"
                    return True
                return False

            lv_ticks = exact_ticks(lv_ns * 1e-9)
            obs_spacing_ticks = exact_ticks(dt)       # the observation pair is one action step apart

            def advance_to(tick_target):
                """Step to exactly tick_target (reset-relative); fire jaw events on their own
                ticks; the camera barrier after every call; evaluate after every call. True if
                the episode ended on the way."""
                while b.tick_now() < tick_target:
                    cur = b.tick_now()
                    due = [ex.jaw_tick(ev) for ev in ex.jaw_events]
                    nxt = min([d for d in due if d > cur] + [tick_target])
                    b.step(max(1, min(batch, nxt - cur)))
                    camera_after_step()
                    ex.service_jaw()
                    if evaluate():
                        return True
                return False

            def next_obs(ref_tick):
                """The first capture tick F >= ref_tick whose frame passed the barrier and has
                a barrier-passed frame exactly one observation spacing earlier (the
                asynchronous executor's exact-pair rule), stepping on while there is none."""
                while True:
                    ok = sorted(c["tick"] for c in cam["checks"] if c["ok"] and c["tick_ns"] >= b.reset_ns)
                    oks = set(ok)
                    F = next((x for x in ok if x >= ref_tick and (x - obs_spacing_ticks) in oks), None)
                    if F is not None:
                        return F, False
                    if advance_to(b.tick_now() + batch):
                        return None, True

            def frame_ns_of_tick(k):
                c = next((c for c in cam["checks"] if c["ok"] and c["tick"] == k and c["tick_ns"] >= b.reset_ns), None)
                return None if c is None else c["frame_ns"]

            obs_tick, ended = next_obs(settle_ticks + obs_spacing_ticks)
            while not ended and ex.ticks < max_ticks and time.time() - t_wall0 < wall_limit:
                deliver_tick = obs_tick + lv_ticks
                if b.tick_now() > deliver_tick - 1:
                    b.anomalies.append({"what": "observation found after its delivery tick",
                                        "obs_tick": obs_tick, "now_tick": b.tick_now()})
                    stopped = "evaluator: observation found too late"
                    break
                try:
                    ex.observe(frame_ns_of_tick(obs_tick) * 1e-9)
                except RuntimeError as e:
                    stopped = str(e)[:40]
                    break
                if ex.obs_tick != obs_tick:
                    b.anomalies.append({"what": "observation frame tick mismatch", "want": obs_tick, "got": ex.obs_tick})
                ended = advance_to(deliver_tick)
                if ended:
                    break
                got = ex.collect()
                ex.plans[-1]["dse"] = {"obs_tick": obs_tick, "deliver_tick": deliver_tick,
                                       "collect_tick": b.tick_now(), "lv_ticks": lv_ticks,
                                       "t_obs_s": round(ex.obs_t_exact, 9), "L_v_s": lv_ns / 1e9,
                                       "T_d_s": round(b.time_of_tick(deliver_tick), 9),
                                       "inference_wall_s": ex.plans[-1]["obs"].get("dse_inference_wall_s")}
                if got:
                    ex.send()
                    consecutive = 0
                else:
                    consecutive += 1
                    if consecutive >= 8:
                        stopped = "eight plans in a row the arm could not reach"
                        break
                # the takeover step: the next update must start the new trajectory
                ended = advance_to(deliver_tick + 1)
                if got:
                    cs_ = b.cstate.get(b.ns_now)
                    ex.plans[-1]["dse"]["installed_next_tick"] = None if cs_ is None else bool(abs(cs_[0]) < 1e-9)
                    if cs_ is not None and abs(cs_[0]) > 1e-9:
                        b.anomalies.append({"what": "goal not started at the next update",
                                            "tick": b.tick_now(), "ref_tfs": cs_[0]})
                if ended:
                    break
                # cadence: the chunking contract -- steps_per_inference action steps per
                # inference (UMI eval_real.py, default 6), i.e. the next observation is that
                # many action steps after this one; each plan then commands exactly that many
                # points before the next takeover. (The earlier "next frame after delivery"
                # rule collapsed to 0.3 s once the stale-clock delay was gone: 3 points per plan.)
                nxt_tick, ended = next_obs(obs_tick + steps_per_inference * ex.ticks_per_action)
                newest = None
                if ended:
                    break
                cadence.append(round((nxt_tick - obs_tick) * PHYSICS_DT, 6))
                if len(ex.plans) % 10 == 0:
                    click.echo(f"      plan {len(ex.plans):4d}  tick {b.tick_now():6d} ({b.tick_now() * PHYSICS_DT:6.2f} s)  "
                               f"wall {time.time() - t_wall0:6.1f} s  ticks {ex.ticks}  "
                               f"k* {ex.plans[-1]['sent'][0]['k'] if ex.plans[-1].get('sent') else '-'}  "
                               f"anomalies {len(b.anomalies)}  skips {len(b.skips)}", err=False)
                ex.plans[-1]["dse"]["next_obs_tick"] = nxt_tick
                obs_tick = nxt_tick
            if time.time() - t_wall0 >= wall_limit:
                stopped = "the wall-clock safety net, not the task's clock"
            if ex.plans and ex.plans[-1].get("executed") is None:
                ex.plans[-1]["executed"] = ex.ticks - ex._ticks_at_send
            # settle the outcome on plant time, as the asynchronous rollout waits 1.5 s
            step_to_tracked(b.tick_now() + exact_ticks(1.5))
            ball = b.body_xyz("object")
            ok, local = in_bin(cfg, ball, ep["bin_xy"], ep["bin_yaw"]) \
                if ball is not None else (False, np.array([np.nan, np.nan]))
            checked, bad = lock_check(b.cycles, b.cstate, episode_t0)
            tl_rows, tl_summ = timeline_checks(ex.plans, b.cstate, b.tick_of_ns, exact_ticks(lv_ns * 1e-9), ex.jaw_log,
                                               {b.tick_of_ns(k) for k in b.skips}, ex.ticks_per_action,
                                               ex.robot_latency_ticks)
            if b.frame_log:
                st_ = sorted(b.frame_log)
                extra = {}
                if all(b.frame_log[t][1] is not None for t in st_):
                    extra["canvas"] = np.stack([b.frame_log[t][1] for t in st_])
                np.savez_compressed(frames_path / f"ep{i:02d}.npz",
                                    image_stamp_s=np.array(st_, np.float64),
                                    masked=np.stack([b.frame_log[t][0] for t in st_]),
                                    geometry=np.array(b.rgb_geometry), **extra)
            if ex.policy_io:
                lk = sorted(ex.policy_io[0]["lowdim"])
                np.savez_compressed(frames_path / f"ep{i:02d}_policy.npz",
                                    req_id=np.array([x["req_id"] for x in ex.policy_io]),
                                    t_obs=np.array([x["t_obs"] for x in ex.policy_io], np.float64),
                                    rgb_sha1=np.array([x["rgb_sha1"] for x in ex.policy_io]),
                                    action=np.stack([x["action"] for x in ex.policy_io]),
                                    **{f"lowdim_{k_}": np.stack([x["lowdim"][k_] for x in ex.policy_io]) for k_ in lk})
            ks = sorted(b.cycles)
            np.savez_compressed(frames_path / f"ep{i:02d}_cycles.npz",
                                ns=np.array(ks, np.int64),
                                names=np.array(list(b.cycles[ks[0]].name)) if ks else np.array([]),
                                q=np.array([b.cycles[k].position for k in ks]),
                                qd=np.array([b.cycles[k].velocity for k in ks]),
                                eff=np.array([b.cycles[k].effort for k in ks]),
                                cs_ns=np.array(sorted(b.cstate), np.int64),
                                cs_out=np.array([b.cstate[k][1] if b.cstate[k][1] else [np.nan] * 5
                                                 for k in sorted(b.cstate)]))
            corr_p = [x["moved_by_projection_mm"] for pl in ex.plans for x in pl["sent"]]
            corr_r = [x["turned_by_projection_deg"] for pl in ex.plans for x in pl["sent"]]
            rows.append({"episode": i, "success": ok, "steps": ex.ticks,
                         "chunks_tried": len(ex.plans), "ik_attempts": ex.ik_attempts,
                         "ik_refusals": ex.ik_refusals,
                         "ik_reachable_rate": round(1.0 - ex.ik_refusals / max(ex.ik_attempts, 1), 4),
                         "stopped_because": stopped, "stage_ticks": stage_ticks, "let_go": dropped,
                         "furthest_stage": (max(reached, key=lambda s_: ORDER.index(s_)) if reached else "none"),
                         "seconds": round(time.time() - t_wall0, 1), "grasped": ever_held,
                         "ik_failures": 0, "correction_pos_mm": corr_p, "correction_rot_deg": corr_r,
                         "trace": ex.plans, "ee_track": ee_track, "obs_wait_s": 0.0,
                         "infra_retries": 0, "infra_log": [start_info], "stage_events": stage_events,
                         "started_perturbed": pert, "jaw_log": ex.jaw_log, "latch_log": [],
                         "latched_width_mm": None, "latched_at_s": None,
                         "ball_final_mm": (ball * 1000).tolist() if ball is not None else None,
                         "offset_from_bin_mm": (local * 1000).tolist(),
                         "dse": {"L_v_s": lv_ns / 1e9, "settle_ticks": settle_ticks, "batch": batch,
                                 "cadence_s": cadence,
                                 "skips_rel_ticks": [int(round((s - episode_t0) / DT_NS)) for s in b.skips],
                                 "anomalies": b.anomalies,
                                 "camera_checks": {"frames_checked": sum(1 for c in cam["checks"] if c["tick_ns"] >= episode_t0),
                                                   "on_predicted_tick": sum(1 for c in cam["checks"] if c["tick_ns"] >= episode_t0 and c["ok"]),
                                                   "capture_ticks_rel": [int(round((c["tick_ns"] - episode_t0) / DT_NS))
                                                                         for c in cam["checks"] if c["tick_ns"] >= episode_t0][:400]},
                                 "timeline": {"summary": tl_summ, "plans": tl_rows},
                                 "lock_check": {"ticks_checked": checked, "violations": bad[:50],
                                                "n_violations": len(bad)},
                                 "inference_wall_s": [pl["obs"].get("dse_inference_wall_s") for pl in ex.plans],
                                 "step_call_wall_ms": {
                                     name: {q: round(float(np.percentile([c[j] for c in b.call_timing], q)) * 1000, 3)
                                            for q in (50, 90, 99)} if b.call_timing else None
                                     for j, name in ((1, "service"), (2, "clock_wait"), (3, "cycle_wait"))},
                                 "step_calls": len(b.call_timing),
                                 "steps_per_call_mean": round(float(np.mean([c[0] for c in b.call_timing])), 3) if b.call_timing else None}})
            rows[-1]["dse"]["gates"] = episode_gates(rows[-1])
            gt = rows[-1]["dse"]["gates"]
            click.secho(f"  [{i}] GATES {'PASS' if gt['all'] else 'FAIL'}  " + "  ".join(
                f"{k} {'ok' if v else 'FAIL'}" for k, v in gt.items() if k != "all"),
                fg="green" if gt["all"] else "red", bold=True)
            write_out(rows, invalid, partial=True)
            click.secho(f"  [{i}] {'SUCCESS' if ok else 'failed'}   {ex.ticks:3d} actions   "
                        f"{rows[-1]['seconds']:6.1f} s wall   grasped {ever_held}   skips {len(b.skips)}   "
                        f"anomalies {len(b.anomalies)}   lock violations {len(bad)}/{checked}   timeline {tl_summ}   "
                        f"cadence median {np.median(cadence) if cadence else float('nan'):.3f} s",
                        fg="green" if ok else "yellow")
    finally:
        b.pause(False)
    n_ok = sum(r_["success"] for r_ in rows)
    allp = np.concatenate([r_["correction_pos_mm"] for r_ in rows if r_["correction_pos_mm"]]) if rows else np.zeros(1)
    allr = np.concatenate([r_["correction_rot_deg"] for r_ in rows if r_["correction_rot_deg"]]) if rows else np.zeros(1)
    click.secho(f"\n{n_ok}/{len(rows)} rollouts put the ball in the bin; "
                f"{sum(r_['grasped'] for r_ in rows)} grasped it; invalid starts {len(invalid)}", bold=True)
    write_out(rows, invalid, partial=False)
    click.echo(f"wrote {out}")
    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
