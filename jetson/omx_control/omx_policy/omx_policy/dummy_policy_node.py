"""dummy_policy_node: scripted stand-in for the trained policy.

Same interface the real policy node will have:

    /ee_state (omx_msgs/EEState)           -> anchor pose
    /task_cmd (std_msgs/String)            start | stop | reset
    ------------------------------------------------------------
    /policy/action_chunk (omx_msgs/EEActionChunk)  RELATIVE poses, ABSOLUTE widths
    /policy/heartbeat    (std_msgs/Empty)          every tick while alive

Ported from dummy_exec/dummy_policy.py.  Waypoints are absolute poses; the
dummy walks toward the active one with a capped step size, which is what a
real policy's chunk looks like: large steps in free space, small steps while
aligning, near-zero while the gripper closes.
"""

import math

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from omx_msgs.msg import EEActionChunk, EEState
from omx_task_control import action_format as af
from omx_task_control.kinematics import BASE_X, rpy_to_rot

MAX_STEP = 0.008       # metres per step during transit  (0.2 m/s at dt=0.04)
FINE_STEP = 0.003      # metres per step during alignment
MAX_ANG_STEP = 0.05    # radians per step (1.25 rad/s at dt=0.04)


def _wp(x, y, z, pitch_deg, roll_deg, width, tol=0.008, fine=False, dwell=0):
    return {
        'p': np.array([x, y, z], float),
        'pitch': math.radians(pitch_deg),
        'roll': math.radians(roll_deg),
        'width': width,
        'tol': tol,
        'fine': fine,
        'dwell': dwell,      # ticks to hold once reached (lets the gripper act)
    }


# A pick sequence in front of the robot. Approach pitch 45 deg down throughout,
# which keeps every pose comfortably inside the 5-DOF reachable set.
PICK_SCRIPT = [
    _wp(0.20, 0.00, 0.18, 45, 0, 1.0),                                  # hover above
    _wp(0.22, 0.00, 0.10, 45, 0, 1.0, tol=0.004, fine=True),            # descend, aligned
    _wp(0.22, 0.00, 0.10, 45, 0, 0.0, tol=0.004, fine=True, dwell=6),   # close
    _wp(0.20, 0.00, 0.20, 45, 0, 0.0),                                  # lift
    _wp(0.16, 0.12, 0.18, 45, 0, 0.0),                                  # move aside
    _wp(0.16, 0.12, 0.18, 45, 0, 1.0, dwell=6),                         # release
]


class DummyPolicy:
    """Scripted chunk generator with the same call signature as a trained policy."""

    def __init__(self, horizon, script=None):
        self.h = int(horizon)
        self.script = script if script is not None else PICK_SCRIPT
        self.reset()

    def reset(self):
        self.idx = 0
        self.dwell_left = 0

    @property
    def done(self):
        return self.idx >= len(self.script)

    def __call__(self, t_current):
        """t_current (4x4, base frame) -> chunk [H, 10] of relative actions."""
        if self.done:
            return self.hold(t_current)

        wp = self.script[self.idx]
        p_now = t_current[:3, 3].copy()
        if np.linalg.norm(wp['p'] - p_now) <= wp['tol']:
            if self.dwell_left == 0 and wp['dwell'] > 0:
                self.dwell_left = wp['dwell']
            if self.dwell_left > 0:
                self.dwell_left -= 1
                if self.dwell_left == 0:
                    self.idx += 1
            else:
                self.idx += 1
            if self.done:
                return self.hold(t_current, width=wp['width'])

        wp = self.script[min(self.idx, len(self.script) - 1)]
        step = FINE_STEP if wp['fine'] else MAX_STEP

        r_inv = t_current[:3, :3].T
        chunk = np.zeros((self.h, af.ACTION_DIM))
        p = p_now.copy()
        r_prev = t_current[:3, :3].copy()
        for k in range(self.h):
            to_go = wp['p'] - p
            dist = np.linalg.norm(to_go)
            p = wp['p'].copy() if dist <= step else p + to_go / dist * step
            # yaw follows the target azimuth (the arm forces this anyway)
            yaw = math.atan2(p[1], p[0] - BASE_X)
            r_abs = rpy_to_rot(yaw, wp['pitch'], wp['roll'])
            # rotate toward the target orientation at most MAX_ANG_STEP per step,
            # like a real policy would (no instantaneous re-orientation)
            w = af.so3_log(r_prev.T @ r_abs)
            ang = float(np.linalg.norm(w))
            if ang > MAX_ANG_STEP:
                w = w / ang * MAX_ANG_STEP
            r_k = r_prev @ af.so3_exp(w)
            chunk[k, 0:3] = r_inv @ (p - t_current[:3, 3])
            chunk[k, 3:9] = af.rot_to_6d(r_inv @ r_k)
            chunk[k, 9] = wp['width']
            r_prev = r_k
        return chunk

    def hold(self, t_current, width=1.0):
        """Zero-motion chunk: what the policy emits when nothing should move."""
        chunk = np.zeros((self.h, af.ACTION_DIM))
        chunk[:, 3:9] = af.rot_to_6d(np.eye(3))
        chunk[:, 9] = width
        return chunk


class DummyPolicyNode(Node):

    def __init__(self):
        super().__init__('policy_node')
        self.declare_parameter('rate_hz', 4.0)
        self.declare_parameter('horizon', 16)
        self.declare_parameter('dt', 0.04)
        self.declare_parameter('auto_start', True)
        self.declare_parameter('loop', False)

        p = self.get_parameter
        self.rate = float(p('rate_hz').value)
        self.dt = float(p('dt').value)
        self.loop = bool(p('loop').value)
        self.policy = DummyPolicy(int(p('horizon').value))
        self.running = bool(p('auto_start').value)
        self.ee = None
        self.done_logged = False

        self.sub_ee = self.create_subscription(EEState, '/ee_state', self.on_ee_state, 10)
        self.sub_cmd = self.create_subscription(String, '/task_cmd', self.on_task_cmd, 10)
        self.pub_chunk = self.create_publisher(EEActionChunk, '/policy/action_chunk', 10)
        self.pub_hb = self.create_publisher(Empty, '/policy/heartbeat', 10)
        self.timer = self.create_timer(1.0 / self.rate, self.on_tick)
        self.get_logger().info(
            f'dummy policy @ {self.rate:.1f} Hz, H={self.policy.h}, dt={self.dt}s '
            f'({self.policy.h * self.dt:.2f}s lookahead), auto_start={self.running}')

    def on_ee_state(self, msg):
        self.ee = msg

    def on_task_cmd(self, msg):
        cmd = msg.data.strip().lower()
        if cmd == 'start':
            self.policy.reset()
            self.running = True
            self.done_logged = False
        elif cmd == 'stop':
            self.running = False
        elif cmd == 'reset':
            self.policy.reset()
            self.done_logged = False
        else:
            self.get_logger().warn(f'unknown /task_cmd "{msg.data}" (start|stop|reset)')
            return
        self.get_logger().info(f'task_cmd: {cmd}')

    def on_tick(self):
        self.pub_hb.publish(Empty())
        if not self.running:
            return
        if self.ee is None:
            self.get_logger().warn('waiting for /ee_state', throttle_duration_sec=2.0)
            return
        t_anchor = af.t_from_pose(self.ee.tcp_pose)
        chunk = self.policy(t_anchor)
        msg = af.chunk_to_msg(chunk, t_anchor, self.dt, self.ee.header.stamp,
                              frame_id=self.ee.header.frame_id or 'base_link', confidence=1.0)
        self.pub_chunk.publish(msg)
        if self.policy.done and not self.done_logged:
            self.get_logger().info('script complete' + (' (looping)' if self.loop else ''))
            self.done_logged = True
            if self.loop:
                self.policy.reset()
                self.done_logged = False


def main(args=None):
    rclpy.init(args=args)
    node = DummyPolicyNode()
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
