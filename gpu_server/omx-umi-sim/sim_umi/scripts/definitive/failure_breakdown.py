"""Episode-by-episode breakdown of a definitive run: where each one ended, and
for a run that ended on eight unreachable plans, what the arm was asked for.

    python sim_umi/scripts/definitive/failure_breakdown.py \
        sim_umi/eval_results/2026-09-27_definitive/nominal_v2_11400.json --out <stem>

Evaluation only. The runtime gate is reproduced exactly: the pitch is read off
the raw action's finger axis, joints 2-4 are solved by solve_ik_best and
clipped to their limits, and a waypoint is refused when the in-plane position
miss is above 2 mm. For every refused waypoint this asks three further things
the runtime never asks:

- which of joints 2-4 the solution is pinned at, and how far past that limit
  the same solve goes when the limits are lifted (the unclipped requirement);
- whether the position is reachable at SOME pitch (scan), i.e. whether it is
  the pitch that was impossible or the position itself;
- how much yaw the projection threw away (finger axis vs the radial plane).

Ground-truth ball pose and jaw are read from the logs for scoring only.
"""
import json
import math
import pathlib
import sys

import click
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(SIM / "src"), str(SIM / "scripts"), str(SIM / "scripts" / "definitive")]

from aggregate import EXPERT, Kin, load  # noqa: E402

GATE_MM = 2.0
LIMIT_TOL_DEG = 0.5
PITCH_SCAN = np.radians(np.arange(-30.0, 90.1, 2.0))


def stage_at(events, t):
    s = events[0]["stage"] if events else "?"
    for ev in events:
        if ev["t"] <= t + 1e-6:
            s = ev["stage"]
    return s


class Gate:
    def __init__(self, kin):
        self.kin, self.k = kin, kin.k
        self.lo = self.k.arm_range[:, 0].copy()
        self.hi = self.k.arm_range[:, 1].copy()

    def solve(self, p, pitch, clipped=True):
        if clipped:
            return self.k.solve_ik_best(np.asarray(p), pitch)
        saved = self.k.arm_range.copy()
        try:
            self.k.arm_range[1:4, 0] = -2 * math.pi
            self.k.arm_range[1:4, 1] = 2 * math.pi
            return self.k.solve_ik_best(np.asarray(p), pitch)
        finally:
            self.k.arm_range[:] = saved

    def refused(self, p_mm, R9):
        p = np.asarray(p_mm) / 1000.0
        R = np.asarray(R9).reshape(3, 3)
        fwd = R[:, 1]
        pitch = math.asin(max(-1.0, min(1.0, -fwd[2])))
        q, ep, er, oop = self.solve(p, pitch)
        at = [f"joint{j + 1} {'lower' if q[j] - self.lo[j] < self.hi[j] - q[j] else 'upper'}"
              for j in (1, 2, 3)
              if min(q[j] - self.lo[j], self.hi[j] - q[j]) < math.radians(LIMIT_TOL_DEG)]
        qu, epu, _, _ = self.solve(p, pitch, clipped=False)
        over = {}
        for j in (1, 2, 3):
            past = max(self.lo[j] - qu[j], qu[j] - self.hi[j], 0.0)
            if past > 0:
                over[f"joint{j + 1}"] = round(math.degrees(past), 2)
        scan = [self.solve(p, pp)[1] for pp in PITCH_SCAN]
        kbest = int(np.argmin(scan))
        bx, by = self.k.arm_pivot_xy
        radial = np.array([p[0] - bx, p[1] - by])
        h = fwd[:2]
        yaw_dev = (math.degrees(math.acos(max(-1.0, min(1.0, float(
            h @ radial / (np.linalg.norm(h) * np.linalg.norm(radial) + 1e-12))))))
            if np.linalg.norm(h) > 1e-6 else None)
        return {"miss_mm": round(ep * 1000, 2), "asked_pitch_deg": round(math.degrees(pitch), 2),
                "pinned": at, "past_limit_deg_if_unclipped": over,
                "unclipped_miss_mm": round(epu * 1000, 2),
                "best_pitch_deg": round(math.degrees(PITCH_SCAN[kbest]), 1),
                "best_pitch_miss_mm": round(scan[kbest] * 1000, 2),
                "reachable_at_some_pitch": bool(scan[kbest] * 1000 <= GATE_MM),
                "yaw_discarded_deg": None if yaw_dev is None else round(yaw_dev, 1),
                "radius_mm": round(float(np.linalg.norm(radial)) * 1000, 1),
                "z_mm": round(float(p[2]) * 1000, 1)}

    def miss_only(self, p_mm, R9):
        p = np.asarray(p_mm) / 1000.0
        R = np.asarray(R9).reshape(3, 3)
        pitch = math.asin(max(-1.0, min(1.0, -R[:, 1][2])))
        return self.solve(p, pitch)[1] * 1000


def episode(e, cols, gate, kin, ball_r_mm):
    ci = {c: i for i, c in enumerate(cols)}
    tk = np.array([[np.nan if v is None else v for v in r] for r in e["ee_track"]], float)
    T = tk[:, ci["stamp_s"]]
    Q = np.radians(tk[:, ci["j1_deg"]:ci["j1_deg"] + 5])
    B = tk[:, ci["ball_x_mm"]:ci["ball_x_mm"] + 3]
    P = tk[:, ci["pitch_deg"]]
    JAW = tk[:, ci["jaw_gt_mm"]]
    offs = np.full((len(T), 3), np.nan)
    for i in range(len(T)):
        if not np.isnan(B[i]).any():
            p_m, R = kin.fk(Q[i])
            offs[i] = R.T @ (B[i] / 1000.0 - p_m) * 1000.0
    ev = e.get("stage_events", [])
    plans = e["trace"]
    lo, hi = gate.lo, gate.hi

    def nearest(t):
        return int(np.argmin(np.abs(T - t)))

    out = {"episode": e["episode"], "ticks": int(e["steps"]), "ended": e["stopped_because"],
           "stage_path": [f"{x['stage']}@{x['tick']}" for x in ev],
           "grasped_flag": bool(e["grasped"]), "bin": bool(e["success"]),
           "ball_max_rise_mm": round(float(np.nanmax(B[:, 2]) - ball_r_mm), 1)}
    # insertion depth: at every GRASP entry's closing onset, and the deepest
    # the ball ever sat along the finger axis while it was between the jaws'
    # lateral and vertical reach
    close_pts, seen_k0, prev_kg = [], set(), 0
    for x in ev:
        if x["stage"] != "GRASP":
            continue
        kg = nearest(x["t"])
        open_w = float(np.nanmax(JAW[:max(kg, 1)]))
        k0 = kg
        while k0 > 0 and JAW[k0] < open_w - 1.0:
            k0 -= 1
        if k0 in seen_k0:
            # the jaw never came back to within 1 mm of open since the last
            # close, so there is no new closing onset -- say so rather than
            # repeat the old one
            close_pts.append({"grasp_entry_tick": x["tick"], "same_close_as_before": True,
                              "jaw_max_since_last_entry_mm": round(float(np.nanmax(JAW[prev_kg:kg + 1])), 1),
                              "jaw_at_entry_mm": round(float(JAW[kg]), 1)})
            prev_kg = kg
            continue
        seen_k0.add(k0)
        prev_kg = kg
        close_pts.append({"grasp_entry_tick": x["tick"], "t": round(float(T[k0] - T[0]), 2),
                          "lateral": round(float(offs[k0, 0]), 2), "depth": round(float(offs[k0, 1]), 2),
                          "vertical": round(float(offs[k0, 2]), 2), "pitch": round(float(P[k0]), 2),
                          "jaw_min_after_mm": round(float(np.nanmin(JAW[kg:])), 1),
                          "object_visible_near": None})
    for c in close_pts:
        if c.get("same_close_as_before"):
            continue
        tc = T[0] + c["t"]
        pl = min(plans, key=lambda x: abs(x["obs_t_s"] - tc))
        c["object_visible_near"] = bool(pl["object_visible"])
    out["closing_onsets"] = close_pts
    inreach = (np.abs(offs[:, 0]) < 10) & (offs[:, 2] > -5) & (offs[:, 2] < 20)
    pre = inreach & (T < (T[0] + close_pts[0]["t"] if close_pts else T[-1]))
    # where the ball went: pushed along the table by failed closes
    bxy = np.array(gate.k.arm_pivot_xy) * 1000
    rb = np.hypot(B[:, 0] - bxy[0], B[:, 1] - bxy[1])
    out["ball_radius_mm"] = {"start": round(float(rb[0]), 1), "end": round(float(rb[-1]), 1),
                             "max": round(float(np.nanmax(rb)), 1)}
    out["deepest_before_first_close_mm"] = (round(float(np.nanmin(offs[pre, 1])), 2) if pre.any() else None)
    out["deepest_ever_mm"] = round(float(np.nanmin(offs[inreach, 1])), 2) if inreach.any() else None
    # visibility over the approach
    app = [pl for pl in plans if stage_at(ev, pl["obs_t_s"]) in ("APPROACH_OBJECT", "GRASP")]
    out["object_visible_in_approach_grasp"] = f"{sum(pl['object_visible'] for pl in app)}/{len(app)} plans"
    # refused plans
    vp = [pl["valid_prefix"] for pl in plans]
    failed = [i for i, v in enumerate(vp) if v == 0]
    out["plans"] = len(plans)
    out["plans_nothing_sendable"] = len(failed)
    out["plans_with_any_refusal"] = sum(1 for pl in plans if pl["first_unreachable_k"] is not None)
    first_ref = next((i for i, pl in enumerate(plans) if pl["first_unreachable_k"] is not None), None)
    if first_ref is not None:
        pl = plans[first_ref]
        out["first_refusal"] = {"plan": first_ref, "t": round(pl["obs_t_s"] - T[0], 2),
                                "stage": stage_at(ev, pl["obs_t_s"]), "sent_before_it": pl["valid_prefix"]}
    # the trailing run of plans with nothing sendable, if the run ended on it
    s = len(plans)
    while s > 0 and vp[s - 1] == 0:
        s -= 1
    streak = list(range(s, len(plans)))
    if len(streak) >= 8:
        pl0 = plans[streak[0]]
        k0 = nearest(pl0["obs_t_s"])
        q0 = Q[k0]
        margins = {f"joint{j + 1}": {"q_deg": round(math.degrees(q0[j]), 2),
                                     "to_lower_deg": round(math.degrees(q0[j] - lo[j]), 2),
                                     "to_upper_deg": round(math.degrees(hi[j] - q0[j]), 2)}
                   for j in range(5)}
        rows = []
        for i in streak:
            pl = plans[i]
            pa = {x["k"]: x for x in pl["plan_abs"]}
            k_first = pl["first_unreachable_k"]
            ref = gate.refused(pa[k_first]["p"], pa[k_first]["R"]) if k_first is not None else None
            misses = [round(gate.miss_only(x["p"], x["R"]), 1) for x in pl["plan_abs"]]
            ee = np.array(pl["ee_at_obs_mm"])
            tgt = np.array(pa[k_first]["p"]) if k_first is not None else None
            rows.append({"plan": i, "t": round(pl["obs_t_s"] - T[0], 2),
                         "stage": stage_at(ev, pl["obs_t_s"]),
                         "object_visible": bool(pl["object_visible"]), "bin_visible": bool(pl["bin_visible"]),
                         "first_due_k": k_first, "first_due": ref,
                         "raw_misses_all_16_mm": misses,
                         "raw_unreachable_of_16": int(sum(m > GATE_MM for m in misses)),
                         "target_minus_ee_mm": None if tgt is None else (tgt - ee).round(1).tolist()})
        kb = nearest(pl0["obs_t_s"])
        out["abort_streak"] = {
            "first_plan": streak[0], "length": len(streak),
            "t": round(pl0["obs_t_s"] - T[0], 2), "stage": stage_at(ev, pl0["obs_t_s"]),
            "plan_before": {"plan": streak[0] - 1, "sent": vp[streak[0] - 1]} if streak[0] > 0 else None,
            "measured_joints_at_start": margins,
            "ball_at_start": {"rise_mm": round(float(B[kb, 2] - ball_r_mm), 1),
                              "toolframe_mm": offs[kb].round(1).tolist()},
            "plans_detail": rows}
    return out


def md_episode(x):
    L = [f"### ep{x['episode']} — {x['ended']} ({x['ticks']} ticks; bin {x['bin']})", ""]
    L.append(f"- stages: {' → '.join(x['stage_path'])}")
    L.append(f"- ball max rise {x['ball_max_rise_mm']} mm; runtime grasped flag {x['grasped_flag']}; "
             f"ball distance from the base {x['ball_radius_mm']['start']} -> {x['ball_radius_mm']['end']} mm "
             f"(max {x['ball_radius_mm']['max']})")
    for c in x["closing_onsets"]:
        if c.get("same_close_as_before"):
            L.append(f"- GRASP entry tick {c['grasp_entry_tick']}: no new close -- the jaw only reopened to "
                     f"{c['jaw_max_since_last_entry_mm']} mm since the last entry (open ~51.8)")
            continue
        L.append(f"- closing onset (GRASP entry tick {c['grasp_entry_tick']}): lateral {c['lateral']:+.1f}, "
                 f"depth {c['depth']:+.1f}, vertical {c['vertical']:+.1f} mm, pitch {c['pitch']:.1f}°; "
                 f"jaw closed to {c['jaw_min_after_mm']} mm afterwards; object in crop {c['object_visible_near']}")
    L.append(f"- deepest along the finger axis before the first close: {x['deepest_before_first_close_mm']} mm; "
             f"ever: {x['deepest_ever_mm']} mm (expert onset {EXPERT['depth'][0]:+.2f} [{EXPERT['depth'][1]}, {EXPERT['depth'][2]}])")
    L.append(f"- object in crop during APPROACH/GRASP: {x['object_visible_in_approach_grasp']}")
    L.append(f"- plans {x['plans']}; with a refusal {x['plans_with_any_refusal']}; nothing sendable {x['plans_nothing_sendable']}")
    if x.get("first_refusal"):
        f = x["first_refusal"]
        L.append(f"- first refusal: plan {f['plan']} at {f['t']} s in {f['stage']} ({f['sent_before_it']} waypoints sent before it)")
    a = x.get("abort_streak")
    if a:
        L.append(f"- **8-plan abort** starts plan {a['first_plan']} at {a['t']} s in **{a['stage']}**; "
                 f"plan before it sent {a['plan_before']['sent'] if a['plan_before'] else '—'}")
        m = a["measured_joints_at_start"]
        L.append("- measured joints then (deg; margin to lower / upper hard limit): " + "; ".join(
            f"{j} {v['q_deg']:+.1f} ({v['to_lower_deg']:.1f} / {v['to_upper_deg']:.1f})" for j, v in m.items()))
        L.append(f"- ball then: rise {a['ball_at_start']['rise_mm']} mm, tool frame {a['ball_at_start']['toolframe_mm']} mm")
        L.append("")
        L.append("| plan | t s | stage | obj / bin in crop | first due k | miss mm | asked pitch | pinned | past limit if unclipped (deg) | best pitch (miss) | reachable at some pitch | yaw discarded | target r / z mm | raw unreachable of 16 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in a["plans_detail"]:
            f = r["first_due"] or {}
            L.append(f"| {r['plan']} | {r['t']} | {r['stage']} | {r['object_visible']} / {r['bin_visible']} | {r['first_due_k']} | "
                     f"{f.get('miss_mm')} | {f.get('asked_pitch_deg')} | {', '.join(f.get('pinned', [])) or '—'} | "
                     f"{f.get('past_limit_deg_if_unclipped') or '—'} | {f.get('best_pitch_deg')} ({f.get('best_pitch_miss_mm')}) | "
                     f"{f.get('reachable_at_some_pitch')} | {f.get('yaw_discarded_deg')} | {f.get('radius_mm')} / {f.get('z_mm')} | "
                     f"{r['raw_unreachable_of_16']} |")
    L.append("")
    return "\n".join(L)


@click.command()
@click.argument("rollout")
@click.option("--out", required=True, help="output stem (.json and .md are written)")
def main(rollout, out):
    d = load(rollout)
    cols = d["ee_track_columns"]
    split = d.get("from_demos", "train")
    specs = [json.loads(str(np.load(p, allow_pickle=True)["spec"]))
             for p in sorted((SIM / "data" / "demos" / split).glob("episode_*.npz"))]
    kin = Kin()
    gate = Gate(kin)
    res = [episode(e, cols, gate, kin, specs[e["episode"]]["ball_r"] * 1000) for e in d["episodes"]]
    pathlib.Path(out + ".json").write_text(json.dumps(res, indent=1))
    md = [f"# Episode breakdown — {pathlib.Path(rollout).name}", "",
          f"Gate reproduced: pitch from the raw finger axis, solve_ik_best with joints 2-4 clipped, refused above {GATE_MM} mm. "
          f"'pinned' = within {LIMIT_TOL_DEG}° of a hard limit; 'past limit if unclipped' = the same solve with the limits lifted; "
          f"'best pitch' = the pitch in a {math.degrees(PITCH_SCAN[0]):.0f}..{math.degrees(PITCH_SCAN[-1]):.0f}° scan with the smallest miss at that position.", ""]
    md += [md_episode(x) for x in res]
    pathlib.Path(out + ".md").write_text("\n".join(md))
    click.echo("\n".join(md))


if __name__ == "__main__":
    main()
