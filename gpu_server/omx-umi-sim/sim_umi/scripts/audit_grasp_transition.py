"""How many different ways has the policy been shown to close a grasp?

    python sim_umi/scripts/audit_grasp_transition.py

The rollout never enters the expert's grasp corridor, and the axis that fails
is depth: the ball never gets far enough inside the fingers, and the tool stays
about eleven degrees too steep. Those two are not independent -- lowering the
nose is how the fingers get past the ball -- so what matters is whether the
demonstrations contain that coupled move in any variety, or one move twenty
times.

Six thousand training windows sounds like a lot of coverage. It is not six
thousand grasps. Every window inside one episode's approach describes the same
physical transition, so the independent count is the number of episodes, and
this says so explicitly rather than letting the window count stand in for it.

Everything is in the tool frame, from the demonstrations' own recorded ball
pose. Evaluation only; it reaches no observation and no command.
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

HZ = 10.0
BEFORE, AFTER = 1.5, 0.5


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


def onset(z):
    """The frame the jaw starts to shut."""
    st = z["stage"].astype(str)
    w = z["gripper_width"] * 1000
    g = np.where(st == "GRASP")[0]
    if not len(g):
        return None
    return next((k for k in g if w[k] < w[g[0]] - 1.0), g[0])


def window(p):
    z = np.load(p, allow_pickle=True)
    i = onset(z)
    if i is None:
        return None
    ee, R, b = z["eef_pos"], z["eef_rot"], z["eval_ball_pos"]
    w = z["gripper_width"] * 1000
    spec = json.loads(str(z["spec"]))
    lo, hi = i - int(BEFORE * HZ), i + int(AFTER * HZ)
    if lo < 0 or hi >= len(ee):
        lo, hi = max(lo, 0), min(hi, len(ee) - 1)
    rows = []
    for k in range(lo, hi + 1):
        off = R[k].T @ (b[k] - ee[k]) * 1000
        rows.append({
            "rel_s": round((k - i) / HZ, 2),
            "lat": off[0], "dep": off[1], "ver": off[2],
            "pitch": pitch_of(R[k]),
            "ee": ee[k] * 1000,
            "jaw": w[k],
            "jaw_v": (w[k] - w[k - 1]) * HZ if k else 0.0,
            "ee_v": float(np.linalg.norm(ee[k] - ee[k - 1])) * 1000 if k else 0.0})
    ox, oy = spec["object_xy"]
    return {"episode": p.name, "onset_i": int(i), "rows": rows,
            "obj_x": ox * 1000, "obj_y": oy * 1000,
            "obj_r": float(np.hypot(ox, oy)) * 1000,
            "obj_az": math.degrees(math.atan2(oy, ox)),
            "ball_r": spec["ball_r"] * 1000,
            "n_frames": len(ee)}


def at(ep, rel):
    for r in ep["rows"]:
        if abs(r["rel_s"] - rel) < 1e-6:
            return r
    return None


@click.command()
@click.option("--rollouts", default="", help="comma separated rollout json(.gz) "
                                             "to place against the expert")
@click.option("--plot", default=None)
def main(rollouts, plot):
    eps = [w for w in (window(p) for p in
                       sorted((SIM / "data" / "demos" / "train")
                              .glob("episode_*.npz"))) if w]
    click.secho(f"{len(eps)} expert episodes with a grasp", bold=True)

    # ------------------------------------------- 3. what is actually independent --
    click.secho("\n3. how many grasps this dataset really contains", bold=True)
    frames = sum(e["n_frames"] for e in eps)
    win = sum(max(e["n_frames"] - 16 - 1, 0) for e in eps)
    near = sum(1 for e in eps for k in range(e["n_frames"] - 17)
               if abs(k - e["onset_i"]) <= BEFORE * HZ)
    click.echo(f"  physical episodes                      {len(eps):6d}")
    click.echo(f"  independent APPROACH->GRASP transitions {len(eps):6d}")
    click.echo(f"  frames                                 {frames:6d}")
    click.echo(f"  16-step training windows               {win:6d}")
    click.echo(f"  windows whose start is within {BEFORE:.1f}s of a "
               f"closing jaw {near:6d}")
    click.echo(f"  -> {near} windows, but {len(eps)} events. The windows "
               f"overlap by {1 - len(eps)/max(near,1):.1%}; they are the same "
               f"{len(eps)} transitions resampled.")

    # ----------------------------- 1. are the twenty transitions the same path --
    click.secho("\n1. the transition, aligned on the instant the jaw starts to "
                "shut", bold=True)
    click.echo(f"  {'t':>7s} {'depth mean':>11s} {'sd':>6s} {'p5..p95':>16s} "
               f"{'pitch mean':>11s} {'sd':>6s} {'p5..p95':>16s} {'EE v':>7s}")
    grid = [round(-BEFORE + k / HZ, 1) for k in range(int((BEFORE + AFTER) * HZ) + 1)]
    spread = {}
    for rel in grid:
        vals = [at(e, rel) for e in eps]
        vals = [v for v in vals if v]
        if len(vals) < 5:
            continue
        D = np.array([v["dep"] for v in vals])
        P = np.array([v["pitch"] for v in vals])
        V = np.array([v["ee_v"] for v in vals])
        spread[rel] = {"dep": D, "pit": P,
                       "lat": np.array([v["lat"] for v in vals]),
                       "ver": np.array([v["ver"] for v in vals]),
                       "jaw": np.array([v["jaw"] for v in vals])}
        click.echo(f"  {rel:+6.1f}s {D.mean():+11.2f} {D.std():6.2f} "
                   f"{np.percentile(D,5):+7.2f}..{np.percentile(D,95):+7.2f} "
                   f"{P.mean():+11.2f} {P.std():6.2f} "
                   f"{np.percentile(P,5):+7.2f}..{np.percentile(P,95):+7.2f} "
                   f"{V.mean():7.3f}")
    d0 = spread.get(-1.0)
    dg = spread.get(0.0)
    if d0 and dg:
        click.secho(f"\n  one second before: depth {d0['dep'].mean():+.2f} "
                    f"+- {d0['dep'].std():.2f} mm, pitch {d0['pit'].mean():+.2f} "
                    f"+- {d0['pit'].std():.2f} deg", bold=True)
        click.secho(f"  at the close:      depth {dg['dep'].mean():+.2f} "
                    f"+- {dg['dep'].std():.2f} mm, pitch {dg['pit'].mean():+.2f} "
                    f"+- {dg['pit'].std():.2f} deg", bold=True)
        click.echo(f"  the move itself: depth {dg['dep'].mean()-d0['dep'].mean():+.2f} mm, "
                   f"pitch {dg['pit'].mean()-d0['pit'].mean():+.2f} deg, and across "
                   f"the twenty episodes those two are spread by only "
                   f"{np.std([at(e,0.0)['dep']-at(e,-1.0)['dep'] for e in eps if at(e,-1.0) and at(e,0.0)]):.2f} mm "
                   f"and {np.std([at(e,0.0)['pitch']-at(e,-1.0)['pitch'] for e in eps if at(e,-1.0) and at(e,0.0)]):.2f} deg")

    # ------------------------ 2. does the placement change the transition at all --
    click.secho("\n2. does where the ball is change how it is picked up?", bold=True)
    feats = []
    for e in eps:
        a, b = at(e, -1.0), at(e, 0.0)
        if not a or not b:
            continue
        pathlen = sum(float(np.linalg.norm(r2["ee"] - r1["ee"]))
                      for r1, r2 in zip(e["rows"], e["rows"][1:]))
        net = float(np.linalg.norm(e["rows"][-1]["ee"] - e["rows"][0]["ee"]))
        feats.append({"r": e["obj_r"], "az": e["obj_az"], "x": e["obj_x"],
                      "y": e["obj_y"], "rad": e["ball_r"],
                      "dep0": a["dep"], "pit0": a["pitch"],
                      "dpit": b["pitch"] - a["pitch"], "ddep": b["dep"] - a["dep"],
                      "curv": pathlen / max(net, 1e-6),
                      "dep_g": b["dep"], "pit_g": b["pitch"], "lat_g": b["lat"]})
    click.echo(f"  ball placement spans radius "
               f"{min(f['r'] for f in feats):.0f}..{max(f['r'] for f in feats):.0f} mm, "
               f"azimuth {min(f['az'] for f in feats):.0f}..{max(f['az'] for f in feats):.0f} deg")
    click.echo(f"  {'against':22s} {'corr r':>7s} {'corr az':>8s}   "
               f"{'value mean':>11s} {'sd':>7s} {'range':>16s}")
    for k, lab in (("dep0", "depth 1 s before"), ("pit0", "pitch 1 s before"),
                   ("dpit", "pitch change"), ("ddep", "depth change"),
                   ("curv", "path/net (curvature)"), ("dep_g", "depth at close"),
                   ("pit_g", "pitch at close"), ("lat_g", "lateral at close")):
        v = np.array([f[k] for f in feats])
        cr = np.corrcoef([f["r"] for f in feats], v)[0, 1]
        ca = np.corrcoef([f["az"] for f in feats], v)[0, 1]
        click.echo(f"  {lab:22s} {cr:+7.2f} {ca:+8.2f}   {v.mean():+11.2f} "
                   f"{v.std():7.2f} {v.min():+7.2f}..{v.max():+7.2f}")

    # -------------------------------- 5. when does a rollout leave that manifold --
    if rollouts:
        click.secho("\n5. the rollout against that distribution, counted back "
                    "from its own close", bold=True)
        import mujoco
        from collector import Collector
        from scene import SceneConfig, write_scene
        kin = Collector(str(write_scene(SceneConfig())), cfg=SceneConfig(),
                        render=False)

        def fk(q):
            dd = kin._ik
            dd.qpos[:] = kin.data.qpos
            for a_, v_ in zip(kin.arm_qadr, np.radians(q)):
                dd.qpos[a_] = v_
            mujoco.mj_kinematics(kin.model, dd)
            return (dd.site_xpos[kin.tcp_sid].copy() * 1000,
                    np.asarray(dd.site_xmat[kin.tcp_sid]).reshape(3, 3).copy())

        for path in rollouts.split(","):
            pp = pathlib.Path(path.strip())
            op = gzip.open if pp.suffix == ".gz" else open
            with op(pp, "rt") as f:
                d = json.load(f)
            e = d["episodes"][0]
            cols = d["ee_track_columns"]
            iq, ib = cols.index("j1_deg"), cols.index("ball_x_mm")
            jl = e.get("jaw_log") or []
            cl = [x for x in jl if x["actual_width_mm"] < 49.0]
            if not cl:
                click.echo(f"  {pp.name}: the jaw never shut")
                continue
            tc = cl[0]["t_fired_s"]
            track = []
            for row in e["ee_track"]:
                if row[ib] is None:
                    continue
                p_, R_ = fk(row[iq:iq + 5])
                off = R_.T @ (np.array(row[ib:ib + 3]) - p_)
                track.append((row[0], off, pitch_of(R_)))
            click.secho(f"\n  {pp.name}", bold=True)
            click.echo(f"    {'before close':>13s} {'lateral':>18s} "
                       f"{'depth':>20s} {'vertical':>18s} {'pitch':>20s}")
            for back in (1.5, 1.0, 0.5, 0.0):
                s = spread.get(round(-back, 1)) if back else spread.get(0.0)
                if s is None:
                    continue
                r = min(track, key=lambda x: abs(x[0] - (tc - back)))
                out = [f"    {-back:+12.1f}s"]
                for key, val in (("lat", r[1][0]), ("dep", r[1][1]),
                                 ("ver", r[1][2]), ("pit", r[2])):
                    ref = s[key if key != "pit" else "pit"]
                    zs = (val - ref.mean()) / max(ref.std(), 1e-9)
                    out.append(f"{val:+8.2f} ({zs:+7.1f}sd)")
                click.echo(" ".join(out))
            click.echo("    sd is the spread across the twenty expert "
                       "transitions at that same instant before their own close")
        kin.close()

    if plot:
        _plot(eps, plot)


def _plot(eps, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    for e in eps:
        t = [r["rel_s"] for r in e["rows"]]
        ax[0].plot(t, [r["dep"] for r in e["rows"]], lw=1, alpha=.7)
        ax[1].plot(t, [r["pitch"] for r in e["rows"]], lw=1, alpha=.7)
        ax[2].plot([r["dep"] for r in e["rows"]],
                   [r["pitch"] for r in e["rows"]], lw=1, alpha=.7)
        ax[2].plot(e["rows"][-1]["dep"], e["rows"][-1]["pitch"], "k.", ms=4)
    for a, lab in ((ax[0], "ball depth in the tool frame (mm)"),
                   (ax[1], "tool pitch (deg)")):
        a.set_xlabel("seconds from the jaw starting to shut")
        a.set_ylabel(lab)
        a.axvline(0, color="k", lw=.8, ls="--")
        a.grid(alpha=.3)
    ax[2].set_xlabel("depth (mm)")
    ax[2].set_ylabel("pitch (deg)")
    ax[2].set_title("the coupled move, twenty times")
    ax[2].grid(alpha=.3)
    fig.suptitle("every expert grasp transition, aligned on its own closing "
                 "instant", y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=110, bbox_inches="tight")
    click.echo(f"\nwrote {out}")


if __name__ == "__main__":
    main()
