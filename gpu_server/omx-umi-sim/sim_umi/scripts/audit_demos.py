"""Does the demonstration only ever act on what it could see?

    python sim_umi/scripts/audit_demos.py --in-dir sim_umi/data/demos/audit

Five things have to hold before any of these episodes is worth training on,
and each is a property of the recorded frames rather than of the code that
wrote them:

  1. every episode starts at the same HOME, independent of the one before it
  2. while the ball is not in the policy's crop, no action in the next 16
     belongs to a phase that knows where the ball is
  3. the same for the bin
  4. episodes only diverge after a target has been seen -- until then the
     search is the same motion in all of them
  5. the search actually works: every episode ends up with both the ball and
     the bin inside the crop

It also prints, per phase, how often each target was visible and when it first
was, and where the 16-step horizon reaches from each frame. Anything it cannot
check it says so rather than passing quietly.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))

import click
import numpy as np

#: Which phases read which target. Taken from what the path builders in
#: collect_demos.py actually consult, and written out here rather than
#: imported, so the audit is not checking the collector against its own
#: opinion of itself:
#:
#:   approach_path, lift_path        read ep["object_xy"]
#:   transport_path, place_path,
#:   retreat_path                    read ep["bin_xy"]
#:   scan_legs                       reads neither
#:
#: GRASP is counted as ball-dependent although it only closes the jaw: it
#: happens where the approach left the arm, which is at the ball.
OBJECT_DEPENDENT = ("APPROACH_OBJECT", "GRASP", "LIFT")
BIN_DEPENDENT = ("TRANSPORT", "PLACE", "RETREAT")
ALL_PHASES = ("HOME", "SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP", "LIFT",
              "SEARCH_BIN", "TRANSPORT", "PLACE", "RETREAT", "SETTLE")
OBJECT_FREE = tuple(p for p in ALL_PHASES if p not in OBJECT_DEPENDENT)
BIN_FREE = tuple(p for p in ALL_PHASES if p not in BIN_DEPENDENT)
HORIZON = 16


def load(d):
    eps = []
    for p in sorted(pathlib.Path(d).glob("episode_*.npz")):
        z = np.load(p, allow_pickle=True)
        if "eval_object_visible" not in z:
            raise click.ClickException(
                f"{p.name} predates the visual expert: it has no visibility "
                f"channel, so none of this can be checked on it")
        eps.append({"name": p.stem, "t": z["t"], "pos": z["eef_pos"],
                    "rot": z["eef_rot"], "phase": np.array(
                        [str(v) for v in z["stage"]]),
                    "obj": z["eval_object_visible"],
                    "bin": z["eval_bin_visible"],
                    "w": z["gripper_width"], "rgb": z["rgb"],
                    "spec": json.loads(str(z["spec"]))})
    if not eps:
        raise click.ClickException(f"no episodes under {d}")
    return eps


def leakage(ep, key, free):
    """Acquisition leaks: a move towards a target that has not been seen.

    Only frames the arm is NOT already acting on that target in count. Inside
    APPROACH the ball passes under the gripper as the tool descends onto it --
    measured, at 70 to 84 percent of the way down, between 89 and 110 mm -- and
    inside LIFT and RETREAT the target is behind the arm that is leaving it.
    Those are not moves towards something unseen; they are occlusions during a
    move that a seen target started, and what governs them is how much of the
    phase keeps its target in view, which is checked separately. Counting them
    here would say the expert acted on a ball it had not seen, which is false.
    """
    bad = []
    n = len(ep["t"])
    for i in range(n):
        if ep[key][i] or ep["phase"][i] not in free:
            continue
        ahead = ep["phase"][i + 1:min(n, i + 1 + HORIZON)]
        unknown = sorted(set(ahead) - set(ALL_PHASES))
        if unknown:
            raise click.ClickException(
                f"{ep['name']} has phases this audit does not know about: "
                f"{unknown}. Classify them before trusting the result.")
        outside = sorted(set(ahead) - set(free))
        if outside:
            bad.append((i, float(ep["t"][i]), outside))
    return bad


@click.command()
@click.option("--in-dir", default=str(SIM / "data" / "demos" / "audit"))
@click.option("--zarr", "zarr_path", default=None,
              help="the built dataset, to check that nothing but the five "
                   "observation keys reached it")
@click.option("--crops", default=6, type=int,
              help="how many 224 crops per episode to write out for looking at")
def main(in_dir, zarr_path, crops):
    eps = load(in_dir)
    out = SIM / "outputs" / "audit"
    out.mkdir(parents=True, exist_ok=True)
    click.secho(f"{len(eps)} episodes from {in_dir}\n", bold=True)

    # ---------------------------------------------------------- per episode --
    click.secho("per episode", bold=True)
    click.echo(f"  {'episode':10s} {'frames':>6s} {'ball xy':>16s} {'bin xy':>16s} "
               f"{'obj 1st':>8s} {'bin 1st':>8s} {'start xyz (mm)':>22s}")
    for ep in eps:
        s = ep["spec"]
        fo = ep["t"][np.argmax(ep["obj"])] if ep["obj"].any() else np.nan
        fb = ep["t"][np.argmax(ep["bin"])] if ep["bin"].any() else np.nan
        st = ep["pos"][0] * 1000
        click.echo(f"  {ep['name']:10s} {len(ep['t']):6d} "
                   f"{s['object_xy'][0]*1000:+7.0f},{s['object_xy'][1]*1000:+7.0f} "
                   f"{s['bin_xy'][0]*1000:+7.0f},{s['bin_xy'][1]*1000:+7.0f} "
                   f"{fo:7.1f}s {fb:7.1f}s "
                   f"{st[0]:+7.1f},{st[1]:+7.1f},{st[2]:+6.1f}")

    # -------------------------------------------------------------- check 1 --
    starts = np.array([ep["pos"][0] for ep in eps]) * 1000
    spread = float(np.abs(starts - starts.mean(0)).max())
    ok1 = spread < 5.0
    click.secho(f"\n1. every episode starts at the same HOME", bold=True)
    click.secho(f"   worst start deviates {spread:.2f} mm from the mean "
                f"-> {'PASS' if ok1 else 'FAIL'}",
                fg="green" if ok1 else "red")

    # ------------------------------------------------------ checks 2 and 3 --
    ok2 = ok3 = True
    for n, (key, free, label) in enumerate(
            (("obj", OBJECT_FREE, "ball"), ("bin", BIN_FREE, "bin")), start=2):
        click.secho(f"\n{n}. before the {label} has been seen, the next "
                    f"{HORIZON} actions stay {label}-free", bold=True)
        worst = 0
        for ep in eps:
            bad = leakage(ep, key, free)
            worst = max(worst, len(bad))
            if bad:
                i, t, outside = bad[0]
                click.secho(f"   {ep['name']}: {len(bad)} frames leak, first at "
                            f"{t:.1f}s into {outside}", fg="red")
        if worst == 0:
            click.secho(f"   no frame in any episode -> PASS", fg="green")
        else:
            if n == 2:
                ok2 = False
            else:
                ok3 = False

    # -------------------------------------------------------------- check 4 --
    # Comparing the first k frames of every episode is too weak when one of
    # them can already see its ball at HOME: k collapses to 1 and the test
    # passes on nothing. Compare each PAIR over the frames where neither of
    # the two had yet seen its own ball, and report the longest such stretch.
    click.secho("\n4. episodes are the same motion until a target is seen",
                bold=True)
    first = [int(np.argmax(ep["obj"])) if ep["obj"].any() else len(ep["t"])
             for ep in eps]
    pairs, best = [], None
    for i in range(len(eps)):
        for j in range(i + 1, len(eps)):
            k = min(first[i], first[j], len(eps[i]["t"]), len(eps[j]["t"]))
            if k < 5:
                continue
            # Each blind prefix is measured against the OTHER episode's whole
            # look-around, not against its prefix cut at the same frame. Cut
            # both at k and the last point of whichever episode is a frame
            # ahead has nothing to match, which reads as a path difference the
            # size of one step and is only the truncation.
            def blind_path(e):
                m = np.isin(e["phase"], ("HOME", "SEARCH_OBJECT"))
                return e["pos"][m]
            a, b = eps[i]["pos"][:k][:-2], eps[j]["pos"][:k][:-2]
            fa, fb = blind_path(eps[i]), blind_path(eps[j])
            # Frame n of one episode and frame n of another are not the same
            # instant: the recorder samples wall time while the controller
            # runs its own clock, so half a frame of lag shows up as a
            # displacement even when the motion is identical. What has to
            # match is the PATH, so each point is measured to the nearest
            # point of the other path, both ways.
            def curve_gap(u, v):
                return float(np.sqrt(((u[:, None, :] - v[None, :, :]) ** 2)
                                     .sum(-1)).min(1).max()) * 1000
            d = max(curve_gap(a, fb), curve_gap(b, fa))
            pointwise = float(np.abs(a - b).max()) * 1000 if len(a) else 0.0
            pairs.append((k, d, eps[i]["name"], eps[j]["name"], pointwise))
            if best is None or k > best[0]:
                best = (k, d, eps[i]["name"], eps[j]["name"])
    if not pairs:
        ok4 = False
        click.secho("   no two episodes searched for 5 frames without seeing "
                    "the ball -- nothing to compare -> INCONCLUSIVE", fg="yellow")
    else:
        worst = max(d for _, d, _, _, _ in pairs)
        worst_pt = max(pw for _, _, _, _, pw in pairs)
        ok4 = worst < 5.0
        click.echo(f"   {len(pairs)} comparable pairs; longest blind stretch "
                   f"{best[0]} frames ({best[2]} vs {best[3]})")
        click.secho(f"   the paths differ by at most {worst:.2f} mm while both "
                    f"were still blind -> {'PASS' if ok4 else 'FAIL'}",
                    fg="green" if ok4 else "red")
        click.echo(f"   (frame against frame it is {worst_pt:.2f} mm; the "
                   f"difference between the two is sampling phase, not motion)")
        early = [ep["name"] for ep, f in zip(eps, first) if f < 5]
        if early:
            click.secho(f"   note: {len(early)} episode(s) could see the ball "
                        f"from HOME, so they contribute no search to compare: "
                        f"{early}", fg="yellow")

    # -------------------------------------------------------------- check 5 --
    miss = [ep["name"] for ep in eps if not (ep["obj"].any() and ep["bin"].any())]
    ok5 = not miss
    click.secho("\n5. the search puts both targets in the crop", bold=True)
    click.secho(f"   {'every episode saw both' if ok5 else 'missed: ' + str(miss)}"
                f" -> {'PASS' if ok5 else 'FAIL'}", fg="green" if ok5 else "red")

    # -------------------------------------------------------------- check 6 --
    # The invariant is that a target is in view while the arm is acting ON it.
    # LIFT and RETREAT are built from a target's position but are leaving it:
    # the ball passes under the gripper as it rises and the bin drops out of
    # frame as the arm backs off. Demanding they keep it in view would buy
    # nothing and would bend the trajectory to satisfy the audit, so they are
    # reported and not enforced.
    ENFORCED = {"obj": ("APPROACH_OBJECT", "GRASP"),
                "bin": ("TRANSPORT", "PLACE")}
    #: 99% rather than 100: the ball goes under the gripper for two or three
    #: frames near the bottom of the descent, which is the camera's geometry
    #: and not a fault in the demonstration.
    click.secho("\n6. a target is in view while the arm is acting on it", bold=True)
    ok6 = True
    for key, dependent, label in (("obj", OBJECT_DEPENDENT, "ball"),
                                  ("bin", BIN_DEPENDENT, "bin")):
        for ph in dependent:
            m = np.concatenate([ep["phase"] == ph for ep in eps])
            if not m.any():
                continue
            v = np.concatenate([ep[key] for ep in eps])[m]
            rate = v.mean() * 100
            enforced = ph in ENFORCED[key]
            good = rate >= 99.0
            if enforced:
                ok6 &= good
            click.secho(f"   {ph:16s} {label:5s} in view {rate:6.2f}% of "
                        f"{int(m.sum()):4d} frames -> "
                        f"{('ok' if good else 'FAIL') if enforced else 'reported only'}",
                        fg=None if (good or not enforced) else "red")

    # -------------------------------------------------------------- check 7 --
    click.secho("\n7. nothing but the observation keys reached the dataset",
                bold=True)
    ok7 = True
    if zarr_path is None:
        click.secho("   no --zarr given, so this is unchecked", fg="yellow")
        ok7 = False
    else:
        import zarr as zarrlib
        allowed = {"camera0_rgb", "robot0_eef_pos", "robot0_eef_rot_axis_angle",
                   "robot0_gripper_width", "robot0_demo_start_pose",
                   "robot0_demo_end_pose"}
        with zarrlib.ZipStore(str(zarr_path), mode="r") as st:
            keys = set(zarrlib.group(st)["data"].array_keys())
        extra = sorted(keys - allowed)
        missing = sorted(allowed - keys)
        for k in sorted(keys):
            click.echo(f"     {k}")
        if extra:
            click.secho(f"   these are not observation keys: {extra}", fg="red")
            ok7 = False
        if missing:
            click.secho(f"   missing: {missing}", fg="red")
            ok7 = False
        if ok7:
            click.secho("   every key is one the runtime can produce from the "
                        "wrist camera and /joint_states -> PASS", fg="green")
        gt = [k for k in keys if k.startswith("eval") or "ball" in k
              or "object" in k or "bin" in k or "_gt" in k]
        if gt:
            click.secho(f"   ground truth leaked in: {gt}", fg="red")
            ok7 = False

    # -------------------------------------------------- visibility by phase --
    click.secho("\nvisibility by phase, over all episodes", bold=True)
    click.echo(f"  {'phase':16s} {'frames':>7s} {'ball in crop':>13s} "
               f"{'bin in crop':>12s} {'phase spans':>12s}")
    order, seen = [], set()
    for ep in eps:
        for ph in ep["phase"]:
            if ph not in seen:
                seen.add(ph)
                order.append(ph)
    for ph in order:
        m = np.concatenate([ep["phase"] == ph for ep in eps])
        o = np.concatenate([ep["obj"] for ep in eps])[m]
        b = np.concatenate([ep["bin"] for ep in eps])[m]
        secs = sum(float((ep["phase"] == ph).sum()) for ep in eps) / 10.0 / len(eps)
        click.echo(f"  {ph:16s} {int(m.sum()):7d} {o.mean()*100:12.1f}% "
                   f"{b.mean()*100:11.1f}% {secs:10.1f}s")

    # ------------------------------------------ how far the horizon reaches --
    click.secho("\nwhat the 16-step horizon reaches, by the phase it starts in",
                bold=True)
    reach = {}
    for ep in eps:
        n = len(ep["t"])
        for i in range(n):
            here = ep["phase"][i]
            ahead = set(ep["phase"][i + 1:min(n, i + 1 + HORIZON)])
            reach.setdefault(here, set()).update(ahead)
    for ph in order:
        click.echo(f"  {ph:16s} -> {', '.join(sorted(reach.get(ph, set()))) or '(end)'}")

    # ------------------------------------------------- the action, per frame --
    click.secho("\nexpert action, as the step between recorded poses", bold=True)
    click.echo(f"  {'phase':16s} {'mean step':>10s} {'max step':>9s} "
               f"{'mean over 16':>13s}")
    for ph in order:
        steps, chunks = [], []
        for ep in eps:
            d = np.linalg.norm(np.diff(ep["pos"], axis=0), axis=1) * 1000
            m = ep["phase"][:-1] == ph
            steps.append(d[m])
            n = len(ep["t"])
            for i in np.flatnonzero(ep["phase"] == ph):
                j = min(n - 1, i + HORIZON)
                chunks.append(float(np.linalg.norm(ep["pos"][j] - ep["pos"][i]) * 1000))
        steps = np.concatenate(steps) if steps else np.zeros(1)
        if len(steps) == 0:
            continue
        click.echo(f"  {ph:16s} {steps.mean():9.2f} {steps.max():8.2f} "
                   f"{np.mean(chunks):12.2f}   mm")

    # ------------------------------------------------------------- the crops --
    import cv2
    for ep in eps:
        idx = np.linspace(0, len(ep["rgb"]) - 1, crops).astype(int)
        tiles = []
        for i in idx:
            f = ep["rgb"][i]
            h, w = f.shape[:2]
            side = min(h, w)
            y0, x0 = (h - side) // 2, (w - side) // 2
            c = cv2.resize(f[y0:y0 + side, x0:x0 + side], (224, 224),
                           interpolation=cv2.INTER_AREA)
            tag = f"{ep['t'][i]:.1f}s {ep['phase'][i]}"
            mark = ("ball " if ep["obj"][i] else "") + ("bin" if ep["bin"][i] else "")
            for txt, y in ((tag, 16), (mark or "nothing in view", 34)):
                for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                    cv2.putText(c, txt, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                                col, th, cv2.LINE_AA)
            tiles.append(c)
        cv2.imwrite(str(out / f"crops_{ep['name']}.png"),
                    np.hstack(tiles)[..., ::-1])
    click.echo(f"\ncrops written to {out}")

    allok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7
    click.secho(f"\n{'ALL SEVEN CHECKS PASS' if allok else 'AUDIT FAILED'}",
                bold=True, fg="green" if allok else "red")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
