"""Hard gate of the mask-capable evaluator (dse_rollout_masks.py).

    python sim_umi/scripts/aux/dse_mask_gate.py <rollout .json> [...] [--mark] [--print-hash]

PASS needs, for every smoke file:
  1. dse_gate.py's hard gates in every episode (timeline invariants, arm / jaw continuity,
     exact observation ticks, JTC takeover, no anomalies) and no invalid start;
  2. in its mask log (<json>.masks.jsonl), for EVERY observation frame: the masks came from
     the joint snapshot of the SAME stamp as the image (exact mode, snapshot stamp == image
     stamp), both free joints present (valid), no finger pixel off the finger box, a
     visible gripper and fingertip, and the mirror of that state within the prep QA level
     of the image the policy got (median over the file < 1.0 grey level; prep median 0.22).
The pass marker is keyed by the content hash of dse_gate's evaluator files PLUS the mask
path's own files, so any change to either invalidates it.
"""
import hashlib
import json
import pathlib
import statistics
import subprocess
import sys

import click

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim_umi" / "scripts" / "dse"))
from dse_gate import CODE  # noqa: E402

EXTRA = ["sim_umi/ros/dse_rollout_masks.py", "sim_umi/src/oracle_render.py", "sim_umi/src/oracle_masks.py",
         "sim_umi/src/oracle_state.py", "sim_umi/ros/env_overlay_masks.sh",
         "sim_umi/ros/config/mujoco_plugins_dse_masks.yaml", "sim_umi/ros/overlay_patches/camera_snapshot_free_joints.patch"]
OUT = ROOT / "sim_umi/eval_results/2026-09-28_dse_masks"


def code_hash():
    h = hashlib.sha1()
    for f in CODE + EXTRA:
        h.update((ROOT / f).read_bytes())
    return h.hexdigest()[:12]


@click.command()
@click.argument("files", nargs=-1)
@click.option("--print-hash", is_flag=True)
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
            report[f"{pathlib.Path(f).name}:ep{e['episode']}:dse"] = g
            print(f"{pathlib.Path(f).name} ep{e['episode']} dse gates -> {'PASS' if g['all'] else 'FAIL'}")
            ok &= bool(g["all"])
        if R.get("infra_failed"):
            print(f"{f}: invalid starts {R['infra_failed']}")
            ok = False
        recs = [json.loads(l) for l in open(str(f).replace(".json", ".masks.jsonl"))]
        bad = {"not_exact": sum(r["state_mode"] != "exact" or r["state_source"] != "rgb_snapshot" for r in recs),
               "stamp_mismatch": sum(r["snapshot_stamp_ns"] != r["image_stamp_ns"] for r in recs),
               "invalid": sum(not r["valid"] for r in recs),
               "finger_px_off_box": sum(r["gripper_px_off_finger_box"] > 0 for r in recs),
               "no_gripper_or_tip": sum(r["px224"]["ee_gripper_mask"] == 0 or r["px224"]["ee_tip_mask"] == 0 for r in recs)}
        mad = [r["mirror_vs_image_mad_crop"] for r in recs]
        m = {"frames": len(recs), **bad, "mirror_mad_median": round(statistics.median(mad), 4) if mad else None,
             "mirror_mad_max": max(mad) if mad else None,
             "render_wall_s_median": round(statistics.median(r["render_wall_s"] for r in recs), 4) if recs else None}
        passed = len(recs) > 0 and not any(bad.values()) and m["mirror_mad_median"] < 1.0
        report[f"{pathlib.Path(f).name}:masks"] = dict(m, ok=passed)
        print(f"{pathlib.Path(f).name} masks: {json.dumps(m)} -> {'PASS' if passed else 'FAIL'}")
        ok &= passed
    print("MASK GATE", "PASS" if ok else "FAIL")
    if ok and mark:
        h = code_hash()
        git = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"GATE_PASS_MASKS_{h}.json").write_text(json.dumps(
            {"code_hash": h, "code_files": CODE + EXTRA, "git_at_mark": git, "files": list(files), "gates": report}, indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
