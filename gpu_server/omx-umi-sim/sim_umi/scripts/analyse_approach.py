"""Why does the approach take 580 ticks when the expert takes 72?

    python sim_umi/scripts/analyse_approach.py --rollout .../rollout_ep40.json

Three things would explain it and they call for different fixes, so they have
to be told apart:

    undertrained     the policy moves the right way, just not far enough --
                     small steps in a consistent direction
    oscillation      the steps are not small, they cancel: the tool goes back
                     and forth and the distance to the ball stops falling
    the grasp itself the tool arrives but shuts at the wrong place or the
                     wrong moment, and then does not try to lift

So this reports, for each: how far a commanded step actually moves against the
expert's own step at the same phase, whether the distance from the tool to the
ball keeps closing, where the tool was when the jaw began to shut, and which
way the chunk points once it has shut.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"

import click
import numpy as np


def expert_steps():
    """How far the expert's tool moves in one tick, by phase."""
    out = {}
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        pos, st = d["eef_pos"], d["stage"]
        step = np.linalg.norm(np.diff(pos, axis=0), axis=1) * 1000
        for s, v in zip(st[:-1], step):
            out.setdefault(str(s), []).append(float(v))
    return {k: np.array(v) for k, v in out.items()}


def policy_steps(eps):
    """The same, from the per-tick TCP targets the projection produced."""
    out = {}
    for e in eps:
        for r in e["trace"]:
            t = r.get("targets_mm") or []
            if len(t) < 2:
                continue
            a = np.asarray(t, float)
            for v in np.linalg.norm(np.diff(a, axis=0), axis=1):
                out.setdefault(r["stage"], []).append(float(v))
    return {k: np.array(v) for k, v in out.items()}


def table(name, d):
    click.secho(f"\n  {name}", bold=True)
    click.echo(f"    {'phase':16s} {'n':>7s} {'mean':>8s} {'median':>8s} {'p95':>8s}")
    for k in sorted(d, key=lambda k: -len(d[k])):
        v = d[k]
        if len(v) < 5:
            continue
        click.echo(f"    {k:16s} {len(v):7d} {v.mean():8.2f} "
                   f"{np.median(v):8.2f} {np.percentile(v, 95):8.2f}")


@click.command()
@click.option("--rollout", "rollout_path", required=True)
@click.option("--open-loop-log", default=None,
              help="the eval_policy_offline log, for the per-step table")
def main(rollout_path, open_loop_log):
    d = json.load(open(rollout_path))
    eps = d["episodes"]
    click.secho(f"{pathlib.Path(rollout_path).name}: {len(eps)} rollouts", bold=True)

    # ---------------------------------------------------- 1. step lengths --
    click.secho("\n1. how far one tick moves the tool (mm)", bold=True)
    table("the expert", expert_steps())
    table("the policy", policy_steps(eps))

    # ------------------------------------------ 2. does the gap keep closing --
    click.secho("\n2. distance from the tool to the ball, tick by tick", bold=True)
    for e in eps:
        tr = [r for r in e["trace"] if r.get("tcp_to_ball_mm") is not None]
        if len(tr) < 4:
            click.echo(f"  rollout {e['episode']}: too short to say")
            continue
        dist = np.array([r["tcp_to_ball_mm"] for r in tr])
        tick = np.array([r["tick"] for r in tr])
        # is it falling, or moving about without getting closer?
        closing = np.diff(dist)
        click.echo(f"  rollout {e['episode']}: {dist[0]:7.1f} -> {dist.min():7.1f} mm "
                   f"(closest at tick {tick[int(np.argmin(dist))]:3d} of {tick[-1]}), "
                   f"ends {dist[-1]:7.1f}")
        click.echo(f"      of {len(closing)} chunks, {int((closing < -1).sum())} "
                   f"closed in, {int((closing > 1).sum())} backed off, "
                   f"{int((np.abs(closing) <= 1).sum())} went nowhere")

    # --------------------------------------- 3. where the jaw began to shut --
    click.secho("\n3. the tool when the jaw began to shut", bold=True)
    any_close = False
    for e in eps:
        tr = e["trace"]
        idx = next((i for i, r in enumerate(tr)
                    if r.get("jaw_cmd_mm", 99) < 40.0), None)
        if idx is None:
            click.echo(f"  rollout {e['episode']}: the jaw was never commanded shut")
            continue
        any_close = True
        r = tr[idx]
        click.echo(f"  rollout {e['episode']}: tick {r['tick']}, "
                   f"XY off by {r.get('tcp_to_ball_xy_mm')} mm, "
                   f"Z above the ball by {r.get('tcp_to_ball_z_mm')} mm, "
                   f"jaw commanded {r['jaw_cmd_mm']} mm (true {r.get('jaw_gt_mm')})")
        # ------------------------------ 4. does it then try to lift? --
        after = tr[idx:idx + 6]
        ups = [np.mean(a["chunk_dz_mm"]) for a in after if a.get("chunk_dz_mm")]
        if ups:
            click.echo(f"      the six chunks from there ask for a mean z of "
                       f"{np.mean(ups):+7.2f} mm "
                       f"({int(sum(u > 0 for u in ups))}/{len(ups)} upward)")
    if not any_close:
        click.secho("  the jaw never closed in any rollout: the approach never "
                    "finished, so the grasp cannot be the thing that is wrong",
                    fg="yellow")

    # ------------------------------------------- 5. the open-loop by step --
    if open_loop_log:
        click.secho("\n5. open-loop error by step of the 16-step horizon", bold=True)
        txt = pathlib.Path(open_loop_log).read_text().splitlines()
        i = next((k for k, l in enumerate(txt) if "by step of the" in l), None)
        if i is None:
            click.secho("  not in that log", fg="yellow")
        else:
            for l in txt[i:i + 19]:
                click.echo("  " + l.strip())


if __name__ == "__main__":
    main()
