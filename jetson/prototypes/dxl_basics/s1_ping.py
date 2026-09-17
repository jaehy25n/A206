#!/usr/bin/env python3
"""Step 1 -- say hello.  Nothing else.

Sends a 10-byte ping to each id and prints both directions in hex, so you can
see the actual conversation rather than a library's opinion of it.

Reads nothing, writes nothing, moves nothing.  Torque state is untouched: if
the arm was holding, it keeps holding; if it was limp, it stays limp.

    python3 s1_ping.py --port /dev/ttyACM0

Nothing may hold the port at the same time -- one wire, one talker.  Stop the
ros2_control stack first.
"""

import argparse
import sys

import dxl_raw as D

# The follower's six servos.  Which id drives which joint is not written down
# anywhere in the vendor's repo -- it is purely the order they are chained in,
# and this is the assumption we are about to start testing.
JOINT_OF = {11: 'joint1', 12: 'joint2', 13: 'joint3',
            14: 'joint4', 15: 'joint5', 16: 'gripper'}

# Model number lives at EEPROM address 0 and comes back in the ping reply.
MODELS = {1060: 'XL430-W250', 1020: 'XM430-W350', 1030: 'XM430-W210',
          1190: 'XL330-M077', 1200: 'XL330-M288', 1090: 'XL320'}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--baud', type=int, default=1000000)
    ap.add_argument('--ids', default='11,12,13,14,15,16',
                    help='comma separated, or "scan" to try every id 0..252')
    args = ap.parse_args()

    ids = (range(253) if args.ids == 'scan'
           else [int(v) for v in args.ids.split(',')])

    try:
        bus = D.Bus(args.port, args.baud)
    except PermissionError:
        print(f'no permission for {args.port}.')
        print('  the port is usually root:dialout, so either')
        print(f'    sudo python3 {sys.argv[0]} --port {args.port}   (one-off)')
        print('  or join the group once and for all:')
        print('    sudo usermod -aG dialout $USER   # then log out, log in')
        return 1
    except Exception as exc:
        print(f'cannot open {args.port}: {exc}')
        print('  - is something still holding the port?  the container')
        print('    shares /dev with the host, so ros2_control INSIDE it')
        print('    locks us out here too')
        print('  - does the device exist?   ls -l /dev/ttyACM* /dev/ttyUSB*')
        return 1

    print(f'{args.port} @ {args.baud} baud, via {bus.backend}')
    print()
    found = []
    for dxl_id in ids:
        err, data, sent, got = bus.ping(dxl_id)
        name = JOINT_OF.get(dxl_id, '?')

        if args.ids == 'scan' and err is None:
            continue                     # scanning: only report what answers

        print(f'id {dxl_id:3d}  {name}')
        print(f'  -> {D.hexs(sent)}')
        print(f'  <- {D.hexs(got)}')

        if err is None:
            print(f'     no usable reply: {data.decode()}')
        elif err & 0x7F:
            print(f"     replied, but ERR={err}: "
                  f"{D.ERRORS.get(err & 0x7F, chr(63))}")
        else:
            model = D.to_int(data[0:2])
            print(f'     model {model} ({MODELS.get(model, "unknown")})  '
                  f'firmware {data[2]}')
            if err & 0x80:
                print("     hardware alert bit is set -- s2_read.py decodes address 70")
            found.append(dxl_id)
        print()

    bus.close()

    print(f'{len(found)} of {len(list(ids))} answered: {found}'
          if args.ids != 'scan' else f'found: {found}')
    if not found:
        print('\nnothing answered.  in order of likelihood:')
        print('  1. something else holds the port (ros2_control, another shell)')
        print('  2. wrong baud -- try --baud 57600, 115200, 2000000, 3000000')
        print('  3. wrong device -- try the other /dev/ttyACM* or /dev/ttyUSB*')
        print('  4. the arm is not powered (USB alone does not power the servos)')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
