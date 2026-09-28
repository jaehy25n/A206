"""The DSE hard gate: every plan's timeline invariants, arm / jaw continuity, exact
observation ticks, the JTC takeover step, no anomalies -- in every episode of a smoke.

    python sim_umi/scripts/dse/dse_gate.py <dse rollout .json> [...] [--mark]

Exit 0 only if every gate holds in every episode. With --mark, a pass is recorded as
sim_umi/eval_results/2026-09-27_dse/GATE_PASS_<git>.json; run_eval_dse.sh refuses a full
evaluation without the marker for the code it would run. The marker is keyed by the
content hash of the evaluator's own files (CODE below), not by the git commit, so journal
commits do not invalidate a pass and any change to the evaluator does.
"""
import json
import pathlib
import subprocess
import sys

import click

ROOT = pathlib.Path(__file__).resolve().parents[3]
CODE = ["sim_umi/ros/dse_rollout.py", "sim_umi/ros/policy_bridge.py", "sim_umi/ros/rolling_executor.py",
        "sim_umi/ros/policy_rollout.py", "sim_umi/ros/policy_server.py", "sim_umi/src/rgb_geometry.py"]


def code_hash():
    import hashlib
    h = hashlib.sha1()
    for f in CODE:
        h.update((ROOT / f).read_bytes())
    return h.hexdigest()[:12]


@click.command()
@click.argument("files", nargs=-1)
@click.option("--print-hash", is_flag=True, help="print the evaluator code hash and exit")
@click.option("--mark", is_flag=True)
def main(files, print_hash, mark):
    if print_hash:
        print(code_hash())
        return
    ok, report = True, {}
    for f in files:
        R = json.load(open(f))
        for e in R["episodes"]:
            g = e["dse"]["gates"]
            report[f"{pathlib.Path(f).name}:ep{e['episode']}"] = g
            print(f"{pathlib.Path(f).name} ep{e['episode']}: " + "  ".join(
                f"{k} {'ok' if v else 'FAIL'}" for k, v in g.items() if k != "all") + f"  -> {'PASS' if g['all'] else 'FAIL'}")
            ok &= g["all"]
        if R.get("infra_failed"):
            print(f"{f}: invalid starts {R['infra_failed']}")
            ok = False
    print("GATE", "PASS" if ok else "FAIL")
    if ok and mark:
        h = code_hash()
        git = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        m = ROOT / "sim_umi/eval_results/2026-09-27_dse" / f"GATE_PASS_{h}.json"
        m.write_text(json.dumps({"code_hash": h, "code_files": CODE, "git_at_mark": git,
                                 "files": list(files), "gates": report}, indent=1))
        print(f"marked {m}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
