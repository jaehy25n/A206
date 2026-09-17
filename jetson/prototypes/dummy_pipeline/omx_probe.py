#!/usr/bin/env python3
"""Read-only probe of the OMX-AI follower over DYNAMIXEL Protocol 2.0.

Writes nothing, moves nothing.  It pings every servo, dumps the configuration
the servos are actually running, and reads their positions -- which is enough to
settle the three things that cost us the most time on the ros2_control path:

  * which joint is which DXL id (the vendor xacro never says; it is positional)
  * what the real joint limits are (datasheet, URDF and xacro all disagreed)
  * whether raw ticks convert to the angles our FK expects

Run with the ros2_control stack STOPPED -- only one process may hold the port.

    pip install dynamixel-sdk
    python3 omx_probe.py --port /dev/ttyACM0
"""

import argparse
import math
import sys

# Control table, Protocol 2.0.  Verified identical on XL430-W250 and XL330-M288
# in dynamixel_sdk/control_table/*.model, which is why one address list covers
# the whole arm.  Only 126 differs in meaning: Present Load on the XL430s
# (joints 1-3), Present Current on the XL330s (joints 4, 5, gripper).
ADDR = {
    'Drive Mode':         (10, 1),
    'Operating Mode':     (11, 1),
    'PWM Limit':          (36, 2),
    'Current Limit':      (38, 2),
    'Max Position Limit': (48, 4),
    'Min Position Limit': (52, 4),
    'Torque Enable':      (64, 1),
    'Position D Gain':    (80, 2),
    'Position I Gain':    (82, 2),
    'Position P Gain':    (84, 2),
    'Profile Acceleration': (108, 4),
    'Profile Velocity':   (112, 4),
    'Goal Position':      (116, 4),
    'Present Load':       (126, 2),
    'Present Velocity':   (128, 4),
    'Present Position':   (132, 4),
}

IDS = [11, 12, 13, 14, 15, 16]
JOINT_OF = {11: 'joint1', 12: 'joint2', 13: 'joint3',
            14: 'joint4', 15: 'joint5', 16: 'gripper'}

# 0..4095 spans -pi..+pi with 2048 at zero, per the .model files'
# value_of_zero_radian_position / min_radian / max_radian.
CENTER = 2048
TICKS_PER_TURN = 4096

OPERATING_MODE = {0: 'current', 1: 'velocity', 3: 'position',
                  4: 'extended position', 5: 'current-based position',
                  16: 'PWM'}


def to_signed(value, size):
    bits = size * 8
    return value - (1 << bits) if value >= (1 << (bits - 1)) else value


def ticks_to_rad(ticks):
    return (ticks - CENTER) / TICKS_PER_TURN * 2.0 * math.pi


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--baud', type=int, default=1000000)
    args = ap.parse_args()

    try:
        from dynamixel_sdk import PortHandler, PacketHandler
    except ImportError:
        print('dynamixel_sdk not installed.  pip install dynamixel-sdk')
        return 1

    port = PortHandler(args.port)
    packet = PacketHandler(2.0)

    if not port.openPort():
        print(f'could not open {args.port} -- is the ros2_control stack still running?')
        return 1
    if not port.setBaudRate(args.baud):
        print(f'could not set baud {args.baud}')
        port.closePort()
        return 1
    print(f'{args.port} @ {args.baud}\n')

    def read(dxl_id, name):
        addr, size = ADDR[name]
        fn = {1: packet.read1ByteTxRx, 2: packet.read2ByteTxRx,
              4: packet.read4ByteTxRx}[size]
        value, comm, err = fn(port, dxl_id, addr)
        if comm != 0 or err != 0:
            return None
        return to_signed(value, size)

    found = []
    print('=== ping ===')
    for dxl_id in IDS:
        model, comm, err = packet.ping(port, dxl_id)
        if comm != 0:
            print(f'  id {dxl_id:2d} ({JOINT_OF[dxl_id]:8s}) no response: '
                  f'{packet.getTxRxResult(comm)}')
            continue
        print(f'  id {dxl_id:2d} ({JOINT_OF[dxl_id]:8s}) model {model}')
        found.append(dxl_id)

    if not found:
        print('\nnothing answered -- check power, cable, and that nothing else '
              'holds the port')
        port.closePort()
        return 1

    print('\n=== configuration the servos are actually running ===')
    cfg = ['Operating Mode', 'Drive Mode', 'Torque Enable',
           'Position P Gain', 'Position I Gain', 'Position D Gain',
           'Profile Velocity', 'Profile Acceleration',
           'Min Position Limit', 'Max Position Limit']
    print(f'{"":10s}' + ''.join(f'{n.replace("Position ", "").replace(" Gain", ""):>9s}'
                                for n in cfg))
    limits = {}
    for dxl_id in found:
        row = f'{JOINT_OF[dxl_id]:10s}'
        for name in cfg:
            v = read(dxl_id, name)
            row += f'{"err" if v is None else v:>9}'
            if name.endswith('Position Limit'):
                limits.setdefault(dxl_id, {})[name] = v
        mode = read(dxl_id, 'Operating Mode')
        print(row + f'   {OPERATING_MODE.get(mode, "?")}')

    print('\n=== limits in degrees (this is the answer the three sources disagreed on) ===')
    for dxl_id in found:
        lo = limits.get(dxl_id, {}).get('Min Position Limit')
        hi = limits.get(dxl_id, {}).get('Max Position Limit')
        if lo is None or hi is None:
            continue
        print(f'  {JOINT_OF[dxl_id]:8s} raw {lo:5d} .. {hi:5d}   '
              f'{math.degrees(ticks_to_rad(lo)):7.1f} .. '
              f'{math.degrees(ticks_to_rad(hi)):6.1f} deg')

    print('\n=== present state ===')
    print(f'  {"joint":8s} {"raw":>7s} {"deg":>8s} {"rad":>9s} {"load/cur":>9s}')
    q = {}
    for dxl_id in found:
        pos = read(dxl_id, 'Present Position')
        load = read(dxl_id, 'Present Load')
        if pos is None:
            print(f'  {JOINT_OF[dxl_id]:8s}  read failed')
            continue
        rad = ticks_to_rad(pos)
        q[dxl_id] = rad
        print(f'  {JOINT_OF[dxl_id]:8s} {pos:7d} {math.degrees(rad):8.2f} '
              f'{rad:9.4f} {"-" if load is None else load:>9}')

    arm = [q[i] for i in (11, 12, 13, 14, 15) if i in q]
    if len(arm) == 5:
        try:
            import omx_kinematics as K
            x, y, z, pitch, roll = K.forward(arm)
            print(f'\n=== our FK on those angles ===')
            print(f'  ee = ({x:.4f}, {y:.4f}, {z:.4f})  '
                  f'pitch={math.degrees(pitch):.2f}  roll={math.degrees(roll):.2f}')
            print('  compare against where the gripper physically is; a large '
                  'mismatch means the tick->rad mapping needs an offset')
        except ImportError:
            pass

    port.closePort()
    return 0


if __name__ == '__main__':
    sys.exit(main())
