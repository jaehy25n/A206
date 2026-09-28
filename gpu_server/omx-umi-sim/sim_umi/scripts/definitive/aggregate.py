"""Every metric the definitive protocol asks for, from finished rollout logs.

    python sim_umi/scripts/definitive/aggregate.py --runs "label=file,..." --out summary.json

Evaluation-only ground truth (the ball's true pose, the simulator's jaw) is used
here and nowhere upstream. Metrics that are different things are kept apart on
purpose: the GRASP stage (jaw below 45 mm with the ball not lifted), the LIFT
stage, the runtime `grasped` flag, the ball actually leaving the table, and a
strict ground-truth secure grasp are five separate columns and are never folded
into one "grasp success".

Close geometry is taken only where a rollout actually entered GRASP, at the
onset of that attempt's closing -- the last moment before GRASP entry that the
true jaw was still within 1 mm of open -- the same definition the expert
corridor was measured with. A rollout with no GRASP entry has no close
geometry: N/A, never a number read off some threshold crossing.

Feasibility: the runtime has exactly one gate, the in-plane position residual
of solve_ik_best above 2 mm. Each rejected waypoint's target is re-solved here
with the same deterministic IK on the same kinematics file, the reproduced
residual is checked against the logged one, and the rejection is decomposed
into what the solver ran into: a joint pinned at its limit, a pitch it had to
give up, or neither.
"""
import gzip
import json
import math
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "scripts"))

import click
import numpy as np

TRAP = (25.0, 32.0)
HOLD_RISE_MM = 20.0
SECURE_STEADY_MM = 4.0
SECURE_MOVE_MM = 30.0
SECURE_MIN_S = 0.5
EXPERT = {"lateral": (-0.62, -2.26, 2.20), "depth": (-22.62, -23.66, -15.86),
          "vertical": (4.30, 0.51, 8.19), "pitch": (12.57, 7.91, 17.40),
          "speed": 0.15}
STAGES = ["SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP", "LIFT", "SEARCH_BIN",
          "TRANSPORT", "PLACE", "AFTER_RELEASE"]


def load(p):
    p = pathlib.Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return json.load(f)


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


def geodesic_deg(Ra, Rb):
    R = np.asarray(Ra).reshape(3, 3).T @ np.asarray(Rb).reshape(3, 3)
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))


class Kin:
    def __init__(self):
        import mujoco
        from collector import Collector
        from scene import SceneConfig
        self.mj = mujoco
        self.k = Collector(str(SIM / "mjcf" / "collector_scene.xml"),
                           cfg=SceneConfig(), render=False)
        self.lo = self.k.arm_range[:, 0]
        self.hi = self.k.arm_range[:, 1]

    def fk(self, q_rad):
        d = self.k._ik
        d.qpos[:] = self.k.data.qpos
        for a, v in zip(self.k.arm_qadr, q_rad):
            d.qpos[a] = v
        self.mj.mj_kinematics(self.k.model, d)
        return (d.site_xpos[self.k.tcp_sid].copy(),
                np.asarray(d.site_xmat[self.k.tcp_sid]).reshape(3, 3).copy())

    def solve(self, p_m, R):
        """What project_5dof does: pitch off the finger axis, solve_ik_best."""
        fwd = np.asarray(R)[:, 1]
        pitch = math.asin(max(-1.0, min(1.0, -fwd[2])))
        q, ep, er, oop = self.k.solve_ik_best(np.asarray(p_m), pitch)
        return q, ep, er, oop, pitch

    def close(self):
        self.k.close()


#: A start is not the start the protocol asked for if, at the first sample of
#: the rollout, the ball is this far from its placement. From HOME nothing has
#: touched it yet, so 2 mm; at a perturbed pose the move there nudges it, and
#: every demonstration nudged it too (v2_val 2.4-16.0 mm at that pose), so only
#: a knock past 25 mm. Measured from the logged free-joint ball, never from the
#: policy's inputs.
START_BALL_TOL_MM = {"home": 2.0, "perturbed": 25.0}


def episode_spec(split, idx, cache={}):
    key = (split, idx)
    if key not in cache:
        p = sorted((SIM / "data" / "demos" / split).glob("episode_*.npz"))[idx]
        cache[key] = json.loads(str(np.load(p, allow_pickle=True)["spec"]))
    return cache[key]


def start_check(e, cols, split):
    """Where the ball was when the policy was first asked, against where it
    was placed; and what the start procedure itself logged, when it did."""
    sp = episode_spec(split, e["episode"])
    ib = cols.index("ball_x_mm")
    first = next((r for r in e["ee_track"] if r[ib] is not None), None)
    last_try = (e.get("infra_log") or [{}])[-1]
    pert = last_try.get("perturbed") if "infra_log" in e else e.get("started_perturbed")
    out = {"perturbed": bool(pert), "settled": (pert or {}).get("settled"),
           "realized_pitch_deg": (pert or {}).get("realized_pitch"),
           "ball_start_dev_mm": None,
           "bodies_after_place": last_try.get("bodies_after_place"),
           "bodies_after_perturb": last_try.get("bodies_after_perturb")}
    if first is not None:
        want = np.array([sp["object_xy"][0], sp["object_xy"][1], sp["ball_r"]]) * 1000
        out["ball_start_dev_mm"] = round(float(np.linalg.norm(np.array(first[ib:ib + 3]) - want)), 2)
    tol = START_BALL_TOL_MM["perturbed" if out["perturbed"] else "home"]
    out["valid"] = out["ball_start_dev_mm"] is not None and out["ball_start_dev_mm"] <= tol
    out["tolerance_mm"] = tol
    return out


def ball_radius(split, idx, cache={}):
    key = (split, idx)
    if key not in cache:
        p = sorted((SIM / "data" / "demos" / split).glob("episode_*.npz"))[idx]
        cache[key] = float(json.loads(str(np.load(p, allow_pickle=True)["spec"]))["ball_r"]) * 1000
    return cache[key]


def episode_metrics(e, cols, split, kin, corridor):
    from analyse_grasp_corridor import inside
    ci = {c: i for i, c in enumerate(cols)}
    tk = np.array([[np.nan if v is None else v for v in row] for row in e["ee_track"]], float)
    T = tk[:, ci["stamp_s"]]
    P = tk[:, ci["pitch_deg"]]
    Q = np.radians(tk[:, ci["j1_deg"]:ci["j1_deg"] + 5])
    EE = tk[:, ci["x_mm"]:ci["x_mm"] + 3]
    BALL = tk[:, ci["ball_x_mm"]:ci["ball_x_mm"] + 3]
    JAW = tk[:, ci["jaw_gt_mm"]] if "jaw_gt_mm" in ci else None
    r_mm = ball_radius(split, e["episode"])
    dt = np.diff(T, append=T[-1])
    out = {"episode": e["episode"], "total_ticks": int(e["steps"]),
           "stage_ticks": {s: int(e["stage_ticks"].get(s, 0)) for s in STAGES},
           "infra_retries": int(e.get("infra_retries", 0)),
           "started_perturbed": e.get("started_perturbed")}
    inband = (P >= TRAP[0]) & (P < TRAP[1])
    out["trap_dwell_s"] = float(dt[inband].sum())
    out["reached_pitch_below_20"] = bool((P < 20.0).any())
    # tool-frame ball offset at every sample
    offs = np.full((len(T), 3), np.nan)
    for i in range(len(T)):
        if np.isnan(BALL[i]).any():
            continue
        p_m, R = kin.fk(Q[i])
        offs[i] = R.T @ (BALL[i] / 1000.0 - p_m) * 1000.0
    ok = ~np.isnan(offs).any(1)
    out["entered_corridor"] = bool(any(inside(corridor, offs[i], P[i]) for i in np.where(ok)[0]))
    stages_seen = [x["stage"] for x in e.get("stage_events", [])]
    out["grasp_stage_reached"] = "GRASP" in stages_seen or out["stage_ticks"]["GRASP"] > 0
    out["lift_stage_reached"] = "LIFT" in stages_seen or out["stage_ticks"]["LIFT"] > 0
    out["runtime_grasped_flag"] = bool(e["grasped"])
    lifted = ok & (BALL[:, 2] > r_mm + HOLD_RISE_MM)
    out["object_lifted"] = bool(lifted.any())
    secure = False
    if lifted.sum() >= 3:
        idx = np.where(lifted)[0]
        # kept for the record: the same numbers over EVERY lifted sample. That
        # was the first definition, and it is wrong for this purpose -- it
        # takes in the ball's fall after the jaw opens over the bin, so a
        # carried-and-placed ball failed it (20.9 mm "deviation").
        out["whole_lifted_seconds"] = float(dt[lifted].sum())
        out["whole_lifted_toolframe_deviation_mm"] = float(np.abs(offs[lifted] - offs[lifted].mean(0)).max())
        out["whole_lifted_ee_travel_mm"] = float(np.linalg.norm(EE[idx[-1]] - EE[idx[0]]))
        # The grasp is judged where it is supposed to hold: from a lift-off,
        # for as long as the ball rides with the tool -- the longest prefix of
        # that lifted stretch whose tool-frame positions all stay within
        # SECURE_STEADY_MM of the prefix's own mean. It ends at the release,
        # or wherever the ball starts to slip; it never reaches past either.
        # Every lifted stretch is judged from its own lift-off and the best
        # one is kept: the ball can graze the 20 mm line for 0.04-0.11 s while
        # the jaw takes the load, and judging only that first blip missed
        # carries of 130-150 mm that began 0.6 s later (correction 08:00).
        stretches, i0 = [], idx[0]
        while i0 < len(lifted):
            if lifted[i0]:
                j0 = i0
                while j0 + 1 < len(lifted) and lifted[j0 + 1]:
                    j0 += 1
                stretches.append(np.arange(i0, j0 + 1))
                i0 = j0 + 1
            else:
                i0 += 1
        best = None
        for seg in stretches:
            O = offs[seg]
            n_ = np.arange(1, len(seg) + 1)[:, None]
            mean = np.cumsum(O, 0) / n_
            hi_ = np.maximum.accumulate(O, 0)
            lo_ = np.minimum.accumulate(O, 0)
            dev_k = np.maximum(hi_ - mean, mean - lo_).max(1)
            bad = np.where(dev_k >= SECURE_STEADY_MM)[0]
            k_end = (bad[0] - 1) if len(bad) else len(seg) - 1
            if k_end >= 1:
                rig = seg[:k_end + 1]
                cand = (float(T[rig[-1]] - T[rig[0]]), float(dev_k[k_end]),
                        float(np.linalg.norm(EE[rig[-1]] - EE[rig[0]])))
            else:
                cand = (0.0, float(dev_k[0]), 0.0)
            ok_c = cand[0] >= SECURE_MIN_S and cand[1] < SECURE_STEADY_MM and cand[2] >= SECURE_MOVE_MM
            key = (ok_c, cand[2], cand[0])
            if best is None or key > best[0]:
                best = (key, cand)
        held_t, dev, moved = best[1]
        out["lifted_stretches"] = len(stretches)
        out["held_seconds"] = held_t
        out["held_toolframe_deviation_mm"] = dev
        out["held_ee_travel_mm"] = moved
        secure = held_t >= SECURE_MIN_S and dev < SECURE_STEADY_MM and moved >= SECURE_MOVE_MM
    out["strict_gt_secure_grasp"] = bool(secure)
    out["bin_success"] = bool(e["success"])
    pre = np.array([pl["valid_prefix"] for pl in e["trace"]])
    out["plans"] = int(len(pre))
    out["valid_prefix_le2_ratio"] = float((pre <= 2).mean()) if len(pre) else None
    out["consecutive_unreachable_abort"] = "eight plans in a row" in e["stopped_because"]
    out["abort_reason"] = e["stopped_because"]
    # close geometry: only at a real GRASP attempt
    out["close"] = None
    ge = [x for x in e.get("stage_events", []) if x["stage"] == "GRASP"]
    if ge and JAW is not None:
        tg = ge[0]["t"]
        kg = int(np.argmin(np.abs(T - tg)))
        open_w = float(np.nanmax(JAW[:max(kg, 1)]))
        k0 = kg
        while k0 > 0 and JAW[k0] < open_w - 1.0:
            k0 -= 1
        tc = T[k0]
        w = (T >= tc - 0.3) & (T <= tc)
        idx = np.where(w)[0]
        if len(idx) >= 2 and T[idx[-1]] > T[idx[0]]:
            path = float(np.linalg.norm(np.diff(EE[idx], axis=0), axis=1).sum())
            speed = path / (T[idx[-1]] - T[idx[0]]) * 0.1
        else:
            speed = None
        if ok[k0]:
            out["close"] = {"t_onset": float(tc), "t_grasp_entry": float(tg),
                            "jaw_open_mm": open_w, "jaw_at_onset_mm": float(JAW[k0]),
                            "lateral": float(offs[k0][0]), "depth": float(offs[k0][1]),
                            "vertical": float(offs[k0][2]), "pitch": float(P[k0]),
                            "tool_ball_distance_mm": float(np.linalg.norm(offs[k0])),
                            "ee_speed_mm_per_tick": (None if speed is None else float(speed))}
    return out


def rejections(e, kin):
    """Decompose every rejected waypoint, and profile every attempted one."""
    rows, att = [], []
    for pl in e["trace"]:
        pa = {x["k"]: x for x in pl.get("plan_abs", [])}
        for a in pl.get("attempts", []):
            x = pa.get(a["k"])
            if x is None:
                continue
            p_m = np.array(x["p"]) / 1000.0
            R = np.array(x["R"]).reshape(3, 3)
            q, ep, er, oop, pitch = kin.solve(p_m, R)
            p_got, R_got = kin.fk(q)
            rec = {"k": a["k"], "reachable": a["reachable"],
                   "logged_err_mm": a["ik_pos_err_mm"], "recomputed_err_mm": ep * 1000,
                   "pitch_err_deg": math.degrees(er), "asked_pitch_deg": math.degrees(pitch),
                   "orientation_residual_deg": geodesic_deg(R, R_got),
                   "joint_at_limit": bool(any(min(q[j] - kin.lo[j], kin.hi[j] - q[j]) < math.radians(0.5)
                                               for j in (1, 2, 3)))}
            att.append(rec)
            if not a["reachable"]:
                cause = ("joint limit" if rec["joint_at_limit"] else
                         "pitch unattainable at that position" if rec["pitch_err_deg"] > 2.0 else
                         "position unreachable (no limit, pitch met)")
                rows.append(dict(rec, cause=cause))
    return rows, att


@click.command()
@click.option("--runs", required=True, help="label=file[;file],...")
@click.option("--out", required=True)
@click.option("--invalid", default="",
              help="label:ep,ep|label:ep -- episodes whose start was not the "
                   "start the protocol asked for; listed, never counted")
@click.option("--invalid-reason", default="started from HOME after a re-reset, not from the perturbed pose")
def main(runs, out, invalid, invalid_reason):
    bad_eps = {}
    for part in [x for x in invalid.split("|") if x]:
        lab, eps_ = part.split(":")
        bad_eps[lab] = {int(v) for v in eps_.split(",") if v}
    from analyse_grasp_corridor import corridor as make_corridor
    corridor = make_corridor()
    kin = Kin()
    summary = {"definitions": {
        "trap_band_deg": TRAP, "lifted": f"ball z > radius + {HOLD_RISE_MM} mm",
        "strict_gt_secure_grasp": (f"from a lift-off (ball z > radius + {HOLD_RISE_MM} mm), over that "
                                   f"unbroken lifted stretch, the longest prefix in which the ball's "
                                   f"tool-frame position stays within {SECURE_STEADY_MM} mm of that prefix's "
                                   f"mean lasts >= {SECURE_MIN_S} s and the tool travels >= {SECURE_MOVE_MM} mm "
                                   f"in it; every lifted stretch is judged from its own lift-off and the "
                                   f"best kept. (Corrected 06:50: the first version measured over every "
                                   f"lifted sample, including the fall after release -- kept as "
                                   f"whole_lifted_*. Corrected 08:00: judging only the first stretch "
                                   f"caught 0.04-0.11 s grazes of the 20 mm line instead of the carry.)"),
        "close_geometry": "at the onset of closing of the first GRASP-stage attempt; N/A without one",
        "runtime_gate": "solve_ik_best in-plane position residual > 2 mm (the only runtime gate)",
        "invalid_start": (f"ball farther than {START_BALL_TOL_MM['home']} mm (from HOME) or "
                          f"{START_BALL_TOL_MM['perturbed']} mm (perturbed start) from its placement "
                          f"at the first rollout sample, or listed with --invalid; such episodes are "
                          f"listed and never counted")},
        "expert": EXPERT, "runs": {}}
    for spec in runs.split(","):
        label, files = spec.split("=", 1)
        eps, cols, split, infra = [], None, None, []
        for f in files.split(";"):
            d = load(f)
            cols = cols or d["ee_track_columns"]
            split = split or d.get("from_demos", "train")
            eps += d["episodes"]
            infra += d.get("infra_failed", [])
        per, rej_all, att_all = [], [], []
        invalid_start, kept = [], []
        for e in eps:
            st = start_check(e, cols, split)
            if e["episode"] in bad_eps.get(label, set()):
                invalid_start.append({"episode": e["episode"], "reason": invalid_reason, "start": st})
            elif not st["valid"]:
                invalid_start.append({"episode": e["episode"],
                                      "reason": (f"ball {st['ball_start_dev_mm']} mm from its placement "
                                                 f"when the rollout began (tolerance {st['tolerance_mm']} mm)"),
                                      "start": st})
            else:
                e["_start"] = st
                kept.append(e)
        eps = kept
        for e in sorted(eps, key=lambda x: x["episode"]):
            m = episode_metrics(e, cols, split, kin, corridor)
            rj, at = rejections(e, kin)
            m["rejections"] = Counter(x["cause"] for x in rj)
            m["start"] = e.pop("_start")
            per.append(m)
            rej_all += rj
            att_all += at
        n = len(per)
        rep = np.array([abs(a["recomputed_err_mm"] - a["logged_err_mm"]) for a in att_all]) if att_all else np.zeros(0)
        closes = [m["close"] for m in per if m["close"]]
        def geo(k):
            v = [c[k] for c in closes if c.get(k) is not None]
            return None if not v else {"n": len(v), "mean": float(np.mean(v)),
                                       "median": float(np.median(v)), "std": float(np.std(v)),
                                       "values": v}
        acc = [a for a in att_all if a["reachable"]]
        bad = [a for a in att_all if not a["reachable"]]
        R = {"n_episodes": n, "infra_failed_episodes": len(infra),
             "infra_retries_total": int(sum(m["infra_retries"] for m in per)),
             "counts": {k: int(sum(bool(m[k]) for m in per)) for k in (
                 "grasp_stage_reached", "lift_stage_reached", "runtime_grasped_flag",
                 "object_lifted", "strict_gt_secure_grasp", "bin_success",
                 "entered_corridor", "reached_pitch_below_20", "consecutive_unreachable_abort")},
             "total_ticks": [m["total_ticks"] for m in per],
             "stage_ticks_mean": {s: float(np.mean([m["stage_ticks"][s] for m in per])) for s in STAGES},
             "trap_dwell_s": [m["trap_dwell_s"] for m in per],
             "valid_prefix_le2_ratio": [m["valid_prefix_le2_ratio"] for m in per],
             "abort_reasons": dict(Counter(m["abort_reason"] for m in per)),
             "close_geometry": {k: geo(k) for k in ("lateral", "depth", "vertical", "pitch",
                                                    "ee_speed_mm_per_tick")},
             "feasibility": {
                 "attempted_waypoints": len(att_all), "rejected_waypoints": len(bad),
                 "rejection_causes": dict(Counter(x["cause"] for x in rej_all)),
                 "recomputation_matches_logged_within_0.05mm": (float((rep < 0.05).mean()) if len(rep) else None),
                 "asked_pitch_deg_accepted": (float(np.mean([a["asked_pitch_deg"] for a in acc])) if acc else None),
                 "asked_pitch_deg_rejected": (float(np.mean([a["asked_pitch_deg"] for a in bad])) if bad else None),
                 "orientation_residual_deg_accepted_mean": (float(np.mean([a["orientation_residual_deg"] for a in acc])) if acc else None),
                 "orientation_residual_deg_rejected_mean": (float(np.mean([a["orientation_residual_deg"] for a in bad])) if bad else None),
                 "pitch_err_deg_rejected_mean": (float(np.mean([a["pitch_err_deg"] for a in bad])) if bad else None),
                 "joint_at_limit_fraction_rejected": (float(np.mean([a["joint_at_limit"] for a in bad])) if bad else None)},
             "episodes": per, "infra_failed": infra, "invalid_start": invalid_start}
        summary["runs"][label] = R
        c = R["counts"]
        click.secho(f"\n{label}  (n={n} valid, invalid-start {len(invalid_start)} "
                    f"{[x['episode'] for x in invalid_start]}, infra-failed {len(infra)}, "
                    f"infra retries {R['infra_retries_total']})", bold=True)
        click.echo(f"  GRASP stage {c['grasp_stage_reached']}/{n}  LIFT stage {c['lift_stage_reached']}/{n}  "
                   f"runtime grasped {c['runtime_grasped_flag']}/{n}  lifted {c['object_lifted']}/{n}  "
                   f"strict secure {c['strict_gt_secure_grasp']}/{n}  bin {c['bin_success']}/{n}")
        click.echo(f"  corridor {c['entered_corridor']}/{n}  pitch<20 {c['reached_pitch_below_20']}/{n}  "
                   f"unreachable-abort {c['consecutive_unreachable_abort']}/{n}  "
                   f"ticks mean {np.mean(R['total_ticks']):.0f}  trap {np.mean(R['trap_dwell_s']):.2f}s")
        f = R["feasibility"]
        click.echo(f"  rejections {f['rejected_waypoints']}/{f['attempted_waypoints']}  causes {f['rejection_causes']}  "
                   f"(IK recomputation matches log in {f['recomputation_matches_logged_within_0.05mm']})")
        g = R["close_geometry"]
        no_jaw = "jaw_gt_mm" not in cols
        click.echo("  close geometry: " + (("N/A (this log has no jaw track)" if no_jaw else "N/A (no GRASP attempt)") if not closes else
                   "  ".join(f"{k} {g[k]['mean']:+.2f}" for k in ("lateral", "depth", "vertical", "pitch", "ee_speed_mm_per_tick") if g[k])
                   + f"  (n={len(closes)})"))
    kin.close()
    pathlib.Path(out).write_text(json.dumps(summary, indent=1, default=str))
    click.echo(f"\nwrote {out}")


if __name__ == "__main__":
    main()
