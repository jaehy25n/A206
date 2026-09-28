"""Validation of the label + ORACLE mask sidecars (no GPU, no simulator).

    python sim_umi/scripts/labels/validate_sidecars.py --split train --out <dir>

1. mapping   every zarr row's decoded RGB against the G0 frame rebuilt from its
             mapped source demo frame (and against the neighbouring source frame,
             so the check can tell frames apart); 30 random rows re-encoded with
             the G0 codec and compared byte for byte; a picture of those 30.
2. overlays  12 rows per 5-stage phase (60), zarr RGB + target (red) / gripper
             (green) / tip (blue) + the 14x14 ViT grid, each beside the same row
             after one random train crop (212 -> 224) applied to RGB and masks
             with a single offset (oracle_masks.crop_resize_pair); plus a 3x zoom
             of target boundaries.
3. stats     visibility, empty-mask reasons, ViT patch occupancy -- by phase and
             by expert stage -- into <dir>/<stem>_stats.json.
"""
import json
import pathlib
import sys
from multiprocessing import Pool

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(ROOT), str(SIM / "src"), str(SIM / "scripts")]

import click
import cv2
import numpy as np
import zarr

from diffusion_policy.codecs.imagecodecs_numcodecs import JpegXl, register_codecs  # noqa: E402

register_codecs()
from demos_to_umi_zarr import center_crop_resize  # noqa: E402
import oracle_masks as OM  # noqa: E402

SIDE = SIM / "data" / "sidecars"
SPLITS = {"train": "omx_sim_train_v2", "val": "omx_sim_val_v2", "val_clean": "omx_sim_val"}
MASKS = ("target_mask", "ee_gripper_mask", "ee_tip_mask")
COL = {"target_mask": (255, 40, 40), "ee_gripper_mask": (40, 220, 40), "ee_tip_mask": (40, 90, 255)}


def _mapping_worker(args):
    stem, p, rows, frames = args
    rgb = zarr.open(zarr.ZipStore(str(SIM / "data" / f"{stem}.zarr.zip"), mode="r"), "r")["data/camera0_rgb"]
    src = np.load(ROOT / p, allow_pickle=True)["rgb"]
    own, nb = [], []
    for r, f in zip(rows, frames):
        zimg = rgb[r].astype(np.int16)
        own.append(np.abs(zimg - center_crop_resize(src[f], (224, 224))).mean())
        g = f + 1 if f + 1 < len(src) else f - 1
        nb.append(np.abs(zimg - center_crop_resize(src[g], (224, 224))).mean())
    return rows, own, nb


def overlay(img, masks, grid=True, fill=0.45):
    out = img.copy()
    for name in MASKS:
        m = masks[name].astype(bool)
        if name == "ee_gripper_mask":
            m = m & ~masks["ee_tip_mask"].astype(bool)
        out[m] = ((1 - fill) * out[m] + fill * np.array(COL[name])).astype(np.uint8)
        cnt, _ = cv2.findContours(masks[name].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(out, cnt, -1, COL[name], 1)
    if grid:
        for g in range(0, 224, OM.PATCH):
            out[g, :] = (out[g, :] * 0.6 + 255 * 0.4).astype(np.uint8)
            out[:, g] = (out[:, g] * 0.6 + 255 * 0.4).astype(np.uint8)
    return out


def label(img, lines):
    out = img.copy()
    for i, s in enumerate(lines):
        cv2.putText(out, s, (3, 12 + 12 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(out, s, (3, 12 + 12 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 0), 1, cv2.LINE_AA)
    return out


@click.command()
@click.option("--split", type=click.Choice(list(SPLITS)), default="train")
@click.option("--out", required=True)
@click.option("--workers", default=32)
def main(split, out, workers):
    import torch
    stem = SPLITS[split]
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    lab = np.load(SIDE / f"{stem}.labels.npz")
    mz = zarr.open(zarr.ZipStore(str(SIDE / f"{stem}.oracle_masks_g0.zarr.zip"), mode="r"), "r")
    rgbz = zarr.open(zarr.ZipStore(str(SIM / "data" / f"{stem}.zarr.zip"), mode="r"), "r")["data/camera0_rgb"]
    N = len(lab["row_zarr_row_idx"])
    ph, es = lab["row_phase_5"], lab["row_expert_stage_10"]
    PH, ES = [str(x) for x in lab["phase_5_names"]], [str(x) for x in lab["expert_stage_10_names"]]
    dp = lab["demo_path"]
    rep = {"split": split, "rows": int(N)}

    # ------------------------------------------------------------ 1. mapping
    jobs = []
    for di in np.unique(lab["row_source_demo_id"]):
        rows = np.flatnonzero(lab["row_source_demo_id"] == di)
        jobs.append((stem, str(dp[di]), rows.tolist(), lab["row_source_frame_idx"][rows].tolist()))
    own, nb = np.zeros(N), np.zeros(N)
    with Pool(workers) as pool:
        for rows, o, n_ in pool.imap_unordered(_mapping_worker, jobs):
            own[rows], nb[rows] = o, n_
    rng = np.random.default_rng(0)
    pick = np.sort(rng.choice(N, 30, replace=False))
    codec = JpegXl(level=99, numthreads=1)
    store = zarr.ZipStore(str(SIM / "data" / f"{stem}.zarr.zip"), mode="r")
    tiles, byte_eq = [], []
    for r in pick:
        p, f = str(dp[lab["row_source_demo_id"][r]]), int(lab["row_source_frame_idx"][r])
        z = np.load(ROOT / p, allow_pickle=True)
        g0 = center_crop_resize(z["rgb"][f], (224, 224))
        byte_eq.append(bytes(codec.encode(np.ascontiguousarray(g0[None]))) == bytes(store[f"data/camera0_rgb/{r}.0.0.0"]))
        zimg = rgbz[r]
        diff = np.clip(np.abs(zimg.astype(int) - g0.astype(int)) * 8, 0, 255).astype(np.uint8)
        a = label(g0, [f"SOURCE {pathlib.Path(p).parent.name}/{pathlib.Path(p).stem[-4:]} f{f}",
                       f"t={z['t'][f]:.2f}s {z['stage'][f]}"])
        b = label(zimg, [f"ZARR row {r} ep {lab['row_zarr_episode_idx'][r]}",
                         f"t={lab['row_timestamp_s'][r]:.2f}s {ES[es[r]]} / {PH[ph[r]]}"])
        c = label(diff, [f"|diff|x8 mean {np.abs(zimg.astype(int) - g0.astype(int)).mean():.2f}"])
        tiles.append(np.concatenate([a, b, c], 1))
        assert z["stage"][f] == ES[es[r]] and abs(z["t"][f] - lab["row_timestamp_s"][r]) == 0
    store.close()
    sheet = np.concatenate([np.concatenate(tiles[i:i + 2], 1) for i in range(0, 30, 2)], 0)
    cv2.imwrite(str(out / f"{stem}_mapping_30.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    rep["mapping"] = {
        "all_rows_rgb_mad_to_mapped_source": {"median": round(float(np.median(own)), 3), "max": round(float(own.max()), 3)},
        "all_rows_rgb_mad_to_neighbour_source_frame": {"median": round(float(np.median(nb)), 3), "min": round(float(nb.min()), 3)},
        "rows_where_neighbour_matches_better": int((nb <= own).sum()),
        "random30_rows": pick.tolist(), "random30_reencode_bytes_equal": f"{sum(byte_eq)}/30",
        "random30_stage_and_timestamp_equal": "30/30"}

    # ----------------------------------------------------------- 3. stats
    px = {k: mz[f"stats/{k}_px_224"][:] for k in MASKS}
    reason = mz["stats/target_empty_reason"][:]
    rnames = list(mz.attrs["target_empty_reason_codes"])
    patches = {k: np.zeros(N, np.int16) for k in MASKS}
    half = {k: np.zeros(N, np.int16) for k in MASKS}
    B = 512
    for s in range(0, N, B):
        for k in MASKS:
            occ = OM.patch_occupancy(mz[f"data/{k}"][s:s + B])
            patches[k][s:s + B] = (occ > 0).sum(-1)
            half[k][s:s + B] = (occ >= 0.5).sum(-1)
    S = lab["row_is_sample_current"]
    valid = mz["data/target_mask_valid"][:].astype(bool)
    psrc = mz["data/target_pose_source"][:]
    pnames = list(mz.attrs["target_pose_source_codes"])

    def summ(sel):
        d = {"rows": int(sel.sum()), "target_mask_valid_rows": int((sel & valid).sum()),
             "target_pose_source": {pnames[i]: int((psrc[sel] == i).sum()) for i in range(len(pnames)) if (psrc[sel] == i).any()}}
        for k in MASKS:
            ks = sel & valid if k == "target_mask" else sel
            if not ks.any():
                d[k] = None
                continue
            v, pt, hf = px[k][ks], patches[k][ks], half[k][ks]
            d[k] = {"visible_ratio(>=12px)": round(float((v >= 12).mean()), 4), "empty_ratio": round(float((v == 0).mean()), 4),
                    "px224_median": float(np.median(v)), "patches_touched_mean": round(float(pt.mean()), 2),
                    "patches_touched_median": float(np.median(pt)), "patches_half_covered_mean": round(float(hf.mean()), 2),
                    "patches_touched_median_when_visible": float(np.median(pt[v >= 12])) if (v >= 12).any() else None}
        rr = reason[sel & valid]
        d["target_empty_reasons_valid_rows"] = {rnames[i]: int((rr == i).sum()) for i in range(1, len(rnames)) if (rr == i).any()}
        return d
    rep["stats_all_rows"] = summ(np.ones(N, bool))
    rep["stats_training_samples"] = summ(S)
    rep["stats_by_phase"] = {PH[i]: summ(ph == i) for i in range(5)}
    rep["stats_by_expert_stage"] = {ES[i]: summ(es == i) for i in range(10) if (es == i).any()}
    qa = {k: mz[f"qa/{k}"][:] for k in mz["qa"].array_keys()}
    rep["qa"] = {k: {"median": round(float(np.nanmedian(v)), 3), "p95": round(float(np.nanpercentile(v, 95)), 3),
                     "max": round(float(np.nanmax(v)), 3)} for k, v in qa.items() if k != "recorded_object_visible"}
    rep["qa_by_phase_target_band_mad_valid_rows"] = {
        PH[i]: {"median": round(float(np.nanmedian(qa["target_band_mad"][(ph == i) & valid])), 2),
                "p95": round(float(np.nanpercentile(qa["target_band_mad"][(ph == i) & valid], 95)), 2)}
        for i in range(5) if ((ph == i) & valid & np.isfinite(qa["target_band_mad"])).any()}
    fits = json.loads((SIDE / f"{stem}.oracle_masks_g0.json").read_text())["rigid_fit_per_demo"]
    F = lambda key: np.array([f[key] for f in fits.values() if f[key] is not None], float)
    rep["rigid_T_ee_obj"] = {
        "demos": len(fits), "fallback_to_all_frames": int(sum(f["fallback_all_frames"] for f in fits.values())),
        "static_frames_per_demo_min_median": [int(F("static_frames").min()), float(np.median(F("static_frames")))],
        "T_ee_obj_mm_min": np.array([f["T_ee_obj_mm"] for f in fits.values()]).min(0).round(2).tolist(),
        "T_ee_obj_mm_max": np.array([f["T_ee_obj_mm"] for f in fits.values()]).max(0).round(2).tolist(),
        "residual_static_mm_median_max": [round(float(np.median(F("residual_static_mm_median"))), 3), round(float(F("residual_static_mm_max").max()), 3)],
        "residual_all_secure_hold_mm_median_p95_max": [round(float(np.median(F("residual_all_mm_median"))), 2),
                                                       round(float(np.median(F("residual_all_mm_p95"))), 2), round(float(F("residual_all_mm_max").max()), 2)],
        "median_all_minus_static_mm_max": round(float(F("median_all_minus_static_mm").max()), 2),
        "invalid_release_frames_per_demo": {int(a): int(c) for a, c in zip(*np.unique(F("invalid_frames").astype(int), return_counts=True))}}
    ours = mz["stats/target_mask_px_crop"][:] >= 12
    recv = qa["recorded_object_visible"].astype(bool)
    rep["qa"]["recorded_visibility_flag_agreement"] = {"agree": round(float((ours == recv).mean()), 5),
                                                       "recorded_only": int((recv & ~ours).sum()), "oracle_only": int((~recv & ours).sum())}

    # --------------------------------------------------------- 2. overlays
    rng = np.random.default_rng(1)
    chosen = {i: np.sort(rng.choice(np.flatnonzero(ph == i), 12, replace=False)) for i in range(5)}
    crops = []
    for i in range(5):
        tiles = []
        for r in chosen[i]:
            img = rgbz[r]
            ms = {k: mz[f"data/{k}"][r] for k in MASKS}
            top, left = (int(x) for x in rng.integers(0, 224 - OM.TRAIN_CROP + 1, 2))
            rt = torch.from_numpy(img).permute(2, 0, 1)[None].float() / 255
            mt = torch.from_numpy(np.stack([ms[k] for k in MASKS]))[None]
            ra, ma = OM.crop_resize_pair(rt, mt, top, left)
            ia = (ra[0].permute(1, 2, 0).numpy() * 255).round().clip(0, 255).astype(np.uint8)
            msa = {k: ma[0, j].numpy().astype(bool) for j, k in enumerate(MASKS)}
            crops.append((int(r), top, left))
            a = label(overlay(img, ms), [f"row {r} {PH[i]}", f"{ES[es[r]]} f{lab['row_source_frame_idx'][r]}",
                                         f"px T{px['target_mask'][r]} G{px['ee_gripper_mask'][r]} t{px['ee_tip_mask'][r]}",
                                         f"target {pnames[psrc[r]]}" + ("" if valid[r] else "  INVALID")])
            b = label(overlay(ia, msa), [f"train crop top {top} left {left}", "RGB bilinear, masks nearest"])
            tiles.append(np.concatenate([a, b], 1))
        sheet = np.concatenate([np.concatenate(tiles[j:j + 2], 1) for j in range(0, 12, 2)], 0)
        cv2.imwrite(str(out / f"{stem}_overlay_phase{i}_{PH[i]}.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
    # 3x zoom on target boundaries (contour only)
    zoom = []
    for r in np.concatenate([chosen[i][:2] for i in range(5)]):
        m = mz["data/target_mask"][r]
        if m.sum() < 12:
            continue
        ys, xs = np.nonzero(m)
        cy, cx = int(np.clip(ys.min(), 32, 224 - 32)), int(np.clip((xs.min() + xs.max()) // 2, 32, 224 - 32))
        img = rgbz[r].copy()
        cnt, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        big = cv2.resize(img[cy - 32:cy + 32, cx - 32:cx + 32], (192, 192), interpolation=cv2.INTER_NEAREST)
        mb = cv2.resize(m[cy - 32:cy + 32, cx - 32:cx + 32].astype(np.uint8), (192, 192), interpolation=cv2.INTER_NEAREST)
        cnt, _ = cv2.findContours(mb, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(big, cnt, -1, (255, 0, 0), 1)
        zoom.append(label(big, [f"row {r} {PH[ph[r]]}"]))
    if zoom:
        cv2.imwrite(str(out / f"{stem}_target_boundary_zoom3x.jpg"),
                    cv2.cvtColor(np.concatenate([np.concatenate(zoom[j:j + 5], 1) for j in range(0, len(zoom) - len(zoom) % 5, 5)], 0),
                                 cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    rep["overlay_rows"] = {PH[i]: chosen[i].tolist() for i in range(5)}
    rep["overlay_train_crops(row,top,left)"] = crops
    (out / f"{stem}_stats.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("mapping", "qa")}, indent=1))


if __name__ == "__main__":
    main()
