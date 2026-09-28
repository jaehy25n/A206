"""Camera capture ticks under paused stepping: expected vs actual, and repeat vs repeat.

    source sim_umi/ros/env_overlay.sh
    python sim_umi/scripts/dse/camera_step_test.py --out <dir>

--trigger node_clock (the original plugin): the capture is decided inside the controller
cycle on the plugin's node clock; EXPECTED = the first controller-cycle tick c with
c - last capture >= 50,000,000 ns.
--trigger sim_state (the patched plugin, DSE config): the capture is taken on the physics
thread as every 25th step since the last world reset begins; EXPECTED = reset + 25k. The
joint snapshot of the same data must carry the frame's stamp, and its joint positions must
equal the controller cycle's state of that tick (where the cycle exists) bit for bit.
The ACTUAL tick is the one whose /clock value matches the frame's stamp.

Per run (reset to HOME, zero velocity, hold goal installed; 250 ticks stepped 1, 5 or 25
per call; each mode twice): the expected and actual capture ticks relative to the reset.
Judged, and never softened by "the frame arrived eventually":
  (a) within a run: actual == expected for every capture;
  (b) across the two repeats of a mode: identical actual capture ticks relative to reset.
With one step per call the audit waits, at every expected tick, for that frame before
stepping on (the DSE's sensor-ready barrier); a frame that comes on another tick is a
miss, not a recovery.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import click
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

import step_audit as sa

DT_NS, FRAME_NS = 2_000_000, 50_000_000


def ns(stamp):
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def clock_tick_of(clock, f):
    c = min(clock, key=lambda x: abs(x - f)) if clock else None
    return c if c is not None and abs(c - f) < 100_000 else None


@click.command()
@click.option("--out", required=True)
@click.option("--ticks", default=250)
@click.option("--trigger", type=click.Choice(["node_clock", "sim_state"]), required=True)
def main(out, ticks, trigger):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=False)
    a = sa.Audit()
    frames, snaps = [], {}
    q = QoSProfile(depth=5000, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)
    a.n.create_subscription(Image, "/wrist_camera/image_raw", lambda m: a._add(frames, ns(m.header.stamp)), q)
    from sensor_msgs.msg import JointState as _JS

    def _snap(m):
        with a.lock:
            snaps[ns(m.header.stamp)] = dict(zip(m.name, m.position))
    a.n.create_subscription(_JS, "/wrist_camera/joint_snapshot", _snap, q)
    time.sleep(1.0)
    q0 = list(sa.HOME_Q)
    grip = {g: float(a.last_js[g]) for g in sa.GRIP if g in a.last_js}
    res = {"runs": []}
    assert a.pause(True)
    try:
        for mode in (1, 1, 5, 5, 25, 25):
            a.reset_to(q0, grip)
            time.sleep(0.3)
            with a.lock:
                R = int(round(a.clock[-1][0] * 1e9))
                clk_before = sorted({int(round(c * 1e9)) for c, _ in a.clock})
                prior = [f for f in frames if f <= R + 100_000]
            a.t_sim = R * 1e-9
            last0 = clock_tick_of(clk_before, max(prior)) if prior else None
            walls, done, barrier_misses, calls = [], 0, [], []
            exp_last = last0
            while done < ticks:
                n = min(mode, ticks - done)
                w0 = time.time()
                a.step(n, 0.0)
                walls.append((time.time() - w0) / n)
                calls.append(dict(a.last_timing))
                done += n
                if mode == 1 and trigger == "sim_state":
                    with a.lock:
                        cks = sorted({int(round(c * 1e9)) for c, _ in a.clock if c * 1e9 >= R - 1e5})
                    i_now = len(cks) - 1
                    if i_now >= 1 and (i_now - 1) % 25 == 0:
                        want = cks[i_now - 1]
                        t0 = time.time()
                        hit = False
                        while time.time() - t0 < 2.0:
                            with a.lock:
                                hit = any(abs(f - want) < 100_000 for f in frames)
                            if hit:
                                break
                            time.sleep(0.001)
                        if not hit:
                            barrier_misses.append(i_now - 1)
                elif mode == 1 and exp_last is not None:
                    # the DSE's barrier: at an expected capture tick, hold for that frame
                    with a.lock:
                        c = int(round(a.clock[-1][0] * 1e9))
                        cyc = any(abs(x["t"] * 1e9 - c) < 100_000 for x in a.act[-5:])
                    if cyc and c - exp_last >= FRAME_NS:
                        t0 = time.time()
                        hit = False
                        while time.time() - t0 < 2.0:
                            with a.lock:
                                hit = any(abs(f - c) < 100_000 for f in frames)
                            if hit:
                                break
                            time.sleep(0.001)
                        if not hit:
                            barrier_misses.append(round((c - R) / DT_NS, 3))
                        exp_last = c          # the rule's next reference, whatever happened
            time.sleep(1.0)                   # late frames from the render thread
            with a.lock:
                clk = sorted({int(round(c * 1e9)) for c, _ in a.clock if c * 1e9 > R - 1e5})
                cyc = sorted({int(round(x["t"] * 1e9)) for x in a.act if x["t"] * 1e9 > R + 1e5})
                fr = sorted({f for f in frames if (R - 100_000 if trigger == "sim_state" else R + 100_000) < f})
                snap_copy = dict(snaps)
                act_by_ns = {int(round(x["t"] * 1e9)): dict(zip(x["names"], x["q"])) for x in a.act}
            end = clk[-1]
            fr = [f for f in fr if f <= end + 100_000]
            # expected captures
            expected, last = [], last0
            cyc_set = set(cyc)
            if trigger == "sim_state":
                ticks_from_R = [c for c in clk if c >= R - 100_000]
                # tick m is captured as step m -> m+1 begins: only ticks with a following step
                expected = [ticks_from_R[m] for m in range(0, len(ticks_from_R) - 1, 25)]
            else:
                for c in clk:
                    if c <= R or last is None:
                        continue
                    if c in cyc_set and c - last >= FRAME_NS:
                        expected.append(c)
                        last = c
            actual = [clock_tick_of(clk, f) for f in fr]
            rel = lambda x: None if x is None else int(round((x - R) / DT_NS))
            e_rel, a_rel = [rel(x) for x in expected], [rel(x) for x in actual]
            snap_same_stamp = [f in snap_copy for f in fr]
            snap_eq_cycle, snap_diff = [], []
            for f in fr:
                c = clock_tick_of(clk, f)
                if f in snap_copy and c in act_by_ns:
                    sj, cj = snap_copy[f], act_by_ns[c]
                    same = all(sj[k] == cj[k] for k in cj if k in sj)
                    snap_eq_cycle.append(same)
                    if not same:
                        snap_diff.append({"rel_tick": rel(c), "max_abs_dq": max(abs(sj[k] - cj[k]) for k in cj if k in sj)})
            run = {"trigger": trigger, "steps_per_call": mode, "reset_ns": R, "prior_capture_rel": rel(last0),
                   "snapshot_with_same_stamp": f"{sum(snap_same_stamp)}/{len(fr)}",
                   "snapshot_q_equals_cycle_q": f"{sum(snap_eq_cycle)}/{len(snap_eq_cycle)}",
                   "snapshot_vs_cycle_differences": snap_diff,
                   "calls": calls,
                   "call_wall_ms": {k: {"median": round(sorted(c[k] for c in calls)[len(calls) // 2], 3),
                                        "p90": round(sorted(c[k] for c in calls)[int(0.9 * (len(calls) - 1))], 3),
                                        "max": round(max(c[k] for c in calls), 3)}
                                    for k in ("service_ms", "clock_wait_ms", "cycle_msgs_wait_ms", "total_ms")},
                   "expected_rel": e_rel, "actual_rel": a_rel,
                   "actual_equals_expected": e_rel == a_rel,
                   "mismatches": [x for x in sorted(set(e_rel) ^ set(a_rel))],
                   "barrier_misses_rel": barrier_misses,
                   "short_ticks_rel": [rel(clk[k + 1]) for k in range(len(clk) - 1) if clk[k + 1] - clk[k] < DT_NS],
                   "wall_ms_per_tick_median": round(1000 * sorted(walls)[len(walls) // 2], 2)}
            res["runs"].append(run)
            print(f"steps/call {mode:2d}: snapshot same stamp {run['snapshot_with_same_stamp']}  snapshot q == cycle q "
                  f"{run['snapshot_q_equals_cycle_q']} (differs at {[d['rel_tick'] for d in snap_diff]})  per call: "
                  + "  ".join(f"{k.replace('_ms','')} {v['median']}/{v['p90']}/{v['max']} ms" for k, v in run["call_wall_ms"].items())
                  + f"  prior capture at {run['prior_capture_rel']}  expected {e_rel}  actual {a_rel}  "
                  f"equal {run['actual_equals_expected']}  barrier misses {barrier_misses}  short ticks "
                  f"{run['short_ticks_rel']}  wall/tick {run['wall_ms_per_tick_median']} ms", flush=True)
        # repeat vs repeat
        rr = res["runs"]
        res["repeats_identical"] = {str(m): rr[2 * j]["actual_rel"] == rr[2 * j + 1]["actual_rel"]
                                    for j, m in enumerate((1, 5, 25))}
        print("repeats identical (actual capture ticks relative to reset):", res["repeats_identical"], flush=True)
    finally:
        a.pause(False)
        (out / "camera_step_test.json").write_text(json.dumps(res, indent=1))
    a.goal([(0.5, q0)])
    print(f"-> {out / 'camera_step_test.json'}; plant resumed", flush=True)
    a.ex.shutdown()
    a.n.destroy_node()
    sa.rclpy.shutdown()


if __name__ == "__main__":
    main()
