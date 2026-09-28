"""Is the published image really the plant's, or just the arm's?

    python sim_umi/ros/check_camera_topic.py

Three things, in the order they can go wrong:

  1. arm only        the image changes when the joints do, and the two agree
  2. grasp and lift  the BALL moves in the image, which the old mirror could
                     never show: it rendered a second model whose ball sat
                     wherever the MJCF started it
  3. release         the ball falls, and consecutive frames follow it

The ball's true pose comes from the free-joint publisher and is used for
CHECKING only -- it is compared against where the ball appears in the image.
"""
import math
import pathlib
import sys
import time

SIM = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import cv2
import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectoryPoint

from collector import Collector
from scene import SceneConfig

ARM = [f"joint{i}" for i in range(1, 6)]


class Watch(Node):
    def __init__(self):
        super().__init__("camera_topic_check")
        self.cfg = SceneConfig()
        self.kin = Collector(str(SIM / "mjcf" / "collector_scene.xml"), cfg=self.cfg)
        self.img = None
        self.img_stamp = None
        self.js = None
        self.balls = None
        self.create_subscription(Image, "/wrist_camera/image_raw", self._img, 10)
        self.create_subscription(JointState, "/joint_states", self._js, 50)
        try:
            from mujoco_ros2_control_msgs.msg import FreeJointStateArray
            self.create_subscription(
                FreeJointStateArray,
                "/free_joint_state_publisher/free_joint_states", self._free, 10)
        except ImportError:
            print("   (free joint messages unavailable)")
        self.arm = ActionClient(self, FollowJointTrajectory,
                                "/arm_controller/follow_joint_trajectory")
        self.grip = ActionClient(self, GripperCommand,
                                 "/gripper_controller/gripper_cmd")
        self.arm.wait_for_server(timeout_sec=30)
        self.grip.wait_for_server(timeout_sec=30)

    def _img(self, m):
        self.img = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, -1)
        self.img_stamp = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        self.enc = m.encoding

    def _js(self, m):
        self.js = m

    def _free(self, m):
        self.balls = m

    def spin(self, s):
        t0 = time.time()
        while time.time() - t0 < s:
            rclpy.spin_once(self, timeout_sec=0.01)

    def q(self):
        n = list(self.js.name)
        return np.array([self.js.position[n.index(j)] for j in ARM])

    def ball_pose(self):
        if self.balls is None or not self.balls.free_joints:
            return None
        for e in self.balls.free_joints:
            if e.name == "object":
                p = e.pose.pose.position
                return np.array([p.x, p.y, p.z])
        p = self.balls.free_joints[0].pose.pose.position
        return np.array([p.x, p.y, p.z])

    def ball_pixels(self):
        """How much white ball is in frame, and where.

        The ball is the brightest large thing that is not the gripper; the
        gripper's own white is at the bottom of the frame, so the test looks
        at the upper two thirds.
        """
        if self.img is None:
            return 0, None
        rgb = self.img[..., :3]
        top = rgb[: int(rgb.shape[0] * 0.75)]
        lum = top.astype(np.int16).mean(axis=2)
        m = lum > 215
        n = int(m.sum())
        if n < 20:
            return n, None
        ys, xs = np.nonzero(m)
        return n, (float(xs.mean()), float(ys.mean()))

    def move(self, q, seconds=2.0):
        g = FollowJointTrajectory.Goal()
        g.trajectory.joint_names = ARM
        pt = JointTrajectoryPoint()
        pt.positions = [float(v) for v in q]
        pt.time_from_start.sec = int(seconds)
        pt.time_from_start.nanosec = int((seconds % 1) * 1e9)
        g.trajectory.points.append(pt)
        f = self.arm.send_goal_async(g)
        rclpy.spin_until_future_complete(self, f, timeout_sec=5)
        h = f.result()
        if h is None or not h.accepted:
            return False
        rf = h.get_result_async()
        rclpy.spin_until_future_complete(self, rf, timeout_sec=seconds + 10)
        return rf.result() is not None and rf.result().result.error_code == 0

    def jaw_async(self, theta):
        """Send and return. A released ball falls 117 mm in about 0.15 s, so
        waiting for the action result means sampling after it has landed --
        which is how this test first 'failed' while the camera was fine."""
        g = GripperCommand.Goal()
        g.command.position = float(theta)
        g.command.max_effort = 0.5
        f = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, f, timeout_sec=2)

    def jaw(self, theta):
        g = GripperCommand.Goal()
        g.command.position = float(theta)
        g.command.max_effort = 0.5
        f = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, f, timeout_sec=5)
        h = f.result()
        if h is not None and h.accepted:
            rf = h.get_result_async()
            rclpy.spin_until_future_complete(self, rf, timeout_sec=10)
        self.spin(0.5)


@click.command()
def main():
    rclpy.init()
    w = Watch()
    w.spin(3.0)
    if w.img is None:
        raise SystemExit("no image on /wrist_camera/image_raw")
    click.secho(f"image {w.img.shape} {w.enc}   ball pose topic: "
                f"{'yes' if w.ball_pose() is not None else 'no'}", bold=True)
    shots = []

    def snap(tag):
        n, c = w.ball_pixels()
        bp = w.ball_pose()
        img = w.img[..., :3].copy()
        cv2.putText(img, tag, (5, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 0, 0), 2)
        cv2.putText(img, tag, (5, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)
        shots.append(img)
        return n, c, bp

    cfg = w.cfg
    ox, oy = cfg.object_start_xy
    r = float(cfg.object_size[2])
    pitch = math.radians(10.0)
    q_pre, _, _, _ = w.kin.solve_ik_best(
        w.kin.grasp_tcp_target((ox, oy), r + 0.07, pitch, 0.065), pitch)
    q_grasp, _, _, _ = w.kin.solve_ik_best(
        w.kin.grasp_tcp_target((ox, oy), r, pitch, 0.065), pitch)
    q_lift, _, _, _ = w.kin.solve_ik_best(
        w.kin.grasp_tcp_target((ox, oy), r + 0.12, pitch, 0.065), pitch)
    open_theta = float(w.kin.grip_hi)

    click.secho("\n1. the arm moves, the image follows", bold=True)
    w.jaw(open_theta)
    before = w.img.copy()
    n0, c0, b0 = snap("1 start")
    w.move(q_pre, 2.0)
    w.spin(0.6)
    after = w.img.copy()
    n1, c1, b1 = snap("2 at the stand-off")
    diff = float(np.abs(after.astype(int) - before.astype(int)).mean())
    qd = float(np.abs(w.q() - q_pre).max())
    click.echo(f"   image changed by {diff:.2f} levels/px   joints within "
               f"{math.degrees(qd):.2f} deg of the command")
    click.secho(f"   {'PASS' if diff > 1.0 and qd < 0.05 else 'FAIL'}",
                fg="green" if diff > 1.0 and qd < 0.05 else "red")

    click.secho("\n2. grasp and lift: the ball moves in the image", bold=True)
    w.move(q_grasp, 2.0)
    w.spin(0.5)
    n2, c2, b2 = snap("3 at the ball")
    w.jaw(0.0)
    n3, c3, b3 = snap("4 closed")
    w.move(q_lift, 2.0)
    w.spin(0.8)
    n4, c4, b4 = snap("5 lifted")
    click.echo(f"   ball pixels   at the ball {n2}   closed {n3}   lifted {n4}")
    if b2 is not None and b4 is not None:
        click.echo(f"   ball pose     {np.round(b2*1000,1)} -> "
                   f"{np.round(b4*1000,1)} mm   rose {(b4[2]-b2[2])*1000:+.1f} mm")
    if c2 and c4:
        click.echo(f"   ball centroid in the image {np.round(c2,1)} -> "
                   f"{np.round(c4,1)} px")
    lifted = b4 is not None and b2 is not None and (b4[2] - b2[2]) > 0.03
    seen = n4 > 200
    click.secho(f"   {'PASS' if lifted and seen else 'FAIL'}"
                f"  (ball actually rose: {lifted}, still in frame: {seen})",
                fg="green" if lifted and seen else "red")

    click.secho("\n3. release: consecutive frames follow the fall", bold=True)
    w.jaw_async(open_theta)
    seq, last = [], None
    t0 = time.time()
    while time.time() - t0 < 1.2:
        rclpy.spin_once(w, timeout_sec=0.01)
        if w.img_stamp is not None and w.img_stamp != last:
            last = w.img_stamp
            n, _ = w.ball_pixels()
            b = w.ball_pose()
            seq.append((n, None if b is None else round(float(b[2]) * 1000, 1)))
            if len(seq) in (1, 4, 9):
                snap(f"6 falling {len(seq)}")
    click.echo(f"   {len(seq)} camera frames in 1.2 s")
    click.echo("   (ball pixels, true height mm): " + ", ".join(
        f"({n},{z})" for n, z in seq[:14]))
    heights = [z for _, z in seq if z is not None]
    fell = len(heights) >= 2 and (max(heights) - min(heights)) > 5
    changed = len({n for n, _ in seq}) > 1
    click.secho(f"   {'PASS' if fell and changed else 'FAIL'}"
                f"  (height changed by {max(heights)-min(heights):.1f} mm, "
                f"pixel count varied: {changed})",
                fg="green" if fell and changed else "red")

    out = SIM / "outputs" / "camera_topic_check.png"
    h = max(s.shape[0] for s in shots)
    row = np.concatenate([cv2.resize(s, (int(s.shape[1] * h / s.shape[0]), h))
                          for s in shots], axis=1)
    cv2.imwrite(str(out), cv2.cvtColor(row, cv2.COLOR_RGB2BGR))
    click.echo(f"\n-> {out}")
    w.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
