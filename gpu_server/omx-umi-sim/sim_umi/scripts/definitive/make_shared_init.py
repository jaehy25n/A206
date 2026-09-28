"""One initial model state for both definitive runs.

Built by the production workspace constructor from the same config file and
seed the runs use, saved once, and checksummed. Each run loads this file, so
"clean and v2 started from the same weights" is something the runs prove at
startup (init_checksum in run_provenance.json) rather than something the seed
is trusted to have done.
"""
import json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import torch
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
OmegaConf.register_new_resolver("eval", eval, replace=True)
from diffusion_policy.workspace.train_diffusion_unet_image_workspace import (
    TrainDiffusionUnetImageWorkspace, param_checksum)

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
with initialize_config_dir(version_base=None, config_dir=str(ROOT / "diffusion_policy/config")):
    cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace",
                  overrides=["training.seed=42"])
OmegaConf.resolve(cfg)
ws = TrainDiffusionUnetImageWorkspace(cfg, output_dir=str(out))
sd = {k: v.detach().cpu().clone() for k, v in ws.model.state_dict().items()}
torch.save(sd, out / "init_state.pt")
body, norm = param_checksum(ws.model)
# a second construction from the seed alone, to see whether the seed by
# itself would have reproduced the same weights
ws2 = TrainDiffusionUnetImageWorkspace(cfg, output_dir=str(out))
body2, _ = param_checksum(ws2.model)
rec = {"created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "file": str((out / "init_state.pt").resolve()),
       "tensors": len(sd), "trainable_params": int(sum(p.numel() for p in ws.model.parameters() if p.requires_grad)),
       "checksum_excluding_normalizer": body, "normalizer_checksum": norm,
       "second_seeded_construction_checksum": body2,
       "seed_alone_reproduces": body == body2}
(out / "init_state.json").write_text(json.dumps(rec, indent=1))
print(json.dumps(rec, indent=1))
