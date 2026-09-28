"""Standing exactly where the expert stands before it closes, what does the
policy plan?

    python sim_umi/scripts/teacher_forced_grasp.py --checkpoint ...

The expert's transition, measured over twenty episodes, is not what it looked
like from the rollout side. The nose is already down -- pitch 12.4 degrees a
second and a half out, 12.6 at the close, a change of +0.16 +- 0.05 degrees.
What actually happens is an insertion: the ball goes from 13 mm inside the
tool frame to 23, along a path whose length equals its net displacement to
four decimal places in every episode, while the tool decelerates from
5.5 mm/tick to 0.15.

So the question for the checkpoint is narrow. Given the expert's own
observations through that second, does it predict the insertion continuing,
the deceleration, and the jaw shutting at the end of it?

No simulator stepping. The ball is taken where the demonstration recorded it,
which over one second before contact is where it stays.
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

from diffusion_policy.workspace.base_workspace import BaseWorkspace

CROP = 224


def crop224(img):
    h, w = img.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    return cv2.resize(img[y0:y0 + s, x0:x0 + s], (CROP, CROP),
                      interpolation=cv2.INTER_AREA)


def mat(p, R):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, p
    return T


def build_obs(d, t, horizon=2):
    idx = [t - (horizon - 1) + i for i in range(horizon)]
    T = [mat(d["eef_pos"][i], d["eef_rot"][i]) for i in idx]
    inv = np.linalg.inv(T[-1])
    sinv = np.linalg.inv(mat(d["eef_pos"][0], d["eef_rot"][0]))
    pos, rot6, wrt = [], [], []
    for Tk in T:
        rel = inv @ Tk
        pos.append(rel[:3, 3])
        rot6.append(rel[:2, :3].reshape(6))
        wrt.append((sinv @ Tk)[:2, :3].reshape(6))
    rgb = np.stack([crop224(d["rgb"][i]).astype(np.float32).transpose(2, 0, 1) / 255.0
                    for i in idx])
    return {"camera0_rgb": rgb[None],
            "robot0_eef_pos": np.stack(pos)[None].astype(np.float32),
            "robot0_eef_rot_axis_angle": np.stack(rot6)[None].astype(np.float32),
            "robot0_eef_rot_axis_angle_wrt_start": np.stack(wrt)[None].astype(np.float32),
            "robot0_gripper_width": d["gripper_width"][idx].reshape(1, -1, 1).astype(np.float32)}


def six_to_R(six):
    a = np.asarray(six, float).reshape(2, 3)
    r0 = a[0] / np.linalg.norm(a[0])
    r1 = a[1] - (a[1] @ r0) * r0
    return np.stack([r0, r1 / np.linalg.norm(r1), np.cross(r0, r1 / np.linalg.norm(r1))])


def pitch_of(R):
    return math.degrees(math.asin(max(-1.0, min(1.0, -np.asarray(R)[:, 1][2]))))


@click.command()
@click.option("--checkpoint", required=True)
@click.option("--device", default="cuda:0")
@click.option("--seed", default=1234, type=int)
@click.option("--out", default=None)
def main(checkpoint, device, seed, out):
    payload = torch.load(pathlib.Path(checkpoint).open("rb"), pickle_module=dill,
                         map_location="cpu")
    cfg = payload["cfg"]
    ws: BaseWorkspace = hydra.utils.get_class(cfg._target_)(
        cfg, output_dir=str(SIM / "outputs" / "tf_grasp"))
    ws.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = ws.model
    if cfg.training.use_ema and getattr(ws, "ema_model", None) is not None:
        policy = ws.ema_model
    policy.to(device).eval()
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

    rows = []
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        st = d["stage"].astype(str)
        w = d["gripper_width"] * 1000
        g = np.where(st == "GRASP")[0]
        if not len(g):
            continue
        i = next((k for k in g if w[k] < w[g[0]] - 1.0), g[0])
        for t in range(max(i - 10, 1), min(i + 1, len(d["t"]) - 17)):
            obs = build_obs(d, t)
            batch = {k: torch.from_numpy(v).to(device) for k, v in obs.items()}
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            with torch.no_grad():
                act = policy.predict_action(batch, None)["action_pred"][0].cpu().numpy()
            bp, bR = d["eef_pos"][t], d["eef_rot"][t]
            ball = d["eval_ball_pos"][t]
            P = [bR @ act[k, :3] + bp for k in range(16)]
            R = [bR @ six_to_R(act[k, 3:9]) for k in range(16)]
            dep = [float((R[k].T @ (ball - P[k]))[1] * 1000) for k in range(16)]
            pit = [pitch_of(R[k]) for k in range(16)]
            jaw = [float(act[k, 9]) * 1000 for k in range(16)]
            # the expert's own future over the same window
            n = min(16, len(d["eef_pos"]) - t)
            edep, epit, ejaw = [], [], []
            for k in range(n):
                Rk, pk = d["eef_rot"][t + k], d["eef_pos"][t + k]
                edep.append(float((Rk.T @ (d["eval_ball_pos"][t + k] - pk))[1] * 1000))
                epit.append(pitch_of(Rk))
                ejaw.append(float(w[t + k]))
            spd = [float(np.linalg.norm(P[k + 1] - P[k])) * 1000 for k in range(15)]
            rows.append({"episode": p.name, "rel_s": round((t - i) / 10.0, 2),
                         "dep_now": dep[0], "pitch_now": pit[0], "jaw_now": jaw[0],
                         "dep_pred": dep, "pitch_pred": pit, "jaw_pred": jaw,
                         "dep_exp": edep, "pitch_exp": epit, "jaw_exp": ejaw,
                         "speed_pred": spd})
        click.echo(f"  {p.name}: onset at frame {i}")

    click.secho("\nthe policy, standing in the expert's own states through the "
                "grasp transition", bold=True)
    click.echo(f"  {'t':>7s} {'n':>3s} | {'depth now':>10s} | "
               f"{'predicted depth in 0.8s':>24s} {'expert':>8s} | "
               f"{'pitch +0.8s':>12s} {'expert':>8s} | "
               f"{'jaw +0.8s':>10s} {'expert':>8s} | {'speed':>7s}")
    for rel in [round(-1.0 + k / 10, 1) for k in range(11)]:
        g = [r for r in rows if abs(r["rel_s"] - rel) < 1e-6]
        if len(g) < 5:
            continue
        def m(key, k):
            return np.mean([r[key][k] for r in g if len(r[key]) > k])
        click.echo(f"  {rel:+6.1f}s {len(g):3d} | {np.mean([r['dep_now'] for r in g]):+10.2f} | "
                   f"{m('dep_pred',8):+24.2f} {m('dep_exp',8):+8.2f} | "
                   f"{m('pitch_pred',8):+12.2f} {m('pitch_exp',8):+8.2f} | "
                   f"{m('jaw_pred',8):+10.2f} {m('jaw_exp',8):+8.2f} | "
                   f"{np.mean([np.mean(r['speed_pred']) for r in g]):7.2f}")
    click.secho("\n  does it predict the insertion, the stop, and the close?",
                bold=True)
    last = [r for r in rows if abs(r["rel_s"]) < 1e-6]
    if last:
        dd = np.array([r["dep_pred"][8] - r["dep_now"] for r in last])
        de = np.array([r["dep_exp"][min(8, len(r["dep_exp"])-1)] - r["dep_now"]
                       for r in last])
        jj = np.array([min(r["jaw_pred"]) for r in last])
        je = np.array([min(r["jaw_exp"]) for r in last])
        sp = np.array([r["speed_pred"][-1] for r in last])
        click.echo(f"    at the closing instant, over the next 0.8 s the policy "
                   f"moves the ball {dd.mean():+.2f} mm in depth; the expert "
                   f"{de.mean():+.2f}")
        click.echo(f"    narrowest jaw it plans in the horizon "
                   f"{jj.mean():.2f} mm; the expert {je.mean():.2f}")
        click.echo(f"    its speed at the end of the horizon {sp.mean():.2f} "
                   f"mm/tick; the expert has stopped at 0.15")
    out = out or str(SIM / "outputs" / "tf_grasp.json")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(rows))
    click.echo(f"\nwrote {out}")


if __name__ == "__main__":
    main()
