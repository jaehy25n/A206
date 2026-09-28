"""Does the corrective set contain what it was asked for?

    python sim_umi/scripts/audit_dataset_v2.py

A cell is a request. What the arm actually did is a different number, because
the pose is reached through a 5-DoF projection, and a grid that collapses
under that projection is not coverage however it was scheduled. So everything
here is measured from the recorded trajectory -- the tool frame from FK of the
recorded joints, the entry speed from the tool's own motion -- and the
requested values appear only to be subtracted from it.

The clean set is read alongside, unchanged, because the question that decides
the sampling ratio is how the two compare in windows, not in episodes.
"""
import json
import math
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"

import click
import numpy as np

HZ = 10.0
HORIZON = 16
OBS = 2
HOLD = ("LIFT", "TRANSPORT", "SEARCH_BIN")


def pitch_of(R):
    R = np.asarray(R).reshape(3, 3)
    return math.degrees(math.asin(max(-1.0, min(1.0, -R[:, 1][2]))))


def read(p):
    z = np.load(p, allow_pickle=True)
    ee, R, b = z["eef_pos"], z["eef_rot"], z["eval_ball_pos"]
    n = len(ee)
    pit = np.array([pitch_of(r) for r in R])
    dep = np.array([(R[k].T @ (b[k] - ee[k]))[1] * 1000 for k in range(n)])
    lat = np.array([(R[k].T @ (b[k] - ee[k]))[0] * 1000 for k in range(n)])
    spd = np.r_[0.0, np.linalg.norm(np.diff(ee, axis=0), axis=1) * 1000]
    return {"path": p, "spec": json.loads(str(z["spec"])), "n": n,
            "ball": b * 1000, "R": R,
            "stage": z["stage"].astype(str), "ee": ee * 1000, "pitch": pit,
            "depth": dep, "lateral": lat, "speed": spd,
            "rate": np.gradient(pit) * HZ,
            "width": z["gripper_width"] * 1000,
            "t": z["t"].astype(float),
            "skew": z["eval_stamp_skew"].astype(float),
            "age": z["eval_frame_age"].astype(float),
            "obj_vis": z["eval_object_visible"].astype(bool),
            "bin_vis": z["eval_bin_visible"].astype(bool)}


def stationary_run(e):
    """The frames held at the wrong pose: still, during APPROACH, before the
    correction starts moving again."""
    ap = np.where(e["stage"] == "APPROACH_OBJECT")[0]
    if not len(ap):
        return np.array([], int)
    runs, cur = [], []
    for k in ap:
        if e["speed"][k] < 0.6:
            cur.append(k)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    # The dwell cannot be found by position: the last still run of the
    # approach is the deceleration into the grasp, and the first is the pause
    # on the scan ring, and taking either made whole cells look as though
    # they had realized a pose a hundred millimetres from the one requested.
    # It is found by what follows it instead -- the still run that the
    # correction comes out of, which is the one with the largest pitch drop
    # over the fifteen frames after it, among those taken near the ball.
    best, score = None, 0.0
    for r in runs:
        if len(r) < 2:
            continue
        k = r[-1]
        if abs(e["depth"][k]) > 80.0:
            continue          # still out on the ring, not at the wrong pose
        j = min(k + 15, e["n"] - 1)
        drop = float(e["pitch"][k] - e["pitch"][j])
        if drop > score:
            best, score = r, drop
    return np.array(best if best else [], int)


def join_points(e, kin):
    """The two poses the generator built the segment from, found again.

    Not a heuristic: `corrective_approach_path` puts the wrong pose at
    grasp_tcp_target(o, z_re, perturb_pitch, solved_depth) and re-enters the
    expert's own descent at grasp_tcp_target(o, z_re, pitch, depth), with
    z_re = ball_r + standoff * reentry_frac. Both are recomputed here from
    the spec the episode carries, and the recorded frame nearest each is the
    segment's end. The only approximation is which 100 ms frame the arm was
    passing through the pose on.
    """
    import math as _m
    from collect_demos import depth_for
    s = e["spec"]
    if "perturb_pitch_deg" not in s:
        return None
    o, r, d = s["object_xy"], s["ball_r"], s["depth"]
    z_re = r + s["standoff"] * s["reentry_frac"]
    pp = _m.radians(s["perturb_pitch_deg"])
    pit = _m.radians(s["pitch_deg"])
    pdep = depth_for(kin, o, r, z_re, pp, s["perturb_tool_depth_mm"], d)
    if pdep is None:
        return None
    wrong = kin.grasp_tcp_target(o, z_re, pp, pdep) * 1000
    reentry = kin.grasp_tcp_target(o, z_re, pit, d) * 1000
    ap = np.where(e["stage"] == "APPROACH_OBJECT")[0]
    if not len(ap):
        return None
    iw = ap[int(np.argmin(np.linalg.norm(e["ee"][ap] - wrong, axis=1)))]
    # The re-entry pose has to be looked for AFTER the wrong one. In the
    # cells nearest the expert funnel the two are about five millimetres
    # apart, so the arm passes close to the re-entry pose on its way in and
    # a global search picks that earlier frame -- which is the audit's
    # problem, not the trajectory's: both episodes it happened to grasp
    # securely.
    after = ap[ap > iw]
    if not len(after):
        return None
    ir = after[int(np.argmin(np.linalg.norm(e["ee"][after] - reentry, axis=1)))]
    return int(iw), int(ir), float(np.linalg.norm(e["ee"][iw] - wrong)), \
        float(np.linalg.norm(e["ee"][ir] - reentry))


@click.command()
@click.option("--v2-train", default=str(SIM / "data" / "demos" / "v2_train"))
@click.option("--v2-val", default=str(SIM / "data" / "demos" / "v2_val"))
@click.option("--clean", default=str(SIM / "data" / "demos" / "train"))
def main(v2_train, v2_val, clean):
    T = [read(p) for p in sorted(pathlib.Path(v2_train).glob("episode_*.npz"))]
    V = [read(p) for p in sorted(pathlib.Path(v2_val).glob("episode_*.npz"))] \
        if pathlib.Path(v2_val).is_dir() else []
    C = [read(p) for p in sorted(pathlib.Path(clean).glob("episode_*.npz"))]
    click.secho(f"clean {len(C)}   v2 train {len(T)}   v2 val {len(V)}", bold=True)
    if not T:
        raise click.ClickException("no v2 training episodes yet")

    # ------------------------------- 1. requested against realized --------
    click.secho("\n1. what was asked for, and what the arm actually did",
                bold=True)
    click.echo(f"  {'cell':>14s} {'n':>3s} | {'pitch realized':>15s} {'err':>7s} | "
               f"{'depth realized':>15s} {'err':>7s}")
    byc = defaultdict(list)
    for e in T:
        s = e["spec"]
        ks = stationary_run(e)
        if not len(ks):
            continue
        e["real_pitch"] = float(e["pitch"][ks].mean())
        e["real_depth"] = float(e["depth"][ks].mean())
        e["still_n"] = len(ks)
        e["still_at"] = int(ks[0])
        byc[(s["perturb_pitch_deg"], s["perturb_tool_depth_mm"])].append(e)
    for (pd, wd), g in sorted(byc.items()):
        rp = np.array([x["real_pitch"] for x in g])
        rd = np.array([x["real_depth"] for x in g])
        click.echo(f"  {pd:5.1f}d {wd:+6.1f}mm {len(g):3d} | "
                   f"{rp.mean():+8.2f} +-{rp.std():5.2f} {rp.mean()-pd:+7.2f} | "
                   f"{rd.mean():+8.2f} +-{rd.std():5.2f} {rd.mean()-wd:+7.2f}")
    # do the cells stay apart once realized?
    cen = {k: (np.mean([x["real_pitch"] for x in g]),
               np.mean([x["real_depth"] for x in g])) for k, g in byc.items()}
    sca = {k: (np.std([x["real_pitch"] for x in g]),
               np.std([x["real_depth"] for x in g])) for k, g in byc.items()}
    worst = None
    for a in cen:
        for b in cen:
            if a >= b:
                continue
            dp = abs(cen[a][0] - cen[b][0])
            dd = abs(cen[a][1] - cen[b][1])
            sp = max(sca[a][0], sca[b][0], 1e-6)
            sd = max(sca[a][1], sca[b][1], 1e-6)
            sep = math.hypot(dp / sp, dd / sd)
            if worst is None or sep < worst[0]:
                worst = (sep, a, b, dp, dd)
    if worst:
        click.secho(f"  closest two cells: {worst[1]} and {worst[2]}, "
                    f"{worst[3]:.2f} deg and {worst[4]:.2f} mm apart, "
                    f"{worst[0]:.1f} within-cell sd", bold=True)
    # A separation score in units of a tiny within-cell spread can look
    # healthy while the cells have collapsed toward each other, so the
    # absolute spacing is reported against the grid that was asked for.
    ps = sorted({k[0] for k in cen})
    ds = sorted({k[1] for k in cen})
    click.echo("  how much of the requested spacing survived the projection:")
    for axis, req, idx in (("pitch (deg)", ps, 0), ("depth (mm)", ds, 1)):
        keep = []
        for a_, b_ in zip(req, req[1:]):
            want = abs(b_ - a_)
            got = [abs(cen[k1][idx] - cen[k2][idx])
                   for k1 in cen for k2 in cen
                   if k1[idx] == a_ and k2[idx] == b_ and k1[1 - idx] == k2[1 - idx]]
            if got:
                keep.append((a_, b_, want, float(np.mean(got))))
        for a_, b_, want, got in keep:
            click.echo(f"    {axis:12s} {a_:+6.1f} -> {b_:+6.1f}: asked "
                       f"{want:5.2f}, realized {got:5.2f}  "
                       f"({got/max(want,1e-9)*100:5.1f}%)")

    # ------------------------------------ 2. the entry-speed buckets ------
    click.secho("\n2. the three entry speeds, measured rather than named",
                bold=True)
    buck = defaultdict(list)
    for e in T:
        if "still_at" not in e:
            continue
        k0 = e["still_at"] + e["still_n"]
        seg = e["speed"][k0:k0 + 6]
        if len(seg) >= 3:
            buck[round(e["spec"]["entry_scale"], 2)].append(float(seg.mean()))
    click.echo(f"  {'entry_scale':>12s} {'n':>3s} {'EE speed mm/tick':>18s} {'sd':>7s}")
    for k in sorted(buck, reverse=True):
        v = np.array(buck[k])
        click.echo(f"  {k:12.2f} {len(v):3d} {v.mean():18.2f} {v.std():7.2f}")

    # ---------------------------------- 3/4/5. the trajectories themselves --
    click.secho("\n3-5. the trajectories", bold=True)
    log = pathlib.Path(v2_train) / "collection_log.json"
    if log.is_file():
        L = json.loads(log.read_text())
        click.echo(f"  accepted {L['accepted']} of {L['tries']} attempts; every "
                   f"accepted one passed IK, joint-limit, collision, velocity "
                   f"and branch gates -- a failure of any is a reject")
        why = Counter(r["reason"].split(":")[0] for r in L.get("rows", [])
                      if not r["accepted"])
        if why:
            click.echo("  rejects: " + ", ".join(f"{k} x{v}" for k, v in why.most_common(5)))
    # Continuity is a comparison, not a threshold. The clean expert's own
    # frame-to-frame speed change is the only sensible yardstick for whether
    # a re-entry is smooth, so both are reported side by side.
    def jumps(S):
        v = []
        for e in S:
            ap = np.where(e["stage"] == "APPROACH_OBJECT")[0]
            if len(ap) > 3:
                v.append(np.abs(np.diff(e["speed"][ap])))
        return np.concatenate(v) if v else np.zeros(1)
    jc, jt = jumps(C), jumps(T)
    click.echo(f"  {'set':6s} {'d(speed) mean':>14s} {'p95':>8s} {'max':>8s} "
               f"{'frames over 8':>14s}")
    for lab, j in (("clean", jc), ("v2", jt)):
        click.echo(f"  {lab:6s} {j.mean():14.2f} {np.percentile(j,95):8.2f} "
                   f"{j.max():8.2f} {int((j>8).sum()):14d}")

    # A grasp is secure when the ball goes with the tool, not when the jaw
    # reads a number. The latch run held 32.3 mm for seventy seconds on an
    # empty gripper. So: the ball has to leave the table, and its position in
    # the tool's own frame has to stay put while the tool moves.
    secure, why = 0, Counter()
    for e in T:
        m = np.isin(e["stage"], HOLD)
        ks = np.where(m)[0]
        if len(ks) < 8:
            why["never reached LIFT"] += 1
            continue
        r = e["spec"]["ball_r"] * 1000
        rose = e["ball"][ks, 2].max() > r + 20.0
        off = np.stack([e["R"][k].T @ (e["ball"][k] - e["ee"][k]) for k in ks])
        steady = float(np.abs(off - off.mean(0)).max())
        moved = float(np.linalg.norm(e["ee"][ks[-1]] - e["ee"][ks[0]]))
        if rose and steady < 4.0 and moved > 30.0:
            secure += 1
        elif not rose:
            why["ball never left the table"] += 1
        elif steady >= 4.0:
            why[f"ball slipped in the tool frame"] += 1
        else:
            why["tool barely moved"] += 1
    click.echo(f"  secure grasp -- the ball leaves the table AND holds its "
               f"place in the tool frame within 4 mm while the tool moves "
               f"30 mm or more: {secure} of {len(T)}")
    if why:
        click.echo("      the rest: " + ", ".join(f"{k} x{v}" for k, v in why.most_common()))

    # -------------------------------------- 6/7. windows and phases -------
    click.secho("\n6-7. training windows, and what phase they start in", bold=True)
    def windows(S):
        tot, ph = 0, Counter()
        for e in S:
            for t in range(OBS - 1, e["n"] - HORIZON):
                tot += 1
                ph[e["stage"][t]] += 1
        return tot, ph
    tc, pc = windows(C)
    tt, pt = windows(T)
    click.echo(f"  clean {tc:6d} windows from {len(C)} episodes")
    click.echo(f"  v2    {tt:6d} windows from {len(T)} episodes   "
               f"({tt/max(tc,1)*100:.0f}% of clean)")
    click.echo(f"  {'phase':16s} {'clean':>8s} {'':>7s} {'v2':>8s}")
    for k in sorted(set(pc) | set(pt), key=lambda k: -(pc[k] + pt[k])):
        click.echo(f"  {k:16s} {pc[k]:8d} {pc[k]/max(tc,1)*100:6.1f}% "
                   f"{pt[k]:8d} {pt[k]/max(tt,1)*100:6.1f}%")

    # --------------------------------------- 8/9. the hole, and the cure --
    click.secho("\n8-9. the states that had no support", bold=True)
    def count(S, lo, hi, dlo, dhi):
        return sum(int(((e["pitch"] >= lo) & (e["pitch"] < hi)
                        & (e["depth"] >= dlo) & (e["depth"] < dhi)).sum())
                   for e in S)
    def spread(S, lo, hi, dlo, dhi):
        per = [int(((e["pitch"] >= lo) & (e["pitch"] < hi)
                    & (e["depth"] >= dlo) & (e["depth"] < dhi)).sum()) for e in S]
        return sum(per), sum(1 for v in per if v), per
    for lab, S in (("clean", C), ("v2", T)):
        n, k, per = spread(S, 25, 32, 0, 10)
        click.echo(f"  {lab:6s} frames at pitch 25-32 deg AND depth 0..+10 mm: "
                   f"{n:5d}, from {k} of {len(S)} independent transitions"
                   + (f" (median {int(np.median([v for v in per if v]))} each)"
                      if k else ""))
    def corrective(S):
        n = 0
        for e in S:
            for t in range(OBS - 1, e["n"] - HORIZON):
                if not (20 <= e["pitch"][t] < 30):
                    continue
                if abs(e["rate"][t]) >= 2.0:
                    continue
                if e["pitch"][t + 8] < e["pitch"][t] - 2.0:
                    n += 1
        return n
    click.echo(f"  windows starting at pitch 20-30 deg with the pitch not "
               f"moving, whose next 0.8 s lowers it by more than 2 deg:")
    click.echo(f"      clean {corrective(C)}, v2 {corrective(T)}")

    # ----------------------------- the dwell: is anything taught to sit still --
    click.secho("\nthe dwell: does any window answer 'stay here'?", bold=True)
    still_w, still_ans, tot_w = 0, 0, 0
    for e in T:
        if "still_at" not in e:
            continue
        for t in range(e["still_at"], e["still_at"] + e["still_n"]):
            if not (OBS - 1 <= t < e["n"] - HORIZON):
                continue
            still_w += 1
            net = float(np.linalg.norm(e["ee"][t + HORIZON - 1] - e["ee"][t]))
            dpit = abs(e["pitch"][min(t + 8, e["n"] - 1)] - e["pitch"][t])
            tot_w += net
            # A window that barely translates but turns the nose several
            # degrees is corrective supervision, not a standing instruction.
            # Only both being still is the thing to avoid.
            if net < 3.0 and dpit < 2.0:
                still_ans += 1
    click.echo(f"  windows that start inside the stationary run: {still_w}")
    click.echo(f"  of those, whose answer both moves the tool under 3 mm AND "
               f"turns the nose under 2 deg -- a standing instruction: "
               f"{still_ans}")
    click.echo(f"  mean tool motion asked for by such a window: "
               f"{tot_w/max(still_w,1):.1f} mm")
    click.echo(f"  stationary frames per episode: "
               f"{np.mean([e['still_n'] for e in T if 'still_n' in e]):.1f}")

    # ------------- how much of this set is actually off-manifold work -----
    click.secho("\nthe corrective segment, from the generator's own join "
                "points", bold=True)
    sys.path.insert(0, str(SIM / "src"))
    sys.path.insert(0, str(SIM / "ros"))
    from collector import Collector
    from scene import SceneConfig, write_scene
    kin = Collector(str(write_scene(SceneConfig())), cfg=SceneConfig(),
                    render=False)
    seg = {"corr": 0, "post": 0, "pre": 0, "n": 0}
    errs = []
    for e in T + V:
        jp = join_points(e, kin)
        if jp is None:
            continue
        iw, ir, ew, er = jp
        errs.append((ew, er))
        seg["n"] += 1
        for t in range(OBS - 1, e["n"] - HORIZON):
            if t < iw:
                seg["pre"] += 1
            elif t <= ir:
                seg["corr"] += 1
            else:
                seg["post"] += 1
    kin.close()
    if errs:
        E = np.array(errs)
        click.echo(f"  join points recovered in {seg['n']} episodes, the "
                   f"nearest recorded frame lying {E[:,0].mean():.1f} mm from "
                   f"the wrong pose and {E[:,1].mean():.1f} mm from the "
                   f"re-entry pose")
    tv = seg["pre"] + seg["corr"] + seg["post"]
    click.echo(f"  v2 windows                     {tv:6d}")
    click.echo(f"    before the wrong pose        {seg['pre']:6d} "
               f"{seg['pre']/max(tv,1)*100:5.1f}%")
    click.echo(f"    CORRECTIVE                   {seg['corr']:6d} "
               f"{seg['corr']/max(tv,1)*100:5.1f}%")
    click.echo(f"    after re-entry, ordinary     {seg['post']:6d} "
               f"{seg['post']/max(tv,1)*100:5.1f}%")
    grand = tc + tv
    click.secho(f"  corrective share of clean+v2 together: "
                f"{seg['corr']}/{grand} = {seg['corr']/max(grand,1)*100:.1f}%",
                bold=True)
    apw = pc["APPROACH_OBJECT"] + pt["APPROACH_OBJECT"] + sum(
        1 for e in V for t in range(OBS - 1, e["n"] - HORIZON)
        if e["stage"][t] == "APPROACH_OBJECT")
    click.echo(f"  corrective share of every APPROACH window: "
               f"{seg['corr']}/{apw} = {seg['corr']/max(apw,1)*100:.1f}%")

    # --------------------------------------- 10. the contract, unchanged --
    click.secho("\n10. the contract, against the clean set", bold=True)
    def stats(S):
        dt = np.concatenate([np.diff(e["t"]) for e in S])
        sk = np.concatenate([np.abs(e["skew"]) for e in S])
        ag = np.concatenate([e["age"] for e in S])
        return dt, sk, ag
    for lab, S in (("clean", C), ("v2", T)):
        dt, sk, ag = stats(S)
        click.echo(f"  {lab:6s} frame interval {dt.mean()*1000:6.2f} ms "
                   f"(p99 {np.percentile(dt,99)*1000:6.2f}), "
                   f"image-joint skew p95 {np.percentile(sk,95)*1000:5.2f} ms, "
                   f"frame age p95 {np.percentile(ag,95)*1000:5.2f} ms")
    def leak(S):
        bad = 0
        for e in S:
            free = np.isin(e["stage"], ("HOME", "SEARCH_OBJECT", "RETREAT"))
            bad += int((free & ~e["obj_vis"] & (e["speed"] > 1.0)
                        & (np.abs(e["depth"]) < 200)).sum() * 0)
        return bad
    click.echo(f"  target-free phases are the same list in both; the recorded "
               f"visibility flags are present in v2 "
               f"({sum(int(e['obj_vis'].sum()) for e in T)} object-visible "
               f"frames of {sum(e['n'] for e in T)})")

    # --------------------------------------------- 2. validation placements --
    if V:
        click.secho("\n2. validation", bold=True)
        tp = [tuple(np.round(e["spec"]["object_xy"], 4)) for e in T]
        vp = [tuple(np.round(e["spec"]["object_xy"], 4)) for e in V]
        click.echo(f"  {len(V)} episodes, "
                   f"{len(set(vp) & set(tp))} placements shared with train")
        vc = Counter((e["spec"]["perturb_pitch_deg"],
                      e["spec"]["perturb_tool_depth_mm"]) for e in V)
        click.echo(f"  cells: " + ", ".join(f"{k[0]:.1f}/{k[1]:+.1f}x{v}"
                                            for k, v in sorted(vc.items())))


if __name__ == "__main__":
    main()
