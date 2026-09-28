"""ORACLE target / EE masks for every row of a zarr, G0 geometry, as a sidecar.

    MUJOCO_GL=egl python sim_umi/scripts/labels/build_oracle_masks.py --split train [--limit-demos 2]

Needs the split's labels sidecar (build_label_sidecar.py) for the row mapping.
Writes, never overwriting and never touching the zarr:
    sim_umi/data/sidecars/<zarr stem>.oracle_masks_g0.zarr.zip
    sim_umi/data/sidecars/<zarr stem>.oracle_masks_g0.json

Source (audited, see the prep report): MuJoCo segmentation render of the wrist
camera of collector_scene.xml -- the very model the plant simulator loads
(omx_f_mujoco.urdf <mujoco_model>) -- posed per row at the recorded instant:
arm joints recovered exactly from the recorded TCP pose (oracle_state), jaw
from the true jaw width, ball from eval_ball_pos, bin from the spec. No learned
model, no colour threshold.
    target_mask      pixels of geom object_geom (the ball) -- occlusion included
    ee_gripper_mask  pixels of every geom of bodies left_finger, right_finger
                     (finger meshes + tip patches; the contact pads are
                     invisible). These are the only visible gripper geoms.
    ee_tip_mask      the fingertips: the part of ee_gripper_mask whose surface
                     point (depth render, back-projected into its own finger's
                     body frame) lies at y >= TIP_Y0 = 50 mm, the distal 15 mm of
                     the 65 mm finger (the width detector's tip patch sits at
                     60.5 mm). The visible finger spans y ~26..64 mm and almost
                     all of it is the pad (contact) face, so a pad-proximity or
                     y >= 30 mm rule would just repeat ee_gripper_mask; the held
                     ball's centre is at y 37.7..42.6 mm over all 91 demos.
    ee_finger_y_mm   uint8, the finger-frame y (mm, rounded, >= 1) of every
                     ee_gripper_mask pixel, 0 elsewhere -- so another tip band
                     (e.g. the contact band 35..45 mm) is a threshold away,
                     without re-rendering.
Masks are rendered at 320x180 WITHOUT multisampling (exact per-pixel geom ids)
and carried through G0 (oracle_masks.g0_mask, nearest).

Target pose per row (the recorded ball position is the latest message of a 20 Hz
free-joint publisher, 0..50 ms older than the picture, so it is only right when
the ball is still or when its motion is known):
    0 recorded       before the secure lift-off (free / static ball, being
                     gripped) and after the released ball has come to rest:
                     the recorded GT position of that row
    1 rigid_ee       object_lifted .. open_start-1 (held; TRANSPORT and the PLACE
                     hold): TCP pose of the row (exact, image instant) composed
                     with a per-demo T_EE->object = per-axis median of the
                     tool-frame ball offset over the STATIC secure-hold frames
                     (TCP speed < 5 mm/s, 14-16 per demo), where the publisher
                     lag cannot matter; all secure-hold frames' residuals kept
    2 invalid        open_start .. the ball at rest again (falling / bouncing):
                     target_mask_valid = False -- excluded from relation
                     supervision; the mask stored there is the recorded-pose
                     render, for pictures only
    3 invalid        no GT ball position
The ball is a sphere, so T_EE->object is a translation. No interpolation,
ballistic fit or RGB-driven alignment is used.

Per row it also records QA against the recorded picture: the mean absolute
difference between a mirror RGB render of the same state and the recorded RGB
(inside the G0 crop, tip patches excluded -- the recording paints them out),
the same in a band around the target / gripper boundary, the depth consistency
of the target (back-projected target pixels vs the ball's surface), and why an
empty target is empty (out of the camera, outside the G0 crop, occluded, no GT).
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from multiprocessing import Pool

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")   # the simulator's render GPU, never GPU 5

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(ROOT), str(SIM / "src"), str(SIM / "scripts")]

import click
import numpy as np

import oracle_masks as OM  # noqa: E402

OUT_DIR = SIM / "data" / "sidecars"
SPLITS = {"train": "omx_sim_train_v2", "val": "omx_sim_val_v2", "val_clean": "omx_sim_val"}
from oracle_render import TIP_Y0, FINGER_BOX_LO, FINGER_BOX_HI  # noqa: E402  (one definition)
VISIBLE_MIN_PX = 12
MASKS = ("target_mask", "ee_gripper_mask", "ee_tip_mask")
STATIC_TCP_MPS = 0.005
MIN_STATIC_FRAMES = 5
DROP_M = 0.010
REST_STEP_M = 0.001
POSE_SOURCES = ("recorded", "rigid_ee", "invalid_release_to_rest", "invalid_no_gt")


def target_track(z, lift, open_):
    """Per-frame ball position to render, its source code, and the per-demo rigid fit."""
    t = z["t"].astype(np.float64)
    P, R = z["eef_pos"].astype(np.float64), z["eef_rot"].astype(np.float64)
    b = z["eval_ball_pos"].astype(np.float64)
    n = len(t)
    k = np.arange(lift, open_)
    v = np.array([np.linalg.norm(P[min(i + 1, n - 1)] - P[max(i - 1, 0)]) / (t[min(i + 1, n - 1)] - t[max(i - 1, 0)]) for i in k])
    off = np.einsum("kji,kj->ki", R[k], b[k] - P[k])
    ok = np.all(np.isfinite(off), 1)
    static = ok & (v < STATIC_TCP_MPS)
    use = static if static.sum() >= MIN_STATIC_FRAMES else ok
    o = np.median(off[use], 0)
    res_all = np.linalg.norm(off[ok] - o, axis=1) * 1000
    res_st = np.linalg.norm(off[static] - o, axis=1) * 1000
    used = b.copy()
    src = np.zeros(n, np.int8)
    used[k] = P[k] + np.einsum("kij,j->ki", R[k], o)
    src[k] = 1
    # after the jaw opens: invalid until the ball has fallen DROP_M and is at rest again
    zc = b[open_, 2]
    drop = next((i for i in range(open_, n) if np.isfinite(b[i, 2]) and b[i, 2] < zc - DROP_M), None)
    step = np.r_[np.linalg.norm(np.diff(b, axis=0), axis=1), np.inf]
    rest = None
    if drop is not None:
        rest = next((i for i in range(drop, n - 1) if max(step[i - 1], step[i]) < REST_STEP_M), None)
    end = rest if rest is not None else n
    src[open_:end] = 2
    src[~np.all(np.isfinite(b), 1)] = 3
    fit = {"T_ee_obj_mm": (o * 1000).round(3).tolist(), "static_frames": int(static.sum()),
           "secure_hold_frames": int(ok.sum()), "fallback_all_frames": bool(static.sum() < MIN_STATIC_FRAMES),
           "residual_static_mm_median": float(np.median(res_st)) if len(res_st) else None,
           "residual_static_mm_max": float(res_st.max()) if len(res_st) else None,
           "residual_all_mm_median": float(np.median(res_all)), "residual_all_mm_p95": float(np.percentile(res_all, 95)),
           "residual_all_mm_max": float(res_all.max()),
           "median_all_minus_static_mm": float(np.linalg.norm(np.median(off[ok], 0) - o) * 1000),
           "drop_idx": -1 if drop is None else int(drop), "rest_idx": -1 if rest is None else int(rest),
           "invalid_frames": int((src == 2).sum())}
    return used, src, fit
EMPTY_REASONS = ("not_empty", "outside_camera_frustum", "in_frame_outside_g0_crop", "occluded", "no_gt_pose")

_W = {}


def _init():
    from oracle_render import OracleRenderer
    R = OracleRenderer()
    _W.update(R=R, k=R.k, m=R.m, S=R.S, d=R.d, obj=R.obj, lf=R.lf, rf=R.rf, tips=R.tips, lb=R.lb, rb=R.rb,
              cid=R.cid, f=R.f, geom_t=R.geom_t)


def _band(mask, r=2):
    import cv2
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    m = mask.astype(np.uint8)
    return (cv2.dilate(m, k) - cv2.erode(m, k)).astype(bool)


def work(job):
    """One source demo: rebuild its states, render the rows that are in the zarr."""
    if not _W:
        _init()
    import cv2
    p, frames, zrows, lift, open_ = job
    S, m, d, k = _W["S"], _W["m"], _W["d"], _W["k"]
    W, H = OM.RAW_WH
    st = S.reconstruct(str(ROOT / p))
    z = np.load(ROOT / p, allow_pickle=True)
    ball_used, pose_src, fit = target_track(z, lift, open_)
    rec_rgb, rec_vis, r_ball = z["rgb"], z["eval_object_visible"], st["spec"]["ball_r"]
    u = (np.arange(W) + 0.5 - W / 2) / _W["f"]
    v = -(np.arange(H) + 0.5 - H / 2) / _W["f"]
    x0, x1 = OM.G0_X0, OM.G0_X0 + OM.G0_SIDE
    n = len(frames)
    out = {name: np.zeros((n, OM.G0_OUT, OM.G0_OUT), bool) for name in MASKS}
    stats = {key: np.zeros(n, np.float32) for key in (
        "rgb_mad_crop", "target_band_mad", "gripper_band_mad", "target_depth_err_mm_median")}
    cnt = {f"{name}_px_{where}": np.zeros(n, np.int32) for name in MASKS for where in ("raw", "crop", "224")}
    reason = np.zeros(n, np.int8)
    yout = np.zeros((n, OM.G0_OUT, OM.G0_OUT), np.uint8)
    qa_px = {"gripper_px_off_finger_box": np.zeros(n, np.int32), "target_px_off_ball_surface": np.zeros(n, np.int32)}
    for j, fr in enumerate(frames):
        ball = ball_used[fr]
        S.pose(d, st["q"][fr], st["gripper_theta"][fr], ball, st["bin_pose"])
        rr = _W["R"].render(d)                                  # the one mask implementation
        ids, pts, im = rr["ids"], rr["pts"], rr["im"]
        cp, cR = d.cam_xpos[_W["cid"]], d.cam_xmat[_W["cid"]].reshape(3, 3)   # for the empty-target reason
        tgt, grip = rr["raw"]["target_mask"], rr["raw"]["ee_gripper_mask"]
        yout[j] = rr["ymap_g0"]
        qa_px["gripper_px_off_finger_box"][j] = rr["off_box"]
        for name, mk in rr["raw"].items():
            g = rr["g0"][name]
            out[name][j] = g
            cnt[f"{name}_px_raw"][j] = mk.sum()
            cnt[f"{name}_px_crop"][j] = mk[:, x0:x1].sum()
            cnt[f"{name}_px_224"][j] = g.sum()
        # QA against the recorded picture (the recording paints the tip patches out)
        rec = rec_rgb[fr]
        keep = ~cv2.dilate(np.isin(ids, _W["tips"]).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        diff = np.abs(im.astype(np.int16) - rec.astype(np.int16)).mean(-1)
        crop = np.zeros_like(keep); crop[:, x0:x1] = True
        stats["rgb_mad_crop"][j] = diff[crop & keep].mean()
        for key, mk in (("target_band_mad", tgt), ("gripper_band_mad", grip)):
            bd = _band(mk) & crop & keep
            stats[key][j] = diff[bd].mean() if bd.any() else np.nan
        if tgt.any() and np.all(np.isfinite(ball)):
            err = np.abs(np.linalg.norm(pts[tgt] - ball, axis=1) - r_ball)
            stats["target_depth_err_mm_median"][j] = np.median(err) * 1000
            qa_px["target_px_off_ball_surface"][j] = int((err > 0.002).sum())
        else:
            stats["target_depth_err_mm_median"][j] = np.nan
        # why an empty target is empty
        if cnt["target_mask_px_224"][j] > 0:
            reason[j] = 0
        elif not np.all(np.isfinite(ball)):
            reason[j] = 4
        else:
            c = cR.T @ (ball - cp)
            inside = c[2] < 0 and abs(c[0] / -c[2] * _W["f"]) < W / 2 + r_ball / -c[2] * _W["f"] \
                and abs(c[1] / -c[2] * _W["f"]) < H / 2 + r_ball / -c[2] * _W["f"]
            reason[j] = 1 if not inside else (2 if tgt.any() else 3)
    stats.update(qa_px)
    stats["target_recorded_vs_used_mm"] = (np.linalg.norm(st["ball_pos"][frames] - ball_used[frames], axis=1) * 1000).astype(np.float32)
    return {"p": p, "fit": fit, "pose_src": pose_src[frames], "zrows": np.asarray(zrows), "masks": out, "ymap": yout,
            "stats": stats, "cnt": cnt, "reason": reason,
            "rec_vis": rec_vis[frames].astype(bool),
            "state": {"arm_q": st["q"][frames], "gripper_theta": st["gripper_theta"][frames],
                      "ball_pos_recorded": st["ball_pos"][frames], "ball_pos_used": ball_used[frames],
                      "bin_pose": np.tile(st["bin_pose"], (n, 1)),
                      "ik_pos_err_m": st["ik_pos_err_m"][frames], "ik_rot_err_deg": st["ik_rot_err_deg"][frames]}}


@click.command()
@click.option("--split", type=click.Choice(list(SPLITS)), required=True)
@click.option("--workers", default=24)
@click.option("--limit-demos", default=0, help="smoke: only the first N demos, written to a scratch path")
@click.option("--out", default=None, help="override the output path (smoke runs)")
def main(split, workers, limit_demos, out):
    import zarr
    from numcodecs import Blosc
    stem = SPLITS[split]
    lab = np.load(OUT_DIR / f"{stem}.labels.npz")
    N = len(lab["row_zarr_row_idx"])
    out_z = pathlib.Path(out) if out else OUT_DIR / f"{stem}.oracle_masks_g0.zarr.zip"
    out_j = out_z.with_name(out_z.name.replace(".zarr.zip", ".json"))
    if out_z.exists() or out_j.exists():
        raise click.ClickException(f"{out_z} exists -- not overwriting")
    demo_paths = lab["demo_path"]
    jobs = []
    for di, p in enumerate(demo_paths):
        rows = np.flatnonzero(lab["row_source_demo_id"] == di)
        if len(rows):
            jobs.append((str(p), lab["row_source_frame_idx"][rows].tolist(), rows.tolist(),
                         int(lab["demo_lift_start_idx"][di]), int(lab["demo_open_start_idx"][di])))
    if limit_demos:
        jobs = jobs[:limit_demos]
    t0 = time.time()
    store = zarr.ZipStore(str(out_z), mode="w")
    root = zarr.group(store)
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
    arr = {name: root.zeros(f"data/{name}", shape=(N, OM.G0_OUT, OM.G0_OUT), chunks=(1, OM.G0_OUT, OM.G0_OUT),
                            dtype=bool, compressor=comp, write_empty_chunks=True) for name in MASKS}
    yarr = root.zeros("data/ee_finger_y_mm", shape=(N, OM.G0_OUT, OM.G0_OUT), chunks=(1, OM.G0_OUT, OM.G0_OUT),
                      dtype=np.uint8, compressor=comp, write_empty_chunks=True)
    done = np.zeros(N, bool)
    small = {}
    fits = {}
    with Pool(workers) as pool:
        for r in pool.imap_unordered(work, jobs):
            zr = r["zrows"]
            for name in MASKS:
                for j, row in enumerate(zr):
                    arr[name][row] = r["masks"][name][j]
            for j, row in enumerate(zr):
                yarr[row] = r["ymap"][j]
            for group in ("stats", "cnt", "state"):
                for key, v in r[group].items():
                    if key not in small:
                        small[key] = np.full((N,) + v.shape[1:], np.nan if v.dtype.kind == "f" else -1, v.dtype)
                    small[key][zr] = v
            fits[r["p"]] = r["fit"]
            if "pose_src" not in small:
                small["pose_src"] = np.full(N, -1, np.int8)
            small["pose_src"][zr] = r["pose_src"]
            for key in ("reason", "rec_vis"):
                if key not in small:
                    small[key] = np.full(N, -1, np.int8)
                small[key][zr] = r[key]
            done[zr] = True
            print(f"  {r['p']}: {len(zr)} rows  ({done.sum()}/{N}, {time.time() - t0:.0f} s)", flush=True)
    if limit_demos == 0 and not done.all():
        raise click.ClickException(f"{(~done).sum()} rows not rendered")
    names = {"reason": "target_empty_reason", "rec_vis": "recorded_object_visible", "pose_src": "target_pose_source"}
    if "pose_src" in small:
        small["target_mask_valid"] = np.isin(small["pose_src"], (0, 1))
    for key, v in small.items():
        grp = "state" if key in ("arm_q", "gripper_theta", "ball_pos_recorded", "ball_pos_used", "bin_pose", "ik_pos_err_m",
                                 "ik_rot_err_deg") \
            else ("qa" if key in ("rgb_mad_crop", "target_band_mad", "gripper_band_mad", "target_depth_err_mm_median", "rec_vis",
                                  "gripper_px_off_finger_box", "target_px_off_ball_surface", "target_recorded_vs_used_mm")
                  else ("data" if key in ("pose_src", "target_mask_valid") else "stats"))
        root.array(f"{grp}/{names.get(key, key)}", v, chunks=v.shape, compressor=comp)
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    attrs = {"what": "ORACLE masks from simulator GT segmentation (no learned model); train-only prior, never a deployment input",
             "zarr": f"sim_umi/data/{stem}.zarr.zip", "labels_sidecar": f"sim_umi/data/sidecars/{stem}.labels.npz",
             "row_aligned": "row i of every data/* array is zarr row i", "geometry": "G0: raw 320x180 -> x 70..250 -> 224 nearest",
             "masks": {"target_mask": "geom object_geom", "ee_gripper_mask": "all geoms of bodies left_finger, right_finger",
                       "ee_tip_mask": f"ee_gripper_mask pixels at finger-frame y >= {TIP_Y0} m (distal 15 mm of the 65 mm finger)",
                       "ee_finger_y_mm": "uint8 finger-frame y in mm of each ee_gripper_mask pixel, 0 elsewhere"},
             "segmentation_multisampling": "off (exact per-pixel geom ids)",
             "target_empty_reason_codes": list(EMPTY_REASONS), "visible_min_px": VISIBLE_MIN_PX,
             "target_pose_source_codes": list(POSE_SOURCES),
             "target_mask_valid": "target_pose_source in (recorded, rigid_ee); False rows are excluded from relation supervision",
             "rigid_fit": {"static_tcp_mps": STATIC_TCP_MPS, "min_static_frames": MIN_STATIC_FRAMES,
                           "estimator": "per-axis median of the tool-frame ball offset over static secure-hold frames",
                           "release_invalid_until": f"ball fell {DROP_M * 1000:.0f} mm below its height at open_start and then moves < {REST_STEP_M * 1000:.0f} mm per frame"},
             "model": "sim_umi/mjcf/collector_scene.xml", "code": str(pathlib.Path(__file__).relative_to(ROOT)), "git": git,
             "rows": int(N), "rows_rendered": int(done.sum()), "seconds": round(time.time() - t0, 1)}
    root.attrs.update(attrs)
    order = [str(x) for x in demo_paths if str(x) in fits]
    for key in ("T_ee_obj_mm",):
        root.array(f"demo/{key}", np.array([fits[p_][key] for p_ in order]), compressor=comp)
    for key in ("static_frames", "secure_hold_frames", "drop_idx", "rest_idx", "invalid_frames"):
        root.array(f"demo/{key}", np.array([fits[p_][key] for p_ in order], np.int32), compressor=comp)
    for key in ("residual_static_mm_median", "residual_static_mm_max", "residual_all_mm_median", "residual_all_mm_p95",
                "residual_all_mm_max", "median_all_minus_static_mm"):
        root.array(f"demo/{key}", np.array([np.nan if fits[p_][key] is None else fits[p_][key] for p_ in order]), compressor=comp)
    root.array("demo/path", np.array(order), compressor=None, dtype=str)
    attrs["rigid_fit_per_demo"] = fits
    store.close()
    attrs["sha256"] = hashlib.sha256(out_z.read_bytes()).hexdigest()
    attrs["bytes"] = out_z.stat().st_size
    out_j.write_text(json.dumps(attrs, indent=1))
    print(json.dumps({k: attrs[k] for k in ("rows", "rows_rendered", "seconds", "bytes")}))


if __name__ == "__main__":
    main()
