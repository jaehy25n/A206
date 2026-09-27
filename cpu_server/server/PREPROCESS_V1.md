# CPU preprocessing v1

`preprocess.py` reads an uploaded raw session from `/srv/sessions/<session_id>` and writes an episode-scoped dataset under `/srv/processed/v1/<session_id>`. It needs Python 3.10+ plus the system `ffmpeg` and `ffprobe`; it does not need NumPy, pandas, or PyArrow.

```bash
cd /home/ubuntu/server
./.venv/bin/python preprocess.py
```

Use `--session-id <uuid>` to process one session. Existing output is left untouched unless `--force` is passed; forced replacement is staged and then swapped in. The top-level `validation_report.json` and `.csv` summarize published segments, rejected and failed episodes, repair counters, quality, clipped edges, and alignment diagnostics.

## Output contract

A published segment is a continuous trajectory the GPU can consume without repairing anything: every row has an RGB frame, a timestamp, and a usable camera pose. Rows whose pose is unusable are never published. An episode that yields no such segment is rejected and no `READY` is written for a session with no usable segment.

Directory names carry that contract. Only `episode_*` folders are publishable; a rejected episode lands in `rejected_episode_<id>/` and an episode that raised lands in `failed_episode_<id>/`, both holding just `quality.json` and `metadata.json` — no RGB is decoded or copied for either.

An episode that is split produces `episode_<id>_seg000`, `episode_<id>_seg001`, ... An episode that survives intact keeps the plain `episode_<id>` name. Every segment records its lineage (`source_episode_id`, `segment_index`, `segment_count`, `original_frame_range`, `original_frame_count`, `final_frame_count`, and the trim/interpolate/split/dropped-gap counters) in `metadata.json` and `quality.json`.

## Processed episode files

Each published segment contains:

- `frames.csv`: canonical frame table. `frame_idx` is segment-local; `rgb_frame_index` is the zero-based decoded frame index in the original session MP4, so it still identifies the source frame after trimming and splitting. The raw `frame_number` column is ignored. Rows have a segment-local JPEG at `rgb_path`. `pose_valid` is true on every published row; `pose_valid_original` and `pose_interpolated` say whether that pose came from ARCore or from repair, and `tracking_state` keeps the state ARCore reported.
- `rgb_frames/frame_*.jpg`: the selected decoded RGB frames, in the same order as `frames.csv`.
- `trajectory.npz`: NumPy-loadable arrays for camera/world/EE/segment-relative transforms, the `pose_valid`/`pose_valid_original`/`pose_interpolated` masks, and adjacent valid transform-delta actions. Transform-matrix actions are an interface artifact, not a final UMI action contract.
- `quality.json`: before/after repair counts (`original_frame_count`, `valid_pose_count_before_repair`, `invalid_pose_count_before_repair`, `trimmed_start_frames`, `trimmed_end_frames`, `interpolated_pose_frames`, `split_count`, `output_segment_count`, `final_frame_count`, `final_valid_pose_count`), `training_usable`, `reject_reason`, the provisional quality label, and every configured threshold. The before-repair and trim/split counters describe the whole source episode; `interpolated_pose_frames`, `final_frame_count` and `final_valid_pose_count` describe this segment.
- `metadata.json`: episode bounds, effective start, segment bounds and lineage, timestamp mapping details, source frames trimmed before/after the episode window, calibration status, coordinate conventions, and warnings.
- `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`: the unmodified raw samples whose timestamps fall within this segment's first and last frame timestamps. No sensor resampling or interpolation is performed.

The session MP4 and source manifest remain in `/srv/sessions`; `rgb_frames` makes the published segment self-contained for image input.

## Alignment and data policy

CSV camera timestamps and MP4 PTS are checked after rebasing both to their first sample. The common prefix is mapped by ordered frame index; CSV tail rows with no encoded MP4 image are excluded. The check has configurable per-interval and cumulative relative-error limits. Re-basing checks cadence, not absolute clock offset or physical frame identity, so output metadata keeps `timestamp_timebase_verified` false. `main_frame_timestamps.csv.frame_number` is never interpreted as a frame index.

ARCore rows are joined only by exact equality between `timestamp_ns` and `android_camera_timestamp_ns`. Frames with no ARCore row are marked `tracking_state=MISSING`. Unusable poses are dropped or repaired by the trajectory stage below rather than published.

`max_paused_duration_ms` is measured from the first PAUSED frame timestamp to the next non-PAUSED frame timestamp; a PAUSED run ending at the episode boundary is extended by one median in-episode RGB interval. `num_frames_trimmed_at_start/end` count source encoded MP4 frames outside the episode timestamp window. CSV timestamp rows without an encoded frame inside the episode window are reported separately and never fabricated into RGB samples.

An episode that starts before its first encoded RGB frame uses `effective_start=max(episode_start, first_rgb_timestamp)`, emits a warning, and records the clipped time. No timestamp is shifted or inferred.

## Pose validity and trajectory repair

A pose is usable only when its `tracking_state` is in `pose_validity.usable_tracking_states`, every translation and rotation component is present and finite, and the quaternion norm is within `pose_validity.quaternion_norm_tolerance` of unity. The state gate is load-bearing, not redundant: real uploads fill PAUSED and MISSING rows with a constant unit-norm placeholder pose, so the numeric checks alone would accept them. A row that claims a usable state but carries unreadable numbers is recorded as `INVALID_TRACKING_POSE`, never trusted.

Repair then runs per episode, in this order, and only within the episode window the timestamps already selected:

1. **Trim.** Leading and trailing runs of unusable poses are cut. Counted as `trimmed_start_frames` / `trimmed_end_frames`.
2. **Interpolate.** A dropout is filled only when it is at most `pose_gap.interpolate_max_frames` long *and* spans at most `pose_gap.interpolate_max_gap_ms` between its bounding valid poses. Translation is linear in timestamp; rotation is shortest-arc SLERP. Component-wise quaternion interpolation is not used as the general method — only as the small-angle fallback where it is numerically equal to SLERP. Filled rows keep `pose_valid_original=false`, gain `pose_interpolated=true`, and keep the tracking state ARCore reported, so a repaired pose is never mistaken for a measured one.
3. **Split.** A longer tracking loss ends the segment and starts a new one after the gap; the unusable frames are dropped. Motion across a long loss is unknown, so it is never bridged.
4. **Drop short segments.** A segment shorter than `trajectory_quality.min_publish_segment_frames` source frames is dropped rather than published as its own episode.
5. **Reject.** An episode left with no segment is rejected with `NO_VALID_TRACKING_POSE` (no usable pose at all) or `ALL_SEGMENTS_BELOW_MIN_PUBLISH_LENGTH`.

## Handoff contract

Every published artifact records the values it was built against, under `handoff_contract`, in `session_metadata.json`, each segment's `metadata.json`, and `validation_report.json`:

```json
"handoff_contract": {
  "version": "omx_processed_v1_posefix_1",
  "source_hz_reference": 30.0,
  "policy_hz_reference": 10.0,
  "action_horizon_reference": 16,
  "min_publish_segment_frames": 48
}
```

This exists because the config check below only catches drift on this side. This preprocessor cannot see the GPU's configuration, so if the GPU raises its action horizon to 32 while this config still says 16, nothing here fails — the output is simply built to the older contract. The GPU inspector/converter is expected to compare its own values against this block and fail on a mismatch. A segment carries it too, so it stays self-describing if it is moved without its session directory. Bump `version` when the meaning of the published output changes, not merely when a number does.

`min_publish_segment_frames` is the one number CPU and GPU must share: a shorter segment yields no sample under the GPU's `SequenceSampler(action_padding=False)`, which the GPU treats as a contract error. It is counted in source frames, so `trajectory_quality` also records the rates it was derived from (`source_hz_reference`, `policy_hz_reference`, `action_horizon_reference`). The loader computes `implied_min_publish_segment_frames = ceil(action_horizon * source_hz / policy_hz)` — 48 for the current 16-step horizon at 10 Hz over 30 Hz source — and **refuses to run** when the configured gate is below it. Publishing a segment the GPU must reject would export the failure instead of preventing it, so the mismatch is a startup error rather than a silent override. Raising the GPU's action horizon therefore fails loudly here until both sides are updated together.

## READY

`READY` marks a session the GPU may pull. It is written only after preprocessing, validation and output publication have all completed, as the last operation on the session directory, and only when the session has at least one training-usable segment. A session directory existing, or preprocessing finishing without an exception, is not READY. Sessions with no usable segment are published without `READY` and listed in the validation report with their reject reasons.

## Transform and action conventions

ARCore quaternions are interpreted in `[x,y,z,w]` order as active Hamilton rotations. Translation is meters. `T_A_B` maps column-vector coordinates from frame B to frame A; matrices are homogeneous 4x4, stored row-major. ARCore camera local axes are +X image-right, +Y image-up, and -Z forward; the session world is right-handed and local to an ARCore session. The uploader does not record its ARCore SDK version, so the documented legacy camera-axis rotation behavior in ARCore 1.5 and earlier cannot be ruled out by this preprocessing run.

The calibration interface uses `T_world_EE = T_world_camera @ T_camera_EE`. The checked-in config contains identity only as a placeholder and marks calibration unfinalized. Consequently `T_world_EE`, `T_episode0_EE`, and actions derived from it are for pipeline/interface validation and must not be treated as calibrated EE training labels. Segment-relative pose is `inverse(T_world_EE[t0]) @ T_world_EE[t]`, with `t0` the segment's first frame. The action helper computes `inverse(T_t) @ T_(t+h)` only when both endpoint poses are valid; it does not skip invalid spans or interpolate. Position/rotation/gripper action encoding remains pending the GPU baseline contract.

Quality thresholds are in `preprocess_v1_config.json` and marked `thresholds_finalized: false`. Labels are provisional and should be re-evaluated before training.

## Not done here

Policy-rate downsampling, `T_camera_EE` application as a calibrated transform, 6D rotation encoding, UMI ReplayBuffer/Zarr construction, CLIP preprocessing, and Diffusion Policy action encoding are GPU-side steps. CPU output stops at a time-aligned, fully-posed, continuous trajectory dataset.
