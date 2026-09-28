"""dummy_policy_node: scripted stand-in for the trained policy.

Same interface the real policy node will have:

    /ee_state (omx_msgs/EEState)           -> base pose T0 and its time t0
    /task_cmd (std_msgs/String)            start | stop | reset
    ------------------------------------------------------------
    /policy/action_chunk (omx_msgs/EEActionChunk)  RELATIVE poses, ABSOLUTE widths [m]
    /policy/heartbeat    (std_msgs/Empty)          heartbeat_hz while alive

The chunk follows the GPU handoff contract (action_format.py): H = 16 steps
0.1 s apart, step k meant for t0 + k*dt, action[0] = the pose the arm is
already in, gripper as a jaw width in metres.  Like the trained policy it
replans every steps_per_inference steps (7 fits the measured Jetson inference
latency, gpu_server/omx-umi-sim/REPORT_JETSON_INFERENCE_BRINGUP.md).

Waypoints are absolute poses; the dummy walks toward the active one with a
capped speed, which is what a real policy's chunk looks like: large steps in
free space, small steps while aligning, near-zero while the gripper closes.
The heartbeat has its own timer so a slow replan never trips the watchdog.
"""

import math

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from omx_msgs.msg import EEActionChunk, EEState
from omx_task_control import action_format as af
from omx_task_control.kinematics import BASE_X, DEFAULT_GRIPPER_OPEN_WIDTH_M, rpy_to_rot

MAX_SPEED = 0.2          # m/s during transit
FINE_SPEED = 0.075       # m/s during alignment
MAX_ANG_SPEED = 1.25     # rad/s


def _wp(x, y, z, pitch_deg, roll_deg, open_frac, tol=0.008, fine=False, dwell=0):
    return {
        'p': np.array([x, y, z], float),
        'pitch': math.radians(pitch_deg),
        'roll': math.radians(roll_deg),
        'open': open_frac,   # 1 = jaw fully open, 0 = closed
        'tol': tol,
        'fine': fine,
        'dwell': dwell,      # replans to hold once reached (lets the gripper act)
    }


# A pick sequence in front of the robot. Approach pitch 45 deg down throughout,
# which keeps every pose comfortably inside the 5-DOF reachable set.
PICK_SCRIPT = [
    _wp(0.20, 0.00, 0.18, 45, 0, 1.0),                                  # hover above
    _wp(0.22, 0.00, 0.10, 45, 0, 1.0, tol=0.004, fine=True),            # descend, aligned
    _wp(0.22, 0.00, 0.10, 45, 0, 0.0, tol=0.004, fine=True, dwell=2),   # close
    _wp(0.20, 0.00, 0.20, 45, 0, 0.0),                                  # lift
    _wp(0.16, 0.12, 0.18, 45, 0, 0.0),                                  # move aside
    _wp(0.16, 0.12, 0.18, 45, 0, 1.0, dwell=2),                         # release
]


class DummyPolicy:
    """Scripted chunk generator with the same call signature as a trained policy."""

    def __init__(self, horizon, dt, open_width_m, script=None):
        self.h = int(horizon)
        self.dt = float(dt)
        self.open_w = float(open_width_m)
        self.script = script if script is not None else PICK_SCRIPT
        self.reset()

    def reset(self):
        self.idx = 0
        self.dwell_left = 0

    @property
    def done(self):
        return self.idx >= len(self.script)

    def __call__(self, t_current):
        """t_current (4x4 base pose T0) -> chunk [H, 10] relative to T0."""
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
                return self.hold(t_current, open_frac=wp['open'])

        wp = self.script[min(self.idx, len(self.script) - 1)]
        step = (FINE_SPEED if wp['fine'] else MAX_SPEED) * self.dt
        max_ang = MAX_ANG_SPEED * self.dt
        width = wp['open'] * self.open_w

        # action[0] is the pose the arm is already in; motion starts at step 1
        poses, widths = [t_current.copy()], [width]
        p = p_now.copy()
        r_prev = t_current[:3, :3].copy()
        for _ in range(1, self.h):
            to_go = wp['p'] - p
            dist = np.linalg.norm(to_go)
            p = wp['p'].copy() if dist <= step else p + to_go / dist * step
            # yaw follows the target azimuth (the arm forces this anyway)
            yaw = math.atan2(p[1], p[0] - BASE_X)
            r_abs = rpy_to_rot(yaw, wp['pitch'], wp['roll'])
            # rotate toward the target orientation at most max_ang per step,
            # like a real policy would (no instantaneous re-orientation)
            w = af.so3_log(r_prev.T @ r_abs)
            ang = float(np.linalg.norm(w))
            if ang > max_ang:
                w = w / ang * max_ang
            r_prev = r_prev @ af.so3_exp(w)
            poses.append(af.make_t(p, r_prev))
            widths.append(width)
        return af.encode_action(t_current, poses, widths)

    def hold(self, t_current, open_frac=1.0):
        """Zero-motion chunk: what the policy emits when nothing should move."""
        return af.encode_action(t_current, [t_current] * self.h,
                                [open_frac * self.open_w] * self.h)


class DummyPolicyNode(Node):

    def __init__(self):
        super().__init__('policy_node')
        self.declare_parameter('horizon', af.ACTION_HORIZON)
        self.declare_parameter('dt', af.ACTION_DT_S)
        self.declare_parameter('steps_per_inference', 7)
        self.declare_parameter('heartbeat_hz', 10.0)
        self.declare_parameter('gripper_open_width_m', DEFAULT_GRIPPER_OPEN_WIDTH_M)
        self.declare_parameter('auto_start', True)
        self.declare_parameter('loop', False)

        p = self.get_parameter
        self.dt = float(p('dt').value)
        self.loop = bool(p('loop').value)
        self.policy = DummyPolicy(int(p('horizon').value), self.dt,
                                  float(p('gripper_open_width_m').value))
        self.running = bool(p('auto_start').value)
        self.ee = None
        self.done_logged = False
        replan_s = int(p('steps_per_inference').value) * self.dt

        self.sub_ee = self.create_subscription(EEState, '/ee_state', self.on_ee_state, 10)
        self.sub_cmd = self.create_subscription(String, '/task_cmd', self.on_task_cmd, 10)
        self.pub_chunk = self.create_publisher(EEActionChunk, '/policy/action_chunk', 10)
        self.pub_hb = self.create_publisher(Empty, '/policy/heartbeat', 10)
        self.timer = self.create_timer(replan_s, self.on_tick)
        self.hb_timer = self.create_timer(1.0 / float(p('heartbeat_hz').value),
                                          lambda: self.pub_hb.publish(Empty()))
        self.get_logger().info(
            f'dummy policy: H={self.policy.h}, dt={self.dt}s '
            f'({self.policy.h * self.dt:.2f}s lookahead), replan every {replan_s:.2f}s, '
            f'auto_start={self.running}')

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
