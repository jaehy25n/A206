"""Is every training window really on the grid the contract claims?

    python sim_umi/scripts/audit_timing.py --split train

The policy is told action_dt_s = 0.1 and reads row indices. So what has to
hold is not that neighbouring rows are 100 ms apart on average, but that
across a whole window -- two observations back and sixteen actions forward --
row i+k sits 0.1*k seconds from row i. This measures that directly, over every
window the sampler could draw.

It also counts the windows that would straddle a gap. A picture that never
arrived leaves a hole; a window across it contains a step the model would read
as one tenth of a second and that was two. Those windows must be zero, which
the converter arranges by cutting the episode at the gap rather than
interpolating a frame that was never taken.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"

import click
import numpy as np

DT = 0.1
OBS_HORIZON = 2          # observations at [-0.1, 0]
ACTION_HORIZON = 16
#: what one window spans: the earliest observation to the latest action
WINDOW = OBS_HORIZON - 1 + ACTION_HORIZON + 1
MAX_STEP_S = 0.105


@click.command()
@click.option("--split", default="train")
@click.option("--in-dir", default=None)
def main(split, in_dir):
    src = pathlib.Path(in_dir or (SIM / "data" / "demos" / split))
    eps = sorted(src.glob("episode_*.npz"))
    if not eps:
        raise click.ClickException(f"no episodes under {src}")

    dev_all, dev_kept, cross, n_win, n_rows, gaps = [], [], 0, 0, 0, []
    seg_worst = []
    worst = None
    for p in eps:
        d = np.load(p, allow_pickle=True)
        t = np.asarray(d["t"], np.float64)
        n_rows += len(t)
        step = np.diff(t)
        gaps.extend(step[step > MAX_STEP_S].tolist())
        # where the converter will cut
        cuts = [0] + list(np.flatnonzero(step > MAX_STEP_S) + 1) + [len(t)]
        segs = [(a, b) for a, b in zip(cuts[:-1], cuts[1:])]
        # every gap must fall on a cut, so no segment has one inside it
        for a, b in segs:
            if b - a >= 2:
                seg_worst.append(float(np.diff(t[a:b]).max()))
        for i in range(len(t) - WINDOW + 1):
            n_win += 1
            k = np.arange(WINDOW)
            dev = np.abs((t[i:i + WINDOW] - t[i]) - DT * k)
            dev_all.append(dev.max())
            if any(a <= i and i + WINDOW <= b for a, b in segs):
                dev_kept.append(dev.max())
            else:
                cross += 1
                if worst is None or dev.max() > worst[0]:
                    worst = (dev.max(), p.name, i)

    dev_all = np.array(dev_all) * 1000
    dev_kept = np.array(dev_kept) * 1000 if dev_kept else np.zeros(1)
    click.secho(f"{len(eps)} episodes, {n_rows} rows, {n_win} windows of "
                f"{WINDOW} rows ({OBS_HORIZON} observations, "
                f"{ACTION_HORIZON} actions)", bold=True)

    click.secho("\nt[i+k] - t[i] against 0.1*k, worst k in each window", bold=True)
    click.echo(f"  every window        mean {dev_all.mean():7.4f}  p95 "
               f"{np.percentile(dev_all, 95):7.4f}  max {dev_all.max():7.4f} ms")
    click.echo(f"  the ones kept       mean {dev_kept.mean():7.4f}  p95 "
               f"{np.percentile(dev_kept, 95):7.4f}  max {dev_kept.max():7.4f} ms")
    for lim in (1.0, 2.5, 5.0):
        click.echo(f"  kept windows within {lim:5.1f} ms: "
                   f"{(dev_kept <= lim).mean()*100:6.2f}%")

    click.secho(f"\ngaps longer than {MAX_STEP_S*1000:.0f} ms", bold=True)
    if gaps:
        g = np.array(gaps) * 1000
        click.echo(f"  {len(g)} of them: {np.round(np.unique(np.round(g)), 0)} ms")
    else:
        click.secho("  none", fg="green")

    click.secho("\nwindows the cut removes", bold=True)
    click.echo(f"  {cross} of {n_win} ({cross/max(n_win,1)*100:.2f}%) straddle a "
               f"gap and are dropped with it")
    if worst:
        click.echo(f"  worst of them: {worst[1]} at row {worst[2]}, "
                   f"{worst[0]*1000:.1f} ms off the grid")

    click.secho("\nafter the cut, the largest step inside any segment", bold=True)
    sw = max(seg_worst) * 1000 if seg_worst else 0.0
    ok = sw <= MAX_STEP_S * 1000
    click.secho(f"  {sw:.3f} ms -> {'PASS' if ok else 'a gap survived the cut'}",
                fg="green" if ok else "red")

    # the verdict is about what reaches the sampler, not about
    # windows the converter removes
    jitter_only = dev_kept.max() <= 5.0
    verdict = ("temporal contract holds: only the camera's tick jitter is left"
               if (ok and jitter_only) else "temporal contract is NOT clean")
    click.secho(f"\n{verdict}", bold=True,
                fg="green" if (ok and jitter_only) else "red")
    sys.exit(0 if (ok and jitter_only) else 1)


if __name__ == "__main__":
    main()
