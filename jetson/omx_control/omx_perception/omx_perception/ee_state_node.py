"""ee_state_node: /joint_states -> /ee_state (T_base_tcp + normalised gripper width).

Uses the same analytic kinematics as ik_node so the policy's notion of "where
the TCP is" and the IK's notion agree exactly.  Publishes at most rate_hz.
"""

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import JointState

from omx_msgs.msg import EEState
from omx_task_control import action_format as af
from omx_task_control.kinematics import (DEFAULT_LOWER, DEFAULT_UPPER, JOINT_NAMES,
                                         Kinematics)


class EEStateNode(Node):

    def __init__(self):
        super().__init__('ee_state_node')
        self.declare_parameter('rate_hz', 30.0)
        self.declare_parameter('tcp_offset_x', 0.0)
        self.declare_parameter('lower_limits_rad', DEFAULT_LOWER)
        self.declare_parameter('upper_limits_rad', DEFAULT_UPPER)
        self.declare_parameter('gripper_open_rad', 1.745)
        self.declare_parameter('gripper_closed_rad', 0.0)
        self.declare_parameter('base_frame', 'base_link')

        p = self.get_parameter
        self.kin = Kinematics(
            tcp_offset_x=float(p('tcp_offset_x').value),
            lower=list(p('lower_limits_rad').value),
            upper=list(p('upper_limits_rad').value),
            gripper_open_rad=float(p('gripper_open_rad').value),
            gripper_closed_rad=float(p('gripper_closed_rad').value))
        self.min_period = 1.0 / float(p('rate_hz').value)
        self.frame = str(p('base_frame').value)
        self.last_pub = None

        self.sub = self.create_subscription(JointState, '/joint_states', self.on_joint_state, 10)
        self.pub = self.create_publisher(EEState, '/ee_state', 10)

    def on_joint_state(self, msg):
        try:
            idx = [msg.name.index(n) for n in JOINT_NAMES]
        except ValueError:
            return
        stamp = Time.from_msg(msg.header.stamp)
        if self.last_pub is not None and (stamp - self.last_pub).nanoseconds * 1e-9 < self.min_period:
            return
        self.last_pub = stamp

        q = [msg.position[i] for i in idx]
        t = self.kin.forward_matrix(q[:5])

        out = EEState()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = self.frame
        out.tcp_pose = af.pose_from_t(t)
        out.gripper_width = float(self.kin.gripper_to_width(q[5]))
        out.joint_names = list(JOINT_NAMES)
        out.joint_positions = [float(v) for v in q]
        self.pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = EEStateNode()
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
