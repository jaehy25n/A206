"""Did the tool ever stand where the expert stands when it closes?

    python sim_umi/scripts/analyse_grasp_corridor.py --rollout .../geom_ep2_a.json

Watching the video, the arm looks as though it reaches a good grasp pose,
does not close, wanders, and closes later from a worse one -- pushing the ball
aside instead of enclosing it. That is a claim about geometry over time and it
needs the geometry, not the distance.

Euclidean distance will not do. The expert's own grasps are held within
0.61 mm laterally and 0.61 mm in depth of one pose in the TOOL frame, so
"close to the ball" and "in a position to grasp it" are different statements.
The corridor is therefore built from the demonstrations themselves: the ball's
position in the tool frame at the instant each expert's jaw starts to shut,
and through every frame it securely holds afterwards.

The ball's true pose is used, and only here. It reaches no observation and no
command; this runs after the fact, on a finished log.
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

HELD = ["LIFT", "TRANSPORT", "SEARCH_BIN"]


def load(p):
    p = pathlib.Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return json.load(f)


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


def corridor():
    """Where the ball sits, in the tool's own frame, when the expert grasps."""
    onset, held = [], []
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        z = np.load(p, allow_pickle=True)
        st = z["stage"].astype(str)
        ee, R, b = z["eef_pos"], z["eef_rot"], z["eval_ball_pos"]
        w = z["gripper_width"] * 1000
        g = np.where(st == "GRASP")[0]
        if len(g):
            i = next((k for k in g if w[k] < w[g[0]] - 1.0), g[0])
            onset.append((R[i].T @ (b[i] - ee[i]) * 1000, pitch_of(R[i]),
                          float(np.linalg.norm(ee[i] - ee[max(i - 1, 0)]) * 1000)))
        for i in np.where(np.isin(st, HELD))[0]:
            held.append(R[i].T @ (b[i] - ee[i]) * 1000)
    O = np.array([o[0] for o in onset])
    H = np.array(held)
    both = np.vstack([O, H])
    return {"x": (both[:, 0].min(), both[:, 0].max()),
            "y": (both[:, 1].min(), both[:, 1].max()),
            "z": (both[:, 2].min(), both[:, 2].max()),
            "pitch": (min(o[1] for o in onset), max(o[1] for o in onset)),
            "onset": O, "held": H,
            "onset_pitch": np.array([o[1] for o in onset]),
            "onset_speed": np.array([o[2] for o in onset])}


def inside(c, off, pit):
    return (c["x"][0] <= off[0] <= c["x"][1] and c["y"][0] <= off[1] <= c["y"][1]
            and c["z"][0] <= off[2] <= c["z"][1]
            and c["pitch"][0] <= pit <= c["pitch"][1])


def badness(c, off, pit):
    """How far outside the corridor, in mm and degrees, zero when inside."""
    out = 0.0
    for j, k in enumerate("xyz"):
        lo, hi = c[k]
        out += max(0.0, lo - off[j]) + max(0.0, off[j] - hi)
    lo, hi = c["pitch"]
    return out, max(0.0, lo - pit) + max(0.0, pit - hi)


@click.command()
@click.option("--rollout", "rollout_path", required=True)
@click.option("--episode", default=2, type=int)
def main(rollout_path, episode):
    import mujoco
    from collector import Collector
    from scene import SceneConfig, write_scene

    c = corridor()
    click.secho("the expert's grasp corridor, from 20 demonstrations", bold=True)
    click.echo(f"  {'':10s} {'onset mean':>12s} {'onset sd':>9s}   corridor")
    for j, k in enumerate("xyz"):
        lab = {"x": "lateral", "y": "depth", "z": "vertical"}[k]
        click.echo(f"  {lab:10s} {c['onset'][:, j].mean():+11.2f} "
                   f"{c['onset'][:, j].std():9.2f}   "
                   f"[{c[k][0]:+7.2f}, {c[k][1]:+7.2f}] mm")
    click.echo(f"  {'pitch':10s} {c['onset_pitch'].mean():+11.2f} "
               f"{c['onset_pitch'].std():9.2f}   "
               f"[{c['pitch'][0]:+7.2f}, {c['pitch'][1]:+7.2f}] deg")
    click.echo(f"  {'EE speed':10s} {c['onset_speed'].mean():+11.2f} "
               f"{c['onset_speed'].std():9.2f}   mm per tick at the instant it "
               f"shuts -- it has all but stopped")

    d = load(rollout_path)
    e = [x for x in d["episodes"] if x["episode"] == episode][0]
    cols = d.get("ee_track_columns") or []
    if "ball_x_mm" not in cols:
        raise click.ClickException("this log has no ball track; re-run the "
                                   "rollout with the version that records it")
    tk = np.array([[np.nan if v is None else v for v in row]
                   for row in e["ee_track"]], float)
    iq = cols.index("j1_deg")
    ib = cols.index("ball_x_mm")

    scfg = SceneConfig()
    kin = Collector(str(write_scene(scfg)), cfg=scfg, render=False)

    def fk(q_deg):
        dd = kin._ik
        dd.qpos[:] = kin.data.qpos
        for a, v in zip(kin.arm_qadr, np.radians(q_deg)):
            dd.qpos[a] = v
        mujoco.mj_kinematics(kin.model, dd)
        return (dd.site_xpos[kin.tcp_sid].copy() * 1000,
                np.asarray(dd.site_xmat[kin.tcp_sid]).reshape(3, 3).copy())

    rows = []
    for r in tk:
        if np.isnan(r[ib]):
            continue
        p, R = fk(r[iq:iq + 5])
        off = R.T @ (r[ib:ib + 3] - p)
        pit = pitch_of(R)
        pos, rot = badness(c, off, pit)
        rows.append({"t": r[0], "p": p, "R": R, "off": off, "pitch": pit,
                     "out_mm": pos, "out_deg": rot,
                     "inside": inside(c, off, pit),
                     "ball": r[ib:ib + 3].copy()})
    if not rows:
        raise click.ClickException("no samples with a ball position")
    t0 = rows[0]["t"]

    # ------------------------------------------------ when the jaw shut --
    jl = e.get("jaw_log") or []
    closing = [x for x in jl if x["actual_width_mm"] < 49.0]
    t_close = closing[0]["t_fired_s"] if closing else None
    t_hard = (min(jl, key=lambda x: x["actual_width_mm"])["t_fired_s"]
              if jl else None)
    w_hard = min((x["actual_width_mm"] for x in jl), default=float("nan"))

    click.secho(f"\nthe rollout, {len(rows)} samples over "
                f"{rows[-1]['t']-t0:.1f} s", bold=True)
    ins = [r for r in rows if r["inside"]]
    best = min(rows, key=lambda r: r["out_mm"] + r["out_deg"])
    near = min(rows, key=lambda r: abs(r["off"][0]) + abs(r["off"][1] + 19.8))
    click.echo(f"  frames inside the corridor: {len(ins)} of {len(rows)}")
    if ins:
        click.echo(f"  first entry at t+{ins[0]['t']-t0:.2f}s, last at "
                   f"t+{ins[-1]['t']-t0:.2f}s")
    click.echo(f"  closest approach to it at t+{best['t']-t0:.2f}s: "
               f"lateral {best['off'][0]:+.2f}, depth {best['off'][1]:+.2f}, "
               f"vertical {best['off'][2]:+.2f} mm, pitch {best['pitch']:+.2f} deg "
               f"-> {best['out_mm']:.2f} mm and {best['out_deg']:.2f} deg outside")
    if t_close:
        rc = min(rows, key=lambda r: abs(r["t"] - t_close))
        click.echo(f"  the jaw first reads shut at t+{t_close-t0:.2f}s: "
                   f"lateral {rc['off'][0]:+.2f}, depth {rc['off'][1]:+.2f}, "
                   f"vertical {rc['off'][2]:+.2f} mm, pitch {rc['pitch']:+.2f} deg "
                   f"-> {rc['out_mm']:.2f} mm outside")
    if t_hard:
        rh = min(rows, key=lambda r: abs(r["t"] - t_hard))
        click.echo(f"  narrowest at t+{t_hard-t0:.2f}s ({w_hard:.1f} mm): "
                   f"lateral {rh['off'][0]:+.2f}, depth {rh['off'][1]:+.2f}, "
                   f"vertical {rh['off'][2]:+.2f} mm, pitch {rh['pitch']:+.2f} deg")

    # ------------------------------------------ the approach, tick by tick --
    click.secho("\nthe last stretch before the jaw shuts", bold=True)
    click.echo(f"  {'t':>8s} {'lateral':>8s} {'depth':>8s} {'vert':>7s} "
               f"{'pitch':>7s} {'out mm':>7s} {'in':>3s} {'speed':>7s}")
    lim = t_close if t_close else rows[-1]["t"]
    sel = [r for r in rows if lim - 6.0 <= r["t"] <= lim + 1.0]
    for k, r in enumerate(sel):
        if k % 2:
            continue
        sp = (np.linalg.norm(r["p"] - sel[k - 1]["p"]) if k else 0.0)
        click.echo(f"  {r['t']-t0:7.2f}s {r['off'][0]:+8.2f} {r['off'][1]:+8.2f} "
                   f"{r['off'][2]:+7.2f} {r['pitch']:+7.2f} {r['out_mm']:7.2f} "
                   f"{'IN' if r['inside'] else '--':>3s} {sp:7.2f}")

    # --------------------------------- what the plans said at those moments --
    click.secho("\nwhat the policy was planning at the best pose, and after it",
                bold=True)
    tr = [x for x in e["trace"] if x.get("plan_abs")]

    def first_close(pl, drop=3.0):
        g = [x["g"] for x in pl["plan_abs"]]
        return next((j for j in range(1, len(g)) if g[0] - g[j] > drop), None)

    click.echo(f"  {'t':>8s} {'stage':>9s} {'jaw seen':>9s} {'P0 jaw':>7s} "
               f"{'close at k':>10s} {'plan end lat/dep':>18s} {'jump':>6s} "
               f"{'dpitch':>7s}")
    win = [(x, min(rows, key=lambda r: abs(r["t"] - x["obs_t_s"]))) for x in tr
           if best["t"] - 2.5 <= x["obs_t_s"] <= lim + 1.5]
    prev = None
    for x, r in win:
        pl = x["plan_abs"]
        pend = np.array(pl[-1]["p"])
        Rend = np.asarray(pl[-1]["R"]).reshape(3, 3)
        offend = Rend.T @ (r["ball"] - pend)
        fc = first_close(x)
        jump = dp = float("nan")
        if prev is not None:
            a = {round(y["t_s"] / 0.1): y for y in prev["plan_abs"]}
            m = a.get(round(pl[0]["t_s"] / 0.1))
            if m:
                jump = float(np.linalg.norm(np.array(m["p"]) - np.array(pl[0]["p"])))
                dp = pitch_of(pl[0]["R"]) - pitch_of(m["R"])
        click.echo(f"  {x['obs_t_s']-t0:7.2f}s {str(x.get('stage'))[:9]:>9s} "
                   f"{x['obs']['input_width_mm'] if x.get('obs') else float('nan'):9.1f} "
                   f"{pl[0]['g']:7.1f} {str(fc):>10s} "
                   f"{offend[0]:+8.1f} /{offend[1]:+8.1f} {jump:6.1f} {dp:+7.2f}")
        prev = x
    click.echo("  'close at k' is the first step of the sixteen whose width is "
               "3 mm under the plan's own first step; only k=3..10 is ever sent")
    kin.close()


if __name__ == "__main__":
    main()
