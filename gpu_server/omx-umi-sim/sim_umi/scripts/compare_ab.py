"""Two checkpoints, the same placements, the eight things that decide it.

    python sim_umi/scripts/compare_ab.py --runs "clean e60=a.json,+v2 step5986=b.json"

The question is whether filling the state support changed the closed-loop
behaviour, and the answer is not "did it put the ball in the bin" -- nothing
does that yet. It is whether the arm still parks at twenty-eight degrees and
closes on empty air twenty millimetres short.

So the metrics are the ones the failure was diagnosed with: how long the tool
sits in the pitch band the demonstrations only ever pass through, whether it
ever gets the nose down to where the expert grasps, whether it reaches the
corridor at all, the geometry at the moment the jaw shuts, and only then
whether anything was held or lifted.

Ground truth is used throughout and only here: this reads finished logs.
"""
import gzip
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "scripts"))

import click
import numpy as np

TRAP = (25.0, 32.0)
GRASP_PITCH = 20.0
HOLD = ("LIFT", "TRANSPORT", "SEARCH_BIN")


def load(p):
    p = pathlib.Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return json.load(f)


def episodes(paths):
    out, cols = [], None
    for p in paths:
        d = load(p)
        cols = cols or d.get("ee_track_columns")
        out += d["episodes"]
    return out, cols


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


@click.command()
@click.option("--runs", required=True,
              help="label=file[;file] pairs, comma separated")
def main(runs):
    from analyse_grasp_corridor import corridor, inside, badness
    import mujoco
    from collector import Collector
    from scene import SceneConfig, write_scene

    c = corridor()
    kin = Collector(str(write_scene(SceneConfig())), cfg=SceneConfig(), render=False)

    def fk(q):
        d = kin._ik
        d.qpos[:] = kin.data.qpos
        for a, v in zip(kin.arm_qadr, np.radians(q)):
            d.qpos[a] = v
        mujoco.mj_kinematics(kin.model, d)
        return (d.site_xpos[kin.tcp_sid].copy() * 1000,
                np.asarray(d.site_xmat[kin.tcp_sid]).reshape(3, 3).copy())

    rows = []
    for spec in runs.split(","):
        label, files = spec.split("=", 1)
        eps, cols = episodes(files.split(";"))
        iq, ib = cols.index("j1_deg"), cols.index("ball_x_mm")
        r = {"label": label.strip(), "n": len(eps), "trap": [], "below20": 0,
             "corridor": 0, "close": [], "secure": 0, "lift": 0, "ticks": []}
        for e in eps:
            tk = [x for x in e["ee_track"] if x[ib] is not None]
            if not tk:
                continue
            T = np.array([x[0] for x in tk])
            P, D, S, B = [], [], [], []
            prev = None
            for x in tk:
                p_, R_ = fk(x[iq:iq + 5])
                off = R_.T @ (np.array(x[ib:ib + 3]) - p_)
                P.append(pitch_of(R_))
                D.append(off)
                S.append(0.0 if prev is None else float(np.linalg.norm(p_ - prev)))
                B.append(np.array(x[ib:ib + 3]))
                prev = p_
            P, D, S = np.array(P), np.array(D), np.array(S)
            dt = float(np.median(np.diff(T))) if len(T) > 2 else 0.05
            r["trap"].append(float(((P >= TRAP[0]) & (P < TRAP[1])).sum() * dt))
            r["below20"] += int((P < GRASP_PITCH).any())
            r["corridor"] += int(any(inside(c, D[k], P[k]) for k in range(len(P))))
            r["ticks"].append(e["steps"])
            # the moment the jaw first reads shut
            jl = e.get("jaw_log") or []
            cl = [x for x in jl if x["actual_width_mm"] < 49.0]
            if cl:
                t0 = cl[0]["t_fired_s"]
                k = int(np.argmin(np.abs(T - t0)))
                r["close"].append((D[k][0], D[k][1], D[k][2], P[k],
                                   float(S[max(k - 3, 0):k + 1].mean()) / max(dt, 1e-9) * 0.1))
            # secure grasp, from the ball
            ks = [i for i, x in enumerate(e["trace"]) if x.get("stage") in HOLD]
            ball = np.array(B)
            ball_r = 25.0
            held = ball[:, 2].max() > ball_r + 20.0
            if held:
                r["lift"] += 1
                w = ball[:, 2] > ball_r + 20.0
                off = D[w]
                if len(off) > 5 and float(np.abs(off - off.mean(0)).max()) < 6.0:
                    r["secure"] += 1
        rows.append(r)
    kin.close()

    click.secho("the eight things, on the same placements", bold=True)
    click.echo(f"  {'':34s}" + "".join(f"{r['label']:>22s}" for r in rows))
    def line(name, fn):
        click.echo(f"  {name:34s}" + "".join(f"{fn(r):>22s}" for r in rows))
    line("1 time parked at 25-32 deg (s)",
         lambda r: f"{np.mean(r['trap']):.1f} +- {np.std(r['trap']):.1f}")
    line("2 reached pitch < 20 deg",
         lambda r: f"{r['below20']}/{r['n']}")
    line("3 entered the grasp corridor",
         lambda r: f"{r['corridor']}/{r['n']}")
    for i, (lab, j) in enumerate((("4 lateral at close (mm)", 0),
                                  ("5 depth at close (mm)", 1),
                                  ("  vertical at close (mm)", 2))):
        line(lab, lambda r, j=j: (f"{np.mean([x[j] for x in r['close']]):+.2f}"
                                  if r["close"] else "no close"))
    line("6 pitch at close (deg)",
         lambda r: (f"{np.mean([x[3] for x in r['close']]):+.2f}"
                    if r["close"] else "no close"))
    line("  EE speed at close (mm/tick)",
         lambda r: (f"{np.mean([x[4] for x in r['close']]):.2f}"
                    if r["close"] else "no close"))
    line("7 GT secure grasp", lambda r: f"{r['secure']}/{r['n']}")
    line("8 LIFT (ball off the table)", lambda r: f"{r['lift']}/{r['n']}")
    line("  ticks run", lambda r: f"{np.mean(r['ticks']):.0f}")
    click.echo(f"\n  the expert closes at lateral -0.62, depth -22.62, "
               f"vertical +4.30 mm, pitch +12.57 deg, 0.15 mm/tick")


if __name__ == "__main__":
    main()
