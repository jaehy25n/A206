"""Does the CLIP encoder still know where things are?

    python sim_umi/scripts/audit_visual_spatial.py

The policy sees one 768-number vector per frame: the CLS token of a CLIP
ViT-B/16. Everything it can ever learn about where the ball and the bin are has
to survive that bottleneck. The earlier training run cannot answer whether it
does -- that data let the expert fly at targets it had not seen, so fitting it
needed no spatial reading of the picture at all.

So this asks the encoder directly, and changes nothing. The arm, the jaw and
the camera are held still; only the ball and the bin move. Their position in
the picture is taken from a segmentation render, which is evaluation only and
never reaches the encoder. A ridge probe -- a linear map, nothing more -- is
fitted from the frozen features to that position on one set of placements and
scored on another, so what is measured is the information in the
representation and not the capacity of the probe.

It reports two conditions, because the encoder augments at inference as well
as in training: RandomCrop to 212 and back to 224, then ColorJitter. That is
upstream's arrangement and it is what the policy will actually see, so it is
measured as well as the clean image.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))

import click
import cv2
import hydra
import mujoco
import numpy as np
import torch
from omegaconf import OmegaConf
from sklearn.linear_model import RidgeCV, LogisticRegression

from collector import Collector
from gripper_vision import TipDetectorConfig, mask_magenta
from scene import SceneConfig, write_scene

OmegaConf.register_new_resolver("eval", eval, replace=True)
CROP = 224


def crop224(img):
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    return cv2.resize(img[y0:y0 + side, x0:x0 + side], (CROP, CROP),
                      interpolation=cv2.INTER_AREA), (x0, y0, side)


def report_encoder(cfg):
    enc = hydra.utils.instantiate(cfg.policy.obs_encoder,
                                  shape_meta=cfg.task.shape_meta)
    m = enc.key_model_map["camera0_rgb"]
    n_all = sum(p.numel() for p in m.parameters())
    n_grad = sum(p.numel() for p in m.parameters() if p.requires_grad)
    click.secho("the visual path, as configured", bold=True)
    click.echo(f"  model            {cfg.policy.obs_encoder.model_name}")
    click.echo(f"  weights          timm pretrained="
               f"{cfg.policy.obs_encoder.pretrained} -> Hugging Face "
               f"timm/vit_base_patch16_clip_224.openai (OpenAI CLIP)")
    click.echo(f"  frozen flag      {cfg.policy.obs_encoder.frozen}")
    click.echo(f"  parameters       {n_all/1e6:.2f} M, of which "
               f"{n_grad/1e6:.2f} M require grad")
    click.echo(f"  in the optimizer yes, as its own group at 0.1x the base lr "
               f"({cfg.optimizer.lr} -> {cfg.optimizer.lr*0.1})")
    click.echo(f"  aggregation      CLS token only; feature_aggregation "
               f"'{cfg.policy.obs_encoder.feature_aggregation}' is logged as "
               f"ignored for a vit")
    click.echo(f"  feature to policy {tuple(enc.output_shape())} per frame pair "
               f"= 768 visual + low-dim, per observation")
    click.echo(f"  transforms       applied in forward() unconditionally, so "
               f"they run at inference too:")
    for t in enc.key_transform_map["camera0_rgb"]:
        click.echo(f"                     {t}")
    click.secho("  imagenet_norm is accepted as an argument and never used: "
                "the image reaches CLIP as [0,1] with no normalisation",
                fg="yellow")
    return enc


def scene_frames(cfg_scene, home_q, n_grid, second_pose):
    """Render the arm still and the targets moved, with the truth beside it."""
    col = Collector(str(write_scene(cfg_scene)), cfg=cfg_scene, render=False)
    m, d = col.model, col.data
    W, H = cfg_scene.wrist_cam_resolution
    rgb_r = mujoco.Renderer(m, height=H, width=W)
    seg_r = mujoco.Renderer(m, height=H, width=W)
    seg_r.enable_segmentation_rendering()
    gid = {n: set(range(m.body_geomadr[mujoco.mj_name2id(
        m, mujoco.mjtObj.mjOBJ_BODY, n)],
        m.body_geomadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)]
        + m.body_geomnum[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)]))
        for n in ("object", "bin")}
    det = TipDetectorConfig()
    r = float(cfg_scene.object_size[0])
    bx, by = cfg_scene.robot_base_xy

    xs = np.linspace(-0.26, 0.26, n_grid)
    ys = np.linspace(-0.26, -0.02, n_grid)
    spots = [(x, y) for x in xs for y in ys
             if cfg_scene.on_paper(x, y, 0.09) and cfg_scene.reachable(x, y, 0.06)]
    poses = [("home", home_q)] + ([("other", second_pose)] if second_pose is not None else [])

    rows = []
    for pose_name, q in poses:
        for adr, v in zip(col.arm_qadr, q):
            d.qpos[adr] = v
        for target in ("object", "bin"):
            for (x, y) in spots:
                # the other body goes off the paper so only one thing moves
                adr_t = col.obj_qadr if target == "object" else col.bin_qadr
                adr_o = col.bin_qadr if target == "object" else col.obj_qadr
                d.qpos[adr_t:adr_t + 3] = [x, y, r if target == "object" else 0.0]
                d.qpos[adr_t + 3:adr_t + 7] = [1, 0, 0, 0]
                d.qpos[adr_o:adr_o + 3] = [bx + 0.9, by - 0.9, 0.0]
                d.qpos[adr_o + 3:adr_o + 7] = [1, 0, 0, 0]
                mujoco.mj_forward(m, d)
                seg_r.update_scene(d, camera="wrist")
                seg = seg_r.render()[:, :, 0]
                mask = np.isin(seg, list(gid[target]))
                c, (x0, y0, side) = crop224(mask.astype(np.uint8) * 255)
                if (c > 127).sum() < 12:
                    continue                       # not in the policy's square
                v_, u_ = np.nonzero(c > 127)
                rgb_r.update_scene(d, camera="wrist")
                img = rgb_r.render().copy()
                img = mask_magenta(img, det)
                crop, _ = crop224(img)
                rows.append({"pose": pose_name, "target": target,
                             "world": (x, y), "uv": (float(u_.mean()),
                                                     float(v_.mean())),
                             "px": int((c > 127).sum()),
                             "img": crop.astype(np.float32).transpose(2, 0, 1) / 255.0})
    col.close()
    rgb_r.close()
    seg_r.close()
    return rows


@torch.no_grad()
def features(enc, imgs, augment, device, batch=32):
    model = enc.key_model_map["camera0_rgb"].to(device).eval()
    tf = enc.key_transform_map["camera0_rgb"]
    out = []
    for i in range(0, len(imgs), batch):
        x = torch.from_numpy(np.stack(imgs[i:i + batch])).to(device)
        if augment:
            x = tf(x)
        f = model(x)
        out.append(f[:, 0, :].float().cpu().numpy())   # CLS, as the policy takes
    return np.concatenate(out)


def probe(F, uv, split, label):
    tr, te = split
    errs = {}
    # 768 features against a few hundred placements: the strength of the
    # regulariser is chosen by cross-validation inside the training split, so
    # the number reported is not a measure of how well 768 free parameters can
    # memorise a few dozen points.
    alphas = np.logspace(-1, 5, 13)
    reg = RidgeCV(alphas=alphas).fit(F[tr], uv[tr])
    for name, idx in (("fitted on", tr), ("held out", te)):
        pred = reg.predict(F[idx])
        e = np.linalg.norm(pred - uv[idx], axis=1)
        errs[name] = (e.mean(), np.median(e), np.percentile(e, 95))
    # left / centre / right, and up / down, from the same features
    acc = {}
    for ax, nm in ((0, "left|centre|right"), (1, "up|middle|down")):
        q = np.quantile(uv[tr][:, ax], [1 / 3, 2 / 3])
        lab = np.digitize(uv[:, ax], q)
        clf = LogisticRegression(max_iter=2000).fit(F[tr], lab[tr])
        acc[nm] = float((clf.predict(F[te]) == lab[te]).mean())
    # the same fit with the answers shuffled: whatever this scores is what the
    # probe can do with no information at all
    rng = np.random.default_rng(7)
    sh = rng.permutation(len(tr))
    ctrl = RidgeCV(alphas=alphas).fit(F[tr], uv[tr][sh])
    ce = np.linalg.norm(ctrl.predict(F[te]) - uv[te], axis=1)

    click.secho(f"\n  {label}   ({len(tr)} fitted, {len(te)} held out)", bold=True)
    click.echo(f"    position error (pixels in the 224 square)")
    for k, (mean, med, p95) in errs.items():
        click.echo(f"      {k:9s} mean {mean:6.2f}  median {med:6.2f}  "
                   f"p95 {p95:6.2f}")
    click.echo(f"      {'shuffled':9s} mean {ce.mean():6.2f}  median "
               f"{np.median(ce):6.2f}  p95 {np.percentile(ce, 95):6.2f}"
               f"   <- the same probe with the answers scrambled")
    for nm, a in acc.items():
        click.echo(f"    {nm:18s} held out {a*100:5.1f}%  (chance 33.3%)")
    return errs["held out"][0], acc


@click.command()
@click.option("--config", default="train_diffusion_unet_timm_omx_workspace")
@click.option("--n-grid", default=23, type=int)
@click.option("--device", default="cuda:0")
def main(config, n_grid, device):
    with hydra.initialize_config_dir(
            version_base=None,
            config_dir=str(ROOT / "diffusion_policy" / "config")):
        cfg = hydra.compose(config, overrides=[
            f"task.dataset_path={SIM / 'data' / 'omx_sim_train.zarr.zip'}"])
    enc = report_encoder(cfg)

    home = np.array(np.load(sorted((SIM / "data" / "demos" / "train")
                                   .glob("episode_*.npz"))[0],
                            allow_pickle=True)["eval_home_q"], float)
    click.secho(f"\nHOME q (from the collected data) "
                f"{np.round(np.degrees(home), 2)} deg", bold=True)

    cfg_scene = SceneConfig()
    rows = scene_frames(cfg_scene, home, n_grid, None)
    click.secho(f"\n{len(rows)} intervention frames: the arm, the jaw and the "
                f"camera fixed at HOME, only the target moved", bold=True)
    for t in ("object", "bin"):
        n = sum(r["target"] == t for r in rows)
        click.echo(f"  {t:7s} {n:4d} placements land inside the policy's square")

    for augment in (False, True):
        tag = ("as the policy sees it: RandomCrop 212 -> 224 and ColorJitter"
               if augment else "the clean centre crop")
        click.secho(f"\n=== {tag} ===", bold=True)
        for t in ("object", "bin"):
            sel = [i for i, r in enumerate(rows) if r["target"] == t]
            F = features(enc, [rows[i]["img"] for i in sel], augment, device)
            uv = np.array([rows[i]["uv"] for i in sel])
            world = np.array([rows[i]["world"] for i in sel])
            rng = np.random.default_rng(0)
            perm = rng.permutation(len(sel))
            cut = int(0.7 * len(sel))
            probe(F, uv, (perm[:cut], perm[cut:]), f"{t}: placements held out at random")
            # a harder split: train on one side of the paper, test on the other
            left = np.flatnonzero(world[:, 0] <= np.median(world[:, 0]))
            right = np.flatnonzero(world[:, 0] > np.median(world[:, 0]))
            probe(F, uv, (left, right), f"{t}: fitted on one half of the paper, "
                                        f"scored on the other")


if __name__ == "__main__":
    main()
