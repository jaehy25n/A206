#!/usr/bin/env python3
"""Execute UMI-style action chunks on the OMX-AI follower.

    /joint_states  ->  FK  ->  anchor pose T_t
                                    |
                       policy(T_t) -> chunk [H, 10]
                                    |
              compose T_t @ dT  ->  5-DOF projection  ->  analytic IK
                                    |
                    JointTrajectory -> /leader/joint_trajectory

Swap DummyPolicy for the trained model later; nothing below it changes.

Run without ROS to check the maths:
    python chunk_executor_node.py --dry-run
"""

import argparse
import math
import sys

import numpy as np

import action_format as A
import omx_kinematics as K
from dummy_policy import DT, DummyPolicy

JOINT_NAMES = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']

# The follower_ai launch remaps /arm_controller/joint_trajectory to
# /leader/joint_trajectory, i.e. the policy takes the leader arm's place.
# Plain omx_f.launch.py has no remap -- use /arm_controller/joint_trajectory there.
DEFAULT_TOPIC = '/leader/joint_trajectory'

EXECUTE_STEPS = 3        # steps consumed per replan (receding horizon)
TIME_SCALE = 2.0         # >1 slows execution down; keep high for first runs
MAX_JOINT_STEP = math.radians(6.0)   # refuse chunks that jump more than this


def build_segment(steps, q_now, time_scale):
    """Turn decoded chunk steps into (points, reason).

    points is a list of (positions, time_from_start_seconds).
    reason is None if the whole segment is safe, else why it was rejected.
    """
    points = []
    q_prev = list(q_now)
    for k, s in enumerate(steps):
        if s['problem'] or s['q'] is None:
            return None, f'step {k}: {s["problem"] or "no IK solution"}'
        jump = max(abs(a - b) for a, b in zip(q_prev, s['q']))
        if jump > MAX_JOINT_STEP:
            return None, (f'step {k}: joint jump {math.degrees(jump):.1f} deg '
                          f'exceeds {math.degrees(MAX_JOINT_STEP):.1f} deg')
        points.append((list(s['q']) + [s['gripper']],
                       (k + 1) * DT * time_scale))
        q_prev = s['q']
    return points, None


# --- dry run (no ROS) ---------------------------------------------------------
def dry_run(ticks, time_scale):
    q = K.inverse(0.20, 0.0, 0.18, math.radians(45), 0.0)
    policy = DummyPolicy()
    published = rejected = 0

    for tick in range(ticks):
        T = A.joints_to_T(q)
        steps = A.decode_chunk(policy(T), T)[:EXECUTE_STEPS]
        points, reason = build_segment(steps, q, time_scale)
        if reason:
            rejected += 1
            print(f'tick {tick:3d}  REJECT  {reason}')
        else:
            published += 1
            q = points[-1][0][:5]
        if policy.done:
            break

    x, y, z, pitch, roll = K.forward(q)
    print(f'\npublished={published} rejected={rejected}')
    print(f'final ee = ({x:.3f}, {y:.3f}, {z:.3f})  '
          f'pitch={math.degrees(pitch):.1f} roll={math.degrees(roll):.1f}')
    print(f'segment duration = {EXECUTE_STEPS * DT * time_scale:.3f} s '
          f'-> replan at {1.0 / (EXECUTE_STEPS * DT * time_scale):.1f} Hz')
    print('inference must finish inside that window, or lower EXECUTE_STEPS')
    return 0 if rejected == 0 else 1


# --- ROS 2 node ---------------------------------------------------------------
def ros_main(topic, time_scale):
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

    class ChunkExecutor(Node):

        def __init__(self):
            super().__init__('chunk_executor')
            self.declare_parameter('topic', topic)
            self.declare_parameter('time_scale', time_scale)
            self.topic = self.get_parameter('topic').value
            self.time_scale = float(self.get_parameter('time_scale').value)

            self.q = None
            self.policy = DummyPolicy()
            self.finished = False

            self.pub = self.create_publisher(JointTrajectory, self.topic, 10)
            self.create_subscription(
                JointState, '/joint_states', self.on_joint_state, 10)

            period = EXECUTE_STEPS * DT * self.time_scale
            self.create_timer(period, self.on_tick)
            self.get_logger().info(
                f'publishing to {self.topic}, replan every {period:.3f} s, '
                f'time_scale={self.time_scale}')

        def on_joint_state(self, msg):
            try:
                idx = [msg.name.index(n) for n in JOINT_NAMES[:5]]
            except ValueError:
                return          # arm joints not in this message yet
            self.q = [msg.position[i] for i in idx]

        def on_tick(self):
            if self.q is None:
                self.get_logger().warn('waiting for /joint_states', once=True)
                return
            if self.finished:
                return

            T = A.joints_to_T(self.q)
            steps = A.decode_chunk(self.policy(T), T)[:EXECUTE_STEPS]
            points, reason = build_segment(steps, self.q, self.time_scale)
            if reason:
                self.get_logger().warn(f'chunk rejected -- {reason}')
                return          # hold position rather than publish something unsafe

            traj = JointTrajectory()
            traj.joint_names = JOINT_NAMES
            for positions, t in points:
                pt = JointTrajectoryPoint()
                pt.positions = [float(v) for v in positions]
                pt.time_from_start.sec = int(t)
                pt.time_from_start.nanosec = int((t - int(t)) * 1e9)
                traj.points.append(pt)
            self.pub.publish(traj)

            if self.policy.done:
                self.finished = True
                self.get_logger().info('script complete')

    rclpy.init()
    node = ChunkExecutor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='run the maths without ROS')
    ap.add_argument('--ticks', type=int, default=200)
    ap.add_argument('--topic', default=DEFAULT_TOPIC)
    ap.add_argument('--time-scale', type=float, default=TIME_SCALE)
    args = ap.parse_args()

    if args.dry_run:
        return dry_run(args.ticks, args.time_scale)
    return ros_main(args.topic, args.time_scale)


if __name__ == '__main__':
    sys.exit(main())
