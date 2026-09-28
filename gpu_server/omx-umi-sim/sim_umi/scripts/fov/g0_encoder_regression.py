"""G0's encoder must not change when rectangular support is added.

    CUDA_VISIBLE_DEVICES= python sim_umi/scripts/fov/g0_encoder_regression.py save  --out ref.pt
    CUDA_VISIBLE_DEVICES= python sim_umi/scripts/fov/g0_encoder_regression.py check --ref ref.pt

On CPU, from the v2_11400 checkpoint's own cfg and EMA weights: the transform
modules' repr, and the encoder output for a fixed batch through (a) the
evaluation transform (CenterCrop, deterministic) and (b) the training
transform under a fixed torch seed. `check` requires both to be bitwise equal
to what `save` recorded before the code change.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import click
import dill
import hydra
import torch
import torchvision
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

OmegaConf.register_new_resolver("eval", eval, replace=True)
CKPT = ROOT / "sim_umi/train_results/2026-09-27_amp_v2_definitive/checkpoints/step11400.ckpt"
COMBINED = ROOT / "sim_umi/data/omx_sim_train_v2.zarr.zip"


def run():
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    with initialize_config_dir(version_base=None, config_dir=str(ROOT / "diffusion_policy/config")):
        cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace", overrides=[
            f"task.dataset_path={COMBINED}", "task.dataset.val_ratio=0.0", "training.seed=42"])
    OmegaConf.resolve(cfg)
    ds = hydra.utils.instantiate(cfg.task.dataset)
    # UmiDataset adds N(0, 0.05) noise to the episode start pose on every read
    # (umi_dataset.py "HACK: add noise to episode start pose"), from numpy's
    # global generator; seed it so the batch is the same batch every time
    import numpy as np
    np.random.seed(0)
    batch = torch.utils.data.default_collate([ds[i] for i in range(0, 16 * 997, 997)])
    payload = torch.load(open(CKPT, "rb"), pickle_module=dill, map_location="cpu")
    policy = hydra.utils.instantiate(payload["cfg"].policy)
    policy.load_state_dict(payload["state_dicts"]["ema_model"])
    policy.eval()
    enc = policy.obs_encoder
    tr = enc.key_transform_map["camera0_rgb"]
    nobs = policy.normalizer.normalize(batch["obs"])
    out = {"transform_repr": repr(tr)}
    with torch.no_grad():
        torch.manual_seed(1234)
        out["train_path"] = enc(nobs).clone()
        ev = torch.nn.Sequential(*[torchvision.transforms.CenterCrop(t.size) if type(t).__name__ == "RandomCrop"
                                   else t for t in tr if type(t).__name__ != "ColorJitter"])
        enc.key_transform_map["camera0_rgb"] = ev
        out["eval_path"] = enc(nobs).clone()
    return out


@click.command()
@click.argument("mode", type=click.Choice(["save", "check"]))
@click.option("--out", default=None)
@click.option("--ref", default=None)
def main(mode, out, ref):
    got = run()
    if mode == "save":
        torch.save(got, out)
        print("saved", out, {k: (tuple(v.shape) if torch.is_tensor(v) else v) for k, v in got.items()})
        return
    want = torch.load(ref)
    ok_r = got["transform_repr"] == want["transform_repr"]
    ok_t = torch.equal(got["train_path"], want["train_path"])
    ok_e = torch.equal(got["eval_path"], want["eval_path"])
    print(f"transform repr identical: {ok_r}\ntrain-path output bitwise equal: {ok_t} "
          f"(max |d| {float((got['train_path'] - want['train_path']).abs().max()):.3g})\n"
          f"eval-path output bitwise equal: {ok_e} (max |d| {float((got['eval_path'] - want['eval_path']).abs().max()):.3g})")
    if not (ok_r and ok_t and ok_e):
        raise SystemExit("G0 ENCODER CHANGED -- STOP")


if __name__ == "__main__":
    main()
