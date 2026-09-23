#!/usr/bin/env python3
"""Identify the gravity sag compensation of dxl_driver_node from live data.

Model (per joint, applied inside the driver):
    offset_j = goal_offset_rad[j] - sag_compliance_rad_per_nm[j] * tau_j(q_cmd)

While the arm HOLDS several poses under torque (e.g. replaying a teach recording
with 5 s pauses, or HOME), this tool collects stationary samples of
    error   = commanded - present            (/dxl_driver/motor_state.error_deg)
    tau     = model gravity torque           (/dxl_driver/motor_state.gravity_nm)
    offset  = compensation already applied   (/dxl_driver/motor_state.offset_rad)
reconstructs the raw sag  s = offset - error  (what the arm does with no compensation)
and fits  s = a_j + b_j * tau_j  by least squares. Then
    goal_offset_rad[j]           = a_j
    sag_compliance_rad_per_nm[j] = b_j
are printed ready to paste into omx_f_driver.yaml (restart the driver afterwards).

    ros2 run omx_driver fit_sag.py --duration 90
    ros2 run omx_driver fit_sag.py --duration 90 --csv /home/omx/omx_recordings/sag_samples.csv

Cover 4-5 poses inside the working range (reach 0.15-0.30 m, pitch 30-70 deg);
the fit needs a spread of gravity torque. Do NOT hold full extension (overload).
"""

import argparse
import csv
import math
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node

from omx_msgs.msg import MotorState

PITCH_JOINTS = (1, 2, 3)          # indices of joint2, joint3, joint4


class SagCollector(Node):

    def __init__(self, still_rad, still_window_s):
        super().__init__('fit_sag')
        self.still_rad = still_rad
        self.window = still_window_s
        self.hist = []                # (t, present_rad[6])
        self.samples = []             # rows: t, error_rad[6], tau[6], offset[6], present[6]
        self.n_msgs = 0
        self.create_subscription(MotorState, '/dxl_driver/motor_state', self.on_state, 20)

    def on_state(self, msg):
        self.n_msgs += 1
        now = time.time()
        present = np.asarray(msg.present_rad, float)
        self.hist.append((now, present))
        self.hist = [(t, p) for t, p in self.hist if now - t <= self.window]
        if not msg.torque_enabled or len(msg.gravity_nm) != len(present):
            return
        if any(v != 0.0 for v in msg.error_deg) is False and all(v == 0.0 for v in msg.goal_rad):
            return                    # no command yet
        if len(self.hist) < 3 or now - self.hist[0][0] < self.window * 0.8:
            return
        motion = max(float(np.max(np.abs(p - present))) for _, p in self.hist)
        if motion > self.still_rad:
            return                    # arm still moving
        err = np.radians(np.asarray(msg.error_deg, float))
        self.samples.append(np.concatenate([[now], err, np.asarray(msg.gravity_nm, float),
                                            np.asarray(msg.offset_rad, float), present]))


def fit(samples, names):
    data = np.asarray(samples)
    n = len(names)
    err = data[:, 1:1 + n]
    tau = data[:, 1 + n:1 + 2 * n]
    off = data[:, 1 + 2 * n:1 + 3 * n]
    raw_sag = off - err               # what the arm would do with zero compensation
    print(f'\n{len(data)} stationary samples')
    print(f'{"joint":8s} {"tau range [Nm]":>18s} {"a=offset [rad]":>16s} {"b=compliance":>14s} '
          f'{"rms resid [deg]":>16s}')
    offsets = [0.0] * n
    compl = [0.0] * n
    for j in range(n):
        if j not in PITCH_JOINTS:
            continue
        t, s = tau[:, j], raw_sag[:, j]
        spread = float(t.max() - t.min())
        if spread < 0.05 or len(t) < 20:
            a, b = float(np.mean(s)), 0.0
            note = ' (tau spread too small -> constant only)'
        else:
            A = np.stack([np.ones_like(t), t], axis=1)
            (a, b), *_ = np.linalg.lstsq(A, s, rcond=None)
            note = ''
        resid = s - (a + b * t)
        offsets[j], compl[j] = float(a), float(b)
        print(f'{names[j]:8s} {t.min():8.3f}..{t.max():<8.3f} {a:16.4f} {b:14.4f} '
              f'{math.degrees(float(np.sqrt(np.mean(resid ** 2)))):16.3f}{note}')
    print('\npaste into omx_driver/config/omx_f_driver.yaml (then restart the driver):')
    print('    goal_offset_rad: [' + ', '.join(f'{v:.4f}' for v in offsets) + ']')
    print('    sag_compliance_rad_per_nm: [' + ', '.join(f'{v:.4f}' for v in compl) + ']')
    if any(c < 0 for c in compl):
        print('note: a negative compliance means sag DEcreases with load -> check the payload '
              'parameters / pose coverage before trusting it')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--duration', type=float, default=60.0, help='seconds to collect (Ctrl+C to stop early)')
    ap.add_argument('--still-rad', type=float, default=0.004, help='max joint motion over the window to count as stationary')
    ap.add_argument('--window', type=float, default=0.5, help='stationarity window [s]')
    ap.add_argument('--csv', help='also save the raw samples')
    args = ap.parse_args()

    rclpy.init()
    node = SagCollector(args.still_rad, args.window)
    names = None
    t_end = time.time() + args.duration
    last_report = 0.0
    try:
        while time.time() < t_end:
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.time() - last_report > 5.0:
                last_report = time.time()
                print(f'{args.duration - (t_end - time.time()):5.0f}s  msgs={node.n_msgs}  '
                      f'stationary samples={len(node.samples)}')
    except KeyboardInterrupt:
        pass
    names = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
    node.destroy_node()
    rclpy.shutdown()

    if len(node.samples) < 20:
        print('too few stationary samples (need the arm holding poses under torque with a command '
              'active, e.g. TELEOP replay with pauses or HOME)', file=sys.stderr)
        return 1
    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['t'] + [f'err_{n}' for n in names] + [f'tau_{n}' for n in names] +
                       [f'offset_{n}' for n in names] + [f'present_{n}' for n in names])
            w.writerows(node.samples)
        print(f'saved {args.csv}')
    fit(node.samples, names)
    return 0


if __name__ == '__main__':
    sys.exit(main())
