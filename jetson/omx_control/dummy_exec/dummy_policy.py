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

H = 16            # chunk length -- must match the trained model's output head
DT = 0.04         # seconds per step; H*DT = 0.64 s of lookahead
MAX_STEP = 0.010  # metres per step during transit -> 0.25 m/s
FINE_STEP = 0.003 # metres per step during alignment -> 0.075 m/s


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


# A pick sequence in front of the robot.  Approach pitch 45 deg down throughout,
# which keeps every pose comfortably inside the 5-DOF reachable set.
PICK_SCRIPT = [
    _wp(0.20, 0.00, 0.18, 45, 0, 1.0),                          # hover above
    _wp(0.22, 0.00, 0.10, 45, 0, 1.0, tol=0.004, fine=True),    # descend, aligned
    _wp(0.22, 0.00, 0.10, 45, 0, 0.0, tol=0.004, fine=True, dwell=12),  # close
    _wp(0.20, 0.00, 0.20, 45, 0, 0.0, tol=0.008),               # lift
    _wp(0.16, 0.12, 0.18, 45, 0, 0.0, tol=0.008),               # move aside
    _wp(0.16, 0.12, 0.18, 45, 0, 1.0, tol=0.008, dwell=12),     # release
]


class DummyPolicy:
    """Scripted chunk generator with the same interface as a trained policy."""

    def __init__(self, script=None):
        self.script = script if script is not None else PICK_SCRIPT
        self.idx = 0
        self.dwell_left = 0

    @property
    def done(self):
        return self.idx >= len(self.script)

    def __call__(self, T_current):
        """T_current (4x4, base frame) -> chunk [H, 10] of relative actions."""
        if self.done:
            return self.hold(T_current)

        wp = self.script[self.idx]
        p_now = T_current[:3, 3].copy()

        if np.linalg.norm(wp['p'] - p_now) <= wp['tol']:
            if self.dwell_left == 0:
                self.dwell_left = wp['dwell']
            if self.dwell_left > 0:
                self.dwell_left -= 1
                if self.dwell_left == 0:
                    self.idx += 1
            else:
                self.idx += 1
            if self.done:
                return self.hold(T_current, width=wp['width'])

        wp = self.script[min(self.idx, len(self.script) - 1)]
        step = FINE_STEP if wp['fine'] else MAX_STEP

        R_inv = T_current[:3, :3].T
        chunk = np.zeros((H, A.ACTION_DIM))
        p = p_now.copy()
        for k in range(H):
            to_go = wp['p'] - p
            dist = np.linalg.norm(to_go)
            p = wp['p'].copy() if dist <= step else p + to_go / dist * step

            # target orientation: yaw follows the target azimuth (the arm will
            # force this anyway), pitch/roll come from the waypoint
            yaw = math.atan2(p[1], p[0])
            R_abs = A.rpy_to_rot(yaw, wp['pitch'], wp['roll'])

            chunk[k, 0:3] = R_inv @ (p - T_current[:3, 3])
            chunk[k, 3:9] = A.rot_to_6d(R_inv @ R_abs)
            chunk[k, 9] = wp['width']
        return chunk

    def hold(self, T_current, width=1.0):
        """Zero-motion chunk -- what the policy emits when nothing should move."""
        chunk = np.zeros((H, A.ACTION_DIM))
        chunk[:, 3:9] = A.rot_to_6d(np.eye(3))
        chunk[:, 9] = width
        return chunk


# -----------------------------------------------------------------------------
if __name__ == '__main__':
    import omx_kinematics as K

    # start from a pose the arm can actually hold
    q = K.inverse(0.20, 0.0, 0.18, math.radians(45), 0.0)
    print('start joints [deg]:', [round(math.degrees(v), 1) for v in q])

    policy = DummyPolicy()
    executed = 3          # steps consumed per replan (receding horizon)
    ok = bad = 0
    max_drop = 0.0

    for tick in range(400):
        T = A.joints_to_T(q)
        chunk = policy(T)
        steps = A.decode_chunk(chunk, T)

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
