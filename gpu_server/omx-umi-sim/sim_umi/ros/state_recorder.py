"""Every /joint_states message, kept in a separate process for observation
alignment.

    python sim_umi/ros/state_recorder.py --socket /tmp/omx_state_recorder.sock

The rollout's own loop stops handling callbacks for ~200 ms while it projects a
plan, so it misses the joint states around the next observation's history
frame. A thread in the same process fills that hole but slows the loop
(GIL: the rollout's IK ran 3.5x slower with one), which changes the action
side. So the buffer lives here, in its own process, and the bridge asks it for
the joint state AT an image stamp -- the message with that stamp, else linear
interpolation between the two that bracket it, the collector's rule.

Protocol (unix socket, one JSON line each way):
    {"stamp": t}  ->  {"mode": "exact"|"interp"|"nearest"|"none", "names": [...],
                       "position": [...], "state_stamp_s": .., "skew_s": ..,
                       "bracket_s": [lo, hi] (interp only)}
"""
import collections
import json
import os
import socket
import threading

import click
import rclpy
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState

BUF = collections.deque(maxlen=6000)          # ~13 s at 455 Hz
LOCK = threading.Lock()


def lookup(stamp):
    with LOCK:
        buf = list(BUF)
    if not buf:
        return {"mode": "none"}
    # stamps are increasing; bisect by hand to stay dependency-free
    lo, hi = 0, len(buf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if buf[mid][0] < stamp:
            lo = mid + 1
        else:
            hi = mid
    cands = [i for i in (lo - 1, lo) if 0 <= i < len(buf)]
    i = min(cands, key=lambda k: abs(buf[k][0] - stamp))
    t, names, pos = buf[i]
    if abs(t - stamp) < 1e-6:
        return {"mode": "exact", "names": names, "position": pos, "state_stamp_s": t, "skew_s": 0.0}
    if 0 < lo < len(buf) and buf[lo - 1][0] <= stamp <= buf[lo][0]:
        (t0, n0, p0), (t1, n1, p1) = buf[lo - 1], buf[lo]
        a = (stamp - t0) / (t1 - t0)
        h = dict(zip(n1, p1))
        return {"mode": "interp", "names": n0, "position": [v + (h[n] - v) * a for n, v in zip(n0, p0)],
                "state_stamp_s": stamp, "skew_s": 0.0, "bracket_s": [t0, t1]}
    return {"mode": "nearest", "names": names, "position": pos, "state_stamp_s": t, "skew_s": t - stamp}


def serve(path):
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def handle(conn):
    f = conn.makefile("rwb")
    try:
        for line in f:
            req = json.loads(line)
            f.write((json.dumps(lookup(float(req["stamp"]))) + "\n").encode())
            f.flush()
    except (ConnectionError, OSError):
        pass
    finally:
        conn.close()


@click.command()
@click.option("--socket", "path", default="/tmp/omx_state_recorder.sock")
def main(path):
    rclpy.init()
    node = rclpy.create_node("state_recorder")

    def cb(msg):
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        with LOCK:
            BUF.append((t, list(msg.name), [float(v) for v in msg.position]))
    node.create_subscription(JointState, "/joint_states", cb,
                             QoSProfile(depth=200, history=HistoryPolicy.KEEP_LAST,
                                        reliability=ReliabilityPolicy.RELIABLE))
    threading.Thread(target=serve, args=(path,), daemon=True).start()
    print(f"state recorder on {path}", flush=True)
    rclpy.spin(node)


if __name__ == "__main__":
    main()
