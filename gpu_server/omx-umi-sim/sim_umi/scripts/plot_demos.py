"""Draw the collected demonstrations, so they can be looked at rather than
summarised.

    python sim_umi/scripts/plot_demos.py

Writes into sim_umi/outputs/review/:

    spread.png      every training path from above, with the validation ones
                    on top -- the task family, and whether validation sits
                    inside it or outside
    train_*.png     per episode: the path from above, height and gripper width
                    against time, and the ball's height with them
    val_*.png       the same for the held-out episodes
    frames_*.png    the wrist camera through one episode, the picture the
                    policy is actually given

The gripper width drawn is the one in the observation -- estimated from the
camera -- with the simulator's true width behind it, because the gap between
those two is the thing that was wrong three times this week.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))

import click
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

STAGE_COLOUR = {
    "pregrasp": "#4c72b0",
    "close": "#dd8452",
    "grasp": "#55a868",
    "open": "#c44e52",
    "retract": "#8172b3",
    "settle": "#937860",
}
OUT = SIM / "outputs" / "review"


def load(split):
    eps = []
    for p in sorted((SIM / "data" / "demos" / split).glob("episode_*.npz")):
        d = np.load(p, allow_pickle=True)
        eps.append({"name": p.stem, "t": d["t"], "pos": d["eef_pos"],
                    "w": d["gripper_width"] * 1000,
                    "w_gt": d["eval_gripper_width_gt"] * 1000,
                    "ball": d["eval_ball_pos"], "stage": d["stage"],
                    "rgb": d["rgb"], "spec": json.loads(str(d["spec"]))})
    return eps


def draw_path(ax, ep, lw=1.6, colour_by_stage=True):
    pos, st = ep["pos"], ep["stage"]
    if colour_by_stage:
        for s in STAGE_COLOUR:
            m = st == s
            if m.any():
                ax.plot(pos[m, 0] * 1000, pos[m, 1] * 1000, ".",
                        ms=lw * 2, color=STAGE_COLOUR[s], label=s)
    else:
        ax.plot(pos[:, 0] * 1000, pos[:, 1] * 1000, "-", lw=lw, color="0.75")
    sp = ep["spec"]
    ax.plot(sp["object_xy"][0] * 1000, sp["object_xy"][1] * 1000, "o",
            ms=9, mfc="none", mec="k", mew=1.4)
    ax.plot(sp["bin_xy"][0] * 1000, sp["bin_xy"][1] * 1000, "s",
            ms=11, mfc="none", mec="k", mew=1.4)


def spread(train, val):
    fig, ax = plt.subplots(figsize=(7.5, 7.0))
    for ep in train:
        draw_path(ax, ep, colour_by_stage=False)
    for i, ep in enumerate(val):
        ax.plot(ep["pos"][:, 0] * 1000, ep["pos"][:, 1] * 1000, "-", lw=2.0,
                label=f"val {i}")
    for ep in train + val:
        sp = ep["spec"]
        ax.plot(sp["object_xy"][0] * 1000, sp["object_xy"][1] * 1000, "o",
                ms=5, color="#55a868", alpha=0.7)
        ax.plot(sp["bin_xy"][0] * 1000, sp["bin_xy"][1] * 1000, "s",
                ms=6, color="#c44e52", alpha=0.7)
    ax.plot([], [], "o", color="#55a868", label="ball")
    ax.plot([], [], "s", color="#c44e52", label="bin")
    ax.plot([], [], "-", color="0.75", label=f"{len(train)} training paths")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title("every path from above: 20 training, 5 held out")
    ax.legend(fontsize=8, loc="upper left", ncol=2)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "spread.png", dpi=130)
    plt.close(fig)


def episode_figure(ep, tag):
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.4))
    draw_path(axes[0], ep)
    axes[0].set_xlabel("x (mm)")
    axes[0].set_ylabel("y (mm)")
    axes[0].set_aspect("equal")
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=7, ncol=2)
    sp = ep["spec"]
    axes[0].set_title(f"{ep['name']}  from above\n"
                      f"pitch {sp['pitch_deg']:.0f} deg, standoff "
                      f"{sp['standoff']*1000:.0f} mm", fontsize=10)

    t = ep["t"]
    axes[1].plot(t, ep["pos"][:, 2] * 1000, "-", lw=1.8, label="tool height")
    ball_z = ep["ball"][:, 2] * 1000
    axes[1].plot(t, ball_z, "-", lw=1.4, color="#55a868", label="ball height")
    for s, c in STAGE_COLOUR.items():
        m = ep["stage"] == s
        if m.any():
            axes[1].axvspan(t[m].min(), t[m].max(), color=c, alpha=0.10)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("height (mm)")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8)
    axes[1].set_title("height, with the stages shaded")

    axes[2].plot(t, ep["w"], "-", lw=2.0, label="camera estimate (in the observation)")
    axes[2].plot(t, ep["w_gt"], "--", lw=1.2, color="k", label="simulator truth")
    axes[2].set_xlabel("time (s)")
    axes[2].set_ylabel("gripper width (mm)")
    axes[2].grid(alpha=0.3)
    axes[2].legend(fontsize=8)
    err = np.abs(ep["w"] - ep["w_gt"])
    axes[2].set_title(f"gripper width\nerror mean {err.mean():.2f} mm, "
                      f"max {err.max():.2f} mm")
    fig.tight_layout()
    fig.savefig(OUT / f"{tag}.png", dpi=125)
    plt.close(fig)


def frames_figure(ep, tag, n=8):
    """Both the stream and the crop taken out of it.

    The camera publishes 320x180; the policy is handed the central square of
    it, resized to 224. Showing only the wide frame would show something the
    policy never sees, and the crop is where the ball has to be.
    """
    import cv2
    idx = np.linspace(0, len(ep["rgb"]) - 1, n).astype(int)
    fig, axes = plt.subplots(2, n, figsize=(2.0 * n, 4.8))
    for k, col in zip(idx, range(n)):
        f = ep["rgb"][k]
        axes[0, col].imshow(f)
        h, w = f.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        axes[0, col].add_patch(plt.Rectangle((x0, y0), side, side, fill=False,
                                             ec="#dd8452", lw=1.4))
        axes[1, col].imshow(cv2.resize(f[y0:y0 + side, x0:x0 + side], (224, 224),
                                       interpolation=cv2.INTER_AREA))
        axes[0, col].set_title(f"{ep['t'][k]:.1f}s {ep['stage'][k]}\n"
                               f"{ep['w'][k]:.0f} mm", fontsize=8)
        for r in (0, 1):
            axes[r, col].set_xticks([])
            axes[r, col].set_yticks([])
    axes[0, 0].set_ylabel("camera 320x180", fontsize=8)
    axes[1, 0].set_ylabel("policy input 224", fontsize=8)
    fig.suptitle(f"{ep['name']}: the wrist camera, and the central square of it "
                 f"the policy is given (magenta patches already removed)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / f"{tag}.png", dpi=120)
    plt.close(fig)


@click.command()
@click.option("--n-train", default=5, type=int)
@click.option("--n-val", default=5, type=int)
def main(n_train, n_val):
    OUT.mkdir(parents=True, exist_ok=True)
    train, val = load("train"), load("val")
    click.echo(f"train {len(train)} episodes, val {len(val)}")
    spread(train, val)
    for ep in train[:n_train]:
        episode_figure(ep, f"train_{ep['name'][-4:]}")
    for ep in val[:n_val]:
        episode_figure(ep, f"val_{ep['name'][-4:]}")
    frames_figure(train[0], "frames_train_0000")
    frames_figure(val[0], "frames_val_0000")
    for p in sorted(OUT.glob("*.png")):
        click.echo(f"  {p.relative_to(ROOT)}  {p.stat().st_size//1024} kB")


if __name__ == "__main__":
    main()
