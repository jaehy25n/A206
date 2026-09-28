"""One DSE episode as a timeline: what happened on which tick, around plan boundaries.

    /home/j-j15a206/.conda/envs/umi/bin/python sim_umi/scripts/dse/dse_trace.py <run dir> --episode 0 \
        --plans 5,6,7 --out <stem>

Writes <stem>.png (timeline) and <stem>.md (per-plan table for the whole episode). All times
are sim time relative to the episode's reset tick.
"""
import json
import pathlib

import click
import numpy as np

DT = 0.002


@click.command()
@click.argument("run_dir")
@click.option("--episode", default=0)
@click.option("--plans", default="5,6,7")
@click.option("--out", required=True)
def main(run_dir, episode, plans, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = pathlib.Path(run_dir)
    R = json.load(open(d / "nominal_G0.json"))
    e = next(x for x in R["episodes"] if x["episode"] == episode)
    reset = e["infra_log"][0]["reset_tick_ns"] * 1e-9
    rel = lambda t: t - reset
    tr, tl = e["trace"], {r["plan"]: r for r in e["dse"]["timeline"]["plans"]}
    Z = np.load(d / "nominal_G0_frames" / f"ep{episode:02d}_cycles.npz")
    tc = Z["ns"] * 1e-9 - reset
    j1 = list(Z["names"]).index("joint1")
    q1 = Z["q"][:, j1]
    tcs = Z["cs_ns"] * 1e-9 - reset
    out1 = Z["cs_out"][:, 0]
    caps = [c * DT for c in e["dse"]["camera_checks"]["capture_ticks_rel"]]
    # ---- table ----
    L = [f"# DSE episode {episode} trace ({d.name}); times: sim s after the reset tick", "",
         "| plan | obs frames (t-0.1, t) | T_d = t+L_v | collected | k* | goal start | takeover | first point commanded | "
         "= t_k*-0.21 | jaw fired in (t,T_d] (from plan, late) | next obs | cadence |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, pl in enumerate(tr):
        dd = pl.get("dse", {})
        fr = [round(rel(f["image_stamp_s"]), 3) for f in pl["obs"]["frames"]]
        t = rel(pl["obs_t_s"])
        k = pl["sent"][0]["k"] if pl.get("sent") else None
        row = tl.get(n, {})
        jf = [(j["from_plan"], round(j["late_s"], 4)) for j in e["jaw_log"] if pl["obs_t_s"] < j["t_fired_s"] <= dd.get("T_d_s", 0) + 1e-4]
        nxt = dd.get("next_obs_s")
        fmt = lambda v: "" if v is None else f"{v:.3f}"
        gs = rel(pl["goal_start_tick_s"]) if pl.get("goal_start_tick_s") else None
        tk = rel(row["takeover_s"]) if row.get("takeover_s") else None
        fp = rel(pl["first_point_commanded_s"]) if pl.get("first_point_commanded_s") else None
        want = (t + 0.1 * k - 0.21) if k is not None else None
        nx = rel(nxt) if nxt is not None else None
        L.append(f"| {n} | {fr} | {rel(dd['T_d_s']):.3f} | {rel(pl['collected_at_s']):.4f} | {k} | {fmt(gs)} | "
                 f"{fmt(tk)} | {fmt(fp)} | {fmt(want)} | {jf} | {fmt(nx)} | {fmt(None if nx is None else nx - t)} |")
    L += ["", "Checks: " + json.dumps(e["dse"]["timeline"]["summary"]), "Gates: " + json.dumps(e["dse"]["gates"])]
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    # ---- figure ----
    ps = [int(x) for x in plans.split(",")]
    t0 = rel(tr[ps[0]]["obs_t_s"]) - 0.15
    t1 = rel(tr[ps[-1]]["dse"]["T_d_s"]) + 0.35
    fig, ax = plt.subplots(2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [1.3, 2]})
    a = ax[0]
    for c in caps:
        if t0 <= c <= t1:
            a.axvline(c, color="0.85", lw=0.8, zorder=0)
    cols = ["tab:blue", "tab:orange", "tab:green", "tab:purple", "tab:red"]
    for j, n in enumerate(ps):
        pl, dd, row = tr[n], tr[n]["dse"], tl.get(n, {})
        y = len(ps) - j
        col = cols[j % len(cols)]
        t, Td = rel(pl["obs_t_s"]), rel(dd["T_d_s"])
        for f in pl["obs"]["frames"]:
            a.plot(rel(f["image_stamp_s"]), y, "s", color=col, ms=7)
        a.plot([rel(pl["obs"]["frames"][0]["image_stamp_s"]), t], [y, y], ":", color=col)
        a.axvspan(t, Td, ymin=(y - 0.35) / (len(ps) + 1), ymax=(y + 0.35) / (len(ps) + 1), color=col, alpha=0.18)
        a.annotate(f"plan {n}: obs t={t:.3f}\ninfer (0 s sim)\nL_v -> T_d={Td:.3f}", (t, y + 0.25), fontsize=7, color=col)
        if row.get("takeover_s"):
            a.plot(rel(row["takeover_s"]), y, "v", color="k", ms=8)
        if pl.get("first_point_commanded_s"):
            a.plot(rel(pl["first_point_commanded_s"]), y, "*", color=col, ms=11)
        for jl in e["jaw_log"]:
            if t0 <= rel(jl["t_fired_s"]) <= t1 and jl["from_plan"] == n:
                a.plot(rel(jl["t_fired_s"]), y - 0.3, "^", color=col, ms=6)
    a.set_yticks(range(1, len(ps) + 1))
    a.set_yticklabels([f"plan {n}" for n in reversed(ps)])
    a.set_ylim(0.3, len(ps) + 0.9)
    a.set_title("squares: observation frames (t-0.1, t); shaded: L_v (old plan executing); v: JTC takeover (T_d + 1 tick); "
                "*: first commanded waypoint (t_k* - 0.21); ^: jaw command fired (colour = plan it came from); grey: camera captures",
                fontsize=8)
    b = ax[1]
    m = (tcs >= t0) & (tcs <= t1)
    b.plot(tcs[m], np.degrees(out1[m]), "-", lw=1.2, label="joint1 command in effect next step (controller output)")
    m2 = (tc >= t0) & (tc <= t1)
    b.plot(tc[m2], np.degrees(q1[m2]), "-", lw=1.0, label="joint1 actual (simulator state per cycle)")
    for j, n in enumerate(ps):
        row = tl.get(n, {})
        if row.get("takeover_s"):
            b.axvline(rel(row["takeover_s"]), color=cols[j % len(cols)], ls="--", lw=1)
    b.set_xlabel("sim time after the episode's reset tick (s)")
    b.set_ylabel("joint1 (deg)")
    b.legend(fontsize=8)
    b.set_xlim(t0, t1)
    fig.tight_layout()
    fig.savefig(out + ".png", dpi=130)
    print(f"wrote {out}.png and {out}.md")


if __name__ == "__main__":
    main()
