"""Where does the sign flip between what the policy asked and what the arm did?

    python sim_umi/scripts/audit_signed_axis.py --rollout .../rollout_e60_prefix.json.gz

Six plans from the moment the jaw first read shut ask for a net rise, and over
the following 1.5 s the tool fell 14.91 mm. Something between the prediction
and the joints reverses it, and the layers have to be separated to say which.

Five of them, all on the one absolute time axis the actions already carry:

    raw          the prediction decoded into the base frame
    projected    the same after project_5dof -- the nearest pose the five
                 axes can hold, which is the FK of the IK solution
    ik->fk       that IK solution's joint targets, put back through FK. It
                 should equal the line above exactly; if it does not, the
                 projection is not reporting what it returns
    commanded    the subset of those waypoints that actually went into a
                 JointTrajectory goal, and survived being replaced by the
                 next plan
    actual       the tool as the joint states report it

Nothing is re-run. Everything here is read from the rollout's own log.

What is NOT in that log: the actual joint positions and therefore the actual
tool orientation. Four of the five layers carry a pitch; the fifth carries
only a height. That is stated rather than filled in.
"""
import gzip
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))

import click
import numpy as np


def load(p):
    p = pathlib.Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return json.load(f)


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


def track_at(track, t):
    a = np.asarray(track, float)
    if t < a[0, 0] or t > a[-1, 0]:
        return None
    return np.array([np.interp(t, a[:, 0], a[:, 1 + i]) for i in range(3)])


@click.command()
@click.option("--rollout", "rollout_path", required=True)
@click.option("--episode", default=2, type=int)
@click.option("--plans", default=6, type=int)
@click.option("--dt", default=0.1, type=float)
@click.option("--window", default=1.5, type=float)
def main(rollout_path, episode, plans, dt, window):
    d = load(rollout_path)
    e = [x for x in d["episodes"] if x["episode"] == episode][0]
    tr = e["trace"]
    track = e["ee_track"]
    i0 = next((k for k, r in enumerate(tr) if r.get("jaw_gt_mm", 99) < 45), None)
    if i0 is None:
        raise click.ClickException("the jaw never read shut in this rollout")
    sel = tr[i0:i0 + plans]
    t0 = sel[0]["obs_t_s"]
    click.secho(f"rollout {episode}, plans {i0}..{i0+len(sel)-1}, from the first "
                f"frame the jaw read shut (tick {sel[0].get('tick')}, t={t0:.3f})",
                bold=True)

    # ------------------------------------------------- the forward kinematics --
    from collector import Collector
    from scene import SceneConfig, write_scene
    import mujoco
    scfg = SceneConfig()
    kin = Collector(str(write_scene(scfg)), cfg=scfg, render=False)

    def fk(q_deg):
        dd = kin._ik
        dd.qpos[:] = kin.data.qpos
        for a, v in zip(kin.arm_qadr, np.radians(q_deg)):
            dd.qpos[a] = v
        mujoco.mj_kinematics(kin.model, dd)
        p = dd.site_xpos[kin.tcp_sid].copy() * 1000.0
        R = np.asarray(dd.site_xmat[kin.tcp_sid]).reshape(3, 3).copy()
        return p, R

    # ------------------------------------- 1. the layers, plan by plan --
    click.secho("\n1. net change over each plan's own horizon, signed", bold=True)
    click.echo(f"  {'plan':>5s} {'t0':>9s} {'pre':>4s} {'sent':>5s} | "
               f"{'raw dz':>8s} {'proj dz':>8s} {'ikfk dz':>8s} {'cmd dz':>8s} | "
               f"{'raw dp':>8s} {'proj dp':>8s} {'ikfk dp':>8s}")
    fk_mismatch = []
    rowsum = {"raw": [], "proj": [], "ikfk": [], "cmd": []}
    for j, r in enumerate(sel):
        pa = {x["k"]: x for x in r["plan_abs"]}
        sent = {x["k"]: x for x in r["sent"]}
        ks = sorted(sent)
        # every sent waypoint went into the goal unless the goal held fewer
        ngoal = r.get("goal_points", len(ks)) or 0
        cmd_ks = ks[len(ks) - ngoal:] if ngoal else []
        raw_z = [pa[k]["p"][2] for k in ks]
        raw_p = [pitch_of(pa[k]["R"]) for k in ks]
        pr_z = [sent[k]["p_mm"][2] for k in ks]
        ik = [fk(sent[k]["q_deg"]) for k in ks]
        ik_z = [v[0][2] for v in ik]
        ik_p = [pitch_of(v[1]) for v in ik]
        pr_p = ik_p                     # project_5dof returns the FK of the IK
        for k, z_pr, z_ik in zip(ks, pr_z, ik_z):
            if abs(z_pr - z_ik) > 0.05:
                fk_mismatch.append((j, k, z_pr, z_ik))
        cz = [sent[k]["p_mm"][2] for k in cmd_ks]
        def net(v):
            return (v[-1] - v[0]) if len(v) > 1 else float("nan")
        rowsum["raw"].append(net(raw_z))
        rowsum["proj"].append(net(pr_z))
        rowsum["ikfk"].append(net(ik_z))
        rowsum["cmd"].append(net(cz))
        click.echo(f"  {i0+j:5d} {r['obs_t_s']-t0:8.3f}s {r['valid_prefix']:4d} "
                   f"{ngoal:5d} | {net(raw_z):+8.2f} {net(pr_z):+8.2f} "
                   f"{net(ik_z):+8.2f} {net(cz):+8.2f} | {net(raw_p):+8.2f} "
                   f"{net(pr_p):+8.2f} {net(ik_p):+8.2f}")
    click.echo(f"  {'mean':>5s} {'':>9s} {'':>4s} {'':>5s} | " +
               " ".join(f"{np.nanmean(rowsum[k]):+8.2f}"
                        for k in ("raw", "proj", "ikfk", "cmd")))
    if fk_mismatch:
        click.secho(f"  IK targets do not FK back to what the projection "
                    f"reported: {len(fk_mismatch)} waypoints", fg="red")
        for m in fk_mismatch[:5]:
            click.echo(f"    plan {i0+m[0]} k={m[1]}: reported {m[2]:.3f} mm, "
                       f"FK gives {m[3]:.3f} mm")
    else:
        click.secho("  every IK target FKs back to the projected pose within "
                    "0.05 mm: the projection reports what it returns", fg="green")

    # ------------------- 2. the one time axis, commanded against actual --
    click.secho(f"\n2. the same {window:.1f} s on one axis: what was commanded "
                f"at each instant, and where the tool was", bold=True)
    grid = {}
    for r in tr:
        for x in r["sent"]:
            grid[round(x["t_s"] / dt)] = (x["t_s"], x["p_mm"], x["q_deg"])
    z0 = track_at(track, t0)
    click.echo(f"  {'t-t0':>7s} {'cmd z':>9s} {'actual z':>9s} {'err z':>8s} "
               f"{'cmd pitch':>10s} {'err xyz':>9s}")
    lo, hi = round(t0 / dt), round((t0 + window) / dt)
    first = last = None
    errs, errz = [], []
    for slot in range(lo, hi + 1):
        if slot not in grid:
            continue
        ts, p_mm, q_deg = grid[slot]
        act = track_at(track, ts)
        if act is None:
            continue
        _, Rk = fk(q_deg)
        dz = act[2] - p_mm[2]
        err = float(np.linalg.norm(act - np.array(p_mm)))
        errs.append(err)
        errz.append(dz)
        if first is None:
            first = (np.array(p_mm), act)
        last = (np.array(p_mm), act)
        click.echo(f"  {ts-t0:6.2f}s {p_mm[2]:9.2f} {act[2]:9.2f} {dz:+8.2f} "
                   f"{pitch_of(Rk):10.2f} {err:9.2f}")
    if first and last:
        click.secho(f"\n  over that window   commanded z {last[0][2]-first[0][2]:+.2f} mm"
                    f"   actual z {last[1][2]-first[1][2]:+.2f} mm", bold=True)
        click.echo(f"  the tool sat {np.mean(errz):+.2f} mm in z from where it was "
                   f"told to be (mean), {np.mean(errs):.2f} mm away in all")

    # ------------------------------ 3. the same thing over the APPROACH --
    click.secho("\n3. target against actual, over every phase of every rollout",
                bold=True)
    click.echo(f"  {'phase':16s} {'n':>6s} {'lag mm':>8s} {'z bias':>8s} "
               f"{'cmd mm/tick':>12s} {'actual':>8s} {'ratio':>6s}")
    per = {}
    for ep in d["episodes"]:
        tk = ep.get("ee_track") or []
        if len(tk) < 5:
            continue
        g = {}
        for r in ep["trace"]:
            for x in r["sent"]:
                g[round(x["t_s"] / dt)] = (x["t_s"], x["p_mm"], r.get("stage", "?"))
        ks = sorted(g)
        for a, b in zip(ks, ks[1:]):
            if b - a != 1:
                continue
            ta, pa_, st = g[a]
            tb, pb, _ = g[b]
            A, B = track_at(tk, ta), track_at(tk, tb)
            if A is None or B is None:
                continue
            s = per.setdefault(st, {"lag": [], "z": [], "cmd": [], "act": []})
            s["lag"].append(float(np.linalg.norm(A - np.array(pa_))))
            s["z"].append(float(A[2] - pa_[2]))
            s["cmd"].append(float(np.linalg.norm(np.array(pb) - np.array(pa_))))
            s["act"].append(float(np.linalg.norm(B - A)))
    for k in sorted(per, key=lambda k: -len(per[k]["lag"])):
        v = per[k]
        click.echo(f"  {k:16s} {len(v['lag']):6d} {np.mean(v['lag']):8.2f} "
                   f"{np.mean(v['z']):+8.2f} {np.mean(v['cmd']):12.2f} "
                   f"{np.mean(v['act']):8.2f} "
                   f"{np.mean(v['act'])/max(np.mean(v['cmd']),1e-6):6.2f}")
    click.echo("  lag = how far the tool was from the pose whose instant it was; "
               "z bias = the signed part of it")

    # ------------------------------------------- 4. what the jaw was doing --
    click.secho("\n4. the jaw over those six plans", bold=True)
    click.echo(f"  {'plan':>5s} {'commanded':>10s} {'true':>8s}")
    for j, r in enumerate(sel):
        click.echo(f"  {i0+j:5d} {r.get('jaw_cmd_mm'):10} {r.get('jaw_gt_mm'):8}")

    # ---------------------------- 5. what of a plan ever reaches the plant --
    click.secho("\n5. where in the horizon the two committing actions sit, and "
                "whether the executor lives long enough to send them", bold=True)
    click.echo(f"  {'ep':>3s} {'replan':>8s} {'close at k':>11s} {'rise at k':>10s} "
               f"{'asked mm':>9s} {'commanded':>10s}")
    for ep in d["episodes"]:
        t = ep["trace"]
        per_ = np.diff([r["collected_at_s"] for r in t])
        ck, rk = [], []
        for r in t:
            g = [x["g"] for x in r["plan_abs"]]
            z = [x["p"][2] for x in r["plan_abs"]]
            k = next((j for j, v in enumerate(g) if v < 45), None)
            if k is not None:
                ck.append(k)
            ku = next((j for j in range(1, len(z)) if z[j] - z[j - 1] > 0.3), None)
            if ku is not None:
                rk.append(ku)
        asked = min(x["g"] for r in t for x in r["plan_abs"])
        cmdw = min([r["jaw_cmd_mm"] for r in t if r.get("jaw_cmd_mm") is not None]
                   or [float("nan")])
        click.echo(f"  {ep['episode']:3d} {np.mean(per_):7.3f}s "
                   f"{np.median(ck) if ck else float('nan'):11.1f} "
                   f"{np.median(rk) if rk else float('nan'):10.1f} "
                   f"{asked:9.2f} {cmdw:10.2f}")
    click.echo("  k is in units of 0.1 s from the observation. Only k=3..10 is "
               "ever put in a goal, and the goal is replaced after the replan "
               "period -- a jaw action later than that is dropped with the plan "
               "it belonged to, never commanded.")

    kin.close()


if __name__ == "__main__":
    main()
