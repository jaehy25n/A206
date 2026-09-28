#!/usr/bin/env python3
"""Scan a DYNAMIXEL bus (Protocol 2.0): which IDs answer at which baud rate.

    ros2 run omx_driver dxl_scan.py                      # IDs 0-252 at the common baud rates (~1 min)
    ros2 run omx_driver dxl_scan.py --quick              # IDs 11-16 at 1 Mbps only
    ros2 run omx_driver dxl_scan.py --port /dev/ttyACM1 --bauds 1000000,57600

Use it when dxl_driver_node reports "ping failed": it tells you whether a motor
is silent everywhere (cable / power) or just lives at another ID or baud rate.
"""

import argparse
import sys

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

MODELS = {
    1060: 'XL430-W250', 1190: 'XL330-M077', 1200: 'XL330-M288',
    1020: 'XM430-W350', 1030: 'XM430-W210', 1120: 'XM540-W150', 1130: 'XM540-W270',
    1080: 'XC430-W150', 1070: 'XC430-W240', 1220: 'XC330-M181', 1230: 'XC330-M288',
}
EXPECTED = {11: 'joint1', 12: 'joint2', 13: 'joint3', 14: 'joint4', 15: 'joint5', 16: 'gripper'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM0')
    ap.add_argument('--bauds', default='1000000,57600,115200,2000000,3000000,4000000')
    ap.add_argument('--ids', default='0-252', help='range, e.g. 11-16')
    ap.add_argument('--quick', action='store_true', help='IDs 11-16 at 1 Mbps only')
    args = ap.parse_args()

    if args.quick:
        ids, bauds = range(11, 17), [1000000]
    else:
        lo, hi = (int(x) for x in args.ids.split('-'))
        ids, bauds = range(lo, hi + 1), [int(b) for b in args.bauds.split(',')]

    port = PortHandler(args.port)
    if not port.openPort():
        print(f'cannot open {args.port}', file=sys.stderr)
        return 1
    ph = PacketHandler(2.0)

    found = {}
    for baud in bauds:
        if not port.setBaudRate(baud):
            print(f'baud {baud:>8}: not supported by this port')
            continue
        hits = []
        for i in ids:
            model, rc, _err = ph.ping(port, i)
            if rc == COMM_SUCCESS:
                hits.append((i, model))
                found.setdefault(i, []).append(baud)
        if hits:
            print(f'baud {baud:>8}: ' + ', '.join(
                f'id {i} ({MODELS.get(m, "model " + str(m))})' for i, m in hits))
        else:
            print(f'baud {baud:>8}: no response')
    port.closePort()

    print()
    for i, name in EXPECTED.items():
        state = f'ok at {found[i]}' if i in found else 'MISSING'
        print(f'  id {i} {name:8s} {state}')
    extra = sorted(set(found) - set(EXPECTED))
    if extra:
        print(f'  unexpected ids: {extra}')
    missing = [i for i in EXPECTED if i not in found]
    if missing and not found:
        print('\nnothing answers at all -> port / power / cable to the first motor')
    elif missing:
        print(f'\nids {missing} silent at every baud -> check the cable and power of that segment '
              f'(XL330 joints need the 5 V rail); the others answer, so the bus itself works')
    return 0 if not missing else 2


if __name__ == '__main__':
    sys.exit(main())
