"""Two evaluations of the SAME checkpoint on the same episodes: did they run
the same closed loop?

    python sim_umi/scripts/fov/repeat_compare.py --a rep1=<dir> --b rep2=<dir> \
        [--ref def=<dir-or-files>] --out <stem>

Each <dir> holds nominal_G0.json, val18_G0.json, their *_frames/ and
aggregate_G0.json (aggregate.py labels G0_nominal / G0_val18).

Per run: the observation contract, plan by plan -- obs_dt, exact [t-0.1, t]
pair, how each frame's joint state was obtained (exact / interpolated with its
bracket / nearest, recorder or local), counted and listed, never assumed.

Per episode, run a against run b, plan by plan:
  obs stamps     relative to the episode's first observation
  obs_dt, k*     sequences
  policy input   sha1 of the two masked frames the policy was given and the
                 lowdim dict it was given; the first plan where they differ,
                 and by how much (pixels changed, max |lowdim| difference)
  tool position  first plan whose observed tool position differs > 0.1 mm / > 2 mm
  action timing  in the plans up to the first input difference: latency, the
                 first sent waypoint k*, how far ahead of that waypoint the goal
                 reached the controller (the executor keeps absolute stamps, the
                 controller joins from wherever the arm is when the goal lands)
  outcome        LIFT / strict / bin / abort / corridor from the aggregates, and
                 first-close geometry
"""
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim_umi/scripts/definitive"))
import click
import numpy as np

from aggregate import load

MODES = ("nominal", "val18")
OUTC = ["entered_corridor", "object_lifted", "strict_gt_secure_grasp", "bin_success", "consecutive_unreachable_abort"]
SHORT = {"entered_corridor": "C", "object_lifted": "L", "strict_gt_secure_grasp": "S", "bin_success": "B",
         "consecutive_unreachable_abort": "a"}


def load_run(d):
    d = pathlib.Path(d)
    agg = json.load(open(d / "aggregate_G0.json"))["runs"]
    out = {}
    for m in MODES:
        R = load(d / f"{m}_G0.json")
        A = agg[f"G0_{m}"]
        out[m] = {"R": R, "eps": {e["episode"]: e for e in R["episodes"]},
                  "agg": {e["episode"]: e for e in A["episodes"]}, "counts": A["counts"],
                  "infra": sorted(x["episode"] for x in A.get("infra_failed", [])),
                  "frames": d / f"{m}_G0_frames"}
    return out


def contract(run):
    c = {"plans": 0, "obs_dt_not_0.1": [], "pair_not_exact": [], "frame_not_exact": 0,
         "state_modes": {}, "interp_bracket_gt_10ms": [], "nearest_or_none": [], "extra_wait_frames": {}}
    for m in MODES:
        for ep, e in run[m]["eps"].items():
            for n, pl in enumerate(e["trace"]):
                o = pl.get("obs") or {}
                c["plans"] += 1
                if abs((o.get("obs_dt_s") or -1) - 0.1) > 1e-4:
                    c["obs_dt_not_0.1"].append((m, ep, n, o.get("obs_dt_s")))
                if not o.get("obs_pair_exact"):
                    c["pair_not_exact"].append((m, ep, n))
                w = str(o.get("obs_extra_wait_frames"))
                c["extra_wait_frames"][w] = c["extra_wait_frames"].get(w, 0) + 1
                for f in o.get("frames") or []:
                    c["frame_not_exact"] += int(not f.get("frame_exact"))
                    k = f"{f.get('state_mode')}/{f.get('state_source')}"
                    c["state_modes"][k] = c["state_modes"].get(k, 0) + 1
                    b = f.get("state_bracket_s")
                    if f.get("state_mode") == "interp" and b is not None and b > 0.010:
                        c["interp_bracket_gt_10ms"].append((m, ep, n, round(b * 1000, 1)))
                    if f.get("state_mode") in ("nearest", "none", None):
                        c["nearest_or_none"].append((m, ep, n, f.get("state_mode"), f.get("image_state_skew_s")))
    c["holds"] = not (c["obs_dt_not_0.1"] or c["pair_not_exact"] or c["frame_not_exact"]
                      or c["interp_bracket_gt_10ms"] or c["nearest_or_none"])
    return c


def plan_inputs(run, m, ep):
    e = run[m]["eps"][ep]
    f = run[m]["frames"] / f"ep{ep:02d}.npz"
    Z = np.load(f) if f.exists() else None
    T = np.asarray(Z["image_stamp_s"], float) if Z is not None else np.zeros(0)

    def frame_at(t):        # the log rounds stamps to 10 us, the npz keeps them whole
        if not len(T):
            return None
        i = int(np.argmin(np.abs(T - t)))
        return Z["masked"][i] if abs(T[i] - t) < 1e-4 else None
    t0 = e["trace"][0]["obs_t_s"]
    rows = []
    for pl in e["trace"]:
        o = pl.get("obs") or {}
        fr = o.get("frames") or []
        imgs = []
        for x in fr:
            imgs.append(frame_at(float(x["image_stamp_s"])))
        low = o.get("lowdim")
        h_img = hashlib.sha1(b"".join(im.tobytes() for im in imgs)).hexdigest() if imgs and all(im is not None for im in imgs) else None
        h_low = hashlib.sha1(json.dumps(low, sort_keys=True).encode()).hexdigest() if low is not None else None
        sent = pl.get("sent") or []
        k = sent[0]["k"] if sent else None
        lead = None
        if sent and pl.get("goal_sent_at_s") is not None:
            t_k = next(x["t_s"] for x in pl["raw_plan"] if x["k"] == k)
            lead = t_k - pl["robot_latency_s"] - pl["goal_sent_at_s"]
        rows.append({"t_rel": round(pl["obs_t_s"] - t0, 4), "obs_dt": o.get("obs_dt_s"), "k": k,
                     "latency": pl["inference_s"], "goal_lead_s": lead, "prefix": pl["valid_prefix"],
                     "ee": pl["ee_at_obs_mm"], "h_img": h_img, "h_low": h_low, "imgs": imgs, "low": low})
    return rows


def low_diff(a, b):
    if a is None or b is None:
        return None
    return max(float(np.max(np.abs(np.array(a[k], float) - np.array(b[k], float)))) for k in a)


def pair_episode(A, B, m, ep):
    ra, rb = plan_inputs(A, m, ep), plan_inputs(B, m, ep)
    n = min(len(ra), len(rb))
    first = {}
    for key, test in (("t_rel", lambda x, y: abs(x["t_rel"] - y["t_rel"]) > 1e-4),
                      ("obs_dt", lambda x, y: x["obs_dt"] != y["obs_dt"]),
                      ("k", lambda x, y: x["k"] != y["k"]),
                      ("img", lambda x, y: x["h_img"] != y["h_img"]),
                      ("lowdim", lambda x, y: low_diff(x["low"], y["low"]) > 0),     # numeric: -0.0 == 0.0
                      ("ee_0.1mm", lambda x, y: np.linalg.norm(np.array(x["ee"]) - np.array(y["ee"])) > 0.1),
                      ("ee_2mm", lambda x, y: np.linalg.norm(np.array(x["ee"]) - np.array(y["ee"])) > 2.0)):
        hk = {"img": "h_img", "lowdim": "h_low"}.get(key)
        if hk and not all(r[hk] is not None for r in ra[:n] + rb[:n]):
            first[key] = "n/a"          # not logged for every plan: no claim either way
            continue
        first[key] = next((i for i in range(n) if test(ra[i], rb[i])), None)
    fi = [v for v in (first["img"], first["lowdim"]) if isinstance(v, int)]
    n_in = min(fi) if fi else None
    rec = {"episode": ep, "plans": (len(ra), len(rb)), "first_diff_plan": first,
           "hash_available": all(r["h_img"] is not None for r in ra + rb)}
    if n_in is not None:
        x, y = ra[n_in], rb[n_in]
        px = None
        if all(im is not None for im in x["imgs"] + y["imgs"]) and len(x["imgs"]) == len(y["imgs"]):
            px = [int((np.abs(p.astype(int) - q.astype(int)).sum(-1) > 0).sum()) for p, q in zip(x["imgs"], y["imgs"])]
        rec["first_input_diff"] = {"plan": n_in, "t_rel": (x["t_rel"], y["t_rel"]), "pixels_changed_per_frame": px,
                                   "lowdim_max_abs_diff": low_diff(x["low"], y["low"]),
                                   "ee_diff_mm": round(float(np.linalg.norm(np.array(x["ee"]) - np.array(y["ee"]))), 4)}
        w = range(max(0, n_in - 3), n_in + 1)
        rec["action_timing_up_to_it"] = [{"n": i, "k": (ra[i]["k"], rb[i]["k"]),
                                          "latency_ms": (round(ra[i]["latency"] * 1000, 1), round(rb[i]["latency"] * 1000, 1)),
                                          "goal_lead_ms": tuple(None if r[i]["goal_lead_s"] is None else round(r[i]["goal_lead_s"] * 1000, 1) for r in (ra, rb)),
                                          "prefix": (ra[i]["prefix"], rb[i]["prefix"])} for i in w]
    rec["seq"] = {"t_rel": ([r["t_rel"] for r in ra], [r["t_rel"] for r in rb]),
                  "obs_dt": ([r["obs_dt"] for r in ra], [r["obs_dt"] for r in rb]),
                  "k": ([r["k"] for r in ra], [r["k"] for r in rb])}
    oa, ob = A[m]["agg"][ep], B[m]["agg"][ep]
    rec["outcome"] = ("".join(SHORT[k] if oa[k] else "." for k in OUTC), "".join(SHORT[k] if ob[k] else "." for k in OUTC))
    t0a, t0b = A[m]["eps"][ep]["trace"][0]["obs_t_s"], B[m]["eps"][ep]["trace"][0]["obs_t_s"]
    rec["first_close"] = [None if not o.get("close") else
                          {"onset_rel_s": round(o["close"]["t_onset"] - t0, 2),
                           **{g: round(o["close"][g], 1) for g in ("lateral", "depth", "vertical", "pitch")}}
                          for o, t0 in ((oa, t0a), (ob, t0b))]
    return rec


def agreement(A, B, m, eps):
    return {k: sum(bool(A[m]["agg"][e][k]) == bool(B[m]["agg"][e][k]) for e in eps) for k in OUTC}


@click.command()
@click.option("--a", "a_spec", required=True)
@click.option("--b", "b_spec", required=True)
@click.option("--ref", "ref_specs", multiple=True, help="label=dir, outcome agreement only (descriptive)")
@click.option("--out", required=True)
def main(a_spec, b_spec, ref_specs, out):
    (la, da), (lb, db) = a_spec.split("=", 1), b_spec.split("=", 1)
    A, B = load_run(da), load_run(db)
    rep = {"a": la, "b": lb, "contract": {la: contract(A), lb: contract(B)}, "modes": {}}
    L = [f"# {la} vs {lb}", ""]
    for lab, c in rep["contract"].items():
        L.append(f"contract {lab}: holds={c['holds']}  plans {c['plans']}  obs_dt!=0.1 {len(c['obs_dt_not_0.1'])}  "
                 f"pair not exact {len(c['pair_not_exact'])}  frame not exact {c['frame_not_exact']}  "
                 f"state {c['state_modes']}  interp>10ms {len(c['interp_bracket_gt_10ms'])}  "
                 f"nearest/none {len(c['nearest_or_none'])}  extra-wait frames {c['extra_wait_frames']}")
    refs = {lab: load_run(d) for lab, d in (s.split("=", 1) for s in ref_specs)}
    for m in MODES:
        eps = sorted(set(A[m]["agg"]) & set(B[m]["agg"]))
        R = {"episodes": eps, "infra": {la: A[m]["infra"], lb: B[m]["infra"]},
             "counts": {la: {k: A[m]["counts"][k] for k in OUTC}, lb: {k: B[m]["counts"][k] for k in OUTC}},
             "agreement": agreement(A, B, m, eps), "pairs": [pair_episode(A, B, m, e) for e in eps],
             "ref_agreement": {}}
        for rl, Rr in refs.items():
            ce = sorted(set(eps) & set(Rr[m]["agg"]))
            R["ref_agreement"][rl] = {la: agreement(A, Rr, m, ce), lb: agreement(B, Rr, m, ce), "n": len(ce),
                                      "counts": {k: Rr[m]["counts"][k] for k in OUTC}}
        rep["modes"][m] = R
        L += ["", f"## {m} (n={len(eps)}; infra {R['infra']})",
              "counts " + "  ".join(f"{k}: {R['counts'][la][k]} vs {R['counts'][lb][k]}" for k in OUTC),
              f"episode agreement {la}-{lb}: " + "  ".join(f"{k} {v}/{len(eps)}" for k, v in R["agreement"].items())]
        for rl, v in R["ref_agreement"].items():
            L.append(f"  vs {rl} (descriptive, n={v['n']}): {la} " + " ".join(f"{SHORT[k]} {x}" for k, x in v[la].items())
                     + f" | {lb} " + " ".join(f"{SHORT[k]} {x}" for k, x in v[lb].items()))
        L.append("| ep | outcome a / b | plans | first diff plan: t_rel obs_dt k img lowdim ee>0.1 ee>2 | first input diff | first close a / b |")
        L.append("|---|---|---|---|---|---|")
        for p in R["pairs"]:
            f = p["first_diff_plan"]
            fid = p.get("first_input_diff")
            fs = "-" if not fid else (f"plan {fid['plan']} t {fid['t_rel'][0]:.2f}s px {fid['pixels_changed_per_frame']} "
                                      f"low {fid['lowdim_max_abs_diff']:.2e} ee {fid['ee_diff_mm']:.3f}mm")
            fc = " / ".join("-" if c is None else f"t{c['onset_rel_s']} d{c['depth']} v{c['vertical']}" for c in p["first_close"])
            L.append(f"| {p['episode']} | {p['outcome'][0]} / {p['outcome'][1]} | {p['plans'][0]}/{p['plans'][1]} | "
                     + " ".join(str(f[k]) for k in ("t_rel", "obs_dt", "k", "img", "lowdim", "ee_0.1mm", "ee_2mm"))
                     + f" | {fs} | {fc} |")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1, default=str))
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
