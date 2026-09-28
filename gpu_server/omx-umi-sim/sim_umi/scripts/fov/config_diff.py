"""G0 / G1 / G2 resolved configs, diffed, with the allowed differences named.

    python sim_umi/scripts/fov/config_diff.py --out <file>

G0 is the config the definitive v2_11400 run actually resolved (its .hydra
config.yaml). G1 and G2 are composed here from the same config file with G0's
own override list plus only the geometry overrides the FOV protocol allows.
"""
import difflib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import click
import yaml
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

OmegaConf.register_new_resolver("eval", eval, replace=True)
G0_RUN = ROOT / "sim_umi/train_results/2026-09-27_amp_v2_definitive/.hydra"
FOV = ROOT / "sim_umi/train_results/2026-09-27_fov"
DATA = ROOT / "sim_umi/data"
VARIANTS = {
    "G1": {"dataset": DATA / "omx_sim_train_v2_g1_letterbox224.zarr.zip", "geometry": "g1_letterbox224",
           "shape": None, "init": None},
    "G2": {"dataset": DATA / "omx_sim_train_v2_g2_rect288x176.zarr.zip", "geometry": "g2_rect288x176",
           "shape": "[3,176,288]", "init": FOV / "shared_init/init_state_g2.pt"},
}
# keys whose values are timestamps or run directories, set per launch
VOLATILE = re.compile(r"^\s*(name|run_dir|wandb_name_base|dir): ")
ALLOWED = re.compile(r"^[-+]\s*(exp_name|dataset_path|init_state_path|resume|rgb_geometry|shape): |"
                     r"^[-+]\s*- (3|176|224|288)$")


def overrides_for(name):
    base = [o for o in yaml.safe_load((G0_RUN / "overrides.yaml").read_text())
            if not o.startswith(("task.dataset_path=", "exp_name=", "training.resume=",
                                 "+training.init_state_path="))]
    v = VARIANTS[name]
    out = base + [f"task.dataset_path={v['dataset']}", f"exp_name=fov_{v['geometry']}",
                  "training.resume=False", f"+task.rgb_geometry={v['geometry']}",
                  # same sample order in G1 and G2 (their model construction draws
                  # different amounts of randomness), and the proof of it
                  "+training.dataloader_seed=42", "+training.log_batch_fingerprints=300"]
    init = v["init"] or next(o.split("=", 1)[1] for o in yaml.safe_load((G0_RUN / "overrides.yaml").read_text())
                              if o.startswith("+training.init_state_path="))
    out.append(f"+training.init_state_path={init}")
    if v["shape"]:
        out.append(f"task.shape_meta.obs.camera0_rgb.shape={v['shape']}")
        # task/umi_omx.yaml gives the dataset its own copy through a YAML
        # anchor, which the override above does not reach
        out.append(f"task.dataset.shape_meta.obs.camera0_rgb.shape={v['shape']}")
    return out


def resolved(overrides, resolve=True):
    with initialize_config_dir(version_base=None, config_dir=str(ROOT / "diffusion_policy/config")):
        cfg = compose(config_name="train_diffusion_unet_timm_omx_workspace", overrides=overrides)
    if resolve:
        OmegaConf.resolve(cfg)
    return OmegaConf.to_yaml(cfg)


@click.command()
@click.option("--out", required=True)
def main(out):
    # 1. G0 recomposed from its own override list must reproduce the config
    #    the run saved (it is stored unresolved), else nothing below is G0
    g0_ov = yaml.safe_load((G0_RUN / "overrides.yaml").read_text())
    saved = (G0_RUN / "config.yaml").read_text()
    recomposed = resolved(g0_ov, resolve=False)
    rep_d = [l for l in difflib.unified_diff(saved.splitlines(), recomposed.splitlines(), lineterm="", n=0)
             if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    lines = [f"===== G0 saved .hydra/config.yaml vs G0 recomposed from its overrides: "
             f"{len(rep_d)} differing lines =====", *rep_d, ""]
    if rep_d:
        pathlib.Path(out).write_text("\n".join(lines) + "\n")
        raise SystemExit("G0 NOT REPRODUCED BY RECOMPOSITION -- STOP")
    g0 = resolved(g0_ov)
    (FOV / "preflight/config_G0_resolved.yaml").write_text(g0)
    verdict = {}
    def flat(y):
        out_ = {}
        def walk(v, path):
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    walk(v2, path + (str(k2),))
            else:
                out_[".".join(path)] = v
        walk(yaml.safe_load(y), ())
        return out_
    allowed_path = re.compile(r"^(exp_name|logging\.tags|logging\.name|multi_run\..*|hydra\..*|"
                              r"task\.dataset_path|task\.dataset\.dataset_path|training\.resume|"
                              r"training\.init_state_path|task\.rgb_geometry|training\.dataloader_seed|"
                              r"training\.log_batch_fingerprints|(.*\.)?camera0_rgb\.shape)$")
    f0 = flat(g0)
    for name in VARIANTS:
        ov = overrides_for(name)
        y = resolved(ov)
        (FOV / f"preflight/config_{name}.yaml").write_text(y)
        (FOV / f"preflight/overrides_{name}.txt").write_text("\n".join(ov) + "\n")
        f1 = flat(y)
        keys = sorted(set(f0) | set(f1))
        diff = [(k, f0.get(k, "<absent>"), f1.get(k, "<absent>")) for k in keys if f0.get(k, "<absent>") != f1.get(k, "<absent>")]
        vol = [d for d in diff if re.match(r"^(logging\.name|multi_run\..*|hydra\..*)$", d[0])]
        real = [d for d in diff if d not in vol]
        bad = [d for d in real if not allowed_path.match(d[0])]
        verdict[name] = {"diff_keys": len(real), "outside_allowed": bad}
        lines += [f"===== G0 -> {name}: {len(real)} differing keys (timestamps/run dirs excluded) ====="]
        lines += [f"  {k}: {a0!r} -> {a1!r}" for k, a0, a1 in real]
        lines += [f"----- outside the allowed set: {bad if bad else 'none'}", ""]
    pathlib.Path(out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if any(v["outside_allowed"] for v in verdict.values()):
        raise SystemExit("CONFIG DIFF HAS UNINTENDED CHANGES -- STOP")


if __name__ == "__main__":
    main()
