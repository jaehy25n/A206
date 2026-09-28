"""What does the policy predict when it is standing where the expert stood?

    python sim_umi/scripts/teacher_forced.py --episodes 0,3

In its own rollouts the policy asks for 2.10 mm of tool motion per tick against
the expert's 4.84, and in two of five placements it asks for poses the arm
cannot reach from where it is -- the run of reachable waypoints ahead of it was
2 and 4 at the median, against 8 for the placements that ran to the end. Two
things would produce that and they need different answers.

If the same checkpoint, handed the expert's own observations, predicts fast and
reachable motion, then it knows the task and what breaks it is being somewhere
the demonstrations never were: a closed-loop distribution shift. If it predicts
slowly and unreachably from the expert's own states too, the checkpoint has not
learned the demonstrations' pace.

So this puts the expert's observations in and measures the same things the
rollout measures -- how far each predicted step moves, whether the arm could
reach it, how long the reachable run is -- plus the one thing a rollout cannot
measure: how far the prediction is from what the expert actually did next.

No ROS and no simulator stepping. The observations are the recorded frames,
assembled the way policy_bridge assembles them at run time, and the arm is only
used for its kinematics.
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))

import click
import cv2
import dill
import hydra
import numpy as np
import torch

from collector import Collector
from diffusion_policy.workspace.base_workspace import BaseWorkspace
from scene import SceneConfig, write_scene

CROP = 224


def crop224(img):
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    return cv2.resize(img[y0:y0 + side, x0:x0 + side], (CROP, CROP),
                      interpolation=cv2.INTER_AREA)


def mat(p, R):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, p
    return T


def build_obs(d, t, obs_horizon=2):
    """The five keys, exactly as policy_bridge builds them at run time."""
    idx = [t - (obs_horizon - 1) + i for i in range(obs_horizon)]
    T = [mat(d["eef_pos"][i], d["eef_rot"][i]) for i in idx]
    T_last_inv = np.linalg.inv(T[-1])
    T_start_inv = np.linalg.inv(mat(d["eef_pos"][0], d["eef_rot"][0]))
    pos, rot6, wrt = [], [], []
    for Tk in T:
        rel = T_last_inv @ Tk
        pos.append(rel[:3, 3])
        rot6.append(rel[:2, :3].reshape(6))
        wrt.append((T_start_inv @ Tk)[:2, :3].reshape(6))
    rgb = np.stack([crop224(d["rgb"][i]).astype(np.float32).transpose(2, 0, 1) / 255.0
                    for i in idx])
    return {
        "camera0_rgb": rgb[None],
        "robot0_eef_pos": np.stack(pos)[None].astype(np.float32),
        "robot0_eef_rot_axis_angle": np.stack(rot6)[None].astype(np.float32),
        "robot0_eef_rot_axis_angle_wrt_start": np.stack(wrt)[None].astype(np.float32),
        "robot0_gripper_width": d["gripper_width"][idx].reshape(1, -1, 1).astype(np.float32),
    }


def rot6d_to_mat(six):
    a = np.asarray(six, float).reshape(2, 3)
    r0 = a[0] / np.linalg.norm(a[0])
    r1 = a[1] - (a[1] @ r0) * r0
    r1 = r1 / np.linalg.norm(r1)
    return np.stack([r0, r1, np.cross(r0, r1)])


@click.command()
@click.option("--checkpoint", required=True)
@click.option("--split", default="train")
@click.option("--episodes", default="0,3", help="which placements, comma separated")
@click.option("--stride", default=7, type=int, help="sample every Nth timestep")
@click.option("--device", default="cuda:0")
@click.option("--seed", default=1234, type=int)
@click.option("--out", default=None)
def main(checkpoint, split, episodes, stride, device, seed, out):
    payload = torch.load(pathlib.Path(checkpoint).open("rb"), pickle_module=dill,
                         map_location="cpu")
    cfg = payload["cfg"]
    ws: BaseWorkspace = hydra.utils.get_class(cfg._target_)(
        cfg, output_dir=str(SIM / "outputs" / "teacher_forced"))
    ws.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = ws.model
    if cfg.training.use_ema and getattr(ws, "ema_model", None) is not None:
        policy = ws.ema_model
    policy.to(device).eval()
    # the evaluation path, as the deployment server runs it
    import torchvision
    enc = policy.obs_encoder
    for key in list(enc.key_transform_map.keys()):
        kept = []
        for t in enc.key_transform_map[key]:
            n = type(t).__name__
            if n == "RandomCrop":
                kept.append(torchvision.transforms.CenterCrop(t.size))
            elif n != "ColorJitter":
                kept.append(t)
        enc.key_transform_map[key] = torch.nn.Sequential(*kept)

    scfg = SceneConfig()
    kin = Collector(str(write_scene(scfg)), cfg=scfg, render=False)
    dt = 0.1

    def project(p_abs, R_abs):
        fwd = R_abs[:, 1]
        pitch = float(math.asin(max(-1.0, min(1.0, -fwd[2]))))
        q, ep, er, oop = kin.solve_ik_best(p_abs, pitch)
        return float(ep) * 1000.0

    rows = []
    for e in [int(x) for x in episodes.split(",")]:
        p = sorted((SIM / "data" / "demos" / split).glob("episode_*.npz"))[e]
        d = np.load(p, allow_pickle=True)
        n = len(d["t"])
        click.secho(f"\n{p.name}: {n} frames", bold=True)
        for t in range(1, n - 16, stride):
            obs = build_obs(d, t)
            batch = {k: torch.from_numpy(v).to(device) for k, v in obs.items()}
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            with torch.no_grad():
                act = policy.predict_action(batch, None)["action_pred"][0].cpu().numpy()
            base_p, base_R = d["eef_pos"][t], d["eef_rot"][t]
            P = np.array([base_R @ act[k, :3] + base_p for k in range(16)])
            R = [base_R @ rot6d_to_mat(act[k, 3:9]) for k in range(16)]
            step = np.linalg.norm(np.diff(P, axis=0), axis=1) * 1000
            # the one number the arm cannot negotiate: the tool pitch. The
            # demonstrations never leave [7.9, 46.3] degrees, and a pitch
            # outside it is what the 5-DoF IK refuses.
            pit = [math.degrees(math.asin(max(-1.0, min(1.0, -Rk[:, 1][2]))))
                   for Rk in R]
            # feasibility of each future waypoint, the runtime's only gate
            reach, first_bad = [], None
            for k in range(1, 9):
                err = project(P[k], R[k])
                ok = err <= 2.0
                reach.append(ok)
                if not ok and first_bad is None:
                    first_bad = k
            prefix = 0
            for ok in reach:
                if not ok:
                    break
                prefix += 1
            # what the expert actually did over the same window
            exp = d["eef_pos"][t:t + 16]
            exp_step = np.linalg.norm(np.diff(exp, axis=0), axis=1) * 1000
            err_mm = np.linalg.norm(P[:len(exp)] - exp, axis=1) * 1000
            rows.append({"episode": e, "t": int(t), "stage": str(d["stage"][t]),
                         "raw_mm_per_tick": float(step.mean()),
                         "expert_mm_per_tick": float(exp_step.mean()),
                         "p1_reachable": bool(reach[0]),
                         "valid_prefix": prefix,
                         "first_unreachable_k": first_bad,
                         "reachable_ratio": float(np.mean(reach)),
                         "pos_err_vs_expert_mm": float(err_mm.mean()),
                         "pos_err_last_mm": float(err_mm[-1]),
                         "pitch_mean_deg": float(np.mean(pit)),
                         "pitch_max_deg": float(np.max(pit)),
                         "pitch_expert_deg": float(math.degrees(math.asin(
                             max(-1.0, min(1.0, -d["eef_rot"][t][:, 1][2]))))),
                         # action[0] is the observation's own state, so P0's
                         # width should come back as the width handed in
                         "p0_width_mm": float(act[0, 9]) * 1000.0,
                         "obs_width_mm": float(d["gripper_width"][t]) * 1000.0,
                         "p8_width_mm": float(act[8, 9]) * 1000.0})
        click.echo(f"  {sum(1 for r in rows if r['episode']==e)} samples")

    click.secho("\n=== the policy standing where the expert stood ===", bold=True)
    hdr = (f"  {'stage':16s} {'n':>4s} {'raw':>7s} {'expert':>7s} {'P1 ok':>7s} "
           f"{'prefix':>7s} {'reach':>7s} {'err vs expert':>14s}")
    click.echo(hdr)
    stages = list(dict.fromkeys(r["stage"] for r in rows))
    for s in stages:
        g = [r for r in rows if r["stage"] == s]
        if len(g) < 3:
            continue
        click.echo(f"  {s:16s} {len(g):4d} "
                   f"{np.mean([r['raw_mm_per_tick'] for r in g]):6.2f}  "
                   f"{np.mean([r['expert_mm_per_tick'] for r in g]):6.2f}  "
                   f"{np.mean([r['p1_reachable'] for r in g])*100:6.1f}% "
                   f"{np.mean([r['valid_prefix'] for r in g]):6.2f}  "
                   f"{np.mean([r['reachable_ratio'] for r in g])*100:6.1f}% "
                   f"{np.mean([r['pos_err_vs_expert_mm'] for r in g]):13.2f}")
    e0 = np.array([r["p0_width_mm"] - r["obs_width_mm"] for r in rows])
    click.secho(f"\n  P0 width against the width handed in: mean "
                f"{e0.mean():+.3f} mm, |max| {np.abs(e0).max():.3f} mm "
                f"over {len(rows)} windows", bold=True)
    narrow = [r for r in rows if r["obs_width_mm"] < 40]
    if narrow:
        e1 = np.array([r["p0_width_mm"] - r["obs_width_mm"] for r in narrow])
        click.echo(f"  of those, the {len(narrow)} with the jaw already shut: "
                   f"mean {e1.mean():+.3f} mm, |max| {np.abs(e1).max():.3f} mm")
    click.secho("\n  tool pitch: the policy against the expert it is standing in",
                bold=True)
    for s_ in stages:
        g = [r for r in rows if r["stage"] == s_]
        if len(g) < 3:
            continue
        click.echo(f"  {s_:16s} policy {np.mean([r['pitch_mean_deg'] for r in g]):6.1f} "
                   f"(max {np.max([r['pitch_max_deg'] for r in g]):6.1f})   "
                   f"expert {np.mean([r['pitch_expert_deg'] for r in g]):6.1f}   "
                   f"outside [7.9,46.3]: "
                   f"{np.mean([not (7.9 <= r['pitch_max_deg'] <= 46.3) for r in g])*100:5.1f}%")
    click.secho("\n  by placement", bold=True)
    for e in sorted({r["episode"] for r in rows}):
        g = [r for r in rows if r["episode"] == e]
        click.echo(f"  episode {e}: raw {np.mean([r['raw_mm_per_tick'] for r in g]):5.2f} "
                   f"vs expert {np.mean([r['expert_mm_per_tick'] for r in g]):5.2f} mm/tick, "
                   f"P1 reachable {np.mean([r['p1_reachable'] for r in g])*100:5.1f}%, "
                   f"prefix {np.mean([r['valid_prefix'] for r in g]):4.2f}/8")
    out = out or str(SIM / "outputs" / "teacher_forced.json")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(rows, indent=1))
    click.echo(f"\nwrote {out}")
    kin.close()


if __name__ == "__main__":
    main()
