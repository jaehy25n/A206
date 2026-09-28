"""Isolated audit of paused stepping and of the arm controller's trajectory
timing -- the ground a deterministic sim-time evaluator would stand on.

    source sim_umi/ros/env_overlay.sh
    python sim_umi/scripts/dse/step_audit.py --out <dir> [--repeats 2]

Never during an evaluation: the plant is paused for the test and resumed at the
end (also on error). Each case starts from the same state -- the arm reset by
ResetWorld to q0 = HOME (free bodies to their initial poses, the jaw as it
stands) with a hold goal at q0 taken while paused, then 100 steps to settle -- and then gets
a joint1 move of +0.10 rad.

Stepping is one physics step (2 ms) per StepSimulation call. After each call
the audit waits for the /clock tick and for the arm controller's
controller_state stamped with that tick (the controller update that ran on
it), then waits --settle-ms of wall time before the next step. Recorded per
step: the tick, whether an update was seen on it, the update's reference
(sampled trajectory), output (command written) and feedback (state read), the
/joint_states and camera stamps that fell in it.

Cases:
  A  header.stamp = 0, points at tfs 0.3 / 0.6 s   start = which update?
  B  header.stamp = now + 0.2 s (future)            interpolate from where, reach when?
  C  header.stamp = now - 0.4 s: first point past,  jump, clip or interpolate?
     last point in the future
  D  header.stamp = now - 1.0 s, end in the past    rejected?
  A0 = A with --settle-ms 0                         does the one-step offset move?
  A5 = A with 5 steps per StepSimulation call       does the controller keep up?
Every case runs --repeats times; a deterministic offset means the feedback
sequences of the repeats are bitwise identical.
"""
import json
import pathlib
import threading
import time

import click
import rclpy
from builtin_interfaces.msg import Duration, Time as TimeMsg
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTrajectoryControllerState
from mujoco_ros2_control_msgs.srv import ResetWorld, SetPause, StepSimulation
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectoryPoint

ARM = ["joint1", "joint2", "joint3", "joint4", "joint5"]
GRIP = ["gripper_joint_1", "gripper_joint_2"]
HOME_Q = [0.728554, -0.484702, -0.429863, 1.699963, 0.0]     # collect_demos.HOME_Q, the rollout's HOME
SIM = "/mujoco_ros2_control_node"
DT = 0.002


def sec(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


def tmsg(t):
    s = int(t)
    return TimeMsg(sec=s, nanosec=int(round((t - s) * 1e9)))


def dur(t):
    s = int(t)
    return Duration(sec=s, nanosec=int(round((t - s) * 1e9)))


class Audit:
    def __init__(self):
        rclpy.init()
        self.n = rclpy.create_node("step_audit", parameter_overrides=[Parameter("use_sim_time", value=True)])
        self.lock = threading.Lock()
        self.clock, self.cs, self.js, self.img = [], [], [], []
        self.last_js = {}
        q = QoSProfile(depth=5000, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)
        self.n.create_subscription(Clock, "/clock", lambda m: self._add(self.clock, (sec(m.clock), time.time())), q)
        self.n.create_subscription(JointTrajectoryControllerState, "/arm_controller/controller_state", self._cs, q)
        self.n.create_subscription(JointState, "/joint_states", self._js, q)
        # the hardware interface's read(): the simulator's qpos / qvel / qfrc_actuator as of the
        # last physics step, published on its own (independent) realtime publisher
        self.act = []
        self.n.create_subscription(JointState, "/mujoco_actuators_states", self._act, q)
        self.n.create_subscription(Image, "/wrist_camera/image_raw",
                                   lambda m: self._add(self.img, sec(m.header.stamp)), q)
        self.pause_c = self.n.create_client(SetPause, f"{SIM}/set_pause")
        self.step_c = self.n.create_client(StepSimulation, f"{SIM}/step_simulation")
        self.reset_c = self.n.create_client(ResetWorld, f"{SIM}/reset_world")
        self.arm = ActionClient(self.n, FollowJointTrajectory, "/arm_controller/follow_joint_trajectory")
        self.ex = MultiThreadedExecutor(num_threads=4)
        self.ex.add_node(self.n)
        threading.Thread(target=self.ex.spin, daemon=True).start()
        for c in (self.pause_c, self.step_c, self.reset_c):
            assert c.wait_for_service(timeout_sec=10), c.srv_name
        assert self.arm.wait_for_server(timeout_sec=10)

    def _add(self, L, v):
        with self.lock:
            L.append(v)

    def _cs(self, m):
        self._add(self.cs, {"t": sec(m.header.stamp), "names": list(m.joint_names),
                            "ref": list(m.reference.positions), "out": list(m.output.positions),
                            "fb": list(m.feedback.positions), "fbv": list(m.feedback.velocities),
                            "ref_tfs": m.reference.time_from_start.sec + m.reference.time_from_start.nanosec * 1e-9})

    def _act(self, m):
        self._add(self.act, {"t": sec(m.header.stamp), "names": list(m.name), "q": list(m.position),
                             "qd": list(m.velocity), "eff": list(m.effort)})

    def _js(self, m):
        d = dict(zip(m.name, m.position))
        self.last_js = d
        if all(j in d for j in ARM):
            self._add(self.js, (sec(m.header.stamp), [d[j] for j in ARM]))

    @staticmethod
    def wait(fut, timeout=10.0):
        t0 = time.time()
        while not fut.done():
            if time.time() - t0 > timeout:
                raise TimeoutError
            time.sleep(0.0005)
        return fut.result()

    def now(self):
        with self.lock:
            return self.clock[-1][0] if self.clock else None

    def pause(self, p):
        r = self.wait(self.pause_c.call_async(SetPause.Request(paused=p)))
        time.sleep(0.2)
        if p:
            self.drain_clock()
        return r.success

    def drain_clock(self, quiet=0.3, limit=10.0):
        """Until no new /clock tick has arrived for `quiet` s: a paused plant publishes none, so
        whatever still comes in was queued from before (a barrier, not a timing decision)."""
        t0 = time.time()
        with self.lock:
            n = len(self.clock)
        q0 = time.time()
        while time.time() - t0 < limit:
            time.sleep(0.01)
            with self.lock:
                m = len(self.clock)
            if m != n:
                n, q0 = m, time.time()
            elif time.time() - q0 > quiet:
                return

    def goal(self, points, stamp=0.0):
        g = FollowJointTrajectory.Goal()
        g.trajectory.joint_names = ARM
        if stamp:
            g.trajectory.header.stamp = tmsg(stamp)
        for tfs, q in points:
            p = JointTrajectoryPoint()
            p.positions = [float(v) for v in q]
            p.time_from_start = dur(tfs)
            g.trajectory.points.append(p)
        h = self.wait(self.arm.send_goal_async(g))
        time.sleep(0.05)            # accepted callbacks settle while paused
        return bool(h.accepted)

    def step(self, n_steps, settle_ms):
        # the tick is counted here, not read back: /clock is try-published and may be skipped
        t_prev = self.t_sim
        w0 = time.time()
        r = self.wait(self.step_c.call_async(StepSimulation.Request(steps=n_steps)), timeout=30)
        w1 = time.time()
        for _ in range(n_steps):
            self.t_sim += DT
        t = self.t_sim
        t0 = time.time()
        while (self.now() or 0) < t - 1e-6 and time.time() - t0 < 0.1:
            time.sleep(0.0002)
        self.clock_seen = (self.now() or 0) >= t - 1e-6
        w2 = time.time()
        t0 = time.time()
        got_msgs = False
        while time.time() - t0 < 0.05:
            with self.lock:
                if (any(abs(c["t"] - t) < 1e-6 for c in self.cs[-20:])
                        and any(abs(x["t"] - t) < 1e-6 for x in self.act[-20:])):
                    got_msgs = True
                    break
            time.sleep(0.0002)
        w3 = time.time()
        time.sleep(settle_ms / 1000.0)
        # wall time of this call, by part: the StepSimulation round trip (request -> the plant
        # has done n steps -> response), the /clock of the last tick reaching this node, the
        # controller cycle's two messages for it (50 ms cap: a skipped tick has none)
        self.last_timing = {"steps": n_steps, "service_ms": round((w1 - w0) * 1000, 3),
                            "clock_wait_ms": round((w2 - w1) * 1000, 3),
                            "cycle_msgs_wait_ms": round((w3 - w2) * 1000, 3), "cycle_msgs_seen": got_msgs,
                            "total_ms": round((time.time() - w0) * 1000, 3)}
        return r.success, t_prev, t, self.clock_seen

    def window(self, t_prev, t):
        with self.lock:
            cs = [c for c in self.cs if t_prev + 1e-7 < c["t"] <= t + 1e-7]
            js = [s for s, _ in self.js if t_prev + 1e-7 < s <= t + 1e-7]
            im = [s for s in self.img if t_prev + 1e-7 < s <= t + 1e-7]
        return cs, js, im

    def reset_to(self, q0, gripper):
        self.goal([(0.05, q0)])
        req = ResetWorld.Request()
        req.state_overrides.joint_states.name = ARM + list(gripper)
        req.state_overrides.joint_states.position = list(q0) + list(gripper.values())
        req.state_overrides.joint_states.velocity = [0.0] * (len(ARM) + len(gripper))
        r = self.wait(self.reset_c.call_async(req))
        assert r.success, r.message
        time.sleep(0.05)


def run_case(a, name, q0, grip, n_steps, per_call, settle_ms, stamp_fn):
    a.reset_to(q0, grip)
    a.t_sim = a.now()
    for _ in range(100):
        a.step(1, 2.0)
    t_goal = a.t_sim
    q1 = list(q0)
    q1[0] += 0.10
    stamp = stamp_fn(t_goal)
    pts = [(0.3, [q0[0] + 0.05] + list(q0[1:])), (0.6, q1)]
    accepted = a.goal(pts, stamp)
    rows = []
    for _ in range(n_steps // per_call):
        ok, tp, t, seen = a.step(per_call, settle_ms)
        cs, js, im = a.window(tp, t)
        c = cs[-1] if cs else None
        rows.append({"t_rel_ms": round((t - t_goal) * 1000, 3), "step_ok": ok, "clock_seen": seen, "updates": len(cs),
                     "update_rel_ms": [round((x["t"] - t_goal) * 1000, 3) for x in cs],
                     "ref_j1": c["ref"][0] if c and c["ref"] else None,
                     "out_j1": c["out"][0] if c and c["out"] else None,
                     "fb_j1": c["fb"][0] if c and c["fb"] else None,
                     "js_rel_ms": [round((s - t_goal) * 1000, 3) for s in js],
                     "img_rel_ms": [round((s - t_goal) * 1000, 3) for s in im]})
    t_end = a.t_sim
    with a.lock:
        raw = {"cs": [c for c in a.cs if t_goal - 0.21 < c["t"] <= t_end + 1e-7],
               "act": [x for x in a.act if t_goal - 0.21 < x["t"] <= t_end + 1e-7],
               "clock": [c for c, _ in a.clock if t_goal - 0.21 < c <= t_end + 1e-7]}
    moved = next((r["t_rel_ms"] for r in rows if r["ref_j1"] is not None and abs(r["ref_j1"] - q0[0]) > 1e-7), None)
    return {"case": name, "t_goal": t_goal, "stamp_rel_s": None if not stamp else round(stamp - t_goal, 6),
            "accepted": accepted, "settle_ms": settle_ms, "steps_per_call": per_call,
            "first_ref_departure_rel_ms": moved, "rows": rows, "raw": raw}


@click.command()
@click.option("--out", required=True)
@click.option("--repeats", default=2)
@click.option("--steps", default=400)
@click.option("--cases", "case_list", default="A,B,C,D,A0,A5")
def main(out, repeats, steps, case_list):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=False)
    a = Audit()
    time.sleep(1.0)
    q0 = list(HOME_Q)
    grip = {g: float(a.last_js[g]) for g in GRIP if g in a.last_js}     # the jaw stays as it stands
    assert a.cs and grip, "no controller_state / joint_states"
    cases = {
        "A": (1, 2.0, lambda t: 0.0),
        "B": (1, 2.0, lambda t: t + 0.2),
        "C": (1, 2.0, lambda t: t - 0.4),     # first point 0.1 s in the past, last 0.2 s ahead
        "D": (1, 2.0, lambda t: t - 1.0),
        "A0": (1, 0.0, lambda t: 0.0),
        "A5": (5, 2.0, lambda t: 0.0),
    }
    cases = {k: v for k, v in cases.items() if k in case_list.split(",")}
    res = {"q0": q0, "cases": {}}
    assert a.pause(True)
    try:
        for name, (per_call, settle, fn) in cases.items():
            res["cases"][name] = [run_case(a, name, q0, grip, steps, per_call, settle, fn) for _ in range(repeats)]
            R = res["cases"][name]
            same = all(x["rows"] == R[0]["rows"] for x in R[1:]) if len(R) > 1 else None
            fb_same = all([r["fb_j1"] for r in x["rows"]] == [r["fb_j1"] for r in R[0]["rows"]] for x in R[1:])
            print(f"{name}: accepted {[x['accepted'] for x in R]}  first ref departure (ms after goal) "
                  f"{[x['first_ref_departure_rel_ms'] for x in R]}  steps w/o update "
                  f"{[sum(r['updates'] == 0 for r in x['rows']) for x in R]}  repeats identical: rows {same}, "
                  f"feedback {fb_same}", flush=True)
    finally:
        a.pause(False)
        (out / "step_audit.json").write_text(json.dumps(res, indent=1))
    a.goal([(0.5, q0)])
    print(f"-> {out / 'step_audit.json'}; plant resumed", flush=True)
    a.ex.shutdown()
    a.n.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
