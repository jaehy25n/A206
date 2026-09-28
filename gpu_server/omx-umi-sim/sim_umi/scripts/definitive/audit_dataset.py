"""Dataset preflight for the definitive runs, through the production path.

    python sim_umi/scripts/definitive/audit_dataset.py --out <file.json>

The config is composed by hydra from the same config file and the same
overrides the training runs will be launched with, the dataset is built by the
production UmiDataset class, and the DataLoader by the workspace's own
dataloader settings. Nothing is recomputed by hand: every count reported is
read off the objects training will use. That is the point -- the sampler count
was reported wrong twice in this project by computing it instead of reading it.
"""
import hashlib
import json
import math
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import zarr
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from torch.utils.data import DataLoader

from diffusion_policy.common.replay_buffer import ReplayBuffer

OmegaConf.register_new_resolver("eval", eval, replace=True)

CONFIG = "train_diffusion_unet_timm_omx_workspace"
CLEAN = ROOT / "sim_umi/data/omx_sim_train.zarr.zip"
COMBINED = ROOT / "sim_umi/data/omx_sim_train_v2.zarr.zip"
EXPECT = {"clean": {"segments": 25, "frames": 6455, "N": 6080},
          "combined": {"segments": 94, "frames": 22942, "N": 21532},
          "v2_train": {"segments": 69, "frames": 16487, "N": 15452}}


def sha256(p, chunk=1 << 22):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def segments(p):
    with zarr.ZipStore(str(p), mode="r") as zs:
        rb = ReplayBuffer.copy_from_store(src_store=zs, store=zarr.MemoryStore(),
                                          keys=["robot0_eef_pos"])
    e = rb.episode_ends[:]
    return np.diff(np.r_[0, e]).astype(int)


def build(path):
    with initialize_config_dir(version_base=None,
                               config_dir=str(ROOT / "diffusion_policy/config")):
        cfg = compose(config_name=CONFIG, overrides=[
            f"task.dataset_path={path}",
            "task.dataset.val_ratio=0.0",
            "training.seed=42"])
    OmegaConf.resolve(cfg)
    import hydra
    ds = hydra.utils.instantiate(cfg.task.dataset)
    dl = DataLoader(ds, **cfg.dataloader)
    return cfg, ds, dl


def main():
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "config": CONFIG,
           "checks": {}, "fail": []}
    for lab, path in (("clean", CLEAN), ("combined", COMBINED)):
        st = os.stat(path)
        L = segments(path)
        cfg, ds, dl = build(path)
        s = ds.sampler
        # which segments the production sampler actually drew from
        idx = np.array([i[0] for i in s.indices])
        ends = np.cumsum(L)
        used = np.unique(np.searchsorted(ends, idx, side="right"))
        rec = {"path": str(path), "bytes": st.st_size,
               "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
               "sha256": sha256(path),
               "segments": int(len(L)), "raw_frames": int(L.sum()),
               "sampler_len": int(len(s)), "dataset_len": int(len(ds)),
               "dataloader_len": int(len(dl)),
               "batch_size": int(cfg.dataloader.batch_size),
               "drop_last": bool(cfg.dataloader.get("drop_last", False)),
               "shuffle": bool(cfg.dataloader.shuffle),
               "val_ratio": float(cfg.task.dataset.val_ratio),
               "train_segments_used": int(len(used)),
               "heldout_segments": int(len(L) - len(used)),
               "segment_lengths": L.tolist()}
        out["checks"][lab] = rec
        print(f"{lab:9s} {path.name}  {st.st_size/1e6:.1f} MB  sha256 {rec['sha256'][:16]}..")
        print(f"          segments {rec['segments']}  frames {rec['raw_frames']}  "
              f"sampler {rec['sampler_len']}  dataset {rec['dataset_len']}  "
              f"dataloader {rec['dataloader_len']} (batch {rec['batch_size']}, "
              f"drop_last {rec['drop_last']})  val_ratio {rec['val_ratio']}  "
              f"train segs {rec['train_segments_used']} held-out {rec['heldout_segments']}")
    # v2_train is the combined zarr past the clean prefix -- prove the prefix
    c, m = out["checks"]["clean"], out["checks"]["combined"]
    prefix_ok = m["segment_lengths"][:c["segments"]] == c["segment_lengths"]
    v2L = np.array(m["segment_lengths"][c["segments"]:])
    v2 = {"segments": int(len(v2L)), "raw_frames": int(v2L.sum()),
          "N": int(m["sampler_len"] - c["sampler_len"]),
          "N_by_rule": int(np.maximum(0, v2L - 15).sum()),
          "clean_prefix_matches": bool(prefix_ok)}
    out["checks"]["v2_train"] = v2
    print(f"v2_train  segments {v2['segments']}  frames {v2['raw_frames']}  "
          f"N {v2['N']} (per-segment rule gives {v2['N_by_rule']})  "
          f"clean prefix identical: {prefix_ok}")
    # hard checks
    got = {"clean": {"segments": c["segments"], "frames": c["raw_frames"], "N": c["sampler_len"]},
           "combined": {"segments": m["segments"], "frames": m["raw_frames"], "N": m["sampler_len"]},
           "v2_train": {"segments": v2["segments"], "frames": v2["raw_frames"], "N": v2["N"]}}
    for k, exp in EXPECT.items():
        for f, v in exp.items():
            if got[k][f] != v:
                out["fail"].append(f"{k}.{f}: expected {v}, got {got[k][f]}")
    for k in ("clean", "combined"):
        if out["checks"][k]["val_ratio"] != 0.0:
            out["fail"].append(f"{k}.val_ratio != 0.0")
        if out["checks"][k]["heldout_segments"] != 0:
            out["fail"].append(f"{k}: {out['checks'][k]['heldout_segments']} segments held out")
        if out["checks"][k]["sampler_len"] != out["checks"][k]["dataset_len"]:
            out["fail"].append(f"{k}: sampler_len != dataset_len")
    if not prefix_ok:
        out["fail"].append("combined zarr's first 25 segments differ from the clean zarr")
    exp_dl = {k: math.ceil(got[k]["N"] / 64) for k in ("clean", "combined")}
    for k in ("clean", "combined"):
        if out["checks"][k]["dataloader_len"] != exp_dl[k]:
            out["fail"].append(f"{k}.dataloader_len {out['checks'][k]['dataloader_len']} != ceil(N/64) {exp_dl[k]}")
    out["pass"] = not out["fail"]
    print("DATASET PREFLIGHT", "PASSED" if out["pass"] else "FAILED", out["fail"])
    p = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    if p:
        p.write_text(json.dumps(out, indent=1))
    sys.exit(0 if out["pass"] else 3)


if __name__ == "__main__":
    main()
