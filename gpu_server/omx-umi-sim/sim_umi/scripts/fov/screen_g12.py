"""G1/G2 rough screening against the G0 run-to-run spread, by the rule registered
before the runs (JOURNAL 18:15). Screening only -- never a definitive FOV result.

    python sim_umi/scripts/fov/screen_g12.py --agg <aggregate_screen.json> --g0 label=agg.json,... --out <stem>
"""
import json
import pathlib

import click
import numpy as np

M = ["entered_corridor", "object_lifted", "strict_gt_secure_grasp", "bin_success", "consecutive_unreachable_abort"]
S = {"entered_corridor": "C", "object_lifted": "L", "strict_gt_secure_grasp": "S", "bin_success": "B",
     "consecutive_unreachable_abort": "a"}


def summ(run):
    cl = [e["close"] for e in run["episodes"] if e.get("close")]
    return {**{m: run["counts"][m] for m in M},
            "depth_med": float(np.median([x["depth"] for x in cl])) if cl else None,
            "vert_med": float(np.median([x["vertical"] for x in cl])) if cl else None,
            "n": len(run["episodes"])}


@click.command()
@click.option("--agg", required=True)
@click.option("--g0", "g0_specs", required=True)
@click.option("--out", required=True)
def main(agg, g0_specs, out):
    A = json.load(open(agg))["runs"]
    G0 = {lab: json.load(open(f))["runs"] for lab, f in (x.split("=", 1) for x in g0_specs.split(","))}
    rep, L = {}, ["# G1/G2 rough screening (asynchronous evaluator; screening only)", ""]
    for mode in ("nominal", "val18"):
        g0 = {lab: summ(r[f"G0_{mode}"]) for lab, r in G0.items()}
        rng = {k: (min(v[k] for v in g0.values()), max(v[k] for v in g0.values())) for k in M + ["depth_med", "vert_med"]}
        rep[mode] = {"g0_range": rng, "g0_runs": g0}
        L += [f"## {mode}", "| run | " + " | ".join(S[m] for m in M) + " | close depth med | close vertical med |",
              "|---|" + "---|" * (len(M) + 2)]
        for lab, v in g0.items():
            L.append(f"| G0 {lab} | " + " | ".join(str(v[m]) for m in M) + f" | {v['depth_med']:.1f} | {v['vert_med']:.1f} |")
        L.append("| **G0 range** | " + " | ".join(f"{rng[m][0]}-{rng[m][1]}" for m in M)
                 + f" | {rng['depth_med'][0]:.1f}..{rng['depth_med'][1]:.1f} | {rng['vert_med'][0]:.1f}..{rng['vert_med'][1]:.1f} |")
        for g in ("G1", "G2"):
            v = summ(A[f"{g}_{mode}"])
            rep[mode][g] = v
            L.append(f"| **{g}** | " + " | ".join(str(v[m]) for m in M) + f" | {v['depth_med']:.1f} | {v['vert_med']:.1f} |")
        L.append("")
    # the registered rule
    L.append("## Rule (registered 18:15)")
    for g in ("G1", "G2"):
        p, n0 = rep["val18"], rep["nominal"]
        lo_l, hi_l = p["g0_range"]["object_lifted"]
        lo_b, hi_b = p["g0_range"]["bin_success"]
        v = p[g]
        better = v["object_lifted"] >= hi_l + 2 and v["bin_success"] >= hi_b + 2
        worse = v["object_lifted"] <= lo_l - 2 and v["bin_success"] <= lo_b - 2
        c1 = better or worse
        dirn = "better" if better else "worse" if worse else None
        vn, rn = n0[g], n0["g0_range"]
        c2 = True
        if dirn == "better":
            c2 = not (vn["object_lifted"] < rn["object_lifted"][0] or vn["bin_success"] < rn["bin_success"][0])
        elif dirn == "worse":
            c2 = not (vn["object_lifted"] > rn["object_lifted"][1] or vn["bin_success"] > rn["bin_success"][1])
        rd, rv = p["g0_range"]["depth_med"], p["g0_range"]["vert_med"]
        c3 = (v["depth_med"] < rd[0] - 3 or v["depth_med"] > rd[1] + 3 or v["vert_med"] < rv[0] - 3 or v["vert_med"] > rv[1] + 3)
        rep[g + "_rule"] = {"1_lifted_and_bin_outside_by_2": c1, "direction": dirn, "2_nominal_not_opposite": c2,
                            "3_close_geometry_shift_3mm": bool(c3), "4_qualitative": "see per-episode table"}
        L.append(f"- {g}: (1) perturbation lifted {v['object_lifted']} (G0 {lo_l}-{hi_l}) and bin {v['bin_success']} "
                 f"(G0 {lo_b}-{hi_b}) outside by >= 2 in one direction: {c1}; (2) nominal not opposite: {c2}; "
                 f"(3) close median depth {v['depth_med']:.1f} / vertical {v['vert_med']:.1f} beyond G0 range by 3 mm: {bool(c3)} "
                 f"-> {'CANDIDATE (check 4)' if (c1 and c2 and c3) else 'similar: no provisional selection'}")
    # per-episode outcome strings, perturbation
    L += ["", "## Per episode, perturbation (C L S B a)", "| ep | " + " | ".join(f"G0 {k}" for k in G0) + " | G1 | G2 |",
          "|---|" + "---|" * (len(G0) + 2)]
    eps = sorted(e["episode"] for e in A["G1_val18"]["episodes"])
    def code(run, ep):
        e = next((x for x in run["episodes"] if x["episode"] == ep), None)
        return "-" if e is None else "".join(S[m] if e[m] else "." for m in M)
    for ep in eps:
        L.append(f"| {ep} | " + " | ".join(code(r["G0_val18"], ep) for r in G0.values())
                 + f" | {code(A['G1_val18'], ep)} | {code(A['G2_val18'], ep)} |")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1))
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
