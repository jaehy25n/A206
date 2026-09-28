#!/usr/bin/env python3
"""A stand-in for the trained policy: same signature, scripted behaviour.

    chunk = policy(T_current)      ->  [H, 10]

It is deliberately shaped like the real thing -- it reads the current EE pose
and emits RELATIVE actions -- so the executor exercises the whole receding
horizon path (anchor, compose, project, IK, replan) without a model.

Waypoints are absolute poses; the dummy walks toward the active one at a capped
step size, which is what a real policy's chunk looks like: large steps during
free-space transit, small steps during alignment, near-zero while the gripper
closes.
"""

import math

import numpy as np

import action_format as A
import omx_kinematics as K

H = 16            # chunk length -- must match the trained model's output head
DT = 0.04         # seconds per step; H*DT = 0.64 s of lookahead
MAX_STEP = 0.010  # metres per step during transit -> 0.25 m/s
FINE_STEP = 0.003 # metres per step during alignment -> 0.075 m/s

# Orientation has to ramp as well, not snap.  The arm parks at all-joints-zero,
# which is nearly fully extended (r = 0.324 m) with the gripper horizontal;
# demanding 45 deg of pitch there lands outside the reachable set and every
# chunk gets rejected.  Ramping position and pitch together keeps the whole
# path reachable.
MAX_ANG_STEP = math.radians(2.5)   # per step -> 62 deg/s at DT = 0.04

# Give up on a waypoint that stops getting closer.  A tolerance the arm cannot
# physically meet deadlocks the script forever: gravity droop put the real arm
# ~6.5 mm from the descend waypoint whose tol was 4 mm, so at_pos never became
# true and it jabbed at the same spot indefinitely.  Widening tol hid that once,
# but any tolerance can be unreachable on a bad day, and a trained policy can
# stall the same way.  Bail out instead, loudly.
STALL_TICKS = 12       # replans with no improvement before moving on
STALL_EPS = 0.0005     # metres of progress that counts as improvement


def _step_toward(cur, goal, limit):
    d = math.atan2(math.sin(goal - cur), math.cos(goal - cur))   # shortest way
    return cur + max(-limit, min(limit, d))


def _wp(x, y, z, pitch_deg, roll_deg, width, tol=0.008, fine=False, dwell=0):
    return {
        'p': np.array([x, y, z], float),
        'pitch': math.radians(pitch_deg),
        'roll': math.radians(roll_deg),
        'width': width,
        'tol': tol,
        'fine': fine,
        'dwell': dwell,   # steps to hold once reached (lets the gripper act)
    }


# Gripper aperture, normalised over the 0..100 deg range of gripper_joint_1.
# Fully open (1.0) splays the fingers alarmingly wide on the real arm and is far
# more than any of these waypoints needs, so "open" is a partial opening.
OPEN = 0.45
CLOSED = 0.0

# A pick sequence in front of the robot.  Approach pitch 45 deg down throughout,
# which keeps every pose comfortably inside the 5-DOF reachable set.
PICK_SCRIPT = [
    _wp(0.20, 0.00, 0.18, 45, 0, OPEN),                          # hover above
    _wp(0.22, 0.00, 0.10, 45, 0, OPEN, tol=0.012, fine=True),    # descend, aligned
    _wp(0.22, 0.00, 0.10, 45, 0, CLOSED, tol=0.012, fine=True, dwell=12),  # close
    _wp(0.20, 0.00, 0.20, 45, 0, CLOSED, tol=0.008),             # lift
    _wp(0.16, 0.12, 0.18, 45, 0, CLOSED, tol=0.008),             # move aside
    _wp(0.16, 0.12, 0.18, 45, 0, OPEN, tol=0.008, dwell=12),     # release
]


class DummyPolicy:
    """Scripted chunk generator with the same interface as a trained policy."""

    def __init__(self, script=None):
        self.script = script if script is not None else PICK_SCRIPT
        self.idx = 0
        self.dwell_left = 0
        self.best = None        # closest this waypoint has been approached
        self.stall = 0          # consecutive replans with no improvement
        self.notice = None      # one-shot message for the caller to log

    @property
    def done(self):
        return self.idx >= len(self.script)

    def _advance(self):
        self.idx += 1
        self.best = None
        self.stall = 0
        self.dwell_left = 0

    def take_notice(self):
        """Pop the pending message, if any."""
        n, self.notice = self.notice, None
        return n

    def __call__(self, T_current):
        """T_current (4x4, base frame) -> chunk [H, 10] of relative actions."""
        if self.done:
            return self.hold(T_current)

        wp = self.script[self.idx]
        p_now = T_current[:3, 3].copy()
        _, _, _, pitch_now, roll_now = A.project_to_5dof(T_current)

        # a waypoint counts as reached only when orientation has settled too,
        # otherwise the script advances while the wrist is still swinging
        dist = float(np.linalg.norm(wp['p'] - p_now))
        at_pos = dist <= wp['tol']
        at_ang = (abs(_step_toward(pitch_now, wp['pitch'], math.pi) - pitch_now)
                  <= MAX_ANG_STEP
                  and abs(_step_toward(roll_now, wp['roll'], math.pi) - roll_now)
                  <= MAX_ANG_STEP)

        if at_pos and at_ang:
            if self.dwell_left == 0:
                self.dwell_left = wp['dwell']
            if self.dwell_left > 0:
                self.dwell_left -= 1
                if self.dwell_left == 0:
                    self._advance()
            else:
                self._advance()
            if self.done:
                return self.hold(T_current, width=wp['width'])
        elif self.best is None or dist < self.best - STALL_EPS:
            self.best = dist
            self.stall = 0
        else:
            self.stall += 1
            if self.stall >= STALL_TICKS:
                self.notice = (
                    f'waypoint {self.idx} abandoned after {STALL_TICKS} replans '
                    f'with no progress: closest {self.best * 1000:.1f} mm, '
                    f'tol {wp["tol"] * 1000:.1f} mm -- the arm cannot reach it')
                self._advance()
                if self.done:
                    return self.hold(T_current, width=wp['width'])

        wp = self.script[min(self.idx, len(self.script) - 1)]
        step = FINE_STEP if wp['fine'] else MAX_STEP

        R_inv = T_current[:3, :3].T
        chunk = np.zeros((H, A.ACTION_DIM))
        p = p_now.copy()
        pitch, roll = pitch_now, roll_now
        for k in range(H):
            to_go = wp['p'] - p
            dist = np.linalg.norm(to_go)
            p = wp['p'].copy() if dist <= step else p + to_go / dist * step

            # ramp orientation at the same time as position -- snapping straight
            # to the waypoint's pitch makes the first chunk unreachable
            pitch = _step_toward(pitch, wp['pitch'], MAX_ANG_STEP)
            roll = _step_toward(roll, wp['roll'], MAX_ANG_STEP)

            # yaw follows the target azimuth; the arm forces this anyway.
            # Measure it about the joint1 axis, which sits at x = BASE_X and not
            # at the base origin -- using atan2(y, x) instead asks for a yaw the
            # arm will never give (1.85 deg off at the aside waypoint), and the
            # projection then dumps the difference into roll.
            yaw = math.atan2(p[1], p[0] - K.BASE_X)
            R_abs = A.rpy_to_rot(yaw, pitch, roll)

            chunk[k, 0:3] = R_inv @ (p - T_current[:3, 3])
            chunk[k, 3:9] = A.rot_to_6d(R_inv @ R_abs)
            chunk[k, 9] = wp['width']
        return chunk

    def hold(self, T_current, width=OPEN):
        """Zero-motion chunk -- what the policy emits when nothing should move."""
        chunk = np.zeros((H, A.ACTION_DIM))
        chunk[:, 3:9] = A.rot_to_6d(np.eye(3))
        chunk[:, 9] = width
        return chunk


# -----------------------------------------------------------------------------
if __name__ == '__main__':
    # start where the real arm parks: all joints zero
    q = [0.0, 0.0, 0.0, 0.0, 0.0]
    sx, sy, sz, spitch, _ = K.forward(q)
    print(f'start ee = ({sx:.3f}, {sy:.3f}, {sz:.3f})  '
          f'pitch={math.degrees(spitch):.1f} deg')

    policy = DummyPolicy()
    executed = 3          # steps consumed per replan (receding horizon)
    ok = bad = 0
    max_drop = 0.0

    for tick in range(400):
        T = A.joints_to_T(q)
        chunk = policy(T)
        steps = A.decode_chunk(chunk, T, q_ref=q)

        for s in steps[:executed]:
            max_drop = max(max_drop, abs(s['yaw_drop']))
            if s['problem'] or s['q'] is None:
                bad += 1
                print(f'  tick {tick}: {s["problem"]}')
            else:
                ok += 1
                q = s['q']

        if tick % 40 == 0 or policy.done:
            x, y, z, pitch, _ = K.forward(q)
            print(f'tick {tick:3d}  wp={policy.idx}  '
                  f'ee=({x:.3f}, {y:.3f}, {z:.3f})  '
                  f'pitch={math.degrees(pitch):5.1f}  '
                  f'grip={math.degrees(steps[0]["gripper"]):5.1f}')
        if policy.done:
            break

    print(f'\nsteps ok={ok} bad={bad}  '
          f'max discarded yaw={math.degrees(max_drop):.2f} deg')
