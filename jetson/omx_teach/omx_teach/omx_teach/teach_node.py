"""teach_node: kinesthetic teach and replay for the OMX-F follower arm.

Works on top of the omx_control stack WITHOUT modifying it:

    record   /mode_cmd IDLE  (torque off -> the arm goes limp, HOLD IT)
             log /joint_states until record_stop -> <dir>/<name>.csv (+ <name>_ee.csv)
    replay   /mode_cmd TELEOP (torque on), wait for /mode_state to confirm,
             move smoothly to the first sample, then stream the recording on
             /teleop/joint_command; mode_manager relays it to the driver.
             When done the node goes silent -> the driver holds the last pose.

Services
    /teach/record_start  omx_teach_msgs/srv/StartRecording  {name, torque_off}
    /teach/record_stop   std_srvs/srv/Trigger
    /teach/play          omx_teach_msgs/srv/PlayRecording   {name, speed, approach_duration}
    /teach/abort         std_srvs/srv/Trigger                (stop streaming, /mode_cmd STOP)
Topics
    /teach/status        std_msgs/String, 2 Hz
"""

import math
import os
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import Trigger

from omx_teach_msgs.srv import PlayRecording, StartRecording

from . import recording as rec

try:  # optional: confirm the supervisor really switched mode before streaming
    from omx_msgs.msg import ModeState
except ImportError:  # pragma: no cover
    ModeState = None

try:  # optional: export the TCP trajectory next to the joint trajectory
    from omx_task_control import action_format as _af
    from omx_task_control.kinematics import Kinematics as _Kinematics
except ImportError:  # pragma: no cover
    _af = None
    _Kinematics = None

DEFAULT_JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']


def _smoothstep(s):
    s = min(1.0, max(0.0, s))
    return 0.5 - 0.5 * math.cos(math.pi * s)


class TeachNode(Node):

    def __init__(self):
        super().__init__('teach_node')
        self.declare_parameter('recordings_dir', '~/omx_recordings')
        self.declare_parameter('joint_names', DEFAULT_JOINTS)
        self.declare_parameter('command_rate_hz', 50.0)
        self.declare_parameter('default_approach_duration', 3.0)
        self.declare_parameter('hold_after_s', 1.0)
        self.declare_parameter('mode_wait_timeout_s', 3.0)
        self.declare_parameter('record_mode', 'IDLE')
        self.declare_parameter('replay_mode', 'TELEOP')
        self.declare_parameter('command_topic', '/teleop/joint_command')
        self.declare_parameter('export_ee', True)
        self.declare_parameter('max_sample_jump_rad', 0.5)   # reject corrupt recordings

        p = self.get_parameter
        self.dir = rec.recordings_dir(str(p('recordings_dir').value))
        self.joint_names = list(p('joint_names').value)
        self.rate = float(p('command_rate_hz').value)
        self.default_approach = float(p('default_approach_duration').value)
        self.hold_after = float(p('hold_after_s').value)
        self.mode_wait_timeout = float(p('mode_wait_timeout_s').value)
        self.record_mode = str(p('record_mode').value)
        self.replay_mode = str(p('replay_mode').value)
        self.export_ee = bool(p('export_ee').value) and _Kinematics is not None
        self.max_jump = float(p('max_sample_jump_rad').value)
        self.kin = _Kinematics() if self.export_ee else None

        # live state
        self.q_now = None
        self.mode_now = None
        self.torque_now = False
        self.state = 'idle'          # idle | recording | wait_mode | approach | stream | hold
        self.last_result = ''

        # recording buffers
        self.rec_name = ''
        self.rec_t0 = None
        self.rec_t = []
        self.rec_q = []

        # playback buffers
        self.play_name = ''
        self.play_t = None
        self.play_q = None
        self.play_speed = 1.0
        self.approach_duration = self.default_approach
        self.phase_t0 = None
        self.q_start = None
        self.err_sq = []
        self.err_max = 0.0

        self.pub_cmd = self.create_publisher(JointState, str(p('command_topic').value), 10)
        self.pub_mode = self.create_publisher(String, '/mode_cmd', 10)
        self.pub_status = self.create_publisher(String, '/teach/status', 10)
        self.create_subscription(JointState, '/joint_states', self.on_joint_states, 50)
        if ModeState is not None:
            self.create_subscription(ModeState, '/mode_state', self.on_mode_state, 10)
        else:
            self.get_logger().warn('omx_msgs not available: replay will not confirm the mode switch')

        self.create_service(StartRecording, '/teach/record_start', self.srv_record_start)
        self.create_service(Trigger, '/teach/record_stop', self.srv_record_stop)
        self.create_service(PlayRecording, '/teach/play', self.srv_play)
        self.create_service(Trigger, '/teach/abort', self.srv_abort)

        self.create_timer(1.0 / self.rate, self.on_tick)
        self.create_timer(0.5, self.publish_status)
        self.get_logger().info(
            f'teach_node ready: recordings in {self.dir}, replay via {self.replay_mode} on '
            f'{p("command_topic").value} @ {self.rate:.0f} Hz, ee export={self.export_ee}')

    # ------------------------------------------------------------------ inputs
    def on_joint_states(self, msg):
        try:
            idx = [msg.name.index(n) for n in self.joint_names]
        except ValueError:
            return
        q = [float(msg.position[i]) for i in idx]
        self.q_now = q
        if self.state == 'recording':
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            if self.rec_t0 is None:
                self.rec_t0 = stamp
            self.rec_t.append(stamp - self.rec_t0)
            self.rec_q.append(q)

    def on_mode_state(self, msg):
        self.mode_now = msg.mode
        self.torque_now = bool(msg.torque_enabled)

    def set_mode(self, mode):
        m = String()
        m.data = mode
        self.pub_mode.publish(m)

    # ------------------------------------------------------------------ services
    def srv_record_start(self, req, res):
        if self.state != 'idle':
            res.success, res.message = False, f'busy ({self.state})'
            return res
        if self.q_now is None:
            res.success, res.message = False, 'no /joint_states yet'
            return res
        name = req.name.strip() or time.strftime('rec_%Y%m%d_%H%M%S')
        path = os.path.join(self.dir, name + '.csv')
        if os.path.exists(path):
            res.success, res.message = False, f'{path} exists'
            return res
        self.rec_name, self.rec_t0, self.rec_t, self.rec_q = name, None, [], []
        if req.torque_off:
            self.set_mode(self.record_mode)
        self.state = 'recording'
        self.get_logger().info(f'recording "{name}" started (torque_off={req.torque_off})')
        res.success = True
        res.message = f'recording {name}' + (
            f'; sent /mode_cmd {self.record_mode} (torque OFF) -- hold the arm' if req.torque_off else '')
        return res

    def srv_record_stop(self, _req, res):
        if self.state != 'recording':
            res.success, res.message = False, 'not recording'
            return res
        self.state = 'idle'
        if len(self.rec_t) < 2:
            res.success, res.message = False, 'too few samples, nothing saved'
            return res
        t = np.asarray(self.rec_t)
        q = np.asarray(self.rec_q)
        ee = None
        if self.export_ee:
            ee = np.zeros((len(t), 8))
            for i, qi in enumerate(q):
                tm = self.kin.forward_matrix(qi[:5])
                ee[i, 0:3] = tm[:3, 3]
                ee[i, 3:7] = _af.mat_to_quat(tm[:3, :3])
                ee[i, 7] = self.kin.gripper_to_width(qi[5])
        path = os.path.join(self.dir, self.rec_name + '.csv')
        path, ee_path = rec.save(path, self.rec_name, self.joint_names, t, q, ee)
        dur = float(t[-1] - t[0])
        msg = f'saved {path} ({len(t)} samples, {dur:.2f} s'
        msg += f', tcp -> {ee_path})' if ee_path else ')'
        self.last_result = msg
        self.get_logger().info(msg)
        res.success, res.message = True, msg
        return res

    def srv_play(self, req, res):
        if self.state != 'idle':
            res.success, res.message = False, f'busy ({self.state})'
            return res
        if self.q_now is None:
            res.success, res.message = False, 'no /joint_states yet'
            return res
        try:
            path = rec.resolve(req.name.strip(), self.dir)
            t, q, names = rec.load(path)
        except (OSError, ValueError) as exc:
            res.success, res.message = False, str(exc)
            return res
        if names != self.joint_names:
            res.success, res.message = False, f'joint names {names} != {self.joint_names}'
            return res
        jump = float(np.max(np.abs(np.diff(q, axis=0)))) if len(q) > 1 else 0.0
        if jump > self.max_jump:
            res.success, res.message = False, \
                f'recording has a {math.degrees(jump):.1f} deg jump between samples, refusing'
            return res
        speed = req.speed if req.speed > 0.0 else 1.0
        self.play_speed = min(2.0, max(0.1, float(speed)))
        self.approach_duration = req.approach_duration if req.approach_duration > 0.0 \
            else self.default_approach
        self.play_name = os.path.basename(path)[:-4]
        self.play_t = t - t[0]
        self.play_q = q
        self.err_sq, self.err_max = [], 0.0

        self.set_mode(self.replay_mode)
        self.phase_t0 = self.get_clock().now()
        self.state = 'wait_mode'
        msg = (f'playing {self.play_name}: {len(t)} samples, {self.play_t[-1] / self.play_speed:.2f} s '
               f'at x{self.play_speed:.2f} after a {self.approach_duration:.1f} s approach; '
               f'sent /mode_cmd {self.replay_mode}')
        self.get_logger().info(msg)
        res.success, res.message = True, msg
        return res

    def srv_abort(self, _req, res):
        was = self.state
        if was in ('wait_mode', 'approach', 'stream', 'hold'):
            self.set_mode('STOP')
        self.state = 'idle'
        self.last_result = f'aborted from {was}'
        self.get_logger().warn(self.last_result)
        res.success, res.message = True, self.last_result
        return res

    # ------------------------------------------------------------------ playback
    def _elapsed(self):
        return (self.get_clock().now() - self.phase_t0).nanoseconds * 1e-9

    def _publish(self, q):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self.joint_names)
        msg.position = [float(v) for v in q]
        self.pub_cmd.publish(msg)

    def on_tick(self):
        if self.state == 'wait_mode':
            confirmed = (ModeState is None and self._elapsed() > 1.0) or \
                        (self.mode_now == self.replay_mode and self.torque_now)
            if confirmed:
                self.q_start = list(self.q_now)
                self.phase_t0 = self.get_clock().now()
                self.state = 'approach'
            elif self._elapsed() > self.mode_wait_timeout:
                self.state = 'idle'
                self.last_result = (f'mode_manager did not enter {self.replay_mode} '
                                    f'(now {self.mode_now}, torque {self.torque_now}); check e_stop / joint_states')
                self.get_logger().error(self.last_result)
            return

        if self.state == 'approach':
            s = _smoothstep(self._elapsed() / max(self.approach_duration, 1e-3))
            q0 = self.play_q[0]
            self._publish([a + (b - a) * s for a, b in zip(self.q_start, q0)])
            if s >= 1.0:
                self.phase_t0 = self.get_clock().now()
                self.state = 'stream'
            return

        if self.state == 'stream':
            tau = self._elapsed() * self.play_speed
            t_end = float(self.play_t[-1])
            if tau >= t_end:
                q = self.play_q[-1]
                self._publish(q)
                self.phase_t0 = self.get_clock().now()
                self.state = 'hold'
                return
            q = [float(np.interp(tau, self.play_t, self.play_q[:, j]))
                 for j in range(self.play_q.shape[1])]
            self._publish(q)
            if self.q_now is not None:
                e = np.abs(np.asarray(q[:5]) - np.asarray(self.q_now[:5]))
                self.err_sq.append(float(np.mean(e ** 2)))
                self.err_max = max(self.err_max, float(np.max(e)))
            return

        if self.state == 'hold':
            if self._elapsed() >= self.hold_after:
                rms = math.degrees(math.sqrt(np.mean(self.err_sq))) if self.err_sq else float('nan')
                self.last_result = (f'played {self.play_name}: {self.play_t[-1] / self.play_speed:.2f} s, '
                                    f'arm tracking error rms {rms:.2f} deg, max '
                                    f'{math.degrees(self.err_max):.2f} deg (includes driver lag)')
                self.get_logger().info(self.last_result)
                self.state = 'idle'          # silence -> driver holds the last pose
            return

    # ------------------------------------------------------------------ status
    def publish_status(self):
        if self.state == 'recording':
            t = self.rec_t[-1] if self.rec_t else 0.0
            s = f'recording {self.rec_name}: {len(self.rec_t)} samples, {t:.1f} s'
        elif self.state in ('wait_mode', 'approach'):
            s = f'playing {self.play_name}: {self.state} (mode={self.mode_now}, torque={self.torque_now})'
        elif self.state == 'stream':
            prog = min(1.0, self._elapsed() * self.play_speed / max(float(self.play_t[-1]), 1e-6))
            s = f'playing {self.play_name}: stream {prog * 100:.0f}%'
        elif self.state == 'hold':
            s = f'playing {self.play_name}: hold'
        else:
            s = 'idle' + (f' | last: {self.last_result}' if self.last_result else '')
        m = String()
        m.data = s
        self.pub_status.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = TeachNode()
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
