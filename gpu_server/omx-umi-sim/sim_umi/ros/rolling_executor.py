"""Keep a trajectory in flight while the next one is being thought about.

The executor this replaces sent a chunk, waited for it to finish, then went
away and did inference. Measured on the running stack, the chunk was 0.4 s and
the thinking took between 0.13 and 0.58 s, so the arm stood still for about
half the wall clock and started every chunk from rest: peak 20 mm/s inside a
chunk, 5 to 7 mm/s by its end, 10 mm/s at the start of the next.

It also had the timing wrong in two ways at once. action[0] is the pose the arm
is already in -- the sampler takes the chunk as input_arr[current_idx:] while
the observation window ends at current_idx, and on the training set action[0]
sits 0.000034 mm from the last observation -- so sending it as the first
trajectory point spent a tick going nowhere. And each point was given one more
dt than it should have, so 0.3 s of motion was stretched over 0.4 s.

What upstream does instead, in scripts_real/eval_real_umi.py, is put an
absolute timestamp on every action -- obs_t + k*dt -- and throw away the ones
that are already in the past. action[0] is always among them. This does the
same, and keeps a goal in flight while the next prediction is computed, so the
seam between two plans is a replacement rather than a stop.

Velocity continuity across that seam is NOT assumed. The trace records the tool
speed through every boundary so it can be checked.
"""
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from trajectory_msgs.msg import JointTrajectoryPoint

ARM = [f"joint{i}" for i in range(1, 6)]


def _pitch(R):
    """The tool pitch the 5-DoF projection reads off the finger axis."""
    return math.degrees(math.asin(max(-1.0, min(1.0, -np.asarray(R)[:, 1][2]))))


def _six_to_R(six):
    """rot6d back to a rotation, the dataset's convention: first two ROWS."""
    a = np.asarray(six, float).reshape(2, 3)
    r0 = a[0] / np.linalg.norm(a[0])
    r1 = a[1] - (a[1] @ r0) * r0
    r1 = r1 / np.linalg.norm(r1)
    return np.stack([r0, r1, np.cross(r0, r1)])


class GraspLatch:
    """Hold the gripper shut once the camera says it actually is.

    This changes nothing the policy sees. The width in the observation stays
    the camera's live reading, the picture and the pose stay live, and the
    policy goes on predicting whatever it predicts. Only the command sent to
    the gripper is held.

    What counts as a grasp is read off the same magenta tips the policy is
    given, never off the simulator: the jaw is narrow, the policy is asking
    for narrower than it has got -- which is what contact looks like from
    outside, a command the fingers cannot follow -- and the reading has been
    steady for a moment. Frames the detector could not read are not steady
    readings; they break the run rather than extend it, because the stale
    width they would contribute is the previous one by construction.
    """

    def __init__(self, candidate_mm=40.0, close_margin_mm=2.0,
                 stable_s=0.20, stable_range_mm=1.0, require_intent=False):
        self.candidate = candidate_mm / 1000.0
        self.margin = close_margin_mm / 1000.0
        self.stable_s = stable_s
        self.range = stable_range_mm / 1000.0
        # Asking for narrower than the fingers have got is what contact looks
        # like from outside -- but it depends on the controller being asked to
        # squeeze. The collector asks for 0 mm and lets the ball stop the
        # fingers; this policy predicts a width and the fingers reach it, so
        # the test cannot fire. Measured and reported rather than tuned away.
        self.require_intent = require_intent
        self.window = []             # [(t, w)] since the last unreadable frame
        self.latched = False
        self.latched_width = None
        self.latched_at = None
        self.log = []

    def sample(self, t, width, valid, commanded, asked=None):
        """One camera frame. Returns the row it logged."""
        if not valid:
            self.window = []         # the run of readable frames is broken
            row = {"t_s": round(t, 5), "observed_mm": None, "valid": False,
                   "commanded_mm": (None if commanded is None
                                    else round(commanded * 1000, 3)),
                   "close_intent": False, "candidate": False,
                   "latched": self.latched, "span_s": 0.0, "range_mm": None}
            self.log.append(row)
            return row
        # The window is everything since the last unreadable frame -- that
        # is what "200 ms of continuous detection" means. Trimming it to the
        # stability period and then asking it to span that period is a knife
        # edge that only holds when a sample lands exactly on the boundary,
        # which is why nothing latched the first time. The range is judged
        # over the recent part; the continuity over the whole run.
        self.window.append((t, width))
        if len(self.window) > 400:
            self.window.pop(0)
        span = t - self.window[0][0]
        recent = [w for tt, w in self.window if t - tt <= self.stable_s]
        rng = (max(recent) - min(recent)) if len(recent) > 1 else None
        # against what the policy is asking for now, not against the last
        # value that passed the 3 mm send threshold: that one lags by up to
        # 3 mm and inverts the comparison.
        ref = asked if asked is not None else commanded
        intent = ref is not None and ref < width - self.margin
        cand = bool(width < self.candidate
                    and (intent or not self.require_intent))
        if (not self.latched and cand and span >= self.stable_s
                and rng is not None and rng < self.range):
            self.latched = True
            self.latched_width = width
            self.latched_at = t
        row = {"t_s": round(t, 5), "observed_mm": round(width * 1000, 3),
               "valid": True,
               "commanded_mm": (None if commanded is None
                                else round(commanded * 1000, 3)),
               "asked_mm": None if asked is None else round(asked * 1000, 3),
               "close_intent": bool(intent), "candidate": cand,
               "latched": self.latched, "span_s": round(span, 4),
               "range_mm": (None if rng is None else round(rng * 1000, 4)),
               "latched_width_mm": (None if self.latched_width is None
                                    else round(self.latched_width * 1000, 3))}
        self.log.append(row)
        return row

    def command(self, asked):
        """What to send the gripper: the policy's width, or the held one."""
        return self.latched_width if self.latched else asked


class RollingExecutor:
    """One plan in flight, the next one being computed."""

    def __init__(self, bridge, horizon_steps=8, dt=0.1, jaw_threshold_mm=3.0,
                 jaw_commit_s=0.25, robot_action_latency=0.21,
                 gripper_action_latency=0.14, action_exec_latency=0.01):
        self.b = bridge
        self.K = horizon_steps
        self.dt = dt
        self.jaw_threshold = jaw_threshold_mm / 1000.0
        # An action's timestamp says when it should be REACHED. The arm and
        # the jaw each take time to get there, so each is commanded that much
        # earlier -- upstream's exec_actions does the same, subtracting
        # robot_action_latency and gripper_action_latency from the target
        # time, with separate values because the two are different machines.
        # Measured here by sliding the commanded track against the actual one
        # until it fits: 200-220 ms for the arm, 140-150 ms for the jaw, the
        # jaw's being the better determined of the two (the residual falls
        # from 2.4 to 1.2 mm, against 8.0 to 7.4 mm for the arm, where chunk
        # disagreement dominates). An action whose commanding moment has
        # already passed cannot be reached on time and is dropped.
        self.robot_latency = robot_action_latency
        self.gripper_latency = gripper_action_latency
        self.exec_latency = action_exec_latency
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None          # (future, obs_t, p0, R0, seen)
        self.plan = []               # [(abs_t, q, width)] still in the future
        # The jaw's queue is kept in absolute time and survives a replan.
        # It used to be replaced wholesale, so an action whose moment fell
        # after the next plan arrived was discarded before it could be sent.
        # Now an action close enough to its moment is committed and cannot be
        # moved; only the far end of the queue is refreshed.
        self.jaw_commit_s = jaw_commit_s
        self.jaw_events = []         # [{t, w, committed, plan}] not yet sent
        self.jaw_log = []
        self.jaw_commanded = None
        self.jaw_asked = None
        self.ticks = 0
        self.plans = []              # the trace
        self.ik_refusals = 0
        self.ik_attempts = 0
        self._ticks_at_send = 0
        self.latch = None            # a GraspLatch, if the run wants one

    # ------------------------------------------------------------- clock --
    def now(self):
        """The plant's own clock, from the newest joint state."""
        s = self.b.state
        if s is None:
            return None
        return s.header.stamp.sec + s.header.stamp.nanosec * 1e-9

    # --------------------------------------------------------- inference --
    def start_inference(self):
        """Capture an observation and hand it to the worker."""
        # The observation pair is [t - dt, t] on the SIMULATION clock, as every
        # training row was. It used to be: take the newest frame, sleep 0.1 s
        # of wall clock, take the newest frame again -- on a 20 Hz camera that
        # gave 0.15 s pairs in 24% of plans and up to 0.45 s in 7%, while the
        # training pairs are 0.100 s. The wait is kept, so plans come at the
        # cadence they always did, but it waits for the camera's clock to move
        # one step, and both frames are then picked by stamp from the buffer.
        H = self.b.meta["obs_horizon"]
        t_entry = self.b.frame_stamp
        w0 = time.time()
        while ((self.b.frame_stamp is None or t_entry is None
                or self.b.frame_stamp < t_entry + self.dt * (H - 1) - 1e-4)
               and time.time() - w0 < 2.0):
            self.b.spin(0.002)
        # The subscription keeps only the newest image, so while the loop was
        # busy (sending a goal, collecting) a frame can be dropped and the one
        # stamped t - 0.1 may not exist. Then wait for the next frame and try
        # again: on a 20 Hz camera an exact pair exists again within two frames.
        # Never pair with whatever is nearest.
        extra_frames = 0
        deadline = time.time() + 0.5
        while True:
            t_cur = float(self.b.frame_stamp)
            wanted = [round(t_cur - (H - 1 - i) * self.dt, 6) for i in range(H)]
            have = [t for t, _ in self.b.obs_frames()]
            if all(any(abs(t - w) < 1e-4 for t in have) for w in wanted) or time.time() > deadline:
                break
            t_prev = t_cur
            while self.b.frame_stamp <= t_prev + 1e-6 and time.time() < deadline:
                self.b.spin(0.002)
            extra_frames += 1
        frames, shots, aligned = [], [], []
        for s_ in wanted:
            miss0 = self.b.width_misses
            f, _, info, st = self.b.observe_at(s_)
            frames.append(f)
            aligned.append(st)
            _, R_f = self.b.ee_now(st)
            shots.append({
                "image_stamp_s": round(float(info["image_stamp_s"]), 5),
                "requested_stamp_s": round(float(s_), 5),
                "frame_exact": bool(info["frame_exact"]),
                # the joint state the pose came from: exact, interpolated at
                # the image stamp (the collector's rule), or a flagged nearest
                "state_mode": info["mode"],
                "state_source": info.get("source"),
                "joint_stamp_s": None if info["state_stamp_s"] is None else round(float(info["state_stamp_s"]), 5),
                "image_state_skew_s": info["skew_s"],
                "state_bracket_s": (None if "bracket_s" not in info
                                    else round(info["bracket_s"][1] - info["bracket_s"][0], 5)),
                "state_debug": {k: info[k] for k in ("bracket_rel_ms", "js_within_50ms", "js_buf_span_s", "js_buf_len") if k in info},
                # what the policy is actually given, and the two things it is
                # not: the simulator's jaw, and the pixel gap it came from
                "input_width_mm": round(float(f["grip"]) * 1000, 3),
                "gt_width_mm": round(float(f["_gt_width"]) * 1000, 3),
                "pixel_gap": f["_pixel_gap"],
                # the camera could not find the tips, so the width handed to
                # the policy is the previous one, not a measurement
                "width_is_stale": bool(self.b.width_misses > miss0),
                "fk_pitch_deg": round(_pitch(R_f), 4)})
        obs_t = float(shots[-1]["image_stamp_s"])
        p0, R0 = self.b.ee_now(aligned[-1])
        seen = {n: self.b.target_visible(n) for n in ("object", "bin")}
        # the same pitch read back out of the tensor the policy receives,
        # through the start pose the relative keys are written against
        batch = self.b.build_batch(frames)
        sp, sR = self.b.start_pose
        w = np.asarray(batch["robot0_eef_rot_axis_angle_wrt_start"][0, -1])
        obs_audit = {
            "frames": shots,
            "obs_dt_s": round(shots[-1]["image_stamp_s"] - shots[0]["image_stamp_s"], 5),
            "obs_pair_exact": bool(all(x["frame_exact"] for x in shots)
                                   and all(x["state_mode"] in ("exact", "interp") for x in shots)),
            "obs_wait_s": round(time.time() - w0, 4),
            "obs_extra_wait_frames": extra_frames,
            "frames_distinct": bool(len({s["image_stamp_s"] for s in shots})
                                    == len(shots)),
            "input_width_mm": round(float(
                batch["robot0_gripper_width"][0, -1, 0]) * 1000, 3),
            "jaw_commanded_mm": (None if self.jaw_commanded is None
                                 else round(self.jaw_commanded * 1000, 3)),
            "fk_pitch_deg": round(_pitch(R0), 4),
            "input_pitch_deg": round(_pitch(sR @ _six_to_R(w)), 4),
            "width_misses_total": self.b.width_misses}
        # which request this is, so the server's encoder-input dump and the
        # frames logged on this side can be tied to the plan
        rid = getattr(self.b, "req_id", 0) + 1
        self.b.req_id = rid
        obs_audit["req_id"] = rid
        # The FOV diagnostics are NOT computed here: a render in this path
        # delayed every request by 12-23 ms, and in a rolling executor that is
        # enough to change which waypoints make it into the next plan. Only the
        # bin's ground-truth pose is recorded (a lookup in the last free-joint
        # message); arm, jaw and ball are in ee_track already, and the masks
        # are rendered after the rollout (scripts/fov/fov_postprocess.py).
        if hasattr(self.b, "body_pose"):
            obs_audit["bin_gt"] = self.b.body_pose("bin")
        fut = self.pool.submit(self.b.infer, frames, rid)
        self.pending = (fut, obs_t, p0, R0, seen, obs_audit)

    def collect(self):
        """Take a finished prediction and turn it into future waypoints."""
        from policy_bridge import decode_action
        fut, obs_t, p0, R0, seen, obs_audit = self.pending
        obs_audit["collect_start_wall"] = time.time()
        act, batch_sent = fut.result()
        self.pending = None
        # provenance, recorded only (small, no copies of images): the
        # request's wall send/receive and the low-dim input it carried
        rid = obs_audit.get("req_id")
        obs_audit["request_wall"] = getattr(self.b, "req_timing", {}).pop(rid, None)
        obs_audit["lowdim"] = {k: np.asarray(v).round(6).tolist() for k, v in batch_sent.items()
                               if k != "camera0_rgb"}
        now = self.now()
        raw, sent, dropped = [], [], 0
        plan_abs = []
        attempts, first_bad, closed = [], None, False
        fresh_plan, fresh_jaw = [], []
        for k in range(self.b.meta["action_horizon"]):
            t_k = obs_t + k * self.dt
            p_k, R_k, g_k = decode_action(act[0, k], p0, R0)
            raw.append({"k": k, "t_s": round(t_k, 4),
                        "p_mm": (p_k * 1000).round(4).tolist(),
                        "g_mm": round(float(g_k) * 1000, 3)})
            # the whole prediction in the base frame, kept so two consecutive
            # plans can be laid over the stretch of time they share
            plan_abs.append({"k": k, "t_s": round(t_k, 6),
                             "p": (p_k * 1000).round(4).tolist(),
                             "R": np.asarray(R_k).reshape(9).round(6).tolist(),
                             "g": round(float(g_k) * 1000, 4)})
            t_send = t_k - self.robot_latency
            if k == 0 or t_send <= now + self.exec_latency:
                # to be reached at t_k the arm has to be told at t_k minus its
                # latency, and that moment is already gone. action[0] always
                # is: it is the observation's own pose.
                if not closed:
                    dropped += 1
                continue
            if closed or len(fresh_plan) >= self.K:
                # the horizon is full, or the arm could not reach a waypoint
                # and everything after it is off the table -- but the plan is
                # still decoded in full, because the record of what the policy
                # asked for should not depend on what was done with it
                continue
            self.ik_attempts += 1
            q, p_got, R_got, err = self.b.project_5dof(p_k, R_k)
            attempts.append({"k": k, "reachable": bool(err["pos_err_mm"] <= 2.0),
                             "ik_pos_err_mm": round(err["pos_err_mm"], 4),
                             "from_here_mm": round(float(
                                 np.linalg.norm(p_k - p0)) * 1000, 3)})
            if err["pos_err_mm"] > 2.0:
                # Stop at the first one the arm cannot reach. Skipping it and
                # taking the next was splicing a gap into the trajectory: the
                # arm was sent from the pose before the hole to the pose after
                # it, which is a motion nobody planned. 8.5% of plans carried
                # such a gap.
                self.ik_refusals += 1
                first_bad = k
                closed = True
                continue
            w = float(np.clip(g_k, self.b.kin._width_tab.min(),
                              self.b.kin._width_tab.max()))
            fresh_plan.append((t_k, t_send, q, w))
            fresh_jaw.append({"t": t_k - self.gripper_latency, "reach_t": t_k,
                              "w": w, "committed": False,
                              "plan": len(self.plans)})
            sent.append({"k": k, "t_s": round(t_k, 4),
                         "p_mm": (p_got * 1000).round(4).tolist(),
                         "fk_mm": None,
                         "moved_by_projection_mm": round(
                             float(np.linalg.norm(p_got - p_k)) * 1000, 4),
                         "turned_by_projection_deg": round(float(np.degrees(
                             np.arccos(np.clip((np.trace(np.asarray(R_k).T
                                                         @ np.asarray(R_got)) - 1) / 2,
                                               -1, 1)))), 4),
                         "ik_pos_err_mm": round(err["pos_err_mm"], 5),
                         "q_deg": np.degrees(q).round(4).tolist()})
        if self.plans:
            # the plan being replaced ran for exactly the waypoints that were
            # retired while it was in flight
            self.plans[-1]["executed"] = self.ticks - self._ticks_at_send
        self._ticks_at_send = self.ticks
        self.plan = fresh_plan
        jaw_merge = self.merge_jaw(fresh_jaw, now)
        obs_audit["collect_end_wall"] = time.time()
        self.plans.append({"obs_t_s": round(obs_t, 4),
                           "collected_at_s": round(now, 4),
                           "inference_s": round(now - obs_t, 4),
                           "ee_at_obs_mm": (p0 * 1000).round(4).tolist(),
                           "object_visible": seen["object"],
                           "bin_visible": seen["bin"],
                           "raw_plan": raw, "sent": sent,
                           "plan_abs": plan_abs,
                           "targets_mm": [x["p_mm"] for x in sent],
                           "chunk_dz_mm": [round(plan_abs[j + 1]["p"][2]
                                                 - plan_abs[j]["p"][2], 4)
                                           for j in range(len(plan_abs) - 1)],
                           # the widths this plan asks for over the part of
                           # it that is sent. The first one alone was being
                           # reported as "the commanded width", which it is
                           # not: the later ones are commanded too.
                           "jaw_plan_mm": [round(ev["w"] * 1000, 3)
                                           for ev in fresh_jaw],
                           "jaw_cmd_mm": (round(fresh_jaw[0]["w"] * 1000, 3)
                                          if fresh_jaw else None),
                           "executed": None,
                           "attempts": attempts,
                           "first_unreachable_k": first_bad,
                           "valid_prefix": len(sent),
                           "prefix_covers_s": round(
                               (fresh_plan[-1][0] - now) if fresh_plan else 0.0, 4),
                           "robot_latency_s": self.robot_latency,
                           "gripper_latency_s": self.gripper_latency,
                           "dropped_as_past": dropped,
                           "obs": obs_audit,
                           **jaw_merge})
        return len(fresh_plan) > 0

    # ----------------------------------------------------------- command --
    def send(self):
        """Replace whatever the controller is doing with the new plan."""
        if not self.plan:
            return False
        now = self.now()
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = list(ARM)
        n = 0
        for _, t_send, q, _ in self.plan:
            off = t_send - now
            if off <= 0.02:
                continue
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start.sec = int(off)
            pt.time_from_start.nanosec = int((off % 1) * 1e9)
            traj.trajectory.points.append(pt)
            n += 1
        if n == 0:
            return False
        self.plans[-1]["goal_sent_at_s"] = round(now, 4)
        self.plans[-1]["goal_points"] = n
        self.plans[-1]["goal_span_s"] = round(self.plan[-1][1] - now, 4)
        fa = self.b.arm.send_goal_async(traj)
        rclpy.spin_until_future_complete(self.b, fa, timeout_sec=2.0)
        h = fa.result()
        ok = h is not None and h.accepted
        self.plans[-1]["goal_accepted"] = bool(ok)
        self.plans[-1]["send_end_wall"] = time.time()
        return ok

    def merge_jaw(self, fresh, now):
        """Keep what is about to happen; refresh only the far end.

        Two failure modes have to be avoided at once. Replacing the queue
        wholesale throws away an action whose instant falls between this
        replan and the next, which is how a closing jaw can be asked for and
        never commanded. Keeping everything forever does the opposite: an
        imminent action from an old plan would keep being re-armed and the
        newest information would never take effect.

        So the queue is cut at one instant: whatever is due before the new
        plan's own coverage begins -- or within the commit window, whichever
        is later -- stands, and is marked committed so it cannot be moved
        again. Everything from that instant on comes from the new plan. The
        two halves meet exactly, with no gap and no overlap.
        """
        first_new = fresh[0]["t"] if fresh else float("inf")
        horizon = max(now + self.jaw_commit_s, first_new)
        kept = []
        for ev in self.jaw_events:
            if ev["t"] <= now or ev["t"] >= horizon:
                continue
            ev["committed"] = True
            kept.append(ev)
        taken = [ev for ev in fresh if ev["t"] >= horizon]
        self.jaw_events = sorted(kept + taken, key=lambda e: e["t"])
        return {"jaw_commit_horizon_s": round(horizon - now, 4),
                "jaw_committed_kept": len(kept),
                "jaw_taken_from_new": len(taken),
                "jaw_dropped_from_new": len(fresh) - len(taken),
                "jaw_queue_after": len(self.jaw_events),
                "jaw_queue_spans_s": round(
                    self.jaw_events[-1]["t"] - now, 4) if self.jaw_events else 0.0}

    def service_jaw(self):
        """Command the jaw at the action timestamp it belongs to."""
        now = self.now()
        if now is None:
            return
        while self.jaw_events and self.jaw_events[0]["t"] <= now:
            ev = self.jaw_events.pop(0)
            asked = ev["w"]
            self.jaw_asked = asked
            w = self.latch.command(asked) if self.latch else asked
            big = (self.jaw_commanded is None
                   or abs(w - self.jaw_commanded) > self.jaw_threshold)
            row = {"t_due_s": round(ev["t"], 4), "t_fired_s": round(now, 4),
                   "late_s": round(now - ev["t"], 4),
                   "reach_t_s": round(ev.get("reach_t", ev["t"]), 4),
                   "asked_mm": round(asked * 1000, 3),
                   "width_mm": round(w * 1000, 3),
                   "held": bool(self.latch is not None and self.latch.latched),
                   "committed": ev["committed"], "from_plan": ev["plan"],
                   "sent": bool(big),
                   "actual_width_mm": round(self.b.jaw_now_gt() * 1000, 3)}
            if big:
                self.jaw_commanded = w
                self.b.jaw_async(w)
            self.jaw_log.append(row)

    def retire(self):
        """Count the waypoints whose moment has passed."""
        now = self.now()
        if now is None:
            return
        while self.plan and self.plan[0][0] <= now:
            self.plan.pop(0)
            self.ticks += 1

    def remaining(self):
        now = self.now()
        if now is None or not self.plan:
            return 0.0
        return max(0.0, self.plan[-1][0] - now)
