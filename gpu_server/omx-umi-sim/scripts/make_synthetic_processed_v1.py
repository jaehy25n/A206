"""Generate a synthetic processed_v1 tree, byte-compatible with the EC2 layout.

Purpose: close the P0 path (converter -> zarr -> UmiDataset -> action [16,10] ->
model forward) *before* the real dataset lands, and keep a regression fixture
afterwards.  It is NOT training data -- every build from it is stamped
``synthetic: true`` in the dataset metadata.

The scene is rendered through a real pinhole projection of the generated camera
pose, so the images are geometrically consistent with frames.csv.  That means a
coordinate-convention bug shows up as a visibly wrong image rather than as a
silently plausible one.

    python scripts/make_synthetic_processed_v1.py -o /tmp/omx_synth -n 8
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

import csv
import json
import math
import pathlib
import uuid

import click
import cv2
import numpy as np
import scipy.spatial.transform as st
from tqdm import tqdm

# ARCore-like world: X right, Y up (against gravity), Z toward the user.
WORLD_UP = np.array([0.0, 1.0, 0.0])
TABLE_Y = 0.0
BLOCK_SIZE = 0.035
# Camera sits this far above the finger tips, so a grasped block keeps a constant
# apparent size instead of filling the frame as the arm rises.
TIP_OFFSET = 0.12
TARGET_SIZE = 0.09


def look_at_quat(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Camera pose quaternion [x,y,z,w] for an OpenGL/ARCore camera (-Z forward)."""
    fwd = target - eye
    n = np.linalg.norm(fwd)
    fwd = fwd / n if n > 1e-9 else np.array([0.0, -1.0, 0.0])
    z_axis = -fwd
    right = np.cross(WORLD_UP, z_axis)
    if np.linalg.norm(right) < 1e-6:
        right = np.cross(np.array([0.0, 0.0, 1.0]), z_axis)
    right /= np.linalg.norm(right)
    up = np.cross(z_axis, right)
    R = np.stack([right, up, z_axis], axis=1)
    return st.Rotation.from_matrix(R).as_quat()


def project(points_w: np.ndarray, cam_pos: np.ndarray, cam_quat: np.ndarray,
            K: np.ndarray):
    """World points -> pixel coords for an OpenGL-convention camera."""
    R = st.Rotation.from_quat(cam_quat).as_matrix()
    p_c = (points_w - cam_pos) @ R                       # R^T @ (p - t)
    z = -p_c[:, 2]
    visible = z > 1e-3
    z_safe = np.where(visible, z, 1.0)
    u = K[0, 0] * (p_c[:, 0] / z_safe) + K[0, 2]
    v = -K[1, 1] * (p_c[:, 1] / z_safe) + K[1, 2]
    return np.stack([u, v], axis=1), visible


def quad(cx: float, cz: float, size: float, y: float) -> np.ndarray:
    h = size / 2.0
    return np.array([[cx - h, y, cz - h], [cx + h, y, cz - h],
                     [cx + h, y, cz + h], [cx - h, y, cz + h]])


def render(cam_pos, cam_quat, K, res, block_xz, block_y, target_xz, grip_w,
           grip_range):
    w, h = res
    img = np.full((h, w, 3), (118, 122, 128), dtype=np.uint8)   # table

    # subtle wood-grain-ish texture so ColorJitter/RandomCrop have something to act on
    yy = np.linspace(0, 6 * math.pi, h).reshape(h, 1, 1)
    img = np.clip(img.astype(np.int16) + (8 * np.sin(yy)).astype(np.int16),
                  0, 255).astype(np.uint8)

    for pts_w, color in (
        (quad(target_xz[0], target_xz[1], TARGET_SIZE, TABLE_Y), (60, 170, 90)),
        (quad(block_xz[0], block_xz[1], BLOCK_SIZE, block_y), (40, 70, 220)),
    ):
        px, vis = project(pts_w, cam_pos, cam_quat, K)
        if vis.all():
            cv2.fillConvexPoly(img, px.astype(np.int32), color, lineType=cv2.LINE_AA)

    # gripper fingers in the near field, opening with the real gripper width
    lo, hi = grip_range
    frac = float(np.clip((grip_w - lo) / max(hi - lo, 1e-6), 0.0, 1.0))
    half = int(0.06 * w + frac * 0.16 * w)
    fw, ftop = max(3, w // 42), int(h * 0.80)
    for sign in (-1, 1):
        x = w // 2 + sign * half
        cv2.rectangle(img, (x - fw, ftop), (x + fw, h), (45, 45, 50), -1)
    return img


@click.command()
@click.option("-o", "--output", required=True, help="Root of the synthetic tree.")
@click.option("-n", "--num-episodes", type=int, default=8)
@click.option("--sessions", type=int, default=2)
@click.option("--fps", type=float, default=30.0)
@click.option("--duration", type=float, default=6.0, help="Seconds per episode.")
@click.option("--res", default="640,360", help="WIDTH,HEIGHT (16:9).")
@click.option("--hfov-deg", type=float, default=63.5)
@click.option("--closed-width", type=float, default=0.025)
@click.option("--open-width", type=float, default=0.105)
@click.option("--bad-tracking-frac", type=float, default=0.0,
              help="Fraction of frames marked pose_valid=0, to exercise the "
                   "validity filter and episode splitting.")
@click.option("--interpolate-rows", default=None,
              help="START:END row range to emit as CPU-repaired: tracking_state "
                   "kept as PAUSED, pose_valid_original=0, pose_interpolated=1, "
                   "pose_valid=1 and a numerically valid pose. Exercises the "
                   "GPU-1 rule that such rows must PASS.")
@click.option("--blank-pose-rows", default=None,
              help="START:END row range to emit with BLANK camera pose cells and "
                   "pose_valid=0, e.g. '40:55'. Reproduces the CPU contract "
                   "violation that used to crash the inspector with float(''). "
                   "Applied to the FIRST episode of each session, so a mixed "
                   "good/bad tree is produced.")
@click.option("--jpeg-quality", type=int, default=92)
@click.option("--seed", type=int, default=0)
def main(output, num_episodes, sessions, fps, duration, res, hfov_deg,
         closed_width, open_width, bad_tracking_frac, interpolate_rows,
         blank_pose_rows, jpeg_quality, seed):
    interp_range = None
    if interpolate_rows:
        a, b = interpolate_rows.split(":")
        interp_range = (int(a), int(b))
    blank_range = None
    if blank_pose_rows:
        a, b = blank_pose_rows.split(":")
        blank_range = (int(a), int(b))
    rng = np.random.default_rng(seed)
    w, h = (int(x) for x in res.split(","))
    f = (w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    K = np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]])

    root = pathlib.Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    n = int(round(duration * fps))
    def _uuid() -> str:
        return str(uuid.UUID(bytes=bytes(rng.integers(0, 256, size=16, dtype=np.uint8))))

    session_ids = [_uuid() for _ in range(sessions)]

    # phase boundaries of a pick-and-place, as fractions of the episode
    P = np.array([0.00, 0.22, 0.34, 0.42, 0.55, 0.78, 0.86, 1.00])

    click.echo(f"{num_episodes} episodes x {n} frames @ {fps} Hz -> {root}")
    for ep in tqdm(range(num_episodes), desc="episodes"):
        sess = session_ids[ep % sessions]
        ep_id = _uuid()
        ep_dir = root / sess / ep_id
        (ep_dir / "rgb_frames").mkdir(parents=True, exist_ok=True)

        # object XY varies; everything else is fixed (handoff doc section 2)
        bx, bz = float(rng.uniform(-0.09, 0.09)), float(rng.uniform(-0.07, 0.07))
        tx, tz = 0.16, 0.02
        # ARCore world origin is session-local: give each episode its own offset
        origin = rng.uniform(-0.6, 0.6, size=3) * np.array([1.0, 0.15, 1.0])

        rows, cam_positions, cam_quats, T_world_camera = [], [], [], []
        for i in range(n):
            u = i / (n - 1)
            hover, low = 0.34, TIP_OFFSET + 0.04

            if u < P[1]:            # approach above the block
                s = u / P[1]
                pos = np.array([_lerp(0.0, bx, _ease(s)), hover, _lerp(0.20, bz, _ease(s))])
                g = open_width
            elif u < P[2]:          # descend
                s = (u - P[1]) / (P[2] - P[1])
                pos = np.array([bx, _lerp(hover, low, _ease(s)), bz])
                g = open_width
            elif u < P[3]:          # close
                s = (u - P[2]) / (P[3] - P[2])
                pos = np.array([bx, low, bz])
                g = _lerp(open_width, closed_width, _ease(s))
            elif u < P[4]:          # lift
                s = (u - P[3]) / (P[4] - P[3])
                pos = np.array([bx, _lerp(low, hover, _ease(s)), bz])
                g = closed_width
            elif u < P[5]:          # transport
                s = (u - P[4]) / (P[5] - P[4])
                pos = np.array([_lerp(bx, tx, _ease(s)), hover, _lerp(bz, tz, _ease(s))])
                g = closed_width
            elif u < P[6]:          # place + open
                s = (u - P[5]) / (P[6] - P[5])
                pos = np.array([tx, _lerp(hover, low, _ease(s)), tz])
                g = _lerp(closed_width, open_width, _ease(s))
            else:                   # retreat
                s = (u - P[6]) / (1.0 - P[6])
                pos = np.array([tx, _lerp(low, hover, _ease(s)), tz])
                g = open_width

            grasped = P[3] <= u < P[6]
            blk = (tx, tz) if u >= P[6] else ((pos[0], pos[2]) if grasped else (bx, bz))
            blk_y = (pos[1] - TIP_OFFSET + BLOCK_SIZE / 2) if grasped else BLOCK_SIZE / 2

            look = np.array([pos[0], TABLE_Y, pos[2] - 0.02])
            quat = look_at_quat(pos, look)
            cam_w = pos + origin

            img = render(cam_w - origin, quat, K, (w, h), blk, blk_y, (tx, tz),
                         g, (closed_width, open_width))
            rel = f"rgb_frames/frame_{i:06d}.jpg"
            cv2.imwrite(str(ep_dir / rel), cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])

            valid = 1
            state = "TRACKING"
            if bad_tracking_frac > 0 and rng.random() < bad_tracking_frac:
                valid, state = 0, "PAUSED"

            rows.append({
                "frame_idx": i,
                "timestamp_ns": int(round(i / fps * 1e9)) + 1_700_000_000_000_000_000,
                "rgb_path": rel,
                "camera_tx": cam_w[0], "camera_ty": cam_w[1], "camera_tz": cam_w[2],
                "camera_qx": quat[0], "camera_qy": quat[1],
                "camera_qz": quat[2], "camera_qw": quat[3],
                "tracking_state": state, "pose_valid": valid,
                # CPU repair bookkeeping; a direct measurement by default
                "pose_valid_original": valid, "pose_interpolated": 0,
                "gripper_width_m": g,
            })
            cam_positions.append(cam_w)
            cam_quats.append(quat)
            T = np.eye(4)
            T[:3, :3] = st.Rotation.from_quat(quat).as_matrix()
            T[:3, 3] = cam_w
            T_world_camera.append(T)

        if interp_range is not None and ep < sessions:
            lo, hi = interp_range
            for r in rows[lo:hi]:
                # the pose stays numerically valid: the CPU filled it in.
                # tracking_state deliberately keeps the ORIGINAL value.
                r["tracking_state"] = "PAUSED"
                r["pose_valid_original"] = 0
                r["pose_interpolated"] = 1
                r["pose_valid"] = 1
            click.echo(f"  [{ep_id[:8]}] marked rows {lo}..{hi - 1} as "
                       f"CPU-interpolated (PAUSED + pose_interpolated=1)")

        if blank_range is not None and ep < sessions:
            lo, hi = blank_range
            for r in rows[lo:hi]:
                r["pose_valid"] = 0
                r["tracking_state"] = "PAUSED"
                for k in ("camera_tx", "camera_ty", "camera_tz",
                          "camera_qx", "camera_qy", "camera_qz", "camera_qw"):
                    r[k] = ""           # blank, not 0 -- the real failure mode
            click.echo(f"  [{ep_id[:8]}] blanked pose on rows {lo}..{hi - 1}")

        with open(ep_dir / "frames.csv", "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)

        np.savez(ep_dir / "trajectory.npz",
                 T_world_camera=np.asarray(T_world_camera, dtype=np.float64),
                 timestamp_ns=np.array([r["timestamp_ns"] for r in rows], dtype=np.int64),
                 camera_position=np.asarray(cam_positions),
                 camera_quaternion_xyzw=np.asarray(cam_quats))

        contract = {
            "version": "omx_processed_v1_posefix_1",
            "source_hz_reference": float(fps),
            "policy_hz_reference": float(fps) / 3.0,
            "action_horizon_reference": 16,
            "min_publish_segment_frames": 48,
        }
        with open(ep_dir / "metadata.json", "w") as fh:
            json.dump({"synthetic": True, "handoff_contract": contract,
                       "session_id": sess, "episode_id": ep_id,
                       "fps": fps, "n_frames": n,
                       "image_width": w, "image_height": h, "hfov_deg": hfov_deg,
                       "task": "single_object_pick_and_place",
                       "object_xz": [bx, bz], "target_xz": [tx, tz],
                       "gripper_range_m": [closed_width, open_width],
                       "world_frame": "arcore_session_local_y_up"}, fh, indent=2)
        with open(ep_dir / "quality.json", "w") as fh:
            json.dump({"synthetic": True,
                       "n_invalid_frames": int(sum(1 for r in rows if not r["pose_valid"])),
                       "tracking_ok_ratio": float(np.mean([r["pose_valid"] for r in rows]))},
                      fh, indent=2)

        # IMU sidecars exist in the real layout; the GPU server ignores them
        for name in ("accelerometer.csv", "gyroscope.csv", "rotation_vector.csv"):
            with open(ep_dir / name, "w") as fh:
                fh.write("timestamp_ns,x,y,z\n")

    # The CPU side writes READY last, after validation; the converter only
    # picks up sessions that carry it, so the fixture must too.
    for sess in session_ids:
        with open(root / sess / "session_metadata.json", "w") as fh:
            json.dump({"synthetic": True, "session_id": sess,
                       "handoff_contract": {
                           "version": "omx_processed_v1_posefix_1",
                           "source_hz_reference": float(fps),
                           "policy_hz_reference": float(fps) / 3.0,
                           "action_horizon_reference": 16,
                           "min_publish_segment_frames": 48}}, fh, indent=2)
        (root / sess / "READY").touch()

    click.secho(f"done -> {root}  ({sessions} session(s), READY markers written)",
                fg="green")
    click.echo(f"next: python scripts/convert_processed_to_umi_zarr.py "
               f"-i {root} -o data/omx/zarr/synth.zarr.zip --rgb-mode center_crop")


def _lerp(a, b, t):
    return a + (b - a) * t


def _ease(t):
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3.0 - 2.0 * t)


if __name__ == "__main__":
    main()
