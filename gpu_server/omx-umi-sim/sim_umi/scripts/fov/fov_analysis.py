"""FOV step analysis on top of aggregate.py: FOV diagnostics, first-close
traces, and paired episode-level comparisons between geometries.

    python sim_umi/scripts/fov/fov_analysis.py --agg <aggregate.json> \
        --runs "G0_nominal=<rollout.json>,G1_nominal=...,..." --out <stem>

- FOV: every plan carries fov_diag metrics (evaluation-only ground truth).
  Summarised per run and per stage for the run's own geometry, and for the
  other two geometries on the same frames (what they would have shown).
- First close: the closing onset of the first real GRASP attempt, defined as
  in aggregate.py; depth / vertical / pitch / true jaw / EE speed over +-2 s,
  resampled at 10 Hz.
- Paired: the same episodes under each geometry. Per metric, the episode-level
  transitions (fail -> success, success -> fail) and the exact McNemar p on
  the discordant pairs. Raw counts and transitions are the evidence; p is a
  reference.
"""
import json
import math
import pathlib
import sys
from itertools import combinations

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(SIM / "src"), str(SIM / "scripts"), str(SIM / "scripts" / "definitive")]
import click
import numpy as np

from aggregate import Kin, load

METRICS = ["entered_corridor", "grasp_stage_reached", "lift_stage_reached", "object_lifted",
           "strict_gt_secure_grasp", "bin_success", "consecutive_unreachable_abort"]


def mcnemar_exact(b, c):
    """Two-sided exact McNemar on b (A only) and c (B only) discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def stage_at(events, t):
    s = events[0]["stage"] if events else "?"
    for ev in events:
        if ev["t"] <= t + 1e-6:
            s = ev["stage"]
    return s


def fov_summary(ep_list):
    rows = {}
    for e in ep_list:
        ev = e.get("stage_events", [])
        for pl in e["trace"]:
            f = (pl.get("obs") or {}).get("fov")
            if not f:
                continue
            st = stage_at(ev, pl["obs_t_s"])
            for g in [k for k in f if k != "active"]:
                m = f[g]
                r = rows.setdefault((g, st), {"n": 0, "vis": 0, "both": 0, "area": [], "edge": [], "patch": []})
                r["n"] += 1
                r["vis"] += int(m["visible"])
                r["both"] += int(m["object_and_gripper_visible"])
                if m["area_px"]:
                    r["area"].append(m["area_px"])
                    r["patch"].append(m["patches_touched"])
                    r["edge"].append(min(m["edge_dist_px"].values()))
    out = {}
    for (g, st), r in rows.items():
        out.setdefault(g, {})[st] = {
            "plans": r["n"], "object_visible": round(r["vis"] / r["n"], 3),
            "object_and_gripper_visible": round(r["both"] / r["n"], 3),
            "area_px_median": float(np.median(r["area"])) if r["area"] else None,
            "min_edge_dist_px_median": float(np.median(r["edge"])) if r["edge"] else None,
            "min_edge_dist_px_p10": float(np.percentile(r["edge"], 10)) if r["edge"] else None,
            "patches_touched_median": float(np.median(r["patch"])) if r["patch"] else None}
    return out


def close_traces(ep_list, cols, kin):
    ci = {c: i for i, c in enumerate(cols)}
    out = []
    for e in ep_list:
        ev = [x for x in e.get("stage_events", []) if x["stage"] == "GRASP"]
        if not ev or "jaw_gt_mm" not in ci:
            out.append({"episode": e["episode"], "onset": None})
            continue
        tk = np.array([[np.nan if v is None else v for v in r] for r in e["ee_track"]], float)
        T = tk[:, ci["stamp_s"]]
        J = tk[:, ci["jaw_gt_mm"]]
        kg = int(np.argmin(np.abs(T - ev[0]["t"])))
        open_w = float(np.nanmax(J[:max(kg, 1)]))
        k0 = kg
        while k0 > 0 and J[k0] < open_w - 1.0:
            k0 -= 1
        t0 = T[k0]
        grid = t0 + np.arange(-2.0, 2.0001, 0.1)
        Q = np.radians(tk[:, ci["j1_deg"]:ci["j1_deg"] + 5])
        B = tk[:, ci["ball_x_mm"]:ci["ball_x_mm"] + 3]
        EE = tk[:, ci["x_mm"]:ci["x_mm"] + 3]
        rec = {"episode": e["episode"], "onset_s": round(float(t0 - T[0]), 3), "t_rel_s": np.round(grid - t0, 2).tolist()}
        idx = [int(np.argmin(np.abs(T - g))) if T[0] <= g <= T[-1] else None for g in grid]
        dep, ver, lat, pit, jaw, spd = [], [], [], [], [], []
        for n, i in enumerate(idx):
            if i is None or np.isnan(B[i]).any():
                for L in (dep, ver, lat, pit, jaw, spd):
                    L.append(None)
                continue
            p_m, R = kin.fk(Q[i])
            off = R.T @ (B[i] / 1000.0 - p_m) * 1000.0
            lat.append(round(float(off[0]), 2)); dep.append(round(float(off[1]), 2)); ver.append(round(float(off[2]), 2))
            pit.append(round(float(tk[i, ci["pitch_deg"]]), 2)); jaw.append(round(float(J[i]), 2))
            j = idx[n - 1] if n > 0 else None
            spd.append(None if j is None else round(float(np.linalg.norm(EE[i] - EE[j])), 3))   # mm per 0.1 s tick
        rec.update({"lateral": lat, "depth": dep, "vertical": ver, "pitch": pit, "jaw_mm": jaw, "ee_mm_per_tick": spd})
        out.append(rec)
    return out


def paired(agg, a, b):
    A = {e["episode"]: e for e in agg["runs"][a]["episodes"]}
    B = {e["episode"]: e for e in agg["runs"][b]["episodes"]}
    common = sorted(set(A) & set(B))
    res = {"episodes": common, "metrics": {}}
    for m in METRICS:
        both = sum(1 for k in common if A[k][m] and B[k][m])
        a_only = [k for k in common if A[k][m] and not B[k][m]]
        b_only = [k for k in common if B[k][m] and not A[k][m]]
        res["metrics"][m] = {f"{a}": sum(A[k][m] for k in common), f"{b}": sum(B[k][m] for k in common),
                             "both": both, f"{a}_only": a_only, f"{b}_only": b_only,
                             "mcnemar_exact_p": round(mcnemar_exact(len(a_only), len(b_only)), 4)}
    return res


@click.command()
@click.option("--agg", required=True)
@click.option("--runs", required=True, help="label=rollout.json,...  (labels as in the aggregate)")
@click.option("--out", required=True)
def main(agg, runs, out):
    A = json.load(open(agg))
    kin = Kin()
    rep = {"fov": {}, "first_close": {}, "paired": {}}
    for spec in runs.split(","):
        label, f = spec.split("=", 1)
        d = load(f)
        rep["fov"][label] = fov_summary(d["episodes"])
        rep["first_close"][label] = close_traces(d["episodes"], d["ee_track_columns"], kin)
    for mode in ("nominal", "val18"):
        labs = [k for k in A["runs"] if k.endswith("_" + mode)]
        for a, b in combinations(labs, 2):
            rep["paired"][f"{a}__vs__{b}"] = paired(A, a, b)
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1))
    lines = ["# FOV analysis", ""]
    for k, v in rep["paired"].items():
        lines.append(f"## {k} (n={len(v['episodes'])})")
        lines.append("| metric | A | B | both | A only (episodes) | B only (episodes) | McNemar exact p |")
        lines.append("|---|---|---|---|---|---|---|")
        a, b = k.split("__vs__")
        for m, r in v["metrics"].items():
            lines.append(f"| {m} | {r[a]} | {r[b]} | {r['both']} | {r[a + '_only']} | {r[b + '_only']} | {r['mcnemar_exact_p']} |")
        lines.append("")
    pathlib.Path(out + ".md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
