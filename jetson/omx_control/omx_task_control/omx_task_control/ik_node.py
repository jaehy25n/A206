"""ik_node: EE target -> joint command for the 5-DOF OMX-F arm.

    /ee_target (omx_msgs/EETarget)
        |  workspace box check
        |  5-DOF projection (drop the yaw the arm cannot realise)
        |  analytic IK, both elbow branches, limit check, nearest to current q
        |  per-message joint step clamp
        v
    /ik/joint_command (sensor_msgs/JointState: joint1..joint5, gripper_joint_1)
    /ik/yaw_dropped   (std_msgs/Float32, radians discarded by the projection)

On failure nothing is published (downstream: silence = hold) and a throttled
warning explains why.
"""

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32

from omx_msgs.msg import EETarget

from . import action_format as af
from .kinematics import BASE_X, DEFAULT_LOWER, DEFAULT_UPPER, JOINT_NAMES, Kinematics, wrap


class IkNode(Node):

    def __init__(self):
        super().__init__('ik_node')
        self.declare_parameter('tcp_offset_x', 0.0)
        self.declare_parameter('lower_limits_rad', DEFAULT_LOWER)
        self.declare_parameter('upper_limits_rad', DEFAULT_UPPER)
        self.declare_parameter('gripper_open_rad', 1.745)
        self.declare_parameter('gripper_closed_rad', 0.0)
        self.declare_parameter('max_joint_step_rad', 0.06)     # per /ee_target message
        self.declare_parameter('seed_timeout_s', 0.5)          # reuse last command as seed if newer
        self.declare_parameter('workspace_min', [-0.45, -0.45, -0.05])
        self.declare_parameter('workspace_max', [0.45, 0.45, 0.45])
        # Horizontal reach limit from the joint1 axis [m]. Holding the arm near full
        # extension (0.40 m) overloads the joint2 XL430 (alarm shutdown), so stay well inside.
        self.declare_parameter('max_reach_m', 0.32)
        self.declare_parameter('yaw_drop_warn_deg', 20.0)

        p = self.get_parameter
        self.kin = Kinematics(
            tcp_offset_x=float(p('tcp_offset_x').value),
            lower=list(p('lower_limits_rad').value),
            upper=list(p('upper_limits_rad').value),
            gripper_open_rad=float(p('gripper_open_rad').value),
            gripper_closed_rad=float(p('gripper_closed_rad').value))
        self.max_step = float(p('max_joint_step_rad').value)
        self.seed_timeout = float(p('seed_timeout_s').value)
        self.ws_min = [float(v) for v in p('workspace_min').value]
        self.ws_max = [float(v) for v in p('workspace_max').value]
        self.max_reach = float(p('max_reach_m').value)
        self.yaw_warn = math.radians(float(p('yaw_drop_warn_deg').value))

        self.q_now = None                 # from /joint_states (5 arm joints)
        self.q_last_cmd = None
        self.t_last_cmd = None
        self.fail_count = 0

        self.sub_js = self.create_subscription(JointState, '/joint_states', self.on_joint_state, 10)
        self.sub_target = self.create_subscription(EETarget, '/ee_target', self.on_target, 10)
        self.pub_cmd = self.create_publisher(JointState, '/ik/joint_command', 10)
        self.pub_drop = self.create_publisher(Float32, '/ik/yaw_dropped', 10)
        self.get_logger().info(
            f'analytic IK ready, tcp_offset_x={self.kin.tcp_offset_x:.4f} m, '
            f'max reach {self.kin.max_reach:.3f} m, step clamp {math.degrees(self.max_step):.1f} deg')

    def on_joint_state(self, msg):
        try:
            idx = [msg.name.index(n) for n in JOINT_NAMES[:5]]
        except ValueError:
            return
        self.q_now = [msg.position[i] for i in idx]

    def on_target(self, msg):
        if self.q_now is None:
            self.get_logger().warn('waiting for /joint_states', throttle_duration_sec=2.0)
            return
        t = af.t_from_pose(msg.pose)
        p = t[:3, 3]
        for i, axis in enumerate('xyz'):
            if not self.ws_min[i] <= p[i] <= self.ws_max[i]:
                self.get_logger().warn(
                    f'target {axis}={p[i]:.3f} outside workspace box, holding',
                    throttle_duration_sec=2.0)
                return
        reach = math.hypot(p[0] - BASE_X, p[1])
        if reach > self.max_reach:
            self.get_logger().warn(
                f'target reach {reach:.3f} m > max_reach_m {self.max_reach:.2f} (joint2 overload risk), holding',
                throttle_duration_sec=2.0)
            return

        now = self.get_clock().now()
        seed = self.q_now
        if self.q_last_cmd is not None and self.t_last_cmd is not None and \
                (now - self.t_last_cmd).nanoseconds * 1e-9 < self.seed_timeout:
            seed = self.q_last_cmd

        q, info = self.kin.solve(t, q_seed=seed)
        drop = Float32()
        drop.data = float(info['yaw_drop'])
        self.pub_drop.publish(drop)
        if q is None:
            self.fail_count += 1
            self.get_logger().warn(f'IK failed, holding: {info["reason"]}', throttle_duration_sec=2.0)
            return
        if abs(info['yaw_drop']) > self.yaw_warn:
            self.get_logger().warn(
                f'projection discarded {math.degrees(info["yaw_drop"]):.1f} deg of yaw',
                throttle_duration_sec=2.0)

        # per-message step clamp toward the solution
        q_cmd = []
        for qi, si in zip(q, seed):
            d = wrap(qi - si)
            q_cmd.append(si + max(-self.max_step, min(self.max_step, d)))

        gripper = self.kin.width_to_gripper(msg.gripper_width)

        out = JointState()
        out.header.stamp = now.to_msg()
        out.name = list(JOINT_NAMES)
        out.position = [float(v) for v in q_cmd] + [float(gripper)]
        self.pub_cmd.publish(out)
        self.q_last_cmd = q_cmd
        self.t_last_cmd = now


def main(args=None):
    rclpy.init(args=args)
    node = IkNode()
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
