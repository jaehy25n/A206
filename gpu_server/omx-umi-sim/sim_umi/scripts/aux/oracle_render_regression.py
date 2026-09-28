"""The shared renderer (oracle_render.py, now used by build_oracle_masks.py AND the mask-
capable evaluator) must reproduce the frozen prep sidecar exactly.

    MUJOCO_GL=egl python sim_umi/scripts/aux/oracle_render_regression.py --demos 6 --out <json>

Re-renders every zarr row of the first N source demos through build_oracle_masks.work()
(which now calls OracleRenderer.render) and compares with the stored sidecar arrays: the
three masks, the finger-y map and the pixel counts, bit for bit. Nothing is written to
the sidecar.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "sim_umi" / "src"), str(ROOT / "sim_umi" / "scripts"),
                str(ROOT / "sim_umi" / "scripts" / "labels")]

import click
import numpy as np
import zarr

import build_oracle_masks as B


@click.command()
@click.option("--demos", default=6)
@click.option("--out", required=True)
def main(demos, out):
    stem = "omx_sim_train_v2"
    lab = np.load(ROOT / f"sim_umi/data/sidecars/{stem}.labels.npz")
    mz = zarr.open(zarr.ZipStore(str(ROOT / f"sim_umi/data/sidecars/{stem}.oracle_masks_g0.zarr.zip"), mode="r"), "r")
    rng = np.random.default_rng(0)
    pick = sorted(rng.choice(len(lab["demo_path"]), demos, replace=False).tolist())
    rep, ok = {}, True
    for di in pick:
        rows = np.flatnonzero(lab["row_source_demo_id"] == di)
        if not len(rows):
            continue
        job = (str(lab["demo_path"][di]), lab["row_source_frame_idx"][rows].tolist(), rows.tolist(),
               int(lab["demo_lift_start_idx"][di]), int(lab["demo_open_start_idx"][di]))
        r = B.work(job)
        res = {}
        for name in B.MASKS:
            stored = mz[f"data/{name}"].get_orthogonal_selection((rows, slice(None), slice(None)))
            res[name] = int((stored != r["masks"][name]).any((1, 2)).sum())
        stored_y = mz["data/ee_finger_y_mm"].get_orthogonal_selection((rows, slice(None), slice(None)))
        res["ee_finger_y_mm"] = int((stored_y != r["ymap"]).any((1, 2)).sum())
        for key in ("target_mask_px_224", "ee_gripper_mask_px_224", "ee_tip_mask_px_224"):
            res[key] = int((mz[f"stats/{key}"][:][rows] != r["cnt"][key]).sum())
        res["rows"] = int(len(rows))
        rep[str(lab["demo_path"][di])] = res
        bad = sum(v for k, v in res.items() if k != "rows")
        ok &= bad == 0
        print(lab["demo_path"][di], res, "OK" if bad == 0 else "MISMATCH", flush=True)
    pathlib.Path(out).write_text(json.dumps({"verdict": "PASS" if ok else "FAIL", "mismatching_rows": rep}, indent=1))
    print("REGRESSION", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
