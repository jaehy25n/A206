"""At the pitch the rollout parks in, can the policy tell going-down from
coming-up?

    python sim_umi/scripts/audit_phase_ambiguity.py --checkpoint ...

Between 25 and 32 degrees the demonstrations hold 324 open-jaw frames and
52.8% of them are descending: APPROACH on its way to the ball and RETREAT on
its way back share the band, at +0.02 +- 8.77 deg/s. So the arm's own state
says nothing there about which way to turn, and only the picture can. Whether
the checkpoint actually uses it is a separate question from whether it could,
and this asks it.

Three ways, increasingly sharp:

    every sample     does the sign of the predicted pitch change match the
                     phase it came from?
    matched pairs    the same question restricted to APPROACH and RETREAT
                     samples whose arm state is as close as the dataset allows
    the swap         one sample's low-dimensional state with the other's
                     picture. If vision is the cue, the answer flips.

The swap is a diagnostic. It builds an observation no robot would ever
produce, on purpose, to see which input the answer is hanging on.
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
BAND = (25.0, 32.0)


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


def six_to_R(six):
    a = np.asarray(six, float).reshape(2, 3)
    r0 = a[0] / np.linalg.norm(a[0])
    r1 = a[1] - (a[1] @ r0) * r0
    r1 = r1 / np.linalg.norm(r1)
    return np.stack([r0, r1, np.cross(r0, r1)])


def pitch_of(R):
    return math.degrees(math.asin(max(-1.0, min(1.0, -np.asarray(R)[:, 1][2]))))


def build(d, t, horizon=2):
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


@click.command()
@click.option("--checkpoint", required=True)
@click.option("--device", default="cuda:0")
@click.option("--seed", default=1234, type=int)
@click.option("--rollouts", default="")
@click.option("--out", default=None)
def main(checkpoint, device, seed, rollouts, out):
    payload = torch.load(pathlib.Path(checkpoint).open("rb"), pickle_module=dill,
                         map_location="cpu")
    cfg = payload["cfg"]
    ws: BaseWorkspace = hydra.utils.get_class(cfg._target_)(
        cfg, output_dir=str(SIM / "outputs" / "phase_ambiguity"))
    ws.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = ws.model
    if cfg.training.use_ema and getattr(ws, "ema_model", None) is not None:
        policy = ws.ema_model
    policy.to(device).eval()
    import torchvision
    enc = policy.obs_encoder
    for key in list(enc.key_transform_map.keys()):
        kept = []
        for tf in enc.key_transform_map[key]:
            n = type(tf).__name__
            if n == "RandomCrop":
                kept.append(torchvision.transforms.CenterCrop(tf.size))
            elif n != "ColorJitter":
                kept.append(tf)
        enc.key_transform_map[key] = torch.nn.Sequential(*kept)

    def predict(obs):
        batch = {k: torch.from_numpy(np.ascontiguousarray(v)).to(device)
                 for k, v in obs.items()}
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        with torch.no_grad():
            return policy.predict_action(batch, None)["action_pred"][0].cpu().numpy()

    def rate(act, base_R, k=8):
        """Predicted pitch change over the first k steps, degrees per second."""
        p0 = pitch_of(base_R @ six_to_R(act[0, 3:9]))
        pk = pitch_of(base_R @ six_to_R(act[k, 3:9]))
        return (pk - p0) / (k * 0.1)

    # -------------------------------------------------- gather the samples --
    samples = []
    for p in sorted((SIM / "data" / "demos" / "train").glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        st = d["stage"].astype(str)
        w = d["gripper_width"] * 1000
        pit = np.array([pitch_of(R) for R in d["eef_rot"]])
        for t in range(1, len(st) - 17):
            if not (BAND[0] <= pit[t] < BAND[1]) or w[t] < 45:
                continue
            if st[t] not in ("APPROACH_OBJECT", "RETREAT"):
                continue
            true = (pit[t + 8] - pit[t]) / 0.8
            samples.append({"file": p, "t": t, "phase": st[t], "pitch": pit[t],
                            "ee": d["eef_pos"][t] * 1000, "jaw": w[t],
                            "R": d["eef_rot"][t], "true_rate": true})
    ap = [s for s in samples if s["phase"] == "APPROACH_OBJECT"]
    rt = [s for s in samples if s["phase"] == "RETREAT"]
    click.secho(f"pitch {BAND[0]:.0f}-{BAND[1]:.0f} deg, jaw open: "
                f"{len(ap)} APPROACH and {len(rt)} RETREAT observations", bold=True)
    click.echo(f"  the expert's own pitch rate there: APPROACH "
               f"{np.mean([s['true_rate'] for s in ap]):+.2f}, RETREAT "
               f"{np.mean([s['true_rate'] for s in rt]):+.2f} deg/s")

    cache = {}

    def obs_of(s):
        key = (str(s["file"]), s["t"])
        if key not in cache:
            cache[key] = build(np.load(s["file"], allow_pickle=True), s["t"])
        return cache[key]

    # ------------------------------------------------- 1. every sample --
    for s in samples:
        s["pred_rate"] = rate(predict(obs_of(s)), s["R"])
    click.secho("\n1. every sample: does the predicted pitch change match the "
                "phase?", bold=True)
    click.echo(f"  {'phase':16s} {'n':>4s} {'predicted rate':>15s} {'sd':>7s} "
               f"{'correct sign':>13s} {'|rate|<1':>9s}")
    for lab, g in (("APPROACH (down)", ap), ("RETREAT (up)", rt)):
        r = np.array([s["pred_rate"] for s in g])
        want = -1 if g is ap else +1
        ok = np.mean(np.sign(r) == want) * 100
        click.echo(f"  {lab:16s} {len(g):4d} {r.mean():+15.2f} {r.std():7.2f} "
                   f"{ok:12.1f}% {np.mean(np.abs(r) < 1.0)*100:8.1f}%")
    allr = np.array([s["pred_rate"] for s in samples])
    want = np.array([-1 if s["phase"] == "APPROACH_OBJECT" else 1 for s in samples])
    click.secho(f"  overall sign accuracy {np.mean(np.sign(allr)==want)*100:.1f}% "
                f"(chance 50%)", bold=True)

    # ------------------------------------------------- 2. matched pairs --
    click.secho("\n2. the same question on pairs the arm cannot tell apart",
                bold=True)
    pairs = []
    for s in rt:
        best, bd = None, 1e9
        for a in ap:
            dd = (np.linalg.norm(s["ee"] - a["ee"])
                  + 3.0 * abs(s["pitch"] - a["pitch"])
                  + abs(s["jaw"] - a["jaw"]))
            if dd < bd:
                best, bd = a, dd
        if best is not None:
            pairs.append((best, s, bd))
    pairs.sort(key=lambda x: x[2])
    use = pairs[:min(30, len(pairs))]
    click.echo(f"  {len(use)} pairs, arm states within "
               f"{use[0][2]:.1f} to {use[-1][2]:.1f} mm-equivalent")
    okA = np.mean([p[0]["pred_rate"] < 0 for p in use]) * 100
    okR = np.mean([p[1]["pred_rate"] > 0 for p in use]) * 100
    sep = np.mean([p[1]["pred_rate"] - p[0]["pred_rate"] for p in use])
    click.echo(f"  APPROACH predicted downward in {okA:.1f}%, RETREAT upward "
               f"in {okR:.1f}%")
    click.echo(f"  RETREAT minus APPROACH, per pair: {sep:+.2f} deg/s "
               f"(it should be positive and large)")
    click.echo(f"  the pair is separated by {np.mean([abs(p[0]['ee'][0]-p[1]['ee'][0]) for p in use]):.1f} mm "
               f"in x, {np.mean([abs(p[0]['pitch']-p[1]['pitch']) for p in use]):.2f} deg in pitch")

    # ---------------------------------------------------------- 3. the swap --
    click.secho("\n3. the swap: one sample's arm state with the other's picture",
                bold=True)
    rows = []
    for a, s, _ in use[:20]:
        oa, os_ = obs_of(a), obs_of(s)
        # APPROACH state + RETREAT picture, and the reverse
        mix1 = dict(oa)
        mix1["camera0_rgb"] = os_["camera0_rgb"]
        mix2 = dict(os_)
        mix2["camera0_rgb"] = oa["camera0_rgb"]
        rows.append({
            "a_own": a["pred_rate"], "r_own": s["pred_rate"],
            "a_state_r_rgb": rate(predict(mix1), a["R"]),
            "r_state_a_rgb": rate(predict(mix2), s["R"])})
    A = np.array([r["a_own"] for r in rows])
    R_ = np.array([r["r_own"] for r in rows])
    AR = np.array([r["a_state_r_rgb"] for r in rows])
    RA = np.array([r["r_state_a_rgb"] for r in rows])
    click.echo(f"  {'observation':34s} {'pitch rate':>12s} {'sd':>7s}")
    click.echo(f"  {'APPROACH state + APPROACH picture':34s} {A.mean():+12.2f} {A.std():7.2f}")
    click.echo(f"  {'APPROACH state + RETREAT picture':34s} {AR.mean():+12.2f} {AR.std():7.2f}")
    click.echo(f"  {'RETREAT state + RETREAT picture':34s} {R_.mean():+12.2f} {R_.std():7.2f}")
    click.echo(f"  {'RETREAT state + APPROACH picture':34s} {RA.mean():+12.2f} {RA.std():7.2f}")
    click.secho(f"  swapping the picture moves the answer by "
                f"{np.mean(np.abs(AR-A)):.2f} and {np.mean(np.abs(RA-R_)):.2f} deg/s; "
                f"the gap between the two phases is {abs(R_.mean()-A.mean()):.2f}",
                bold=True)
    flip = np.mean(np.sign(AR) != np.sign(A)) * 100
    flip2 = np.mean(np.sign(RA) != np.sign(R_)) * 100
    click.echo(f"  the sign flips in {flip:.0f}% and {flip2:.0f}% of pairs")

    # ------------------------------------- 4. where the rollout's plans sit --
    if rollouts:
        import gzip
        click.secho("\n4. the stalled rollout, against those two modes", bold=True)
        for path in rollouts.split(","):
            pp = pathlib.Path(path.strip())
            op = gzip.open if pp.suffix == ".gz" else open
            with op(pp, "rt") as f:
                dd = json.load(f)
            e = dd["episodes"][0]
            rr, dz = [], []
            for pl in e["trace"]:
                pa = pl.get("plan_abs") or []
                if len(pa) < 9:
                    continue
                p0 = pitch_of(np.asarray(pa[0]["R"]).reshape(3, 3))
                if not (BAND[0] <= p0 < BAND[1]):
                    continue
                p8 = pitch_of(np.asarray(pa[8]["R"]).reshape(3, 3))
                rr.append((p8 - p0) / 0.8)
                dz.append(pa[8]["p"][2] - pa[0]["p"][2])
            if not rr:
                click.echo(f"  {pp.name}: no plan started in the band")
                continue
            rr = np.array(rr)
            click.echo(f"  {pp.name}: {len(rr)} plans started at 25-32 deg, "
                       f"predicted pitch rate {rr.mean():+.2f} +- {rr.std():.2f} deg/s, "
                       f"downward in {np.mean(rr<0)*100:.0f}%")
            click.echo(f"      expert APPROACH predicts {A.mean():+.2f}, "
                       f"RETREAT {R_.mean():+.2f}; predicted z over the same "
                       f"0.8 s {np.mean(dz):+.2f} mm")
    if out:
        pathlib.Path(out).write_text(json.dumps(
            {"approach": [s["pred_rate"] for s in ap],
             "retreat": [s["pred_rate"] for s in rt],
             "swap": rows}, indent=1))
        click.echo(f"\nwrote {out}")


if __name__ == "__main__":
    main()
