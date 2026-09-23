#!/usr/bin/env python3
"""DYNAMIXEL X-series diagnostics for the OMX-F arm (Protocol 2.0).

STOP dxl_driver_node FIRST: only one process may use the serial port.

    ros2 run omx_driver dxl_diag.py                       # full snapshot of ids 11-16
    ros2 run omx_driver dxl_diag.py --watch 0.5           # live table twice a second (Ctrl+C to stop)
    ros2 run omx_driver dxl_diag.py --watch 0.5 --csv /home/omx/omx_recordings/hold_test.csv
    ros2 run omx_driver dxl_diag.py --reboot 12           # reboot motor id 12 (clears its alarm)
    ros2 run omx_driver dxl_diag.py --ids 11,12 --port /dev/ttyACM0

What to look for when a joint "goes limp":
    hardware_error   Overload (32): sustained load near the motor's limit -> pose / payload / I gain
                     Overheating (4): temperature >= Temperature Limit -> let it cool
                     InputVoltage (1): supply dipped below Min Voltage Limit -> adapter / cable
    pwm_percent      how hard the motor is pushing. An XL430 sitting above ~45-50 % for tens of
                     seconds trips Overload (measured: joint2 died holding a steady -56 %).
    temperature      XL430/XL330 shut down at 72 C (Temperature Limit register).
"""

import argparse
import csv
import datetime
import shutil
import subprocess
import sys
import time

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

# ---------------------------------------------------------------- register map
EEPROM = [  # (addr, size, name, formatter)
    (0, 2, 'model_number', None),
    (6, 1, 'firmware_version', None),
    (7, 1, 'id', None),
    (8, 1, 'baud_rate', lambda v: {0: 9600, 1: 57600, 2: 115200, 3: 1000000, 4: 2000000,
                                   5: 3000000, 6: 4000000, 7: 4500000}.get(v, v)),
    (9, 1, 'return_delay_time_us', lambda v: v * 2),
    (10, 1, 'drive_mode', lambda v: f'{v} (' + ', '.join(
        n for b, n in ((1, 'reverse'), (4, 'time-based-profile'), (8, 'torque-on-by-goal')) if v & b) + ')'),
    (11, 1, 'operating_mode', lambda v: f'{v} ' + {0: 'current', 1: 'velocity', 3: 'position',
                                                     4: 'extended-position', 5: 'current-based-position',
                                                     16: 'pwm'}.get(v, '?')),
    (20, 4, 'homing_offset_ticks', 'int32'),
    (31, 1, 'temperature_limit_c', None),
    (32, 2, 'max_voltage_limit_v', lambda v: v / 10.0),
    (34, 2, 'min_voltage_limit_v', lambda v: v / 10.0),
    (36, 2, 'pwm_limit_percent', lambda v: round(v / 885.0 * 100.0, 1)),
    (38, 2, 'current_limit_ma', None),          # XL330 only (XL430 reads 0/garbage)
    (44, 4, 'velocity_limit_rpm', lambda v: round(v * 0.229, 1)),
    (48, 4, 'max_position_limit_ticks', 'int32'),
    (52, 4, 'min_position_limit_ticks', 'int32'),
    (63, 1, 'shutdown_mask', lambda v: f'{v} (' + describe_error(v) + ')'),
]
RAM = [
    (64, 1, 'torque_enable', None),
    (68, 1, 'status_return_level', None),
    (70, 1, 'hardware_error_status', lambda v: f'{v} ({describe_error(v)})'),
    (76, 2, 'velocity_i_gain', None),
    (78, 2, 'velocity_p_gain', None),
    (80, 2, 'position_d_gain', None),
    (82, 2, 'position_i_gain', None),
    (84, 2, 'position_p_gain', None),
    (90, 2, 'feedforward_1st_gain', None),
    (88, 2, 'feedforward_2nd_gain', None),
    (98, 1, 'bus_watchdog', None),
    (100, 2, 'goal_pwm', 'int16'),
    (102, 2, 'goal_current_ma', 'int16'),
    (108, 4, 'profile_acceleration', None),
    (112, 4, 'profile_velocity', None),
    (116, 4, 'goal_position_ticks', 'int32'),
    (122, 1, 'moving', None),
    (123, 1, 'moving_status', None),
    (124, 2, 'present_pwm_percent', lambda v: round(s16(v) / 885.0 * 100.0, 1)),
    (126, 2, 'present_load_or_current', 'int16'),
    (128, 4, 'present_velocity_rpm', lambda v: round(s32(v) * 0.229, 2)),
    (132, 4, 'present_position_ticks', 'int32'),
    (144, 2, 'present_input_voltage_v', lambda v: v / 10.0),
    (146, 1, 'present_temperature_c', None),
]
MODELS = {1060: 'XL430-W250', 1190: 'XL330-M077', 1200: 'XL330-M288'}
JOINTS = {11: 'joint1', 12: 'joint2', 13: 'joint3', 14: 'joint4', 15: 'joint5', 16: 'gripper'}
TICKS_PER_REV = 4096


def s16(v):
    return v - 65536 if v > 32767 else v


def s32(v):
    return v - 4294967296 if v > 2147483647 else v


def describe_error(v):
    names = [(1, 'InputVoltage'), (4, 'Overheating'), (8, 'MotorEncoder'),
             (16, 'ElectricalShock'), (32, 'Overload')]
    s = [n for b, n in names if v & b]
    return '+'.join(s) if s else 'none'


class Bus:

    def __init__(self, port, baud):
        self.port = PortHandler(port)
        if not self.port.openPort():
            raise RuntimeError(f'cannot open {port}')
        self.port.setBaudRate(baud)
        self.ph = PacketHandler(2.0)

    def read(self, dxl_id, addr, size):
        fn = {1: self.ph.read1ByteTxRx, 2: self.ph.read2ByteTxRx, 4: self.ph.read4ByteTxRx}[size]
        v, rc, err = fn(self.port, dxl_id, addr)
        if rc != COMM_SUCCESS:
            return None
        return v

    def ping(self, dxl_id):
        model, rc, _ = self.ph.ping(self.port, dxl_id)
        return model if rc == COMM_SUCCESS else None

    def reboot(self, dxl_id):
        rc, err = self.ph.reboot(self.port, dxl_id)
        return rc == COMM_SUCCESS, self.ph.getTxRxResult(rc) if rc != COMM_SUCCESS else 'ok'

    def close(self):
        self.port.closePort()


def fmt(value, formatter):
    if value is None:
        return 'n/a'
    if formatter == 'int16':
        return str(s16(value))
    if formatter == 'int32':
        return str(s32(value))
    if callable(formatter):
        return str(formatter(value))
    return str(value)


def snapshot(bus, ids):
    for dxl_id in ids:
        model = bus.ping(dxl_id)
        print(f'\n===== id {dxl_id} {JOINTS.get(dxl_id, "")}  '
              f'{MODELS.get(model, "model " + str(model)) if model else "NO RESPONSE"} =====')
        if model is None:
            continue
        print('--- EEPROM (configuration) ---')
        for addr, size, name, f in EEPROM:
            if name == 'current_limit_ma' and model == 1060:
                continue  # XL430 has no current control
            print(f'  {name:28s} {fmt(bus.read(dxl_id, addr, size), f)}')
        print('--- RAM (live) ---')
        for addr, size, name, f in RAM:
            if name == 'goal_current_ma' and model == 1060:
                continue
            v = bus.read(dxl_id, addr, size)
            extra = ''
            if name in ('goal_position_ticks', 'present_position_ticks') and v is not None:
                extra = f'   ({(s32(v) - 2048) * 360.0 / TICKS_PER_REV:+.2f} deg from 2048)'
            if name == 'present_load_or_current' and v is not None:
                extra = f'   ({s16(v) / 10.0:+.1f} % load)' if model == 1060 else f'   ({s16(v)} mA)'
            print(f'  {name:28s} {fmt(v, f)}{extra}')
        g = bus.read(dxl_id, 116, 4)
        p = bus.read(dxl_id, 132, 4)
        if g is not None and p is not None:
            print(f'  {"goal - present":28s} {(s32(g) - s32(p)) * 360.0 / TICKS_PER_REV:+.2f} deg')


def watch(bus, ids, period, csv_path):
    models = {i: bus.ping(i) for i in ids}
    writer = None
    if csv_path:
        f = open(csv_path, 'w', newline='', encoding='utf-8')
        writer = csv.writer(f)
        writer.writerow(['time', 'id', 'joint', 'torque', 'hw_error', 'temp_c', 'voltage_v',
                         'pwm_percent', 'load_raw', 'goal_ticks', 'present_ticks', 'error_deg'])
    hot_since = {}
    print(f'{"time":8s} {"id":>2s} {"joint":8s} {"trq":>3s} {"hw":>3s} {"tmp":>4s} {"volt":>5s} '
          f'{"pwm%":>6s} {"load":>6s} {"goal":>6s} {"pres":>6s} {"err°":>6s}  note')
    try:
        while True:
            t0 = time.time()
            stamp = datetime.datetime.now().strftime('%H:%M:%S')
            for i in ids:
                if models[i] is None:
                    print(f'{stamp} {i:>2d} {JOINTS.get(i, ""):8s} NO RESPONSE')
                    continue
                trq = bus.read(i, 64, 1)
                hw = bus.read(i, 70, 1)
                tmp = bus.read(i, 146, 1)
                volt = bus.read(i, 144, 2)
                pwm = bus.read(i, 124, 2)
                load = bus.read(i, 126, 2)
                goal = bus.read(i, 116, 4)
                pres = bus.read(i, 132, 4)
                if None in (trq, hw, tmp, volt, pwm, load, goal, pres):
                    print(f'{stamp} {i:>2d} {JOINTS.get(i, ""):8s} read error')
                    continue
                pwm_pct = s16(pwm) / 885.0 * 100.0
                err_deg = (s32(goal) - s32(pres)) * 360.0 / TICKS_PER_REV if trq else 0.0
                note = ''
                if hw:
                    note = 'ALARM ' + describe_error(hw)
                elif abs(pwm_pct) > 45.0:
                    hot_since.setdefault(i, t0)
                    note = f'pwm high {t0 - hot_since[i]:.0f}s -> overload risk'
                else:
                    hot_since.pop(i, None)
                if tmp >= 60 and not hw:
                    note += ' hot'
                load_txt = f'{s16(load) / 10.0:+.1f}%' if models[i] == 1060 else f'{s16(load):+d}mA'
                print(f'{stamp} {i:>2d} {JOINTS.get(i, ""):8s} {trq:>3d} {hw:>3d} {tmp:>4d} {volt / 10.0:>5.1f} '
                      f'{pwm_pct:>6.1f} {load_txt:>6s} {s32(goal):>6d} {s32(pres):>6d} {err_deg:>+6.2f}  {note}')
                if writer:
                    writer.writerow([f'{t0:.3f}', i, JOINTS.get(i, ''), trq, hw, tmp, volt / 10.0,
                                     f'{pwm_pct:.1f}', s16(load), s32(goal), s32(pres), f'{err_deg:.3f}'])
            print('-' * 96)
            time.sleep(max(0.0, period - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if writer:
            f.close()
            print(f'saved {csv_path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--baud', type=int, default=1000000)
    ap.add_argument('--ids', default='11,12,13,14,15,16')
    ap.add_argument('--watch', type=float, metavar='SEC', help='live table every SEC seconds')
    ap.add_argument('--csv', help='with --watch: log every row to this csv')
    ap.add_argument('--reboot', help='comma separated ids to reboot (clears alarm, torque off)')
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(',')]

    if shutil.which('pgrep') and subprocess.run(['pgrep', '-f', 'dxl_driver_node'],
                                                capture_output=True).returncode == 0:
        print('dxl_driver_node is running and owns the port. Stop it first '
              '(or use its /dxl_driver/motor_state topic instead).', file=sys.stderr)
        return 1

    bus = Bus(args.port, args.baud)
    try:
        if args.reboot:
            for i in (int(x) for x in args.reboot.split(',')):
                ok, msg = bus.reboot(i)
                print(f'reboot id {i}: {msg}')
            time.sleep(1.0)
            for i in (int(x) for x in args.reboot.split(',')):
                hw = bus.read(i, 70, 1)
                print(f'id {i} hardware_error now: {hw} ({describe_error(hw or 0)})')
            return 0
        if args.watch:
            watch(bus, ids, args.watch, args.csv)
        else:
            snapshot(bus, ids)
    finally:
        bus.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
