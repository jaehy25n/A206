"""Does the policy's action depend on where the target is?

    python sim_umi/ros/policy_intervention.py --socket-path /tmp/omx_policy.sock

A rollout that reaches the ball is evidence, but weak evidence: the arm could
be following a habit that happens to fit. This asks the question directly. The
arm is returned to the same HOME every time and the jaw to the same opening,
so the low-dimensional half of the observation is identical to the last
decimal. Only the picture changes, because only the ball has moved.

If the policy reads the picture, the action it asks for must follow the ball.
If it does not, the same action comes back whatever the picture shows, and
that is measurable: the spread of the commanded motion across placements
collapses, and its direction stops agreeing with the direction of the ball.

Nothing here is executed. It is one inference per placement.
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import numpy as np
import rclpy

from policy_bridge import decode_action
from policy_rollout import Rollout


def azimuth(cfg, xy):
    bx, by = cfg.robot_base_xy
    return math.atan2(-(xy[0] - bx), xy[1] - by)


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--repeats", default=3, type=int,
              help="inferences per placement; the policy is a sampler, so one "
                   "draw cannot separate a change from its own noise")
@click.option("--out", default=None)
@click.option("--label", default="")
def main(socket_path, repeats, out, label):
    rclpy.init()
    b = Rollout(socket_path)
    b.spin(1.5)
    cfg = b.cfg
    r = float(cfg.object_size[0])
    dt = b.meta["action_dt_s"]

    # left, centre and right at two distances, and the bin parked out of the
    # way so the only thing that differs between frames is the ball
    bx, by = cfg.robot_base_xy
    spots = []
    for radius in (0.20, 0.26):
        for deg in (-40, -20, 0, 20, 40):
            a = math.radians(deg)
            spots.append((round(bx - radius * math.sin(a), 4),
                          round(by + radius * math.cos(a), 4), deg, radius))
    bin_far = (bx + 0.85, by - 0.85)

    click.secho(f"{label}{len(spots)} placements, {repeats} inferences per "
                f"observation, arm returned to HOME before every one", bold=True)
    click.echo(f"  {'ball':>18s} {'seen':>5s} {'first action':>26s} "
               f"{'|step|':>7s} {'chunk end':>26s}")

    rows = []
    for (x, y, deg, radius) in spots:
        if not b.place((x, y), r, bin_far, 0.0):
            click.secho("  could not place the ball", fg="red")
            continue
        if not b.go_home():
            click.secho("  could not reach HOME", fg="red")
            continue
        seen = b.target_visible("object")
        q_home = b.q_now()
        # One observation, taken once, then sent again and again. Repeating
        # the capture would let the arm settle a little differently and the
        # camera catch a different instant, and that difference would be
        # counted as the policy's. Here the bytes are identical, so whatever
        # the action does across repeats is the sampler alone -- and with the
        # server seeded and its crop and jitter made deterministic, it should
        # be nothing at all.
        frames = []
        try:
            for k in range(b.meta["obs_horizon"]):
                f, _ = b.observe()
                frames.append(f)
                if k + 1 < b.meta["obs_horizon"]:
                    b.spin(dt)
        except RuntimeError as e:
            click.secho(f"  {e}", fg="red")
            continue
        p0, R0 = b.ee_now()
        firsts, lasts, chunks = [], [], []
        for _ in range(repeats):
            act, _ = b.infer(frames)
            chunks.append(act[0].copy())
            p1, _, _ = decode_action(act[0, 0], p0, R0)
            pN, _, gN = decode_action(act[0, -1], p0, R0)
            firsts.append((p1 - p0) * 1000)
            lasts.append((pN - p0) * 1000)
        if not firsts:
            continue
        f_mean = np.mean(firsts, axis=0)
        l_mean = np.mean(lasts, axis=0)
        same_obs = float(np.abs(np.array(chunks) - chunks[0]).max()) if chunks else 0.0
        rows.append({"same_obs_action_spread": same_obs,
                     "ball_xy": (x, y), "deg": deg, "radius": radius,
                     "visible": seen,
                     "q_home_max_dev_deg": float(np.degrees(
                         np.abs(q_home - b.q_now()).max())),
                     "first_mm": f_mean.tolist(),
                     "first_spread_mm": float(np.std(firsts, axis=0).max()),
                     "chunk_mm": l_mean.tolist()})
        click.echo(f"  {deg:+4.0f} deg r{radius*1000:3.0f} "
                   f"({x*1000:+5.0f},{y*1000:+5.0f}) {'Y' if seen else '.':>5s} "
                   f"[{f_mean[0]:+7.2f} {f_mean[1]:+7.2f} {f_mean[2]:+7.2f}] "
                   f"{np.linalg.norm(f_mean):7.2f} "
                   f"[{l_mean[0]:+7.2f} {l_mean[1]:+7.2f} {l_mean[2]:+7.2f}]")

    if len(rows) < 3:
        click.secho("not enough placements to say anything", fg="red")
        return

    firsts = np.array([r_["first_mm"] for r_ in rows])
    chunks = np.array([r_["chunk_mm"] for r_ in rows])
    balls = np.array([r_["ball_xy"] for r_ in rows])
    noise = float(np.mean([r_["first_spread_mm"] for r_ in rows]))
    same = max(r_["same_obs_action_spread"] for r_ in rows)

    click.secho("\ndoes the action move with the ball?", bold=True)
    click.echo(f"  spread of the commanded step across placements: "
               f"{np.std(firsts, axis=0).max():.2f} mm")
    click.echo(f"  spread of repeats on the SAME observation bytes: "
               f"{noise:.2f} mm  (largest raw action difference {same:.3e})")
    click.echo(f"  ratio: {np.std(firsts, axis=0).max() / max(noise, 1e-6):.2f}"
               f"   (1 means the ball changes nothing the sampler does not)")

    # does the commanded direction agree with the ball's, in the table plane?
    want = balls - balls.mean(0)
    got = chunks[:, :2] - chunks[:, :2].mean(0)
    for name, v in (("over the whole chunk", got),):
        cos = (want * v).sum(1) / (np.linalg.norm(want, axis=1)
                                   * np.linalg.norm(v, axis=1) + 1e-9)
        click.echo(f"  direction agreement {name}: mean cosine "
                   f"{cos.mean():+.3f}, {int((cos > 0).sum())}/{len(cos)} "
                   f"placements point the right way")
    for ax, nm in ((0, "x"), (1, "y")):
        c = np.corrcoef(balls[:, ax], chunks[:, ax])[0, 1]
        click.echo(f"  correlation of ball {nm} with commanded {nm}: {c:+.3f}")

    q_dev = max(r_["q_home_max_dev_deg"] for r_ in rows)
    click.secho(f"\n  the arm was within {q_dev:.3f} deg of the same pose at "
                f"every placement, so the low-dimensional observation is the "
                f"same and only the picture differs", bold=True)
    if out:
        pathlib.Path(out).write_text(json.dumps(rows, indent=2))
        click.echo(f"wrote {out}")
    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
