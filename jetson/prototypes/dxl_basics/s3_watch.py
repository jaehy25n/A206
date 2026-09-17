#!/usr/bin/env python3
"""Step 3 -- move the arm by hand and watch the numbers follow.

This is the smallest complete thing in robot control: hardware -> number ->
meaning.  It answers three questions that no document answers, by experiment:

  which DXL id is which joint     push a joint, see which row moves.  The
                                  vendor xacro never says this in prose; it is
                                  inferred from the ORDER of its <gpio> blocks,
                                  which is not evidence.
  how ticks map to angles         bend a joint to a rough right angle and see
                                  whether the reading moves by ~1024 ticks.
  whether zero is where you think Homing Offset (addr 20) shifts what the servo
                                  calls zero, and it is printed below.

    python3 s3_watch.py                    read only, nothing changes
    python3 s3_watch.py --torque-off       let go of the motors first

WITHOUT --torque-off the arm stays exactly as it is and this is a read-only
observer.  WITH it, the motors are released and the arm becomes limp.

    *** FOLD THE ARM AND HOLD IT BEFORE USING --torque-off ***

    There are no brakes.  An extended arm falls, and most of its 560 g is
    above joint2.  Torque off is safe only from a folded, supported pose.

Nothing else may hold the serial port -- one wire, one talker.
"""

import argparse
import math
import sys
import time

import dxl_raw as D

JOINT_OF = {11: 'joint1', 12: 'joint2', 13: 'joint3',
            14: 'joint4', 15: 'joint5', 16: 'gripper'}

TORQUE_ENABLE = 64        # RAM, 1 byte.  0 = motors released
PRESENT_POSITION = 132    # RAM, 4 bytes, signed
HOMING_OFFSET = 20        # EEPROM, 4 bytes, signed
OPERATING_MODE = 11       # EEPROM, 1 byte

MODE_NAME = {0: 'current', 1: 'velocity', 3: 'position',
             4: 'extended position', 5: 'current-based position', 16: 'PWM'}

TICKS_PER_TURN = 4096     # the hypothesis this exercise tests
CENTER = 2048

MOVING_TICKS = 3          # below this, it is sensor noise, not your hand


def ticks_to_deg(t):
    return (t - CENTER) / TICKS_PER_TURN * 360.0


def read_int(bus, dxl_id, addr, size, signed=True):
    err, data, _, _ = bus.read(dxl_id, addr, size)
    # The top bit of ERR is a hardware ALERT, not a failed read -- the data is
    # fine, the servo is merely also complaining about heat or load.
    if err is None or (err & 0x7F):
        return None
    return D.to_int(data, signed)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--baud', type=int, default=1000000)
    ap.add_argument('--ids', default='11,12,13,14,15,16')
    ap.add_argument('--hz', type=float, default=10.0)
    ap.add_argument('--torque-off', action='store_true',
                    help='release the motors so you can backdrive by hand')
    args = ap.parse_args()

    ids = [int(v) for v in args.ids.split(',')]

    try:
        bus = D.Bus(args.port, args.baud)
    except PermissionError:
        print(f'no permission for {args.port}.  try:')
        print(f'  sudo python3 {sys.argv[0]} ' + ' '.join(sys.argv[1:]))
        return 1
    except Exception as exc:
        print(f'cannot open {args.port}: {exc}')
        print('  something else may hold it -- sudo fuser -v /dev/ttyACM0')
        return 1

    # --- what we are looking at, before we touch anything -------------------
    print(f'{args.port} @ {args.baud} via {bus.backend}')
    print()
    print(f'  {"id":>3s} {"joint":9s} {"mode":22s} {"homing off":>11s} '
          f'{"torque":>7s} {"now (deg)":>10s}')
    start, missing = {}, []
    for dxl_id in ids:
        pos = read_int(bus, dxl_id, PRESENT_POSITION, 4)
        if pos is None:
            print(f'  {dxl_id:3d} {JOINT_OF.get(dxl_id, "?"):9s} no answer')
            missing.append(dxl_id)
            continue
        mode = read_int(bus, dxl_id, OPERATING_MODE, 1, signed=False)
        ho = read_int(bus, dxl_id, HOMING_OFFSET, 4)
        tq = read_int(bus, dxl_id, TORQUE_ENABLE, 1, signed=False)
        start[dxl_id] = pos
        print(f'  {dxl_id:3d} {JOINT_OF.get(dxl_id, "?"):9s} '
              f'{MODE_NAME.get(mode, str(mode)):22s} {str(ho):>11s} '
              f'{"ON" if tq else "off":>7s} {ticks_to_deg(pos):10.2f}')

    for dxl_id in missing:
        ids.remove(dxl_id)
    if not ids:
        print()
        print('nothing answered -- run s1_ping.py, it diagnoses this')
        bus.close()
        return 1

    if any(v for v in [read_int(bus, i, HOMING_OFFSET, 4) for i in ids] if v):
        print()
        print('  A nonzero Homing Offset means the servo already shifts its own')
        print('  zero.  Present Position INCLUDES it, so the mechanical angle is')
        print('  (reading - offset).  This is very likely the calibration that')
        print('  looked like it was hidden in the vendor C++.')

    # --- the one write, and only if asked -----------------------------------
    if args.torque_off:
        print()
        print('  ABOUT TO RELEASE THE MOTORS.')
        print('  The arm has no brakes and will fall if it is extended.')
        print('  Fold it, put a hand under it, THEN continue.')
        try:
            if input('  type yes to release: ').strip().lower() != 'yes':
                print('  cancelled, nothing was written')
                bus.close()
                return 0
        except (EOFError, KeyboardInterrupt):
            print('\n  cancelled, nothing was written')
            bus.close()
            return 0
        for dxl_id in ids:
            err, _, _, _ = bus.write(dxl_id, TORQUE_ENABLE, [0])
            state = read_int(bus, dxl_id, TORQUE_ENABLE, 1, signed=False)
            ok = 'released' if state == 0 else f'STILL ON (err={err})'
            print(f'  {JOINT_OF.get(dxl_id, dxl_id):9s} {ok}')
        print('  Written AND read back -- never trust a write you did not verify.')

    # --- the loop -----------------------------------------------------------
    print()
    print('Now push the joints by hand.  Watch which row moves.')
    print('That is your id-to-joint map, established by experiment.')
    print('Ctrl-C to stop.')
    print()

    header = (f'  {"id":>3s} {"joint":9s} {"raw":>7s} {"deg":>9s} '
              f'{"rad":>9s} {"moved":>9s}')
    print(header)
    for _ in ids:
        print()
    lines = len(ids)

    prev = dict(start)
    period = 1.0 / args.hz
    try:
        while True:
            rows = []
            for dxl_id in ids:
                pos = read_int(bus, dxl_id, PRESENT_POSITION, 4)
                if pos is None:
                    rows.append(f'  {dxl_id:3d} {JOINT_OF.get(dxl_id, "?"):9s} '
                                f'{"read failed":>37s}')
                    continue
                deg = ticks_to_deg(pos)
                moved = deg - ticks_to_deg(start[dxl_id])
                live = abs(pos - prev.get(dxl_id, pos)) >= MOVING_TICKS
                prev[dxl_id] = pos
                rows.append(
                    f'  {dxl_id:3d} {JOINT_OF.get(dxl_id, "?"):9s} {pos:7d} '
                    f'{deg:9.2f} {math.radians(deg):9.4f} {moved:+9.2f}'
                    + ('   <-- moving' if live else ''))

            sys.stdout.write(f'\033[{lines}A')          # back to the top row
            for r in rows:
                sys.stdout.write('\033[2K' + r + '\n')  # clear, then redraw
            sys.stdout.flush()
            time.sleep(period)
    except KeyboardInterrupt:
        print()
        print('stopped.  The motors are still in whatever state you left them.')
        if args.torque_off:
            print('Torque is OFF -- the arm is limp.  Support it.')
    finally:
        bus.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
