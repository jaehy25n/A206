"""One nominal episode: the corrected-cadence run against the 0.3-s-cadence run (t1_g0_repA).

    python sim_umi/scripts/dse/nominal_vs_wrong.py <new run json> <episode> [--wrong <json>]
"""
import json
import sys

import numpy as np

WRONG = "sim_umi/eval_results/2026-09-27_dse/t1_g0_repA/nominal_G0.json"


def row(e):
    tr = e["trace"]
    ex = [pl["executed"] for pl in tr if pl.get("executed") is not None and pl.get("sent")]
    P = [b["obs_t_s"] - a["obs_t_s"] for a, b in zip(tr, tr[1:])]
    cols = None
    return {"success": e["success"], "grasped": e["grasped"], "furthest": e["furthest_stage"],
            "actions": e["steps"], "plans": len(tr), "stopped": e["stopped_because"],
            "replan_s": round(float(np.median(P)), 3) if P else None,
            "retired_per_plan": float(np.median(ex)) if ex else None,
            "stage_ticks": e["stage_ticks"], "gates": e["dse"]["gates"]["all"],
            "ball_final_mm": [round(v, 1) for v in e["ball_final_mm"]] if e.get("ball_final_mm") else None}


def main():
    new, ep = sys.argv[1], int(sys.argv[2])
    wrong = sys.argv[sys.argv.index("--wrong") + 1] if "--wrong" in sys.argv else WRONG
    N = {e["episode"]: e for e in json.load(open(new))["episodes"]}
    W = {e["episode"]: e for e in json.load(open(wrong))["episodes"]}
    a, b = row(N[ep]), row(W[ep]) if ep in W else None
    print(f"nominal ep{ep}: 0.6 s cadence -> {json.dumps(a)}")
    print(f"nominal ep{ep}: 0.3 s cadence -> {json.dumps(b)}")


if __name__ == "__main__":
    main()
