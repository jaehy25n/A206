"""Does the plant's state stream itself stop while a rollout is inferring,
or only the rollout's own reception of it?

    source sim_umi/ros/env_overlay.sh
    python sim_umi/scripts/dse/stream_gaps.py --out <file.json> --seconds 120

A passive process of its own (nothing published, nothing called) records every
/joint_states, /clock and /wrist_camera/image_raw message: sim stamp and wall
arrival. Run beside a rollout whose log carries collect_start_wall /
collect_end_wall per plan; the gaps in stamp sequence and in arrival are then
set against the rollout's blocked intervals offline.
"""
import json
import threading
import time

import click
import rclpy
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, JointState


def sec(s):
    return s.sec + s.nanosec * 1e-9


@click.command()
@click.option("--out", required=True)
@click.option("--seconds", default=120.0)
def main(out, seconds):
    rclpy.init()
    n = rclpy.create_node("stream_gaps")
    rec = {"joint_states": [], "clock": [], "image": []}
    lock = threading.Lock()
    q = QoSProfile(depth=5000, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)

    def add(k, t):
        with lock:
            rec[k].append((t, time.time()))
    n.create_subscription(JointState, "/joint_states", lambda m: add("joint_states", sec(m.header.stamp)), q)
    n.create_subscription(Clock, "/clock", lambda m: add("clock", sec(m.clock)), q)
    n.create_subscription(Image, "/wrist_camera/image_raw", lambda m: add("image", sec(m.header.stamp)), q)
    t_end = time.time() + seconds
    while time.time() < t_end:
        rclpy.spin_once(n, timeout_sec=0.05)
    with lock:
        summ = {}
        for k, v in rec.items():
            st = [a for a, _ in v]
            gaps = sorted((b - a for a, b in zip(st, st[1:])), reverse=True)
            summ[k] = {"n": len(v), "max_stamp_gap_s": gaps[0] if gaps else None, "top_gaps_s": gaps[:5]}
        json.dump({"summary": summ, "records": rec}, open(out, "w"))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
