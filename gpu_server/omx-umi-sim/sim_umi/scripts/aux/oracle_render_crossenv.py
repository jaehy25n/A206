"""The mask-capable evaluator renders in the ROS env (python 3.12, cv2 5.0); the prep
sidecar was rendered in the umi env (python 3.9, cv2 4.7); both MuJoCo 3.3.7. Prove the
same code gives the same masks in both.

    umi env:  python sim_umi/scripts/aux/oracle_render_crossenv.py export <npz>
    ROS env:  MUJOCO_GL=egl python sim_umi/scripts/aux/oracle_render_crossenv.py check <npz> <json>
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "sim_umi" / "src"), str(ROOT / "sim_umi" / "scripts"),
                str(ROOT / "sim_umi" / "scripts" / "labels")]
import numpy as np

NAMES = ("target_mask", "ee_gripper_mask", "ee_tip_mask")


def export(path):
    import zarr
    stem = "omx_sim_train_v2"
    lab = np.load(ROOT / f"sim_umi/data/sidecars/{stem}.labels.npz")
    mz = zarr.open(zarr.ZipStore(str(ROOT / f"sim_umi/data/sidecars/{stem}.oracle_masks_g0.zarr.zip"), mode="r"), "r")
    out = {}
    for n, di in enumerate((3, 40)):
        rows = np.flatnonzero(lab["row_source_demo_id"] == di)
        out[f"d{n}_path"] = np.array(str(lab["demo_path"][di]))
        out[f"d{n}_frames"] = lab["row_source_frame_idx"][rows]
        out[f"d{n}_rows"] = rows
        out[f"d{n}_ev"] = np.array([lab["demo_lift_start_idx"][di], lab["demo_open_start_idx"][di]])
        for name in NAMES + ("ee_finger_y_mm",):
            out[f"d{n}_{name}"] = mz[f"data/{name}"].get_orthogonal_selection((rows, slice(None), slice(None)))
    np.savez_compressed(path, **out)
    print("exported", {k: v.shape for k, v in out.items() if k.endswith("_rows")})


def check(path, out_json):
    import build_oracle_masks as B
    z = np.load(path)
    rep, ok = {}, True
    for n in (0, 1):
        job = (str(z[f"d{n}_path"]), z[f"d{n}_frames"].tolist(), z[f"d{n}_rows"].tolist(),
               int(z[f"d{n}_ev"][0]), int(z[f"d{n}_ev"][1]))
        r = B.work(job)
        res = {name: int((z[f"d{n}_{name}"] != r["masks"][name]).any((1, 2)).sum()) for name in NAMES}
        res["ee_finger_y_mm"] = int((z[f"d{n}_ee_finger_y_mm"] != r["ymap"]).any((1, 2)).sum())
        res["rows"] = len(job[2])
        rep[job[0]] = res
        ok &= all(v == 0 for k, v in res.items() if k != "rows")
        print(job[0], res, flush=True)
    import cv2
    pathlib.Path(out_json).write_text(json.dumps({"verdict": "PASS" if ok else "FAIL", "python": sys.version.split()[0],
                                                  "cv2": cv2.__version__, "mismatching_rows": rep}, indent=1))
    print("CROSS-ENV", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(sys.argv[2])
    else:
        check(sys.argv[2], sys.argv[3])
