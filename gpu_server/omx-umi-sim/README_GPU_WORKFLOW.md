# OMX-UMI — GPU Server Workflow

GPU-side of the OMX project: turn the EC2 `processed/v1` dataset into a
UMI-compatible zarr, train the stock UMI CLIP-ViT + Diffusion U-Net policy on it,
and hand a 16×10 relative EE trajectory to the OMX execution layer.

```
Galaxy S10 -> FastAPI -> /srv/tiger/sessions -> CPU preprocessing
                                             -> /srv/processed/v1/<session>/READY
                                                        |
                                              rsync over SSH (GPU pulls)
                                                        v
   GPU mirror -> UMI zarr -> UmiDataset -> CLIP ViT-B/16
                                        -> Conditional 1D U-Net
                                        -> [B, 16, 10] -> 5-DoF OMX
```

Everything here is **additive**. No upstream file under `diffusion_policy/`,
`umi/` or `scripts_slam_pipeline/` is modified; `git diff` against upstream for
those paths is empty. The only files added next to upstream configs are
`diffusion_policy/config/task/umi_omx.yaml` and
`diffusion_policy/config/train_diffusion_unet_timm_omx_workspace.yaml`, both of
which document their deltas in their own headers.

`scripts_slam_pipeline/07_generate_replay_buffer.py` is deliberately **not**
used: it assumes `dataset_plan.pkl`, GoPro fisheye intrinsics and SLAM-derived
TCP poses, none of which exist in this project.

---

## 1. Environment

| | |
|---|---|
| conda env | `/home/j-j15a206/.conda/envs/umi` (py3.9.18, torch 2.1.0+cu121, timm 0.9.7, zarr 2.16.1) |
| GPU | **physical GPU 5 only** — Tesla V100-PCIE-32GB, `sm_70` |
| W&B | project `omx-umi`, via `accelerate`'s tracker (`Accelerator(log_with='wandb')`) |
| wandb | **>= 0.22.3 required** — see below |

> **wandb version.** Keys issued in the `wandb_v1_...` format are 86 characters,
> and every client before 0.22.3 hard-rejects them with
> `API key must be 40 characters long, yours was 86` — which reads like a bad key
> rather than an old client. The env shipped 0.15.8; it is now 0.22.3. Nothing
> else changed (`eval-type-backport` was pulled in, no version conflicts), and
> torch/timm/zarr/diffusers/accelerate are untouched. `python -m omx.cli env`
> reports the version and warns if it is too old.

GPU selection is by environment, never by config: `training.device` is
effectively ignored because the workspace runs under `accelerate`. Every
`omx.cli` command that touches the GPU sets `CUDA_VISIBLE_DEVICES=5`, after which
the process sees it as `cuda:0`.

`sm_70` has **no bf16 and no TF32**. The baseline runs in fp32. `fp16` is the
only available speedup and is opt-in per experiment (`mixed_precision="fp16"`),
off by default so the baseline number is not confounded by precision.

```bash
conda activate umi
python -m omx.cli env        # GPU, precision support, wandb version + login state
```

W&B credentials live in `~/.netrc` (mode 600), written once by `wandb login`.
Do not put the key in `~/.bashrc`: that file is world-readable by default.

---

> Latest real-data run: [`REPORT_STAGE_A_INTEGRATION.md`](REPORT_STAGE_A_INTEGRATION.md)
> — 5 sessions / 7 segments / 431 frames, Stage A integration only.
> Jetson runtime contract and reference bundle:
> [`README_JETSON_HANDOFF.md`](README_JETSON_HANDOFF.md).

## 2. Quick start

```bash
# 0. sanity-check the environment
python -m omx.cli env

# 1. pull READY sessions from the CPU server, then validate the mirror
./scripts/sync_processed_from_cpu.sh
python scripts/inspect_synced_processed.py

# 2. see what is registered and what is built
python -m omx.cli list

# 3. scan the processed tree without writing anything
python -m omx.cli build omx_pick_raw_center_v1 --dry-run

# 4. build the zarr
python -m omx.cli build omx_pick_raw_center_v1

# 5. prove it is trainable (this is the P0 gate)
python -m omx.cli inspect omx_pick_raw_center_v1

# 6. smoke -> debug -> full
python -m omx.cli train omx_pick_raw_center_v1 --profile smoke
python -m omx.cli train omx_pick_raw_center_v1 --profile debug
python -m omx.cli train omx_pick_raw_center_v1

# 7. offline inference + the robot handoff artefact
python -m omx.cli infer omx_pick_raw_center_v1
```

No real data yet? A synthetic fixture with the identical layout is included:

```bash
python scripts/make_synthetic_processed_v1.py -o data/omx/synthetic_processed_v1 -n 10
python -m omx.cli build   synth_center_crop
python -m omx.cli inspect synth_center_crop
python -m omx.cli train   synth_center_crop --profile smoke
```

Synthetic builds are stamped `dataset_synthetic=true` in the W&B run config and
`inspect` warns about them. They are a pipeline fixture, never a result.

---

## 3. CPU -> GPU sync

> Full write-up of this layer, including the CPU-side action items:
> [`README_CPU_GPU_SYNC.md`](README_CPU_GPU_SYNC.md). Who owns what across the
> CPU/GPU boundary, the `frames.csv` schema and the current work-item status:
> [`README_HANDOFF_CONTRACT.md`](README_HANDOFF_CONTRACT.md).

The GPU **pulls**; the CPU never pushes and never needs to know this server
exists. No new API, no S3, no queue — `rsync` over SSH, as the CPU-side design
already assumes.

Responsibility split:

| | |
|---|---|
| CPU | publishes a finished session and writes its `READY` marker last |
| GPU | pulls READY sessions whenever it wants to train |

### One-time setup

```bash
# 1. key for the CPU server
ssh-keygen -t ed25519 -f ~/.ssh/tiger_cpu_sync
cat ~/.ssh/tiger_cpu_sync.pub          # register on the EC2 account

# 2. config (already copied here; fill in CPU_HOST)
$EDITOR ~/umi-gpu/config/cpu_sync.env

# 3. verify
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> 'echo CPU_CONNECTION_OK'
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> \
    'find /srv/processed/v1 -maxdepth 2 -name READY -print'
```

If that last command prints nothing while sessions exist, the CPU side is not
writing the marker yet. It needs, after validation succeeds and last of all:

```python
(session_output_dir / "READY").touch()
```

### Pulling

```bash
./scripts/sync_processed_from_cpu.sh            # everything READY
./scripts/sync_processed_from_cpu.sh -n         # dry run
./scripts/sync_processed_from_cpu.sh -s <uuid>  # one session
```

```
CPU  /srv/processed/v1/<session>/READY
       |  rsync over SSH
       v
GPU  <mirror>/.incoming/<session>.partial     staging
       |  READY present?  at least one frames.csv?
       v
GPU  <mirror>/<session>/                      atomic mv + GPU_SYNCED stamp
```

* **READY-gated** — a session directory exists on the CPU while preprocessing is
  still writing into it, so directory existence alone is not the signal.
* **Staged** — nothing is written directly into the final path, so the converter
  can never read a half-copy.
* **Idempotent** — a second run prints `already synced, skipping`. Interrupted
  transfers resume (`rsync --partial`).
* **Never silently stale** — if the CPU re-publishes a session under the same id
  (which is exactly what happens after a preprocessing fix), the local READY
  mtime no longer matches the remote one and the session is reported as STALE
  rather than skipped. `--resync` replaces those, `--force-resync` replaces
  everything; the old copy moves to `.superseded/` rather than being deleted.
* **Non-destructive** — the script never deletes anything, replacements
  included. A final directory that exists without `READY` is reported and left
  alone for a human.
* **Serialised** — an flock stops two runs colliding; every run logs to
  `<mirror>/.logs/`.

A per-session failure is reported and the run continues with the others; the
script exits non-zero if anything failed. (The spec's sketch aborted on the
first error, which would let one bad session block every other.)

### Where the mirror lives

The handoff spec names `/data/dataset/v1`. **This box has no root access and no
`/data` mount**, and `/home` has ~11 TB free, so only the *root* moves:

```
/data/dataset/v1              spec
~/omx_data/processed/v1       here
^^^^^^^^^^^^               only this part differs
```

The `processed/v1` suffix is kept deliberately, so the mirror's path names what
it mirrors: `<cpu>:/srv/processed/v1` → `<gpu>:~/omx_data/processed/v1`. It also
keeps the CPU mirror clearly distinct from what the GPU *generates*, which lives
under `data/omx/`. One setting controls it everywhere:

```
GPU_PROCESSED_ROOT   in ~/umi-gpu/config/cpu_sync.env
```

`omx/config.py` reads that same file, so the sync script and the converter can
never disagree about where the data is. Resolution order is
`OMX_PROCESSED_ROOT` → `GPU_PROCESSED_ROOT` from `cpu_sync.env` → the default.

### Validating the mirror

```bash
python scripts/inspect_synced_processed.py -v
```

Per episode it checks the RGB/`frames.csv` count match, `rgb_path` resolution,
`frame_idx` continuity, timestamp monotonicity and measured fps, quaternion norm
and pose finiteness, and the presence of `quality.json` and the gripper column.
It ends with a status block:

```
DATASET STATUS
--------------
Transfer         : OK
RGB/Pose Align   : OK
T_camera_EE      : PLACEHOLDER
Gripper Width    : MISSING
Training Status  : INTEGRATION ONLY
```

`Training Status` only reads `READY` once `T_camera_EE` is a real calibration and
the gripper column carries marker-derived metres.

### The mirror is read-only

`frames.csv`, the RGB originals, `trajectory.npz`, `quality.json` and `READY` are
never modified on the GPU side. Everything this project generates goes under
`data/omx/` instead. The GPU also never touches the Android-facing
`POST /sessions` endpoint — that is the Android→CPU layer, a different tier.

---

## 4. Input contract — `processed/v1`

```
<OMX_PROCESSED_ROOT>/
└─ <session_uuid>/
   └─ <episode_uuid>/
      ├─ rgb_frames/frame_%06d.jpg   canonical RGB stream
      ├─ frames.csv                  canonical frame table (one row per RGB frame)
      ├─ trajectory.npz              T_world_camera, used for cross-checking only
      ├─ accelerometer.csv / gyroscope.csv / rotation_vector.csv   (ignored here)
      ├─ metadata.json
      └─ quality.json
```

`frames.csv` is the single source of truth. Expected columns:

| column | meaning |
|---|---|
| `frame_idx` | frame index |
| `timestamp_ns` | aligned timestamp (seconds also accepted) |
| `rgb_path` | path to the frame, relative to the episode directory |
| `camera_tx/ty/tz` | `T_world_camera` translation, metres |
| `camera_qx/qy/qz/qw` | `T_world_camera` rotation, **[x, y, z, w]** |
| `tracking_state`, `pose_valid` | ARCore validity |
| `gripper_width_m` | physical finger opening, **metres** |

The GPU server does **not** redo IMU sync or ARCore timestamp interpolation — the
CPU layer already aligned every stream. That is also why every `latency_steps` in
the task config evaluates to 0 (`dataset_frequeny: 0`).

If a column is ever renamed upstream, pin it in the collector config rather than
editing code:

```yaml
field_map: {timestamp_ns: t_ns, gripper: gripper_width_m}
```

Other layouts (`npz` / `hdf5` / video+sidecar / frames+csv per episode) are
supported by `omx/data/readers.py` for one-off imports.

---

## 5. What the converter does

`scripts/convert_processed_to_umi_zarr.py`, in the order the contract requires:

1. **discover** episodes — a natural sort of `<session>__<episode>`, so episode
   ordering is identical for every dataset variant;
2. **validity filter** — `pose_valid`, `tracking_state`, finiteness, quaternion
   norm, and blank/unparseable csv cells
   (full rules: [`README_GPU_VALIDATION.md`](README_GPU_VALIDATION.md));
3. **gate, not repair** — `validity.invalid_policy` defaults to `error`. Tracking
   repair (trimming, short-gap interpolation, long-gap splitting, rejecting
   unusable segments) belongs to CPU preprocessing, which runs before `READY` is
   written, so anything still invalid here is a contract violation to report.
   Every episode is checked before the build fails, so one round trip surfaces
   every problem. `trim` | `split` | `keep` exist for inspecting a known-bad
   export and must not be used to produce a training dataset;
4. **decimate** — 30 Hz → 10 Hz with **one shared index for every stream**
   (`rgb`, `pose`, `gripper` never decimate independently);
5. **pose chain**

   ```
   T_world_ee(t)   = T_world_camera(t) @ T_camera_ee
   T_episode_ee(t) = inv(T_world_ee(0)) @ T_world_ee(t)
   ```

   The episode-relative step matters because ARCore's world origin is
   session-local. It is **not** a frame-to-frame delta; `UmiDataset` still builds
   its own relative representation from the observation's last pose;
6. **rotation** — quaternion → matrix → rotation vector (`axis-angle`). The
   converter never writes rotation-6D; `UmiDataset` does that conversion;
7. **RGB** — the only thing that differs between variants (see §6);
8. **write** the zarr plus a full provenance record.

Output keys:

| key | shape | dtype | notes |
|---|---|---|---|
| `camera0_rgb` | `[N, 224, 224, 3]` | uint8 | JpegXl, one chunk per frame |
| `robot0_eef_pos` | `[N, 3]` | float32 | metres |
| `robot0_eef_rot_axis_angle` | `[N, 3]` | float32 | rotation vector |
| `robot0_gripper_width` | `[N, 1]` | float32 | **metres, physical opening** |
| `robot0_demo_start_pose` | `[N, 6]` | float32 | episode start pose, repeated |
| `robot0_demo_end_pose` | `[N, 6]` | float32 | episode end pose, repeated |

No `action` key is written on purpose. `SequenceSampler` builds the raw 7-D action
(`pos 3 + rotvec 3 + gripper 1`) when `action` is absent, and `UmiDataset` turns
it into the 10-D model action. The converter's job is to store the *physical*
representation correctly.

---

## 6. The 10 Hz invariant

The contract decimates 30 Hz → 10 Hz **in the converter**, so the sampler must
not stride again:

```
converter_stride  x  obs_down_sample_steps  ==  source_fps / policy_hz
        3         x           1             ==        30 / 10
```

This is enforced, not documented-and-hoped-for:

* `TimingConfig` derives both numbers from `source_fps`, `policy_hz` and
  `downsample_stage`, so they cannot be set inconsistently;
* the converter records the required `obs_down_sample_steps` in the zarr
  metadata;
* `omx.cli train` reads it back and forces the matching override;
* `inspect_umi_zarr.py` fails if the task config disagrees.

To store 30 Hz and let the sampler stride instead, set
`timing.downsample_stage: dataset` — the invariant then resolves to `1 × 3` and
everything downstream follows automatically. To compare 15/30 Hz later, change
`policy_hz` and rebuild.

---

## 7. RGB preprocessing modes

Only the image changes between variants. Pose, gripper, episode order, episode
boundaries and the train/val split are byte-identical — that is what makes the
A/B comparison fair, and `omx.cli ab A B` verifies it against the built zarrs.

| mode | what it does | HFOV kept (63.5° source) |
|---|---|---|
| `center_crop` | 16:9 → central square → 224×224 | ~38.4° — **baseline v1** |
| `letterbox` | full width → ~224×126 → pad top/bottom | 63.5°, 56% of rows are content |
| `matched_center_crop` | undistort + reproject onto the robot wrist camera's virtual pinhole | matches the robot camera |
| `stretch` | plain resize, aspect destroyed | control condition |

`matched_center_crop` needs `camera.collector_intrinsics` and either
`camera.robot_intrinsics` or `camera.matched_fov_deg`. `fx/fy/cx/cy` is preferred;
`hfov_deg` alone is enough to build the virtual pinhole before an intrinsic
calibration exists.

> **Watch the compounding.** The training config also applies
> `RandomCrop(ratio=0.95)` and `ColorJitter`. `inspect` writes
> `rgb_augmentation_preview.png` showing the worst-case visible FOV after
> preprocessing *and* augmentation. Check it before trusting a FOV number.

---

## 8. Configuration — where to change what

| file | change this when |
|---|---|
| `configs/collector/default.yaml       calibration / conventions / timing
config/cpu_sync.env.example          sync settings template (real file gitignored)` | calibration, conventions, timing, validity, camera intrinsics |
| `omx/config.py` | adding/altering an experiment, GPU id, paths, W&B project, training profiles |
| `diffusion_policy/config/task/umi_omx.yaml` | task shape_meta / horizons |
| `diffusion_policy/config/train_diffusion_unet_timm_omx_workspace.yaml` | policy, optimizer, schedule |

Adding an experiment is one block in `omx/config.py`:

```python
register(Experiment(
    name="omx_pick_letterbox_v1",
    dataset=_variant("omx_pick_letterbox_v1", "letterbox"),
    tags=("step2", "fov"),
))
```

`build`, `inspect`, `train` and `infer` then all take that one name.

Training profiles (`--profile`): `smoke` (2 steps, batch 4, W&B off) →
`debug` (`training.debug=True`, W&B on, checkpoints) → `full` (120 epochs).

---

## 9. Stage A → Stage B

Stage A is running **now**, with placeholders:

```yaml
camera_to_ee: {status: placeholder, calibration_version: none,
               translation: [0,0,0], quaternion: [0,0,0,1]}
gripper:      {status: placeholder}
```

The exported EE trajectory is therefore *not* a calibrated physical EE
trajectory. That is fine for integration and not reportable as a baseline. Both
the converter, `inspect` and `omx.cli train` say so out loud, and the status is
recorded in the zarr metadata and the W&B run config.

Stage B needs no re-collection — only a re-export:

```yaml
camera_to_ee:
  status: calibrated
  calibration_version: "v1-2026-xx-xx"
  translation: [...]
  quaternion: [...]            # [qx, qy, qz, qw]
gripper:
  status: calibrated
  mode: width_m
```

```bash
python -m omx.cli build omx_pick_raw_center_v1 --overwrite
```

The pose chain (`T_world_camera` from ARCore) is preserved in the raw data, so a
new `T_camera_EE` simply produces a new EE trajectory.

---

## 10. Robot handoff spec (P3)

`scripts/offline_infer_omx.py` writes `sample_prediction.{npy,npz,json}` and the
JSON carries this spec machine-readably.

**Observation the policy expects** (batch dim first, obs horizon 2 at 10 Hz):

```python
obs = {
  "camera0_rgb":                         [B, 2, 3, 224, 224],  # float32 in [0,1], RGB
  "robot0_eef_pos":                      [B, 2, 3],            # metres
  "robot0_eef_rot_axis_angle":           [B, 2, 6],            # rotation 6D
  "robot0_gripper_width":                [B, 2, 1],            # metres
  "robot0_eef_rot_axis_angle_wrt_start": [B, 2, 6],            # rotation 6D
}
```

**Output**: `[B, 16, 10]`, already un-normalized, in physical units.

```
action[t, 0:3]   relative EE position      metres
action[t, 3:9]   relative EE rotation      6D (first two rows of R)
action[t, 9]     gripper width             metres, physical finger opening
```

**Semantics — state this explicitly.** The 16 entries are 16 future EE targets,
each expressed **relative to the EE pose at the inference instant**. They are
**not** frame-to-frame deltas:

```
T_world_target[k] = T_world_now @ T_rel[k]        # correct
T_world_target[k] = T_world_target[k-1] @ delta   # WRONG
```

Decode recipe (reuse the UMI utilities, do not reimplement the maths):

```python
from umi.common.pose_util import pose10d_to_mat, pose_to_mat, mat_to_pose
from diffusion_policy.common.pose_repr_util import convert_pose_mat_rep

T_rel   = pose10d_to_mat(action[b, :, :9])           # [16, 4, 4]
T_now   = pose_to_mat(current_ee_pose6)              # pos + rotvec
T_world = convert_pose_mat_rep(T_rel, base_pose_mat=T_now,
                               pose_rep="relative", backward=True)
targets = mat_to_pose(T_world)                       # [16, 6] pos + rotvec
gripper = action[b, :, 9]                            # metres
```

`offline_infer_omx.py` verifies this recipe against the recorded trajectory on
every run (`decoder self-check`, agreement ~1e-8 m / 1e-8 rad), independently of
how well the model is trained.

> The full contract as consumed by the Jetson runtime — including the base-frame
> position convention, the rot6d row layout, the action time offset, and three
> behaviours that are only visible in the code (no mean/std normalisation, the
> policy randomising its own input at inference, and the lossy JpegXl training
> storage) — is in [`README_JETSON_HANDOFF.md`](README_JETSON_HANDOFF.md).

**The policy always returns all 16 steps.** `n_action_steps: 8` exists in the
config but is *not* applied on the `DiffusionUnetTimmPolicy.predict_action()`
path. How many steps to execute before re-observing is the robot layer's
decision (receding horizon).

Conventions the robot side must match: metres; the collector's axis convention
(ARCore session-local, Y-up — **no** Z-up remap is applied); gripper as physical
width in metres; observation horizon 2 at 10 Hz; and the same RGB preprocessing
as the dataset the checkpoint was trained on (recorded in
`sample_prediction.json` → `rgb_preprocess`).

---

## 11. Gotchas found in this repo

* **Validation loss is not computed.** The validation loop in
  `diffusion_policy/workspace/train_diffusion_unet_image_workspace.py` is
  commented out upstream (~lines 285–300), so `val_loss` is never logged. What
  you get is `val_action_mse_error` from the sampling block. Final model
  selection is real OMX success rate anyway.
* **Short episodes vanish silently.** With `action_padding: False`, an episode
  shorter than `(action_horizon-1) * obs_down_sample_steps + 1` frames
  contributes zero samples and is dropped without a warning. At 10 Hz that is
  **16 frames (1.6 s)**. Both the converter and `inspect` report this explicitly.
* **A blank csv cell is never a number.** `frames.csv` cells that are empty or
  unparseable become `NaN`, never `0.0` — reading `camera_tx=""` as zero would
  teleport the end effector to the world origin and put that trajectory straight
  into the training set. NaN propagates into the validity mask and stops the
  build. `scripts/make_synthetic_processed_v1.py --blank-pose-rows 40:55`
  reproduces the case.
* **`feature_aggregation` is ignored for ViT.** `attention_pool_2d` in the config
  is overridden — `TimmObsEncoder` uses the CLS token and logs a warning. The
  baseline is CLS-only, as intended.
* **The `gripper_width < 0.08` heuristic.** `SequenceSampler` uses it for
  repeat-frame augmentation. Our widths are real metres so the *unit* is right,
  but 0.08 is not our grasp threshold (our gripper is ~0.025–0.105 m). It is
  inert while `repeat_frame_prob: 0.0`. Measure the distribution (`inspect`
  prints it) before ever raising that probability.
* **Checkpoints are ~1.3 GB each** and `checkpoint.topk.k` is 20. A 120-epoch run
  with `checkpoint_every: 10` writes ~15 GB. Budget disk accordingly.
* **`get_normalizer` hardcodes `num_workers=32`** in its DataLoader, independent
  of `cfg.dataloader`. Harmless at this dataset size, surprising on a busy box.

---

## 12. Files

```
omx/
├─ config.py                 experiment registry, GPU id, paths, training profiles
├─ collector_config.py       calibration/conventions/timing, validation + provenance
├─ cli.py                    list / build / inspect / train / infer / ab / env
└─ data/
   ├─ contract.py            input contract + field aliases + validation
   ├─ readers.py             generic readers (npz / hdf5 / video+sidecar / frames+csv)
   ├─ processed_v1.py        the EC2 layout reader + trajectory.npz cross-check
   ├─ pose_convert.py        rotation formats, axis remap, T_camera_to_ee, units
   ├─ rgb_preprocess.py      center_crop / letterbox / matched_center_crop / stretch
   └─ build.py               validity filter, segmentation, decimation, pose chain

configs/collector/default.yaml       calibration / conventions / timing
config/cpu_sync.env.example          sync settings template (real file gitignored)

scripts/
├─ sync_processed_from_cpu.sh          CPU -> GPU pull, READY-gated + atomic
├─ inspect_synced_processed.py         mirror validation + DATASET STATUS
├─ convert_processed_to_umi_zarr.py    P0 adapter
├─ inspect_umi_zarr.py                 P0 gate + plots
├─ offline_infer_omx.py                P2/P3 inference + handoff artefact
└─ make_synthetic_processed_v1.py      integration fixture

diffusion_policy/config/
├─ task/umi_omx.yaml
└─ train_diffusion_unet_timm_omx_workspace.yaml
```

Artefacts land under `data/omx/` (gitignored): `zarr/`, `inspect/`, `train/`,
`infer/`, `synthetic_processed_v1/`.
