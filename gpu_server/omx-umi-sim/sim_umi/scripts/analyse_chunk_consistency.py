"""Does the policy keep agreeing with the plan it made a moment ago?

    python sim_umi/scripts/analyse_chunk_consistency.py --rollout .../rollout_e40.json

The policy plans sixteen steps, four of them are executed, and then it plans
again. Nothing in the training objective asks the second plan to agree with
the first: each chunk was fitted to a demonstration on its own. So the two can
disagree, and if they disagree enough the arm spends its time being pulled in
one direction and then another, which would show up as an approach that takes
hundreds of ticks while covering the distance the expert covers in seventy.

Both plans are decoded into the arm's own frame, where they can be laid over
each other. The old plan from step K onward and the new plan up to its last K
describe the same stretch of time, so the disagreement between them is the
measurement. The jump is reported separately: how far the first action of the
new plan sits from the action the old plan had for that same instant.

The expert is perfectly consistent by construction -- its plan at t and its
plan at t+K are both cut from the one trajectory it actually flew, so they
agree exactly. That is the reference: a demonstration has no replanning noise
at all, and whatever the policy shows here is entirely its own. What the
expert does give is the scale -- how far the tool really travels over the
overlap -- so the disagreement can be read against the motion it is supposed
to describe.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"

import click
import numpy as np


def geodesic(Ra, Rb):
    R = Ra.T @ Rb
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def expert_scale(horizon, K):
    """How far the expert's tool moves over the overlap, by phase."""
    out = {}
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        pos, st = d["eef_pos"], d["stage"]
        n = len(pos)
        for t in range(n - horizon - K):
            seg = pos[t + K:t + horizon]
            out.setdefault(str(st[t]), []).append(
                float(np.linalg.norm(seg[-1] - seg[0])) * 1000)
    return {k: np.array(v) for k, v in out.items()}


@click.command()
@click.option("--rollout", "rollout_path", required=True)
@click.option("--horizon", default=16, type=int)
def main(rollout_path, horizon):
    d = json.load(open(rollout_path))
    eps = d["episodes"]
    K = d.get("exec_steps", 4)

    per = {}
    for e in eps:
        tr = [r for r in e["trace"] if r.get("plan_abs")]
        for a, b in zip(tr, tr[1:]):
            # Derived, not assumed. sampler.py takes the action chunk as
            # input_arr[current_idx : ...] while the observation window ends at
            # current_idx, so action[0] IS the pose at the observation instant
            # -- measured on the training set, 0.000034 mm from it. Plan P made
            # at t therefore has P[k] at t + k*dt. Executing P[0..K-1] leaves
            # the arm at instant t+(K-1)*dt, which is where the next
            # observation is taken, so the new plan Q has Q[j] = P[K-1+j].
            # The overlap is P[K-1:] against Q[:17-K], not P[K:] against Q[:-K].
            k = a.get("executed", K) - 1
            if k <= 0 or k >= horizon:
                continue
            old, new = a["plan_abs"], b["plan_abs"]
            m = min(len(old) - k, len(new))
            if m < 2:
                continue
            dp, dr, dg = [], [], []
            for i in range(m):
                o, nw = old[k + i], new[i]
                dp.append(float(np.linalg.norm(np.array(o["p"]) - np.array(nw["p"]))))
                dr.append(geodesic(np.array(o["R"]).reshape(3, 3),
                                   np.array(nw["R"]).reshape(3, 3)))
                dg.append(abs(o["g"] - nw["g"]))
            jump_p = float(np.linalg.norm(np.array(old[k]["p"]) - np.array(new[0]["p"])))
            jump_r = geodesic(np.array(old[k]["R"]).reshape(3, 3),
                              np.array(new[0]["R"]).reshape(3, 3))
            s = per.setdefault(a["stage"], {"p": [], "r": [], "g": [],
                                            "jp": [], "jr": []})
            s["p"] += dp
            s["r"] += dr
            s["g"] += dg
            s["jp"].append(jump_p)
            s["jr"].append(jump_r)

    click.secho(f"{pathlib.Path(rollout_path).name}: {len(eps)} rollouts, "
                f"{K} of {horizon} actions executed per plan; action[0] is the "
                f"current pose, so the overlap is old[{K-1}:] against new[:{17-K}]",
                bold=True)
    if not per:
        click.secho("  no plans were stored -- re-run the rollout with the "
                    "version that records them", fg="red")
        return

    scale = expert_scale(horizon, K)
    click.secho("\nthe old plan from step K on, against the new plan's start",
                bold=True)
    click.echo(f"  {'phase':16s} {'pairs':>6s} {'pos mean':>9s} {'pos p95':>8s} "
               f"{'rot mean':>9s} {'rot p95':>8s} {'grip mean':>10s}")
    for k in sorted(per, key=lambda k: -len(per[k]["jp"])):
        v = per[k]
        click.echo(f"  {k:16s} {len(v['jp']):6d} {np.mean(v['p']):8.2f}mm "
                   f"{np.percentile(v['p'], 95):7.2f}mm "
                   f"{np.mean(v['r']):8.2f}d {np.percentile(v['r'], 95):7.2f}d "
                   f"{np.mean(v['g']):9.2f}mm")

    click.secho("\nthe jump: the new plan's first action against the old "
                "plan's action for that same instant", bold=True)
    click.echo(f"  {'phase':16s} {'n':>6s} {'pos mean':>9s} {'pos p95':>8s} "
               f"{'rot mean':>9s}")
    for k in sorted(per, key=lambda k: -len(per[k]["jp"])):
        v = per[k]
        click.echo(f"  {k:16s} {len(v['jp']):6d} {np.mean(v['jp']):8.2f}mm "
                   f"{np.percentile(v['jp'], 95):7.2f}mm {np.mean(v['jr']):8.2f}d")

    click.secho("\nread against the motion it is supposed to describe", bold=True)
    click.echo(f"  {'phase':16s} {'expert travel':>14s} {'policy disagreement':>20s}"
               f" {'ratio':>7s}")
    for k in sorted(per, key=lambda k: -len(per[k]["jp"])):
        if k not in scale or len(scale[k]) < 5:
            continue
        trav = float(np.mean(scale[k]))
        dis = float(np.mean(per[k]["p"]))
        click.echo(f"  {k:16s} {trav:13.2f}mm {dis:19.2f}mm {dis/max(trav,1e-6):7.2f}")
    click.secho("\n  the expert's own two plans agree exactly -- they are cut "
                "from the one trajectory it flew -- so all of the above is the "
                "policy's own replanning.", bold=True)


if __name__ == "__main__":
    main()
