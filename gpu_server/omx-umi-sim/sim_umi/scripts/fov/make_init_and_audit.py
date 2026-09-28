"""Initial states for G1 and G2, and proof that they differ from G0's only
where the geometry forces them to.

    CUDA_VISIBLE_DEVICES= python sim_umi/scripts/fov/make_init_and_audit.py --out-dir <dir>

G1 has G0's shapes, so it uses the shared initial state file itself. G2's
positional embedding has 199 rows instead of 197: every other tensor is copied
from the shared state exactly and pos_embed alone is resampled
(posembed.rect_pos_embed). The audit builds the real G1 and G2 policies from
the training config with the geometry overrides, loads each state strictly,
and checks the checksums the workspace itself records.
"""
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import click
import hydra
import torch
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from diffusion_policy.workspace.train_diffusion_unet_image_workspace import param_checksum
from posembed import rect_pos_embed

OmegaConf.register_new_resolver("eval", eval, replace=True)
SHARED = ROOT / "sim_umi/train_results/2026-09-27_definitive/shared_init/init_state.pt"
PE_KEY = "obs_encoder.key_model_map.camera0_rgb.pos_embed"
GEOM = {"G1": [3, 224, 224], "G2": [3, 176, 288]}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def sd_checksum(sd, skip=("normalizer",), also_skip=()):
    h = hashlib.sha256()
    for k in sorted(sd):
        v = sd[k]
        if not torch.is_tensor(v) or any(x in k for x in skip) or k in also_skip:
            continue
        h.update(k.encode() + v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def build_policy(shape):
    with initialize_config_dir(version_base=None, config_dir=str(ROOT / "diffusion_policy/config")):
        cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace", overrides=[
            "task.dataset_path=unused", "training.seed=42",
            f"task.shape_meta.obs.camera0_rgb.shape=[{shape[0]},{shape[1]},{shape[2]}]"])
    OmegaConf.resolve(cfg)
    torch.manual_seed(42)
    return hydra.utils.instantiate(cfg.policy), cfg


@click.command()
@click.option("--out-dir", required=True)
def main(out_dir):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rep = {}
    src = torch.load(SHARED, map_location="cpu")
    rep["source"] = {"file": str(SHARED), "file_sha256": sha_file(SHARED), "tensors": len(src),
                     "checksum_excluding_normalizer": sd_checksum(src),
                     "pos_embed_shape": list(src[PE_KEY].shape)}
    g2 = dict(src)
    g2[PE_KEY] = rect_pos_embed(src[PE_KEY], (14, 14), (11, 18), num_prefix=1)
    g2_path = out / "init_state_g2.pt"
    torch.save(g2, g2_path)
    changed = [k for k in src if (tuple(src[k].shape) != tuple(g2[k].shape)) or not torch.equal(src[k], g2[k])]
    rep["G1"] = {"file": str(SHARED), "note": "same file as G0's shared init",
                 "checksum_excluding_normalizer": sd_checksum(src)}
    rep["G2"] = {"file": str(g2_path), "file_sha256": sha_file(g2_path),
                 "checksum_excluding_normalizer": sd_checksum(g2),
                 "changed_keys": {k: {"from": list(src[k].shape), "to": list(g2[k].shape)} for k in changed},
                 "cls_row_identical": bool(torch.equal(g2[PE_KEY][:, 0], src[PE_KEY][:, 0]))}
    common_src = sd_checksum(src, also_skip=(PE_KEY,))
    common_g2 = sd_checksum(g2, also_skip=(PE_KEY,))
    rep["common_checksum_excluding_pos_embed_and_normalizer"] = {"G0/G1 source": common_src, "G2": common_g2,
                                                                  "equal": common_src == common_g2}
    ok = changed == [PE_KEY] and common_src == common_g2
    # load into the real policies, strictly, and read back what the workspace records
    for name, shape in GEOM.items():
        pol, cfg = build_policy(shape)
        sd = src if name == "G1" else g2
        pol.load_state_dict(sd, strict=True)
        ck = param_checksum(pol)[0]
        vit = pol.obs_encoder.key_model_map["camera0_rgb"]
        B = 2
        obs = {k: torch.rand(B, 2, *v["shape"]) for k, v in cfg.task.shape_meta.obs.items()}
        pol.eval()
        seen = {}
        h = vit.blocks[0].register_forward_pre_hook(lambda m, a: seen.__setitem__("t", list(a[0].shape)))
        with torch.no_grad():
            gc = pol.obs_encoder(obs)
            raw = vit(torch.rand(B * 2, *shape))
        h.remove()
        rep[name]["loaded_strict_into_policy"] = True
        rep[name]["policy_param_checksum_after_load"] = ck
        rep[name]["vit"] = {"img_size": list(vit.patch_embed.img_size), "grid": list(vit.patch_embed.grid_size),
                            "pos_embed": list(vit.pos_embed.shape), "tokens_into_block0": seen["t"],
                            "cls": list(raw[:, 0].shape)}
        rep[name]["train_transform"] = repr(pol.obs_encoder.key_transform_map["camera0_rgb"])
        rep[name]["global_cond_shape"] = list(gc.shape)
        print(name, json.dumps({k: v for k, v in rep[name].items() if k != "changed_keys"}, indent=1), flush=True)
    rep["G1"]["checksum_matches_shared_a4cd264f"] = rep["G1"]["policy_param_checksum_after_load"].startswith("a4cd264f")
    ok &= rep["G1"]["checksum_matches_shared_a4cd264f"] and rep["G1"]["global_cond_shape"] == rep["G2"]["global_cond_shape"]
    rep["pass"] = bool(ok)
    print("source", rep["source"]["checksum_excluding_normalizer"][:16], "| changed keys", list(rep["G2"]["changed_keys"]),
          "| common equal", common_src == common_g2, "| PASS" if ok else "| FAIL")
    (out / "init_audit.json").write_text(json.dumps(rep, indent=1))
    if not ok:
        raise SystemExit("INIT AUDIT FAILED -- STOP")


if __name__ == "__main__":
    main()
