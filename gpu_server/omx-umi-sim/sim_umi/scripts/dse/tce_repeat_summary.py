"""Residual variance of the timing-controlled evaluator: two runs of one checkpoint, judged
by the rule registered before the runs (JOURNAL 20:53).

    python sim_umi/scripts/dse/tce_repeat_summary.py --a A=<run dir> --b B=<run dir> --label G0 --out <stem>

Each run dir holds nominal_<L>.json / val18_<L>.json (timing-controlled rollouts) and
aggregate_<L>.json (aggregate.py labels <L>_nominal / <L>_val18; perturbation primary =
the paired valid 16, ep 11/13 listed invalid there and reported here as secondary).
"""
import json
import pathlib

import click

M = ["entered_corridor", "object_lifted", "strict_gt_secure_grasp", "bin_success", "consecutive_unreachable_abort"]
S = {"entered_corridor": "C", "object_lifted": "L", "strict_gt_secure_grasp": "S", "bin_success": "B",
     "consecutive_unreachable_abort": "a"}
ASYNC = {"nominal": {"object_lifted": 4, "bin_success": 2, "consecutive_unreachable_abort": 1},
         "val18": {"object_lifted": 12, "bin_success": 14, "consecutive_unreachable_abort": 11}}


@click.command()
@click.option("--a", "a_spec", required=True)
@click.option("--b", "b_spec", required=True)
@click.option("--label", default="G0")
@click.option("--out", required=True)
def main(a_spec, b_spec, label, out):
    (la, da), (lb, db) = a_spec.split("=", 1), b_spec.split("=", 1)
    rep, L = {"runs": (la, lb)}, [f"# Timing-controlled evaluator, {label}: {la} vs {lb}", ""]
    ok_all = True
    for mode, tol, need in (("nominal", 1, 4), ("val18", 3, 12)):
        RA, RB = (json.load(open(pathlib.Path(d) / f"{mode}_{label}.json")) for d in (da, db))
        gates = {x: {e["episode"]: e["dse"]["gates"]["all"] for e in R["episodes"]} for x, R in ((la, RA), (lb, RB))}
        AA, AB = (json.load(open(pathlib.Path(d) / f"aggregate_{label}.json"))["runs"][f"{label}_{mode}"] for d in (da, db))
        ea = {e["episode"]: e for e in AA["episodes"]}
        eb = {e["episode"]: e for e in AB["episodes"]}
        common = sorted(set(ea) & set(eb))
        gate_fail = {x: sorted(k for k, v in g.items() if not v and k in common) for x, g in gates.items()}
        c0 = not gate_fail[la] and not gate_fail[lb]
        diff = {m: AA["counts"][m] - AB["counts"][m] for m in M}
        c1 = all(abs(v) <= tol for v in diff.values())
        agree = {m: sum(bool(ea[k][m]) == bool(eb[k][m]) for k in common) for m in M}
        c2 = all(agree[m] >= need for m in ("object_lifted", "bin_success", "consecutive_unreachable_abort"))
        ok_all &= c0 and c1 and c2
        rep[mode] = {"episodes": common, "gate_fail_episodes": gate_fail, "counts": {la: AA["counts"], lb: AB["counts"]},
                     "diff": diff, "agreement": agree, "criteria": {"0_all_gates": c0, "1_aggregate": c1, "2_agreement": c2}}
        L += [f"## {mode} (n={len(common)})",
              f"- (0) hard gates in every episode: {c0}  (failing episodes {gate_fail})",
              "- counts " + "  ".join(f"{S[m]} {AA['counts'][m]} vs {AB['counts'][m]}" for m in M)
              + f"  -> (1) within +-{tol}: {c1}",
              "- episode agreement " + "  ".join(f"{S[m]} {agree[m]}/{len(common)}" for m in M)
              + f"  -> (2) lifted/bin/abort >= {need}: {c2}",
              "- asynchronous pair for reference: " + "  ".join(f"{S[m]} {v}" for m, v in ASYNC[mode].items()), ""]
        if mode == "val18":
            sec = {}
            for x, R in ((la, RA), (lb, RB)):
                sec[x] = {e["episode"]: {"gates": e["dse"]["gates"]["all"], "success": e["success"], "grasped": e["grasped"],
                                         "stopped": e["stopped_because"]} for e in R["episodes"] if e["episode"] in (11, 13)}
            rep["secondary_ep11_13"] = sec
            L.append(f"- secondary ep11/13 (ResetWorld starts; not pooled): {json.dumps(sec)}")
            L.append("")
        per = []
        for k in common:
            per.append(f"| {k} | " + "".join(S[m] if ea[k][m] else "." for m in M) + " | "
                       + "".join(S[m] if eb[k][m] else "." for m in M) + f" | {'ok' if gates[la].get(k) else 'FAIL'} / {'ok' if gates[lb].get(k) else 'FAIL'} |")
        L += ["| ep | " + la + " | " + lb + " | gates |", "|---|---|---|---|"] + per + [""]
    rep["stable_by_registered_rule"] = ok_all
    L.append(f"**Stable by the registered rule: {ok_all}**")
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1, default=str))
    pathlib.Path(out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
