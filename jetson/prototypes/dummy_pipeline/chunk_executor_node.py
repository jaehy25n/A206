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

EXECUTE_STEPS = 3        # steps that elapse before we replan (receding horizon)

# Steps actually put in the message.  JointTrajectoryController falls back to
# LINEAR interpolation when a point carries no velocity, which puts a velocity
# step at every waypoint; supplying velocities gets the cubic spline back.  But
# the final point of a trajectory must have zero velocity or JTC rejects the
# whole message (allow_nonzero_velocity_at_trajectory_end defaults to false, and
# that parameter lives in the vendor's config).  Publishing further ahead than
# we execute puts that zero-velocity tail beyond the replan point, so the arm is
# always in the smooth middle of the spline and never reaches the deceleration.
PUBLISH_STEPS = 8

TIME_SCALE = 2.0         # >1 slows execution down; keep high for first runs

# Cap how fast a joint is asked to move.  This started out as a fixed per-step
# angle, which is the wrong quantity: the same 6 deg is gentle at time_scale 8
# and violent at 0.5, because the step's duration is DT * time_scale.  A real
# pick from the arm's folded pose legitimately needs 6.8 deg in one step, so the
# fixed threshold rejected correct motion while still saying nothing about the
# actual speed.  The URDF rates every joint at 4.8 rad/s (275 deg/s); 180 deg/s
# leaves a wide margin and still catches IK branch flips, which jump far more.
MAX_JOINT_VEL = math.radians(180.0)   # rad/s


def build_segment(steps, q_now, time_scale):
    """Turn decoded chunk steps into (points, reason).

    points is a list of (positions, velocities, time_from_start_seconds).
    reason is None if the whole segment is safe, else why it was rejected.
    """
    dt = DT * time_scale
    poses, times = [], []
    q_prev = list(q_now)
    for k, s in enumerate(steps):
        if s['problem'] or s['q'] is None:
            return None, f'step {k}: {s["problem"] or "no IK solution"}'
        jump = max(abs(a - b) for a, b in zip(q_prev, s['q']))
        vel = jump / dt
        if vel > MAX_JOINT_VEL:
            return None, (f'step {k}: {math.degrees(vel):.0f} deg/s exceeds '
                          f'{math.degrees(MAX_JOINT_VEL):.0f} deg/s '
                          f'({math.degrees(jump):.1f} deg in {dt:.3f} s)')
        poses.append(list(s['q']) + [s['gripper']])
        times.append((k + 1) * dt)
        q_prev = s['q']

    # Central difference over the neighbours, with the arm's present pose
    # standing in for the point before the first one.  The last point gets zero
    # velocity, which is what JTC requires of a trajectory's end.
    prev = list(q_now) + [poses[0][-1]]
    points = []
    for k, p in enumerate(poses):
        if k == len(poses) - 1:
            vels = [0.0] * len(p)
        else:
            before = prev if k == 0 else poses[k - 1]
            vels = [(a - b) / (2.0 * dt) for a, b in zip(poses[k + 1], before)]
        points.append((p, vels, times[k]))
    return points, None


# --- dry run (no ROS) ---------------------------------------------------------
def dry_run(ticks, time_scale):
    # Start where the real arm actually parks: all joints zero, i.e. nearly
    # fully extended and horizontal.  Seeding this with a convenient pose is
    # exactly how the first version hid an unreachable opening chunk.
    q = [0.0, 0.0, 0.0, 0.0, 0.0]
    policy = DummyPolicy()
    published = rejected = 0

    for tick in range(ticks):
        T = A.joints_to_T(q)
        steps = A.decode_chunk(policy(T), T, q_ref=q)[:PUBLISH_STEPS]
        points, reason = build_segment(steps, q, time_scale)
        if reason:
            rejected += 1
            print(f'tick {tick:3d}  REJECT  {reason}')
        else:
            published += 1
            q = points[EXECUTE_STEPS - 1][0][:5]   # only this much elapses
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
def ros_main(topic, time_scale, hold=False):
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
            self.grip = 0.0
            self.policy = DummyPolicy()
            self.finished = False
            self.hold = hold

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
            if JOINT_NAMES[5] in msg.name:
                self.grip = msg.position[msg.name.index(JOINT_NAMES[5])]

        def on_tick(self):
            if self.q is None:
                self.get_logger().warn('waiting for /joint_states', once=True)
                return
            if self.finished:
                return

            if self.hold:
                # First-contact test on real hardware: exercise the whole comms
                # path -- joint_states in, JointTrajectory out, controller
                # accepts it -- while commanding exactly where the arm already
                # is.  Nothing should move.  If it twitches, the frame or joint
                # ordering is wrong and you want to know that before it swings.
                x, y, z, pitch, roll = K.forward(self.q)
                self.get_logger().info(
                    f'HOLD  ee=({x:.3f}, {y:.3f}, {z:.3f}) '
                    f'pitch={math.degrees(pitch):.1f} roll={math.degrees(roll):.1f}',
                    throttle_duration_sec=2.0)
                traj = JointTrajectory()
                traj.joint_names = JOINT_NAMES
                pt = JointTrajectoryPoint()
                pt.positions = [float(v) for v in self.q] + [float(self.grip)]
                pt.time_from_start.sec = 0
                pt.time_from_start.nanosec = int(0.2 * 1e9)
                traj.points.append(pt)
                self.pub.publish(traj)
                return

            T = A.joints_to_T(self.q)
            chunk = self.policy(T)
            notice = self.policy.take_notice()
            if notice:
                self.get_logger().warn(notice)
            steps = A.decode_chunk(chunk, T, q_ref=self.q)[:PUBLISH_STEPS]
            points, reason = build_segment(steps, self.q, self.time_scale)
            if reason:
                self.get_logger().warn(f'chunk rejected -- {reason}')
                return          # hold position rather than publish something unsafe

            traj = JointTrajectory()
            traj.joint_names = JOINT_NAMES
            for positions, velocities, t in points:
                pt = JointTrajectoryPoint()
                pt.positions = [float(v) for v in positions]
                pt.velocities = [float(v) for v in velocities]
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
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        # SIGTERM (e.g. from `timeout`) already shuts the context down; calling
        # shutdown() again raises and buries whatever the run actually printed.
        if rclpy.ok():
            rclpy.shutdown()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='run the maths without ROS')
    ap.add_argument('--hold', action='store_true',
                    help='command the current pose only -- nothing should move. '
                         'Use this as the first test on real hardware.')
    ap.add_argument('--ticks', type=int, default=200)
    ap.add_argument('--topic', default=DEFAULT_TOPIC)
    ap.add_argument('--time-scale', type=float, default=TIME_SCALE)
    args = ap.parse_args()

    if args.dry_run:
        return dry_run(args.ticks, args.time_scale)
    return ros_main(args.topic, args.time_scale, hold=args.hold)


if __name__ == '__main__':
    sys.exit(main())
