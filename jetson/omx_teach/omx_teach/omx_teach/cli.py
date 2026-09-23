"""Command line front-end for teach_node.

    ros2 run omx_teach teach record cup1            # torque OFF, hold the arm, then move it
    ros2 run omx_teach teach record cup1 --keep-torque   # log whatever is moving the arm now
    ros2 run omx_teach teach stop
    ros2 run omx_teach teach play cup1 --speed 0.5 --approach 4
    ros2 run omx_teach teach play                   # newest recording
    ros2 run omx_teach teach abort
    ros2 run omx_teach teach list
"""

import argparse
import sys

import rclpy
from std_srvs.srv import Trigger

from omx_teach_msgs.srv import PlayRecording, StartRecording

from . import recording as rec


def _call(node, srv_type, name, req, timeout=3.0):
    client = node.create_client(srv_type, name)
    if not client.wait_for_service(timeout_sec=timeout):
        print(f'service {name} not available (is teach_node running?)', file=sys.stderr)
        return None
    fut = client.call_async(req)
    rclpy.spin_until_future_complete(node, fut, timeout_sec=timeout)
    if not fut.done():
        print(f'service {name} timed out', file=sys.stderr)
        return None
    return fut.result()


def main(argv=None):
    ap = argparse.ArgumentParser(prog='teach', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('record', help='start recording /joint_states')
    r.add_argument('name', nargs='?', default='')
    r.add_argument('--keep-torque', action='store_true',
                   help='do not switch to IDLE (record while something else drives the arm)')
    sub.add_parser('stop', help='stop recording and save')
    p = sub.add_parser('play', help='replay a recording')
    p.add_argument('name', nargs='?', default='')
    p.add_argument('--speed', type=float, default=1.0)
    p.add_argument('--approach', type=float, default=0.0, help='seconds to reach the first pose')
    sub.add_parser('abort', help='stop playback (mode STOP)')
    ls = sub.add_parser('list', help='list recordings')
    ls.add_argument('--dir', default='~/omx_recordings')
    args = ap.parse_args(argv)

    if args.cmd == 'list':
        d = rec.recordings_dir(args.dir)
        rows = rec.list_recordings(d)
        if not rows:
            print(f'(no recordings in {d})')
        for name, n, dur in rows:
            print(f'{name:30s} {n:6d} samples {dur:7.2f} s')
        return 0

    rclpy.init()
    node = rclpy.create_node('teach_cli')
    try:
        if args.cmd == 'record':
            req = StartRecording.Request()
            req.name = args.name
            req.torque_off = not args.keep_torque
            res = _call(node, StartRecording, '/teach/record_start', req)
        elif args.cmd == 'stop':
            res = _call(node, Trigger, '/teach/record_stop', Trigger.Request())
        elif args.cmd == 'play':
            req = PlayRecording.Request()
            req.name = args.name
            req.speed = float(args.speed)
            req.approach_duration = float(args.approach)
            res = _call(node, PlayRecording, '/teach/play', req)
        else:
            res = _call(node, Trigger, '/teach/abort', Trigger.Request())
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if res is None:
        return 1
    print(('ok: ' if res.success else 'FAILED: ') + res.message)
    return 0 if res.success else 1


if __name__ == '__main__':
    sys.exit(main())
