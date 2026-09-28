"""MuJoCo episodes -> a UMI ReplayBuffer zarr.

Deliberately writes the SAME key set the real-data converter writes
(scripts/convert_processed_to_umi_zarr.py), because that set is what
UmiDataset and SequenceSampler actually read:

    camera0_rgb                 (N, H, W, 3) uint8, JpegXl
    robot0_eef_pos              (N, 3)
    robot0_eef_rot_axis_angle   (N, 3)   rotation vector
    robot0_gripper_width        (N, 1)   metres
    robot0_demo_start_pose      (N, 6)   episode's first pose, repeated
    robot0_demo_end_pose        (N, 6)   episode's last pose, repeated

The two demo_*_pose keys look redundant but are not: UmiDataset reads
demo_start_pose to build robot0_eef_rot_axis_angle_wrt_start, which is an
observation the policy consumes.

    python sim_umi/scripts/sim_to_umi_zarr.py
    python sim_umi/scripts/sim_to_umi_zarr.py --stride 3 --out-res 224,224
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pathlib

import click
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from diffusion_policy.codecs.imagecodecs_numcodecs import JpegXl, register_codecs
from diffusion_policy.common.replay_buffer import ReplayBuffer

register_codecs()

SIM_ROOT = pathlib.Path(ROOT) / "sim_umi"


def quat_wxyz_to_rotvec(q: np.ndarray) -> np.ndarray:
    """MuJoCo stores wxyz; scipy wants xyzw."""
    q = np.asarray(q, dtype=np.float64)
    return Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_rotvec()


def center_crop_resize(img: np.ndarray, out_wh) -> np.ndarray:
    """The runtime RGB contract: central square, INTER_AREA, no padding."""
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    crop = img[y0:y0 + side, x0:x0 + side]
    return cv2.resize(crop, tuple(out_wh), interpolation=cv2.INTER_AREA)


@click.command()
@click.option("-i", "--input-dir", default=str(SIM_ROOT / "data"))
@click.option("-o", "--output", default=str(SIM_ROOT / "data" / "sim_umi.zarr.zip"))
@click.option("--stride", default=3, type=int,
              help="Source decimation. 30 Hz sim / 3 = the 10 Hz policy rate.")
@click.option("--out-res", default="224,224", help="WIDTH,HEIGHT")
@click.option("-cl", "--compression-level", default=99, type=int)
@click.option("--overwrite", is_flag=True)
def main(input_dir, output, stride, out_res, compression_level, overwrite):
    ow, oh = (int(x) for x in out_res.split(","))
    out_path = pathlib.Path(output)
    if out_path.exists() and not overwrite:
        raise click.ClickException(f"{out_path} exists; pass --overwrite")

    eps = sorted(pathlib.Path(input_dir).glob("episode_*.npz"))
    if not eps:
        raise click.ClickException(f"no episode_*.npz under {input_dir}")
    click.echo(f"episodes: {len(eps)}")

    # Build in memory, then save once. A zarr ZipStore is not erasable, so
    # add_episode's resize/rename fails on the second episode -- it happens to
    # work with exactly one, which is how this got through the first time.
    buf = ReplayBuffer.create_empty_numpy()
    rgb_chunks = []
    for p in eps:
        d = np.load(p)
        n_src = len(d["timestamps"])
        idx = np.arange(0, n_src, stride)
        pos = d["tcp_pos"][idx].astype(np.float32)
        rot = quat_wxyz_to_rotvec(d["tcp_quat_wxyz"][idx]).astype(np.float32)
        # robot0_gripper_width is the VISION estimate, matching how the real
        # collector gets it. MuJoCo's value rides along for validation only.
        grip = d["gripper_width"][idx].astype(np.float32).reshape(-1, 1)
        grip_gt = (d["gripper_width_gt"][idx].astype(np.float32).reshape(-1, 1)
                   if "gripper_width_gt" in d.files else grip)
        pose6 = np.concatenate([pos, rot], axis=-1)
        n = len(idx)
        buf.add_episode({
            "robot0_eef_pos": pos,
            "robot0_eef_rot_axis_angle": rot,
            "robot0_gripper_width": grip,
            "robot0_demo_start_pose": np.tile(pose6[0], (n, 1)),
            "robot0_demo_end_pose": np.tile(pose6[-1], (n, 1)),
            "sim_gripper_width_gt": grip_gt,
            "sim_gripper_width_error": (grip - grip_gt).astype(np.float32),
        })
        rgb_chunks.append(np.stack([center_crop_resize(f, (ow, oh))
                                    for f in d["rgb"][idx]]))
        if len(rgb_chunks) % 10 == 0:
            click.echo(f"  {len(rgb_chunks)}/{len(eps)} episodes")

    rgb = np.concatenate(rgb_chunks)
    total = len(rgb)
    if total != buf.n_steps:
        raise click.ClickException(f"rgb {total} != lowdim {buf.n_steps}")
    buf.data["camera0_rgb"] = rgb

    dt = float(np.diff(np.load(eps[0])["timestamps"]).mean()) * stride
    click.echo(f"\nepisodes {buf.n_episodes}  frames {total}  "
               f"dt {dt:.4f}s ({1/dt:.2f} Hz)")
    click.echo(f"episode_ends: {list(buf.episode_ends[:8])}"
               f"{' ...' if buf.n_episodes > 8 else ''}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    import zarr
    with zarr.ZipStore(str(out_path), mode="w") as store:
        buf.save_to_store(
            store,
            chunks={"camera0_rgb": (1, oh, ow, 3)},
            compressors={"camera0_rgb": JpegXl(level=compression_level,
                                               numthreads=1)})

    click.echo(f"\nwrote {out_path}  ({out_path.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
