"""Can anything the runtime cannot know reach the policy's input?

    python sim_umi/scripts/audit_obs_leakage.py \
        --zarr sim_umi/data/omx_sim_train.zarr.zip

A whitelist of zarr keys does not answer this. The dataset carries
robot0_demo_start_pose and robot0_demo_end_pose, and the question is not
whether they are stored but whether they reach the tensors that go into
model.forward. demo_end_pose is the pose the episode finished in: if any part
of the input is built from it, the policy is being told where the
demonstration was going, which no robot can know at the time it has to act.

Reading the loader answers it one way. This answers it the other way, by
experiment: the field is moved by a metre, the loader is rebuilt, and the
tensors are compared. A field nothing depends on cannot change anything.

The rebuild matters. SequenceSampler copies the low-dimensional arrays into
memory when it is constructed -- "load low_dim to memory and keep rgb as
compressed zarr array" -- so editing the zarr after the loader exists reaches
nothing, and a test that does it proves only that the write went nowhere.
That is what a positive control is for, and moving robot0_eef_pos is it: if
that changes nothing, the experiment is not connected and no other result
from it means anything.

    robot0_eef_pos    positive control -- must change the tensors
    demo_end_pose     must change nothing at all
    demo_start_pose   may change the observation, because
                      robot0_eef_rot_axis_angle_wrt_start is measured from the
                      episode's first pose -- which the runtime does have, as
                      its own first observation -- and must change no action
"""
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import click
import hydra
import numpy as np
import torch
import zarr
from omegaconf import OmegaConf

OmegaConf.register_new_resolver("eval", eval, replace=True)


def build(zarr_path, config):
    with hydra.initialize_config_dir(
            version_base=None,
            config_dir=str(ROOT / "diffusion_policy" / "config")):
        cfg = hydra.compose(config, overrides=[
            f"task.dataset_path={pathlib.Path(zarr_path).resolve()}",
            "task.dataset.val_ratio=0.0"])
    return hydra.utils.instantiate(cfg.task.dataset), cfg


def perturbed_copy(zarr_path, key, delta, out_dir):
    """The same dataset with one field moved, as a file a loader can be built
    from. A ZipStore cannot rewrite an entry in place, so it goes out to a
    directory store and back.

    `delta` may be a number or a function of the array. A number is the right
    probe for a field that is already constant within an episode, like the
    demo poses. It is the wrong probe for the end-effector track: both pose
    keys are relative to the last observation in the window, so adding the
    same metre to every frame cancels out and the control reads as if nothing
    depends on the trajectory at all.
    """
    tmp = pathlib.Path(out_dir) / f"tmp_{key}.zarr"
    dst = pathlib.Path(out_dir) / f"perturbed_{key}.zarr.zip"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zarr.ZipStore(str(zarr_path), mode="r") as src:
        zarr.copy_store(src, zarr.DirectoryStore(str(tmp)))
    g = zarr.open(str(tmp), mode="a")
    if key not in list(g["data"].array_keys()):
        shutil.rmtree(tmp)
        raise KeyError(key)
    a = np.asarray(g["data"][key][:])
    g["data"][key][:] = delta(a) if callable(delta) else a + delta
    with zarr.ZipStore(str(dst), mode="w") as z:
        zarr.copy_store(zarr.DirectoryStore(str(tmp)), z)
    shutil.rmtree(tmp)
    return dst


def sample_tensors(ds, n, seed):
    """A few samples, with the loader's own noise pinned down."""
    out = []
    for i in range(n):
        np.random.seed(seed + i)
        torch.manual_seed(seed + i)
        s = ds[i]
        out.append(({k: v.clone() for k, v in s["obs"].items()},
                    s["action"].clone()))
    return out


def compare(a, b):
    diffs = {}
    for k in a[0][0]:
        d = max(float((x[0][k] - y[0][k]).abs().max()) for x, y in zip(a, b))
        if d > 0:
            diffs[k] = d
    d = max(float((x[1] - y[1]).abs().max()) for x, y in zip(a, b))
    if d > 0:
        diffs["action"] = d
    return diffs


@click.command()
@click.option("--zarr", "zarr_path", required=True)
@click.option("--config", default="train_diffusion_unet_timm_omx_workspace")
@click.option("--samples", default=6, type=int)
def main(zarr_path, config, samples):
    ds, cfg = build(zarr_path, config)

    click.secho("what the dataset hands the policy", bold=True)
    np.random.seed(0)
    s = ds[0]
    for k, v in s["obs"].items():
        click.echo(f"   obs {k:38s} {tuple(v.shape)}")
    click.echo(f"   action {tuple(s['action'].shape)}")
    stray = [k for k in s["obs"] if "demo_" in k]
    click.secho(f"   demo_* keys in the model's input: "
                f"{stray if stray else 'none'}",
                fg="red" if stray else "green")

    click.secho("\nwhat the shape_meta declares, which is what the encoder reads",
                bold=True)
    declared = list(cfg.task.shape_meta["obs"].keys())
    click.echo("   " + ", ".join(declared))
    extra = sorted(set(s["obs"]) - set(declared))
    if extra:
        click.secho(f"   the dataset also returns {extra}", fg="yellow")

    click.secho("\nnormalizer keys (anything here is scaled into the model)",
                bold=True)
    nk = sorted(ds.get_normalizer().params_dict.keys())
    click.echo("   " + ", ".join(nk))
    bad = [k for k in nk if "demo_" in k]
    click.secho(f"   demo_* in the normalizer: {bad if bad else 'none'}",
                fg="red" if bad else "green")

    base = sample_tensors(ds, samples, seed=1234)
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for key, delta, expect, control in (
                ("robot0_eef_pos",
                 lambda a: a * 1.5,
                 "everything", True),
                ("robot0_demo_end_pose", 1.0, "nothing", False),
                ("robot0_demo_start_pose", 1.0, "observation only", False)):
            try:
                alt = perturbed_copy(zarr_path, key, delta, tmp)
            except KeyError:
                click.secho(f"\n{key} is not in the dataset at all", fg="yellow")
                continue
            ds2, _ = build(str(alt), config)
            diffs = compare(base, sample_tensors(ds2, samples, seed=1234))
            results[key] = diffs
            click.secho(f"\nmoved {key}, rebuilt the loader, re-read "
                        f"{samples} samples"
                        + ("   [positive control]" if control else ""), bold=True)
            if not diffs:
                click.secho("   nothing changed", fg="red" if control else "green")
            for k, d in sorted(diffs.items()):
                click.echo(f"   {k:38s} changed by {d:.3e}")
            click.echo(f"   expected: {expect}")

    if not results.get("robot0_eef_pos"):
        click.secho("\nthe positive control moved nothing: this test is not "
                    "reaching the loader, so it proves nothing", fg="red",
                    bold=True)
        sys.exit(2)

    ok_end = not results.get("robot0_demo_end_pose", {})
    start = results.get("robot0_demo_start_pose", {})
    ok_start = "action" not in start and not any(
        k in start for k in ("camera0_rgb", "robot0_gripper_width",
                             "robot0_eef_pos"))
    click.secho("\nverdict", bold=True)
    click.secho(f"   demo_end_pose reaches nothing the policy sees: "
                f"{'PASS' if ok_end else 'FAIL'}",
                fg="green" if ok_end else "red")
    click.secho(f"   demo_start_pose reaches only _wrt_start, never the action: "
                f"{'PASS' if ok_start else 'FAIL'}",
                fg="green" if ok_start else "red")
    click.echo("   _wrt_start is the pose relative to the episode's FIRST "
               "observation, which the runtime has: policy_bridge keeps its "
               "own first observed pose for exactly this.")
    sys.exit(0 if (ok_end and ok_start) else 1)


if __name__ == "__main__":
    main()
