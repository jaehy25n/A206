"""How much does a G0 rollout depend on timing? From logs only.

    python sim_umi/scripts/fov/timing_dependency.py --out <stem>

Runs of the SAME checkpoint (definitive v2_11400, evaluator v1, evaluator v2,
the v2 smoke) on the same placements. Per plan:

  latency        collected_at - obs_t (the plant's clock)
  k_first        the first waypoint actually sent (the executor keeps waypoint k
                 when t_send = t_k - robot_latency > collected_at + exec_latency)
  slack_s        how far that first kept waypoint was from being dropped; a
                 small slack means a few ms more latency moves k_first by one
  frame_gap_s    time between the two observation frames (obs horizon 2); the
                 policy reads motion off this pair, and the camera runs at ~18 Hz
                 against a 10 Hz action grid
  prefix         waypoints sent

Per episode these are set against the outcome, and each pair of runs of the same
episode is aligned plan by plan to find where the two closed loops part (first
plan whose observed tool position differs by > 2 mm) and what the timing looked
like there.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
import click
import numpy as np

D = ROOT / "sim_umi/eval_results/2026-09-27_definitive"
F = ROOT / "sim_umi/eval_results/2026-09-27_fov"
RUNS = {
    "def": {"nominal": D / "nominal_v2_11400.json", "val18": D / "val18_v2_11400.json",
            "agg": (D / "aggregate_definitive_final.json", "v2_11400")},
    "v1": {"nominal": F / "nominal_G0.json", "val18": F / "val18_G0.json",
           "agg": (F / "aggregate_G0_regression.json", "G0")},
    "v2": {"nominal": F / "r2_offpath/nominal_G0.json", "val18": F / "r2_offpath/val18_G0.json",
           "agg": (F / "r2_offpath/aggregate_G0.json", "G0")},
}
EXEC_LAT = 0.01


def stage_at(events, t):
    s = events[0]["stage"] if events else "?"
    for ev in events:
        if ev["t"] <= t + 1e-6:
            s = ev["stage"]
    return s


def plan_rows(ep):
    ev = ep.get("stage_events", [])
    rows = []
    for n, pl in enumerate(ep["trace"]):
        sent = pl.get("sent") or []
        k = sent[0]["k"] if sent else None
        slack = None
        if k is not None:
            t_k = next(x["t_s"] for x in pl["raw_plan"] if x["k"] == k)
            slack = (t_k - pl["robot_latency_s"]) - (pl["collected_at_s"] + EXEC_LAT)
        fr = (pl.get("obs") or {}).get("frames") or []
        gap = (fr[-1]["image_stamp_s"] - fr[0]["image_stamp_s"]) if len(fr) >= 2 else None
        rows.append({"n": n, "stage": stage_at(ev, pl["obs_t_s"]), "t": pl["obs_t_s"] - ep["trace"][0]["obs_t_s"],
                     "latency": pl["inference_s"], "k_first": k, "slack": slack, "frame_gap": gap,
                     "prefix": pl["valid_prefix"], "refused_from": pl["first_unreachable_k"],
                     "ee": pl["ee_at_obs_mm"]})
    return rows


@click.command()
@click.option("--out", required=True)
def main(out):
    data = {}
    for run, spec in RUNS.items():
        agg = json.load(open(spec["agg"][0]))["runs"]
        for mode in ("nominal", "val18"):
            d = json.load(open(spec[mode]))
            A = {e["episode"]: e for e in agg[f"{spec['agg'][1]}_{mode}"]["episodes"]}
            for ep in d["episodes"]:
                o = A[ep["episode"]]
                data[(run, mode, ep["episode"])] = {
                    "rows": plan_rows(ep),
                    "lifted": o["object_lifted"], "bin": o["bin_success"], "abort": o["consecutive_unreachable_abort"],
                    "strict": o["strict_gt_secure_grasp"]}
    rep = {"per_run": {}, "success_vs_failure": {}, "divergence": []}
    L = []
    # 1. distributions per run
    for run in RUNS:
        rows = [r for (rr, _, _), v in data.items() if rr == run for r in v["rows"]]
        k = np.array([r["k_first"] for r in rows if r["k_first"] is not None])
        s = np.array([r["slack"] for r in rows if r["slack"] is not None])
        g = np.array([r["frame_gap"] for r in rows if r["frame_gap"] is not None])
        lat = np.array([r["latency"] for r in rows])
        kc = {int(x): int((k == x).sum()) for x in np.unique(k)}
        rep["per_run"][run] = {"plans": len(rows), "latency_median": float(np.median(lat)),
                               "k_first_counts": kc, "slack_lt_20ms_frac": float((s < 0.02).mean()),
                               "slack_median": float(np.median(s)),
                               "frame_gap_quantiles": [round(float(np.percentile(g, q)), 3) for q in (5, 25, 50, 75, 95)],
                               "frame_gap_off_grid_gt_20ms_frac": float((np.abs(g - 0.1) > 0.02).mean())}
        L.append(f"{run}: plans {len(rows)}, latency median {np.median(lat):.3f}, k_first {kc}, "
                 f"slack median {np.median(s) * 1000:.0f} ms, slack<20 ms {100 * (s < 0.02).mean():.1f}%, "
                 f"frame gap q05/q50/q95 {np.percentile(g, 5):.3f}/{np.median(g):.3f}/{np.percentile(g, 95):.3f} s, "
                 f"|gap-0.1|>20 ms {100 * (np.abs(g - 0.1) > 0.02).mean():.1f}%")
    # 2. success vs failure, pooled over runs, around the grasp
    def ep_stats(v, stages=("APPROACH_OBJECT", "GRASP")):
        rs = [r for r in v["rows"] if r["stage"] in stages and r["k_first"] is not None]
        if not rs:
            return None
        return {"k_first_mean": float(np.mean([r["k_first"] for r in rs])),
                "slack_lt_20ms": float(np.mean([r["slack"] < 0.02 for r in rs])),
                "gap_off_grid": float(np.mean([abs(r["frame_gap"] - 0.1) > 0.02 for r in rs if r["frame_gap"] is not None])),
                "latency_mean": float(np.mean([r["latency"] for r in rs]))}
    for label, key in (("lifted", "lifted"), ("bin", "bin")):
        grp = {True: [], False: []}
        for v in data.values():
            s_ = ep_stats(v)
            if s_:
                grp[bool(v[key])].append(s_)
        rep["success_vs_failure"][label] = {str(k): {m: round(float(np.mean([x[m] for x in g])), 4) for m in g[0]} | {"episodes": len(g)}
                                            for k, g in grp.items() if g}
        L.append(f"APPROACH+GRASP plans, episodes {label}=yes vs no: " + " | ".join(
            f"{'yes' if k == 'True' else 'no'} (n={v['episodes']}): k_first {v['k_first_mean']:.2f}, slack<20ms {100 * v['slack_lt_20ms']:.1f}%, "
            f"gap off-grid {100 * v['gap_off_grid']:.1f}%, latency {v['latency_mean']:.3f}"
            for k, v in rep["success_vs_failure"][label].items()))
    # 3. where two runs of the same episode part
    for mode in ("nominal", "val18"):
        eps = sorted({e for (r, m, e) in data if m == mode})
        for e in eps:
            for a, b in (("def", "v1"), ("def", "v2"), ("v1", "v2")):
                if (a, mode, e) not in data or (b, mode, e) not in data:
                    continue
                A, B = data[(a, mode, e)], data[(b, mode, e)]
                ra, rb = A["rows"], B["rows"]
                n_div = None
                for n in range(min(len(ra), len(rb))):
                    if np.linalg.norm(np.array(ra[n]["ee"]) - np.array(rb[n]["ee"])) > 2.0:
                        n_div = n
                        break
                same = (A["lifted"], A["bin"], A["abort"]) == (B["lifted"], B["bin"], B["abort"])
                rec = {"mode": mode, "episode": e, "pair": f"{a}-{b}", "same_outcome": same,
                       "outcome_a": {"lifted": A["lifted"], "bin": A["bin"], "abort": A["abort"]},
                       "outcome_b": {"lifted": B["lifted"], "bin": B["bin"], "abort": B["abort"]},
                       "diverge_plan": n_div}
                if n_div is not None:
                    w = range(max(0, n_div - 3), n_div + 1)
                    rec["diverge_t_s"] = round(ra[n_div]["t"], 2)
                    rec["diverge_stage"] = ra[n_div]["stage"]
                    rec["before_divergence"] = [{"n": n, "k_first": (ra[n]["k_first"], rb[n]["k_first"]),
                                                 "slack_ms": (None if ra[n]["slack"] is None else round(ra[n]["slack"] * 1000),
                                                              None if rb[n]["slack"] is None else round(rb[n]["slack"] * 1000)),
                                                 "latency_ms": (round(ra[n]["latency"] * 1000), round(rb[n]["latency"] * 1000)),
                                                 "gap_ms": (None if ra[n]["frame_gap"] is None else round(ra[n]["frame_gap"] * 1000),
                                                            None if rb[n]["frame_gap"] is None else round(rb[n]["frame_gap"] * 1000)),
                                                 "ee_diff_mm": round(float(np.linalg.norm(np.array(ra[n]["ee"]) - np.array(rb[n]["ee"]))), 2)}
                                                for n in w]
                rep["divergence"].append(rec)
    div = [r for r in rep["divergence"] if r["diverge_plan"] is not None]
    st = {}
    for r in div:
        st.setdefault(r["diverge_stage"], 0)
        st[r["diverge_stage"]] += 1
    L.append(f"run pairs of the same episode: {len(rep['divergence'])}; parting (>2 mm) found in {len(div)}; "
             f"parting plan index median {np.median([r['diverge_plan'] for r in div]):.0f}, at t median "
             f"{np.median([r['diverge_t_s'] for r in div]):.1f} s; stage at parting {st}")
    # what differs at the first parting plan: timing, or not
    kd = sum(1 for r in div if any(x["k_first"][0] != x["k_first"][1] for x in r["before_divergence"]))
    gd = sum(1 for r in div if any(x["gap_ms"][0] is not None and x["gap_ms"][1] is not None and abs(x["gap_ms"][0] - x["gap_ms"][1]) > 20
                                   for x in r["before_divergence"]))
    L.append(f"in the 4 plans up to the parting: k_first differs in {kd}/{len(div)} pairs; the obs frame pair's "
             f"spacing differs by >20 ms in {gd}/{len(div)} pairs")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1, default=str))
    pathlib.Path(out + ".txt").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
