"""Two DSE runs of the same checkpoint and episodes: the same closed loop, item by item?

    python sim_umi/scripts/dse/dse_repeat_compare.py --a A=<dir> --b B=<dir> --out <stem>

Each <dir> holds nominal_G0.json and nominal_G0_frames/ (ep<i>.npz frames,
ep<i>_cycles.npz simulator state + controller output per cycle, ep<i>_policy.npz exact
policy I/O). Everything is compared on ticks relative to each run's own reset tick (the
runs start at different absolute sim times).

Items, per episode (the user's list): reset q / object state; capture ticks; observation
frame stamps; obs_dt; image-state alignment; policy input (sha1 + max |d| of the low-dim
arrays); policy output (sha1 + max |d| of the raw actions); virtual action age (collect,
goal start, first commanded point, each minus the observation); k*; sent waypoints;
jaw commands; commanded joint sequence (controller output per cycle); actual state
trajectory (simulator q per cycle); skipped controller cycles; outcome.
"""
import json
import pathlib

import click
import numpy as np

DT = 2_000_000


def load(d, mode="nominal", label="G0"):
    d = pathlib.Path(d)
    R = json.load(open(d / f"{mode}_{label}.json"))
    fr = d / f"{mode}_{label}_frames"
    out = {}
    for e in R["episodes"]:
        i = e["episode"]
        reset = e["infra_log"][0]["reset_tick_ns"]
        rel = lambda ns: int(round((ns - reset) / DT))
        rec = {"e": e, "reset": reset, "rel": rel}
        c = fr / f"ep{i:02d}_cycles.npz"
        if c.exists():
            Z = np.load(c)
            rec["cyc_rel"] = np.array([rel(x) for x in Z["ns"]])
            rec["q"], rec["names"] = Z["q"], list(Z["names"])
            rec["cs_rel"] = np.array([rel(x) for x in Z["cs_ns"]])
            rec["cs_out"] = Z["cs_out"]
        p = fr / f"ep{i:02d}_policy.npz"
        if p.exists():
            rec["pol"] = dict(np.load(p))
        out[i] = rec
    return out


def seq_first_diff(a, b):
    n = min(len(a), len(b))
    return next((k for k in range(n) if a[k] != b[k]), None if len(a) == len(b) else n)


def aligned_max_diff(ta, xa, tb, xb):
    """xa/xb rows indexed by relative tick; compared on common ticks."""
    ia = {t: k for k, t in enumerate(ta)}
    common = [t for t in tb if t in ia]
    if not common:
        return None, None, 0
    ib = {t: k for k, t in enumerate(tb)}
    d = np.array([np.nanmax(np.abs(np.asarray(xa[ia[t]], float) - np.asarray(xb[ib[t]], float))) for t in common])
    first = next((common[k] for k in range(len(common)) if d[k] > 0), None)
    return float(np.nanmax(d)), first, len(common)


@click.command()
@click.option("--a", "a_spec", required=True)
@click.option("--b", "b_spec", required=True)
@click.option("--mode", default="nominal", type=click.Choice(["nominal", "val18"]))
@click.option("--label", default="G0")
@click.option("--out", required=True)
def main(a_spec, b_spec, mode, label, out):
    (la, da), (lb, db) = a_spec.split("=", 1), b_spec.split("=", 1)
    A, B = load(da, mode, label), load(db, mode, label)
    rep, L = {}, [f"# DSE repeat comparison: {la} vs {lb}", ""]
    for i in sorted(set(A) & set(B)):
        a, b = A[i], B[i]
        ea, eb = a["e"], b["e"]
        r = {}
        sa, sb = ea["infra_log"][0], eb["infra_log"][0]
        r["reset_state_equal"] = sa["q_after_settle_deg"] == sb["q_after_settle_deg"] and \
            sa["ball_dev_mm"] == sb["ball_dev_mm"] and sa["bin_dev_mm"] == sb["bin_dev_mm"]
        r["capture_ticks_equal"] = ea["dse"]["camera_checks"]["capture_ticks_rel"] == eb["dse"]["camera_checks"]["capture_ticks_rel"]
        ta, tb = ea["trace"], eb["trace"]
        r["plans"] = (len(ta), len(tb))
        obs_ticks = lambda rec, tr: [[rec["rel"](int(round(f["image_stamp_s"] * 1e9))) for f in pl["obs"]["frames"]] for pl in tr]
        r["obs_frame_ticks_first_diff_plan"] = seq_first_diff(obs_ticks(a, ta), obs_ticks(b, tb))
        r["obs_dt_first_diff_plan"] = seq_first_diff([pl["obs"]["obs_dt_s"] for pl in ta], [pl["obs"]["obs_dt_s"] for pl in tb])
        r["alignment_all_rgb_snapshot"] = all(f["state_source"] == "rgb_snapshot" and f["image_state_skew_s"] == 0.0
                                              for tr in (ta, tb) for pl in tr for f in pl["obs"]["frames"])
        r["policy_input_first_diff_plan"] = seq_first_diff([pl["obs"].get("policy_input_sha1") for pl in ta],
                                                           [pl["obs"].get("policy_input_sha1") for pl in tb])
        r["policy_output_first_diff_plan"] = seq_first_diff([pl["obs"].get("policy_output_sha1") for pl in ta],
                                                            [pl["obs"].get("policy_output_sha1") for pl in tb])
        if "pol" in a and "pol" in b:
            n = min(len(a["pol"]["action"]), len(b["pol"]["action"]))
            r["policy_output_max_abs_diff"] = float(np.max(np.abs(a["pol"]["action"][:n] - b["pol"]["action"][:n]))) if n else None
            r["policy_lowdim_max_abs_diff"] = max(float(np.max(np.abs(a["pol"][k][:n] - b["pol"][k][:n])))
                                                  for k in a["pol"] if k.startswith("lowdim_")) if n else None
            r["policy_rgb_first_diff_plan"] = seq_first_diff(list(a["pol"]["rgb_sha1"]), list(b["pol"]["rgb_sha1"]))
        age = lambda tr: [(pl.get("collected_at_s", 0) - pl["obs_t_s"], pl.get("goal_start_tick_s", 0) - pl["obs_t_s"] if pl.get("goal_start_tick_s") else None,
                           pl.get("first_point_commanded_s", 0) - pl["obs_t_s"] if pl.get("first_point_commanded_s") else None) for pl in tr]
        rnd = lambda xs: [tuple(None if v is None else round(v, 5) for v in x) for x in xs]
        r["action_age_first_diff_plan"] = seq_first_diff(rnd(age(ta)), rnd(age(tb)))
        r["action_age_values"] = sorted(set(rnd(age(ta))), key=str)[:4]
        r["kstar_first_diff_plan"] = seq_first_diff([pl["sent"][0]["k"] if pl.get("sent") else None for pl in ta],
                                                    [pl["sent"][0]["k"] if pl.get("sent") else None for pl in tb])
        r["sent_waypoints_first_diff_plan"] = seq_first_diff([[x["q_deg"] for x in pl.get("sent", [])] for pl in ta],
                                                             [[x["q_deg"] for x in pl.get("sent", [])] for pl in tb])
        jaw = lambda rec, e: [(rec["rel"](int(round(j["t_due_s"] * 1e9))), j["width_mm"], j["sent"]) for j in e["jaw_log"]]
        r["jaw_first_diff"] = seq_first_diff(jaw(a, ea), jaw(b, eb))
        if "q" in a and "q" in b:
            r["commanded_max_abs_diff"], r["commanded_first_diff_tick"], r["commanded_ticks_compared"] = aligned_max_diff(
                a["cs_rel"], a["cs_out"], b["cs_rel"], b["cs_out"])
            r["state_max_abs_diff"], r["state_first_diff_tick"], r["state_ticks_compared"] = aligned_max_diff(
                a["cyc_rel"], a["q"], b["cyc_rel"], b["q"])
        # the first command: plan 0's goal (send ticks, time_from_start ticks, target joints)
        g = lambda pl: (pl.get("goal_send_ticks"), pl.get("goal_takeover_tick"), [x["q_deg"] for x in pl.get("sent", [])])
        r["first_command_equal"] = g(ta[0]) == g(tb[0]) if ta and tb else None
        # the tool trajectory: ee_track rows on ticks relative to the reset
        ee = lambda rec, e: {rec["rel"](int(round(row[0] * 1e9))): row[1:4] for row in e["ee_track"]}
        A_ee, B_ee = ee(a, ea), ee(b, eb)
        common = sorted(set(A_ee) & set(B_ee))
        dee = [(t, max(abs(x - y) for x, y in zip(A_ee[t], B_ee[t]))) for t in common]
        r["ee_first_diff_tick"] = next((t for t, v in dee if v > 0), None)
        r["ee_max_abs_diff_mm"] = max((v for _, v in dee), default=None)
        r["ee_ticks_compared"] = len(common)
        r["skips_rel"] = (ea["dse"]["skips_rel_ticks"], eb["dse"]["skips_rel_ticks"])
        out_ = lambda e: {k: e[k] for k in ("success", "grasped", "stopped_because", "steps", "furthest_stage")}
        r["outcome"] = (out_(ea), out_(eb))
        r["outcome_equal"] = out_(ea) == out_(eb) and ea.get("ball_final_mm") == eb.get("ball_final_mm")
        r["gates"] = (ea["dse"]["gates"]["all"], eb["dse"]["gates"]["all"])
        rep[i] = r
        L.append(f"## episode {i}")
        for k, v in r.items():
            L.append(f"- {k}: {v}")
        L.append("")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1, default=str))
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
