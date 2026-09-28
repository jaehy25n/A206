"""The G0 image path, stage by stage, measured on the production objects.

    CUDA_VISIBLE_DEVICES= python sim_umi/scripts/fov/audit_input_path.py \
        --ckpt <v2_11400 step checkpoint> --out <stem>

Nothing here is re-implemented: the dataset is the production UmiDataset built
from the same hydra config and overrides the definitive v2 run used, the
policy is instantiated from the checkpoint's own cfg with its EMA weights, and
each stage is the module the policy itself calls. For every stage it records
shape, dtype and range, and it prints the call path with code locations.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim_umi" / "ros"))

import click
import dill
import hydra
import numpy as np
import torch
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

OmegaConf.register_new_resolver("eval", eval, replace=True)
COMBINED = ROOT / "sim_umi/data/omx_sim_train_v2.zarr.zip"


def stat(x):
    x = x.detach().float() if torch.is_tensor(x) else torch.as_tensor(np.asarray(x, np.float32))
    return {"shape": list(x.shape), "min": round(float(x.min()), 5), "max": round(float(x.max()), 5),
            "mean": round(float(x.mean()), 5)}


@click.command()
@click.option("--ckpt", required=True)
@click.option("--out", required=True)
def main(ckpt, out):
    rep, lines = {}, []

    def log(k, v):
        rep[k] = v
        lines.append(f"{k}: {v}")
        print(f"{k}: {v}", flush=True)

    with initialize_config_dir(version_base=None, config_dir=str(ROOT / "diffusion_policy/config")):
        cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace", overrides=[
            f"task.dataset_path={COMBINED}", "task.dataset.val_ratio=0.0", "training.seed=42"])
    OmegaConf.resolve(cfg)
    ds = hydra.utils.instantiate(cfg.task.dataset)
    log("dataset class", f"{type(ds).__module__}.{type(ds).__name__}")
    log("dataset len (sampler N)", len(ds))
    zarr_img = ds.replay_buffer["camera0_rgb"]
    log("replay_buffer camera0_rgb", {"shape": list(zarr_img.shape), "dtype": str(zarr_img.dtype)})
    for i in (0, 5000, 12000, len(ds) - 1):
        s = ds[i]
        log(f"__getitem__({i}) obs.camera0_rgb", {**stat(s["obs"]["camera0_rgb"]),
                                                   "dtype": str(s["obs"]["camera0_rgb"].dtype)})
    # the exact tensor layout: channel order is whatever the zarr holds (RGB,
    # written by cv2 from an RGB array); check the channel means on one sample
    s = ds[5000]["obs"]["camera0_rgb"]
    log("channel means of one sample (C axis = 1)", [round(float(s[:, c].mean()), 4) for c in range(3)])

    payload = torch.load(open(ckpt, "rb"), pickle_module=dill, map_location="cpu")
    pcfg = payload["cfg"]
    policy = hydra.utils.instantiate(pcfg.policy)
    policy.load_state_dict(payload["state_dicts"]["ema_model"])
    policy.eval()
    enc = policy.obs_encoder
    log("checkpoint", ckpt)
    log("obs encoder model_name", enc.model_name)
    nz = policy.normalizer["camera0_rgb"]
    log("normalizer camera0_rgb scale/offset", {"scale": nz.params_dict["scale"].flatten().tolist(),
                                                "offset": nz.params_dict["offset"].flatten().tolist()})
    tr = enc.key_transform_map["camera0_rgb"]
    log("training transform (key_transform_map)", repr(tr))
    vit = enc.key_model_map["camera0_rgb"]
    pe = vit.patch_embed
    log("vit patch_embed", {"img_size": list(pe.img_size), "patch_size": list(pe.patch_size),
                            "grid_size": list(pe.grid_size), "num_patches": pe.num_patches,
                            "strict_img_size": getattr(pe, "strict_img_size", None),
                            "dynamic_img_size": getattr(vit, "dynamic_img_size", None)})
    log("vit pos_embed", {"shape": list(vit.pos_embed.shape), "num_prefix_tokens": vit.num_prefix_tokens,
                          "cls_token": vit.cls_token is not None,
                          "reg_tokens": getattr(vit, "num_reg_tokens", 0),
                          "no_embed_class": getattr(vit, "no_embed_class", None),
                          "global_pool": vit.global_pool})

    batch = torch.utils.data.default_collate([ds[i] for i in range(0, 64 * 50, 50)])
    img = batch["obs"]["camera0_rgb"]
    log("batch obs.camera0_rgb (B,T,C,H,W)", stat(img))
    nobs = policy.normalizer.normalize(batch["obs"])
    x = nobs["camera0_rgb"]
    log("after normalizer (encoder normalization)", stat(x))
    B, T = x.shape[:2]
    x = x.reshape(B * T, *x.shape[2:])
    torch.manual_seed(0)
    y = x
    for i, t in enumerate(tr):
        y = t(y)
        log(f"train transform step {i} {type(t).__name__}", stat(y))
    # evaluation: the server's --deterministic replacement
    import torchvision
    ev = torch.nn.Sequential(*[torchvision.transforms.CenterCrop(t.size) if type(t).__name__ == "RandomCrop" else t
                               for t in tr if type(t).__name__ != "ColorJitter"])
    log("eval transform (policy_server --deterministic)", repr(ev))
    z = ev(x)
    log("eval: encoder input", stat(z))
    seen = {}
    h = vit.blocks[0].register_forward_pre_hook(lambda m, a: seen.__setitem__("tokens", list(a[0].shape)))
    with torch.no_grad():
        feat = vit(z[:8])
    h.remove()
    log("token sequence entering block 0 (8 images)", seen["tokens"])
    log("vit output (8 images)", list(feat.shape))
    cls = enc.aggregate_feature(feat)
    log("CLS feature (aggregate_feature)", {**stat(cls), "norm_mean": round(float(cls.norm(dim=-1).mean()), 4)})
    with torch.no_grad():
        gc = enc(nobs)
    log("obs_encoder output global_cond (B, D)", list(gc.shape))
    pathlib.Path(out + ".json").write_text(json.dumps(rep, indent=1))
    pathlib.Path(out + ".txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
