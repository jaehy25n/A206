"""G1 / G2 training zarrs from the same source frames as G0, and a full check
that the source frames ARE G0's.

    python sim_umi/scripts/fov/build_geometry_zarr.py --workers 48

Everything except the image array is copied from the G0 zarr byte for byte
(low-dim arrays, episode_ends, groups), so labels, segments and sample windows
are G0's by construction. Images: every row of G0 comes from one row of a demo
npz (train + v2_train, cut into segments exactly as demos_to_umi_zarr does);
for each row this

  1. rebuilds G0's frame with the production center_crop_resize, encodes it
     with G0's own codec and compares the COMPRESSED bytes with G0's stored
     chunk (and the decoded pixels) -- all 22942 rows, not a sample;
  2. makes the G1 and G2 frames with rgb_geometry and encodes them with the
     same codec settings (JPEG-XL level 99, lossy, as G0 was trained on).

Any G0 mismatch stops the build before anything is written.
"""
import hashlib
import json
import pathlib
import sys
import time
from multiprocessing import Pool

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(ROOT), str(SIM / "scripts"), str(SIM / "src")]

import click
import numpy as np
import zarr

from diffusion_policy.codecs.imagecodecs_numcodecs import JpegXl, register_codecs

register_codecs()
from demos_to_umi_zarr import MAX_STEP_S, MIN_SEGMENT, center_crop_resize  # noqa: E402
import rgb_geometry as G  # noqa: E402

G0_ZARR = SIM / "data/omx_sim_train_v2.zarr.zip"
OUT = {"g1_letterbox224": SIM / "data/omx_sim_train_v2_g1_letterbox224.zarr.zip",
       "g2_rect288x176": SIM / "data/omx_sim_train_v2_g2_rect288x176.zarr.zip"}
SOURCES = ("train", "v2_train")
KEY = "data/camera0_rgb"


def segments():
    out, g = [], 0
    for dname in SOURCES:
        for p in sorted((SIM / "data/demos" / dname).glob("episode_*.npz")):
            t = np.load(p, allow_pickle=True)["t"]
            n = len(t)
            cuts = [0] + list(np.flatnonzero(np.diff(t) > MAX_STEP_S) + 1) + [n]
            for a, b in zip(cuts[:-1], cuts[1:]):
                if b - a >= MIN_SEGMENT:
                    out.append((g, str(p), a, b))
                    g += b - a
    return out


def work(seg):
    g0_start, p, a, b = seg
    codec = JpegXl(level=99, numthreads=1)
    src = zarr.ZipStore(str(G0_ZARR), mode="r")
    rgb = np.load(p, allow_pickle=True)["rgb"]
    res = []
    for r in range(a, b):
        i = g0_start + (r - a)
        f = rgb[r]
        g0 = center_crop_resize(f, (224, 224))
        enc0 = codec.encode(np.ascontiguousarray(g0[None]))
        stored = src[f"{KEY}/{i}.0.0.0"]
        bytes_eq = bytes(enc0) == bytes(stored)
        dec_eq = bool(np.array_equal(np.asarray(codec.decode(stored)).reshape(g0.shape), g0)) if not bytes_eq else True
        pix_eq = bool(np.array_equal(np.asarray(codec.decode(enc0)).reshape(g0.shape),
                                     np.asarray(codec.decode(stored)).reshape(g0.shape)))
        enc = {name: bytes(codec.encode(np.ascontiguousarray(G.apply(name, f)[None]))) for name in OUT}
        res.append((i, bytes_eq, pix_eq, enc))
    src.close()
    return res


@click.command()
@click.option("--workers", default=48)
def main(workers):
    t0 = time.time()
    segs = segments()
    src = zarr.ZipStore(str(G0_ZARR), mode="r")
    root = zarr.group(src)
    ends = root["meta"]["episode_ends"][:]
    N = int(ends[-1])
    lens = [b - a for _, _, a, b in segs]
    if lens != np.diff(np.r_[0, ends]).tolist():
        raise SystemExit("segmentation does not reproduce G0's episode_ends -- STOP")
    print(f"{len(segs)} segments, {N} rows; source dirs {SOURCES}", flush=True)
    results = {}
    with Pool(workers) as pool:
        for k, res in enumerate(pool.imap_unordered(work, segs)):
            for i, beq, peq, enc in res:
                results[i] = (beq, peq, enc)
            if k % 10 == 0:
                print(f"  {k + 1}/{len(segs)} segments, {len(results)} rows, {time.time() - t0:.0f} s", flush=True)
    assert sorted(results) == list(range(N))
    n_bytes = sum(v[0] for v in results.values())
    n_pix = sum(v[1] for v in results.values())
    print(f"G0 reproduction over all {N} rows: compressed bytes identical {n_bytes}/{N}, "
          f"decoded pixels identical {n_pix}/{N}", flush=True)
    if n_pix != N:
        raise SystemExit("G0 NOT REPRODUCED FROM THE SOURCE FRAMES -- STOP, nothing written")
    zarray = json.loads(src[f"{KEY}/.zarray"])
    for name, path in OUT.items():
        W, H = G.GEOMETRIES[name]["canvas_wh"]
        if path.exists():
            raise SystemExit(f"{path} exists -- not overwriting")
        dst = zarr.ZipStore(str(path), mode="w")
        for k in src.keys():
            if not k.startswith(KEY + "/"):
                dst[k] = src[k]                      # low-dim, meta, groups: G0's bytes
        za = dict(zarray)
        za["shape"] = [N, H, W, 3]
        za["chunks"] = [1, H, W, 3]
        dst[f"{KEY}/.zarray"] = json.dumps(za, indent=4, sort_keys=True).encode()
        for i in range(N):
            dst[f"{KEY}/{i}.0.0.0"] = results[i][2][name]
        dst.close()
        print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
    src.close()
    # sidecar provenance (outside the zarr, so its structure stays G0's)
    for name, path in OUT.items():
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        side = {"geometry": name, "definition": G.GEOMETRIES[name], "pad": G.PAD,
                "content_box_x0y0x1y1": G.content_box(name), "source_zarr_for_non_image_keys": str(G0_ZARR),
                "source_frames": [f"sim_umi/data/demos/{d}" for d in SOURCES],
                "codec": zarray["compressor"], "rows": N, "segments": len(segs),
                "g0_reproduction": {"compressed_bytes_identical": n_bytes, "decoded_identical": n_pix, "rows": N},
                "sha256": h, "built_seconds": round(time.time() - t0, 1)}
        pathlib.Path(str(path) + ".json").write_text(json.dumps(side, indent=1))
        print(name, "sha256", h[:16], flush=True)


if __name__ == "__main__":
    main()
