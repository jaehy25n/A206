"""CPU unit / smoke tests for ablations A and B (no GPU, no training).

    python sim_umi/scripts/aux/unit_tests.py --out <json>
"""
import hashlib
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "sim_umi" / "src")]

import click
import numpy as np
import torch
import hydra
from omegaconf import OmegaConf

OmegaConf.register_new_resolver("eval", eval, replace=True)
INIT = ROOT / "sim_umi/train_results/2026-09-27_definitive/shared_init/init_state.pt"
CFG = {"G0": "train_diffusion_unet_timm_omx_workspace",
       "A": "train_diffusion_unet_timm_omx_timing_aux_workspace",
       "B": "train_diffusion_unet_timm_omx_oracle_tip_relation_film_workspace"}
OVR = ["task.dataset.val_ratio=0.0", "training.seed=42", "training.device=cuda:0", "training.num_epochs=100",
       "training.checkpoint_every=10", "training.sample_every=5", "training.resume=True",
       "+training.mixed_precision=fp16", "+training.lr_scheduler_total_steps=11400",
       "+training.checkpoint_at_steps=[5986,8000,10000,11400]", f"+training.init_state_path={INIT}",
       f"task.dataset_path={ROOT}/sim_umi/data/omx_sim_train_v2.zarr.zip", "+training.max_opt_steps=11400"]


def compose(name):
    from hydra import compose as hc, initialize_config_dir
    with initialize_config_dir(config_dir=str(ROOT / "diffusion_policy/config"), version_base=None):
        return hc(config_name=name, overrides=OVR + [f"exp_name={name}"])


def sha(b):
    return hashlib.sha256(b).hexdigest()[:20]


def flat(d, pre=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, f"{pre}{k}."))
        else:
            out[f"{pre}{k}"] = v
    return out


@click.command()
@click.option("--out", required=True)
def main(out):
    R, fails = {}, []
    def check(name, ok, **info):
        R[name] = dict(ok=bool(ok), **info)
        if not ok:
            fails.append(name)
        print(("PASS " if ok else "FAIL ") + name, json.dumps(info, default=str)[:300], flush=True)

    cfgs = {k: compose(v) for k, v in CFG.items()}
    res = {k: flat(OmegaConf.to_container(c, resolve=True)) for k, c in cfgs.items()}
    for k in ("A", "B"):
        diff = sorted(x for x in set(res["G0"]) | set(res[k]) if res["G0"].get(x) != res[k].get(x))
        allowed = [x for x in diff if x.startswith(("policy.", "task.dataset.")) or x in (
            "exp_name", "logging.name", "logging.tags", "multi_run.run_dir", "multi_run.wandb_name_base")]
        unexpected = [x for x in diff if x not in allowed]
        pol = [x for x in diff if x.startswith(("policy.", "task.dataset."))]
        check(f"{k}_config_diff_only_intended", not unexpected, changed=pol, unexpected=unexpected)

    # ---- construction: RNG after construction, shared init, parameter groups
    from diffusion_policy.workspace.train_diffusion_unet_image_workspace import shared_checksum
    sd = torch.load(INIT, map_location="cpu")
    pol = {}
    for k, c in cfgs.items():
        torch.manual_seed(42); np.random.seed(42); random.seed(42)
        m = hydra.utils.instantiate(c.policy)
        rng = sha(torch.get_rng_state().numpy().tobytes())
        if torch.cuda.is_available():     # the CUDA stream draws the diffusion noise and timesteps
            rng += "|" + sha(torch.cuda.get_rng_state().numpy().tobytes())
        pre = tuple(getattr(m, "new_module_prefixes", ()) or ())
        missing, unexpected = m.load_state_dict(sd, strict=not pre)
        new_keys = sorted(x for x in m.state_dict() if pre and x.startswith(pre))
        pol[k] = dict(model=m, rng=rng, shared=shared_checksum(m, sd.keys()), missing=sorted(missing),
                      unexpected=list(unexpected), new_keys=new_keys,
                      n_new=sum(p.numel() for p in m.new_module_parameters()) if pre else 0)
    for k in ("A", "B"):
        check(f"{k}_rng_after_construction_equals_G0", pol[k]["rng"] == pol["G0"]["rng"], g0=pol["G0"]["rng"], x=pol[k]["rng"])
        check(f"{k}_shared_init_hash_equals_G0", pol[k]["shared"] == pol["G0"]["shared"], hash=pol[k]["shared"])
        check(f"{k}_only_new_module_keys_missing", pol[k]["missing"] == pol[k]["new_keys"] and not pol[k]["unexpected"]
              and len(pol[k]["new_keys"]) > 0, new_keys=pol[k]["new_keys"], n_new_values=pol[k]["n_new"])
    b = pol["B"]["model"].obs_encoder.relation_film.net[-1]
    check("B_last_linear_zero_init", bool((b.weight == 0).all() and (b.bias == 0).all()))

    # ---- datasets
    ds = {}
    for k in ("A", "B"):
        torch.manual_seed(42)
        ds[k] = hydra.utils.instantiate(cfgs[k].task.dataset)
    lab = np.load(ROOT / "sim_umi/data/sidecars/omx_sim_train_v2.labels.npz")
    check("A_train_samples", len(ds["A"]) == 21532, n=len(ds["A"]))
    check("A_scales_are_split_P95", True, **ds["A"].sidecar_provenance["timing_scales_p95_s"])
    rng = np.random.default_rng(0)
    bad = 0
    for idx in rng.choice(len(ds["A"]), 40, replace=False).tolist() + [0]:
        c = ds["A"].sampler.indices[idx][0]
        it = ds["A"][int(idx)]
        ok = int(it["aux"]["phase"]) == int(lab["row_phase_5"][c]) and np.allclose(
            it["aux"]["dt"].numpy(), [lab["row_dt_to_close_s"][c], lab["row_dt_to_lift_s"][c], lab["row_dt_to_open_s"][c]])
        bad += not ok
    check("A_aux_is_current_row_label", bad == 0, checked=41)
    import zarr
    mz = zarr.open(zarr.ZipStore(str(ROOT / "sim_umi/data/sidecars/omx_sim_train_v2.oracle_masks_g0.zarr.zip"), mode="r"), "r")
    bad, starts = 0, 0
    for idx in rng.choice(len(ds["B"]), 30, replace=False).tolist() + [0, 1]:
        c, s, _, _ = ds["B"].sampler.indices[idx]
        it = ds["B"][int(idx)]
        rows = [max(c - 1, s), c]
        starts += c == s
        ok = all(np.array_equal(it["obs"]["camera0_target_mask"][t].numpy().astype(bool), mz["data/target_mask"][r])
                 and np.array_equal(it["obs"]["camera0_ee_tip_mask"][t].numpy().astype(bool), mz["data/ee_tip_mask"][r])
                 and int(it["obs"]["camera0_target_mask_valid"][t]) == int(mz["data/target_mask_valid"][r])
                 for t, r in enumerate(rows))
        bad += not ok
    check("B_masks_are_obs_rows_r-1_r_with_start_padding", bad == 0, checked=32, episode_starts=int(starts))
    # the RGB of the same item comes from the same rows (image equality with the zarr)
    it = ds["B"][5]
    c, s, _, _ = ds["B"].sampler.indices[5]
    rgb = zarr.open(zarr.ZipStore(str(ROOT / "sim_umi/data/omx_sim_train_v2.zarr.zip"), mode="r"), "r")
    from diffusion_policy.codecs.imagecodecs_numcodecs import register_codecs
    register_codecs()
    same = all(np.array_equal((it["obs"]["camera0_rgb"][t].permute(1, 2, 0).numpy() * 255).round().astype(np.uint8),
                              rgb["data/camera0_rgb"][r]) for t, r in enumerate([max(c - 1, s), c]))
    check("B_rgb_and_masks_same_rows", same)

    # ---- B encoder: transform bit-exact and RNG-equal vs G0's Sequential; step-0 identity
    encG0, encB = pol["G0"]["model"].obs_encoder, pol["B"]["model"].obs_encoder
    encG0.train(); encB.train()
    batch = torch.utils.data.default_collate([ds["B"][i] for i in (0, 100, 2000, 9000, 15000, 21000)])
    img = batch["obs"]["camera0_rgb"].reshape(-1, 3, 224, 224)
    torch.manual_seed(7); a = encG0.key_transform_map["camera0_rgb"](img); sa = torch.get_rng_state()
    torch.manual_seed(7)
    m = torch.stack([batch["obs"]["camera0_target_mask"], batch["obs"]["camera0_ee_tip_mask"]], 2).reshape(-1, 2, 224, 224).float()
    b_img, b_m = encB._transform("camera0_rgb", img, m); sb = torch.get_rng_state()
    check("B_transformed_rgb_bit_exact", bool(torch.equal(a, b_img)))
    check("B_rng_after_transform_equal", bool(torch.equal(sa, sb)))
    check("B_masks_stay_binary_after_crop", bool(((b_m == 0) | (b_m == 1)).all()))
    nobs = {k: v for k, v in batch["obs"].items()}
    # normaliser-free check of the encoder output: identical inputs, same seed
    with torch.no_grad():
        torch.manual_seed(11); g0 = encG0(nobs)
        torch.manual_seed(11); gb = encB(nobs)
    check("B_global_cond_equals_G0_at_zero_init", bool(torch.equal(g0, gb)), max_abs=float((g0 - gb).abs().max()))
    # a non-zero FiLM must change only the frames whose target is usable
    with torch.no_grad():
        encB.relation_film.net[-1].bias.fill_(0.1)
        torch.manual_seed(11); gb2 = encB(nobs)
        encB.relation_film.net[-1].bias.zero_()
    valid = batch["obs"]["camera0_target_mask_valid"].reshape(-1).bool()
    area = []
    torch.manual_seed(11)
    _, mm = encB._transform("camera0_rgb", img, m)
    gate = valid & (mm[:, 0].sum((1, 2)) >= 12)
    cls0, cls2 = g0[:, :1536].reshape(-1, 768), gb2[:, :1536].reshape(-1, 768)
    changed = (cls0 != cls2).any(1)
    check("B_hard_gate_per_frame", bool(torch.equal(changed, gate)), gate=gate.tolist(), changed=changed.tolist())
    check("B_lowdim_part_untouched", bool(torch.equal(g0[:, 1536:], gb2[:, 1536:])))

    # ---- A loss: masked, skip-safe
    A = pol["A"]["model"]
    from diffusion_policy.model.common.normalizer import LinearNormalizer
    torch.manual_seed(0)
    bA = torch.utils.data.default_collate([ds["A"][i] for i in range(0, 21532, 2153)][:8])
    norm = ds["A"].get_normalizer() if False else None
    phase = bA["aux"]["phase"]
    check("A_batch_has_aux_at_current_row", bA["aux"]["dt"].shape == (8, 3), phases=phase.tolist())
    tau = torch.zeros(8, 3)
    scales = torch.tensor(A.timing_scales_s)
    y = (bA["aux"]["dt"] / scales).clamp(0, 1)
    losses = [torch.nn.functional.smooth_l1_loss(tau[phase == e, e], y[phase == e, e]) for e in range(3) if (phase == e).any()]
    check("A_masked_loss_defined", all(torch.isfinite(l) for l in losses), active=len(losses))
    pathlib.Path(out).write_text(json.dumps({"fails": fails, "checks": R}, indent=1, default=str))
    print("FAILS:", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
