"""Everything a rolling-horizon rollout can be asked afterwards.

    python sim_umi/scripts/analyse_rolling.py --rollout .../rollout_e60_prefix.json

The old analyses were written against an executor that sent a chunk, waited
for it to finish and then thought about the next one, and they matched two
plans by index because the index was the only thing that lined up. The
executor now puts an absolute time on every action -- obs_t + k*dt -- so two
plans overlap wherever their timestamps agree, and that is what is matched
here. No off-by-one is assumed in either direction; it is read off the
contract the actions carry.

What the tool was asked to do and what it did are four different numbers and
they are reported separately: the raw prediction, the same after projection
onto the five axes the arm has, the stream of waypoints actually commanded
across chunk boundaries, and the tool as it actually moved. Each one loses
something, and which one loses it says whose problem it is.
"""
import gzip
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"

import click
import numpy as np


def load(p):
    p = pathlib.Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return json.load(f)


def geodesic(a, b):
    R = np.asarray(a).reshape(3, 3).T @ np.asarray(b).reshape(3, 3)
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def expert_steps():
    out = {}
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        step = np.linalg.norm(np.diff(d["eef_pos"], axis=0), axis=1) * 1000
        for s, v in zip(d["stage"][:-1], step):
            out.setdefault(str(s), []).append(float(v))
    return {k: np.array(v) for k, v in out.items()}


def resample(track, dt):
    """The tool's position on a regular grid, from the joint-state stream."""
    if len(track) < 3:
        return np.zeros((0,)), np.zeros((0, 3))
    a = np.asarray(track, float)
    t, xyz = a[:, 0], a[:, 1:]
    grid = np.arange(t[0], t[-1], dt)
    return grid, np.stack([np.interp(grid, t, xyz[:, i]) for i in range(3)], 1)


@click.command()
@click.option("--rollout", "rollout_path", required=True)
@click.option("--dt", default=0.1, type=float)
def main(rollout_path, dt):
    d = load(rollout_path)
    eps = d["episodes"]
    click.secho(f"{pathlib.Path(rollout_path).name}: {len(eps)} rollouts, "
                f"{d.get('horizon_steps')} waypoints in flight", bold=True)

    # ------------------------------------------------ 1. how far each got --
    click.secho("\n1. how far the task got", bold=True)
    click.echo(f"  {'ep':>3s} {'furthest':>15s} {'jaw shut':>9s} {'held':>6s} "
               f"{'in bin':>7s} {'ticks':>6s}  stopped because")
    tally = {"GRASP": 0, "jaw": 0, "held": 0, "LIFT": 0, "place": 0}
    for e in eps:
        tr = e["trace"]
        shut = any(r.get("jaw_gt_mm", 99) < 45 for r in tr)
        got = e["stage_ticks"]
        if "GRASP" in got or e["furthest_stage"] in ("GRASP",):
            tally["GRASP"] += 1
        elif any(s in got for s in ("LIFT", "SEARCH_BIN", "TRANSPORT", "PLACE")):
            tally["GRASP"] += 1
        tally["jaw"] += bool(shut)
        tally["held"] += bool(e["grasped"])
        tally["LIFT"] += bool("LIFT" in got)
        tally["place"] += bool(e["success"])
        click.echo(f"  {e['episode']:3d} {e['furthest_stage']:>15s} "
                   f"{'yes' if shut else 'no':>9s} "
                   f"{'yes' if e['grasped'] else 'no':>6s} "
                   f"{'yes' if e['success'] else 'no':>7s} {e['steps']:6d}  "
                   f"{e['stopped_because']}")
    n = len(eps)
    click.secho(f"\n  GRASP reached {tally['GRASP']}/{n}   jaw actually shut "
                f"{tally['jaw']}/{n}   object held {tally['held']}/{n}   "
                f"LIFT {tally['LIFT']}/{n}   in the bin {tally['place']}/{n}",
                bold=True)

    # --------------------------------- 2. the four mm/tick, by phase --
    click.secho("\n2. mm of tool motion per 0.1 s tick, at four places", bold=True)
    raw, proj, cmd, act = {}, {}, {}, {}
    for e in eps:
        stream = []          # every commanded waypoint, in time order
        for r in e["trace"]:
            st = r.get("stage", "?")
            pa = r.get("plan_abs") or []
            if len(pa) > 1:
                p = np.array([x["p"] for x in pa])
                raw.setdefault(st, []).extend(
                    np.linalg.norm(np.diff(p, axis=0), axis=1).tolist())
            sent = r.get("sent") or []
            if len(sent) > 1:
                p = np.array([x["p_mm"] for x in sent])
                proj.setdefault(st, []).extend(
                    np.linalg.norm(np.diff(p, axis=0), axis=1).tolist())
            for x in sent:
                # one slot per action instant. A new goal replaces the old, so
                # where two plans both name an instant the later one is what
                # the controller follows -- pairing them as consecutive points
                # divided by a near-zero time gap is how the commanded figure
                # came out at 8 mm/tick, four times the projected one.
                stream.append((round(x["t_s"] / dt), x["p_mm"], st))
        grid_cmd = {}
        for slot, p_mm, st in stream:
            grid_cmd[slot] = (p_mm, st)
        keys = sorted(grid_cmd)
        for a, b in zip(keys, keys[1:]):
            if b - a != 1:
                continue
            step = float(np.linalg.norm(np.array(grid_cmd[b][0])
                                        - np.array(grid_cmd[a][0])))
            cmd.setdefault(grid_cmd[a][1], []).append(step)
        # what the tool actually did, put on the phase that was running
        grid, xyz = resample(e.get("ee_track") or [], dt)
        if len(grid) > 2:
            marks = [(r["obs_t_s"], r.get("stage", "?")) for r in e["trace"]
                     if r.get("stage")]
            step = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
            for t, v in zip(grid[:-1], step):
                st = "?"
                for ts, s_ in marks:
                    if ts <= t:
                        st = s_
                    else:
                        break
                act.setdefault(st, []).append(float(v))
    exp = expert_steps()
    click.echo(f"  {'phase':16s} {'expert':>8s} {'raw':>8s} {'projected':>10s} "
               f"{'commanded':>10s} {'actual':>8s}   {'n raw':>7s}")
    for st in sorted(raw, key=lambda k: -len(raw[k])):
        def m(dd):
            v = dd.get(st)
            return f"{np.mean(v):8.2f}" if v else f"{'-':>8s}"
        ev = exp.get(st)
        click.echo(f"  {st:16s} {np.mean(ev) if ev is not None else float('nan'):8.2f} "
                   f"{m(raw)} {m(proj):>10s} {m(cmd):>10s} {m(act)}   "
                   f"{len(raw[st]):7d}")
    allr = [v for g in raw.values() for v in g]
    alla = [v for g in act.values() for v in g]
    click.secho(f"  over everything: raw {np.mean(allr):.2f}, actual "
                f"{np.mean(alla) if alla else float('nan'):.2f} mm/tick", bold=True)

    # ------------------------------------- 3. what the arm could reach --
    click.secho("\n3. what the arm could reach of what was asked", bold=True)
    click.echo(f"  {'ep':>3s} {'plans':>6s} {'P1 ok':>7s} {'prefix mean':>12s} "
               f"{'median':>7s} {'prefix<=2':>10s} {'waypoints ok':>13s}")
    for e in eps:
        tr = e["trace"]
        pre = np.array([r["valid_prefix"] for r in tr])
        p1 = [r["attempts"][0]["reachable"] for r in tr if r.get("attempts")]
        click.echo(f"  {e['episode']:3d} {len(tr):6d} "
                   f"{np.mean(p1)*100 if p1 else float('nan'):6.1f}% "
                   f"{pre.mean():12.2f} {np.median(pre):7.1f} "
                   f"{(pre <= 2).mean()*100:9.1f}% "
                   f"{e['ik_reachable_rate']*100:12.1f}%")
    allpre = np.array([r["valid_prefix"] for e in eps for r in e["trace"]])
    click.secho(f"  all: prefix mean {allpre.mean():.2f}, median "
                f"{np.median(allpre):.0f}, prefix<=2 in "
                f"{(allpre<=2).mean()*100:.1f}% of {len(allpre)} plans", bold=True)
    click.echo("  where the prefix ended, over all plans:")
    click.echo("    " + "  ".join(f"{k}:{int((allpre==k).sum())}" for k in range(9)))
    fb = [r["first_unreachable_k"] for e in eps for r in e["trace"]
          if r["first_unreachable_k"] is not None]
    if fb:
        h = np.bincount(fb, minlength=17)
        click.echo("  first unreachable k: " +
                   "  ".join(f"{k}:{int(h[k])}" for k in range(17) if h[k]))

    # ------------------------------ 4. plans that go nowhere or backwards --
    click.secho("\n4. plans that go nowhere, and plans that back off", bold=True)
    click.echo(f"  {'ep':>3s} {'stationary':>11s} {'retreating':>11s} "
               f"{'closing':>9s}")
    for e in eps:
        tr = e["trace"]
        net = [float(np.linalg.norm(np.array(r["plan_abs"][-1]["p"])
                                    - np.array(r["plan_abs"][0]["p"])))
               for r in tr if len(r.get("plan_abs") or []) > 1]
        stat = float(np.mean([v < 5.0 for v in net])) if net else float("nan")
        dist = [r.get("tcp_to_ball_mm") for r in tr]
        dist = [v for v in dist if v is not None]
        back = clos = 0
        for a, b in zip(dist, dist[1:]):
            if b - a > 1:
                back += 1
            elif a - b > 1:
                clos += 1
        tot = max(len(dist) - 1, 1)
        click.echo(f"  {e['episode']:3d} {stat*100:10.1f}% {back/tot*100:10.1f}% "
                   f"{clos/tot*100:8.1f}%")
    click.echo("  stationary = the 16-step plan's endpoint within 5 mm of its "
               "start; retreating = the tool-to-ball distance grew between "
               "one plan and the next")

    # ------------------------------------------ 5. the grasp, if it came --
    click.secho("\n5. where the tool was when the jaw shut, and what came next",
                bold=True)
    any_shut = False
    for e in eps:
        tr = e["trace"]
        i = next((k for k, r in enumerate(tr) if r.get("jaw_gt_mm", 99) < 45), None)
        if i is None:
            click.echo(f"  rollout {e['episode']}: the jaw never shut")
            continue
        any_shut = True
        r = tr[i]
        click.echo(f"  rollout {e['episode']}: tick {r.get('tick')}, XY off by "
                   f"{r.get('tcp_to_ball_xy_mm')} mm, Z above the ball by "
                   f"{r.get('tcp_to_ball_z_mm')} mm, jaw {r.get('jaw_gt_mm')} mm")
        ups = [float(np.sum(a["chunk_dz_mm"])) for a in tr[i:i + 6]
               if a.get("chunk_dz_mm")]
        if ups:
            click.echo(f"      the six plans from there ask for "
                       f"{np.mean(ups):+.2f} mm of z over the horizon "
                       f"({sum(u > 0 for u in ups)}/{len(ups)} upward)")
        grid, xyz = resample(e.get("ee_track") or [], dt)
        if len(grid) > 2:
            t0 = r["obs_t_s"]
            w = (grid >= t0) & (grid <= t0 + 1.5)
            if w.sum() > 2:
                z = xyz[w, 2]
                click.echo(f"      the tool actually moved {z[-1]-z[0]:+.2f} mm "
                           f"in z over the 1.5 s after that")
    if not any_shut:
        click.secho("  no rollout closed the jaw", fg="yellow")

    # ------------------------- 6. does a plan agree with the one before it --
    click.secho("\n6. two consecutive plans, over the time they both describe",
                bold=True)
    per = {}
    for e in eps:
        tr = [r for r in e["trace"] if r.get("plan_abs")]
        for a, b in zip(tr, tr[1:]):
            A = {round(x["t_s"] / dt): x for x in a["plan_abs"]}
            dp, dr, dg, jump = [], [], [], None
            for x in b["plan_abs"]:
                o = A.get(round(x["t_s"] / dt))
                if o is None:
                    continue
                v = float(np.linalg.norm(np.array(o["p"]) - np.array(x["p"])))
                dp.append(v)
                dr.append(geodesic(o["R"], x["R"]))
                dg.append(abs(o["g"] - x["g"]))
                if jump is None:
                    jump = v
            if len(dp) < 2:
                continue
            s = per.setdefault(a.get("stage", "?"),
                               {"p": [], "r": [], "g": [], "j": [], "n": []})
            s["p"] += dp
            s["r"] += dr
            s["g"] += dg
            s["j"].append(jump)
            s["n"].append(len(dp))
    click.echo(f"  {'phase':16s} {'pairs':>6s} {'shared':>7s} {'pos mean':>9s} "
               f"{'pos p95':>8s} {'rot mean':>9s} {'grip':>7s} {'jump':>8s}")
    for k in sorted(per, key=lambda k: -len(per[k]["j"])):
        v = per[k]
        click.echo(f"  {k:16s} {len(v['j']):6d} {np.mean(v['n']):7.1f} "
                   f"{np.mean(v['p']):8.2f}mm {np.percentile(v['p'],95):7.2f}mm "
                   f"{np.mean(v['r']):8.2f}d {np.mean(v['g']):6.2f}mm "
                   f"{np.mean(v['j']):7.2f}mm")
    click.echo("  matched by the absolute timestamp each action carries, not "
               "by index. The expert's two plans would agree exactly: they are "
               "cut from the one trajectory it flew.")


if __name__ == "__main__":
    main()
