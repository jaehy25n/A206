"""Tip grasp: MoveIt where it helps, our own 5-DoF projection where it must.

    python sim_umi/ros/pick_moveit.py

The split is deliberate.

  * Travel (home -> pre-grasp) is a MoveIt joint-space plan. Collision
    avoidance and time parameterization are theirs.
  * The approach and the lift are NOT. A joint-space plan between two
    configurations is free to bend the end effector's path on the way, and
    when the path is "descend onto the object" that bend is the whole task.
    So the EE path is built first, in a straight line, and each waypoint is
    projected onto what five joints can hold -- position exactly, pitch as
    asked, yaw taken from the base angle because the arm has no choice --
    and turned into a joint waypoint by the planar IK.

Every waypoint is then checked against MoveIt's own /check_state_validity
(joint limits, self-collision, the scene) before anything is executed, and the
sequence goes to ROBOTIS's arm_controller as one trajectory.

This is the same adapter the policy will need at run time: the network emits an
EE delta, and something has to turn that into a pose this arm can actually
hold. /compute_ik cannot do it -- ROBOTIS configure it position-only, so the
orientation in a pose goal is simply not part of what it solves, which is why
the first demo closed its jaw on air at joint5 = -2.72 rad.
"""
import math
import pathlib
import sys
import time

import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (Constraints, JointConstraint, RobotState)
from moveit_msgs.srv import GetStateValidity
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

SIM = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "src"))

import mujoco  # noqa: E402
from collector import Collector  # noqa: E402
from scene import SceneConfig  # noqa: E402
sys.path.insert(0, str(SIM / "ros"))
import scene_objects  # noqa: E402

ARM = [f"joint{i}" for i in range(1, 6)]
#: Measured on the 50 mm ball: the claw clears the table by 5.6 mm here and
#: the ball lands in the middle of the cavity.
PITCH = math.radians(10.0)
DEPTH = 0.065                  # along the finger axis: the cavity, not the tips
STANDOFF = 0.07
LIFT = 0.12
#: rad/s. joint_limits.yaml allows 5.0 and scales it by 0.1 by default.
SPEED = 0.5


class Pick(Node):
    def __init__(self):
        super().__init__("tip_pick")
        self.cfg = SceneConfig()
        self.col = Collector(str(SIM / "mjcf" / "collector_scene.xml"), cfg=self.cfg)
        self.obj_xy = self.cfg.object_start_xy
        #: a ball resting on the table has its centre one radius up, and that
        #: is also where the claw's cavity should meet it
        self.obj_z = float(self.cfg.object_size[2])

        self.state = None
        self.log = []
        self.create_subscription(JointState, "/joint_states", self._state, 50)
        self.valid = self.create_client(GetStateValidity, "/check_state_validity")
        self.plan = ActionClient(self, MoveGroup, "/move_action")
        self.arm = ActionClient(self, FollowJointTrajectory,
                                "/arm_controller/follow_joint_trajectory")
        self.grip = ActionClient(self, GripperCommand,
                                 "/gripper_controller/gripper_cmd")
        assert self.valid.wait_for_service(timeout_sec=30.0), "no /check_state_validity"
        assert self.plan.wait_for_server(timeout_sec=30.0), "no /move_action"
        assert self.arm.wait_for_server(timeout_sec=30.0), "no arm_controller"
        assert self.grip.wait_for_server(timeout_sec=30.0), "no gripper_controller"
        # the table, the paper and the bin, so that /check_state_validity is
        # answering about this room and not about a robot in a void
        ids = scene_objects.apply(self, self.cfg)
        print(f"planning scene: {', '.join(ids)}")

    # ------------------------------------------------------------ plumbing --
    def _state(self, msg):
        self.state = msg
        self.log.append((time.time(), list(msg.name), list(msg.position)))

    def spin(self, seconds):
        t0 = time.time()
        while time.time() - t0 < seconds:
            rclpy.spin_once(self, timeout_sec=0.02)

    def q_now(self):
        n = list(self.state.name)
        return np.array([self.state.position[n.index(j)] for j in ARM])

    def jaw_now(self):
        n = list(self.state.name)
        q = self.state.position[n.index("gripper_joint_1")]
        return float(np.interp(q, self.col._theta_tab, self.col._width_tab))

    # ------------------------------------------------------- the projection --
    def ee_target(self, z, depth=DEPTH):
        """TCP pose that puts the point `depth` along the finger axis at the
        object's (x, y) and this height."""
        return self.col.grasp_tcp_target(self.obj_xy, z, PITCH, depth)

    def project(self, tcp_pos):
        """EE pose -> the joints this arm can hold. Returns (q, errors)."""
        q, ep, er, oop = self.col.solve_ik_best(tcp_pos, PITCH)
        return q, dict(pos_err_mm=ep * 1000, pitch_err_deg=math.degrees(er),
                       out_of_plane_mm=oop * 1000)

    def fk(self, q):
        d = self.col._ik
        d.qpos[:] = self.col.data.qpos
        for a, v in zip(self.col.arm_qadr, q):
            d.qpos[a] = v
        mujoco.mj_kinematics(self.col.model, d)
        return d.site_xpos[self.col.tcp_sid].copy()

    def check(self, q):
        req = GetStateValidity.Request()
        req.group_name = "arm"
        rs = RobotState()
        rs.joint_state.name = ARM
        rs.joint_state.position = [float(v) for v in q]
        rs.is_diff = True
        req.robot_state = rs
        fut = self.valid.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        r = fut.result()
        return (r is not None and r.valid), (r.contacts if r is not None else [])

    # ------------------------------------------------------------ execution --
    def moveit_to(self, q, label):
        goal = MoveGroup.Goal()
        goal.request.group_name = "arm"
        goal.request.num_planning_attempts = 10
        goal.request.allowed_planning_time = 5.0
        goal.request.max_velocity_scaling_factor = 0.3
        goal.request.max_acceleration_scaling_factor = 0.3
        c = Constraints()
        for name, v in zip(ARM, q):
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = float(v)
            jc.tolerance_above = jc.tolerance_below = 0.01
            jc.weight = 1.0
            c.joint_constraints.append(jc)
        goal.request.goal_constraints.append(c)
        goal.planning_options.plan_only = False
        fut = self.plan.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10.0)
        h = fut.result()
        if h is None or not h.accepted:
            print(f"   {label}: MoveIt rejected the goal")
            return False
        rf = h.get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=60.0)
        ok = rf.result() is not None and rf.result().result.error_code.val == 1
        print(f"   {label}: MoveIt {'planned and executed' if ok else 'FAILED'}")
        self.spin(0.3)
        return ok

    def run_waypoints(self, qs, label):
        """One trajectory, timed off the largest joint move per segment."""
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = ARM
        t = 0.5
        prev = self.q_now()
        for q in qs:
            t += max(0.12, float(np.abs(np.asarray(q) - prev).max()) / SPEED)
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start.sec = int(t)
            pt.time_from_start.nanosec = int((t % 1) * 1e9)
            traj.trajectory.points.append(pt)
            prev = np.asarray(q)
        fut = self.arm.send_goal_async(traj)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10.0)
        h = fut.result()
        if h is None or not h.accepted:
            print(f"   {label}: arm_controller rejected the trajectory")
            return False
        rf = h.get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=t + 15.0)
        r = rf.result()
        ok = r is not None and r.result.error_code == 0
        print(f"   {label}: {len(qs)} waypoints over {t:.1f} s -> "
              f"{'reached' if ok else 'FAILED'}")
        self.spin(0.3)
        return ok

    def jaw(self, position, label):
        g = GripperCommand.Goal()
        g.command.position = float(position)
        g.command.max_effort = 0.5   # the measured current limit for this ball
        fut = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10.0)
        rf = fut.result().get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=15.0)
        r = rf.result().result
        self.spin(0.6)
        print(f"   {label}: reached={r.reached_goal} stalled={r.stalled}  "
              f"jaw {self.jaw_now()*1000:5.2f} mm")
        return r


def straight_line(a, b, n):
    """EE waypoints from a to b, evenly spaced. a is not repeated."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def main():
    rclpy.init()
    p = Pick()
    p.spin(1.5)
    rows = []

    def record(stage, desired, q, extra=None):
        fk = p.fk(q) if q is not None else np.full(3, np.nan)
        row = {"stage": stage,
               "desired_ee": None if desired is None else np.round(desired, 5).tolist(),
               "q": None if q is None else np.round(q, 5).tolist(),
               "fk_ee": np.round(fk, 5).tolist(),
               "jaw_mm": round(p.jaw_now() * 1000, 3)}
        if extra:
            row.update(extra)
        rows.append(row)
        return row

    grasp_ee = p.ee_target(p.obj_z)
    pre_ee = p.ee_target(p.obj_z + STANDOFF)
    lift_ee = p.ee_target(p.obj_z + LIFT)

    # The model starts with the jaw shut -- MJCF qpos is zero and there is no
    # reset hook -- so a descent that skips this arrives closed and the grasp
    # closes on nothing.
    print("-> open the jaw")
    p.jaw(p.col.grip_hi, "open")
    record("opened", None, p.q_now())

    print("-> pre-grasp, by MoveIt joint-space planning")
    q_pre, err = p.project(pre_ee)
    ok, contacts = p.check(q_pre)
    print(f"   projection: pos {err['pos_err_mm']:.3f} mm, pitch "
          f"{err['pitch_err_deg']:.3f} deg, off-plane {err['out_of_plane_mm']:.3f} mm"
          f"   state valid: {ok}")
    record("pregrasp_target", pre_ee, q_pre, {"valid": ok, **err})
    if not ok:
        print("   pre-grasp state is not valid; stopping")
        return
    p.moveit_to(q_pre, "travel to pre-grasp")
    record("pregrasp_reached", pre_ee, p.q_now())

    # One outer-loop pose correction, in free space only. A P servo settles
    # where kp*(q_cmd - q) balances the load, so the pose it holds is not the
    # pose it was given; measuring FK(q_actual) and re-aiming makes the servo
    # carry the offset it needs. It is done HERE and nowhere else: after
    # contact, the same correction reads the object's resistance as "not there
    # yet" and pushes harder, which is how a 60-100 N squeeze happens.
    fk_now = p.fk(p.q_now())
    err = np.asarray(pre_ee) - fk_now
    print(f"   free-space pose error {np.round(err*1000, 2)} mm "
          f"(|e| {np.linalg.norm(err)*1000:.2f} mm) -> one correction")
    q_fix, err2 = p.project(np.asarray(pre_ee) + err)
    ok, _ = p.check(q_fix)
    record("pregrasp_correction", np.asarray(pre_ee) + err, q_fix,
           {"valid": ok, "applied_mm": np.round(err * 1000, 3).tolist(), **err2})
    if ok:
        p.run_waypoints([q_fix], "pose correction")
        left = np.asarray(pre_ee) - p.fk(p.q_now())
        print(f"   after correction: {np.linalg.norm(left)*1000:.2f} mm")
        record("pregrasp_corrected", pre_ee, p.q_now())
    bias = np.asarray(pre_ee) + err - np.asarray(pre_ee)   # the offset that worked

    print("-> descend, EE straight line projected waypoint by waypoint")
    qs, bad = [], 0
    for i, ee in enumerate(straight_line(pre_ee, grasp_ee, 12)):
        # the correction is carried, not recomputed: no measurement after this
        q, err = p.project(np.asarray(ee) + bias)
        ok, _ = p.check(q)
        bad += (not ok) or err["pos_err_mm"] > 1.0
        qs.append(q)
        record(f"descend_{i:02d}", ee, q, {"valid": ok, **err})
    print(f"   12 waypoints projected, {bad} rejected by validation or IK")
    if bad:
        print("   refusing to execute a path with an invalid waypoint")
        return
    p.run_waypoints(qs, "descend")
    record("descend_reached", grasp_ee, p.q_now())

    print("-> close")
    r = p.jaw(0.0, "close")   # contact from here on: no more pose correction
    record("closed", grasp_ee, p.q_now(),
           {"stalled": bool(r.stalled), "reached_goal": bool(r.reached_goal),
            "effort": float(r.effort)})

    print("-> lift, same construction")
    qs = []
    for i, ee in enumerate(straight_line(grasp_ee, lift_ee, 10)):
        q, err = p.project(np.asarray(ee) + bias)
        ok, _ = p.check(q)
        qs.append(q)
        record(f"lift_{i:02d}", ee, q, {"valid": ok, **err})
    p.run_waypoints(qs, "lift")
    record("lifted", lift_ee, p.q_now())
    p.spin(1.0)

    bin_xy = p.cfg.bin_start_xy
    carry_ee = p.col.grasp_tcp_target(bin_xy, 0.20, PITCH, DEPTH)
    print("-> carry over the bin")
    qs, bad = [], 0
    for i, ee in enumerate(straight_line(lift_ee, carry_ee, 14)):
        q, err = p.project(np.asarray(ee) + bias)
        ok, _ = p.check(q)
        bad += (not ok) or err["pos_err_mm"] > 1.0
        qs.append(q)
        record(f"carry_{i:02d}", ee, q, {"valid": ok, **err})
    print(f"   14 waypoints, {bad} rejected")
    if not bad:
        p.run_waypoints(qs, "carry")
    record("carried", carry_ee, p.q_now())

    # How deep can the claw go into the bin? Ask the scene rather than pick a
    # number: walk down and keep the last height MoveIt still calls valid.
    print("-> descend into the bin")
    deepest, qs = None, []
    for z in np.arange(0.20, 0.055, -0.01):
        ee = p.col.grasp_tcp_target(bin_xy, float(z), PITCH, DEPTH)
        q, err = p.project(np.asarray(ee) + bias)
        ok, _ = p.check(q)
        record(f"place_probe_{int(z*1000):03d}", ee, q, {"valid": ok, **err})
        if not ok or err["pos_err_mm"] > 1.0:
            break
        deepest, qs = (float(z), ee, q), qs + [q]
    if deepest is None:
        print("   nothing below the rim is valid; releasing from above")
        release_ee = carry_ee
    else:
        z, release_ee, _ = deepest
        print(f"   deepest valid TCP height inside the bin: {z*1000:.0f} mm "
              f"({len(qs)} waypoints)")
        p.run_waypoints(qs, "descend into the bin")
    record("above_release", release_ee, p.q_now())

    print("-> release")
    p.jaw(p.col.grip_hi, "release")
    record("released", release_ee, p.q_now())

    print("-> retract")
    out_ee = p.col.grasp_tcp_target(bin_xy, 0.22, PITCH, DEPTH)
    qs = []
    for i, ee in enumerate(straight_line(release_ee, out_ee, 8)):
        q, err = p.project(np.asarray(ee) + bias)
        ok, _ = p.check(q)
        qs.append(q)
        record(f"retract_{i:02d}", ee, q, {"valid": ok, **err})
    p.run_waypoints(qs, "retract")
    record("retracted", out_ee, p.q_now())
    p.spin(1.0)

    out = SIM / "outputs" / "pick_place.npz"
    t = np.array([r[0] for r in p.log])
    np.savez(out, t=t - t[0], names=np.array(p.log[0][1]),
             q=np.array([r[2] for r in p.log]),
             stages=np.array([str(r) for r in rows]))
    print(f"\njaw at the end: {p.jaw_now()*1000:.2f} mm "
          f"(0 means it closed on nothing; the object is 20 mm)")
    print(f"recorded {len(t)} states -> {out}")
    rclpy.shutdown()


if __name__ == "__main__":
    main()
