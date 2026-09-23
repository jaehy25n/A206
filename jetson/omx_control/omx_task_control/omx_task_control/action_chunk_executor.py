"""action_chunk_executor: turn policy action chunks into a smooth 50 Hz EE target.

    /policy/action_chunk (omx_msgs/EEActionChunk)
            |  T_target_k = anchor * delta_k, at t_recv + (k+1)*dt*time_scale
            v
    interpolate (linear position, geodesic rotation, linear gripper)
            |
            v
    /ee_target      (omx_msgs/EETarget, rate_hz)
    /ee_target_pose (geometry_msgs/PoseStamped, for RViz)
    /ee_target_path (nav_msgs/Path, the active chunk, for RViz)

A new chunk replaces the active one (simple receding horizon).  When the
active chunk is exhausted the node keeps publishing its last pose for
hold_after_chunk_s and then goes silent -- downstream, silence means "hold".
"""

import math

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path
from rclpy.node import Node

from omx_msgs.msg import EEActionChunk, EETarget

from . import action_format as af


class ActionChunkExecutor(Node):

    def __init__(self):
        super().__init__('action_chunk_executor')
        self.declare_parameter('rate_hz', 50.0)
        self.declare_parameter('time_scale', 1.0)          # >1 slows execution down
        self.declare_parameter('max_lin_speed', 0.25)      # m/s, chunk is stretched if faster
        self.declare_parameter('max_ang_speed', 1.5)       # rad/s
        self.declare_parameter('hold_after_chunk_s', 0.5)
        self.declare_parameter('base_frame', 'base_link')

        self.rate = float(self.get_parameter('rate_hz').value)
        self.time_scale = float(self.get_parameter('time_scale').value)
        self.max_lin = float(self.get_parameter('max_lin_speed').value)
        self.max_ang = float(self.get_parameter('max_ang_speed').value)
        self.hold_after = float(self.get_parameter('hold_after_chunk_s').value)
        self.frame = str(self.get_parameter('base_frame').value)

        self.traj = None          # list of (t_rel, T, width)
        self.t_start = None       # rclpy Time
        self.chunk_stamp = None
        self.chunks_received = 0

        self.sub = self.create_subscription(EEActionChunk, '/policy/action_chunk', self.on_chunk, 10)
        self.pub_target = self.create_publisher(EETarget, '/ee_target', 10)
        self.pub_pose = self.create_publisher(PoseStamped, '/ee_target_pose', 10)
        self.pub_path = self.create_publisher(Path, '/ee_target_path', 10)
        self.timer = self.create_timer(1.0 / self.rate, self.on_tick)
        self.get_logger().info(
            f'executor @ {self.rate:.0f} Hz, time_scale={self.time_scale}, '
            f'max_lin_speed={self.max_lin} m/s')

    # --- chunk in -------------------------------------------------------------------
    def on_chunk(self, msg):
        if not msg.deltas:
            self.get_logger().warn('empty chunk ignored', throttle_duration_sec=2.0)
            return
        t_anchor, targets = af.msg_to_targets(msg)
        dt = float(msg.dt) * self.time_scale
        if dt <= 0.0:
            self.get_logger().warn('chunk with dt <= 0 ignored', throttle_duration_sec=2.0)
            return

        # speed check: stretch time uniformly rather than reject
        stretch = 1.0
        prev = t_anchor
        for t_k, _ in targets:
            lin = float(np.linalg.norm(t_k[:3, 3] - prev[:3, 3])) / dt
            ang = float(np.linalg.norm(af.so3_log(prev[:3, :3].T @ t_k[:3, :3]))) / dt
            stretch = max(stretch, lin / self.max_lin if self.max_lin > 0 else 1.0,
                          ang / self.max_ang if self.max_ang > 0 else 1.0)
            prev = t_k
        if stretch > 1.0:
            self.get_logger().warn(
                f'chunk exceeds speed limits, stretching time x{stretch:.2f}',
                throttle_duration_sec=2.0)
        dt *= stretch

        first_width = targets[0][1]
        traj = [(0.0, t_anchor, first_width)]
        for k, (t_k, w_k) in enumerate(targets):
            traj.append(((k + 1) * dt, t_k, w_k))
        self.traj = traj
        self.t_start = self.get_clock().now()
        self.chunk_stamp = msg.header.stamp
        self.chunks_received += 1
        self.publish_path()

    def publish_path(self):
        path = Path()
        path.header.stamp = self.get_clock().now().to_msg()
        path.header.frame_id = self.frame
        for _, t_k, _ in self.traj:
            ps = PoseStamped()
            ps.header = path.header
            ps.pose = af.pose_from_t(t_k)
            path.poses.append(ps)
        self.pub_path.publish(path)

    # --- target out -----------------------------------------------------------------
    def on_tick(self):
        if self.traj is None:
            return
        now = self.get_clock().now()
        tau = (now - self.t_start).nanoseconds * 1e-9
        t_end = self.traj[-1][0]
        if tau > t_end + self.hold_after:
            return                          # silence = hold

        if tau >= t_end:
            t_k, w_k = self.traj[-1][1], self.traj[-1][2]
            progress = 1.0
        else:
            # find segment
            i = 1
            while i < len(self.traj) - 1 and self.traj[i][0] < tau:
                i += 1
            t0, ta, wa = self.traj[i - 1]
            t1, tb, wb = self.traj[i]
            s = (tau - t0) / (t1 - t0) if t1 > t0 else 1.0
            t_k = af.interp_t(ta, tb, s)
            w_k = (1.0 - s) * wa + s * wb
            progress = tau / t_end if t_end > 0 else 1.0

        msg = EETarget()
        msg.header.stamp = now.to_msg()
        msg.header.frame_id = self.frame
        msg.pose = af.pose_from_t(t_k)
        msg.gripper_width = float(min(1.0, max(0.0, w_k)))
        msg.chunk_stamp = self.chunk_stamp
        msg.progress = float(min(1.0, progress))
        self.pub_target.publish(msg)

        ps = PoseStamped()
        ps.header = msg.header
        ps.pose = msg.pose
        self.pub_pose.publish(ps)


def main(args=None):
    rclpy.init(args=args)
    node = ActionChunkExecutor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
