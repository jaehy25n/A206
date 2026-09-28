"""Drive the MuJoCo OMX-F through MoveIt, and record what came back.

    python sim_umi/ros/demo_moveit.py

Nothing here reimplements control. Targets go to MoveIt's /compute_ik -- the
KDL solver ROBOTIS configure, position_only_ik and all -- and the answer is
executed through their arm_controller and gripper_controller. What this file
adds is the sequence and the logging: /joint_states is recorded throughout and
written to outputs/moveit_demo.npz, which render_moveit_demo.py turns into
video.
"""
import math
import pathlib
import sys
import time

import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from moveit_msgs.srv import GetPositionIK
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

SIM = pathlib.Path(__file__).resolve().parents[1]
ARM = [f"joint{i}" for i in range(1, 6)]
#: object and bin as the MJCF starts them (scene.py: object_start_xy/bin_start_xy)
OBJECT = (0.08, -0.16, 0.010)
BIN = (-0.14, -0.20)
BASE = (0.0, -0.40)
PITCH = math.radians(40.0)
#: the claw holds a tabletop object at its TIPS; the cavity would put its
#: lower half inside the table (measured: -8 to -22 mm)
DEPTH = 0.095
TCP_OFFSET = np.array([0.0016, 0.09193, 0.0])


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def tcp_for(xy, z, pitch=PITCH, depth=DEPTH):
    yaw = math.atan2(-(xy[0] - BASE[0]), xy[1] - BASE[1])
    R = rot_z(yaw) @ rot_x(-pitch)
    p = np.array([xy[0], xy[1], z]) + R @ (TCP_OFFSET - np.array([0.0, depth, 0.0]))
    q = np.zeros(4)
    # matrix -> quaternion (w, x, y, z), then ROS order (x, y, z, w)
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s,
                      (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
        q = np.zeros(4)
        q[0] = (R[k, j] - R[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (R[j, i] + R[i, j]) / s
        q[1 + k] = (R[k, i] + R[i, k]) / s
    return p, np.array([q[1], q[2], q[3], q[0]])


class Demo(Node):
    def __init__(self):
        super().__init__("moveit_demo")
        self.ik = self.create_client(GetPositionIK, "/compute_ik")
        self.arm = ActionClient(self, FollowJointTrajectory,
                                "/arm_controller/follow_joint_trajectory")
        self.grip = ActionClient(self, GripperCommand,
                                 "/gripper_controller/gripper_cmd")
        self.log = []
        self.create_subscription(JointState, "/joint_states", self._on_state, 50)
        for c, name in ((self.ik, "/compute_ik"), (self.arm, "arm_controller"),
                        (self.grip, "gripper_controller")):
            ok = (c.wait_for_service(timeout_sec=20.0) if hasattr(c, "wait_for_service")
                  else c.wait_for_server(timeout_sec=20.0))
            if not ok:
                raise SystemExit(f"{name} never came up")
        self.state = None

    def _on_state(self, msg):
        self.state = msg
        self.log.append((time.time(), list(msg.name), list(msg.position)))

    def spin(self, seconds):
        t0 = time.time()
        while time.time() - t0 < seconds:
            rclpy.spin_once(self, timeout_sec=0.02)

    def solve(self, pos, quat):
        req = GetPositionIK.Request()
        req.ik_request.group_name = "arm"
        req.ik_request.ik_link_name = "end_effector_link"
        req.ik_request.avoid_collisions = True
        req.ik_request.timeout.sec = 1
        req.ik_request.pose_stamped.header.frame_id = "link0"
        p = req.ik_request.pose_stamped.pose
        p.position.x, p.position.y, p.position.z = [float(v) for v in pos]
        (p.orientation.x, p.orientation.y,
         p.orientation.z, p.orientation.w) = [float(v) for v in quat]
        if self.state is not None:
            req.ik_request.robot_state.joint_state = self.state
        fut = self.ik.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        res = fut.result()
        if res is None or res.error_code.val != 1:
            return None
        names = list(res.solution.joint_state.name)
        pos_ = list(res.solution.joint_state.position)
        return [pos_[names.index(j)] for j in ARM]

    def move(self, q, seconds=3.0, label=""):
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ARM
        pt = JointTrajectoryPoint()
        pt.positions = [float(v) for v in q]
        pt.time_from_start.sec = int(seconds)
        pt.time_from_start.nanosec = int((seconds % 1) * 1e9)
        goal.trajectory.points = [pt]
        fut = self.arm.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        h = fut.result()
        if h is None or not h.accepted:
            print(f"   {label}: goal rejected")
            return False
        rf = h.get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=seconds + 8.0)
        r = rf.result()
        ok = r is not None and r.result.error_code == 0
        print(f"   {label}: {'reached' if ok else 'FAILED'}")
        return ok

    def jaw(self, position, label=""):
        g = GripperCommand.Goal()
        g.command.position = float(position)
        g.command.max_effort = 2.0
        fut = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        h = fut.result()
        rf = h.get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=10.0)
        r = rf.result()
        print(f"   {label}: reached={r.result.reached_goal} "
              f"stalled={r.result.stalled} pos={r.result.position:.4f}")
        self.spin(0.5)


def main():
    rclpy.init()
    n = Demo()
    n.spin(1.0)

    ox, oy, oz = OBJECT
    steps = [
        ("open the jaw", "jaw", 0.47),
        ("stand off above the object", "pose", ((ox, oy), oz + 0.09)),
        ("descend to the tips", "pose", ((ox, oy), oz)),
        ("close on the object", "jaw", 0.0),
        ("lift", "pose", ((ox, oy), oz + 0.12)),
        ("carry over the bin", "pose", (BIN, 0.20)),
        ("release", "jaw", 0.47),
        ("retreat", "pose", (BIN, 0.26)),
    ]
    marks = []
    for label, kind, arg in steps:
        print(f"-> {label}")
        marks.append((len(n.log), label))
        if kind == "jaw":
            n.jaw(arg, label)
            continue
        (xy, z) = arg
        pos, quat = tcp_for(xy, z)
        q = n.solve(pos, quat)
        if q is None:
            print(f"   {label}: /compute_ik found nothing for "
                  f"({pos[0]:+.3f}, {pos[1]:+.3f}, {pos[2]:+.3f})")
            continue
        n.move(q, 3.0, label)
        n.spin(0.4)

    out = SIM / "outputs" / "moveit_demo.npz"
    names = n.log[0][1]
    t = np.array([r[0] for r in n.log])
    q = np.array([r[2] for r in n.log])
    np.savez(out, t=t - t[0], names=np.array(names), q=q,
             marks=np.array([f"{i}:{l}" for i, l in marks]))
    print(f"\nrecorded {len(t)} states over {t[-1]-t[0]:.1f} s -> {out}")
    rclpy.shutdown()


if __name__ == "__main__":
    main()
