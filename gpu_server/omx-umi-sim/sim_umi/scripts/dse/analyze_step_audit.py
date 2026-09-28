"""Did the controller update actually skip a physics step, or was only its
message lost?  From step_audit.json (v2: raw streams).

    python sim_umi/scripts/dse/analyze_step_audit.py <step_audit.json> [...] --out <stem>

Two independent per-update messages exist: the arm controller's
controller_state (reference / output = command written / feedback) and the
hardware read()'s /mujoco_actuators_states (the simulator's qpos, qvel and
qfrc_actuator as of the last physics step). Neither is trusted to be complete.

The simulator side decides. joint1 is a MuJoCo position servo
(force = kp*ctrl - kp*q - kv*qd, limited to +-3.5, gear 1), so the ctrl that was
actually in effect during the step ending at tick i is

    u_i = (qfrc_i + kp*q_{i-1} + kv*qd_{i-1}) / kp

(qfrc_i is computed at the start of that step from the state at tick i-1).
While the trajectory moves, every controller update writes a new command, so
  u_{i+1} == out_i        the update on tick i ran and its command was in effect
                          for the next step (offset 1)
  u_{i+1} == u_i          no new command reached step i+1: the update on tick i
                          did not run, or its write missed the step
and a missing message on a tick whose command did take effect is a publish loss
only. The JTC's own trajectory clock (reference.time_from_start) is reported
alongside: it advances by the measured period, 4 ms across a skipped tick.
kv is checked against the data (least squares over ticks with a known
command), not assumed.
"""
import json
import pathlib
import sys

import click
import numpy as np

DT = 0.002
KP = 50.0
KV_MODEL = 4.86944          # compiled from collector_scene.xml (dampratio 1)
FMAX = 3.5


def by_tick(msgs, t0, n):
    out = [None] * (n + 1)
    for m in msgs:
        i = int(round((m["t"] - t0) / DT))
        if 0 <= i <= n and abs(m["t"] - (t0 + i * DT)) < 5e-4:
            out[i] = m
    return out


def analyse(rep):
    raw = rep["raw"]
    t_goal = rep["t_goal"]
    n = len(rep["rows"]) * rep["steps_per_call"]      # ticks after the goal (a row is one StepSimulation call)
    t0 = t_goal - 0.2                            # 100 ticks of the settled hold before the goal
    N = n + 100
    cs, act = by_tick(raw["cs"], t0, N), by_tick(raw["act"], t0, N)
    ji_a = act[next(i for i, x in enumerate(act) if x)]["names"].index("joint1")
    ji_c = cs[next(i for i, x in enumerate(cs) if x)]["names"].index("joint1")
    q = [None if a is None else a["q"][ji_a] for a in act]
    qd = [None if a is None else a["qd"][ji_a] for a in act]
    eff = [None if a is None else a["eff"][ji_a] for a in act]
    out = [None if c is None or not c["out"] else c["out"][ji_c] for c in cs]
    tfs = [None if c is None else c["ref_tfs"] for c in cs]
    # kv from the data: eff_i = kp*out_{i-1} - kp*q_{i-1} - kv*qd_{i-1} where the command is known
    A, b = [], []
    for i in range(1, N + 1):
        if None not in (eff[i], q[i - 1], qd[i - 1], out[i - 1]) and abs(eff[i]) < FMAX - 1e-6 and abs(qd[i - 1]) > 1e-3:
            A.append(qd[i - 1]); b.append(KP * out[i - 1] - KP * q[i - 1] - eff[i])
    kv_fit = float(np.dot(A, b) / np.dot(A, A)) if A else None
    kv = kv_fit if kv_fit is not None else KV_MODEL
    u = [None] * (N + 1)
    for i in range(1, N + 1):
        if None not in (eff[i], q[i - 1], qd[i - 1]) and abs(eff[i]) < FMAX - 1e-6:
            u[i] = (eff[i] + KP * q[i - 1] + kv * qd[i - 1]) / KP
    # residual of offset-1 where the command is known: validates the inversion
    res1 = [abs(u[i + 1] - out[i]) for i in range(N) if u[i + 1] is not None and out[i] is not None]
    # classify ticks in the moving phase (commands change every update)
    moving = [i for i in range(1, N) if out[i] is not None and out[i - 1] is not None and abs(out[i] - out[i - 1]) > 1e-6]
    lo, hi = (min(moving), max(moving)) if moving else (0, -1)
    tol = 1e-9
    ticks = []
    for i in range(lo, hi + 1):
        rec = {"i": i - 100, "cs": cs[i] is not None, "act": act[i] is not None}
        if u[i + 1] is not None and u[i] is not None:
            held = abs(u[i + 1] - u[i]) < tol
            new_ok = out[i] is not None and abs(u[i + 1] - out[i]) < 1e-7
            rec["verdict"] = ("update ran, command in effect next step" if new_ok else
                              "NO new command at the next step (update skipped or write missed the step)" if held else
                              "new command in effect, value unobserved" if out[i] is None else
                              "command in effect differs from this update's output")
        else:
            rec["verdict"] = "undetermined (simulator state message missing)"
        if i > 0 and tfs[i] is not None and tfs[i - 1] is not None:
            rec["jtc_clock_step_ms"] = round((tfs[i] - tfs[i - 1]) * 1000, 4)
        ticks.append(rec)
    missing = [t for t in ticks if not (t["cs"] and t["act"])]
    # over the whole window after the reset (tick >= -99): which messages were lost, and was
    # the cycle there at all -- read() and update() run in the same controller-manager cycle,
    # so a tick with one of the two messages had its cycle
    win = range(1, N + 1)
    both_missing = [i - 100 for i in win if cs[i] is None and act[i] is None]
    cs_only = [i - 100 for i in win if cs[i] is None and act[i] is not None]
    act_only = [i - 100 for i in win if act[i] is None and cs[i] is not None]
    clk = sorted(int(round(c * 1e9)) for c in raw["clock"])
    short = [int(round((clk[k + 1] / 1e9 - t0) / DT)) - 100 for k in range(len(clk) - 1)
             if 0 < clk[k + 1] - clk[k] < 2_000_000]
    held = [t["i"] for t in ticks if t["verdict"].startswith("NO new")]
    publish_only = [t["i"] for t in ticks if (not t["cs"] or not t["act"]) and t["verdict"].startswith(("update ran", "new command"))]
    ns = [c["t"] for c in raw["cs"]]
    periods_ns = sorted({int(round((b_ - a_) * 1e9)) for a_, b_ in zip(ns, ns[1:])})
    return {"kv_fit": kv_fit, "kv_model": KV_MODEL, "offset1_residual_max": max(res1) if res1 else None,
            "offset1_residual_median": float(np.median(res1)) if res1 else None, "n_offset1_checked": len(res1),
            "moving_ticks": (lo - 100, hi - 100), "ticks_with_a_missing_message": [
                {k: t[k] for k in ("i", "cs", "act", "verdict")} for t in missing],
            "held_command_ticks": held, "publish_only_loss_ticks": publish_only,
            "cycle_absent_ticks": both_missing, "controller_state_lost_only": cs_only,
            "actuator_state_lost_only": act_only, "clock_delta_1999999ns_ticks": short,
            "cycle_absent_equals_short_clock_delta": sorted(both_missing) == sorted(x for x in short if x >= -99),
            "jtc_clock_steps_ms": sorted({t.get("jtc_clock_step_ms") for t in ticks if t.get("jtc_clock_step_ms") is not None}),
            "cs_stamp_periods_ns": periods_ns[:10],
            "q": q, "u": u}


def compare(A, B):
    # from the first settle step on (tick -99): the sample at -100 can predate the reset
    qa, qb, ua, ub = A["q"], B["q"], A["u"], B["u"]
    d = [(i - 100, abs(x - y)) for i, (x, y) in enumerate(zip(qa, qb)) if i >= 1 and x is not None and y is not None]
    du = [(i - 100, abs(x - y)) for i, (x, y) in enumerate(zip(ua, ub)) if i >= 2 and x is not None and y is not None]
    first_q = next((i for i, v in d if v > 0), None)
    first_u = next((i for i, v in du if v > 0), None)
    return {"first_tick_q_differs": first_q, "max_abs_dq_rad": max(v for _, v in d) if d else None,
            "first_tick_u_differs": first_u, "max_abs_du_rad": max(v for _, v in du) if du else None}


@click.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--out", required=True)
def main(files, out):
    rep, L = {}, []
    for f in files:
        R = json.load(open(f))
        for case, reps in R["cases"].items():
            if not reps[0].get("raw"):
                continue
            an = [analyse(r) for r in reps]
            cmp_ = [compare(an[0], x) for x in an[1:]]
            rep[case] = {"repeats": [{k: v for k, v in a.items() if k not in ("q", "u")} for a in an], "vs_repeat0": cmp_}
            L.append(f"## case {case} ({len(reps)} repeats; steps/call {reps[0]['steps_per_call']}, settle {reps[0]['settle_ms']} ms)")
            for j, a in enumerate(an):
                L.append(f"- repeat {j}: controller-manager cycle absent (both messages missing) at {a['cycle_absent_ticks']}; "
                         f"/clock delta 1,999,999 ns at {[x for x in a['clock_delta_1999999ns_ticks'] if x >= -99]} "
                         f"(identical sets: {a['cycle_absent_equals_short_clock_delta']}); controller_state lost alone at "
                         f"{a['controller_state_lost_only']}; actuator_states lost alone at {a['actuator_state_lost_only']}")
                L.append(f"- repeat {j}: kv fit {a['kv_fit']:.5f} (model {KV_MODEL}), offset-1 residual median "
                         f"{a['offset1_residual_median']:.2e} max {a['offset1_residual_max']:.2e} over {a['n_offset1_checked']} ticks; "
                         f"moving ticks {a['moving_ticks']}; ticks with a missing message {len(a['ticks_with_a_missing_message'])}; "
                         f"held-command ticks {a['held_command_ticks']}; publish-only losses {a['publish_only_loss_ticks']}; "
                         f"JTC clock steps (ms) {a['jtc_clock_steps_ms']}; cs stamp periods (ns) {a['cs_stamp_periods_ns']}")
                for t in a["ticks_with_a_missing_message"]:
                    L.append(f"    tick {t['i']}: controller_state {'yes' if t['cs'] else 'MISSING'}, actuator_states "
                             f"{'yes' if t['act'] else 'MISSING'} -> {t['verdict']}")
            for j, c in enumerate(cmp_, 1):
                L.append(f"- repeat {j} vs 0: q first differs at tick {c['first_tick_q_differs']}, max |dq| {c['max_abs_dq_rad']:.3e} rad; "
                         f"applied ctrl first differs at tick {c['first_tick_u_differs']}, max |du| {c['max_abs_du_rad']:.3e} rad")
            L.append("")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1, default=str))
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
