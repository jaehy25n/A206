"""Accepted demonstrations -> a UMI ReplayBuffer zarr.

    python sim_umi/scripts/demos_to_umi_zarr.py --split train

Writes the key set UmiDataset reads, and only that set. The recordings also
carry the simulator's true gripper width and the ball's pose; those are
evaluation metadata and they stay out of the observation keys, because a
policy that can see them is not the policy that will run.

    camera0_rgb                 (N,224,224,3) uint8, JpegXl
    robot0_eef_pos              (N,3)    absolute, FK of /joint_states
    robot0_eef_rot_axis_angle   (N,3)    rotation vector
    robot0_gripper_width        (N,1)    ESTIMATED from the camera
    robot0_demo_start_pose      (N,6)    the episode's first pose, repeated
    robot0_demo_end_pose        (N,6)

The 16-step relative actions are not stored: UmiDataset builds them from these
absolute poses at load time, which is the contract the checkpoint was trained
under. Storing our own would be a second opinion about what the actions mean.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import json
import pathlib

import click
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from diffusion_policy.codecs.imagecodecs_numcodecs import JpegXl, register_codecs
from diffusion_policy.common.replay_buffer import ReplayBuffer

register_codecs()
SIM = pathlib.Path(ROOT) / "sim_umi"


#: The largest step that is still one action step. The grid is 100 ms and the
#: camera's phase wanders by a 2 ms control step, so 105 leaves room for that
#: and for nothing else.
MAX_STEP_S = 0.105
#: A piece shorter than one whole training window cannot produce a sample, so
#: it is not worth carrying: obs horizon 2 plus action horizon 16.
MIN_SEGMENT = 17


def center_crop_resize(img, out_wh):
    """The runtime contract: central square, INTER_AREA, no padding."""
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    return cv2.resize(img[y0:y0 + side, x0:x0 + side], tuple(out_wh),
                      interpolation=cv2.INTER_AREA)


@click.command()
@click.option("--split", default="train")
@click.option("--in-dir", default=None)
@click.option("--out", default=None)
@click.option("--out-res", default="224,224")
@click.option("-cl", "--compression-level", default=99, type=int)
def main(split, in_dir, out, out_res, compression_level):
    ow, oh = (int(x) for x in out_res.split(","))
    # Several directories can go in at once, comma separated, because a
    # corrective subset is kept beside the clean one on disk rather than
    # mixed into it -- so that "clean" and "clean + v2" remain two things
    # that can be built, compared and told apart later.
    srcs = [pathlib.Path(x) for x in (in_dir or str(SIM / "data" / "demos" / split)).split(",")]
    eps = [q for src in srcs for q in sorted(src.glob("episode_*.npz"))]
    if not eps:
        raise click.ClickException(f"no episodes under {', '.join(map(str, srcs))}")
    click.echo(f"{len(eps)} episodes from " + ", ".join(
        f"{src.name} ({len(sorted(src.glob('episode_*.npz')))})" for src in srcs))
    out_path = pathlib.Path(out or (SIM / "data" / f"omx_sim_{split}.zarr.zip"))

    buf = ReplayBuffer.create_empty_numpy()
    rgb_chunks, meta = [], []
    for p in eps:
        d = np.load(p, allow_pickle=True)
        pos = d["eef_pos"].astype(np.float32)
        rot = Rotation.from_matrix(d["eef_rot"]).as_rotvec().astype(np.float32)
        grip = d["gripper_width"].astype(np.float32).reshape(-1, 1)
        pose6 = np.concatenate([pos, rot], axis=-1)
        n = len(pos)

        # An action step is a tenth of a second by contract, and the sampler
        # reads row indices, so a row pair further apart than that is a step
        # the model would mistake for a normal one. A picture that never
        # arrived leaves exactly such a hole. The episode is cut there and
        # each piece goes in as its own episode, which is the only thing
        # SequenceSampler will not build a window across. Nothing is
        # interpolated: a frame that was not taken is not invented.
        t = d["t"]
        cuts = [0] + list(np.flatnonzero(np.diff(t) > MAX_STEP_S) + 1) + [n]
        segments = [(a, b) for a, b in zip(cuts[:-1], cuts[1:])
                    if b - a >= MIN_SEGMENT]
        dropped = n - sum(b - a for a, b in segments)
        for a, b in segments:
            buf.add_episode({
                "robot0_eef_pos": pos[a:b],
                "robot0_eef_rot_axis_angle": rot[a:b],
                "robot0_gripper_width": grip[a:b],
                # the episode's true first and last pose, not the segment's:
                # _wrt_start has to mean the same thing it means at run time,
                # where it is measured from the first observation of the run
                "robot0_demo_start_pose": np.tile(pose6[0], (b - a, 1)),
                "robot0_demo_end_pose": np.tile(pose6[-1], (b - a, 1)),
            })
            rgb_chunks.append(np.stack([center_crop_resize(f, (ow, oh))
                                        for f in d["rgb"][a:b]]))
        spec = json.loads(str(d["spec"]))
        # The width is read off a picture, and the picture is about a tenth of
        # a second old. While the jaw is still that is invisible; while it is
        # sweeping from 31 to 52 mm in a fifth of a second it is worth ten
        # millimetres, and comparing it against a joint state read now
        # measures the lag rather than the estimate. The runtime has the same
        # lag, so the recorded number is the honest one. What the check is for
        # is an estimate that has stopped tracking, so it is applied where the
        # jaw is quasi-static and the transient is reported separately.
        gt = d["eval_gripper_width_gt"]
        dt = np.diff(d["t"], prepend=d["t"][0] - 0.1)
        speed = np.abs(np.diff(gt, prepend=gt[0])) / np.maximum(dt, 1e-3)
        moving = speed > 0.05                       # 50 mm/s
        # The picture lags, so the mismatch outlives the motion by a frame or
        # two: the joint state has settled at 52 mm while the camera is still
        # showing the jaw on its way there. Widen the window by two frames
        # each side rather than call that a tracking failure.
        w = np.zeros_like(moving)
        for k in range(-2, 3):
            w |= np.roll(moving, k)
        moving = w
        e = np.abs(d["gripper_width"] - gt)
        det = (d["eval_width_detected"] if "eval_width_detected" in d
               else np.ones(len(e), bool))
        # A held sample is a known stale value, so its disagreement with the
        # truth measures the hold and not the estimator. The two are checked
        # separately: the estimate has to track while the jaw is still, and a
        # hold has to be short. Squeezing the ball at the grasp hides a tip
        # for two frames out of three hundred, and that is the runtime's
        # behaviour too -- what would not be is a hold that goes on.
        fresh = det & ~moving
        err = float(e[fresh].max()) if fresh.any() else 0.0
        err_moving = float(e[moving].max()) if moving.any() else 0.0
        err_held = float(e[~det].max()) if (~det).any() else 0.0
        held = float(1.0 - det.mean())
        run, longest = 0, 0
        for v in det:
            run = 0 if v else run + 1
            longest = max(longest, run)
        if err > 0.002 or held > 0.05 or longest > 3:
            raise SystemExit(
                f"{p.name}: width error {err*1000:.2f} mm with the jaw still "
                f"and the tips seen, {held*100:.1f}% of samples held, longest "
                f"hold {longest} frames -- refusing to build a dataset on it")
        meta.append({"file": p.name, "frames": int(n), "spec": spec,
                     "segments": [[int(a), int(b)] for a, b in segments],
                     "frames_dropped_to_gaps": int(dropped),
                     "width_vs_gt_max_mm": round(err * 1000, 3),
                     "width_vs_gt_max_mm_jaw_moving": round(err_moving * 1000, 3),
                     "width_vs_gt_max_mm_while_held": round(err_held * 1000, 3),
                     "longest_hold_frames": int(longest),
                     "frames_jaw_moving": int(moving.sum()),
                     "width_held_fraction": round(held, 4),
                     "ball_final": np.round(d["eval_ball_pos"][-1] * 1000, 1).tolist()})
        click.echo(f"  {p.name}  {n:4d} frames   width error max "
                   f"{err*1000:4.2f} mm tracking, {err_moving*1000:4.2f} mm while "
                   f"the jaw moves ({int(moving.sum()):3d} frames), "
                   f"{err_held*1000:4.2f} mm while held ({int((~det).sum())} frames, "
                   f"longest run {longest})")

    n_cut = sum(len(m["segments"]) - 1 for m in meta)
    if n_cut:
        click.secho(f"\n{n_cut} episode(s) were cut at a gap longer than "
                    f"{MAX_STEP_S*1000:.0f} ms; "
                    f"{sum(m['frames_dropped_to_gaps'] for m in meta)} frames "
                    f"fell in pieces too short to sample", fg="yellow")
    rgb = np.concatenate(rgb_chunks)
    if len(rgb) != buf.n_steps:
        raise click.ClickException(f"rgb {len(rgb)} != lowdim {buf.n_steps}")
    buf.data["camera0_rgb"] = rgb
    click.echo(f"\nepisodes {buf.n_episodes}  frames {buf.n_steps}  "
               f"dt 0.1 s (10 Hz)")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    import zarr
    with zarr.ZipStore(str(out_path), mode="w") as store:
        buf.save_to_store(store, chunks={"camera0_rgb": (1, oh, ow, 3)},
                          compressors={"camera0_rgb": JpegXl(
                              level=compression_level, numthreads=1)})
    side = "the raw stream is 16:9; the square is its centre"
    (out_path.parent / f"{out_path.stem.replace('.zarr','')}.meta.json").write_text(
        json.dumps({"split": split, "source": str(src),
                    "n_episodes": buf.n_episodes, "n_frames": int(buf.n_steps),
                    "hz": 10.0, "rgb": {"out": [ow, oh], "crop": "center", "note": side},
                    "gripper_width_source": "camera magenta estimate, frozen calibration",
                    "evaluation_only_keys": ["eval_gripper_width_gt", "eval_ball_pos",
                                             "eval_width_detected", "eval_frame_age"],
                    "episodes": meta}, indent=2))
    click.echo(f"wrote {out_path}  ({out_path.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
