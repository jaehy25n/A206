"""mode_manager: the ONLY publisher of /joint_command.

Everything that wants to move the arm goes through here, so one node holds
the whole safety story:

    modes    IDLE   torque off, nothing published
             HOME   torque on, interpolate to home_positions, then hold there
             POLICY torque on, relay /ik/joint_command  (needs fresh policy heartbeat)
             TELEOP torque on, relay /teleop/joint_command (optional leader arm)
             STOP   torque on, nothing published -> driver holds (silence = hold)

    inputs   /mode_cmd            std_msgs/String   IDLE|HOME|POLICY|TELEOP|STOP
             /e_stop              std_msgs/Bool     true -> STOP (+ torque off if estop_torque_off)
             /policy/heartbeat    std_msgs/Empty    watchdog for POLICY
             /joint_states        sensor_msgs/JointState
             /dxl_driver/status   diagnostic_msgs/DiagnosticArray  ERROR -> STOP
             /ik/joint_command, /teleop/joint_command

    outputs  /joint_command       sensor_msgs/JointState
             /mode_state          omx_msgs/ModeState (10 Hz)
             service client       /dxl_driver/set_torque (std_srvs/SetBool)
"""

import math

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Empty, String
from std_srvs.srv import SetBool

from omx_msgs.msg import ModeState

MODES = ('IDLE', 'HOME', 'POLICY', 'TELEOP', 'STOP')
DEFAULT_JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']


class ModeManager(Node):

    def __init__(self):
        super().__init__('mode_manager')
        self.declare_parameter('start_mode', 'IDLE')
        self.declare_parameter('start_delay_s', 1.0)
        self.declare_parameter('heartbeat_timeout_ms', 300.0)
        self.declare_parameter('joint_state_timeout_ms', 200.0)
        self.declare_parameter('estop_torque_off', True)
        self.declare_parameter('driver_error_stops', True)
        self.declare_parameter('joint_names', DEFAULT_JOINTS)
        self.declare_parameter('home_positions', [0.0, -1.57, 1.57, 1.57, 0.0, 0.0])
        self.declare_parameter('home_duration_s', 4.0)
        self.declare_parameter('command_rate_hz', 50.0)
        self.declare_parameter('torque_service', '/dxl_driver/set_torque')

        p = self.get_parameter
        self.hb_timeout = float(p('heartbeat_timeout_ms').value) / 1000.0
        self.js_timeout = float(p('joint_state_timeout_ms').value) / 1000.0
        self.estop_torque_off = bool(p('estop_torque_off').value)
        self.driver_error_stops = bool(p('driver_error_stops').value)
        self.joint_names = list(p('joint_names').value)
        self.home = [float(v) for v in p('home_positions').value]
        self.home_duration = float(p('home_duration_s').value)
        self.command_rate = float(p('command_rate_hz').value)
        if len(self.home) != len(self.joint_names):
            raise ValueError('home_positions must have one entry per joint')

        self.mode = 'IDLE'
        self.reason = 'startup'
        self.e_stop = False
        self.torque_enabled = False
        self.torque_requested = None
        self.last_hb = None
        self.last_js = None
        self.q_now = None
        self.home_start_q = None
        self.home_t0 = None
        self.pending_mode = None
        self.pending_since = None
        self.relayed = 0

        self.pub_cmd = self.create_publisher(JointState, '/joint_command', 10)
        self.pub_state = self.create_publisher(ModeState, '/mode_state', 10)
        self.create_subscription(JointState, '/ik/joint_command', self.on_ik_cmd, 10)
        self.create_subscription(JointState, '/teleop/joint_command', self.on_teleop_cmd, 10)
        self.create_subscription(Bool, '/e_stop', self.on_estop, 10)
        self.create_subscription(String, '/mode_cmd', self.on_mode_cmd, 10)
        self.create_subscription(Empty, '/policy/heartbeat', self.on_heartbeat, 10)
        self.create_subscription(JointState, '/joint_states', self.on_joint_states, 10)
        self.create_subscription(DiagnosticArray, '/dxl_driver/status', self.on_driver_status, 10)
        self.torque_client = self.create_client(SetBool, str(p('torque_service').value))

        self.tick_timer = self.create_timer(1.0 / self.command_rate, self.on_tick)
        self.state_timer = self.create_timer(0.1, self.publish_state)

        start_mode = str(p('start_mode').value).strip().upper()
        if start_mode != 'IDLE':
            self.pending_mode = start_mode
            self.pending_since = self.get_clock().now()
        self.get_logger().info(f'mode_manager up, start_mode={start_mode}')

    # ------------------------------------------------------------------ helpers
    def _age(self, stamp):
        if stamp is None:
            return None
        return (self.get_clock().now() - stamp).nanoseconds * 1e-9

    def request_torque(self, on):
        if self.torque_requested == on:
            return
        self.torque_requested = on
        if not self.torque_client.service_is_ready():
            self.get_logger().warn('torque service not available yet', throttle_duration_sec=2.0)
            self.torque_requested = None
            return
        req = SetBool.Request()
        req.data = bool(on)
        fut = self.torque_client.call_async(req)

        def done(f):
            try:
                res = f.result()
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error(f'set_torque({on}) call failed: {exc}')
                self.torque_requested = None
                return
            if res.success:
                self.torque_enabled = bool(on)
            else:
                self.get_logger().error(f'set_torque({on}) refused: {res.message}')
                self.torque_requested = None
        fut.add_done_callback(done)

    # ------------------------------------------------------------------ modes
    def set_mode(self, new, reason):
        new = new.strip().upper()
        if new not in MODES:
            self.get_logger().warn(f'unknown mode "{new}" (one of {", ".join(MODES)})')
            return False
        if self.e_stop and new not in ('IDLE', 'STOP'):
            self.get_logger().warn(f'refusing {new}: e_stop active')
            return False
        if new in ('HOME', 'POLICY', 'TELEOP'):
            js_age = self._age(self.last_js)
            if js_age is None or js_age > self.js_timeout:
                self.get_logger().warn(f'refusing {new}: no fresh /joint_states',
                                       throttle_duration_sec=2.0)
                return False
        if new == 'POLICY':
            hb_age = self._age(self.last_hb)
            if hb_age is None or hb_age > self.hb_timeout:
                self.get_logger().warn('refusing POLICY: no fresh /policy/heartbeat',
                                       throttle_duration_sec=2.0)
                return False
        if new == 'HOME':
            self.home_start_q = list(self.q_now)
            self.home_t0 = self.get_clock().now()

        self.request_torque(new != 'IDLE')
        if self.mode != new:
            self.get_logger().info(f'mode {self.mode} -> {new} ({reason})')
        self.mode = new
        self.reason = reason
        return True

    # ------------------------------------------------------------------ callbacks
    def relay(self, msg):
        if len(msg.name) != len(msg.position):
            return
        if any(not math.isfinite(v) for v in msg.position):
            self.get_logger().warn('dropping command with non-finite values', throttle_duration_sec=2.0)
            return
        out = JointState()
        out.header.stamp = self.get_clock().now().to_msg()
        out.name = list(msg.name)
        out.position = list(msg.position)
        out.velocity = list(msg.velocity)
        self.pub_cmd.publish(out)
        self.relayed += 1

    def on_ik_cmd(self, msg):
        if self.mode == 'POLICY':
            self.relay(msg)

    def on_teleop_cmd(self, msg):
        if self.mode == 'TELEOP':
            self.relay(msg)

    def on_estop(self, msg):
        if msg.data and not self.e_stop:
            self.e_stop = True
            self.pending_mode = None
            self.set_mode('STOP', 'e_stop')
            if self.estop_torque_off:
                self.request_torque(False)
            self.get_logger().error('E-STOP')
        elif not msg.data and self.e_stop:
            self.e_stop = False
            self.get_logger().warn('e_stop released, staying in STOP until /mode_cmd')

    def on_mode_cmd(self, msg):
        self.pending_mode = None
        self.set_mode(msg.data, 'mode_cmd')

    def on_heartbeat(self, _msg):
        self.last_hb = self.get_clock().now()

    def on_joint_states(self, msg):
        try:
            idx = [msg.name.index(n) for n in self.joint_names]
        except ValueError:
            return
        self.q_now = [msg.position[i] for i in idx]
        self.last_js = self.get_clock().now()

    def on_driver_status(self, msg):
        if not self.driver_error_stops or self.mode not in ('HOME', 'POLICY', 'TELEOP'):
            return
        for s in msg.status:
            if s.level == DiagnosticStatus.ERROR:
                self.set_mode('STOP', f'driver error: {s.name}: {s.message}')
                return

    # ------------------------------------------------------------------ periodic
    def on_tick(self):
        now = self.get_clock().now()

        if self.pending_mode is not None:
            if self.set_mode(self.pending_mode, 'start_mode'):
                self.pending_mode = None
            elif (now - self.pending_since).nanoseconds * 1e-9 > 10.0:
                self.get_logger().error(f'could not enter start mode {self.pending_mode} within 10 s')
                self.pending_mode = None

        if self.mode == 'POLICY':
            hb_age = self._age(self.last_hb)
            if hb_age is None or hb_age > self.hb_timeout:
                self.set_mode('STOP', f'policy heartbeat lost ({hb_age if hb_age is None else round(hb_age, 3)} s)')
                return
        if self.mode in ('POLICY', 'TELEOP', 'HOME'):
            js_age = self._age(self.last_js)
            if js_age is None or js_age > self.js_timeout:
                self.set_mode('STOP', 'joint_states lost')
                return

        if self.mode == 'HOME' and self.home_start_q is not None:
            s = min(1.0, (now - self.home_t0).nanoseconds * 1e-9 / max(self.home_duration, 1e-3))
            s = 0.5 - 0.5 * math.cos(math.pi * s)          # smooth-step
            out = JointState()
            out.header.stamp = now.to_msg()
            out.name = list(self.joint_names)
            out.position = [a + (b - a) * s for a, b in zip(self.home_start_q, self.home)]
            self.pub_cmd.publish(out)

    def publish_state(self):
        msg = ModeState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.mode = self.mode
        msg.torque_enabled = self.torque_enabled
        msg.e_stop = self.e_stop
        hb_age = self._age(self.last_hb)
        msg.policy_age_ms = -1.0 if hb_age is None else float(hb_age * 1000.0)
        msg.reason = self.reason
        self.pub_state.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ModeManager()
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
