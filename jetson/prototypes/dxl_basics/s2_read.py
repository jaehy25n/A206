#!/usr/bin/env python3
"""Step 2 -- read the control table.

A DYNAMIXEL is a little memory-mapped device.  Every setting and every
measurement is a register at a fixed address, and READ/WRITE at an address is
the whole API.  There is no "command" layer above it: telling the arm to move
IS writing four bytes to address 116.

The memory splits in two at address 64, and that split is the single most
important fact about this hardware:

    EEPROM  0..63    persistent, survives power-off,
                     and is READ-ONLY while torque is enabled
    RAM     64..     volatile, RESET TO DEFAULTS EVERY POWER-ON

Operating Mode, Drive Mode, Return Delay Time and the position limits persist.
P/I/D gains (80/82/84), Profile Acceleration (108) and Profile Velocity (112)
do NOT.  And Profile Velocity 0 means INFINITE, not zero -- so a freshly
powered servo answers its first goal position at full slew.

Reads only.  Nothing moves, torque state is untouched.

    python3 s2_read.py --port /dev/ttyACM0
"""

import argparse
import math
import sys

import dxl_raw as D

from s1_ping import JOINT_OF

# (name, address, byte width, signed).  Verified identical on XL430 and XL330,
# which is why one table covers the whole arm.  Address 126 is the only entry
# that differs in MEANING: Present Load on the XL430s, Present Current on the
# XL330s.
REGS = [
    ('Return Delay Time',    9, 1, False),
    ('Drive Mode',          10, 1, False),
    ('Operating Mode',      11, 1, False),
    ('Homing Offset',       20, 4, True),
    ('Velocity Limit',      44, 4, False),
    ('Max Position Limit',  48, 4, True),
    ('Min Position Limit',  52, 4, True),
    ('Torque Enable',       64, 1, False),
    ('Hardware Error',      70, 1, False),
    ('Position D Gain',     80, 2, False),
    ('Position I Gain',     82, 2, False),
    ('Position P Gain',     84, 2, False),
    ('Profile Accel',      108, 4, False),
    ('Profile Velocity',   112, 4, False),
    ('Goal Position',      116, 4, True),
    ('Present Load',       126, 2, True),
    ('Present Position',   132, 4, True),
]

OPERATING_MODE = {0: 'current', 1: 'velocity', 3: 'position',
                  4: 'extended position', 5: 'current-based position',
                  16: 'PWM'}

# Address 70, one bit per complaint.  Bit 1 is unused on the X series.
HW_ERROR_BITS = {0: 'input voltage', 2: 'overheating', 3: 'motor encoder',
                 4: 'electrical shock', 5: 'overload'}

# A hypothesis, not a fact -- 4096 ticks per turn with 2048 at zero.  Homing
# Offset (address 20) shifts it, which is why we read that too: if it is
# nonzero, this formula is wrong by exactly that many ticks, and the
# calibration we could not find in the vendor's C++ is just one register.
CENTER = 2048
TICKS_PER_TURN = 4096


def ticks_to_deg(t):
    return (t - CENTER) / TICKS_PER_TURN * 360.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--baud', type=int, default=1000000)
    ap.add_argument('--ids', default='11,12,13,14,15,16')
    args = ap.parse_args()

    ids = [int(v) for v in args.ids.split(',')]

    try:
        bus = D.Bus(args.port, args.baud)
    except Exception as exc:
        print(f'cannot open {args.port}: {exc}')
        print('run s1_ping.py -- it explains how to fix each cause')
        return 1

    table, alerts, failed = {}, set(), 0
    for dxl_id in ids:
        row = {}
        for name, addr, size, signed in REGS:
            err, data, _, _ = bus.read(dxl_id, addr, size)
            # The top bit of ERR is the hardware ALERT flag, NOT a read failure.
            # The data that came back is perfectly good; the servo is merely
            # also complaining about heat or load.  Treating 0x80 as failure
            # blanks every register the moment one joint gets warm, which looks
            # exactly like a dead bus and is not.
            if err is None or (err & 0x7F):
                row[name] = None
                failed += 1
            else:
                row[name] = D.to_int(data, signed)
            if err is not None and err & 0x80:
                alerts.add(dxl_id)
        table[dxl_id] = row
    bus.close()

    if failed == len(ids) * len(REGS):
        print('every read failed -- run s1_ping.py first')
        return 1

    def cell(v, width=8):
        return f'{"-" if v is None else v:>{width}}'

    print('=== settings the servos are actually running right now ===')
    cols = ['Operating Mode', 'Drive Mode', 'Torque Enable',
            'Position P Gain', 'Position I Gain', 'Position D Gain',
            'Profile Velocity', 'Profile Accel', 'Return Delay Time']
    head = ''.join(f'{c.replace("Position ", "").replace(" Gain", "")[:9]:>10s}'
                   for c in cols)
    print(f'{"":10s}{head}   mode')
    for dxl_id in ids:
        row = table[dxl_id]
        line = f'{JOINT_OF.get(dxl_id, dxl_id):10s}'
        line += ''.join(cell(row[c], 10) for c in cols)
        print(line + f'   {OPERATING_MODE.get(row["Operating Mode"], "?")}')
    print('  P/I/D and both Profile columns are RAM: whatever wrote them last')
    print('  is gone at the next power cycle.  Mode and Drive Mode persist.')

    print()
    print('=== the tick-to-angle question ===')
    print('Homing Offset (addr 20) shifts where the servo calls zero.  If it is')
    print('nonzero, our (raw - 2048) formula is wrong by exactly that much --')
    print('and the calibration hidden in the vendor C++ is just one number.')
    for dxl_id in ids:
        ho = table[dxl_id]['Homing Offset']
        note = '' if not ho else f'   <-- zero is shifted {ho} ticks'
        print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s} Homing Offset {cell(ho, 7)}{note}')

    print()
    print('=== joint limits, asked of the servo itself ===')
    print('Only Mode 3 (position) enforces these.  Mode 4 (extended position)')
    print('ignores them entirely, and 0..4095 means "no limit" in practice.')
    for dxl_id in ids:
        row = table[dxl_id]
        lo, hi = row['Min Position Limit'], row['Max Position Limit']
        mode = row['Operating Mode']
        if lo is None or hi is None:
            continue
        if mode == 4:
            note = '   NOT ENFORCED (extended position mode)'
        elif lo <= 0 and hi >= 4095:
            note = '   full range, i.e. no real limit'
        else:
            note = '   enforced by firmware'
        print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s} raw {lo:5d} .. {hi:5d}   '
              f'{ticks_to_deg(lo):7.1f} .. {ticks_to_deg(hi):6.1f} deg{note}')

    print()
    print('=== where the arm is standing ===')
    print(f'  {"joint":10s} {"raw":>6s} {"deg":>8s} {"rad":>8s} '
          f'{"goal":>7s} {"load":>7s}')
    for dxl_id in ids:
        row = table[dxl_id]
        pos = row['Present Position']
        if pos is None:
            print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s}  read failed')
            continue
        deg = ticks_to_deg(pos)
        print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s} {pos:6d} {deg:8.2f} '
              f'{math.radians(deg):8.4f} {cell(row["Goal Position"], 7)} '
              f'{cell(row["Present Load"], 7)}')

    if alerts:
        print()
        print('=== servos raising the hardware alert bit ===')
        for dxl_id in sorted(alerts):
            hw = table[dxl_id]['Hardware Error']
            if not hw:
                print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s} alert set, '
                      f'addr 70 reads {hw}')
                continue
            why = [t for b, t in HW_ERROR_BITS.items() if hw & (1 << b)]
            print(f'  {JOINT_OF.get(dxl_id, dxl_id):10s} {", ".join(why)}  '
                  f'(addr 70 = {hw})')
        print('  The reads above are still valid -- the alert bit reports servo')
        print('  distress, it does not mean the answer was corrupt.')

    print()
    print('Now look at the arm.  Do those degrees describe the pose you see?')
    print('If a joint reads far from what your eyes say, the tick-to-angle')
    print('mapping needs an offset, and step 3 is where we measure it.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
