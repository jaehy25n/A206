# Data preparation report: timing labels and ORACLE target/EE masks

Status: prepared and verified. Nothing was trained, and no policy, loader, encoder,
evaluator or zarr was changed. Geometry is G0 only.
Journal: `JOURNAL.md` in this folder. Validation images and statistics: `validation/`.

Everything here is **train-only**. The timing labels come from simulator ground truth
(GT) and the scripted expert. The masks are **oracle** masks, rendered from simulator GT.
Neither may become a deployment input.

---

## [Mapping]

### Why 91 demos became 94 episodes

The 91 demos are not one mapping. They were built into three zarrs, and which source
folders went into which zarr was established by reproducing each zarr, not by reading
folder names.

| zarr | source folders | demos | episodes | rows | training samples |
|---|---|---|---|---|---|
| `omx_sim_train_v2` (the G0 training set) | `train` 20 + `v2_train` 48 | 68 | 94 | 22,942 | 21,532 |
| `omx_sim_val_v2` | `v2_val` 18 **only** | 18 | 27 | 6,329 | (5,924) |
| `omx_sim_val` (clean era) | `val` 5 | 5 | 6 | 1,650 | (1,560) |

The 68 train demos became 94 episodes because of a cut rule in `demos_to_umi_zarr.py`:

- A demo is split wherever two consecutive frames are more than `MAX_STEP_S` = 0.105 s
  apart, which marks a frame that never arrived.
- Every piece of at least `MIN_SEGMENT` = 17 frames becomes its own zarr episode.
- Shorter pieces are dropped. In train, 23 demos were cut and 258 frames were dropped.

### Training samples

The sample list is the loader's own. `UmiDataset` was instantiated from the definitive
G0 run's saved hydra config (`.hydra/config.yaml`, `val_ratio` overridden to 0.0, so all
94 episodes train).

- There is one sample per row whose 16-step action window fits inside its episode:
  22,942 − 15 × 94 = 21,532.
- Observation rows are `{r−1, r}`. At an episode start the first row is repeated.
- Action rows are `r .. r+15`, with no padding.
- For the two val zarrs, the numbers in brackets are what the same sampler config would
  give. The definitive run did not use those zarrs for training.

### Row mapping

Row mapping succeeded for all three zarrs:

- `meta/episode_ends` was reproduced.
- Every row is bitwise equal to its source frame on `robot0_gripper_width`,
  `robot0_eef_pos` and `robot0_eef_rot_axis_angle`.
- Unmatched rows: **0**. Duplicate `(demo, frame)` pairs: **0**.
- Timestamps increase and frames are contiguous inside every episode. The largest step is
  0.104 s.
- Each demo's close, lift, open and retreat rows land in exactly one zarr episode. No
  event fell into a dropped piece.

Each row carries these fields: `source_split`, `source_demo_id`, `source_frame_idx`,
`zarr_episode_idx`, `zarr_row_idx`, `timestamp_s`, `is_sample_current`.

---

## [Timing]  (label sidecar, left as built)

### Event rules

These are the rules of the earlier 91-demo analysis, reused unchanged. The width is the
true jaw width at the image instant (`eval_gripper_width_gt`).

**Reference widths**
- `open_w` = median of the first 10 frames.
- `hold_w` = median over the expert's LIFT .. PLACE-start stretch.
- `mid` = (`open_w` + `hold_w`) / 2.

**close_start**
- The first frame whose width is below `open_w` − 1 mm.

**open_start**
- Start from the first frame that rises back above `mid` after having been below it.
- Walk back along the monotonic rise (steps > 0.1 mm) to where the opening began.
- This refines a detected crossing. A width threshold is not used as the detector,
  because the held width creeps by about 0.5 mm.

**Hysteresis check**
- Levels are `hold_w` + ¼Δ and `open_w` − ¼Δ.
- Every demo must make exactly **1** close transition and **1** open transition.

**object_lifted**
- The lift-off frame of the lifted stretch that passes the evaluator's strict
  secure-grasp test: ball z > r + 20 mm; rigid in the tool frame within 4 mm for at
  least 0.5 s while the tool travels at least 30 mm.
- The constants are imported from `definitive/aggregate.py`.
- In all 91 demos this is also the first lifted frame.

**retreat_start**
- The first frame the expert labelled RETREAT.

### Detection over all 91 demos

| event | detected |
|---|---|
| close | 91/91 |
| lift | 91/91 (all secure) |
| open | 91/91 |
| retreat | 91/91 |
| exactly one close and one open transition | 91/91 |

Camera-width events agree with the GT events within −1..0 frames (close) and −2..+1
frames (open).

### Offsets (frames, 10 Hz)

| offset | min / median / max | expected |
|---|---|---|
| close_start − GRASP start | +1 / +1 / +2 | +1..+2 ✓ |
| object_lifted − GRASP start | +18 / +19 / +21 | +18..+21 ✓ |
| object_lifted − close_start | +16 / +18 / +20 | |
| open_start − PLACE start | +6 / +11 / +14 | mid-PLACE ✓ |
| open_start − RETREAT start | −13 / −13 / −12 | before RETREAT ✓ |

### Durations (s)

| interval | mean | median | range |
|---|---|---|---|
| close → lift | 1.76 | 1.80 | 1.60–2.00 |
| lift → open | 14.04 | 13.90 | 12.40–16.50 |
| open → retreat | 1.27 | 1.30 | 1.20–1.40 |

### 5-stage distribution (train, 21,532 samples)

| phase | share of samples |
|---|---|
| APPROACH | 36.3 % |
| GRASP_LIFT | 5.6 % |
| TRANSPORT | 43.3 % |
| RELEASE | 4.0 % |
| RETREAT_POST | 10.9 % |

In rows: 7,969 / 1,197 / 9,541 / 860 / 3,375, in the same order.

### Time to event (train samples)

| event | share of samples where it is still ahead | dt percentiles for those, 5/25/50/75/95 (s) |
|---|---|---|
| close | 36.3 % | 0.7 / 3.1 / 6.0 / 8.9 / 12.3 |
| lift | 41.9 % | 0.7 / 3.5 / 6.9 / 10.2 / 13.9 |
| open | 85.2 % | 1.5 / 7.1 / 13.9 / 20.8 / 26.9 |

### Horizon-16 coverage

This is the share of samples whose event falls in the sample's own 16-step action window
(same episode). It is **recorded only**; no clipping or normalisation was applied.

| event | train | val_v2 | val |
|---|---|---|---|
| close | 4.64 % (999) | 4.66 % | 5.13 % |
| lift | 5.05 % (1,088) | 4.86 % | 5.13 % |
| open | 4.70 % (1,013) | 4.59 % | 5.13 % |
| any of the three | 14.4 % | | |

### Stored per row

- `expert_stage_10` (raw) and `phase_5`.
- `dt_to_{close,lift,open,retreat}_s`: signed, unclipped.
- `frames_to_*`: signed. Demo frames equal zarr rows equal action steps inside an
  episode.
- `{close,lift,open}_is_future`: frames_to > 0.
- `{close,lift,open}_within_horizon16`.
- `dt_to_{close,open}_cam_s`: the camera-width cross-check.

The per-demo and per-episode event indices are stored in both demo-frame and zarr-row
coordinates.

---

## [Segmentation]  (oracle mask sidecar)

### Source audit

| candidate source (in priority order) | available? | used |
|---|---|---|
| 1. MuJoCo segmentation / geom-id render | yes | **yes** |
| 2. GT pose + camera + known geometry | yes (this is what the render does) | implicitly |
| 3. masks from dataset generation | no: the collector rendered segmentation only to count visibility | no |
| 4. colour / geometry CV | not needed | no |

**The model.** The plant simulator loads `sim_umi/mjcf/collector_scene.xml` (URDF
`<mujoco_model>`). The masks are rendered from the wrist camera of that same model.

**Rebuilding the state of each row.** The demos store the TCP pose, not the joint angles.

- The 5 arm joints are recovered by Gauss–Newton on the TCP site, warm-started from the
  previous frame. Over 91 demos the residuals are ≤ 2e-8 m and ≤ 0.018°, in ≤ 5
  iterations.
- The jaw comes from the true width through the model's angle-to-width table.
- The bin comes from the spec.
- A mirror RGB render of the rebuilt state matches the recorded frame to a median of 0.22
  grey levels inside the crop.

**Masks.** The EE masks come from the same render.

- `target_mask`: geom `object_geom`, with occlusion.
- `ee_gripper_mask`: every geom of bodies `left_finger` and `right_finger`. These are the
  only visible gripper geoms; the contact pads are invisible.
- `ee_tip_mask`: `ee_gripper_mask` pixels whose back-projected surface point (from the
  depth render) lies at y ≥ 50 mm in its own finger's frame. That is the distal 15 mm of
  the 65 mm finger, which contains the width detector's tip patch at 60.5 mm.
  - Why not a wider rule: the visible finger spans y 26–64 mm and is about 99 % pad
    (contact) face. A pad-proximity rule or y ≥ 30 mm would therefore reproduce the
    gripper mask.
  - For reference, the held ball's centre sits at y 37.7–42.6 mm in all 91 demos.
- `ee_finger_y_mm` (uint8): the finger-frame y of every gripper pixel. Any other tip band,
  such as the contact band 35–45 mm, is one threshold away.

**Two render fixes applied before building.**

1. Segmentation and depth are rendered **without MSAA**. With the model's 4× MSAA, edges
   between two geoms decoded into a third, unrelated id: up to 35 stray finger pixels per
   frame. After the fix:
   - 0 finger pixels lie outside the finger box (+3 mm);
   - 0 ball pixels lie more than 2 mm off the ball surface, in every row of all three
     sidecars.
2. The recorded ball position comes from a **20 Hz** publisher, so it is 0–50 ms older
   than the image. Target pose per row, as approved:
   - **recorded**: before secure lift-off (free, static, or being gripped), and after the
     released ball is at rest again. Uses the recorded GT of that row.
   - **rigid_ee**: from object_lifted to open_start − 1, which covers TRANSPORT and the
     PLACE hold. The pose is the row's TCP pose (exact at the image instant) times a
     per-demo T_EE→object.
     - Estimate: per-axis median of the tool-frame offset over **static secure-hold
       frames** (TCP < 5 mm/s). There were 14–16 such frames per demo, and no demo needed
       the all-frames fallback.
     - The ball is a sphere, so T_EE→object is a translation. Over all 91 demos it spans
       x 0.04–0.06, y −17.61 to −17.38, z 1.24–7.55 mm.
     - Residual on the static frames: median 0.04 mm, max 0.65 mm.
     - Residual on all secure-hold frames: median 1.33 mm, p95 2.76 mm (median over demos), max 3.91 mm. This is
       the publisher lag while moving.
     - The median over all frames differs from the static-frame median by at most 0.57 mm.
     - All of these are stored per demo.
   - **invalid**: from open_start until the ball has fallen 10 mm and moves less than
     1 mm per frame. This is 6–9 rows per demo, 606 rows in total. These rows have
     `target_mask_valid = false` and must be excluded from relation supervision. The mask
     stored there is the recorded-pose render and is kept for pictures only.
   - No quadratic interpolation, ballistic fit or RGB-driven alignment was used.

**Model-free.** No learned model, no SAM, no YOLO and no colour threshold was used. The
file names carry `oracle`.

### Visibility and ViT occupancy (train, G0 224×224)

- Visible means at least 12 px at 224.
- The target statistics use valid rows only.
- Occupancy counts the 14×14 patches with non-zero area.

| phase | rows (target-valid) | target visible | target empty | target patches mean / median | gripper visible, patches mean / median | tip visible, patches mean / median |
|---|---|---|---|---|---|---|
| APPROACH | 7,969 (7,969) | 92.2 % | 7.6 % | 13.9 / 12 | 100 %, 16.0 / 16 | 100 %, 14.0 / 14 |
| GRASP_LIFT | 1,197 (1,197) | 100 % | 0 % | 31.2 / 31 | 100 %, 14.5 / 15 | 97.7 %, 7.5 / 7 |
| TRANSPORT | 9,541 (9,541) | 100 % | 0 % | 31.4 / 31 | 100 %, 14.9 / 15 | 100 %, 6.9 / 7 |
| RELEASE | 860 (410) | 33.2 % | 65.4 % | 1.0 / 0 | 100 %, 15.9 / 16 | 100 %, 12.5 / 14 |
| RETREAT_POST | 3,375 (3,375) | 94.8 % | 4.8 % | 9.8 / 11 | 100 %, 16.0 / 16 | 100 %, 14.0 / 14 |
| **all rows** | 22,942 (22,492) | 95.2 % | 4.6 % | 21.4 / 28 (30 when visible) | 100 %, 15.5 / 16 | 99.9 %, 10.6 / 14 |
| **train samples** | 21,532 (21,085) | 95.0 % | 4.8 % | 21.8 / 30 (31 when visible) | 100 %, 15.4 / 16 | 99.9 %, 10.5 / 13 |

**EE masks.** The gripper mask is empty in 0 rows; the tip mask in 4 rows (0.02 %), where
the ball hides the tips during GRASP.

**Empty target masks are normal.** Each is classified by reason. The remaining empty
target rows (the 606 invalid rows are counted separately) are:

| reason | rows | where |
|---|---|---|
| in the frame but outside the G0 crop | 514 | APPROACH only: HOME and SEARCH_OBJECT |
| outside the camera frustum | 518 | 87 in APPROACH; 268 in RELEASE (the ball is below the gripper after it lands); 163 in RETREAT_POST |
| occluded | 2 | |
| other or unexplained | 0 | |

By expert stage, target visibility is:

| expert stage | target visible |
|---|---|
| HOME | 57 % |
| SEARCH_OBJECT | 70 % |
| APPROACH_OBJECT | 99.8 % |
| GRASP, LIFT, SEARCH_BIN, TRANSPORT | 100 % |
| RETREAT | 93 % |
| SETTLE | 100 % |

The val zarrs look the same (`validation/*_stats.json`).

---

## [Validation]

### Mapping

- Every row's decoded zarr RGB was compared with the G0 frame rebuilt from its mapped
  source frame:

  | comparison | mean difference |
  |---|---|
  | against the mapped source frame | median 0.13, max 0.22 grey levels (JPEG-XL loss) |
  | against the neighbouring source frame | median 1.1–1.3 |

  In no row did the neighbouring frame match better (0 rows, all three splits).
- For 30 random rows per split:
  - re-encoding with the G0 codec gave **byte-identical** chunks (30/30);
  - stage and timestamp are equal (30/30);
  - picture: `validation/*_mapping_30.jpg`.

### Mask visuals

- **Coverage:** 60 rows per split, 12 per phase. Each tile shows RGB with target (red),
  gripper (green), tip (blue) and the 14×14 grid, beside the same row after one random
  train crop applied to RGB and masks with a single offset.
  - Files: `validation/*_overlay_phase*.jpg`, plus 3× boundary zooms in
    `*_target_boundary_zoom3x.jpg`.
- **Target:** the target boundary follows the ball in every valid tile, including the
  3× zooms. A 1 px bright rim above the held ball is the recording's MSAA edge, not an
  offset.
- **Fingers and tips:** the gripper mask covers the fingers, and the tips are the distal
  ends.
- **Crop:** alignment holds after the crop.
- **Invalid rows:** they are labelled INVALID, and the falling ball is visibly off there,
  as expected.

### Quantitative alignment (QA)

Two measures are used:

- **Band agreement:** the median |render − recorded| in a ±2 px band around the target
  boundary, in grey levels, valid rows only.
- **Pixel offset:** the best-alignment offset of the render against the recorded frame,
  searched over ±4 px. This is a QA measurement only and was not used to make the masks.

| phase | band agreement median / p95 | pixel offset |
|---|---|---|
| APPROACH | 1.2 / 4.4 | |
| GRASP_LIFT | 5.2 / 14.2 | 210 rows: max 1.24 G0 px, 0 % ≥ 2 px |
| TRANSPORT (rigid_ee) | 5.3 / 10.5 | 108 rows: 90 % at 0 px, max 1.24 px, 0 % ≥ 2 px |
| RELEASE (valid) | 7.6 / 9.2 | |
| RETREAT_POST | 6.0 / 8.3 | |

For comparison, TRANSPORT with the raw recorded pose had p90 2.5 px, max 3.7 px and 14 %
of rows ≥ 2 px. The remaining band error is shading and edge antialiasing, not offset.

Other checks:

- Back-projected target depth error: median 0.12 mm.
- The collector's own recorded visibility flag agrees with the oracle (≥ 12 px in the
  crop) on 99.99 % of rows (train); 2 rows differ.

### Augmentation alignment (audit and plan; not implemented)

**Where augmentation happens.** It is not in the dataset. `TimmObsEncoder.forward` applies
`Sequential(RandomCrop(212), Resize(224, antialias), ColorJitter)` to the (B·T) image
batch. torchvision 0.16 draws **one** crop offset and one set of jitter parameters per
call, shared by the whole batch (verified).

**The helper.** `oracle_masks.crop_resize_pair(rgb, masks, top, left)` reproduces the
encoder's RGB crop and resize bit for bit (max |diff| 0.0, verified), and applies a
nearest resize to the masks. The evaluation CenterCrop offset is (6, 6), from
`eval_crop_offset()`.

**Minimal patch plan for later.**

1. **SequenceSampler / UmiDataset.** Open the mask sidecar next to the replay buffer. It
   is row-aligned, and the sampler's indices are zarr rows. Slice the masks with the
   exact RGB rule: rows `{r−1, r}`, with first-frame padding.
   - Return them as uint8 under a separate `aux` key, not in `obs`, so the normaliser and
     the policy never see them.
   - Return the same way `target_mask_valid[obs rows]` and the timing labels at `r`.
2. **TimmObsEncoder.forward.** When aux masks are present, replace the Sequential call
   with the following, per call:
   - draw `RandomCrop.get_params` once;
   - call `crop_resize_pair` on the image and masks;
   - apply `ColorJitter` to the image only.
   In eval, use offset (6, 6).
3. **Occupancy.** `oracle_masks.patch_occupancy(mask224)` gives [..., 196] area fractions
   in ViT token order. This was verified against a patch-embed style conv, flatten and
   transpose. Occupancy must be computed **after** the crop and resize, never stored
   before them.

---

## [Artifacts]

### Sidecars

The sidecars are in `sim_umi/data/sidecars/`, which is not tracked by git. The JSON
summaries are committed, with the sha256 of each file.

| file | content | size |
|---|---|---|
| `omx_sim_train_v2.labels.{npz,json}` | row, episode, demo and sample tables; phase_5; expert_stage_10; timing | 175 KB |
| `omx_sim_val_v2.labels.*`, `omx_sim_val.labels.*` | the same | 69 KB, 35 KB |
| `omx_sim_train_v2.oracle_masks_g0.{zarr.zip,json}` | `data/{target_mask, ee_gripper_mask, ee_tip_mask}` [N,224,224] bool; `data/ee_finger_y_mm` uint8; `data/target_mask_valid`; `data/target_pose_source`; `state/*`; `stats/*`; `qa/*`; `demo/*` (rigid fits). Blosc zstd bitshuffle, chunk (1,224,224) | 45 MB |
| `omx_sim_val_v2.oracle_masks_g0.*`, `omx_sim_val.oracle_masks_g0.*` | the same | 12 MB, 3 MB |

### Code

| file | purpose |
|---|---|
| `sim_umi/scripts/labels/build_label_sidecar.py` | mapping and timing |
| `sim_umi/scripts/labels/build_oracle_masks.py` | oracle masks |
| `sim_umi/scripts/labels/validate_sidecars.py` | validation |
| `sim_umi/src/oracle_state.py` | state rebuild |
| `sim_umi/src/oracle_masks.py` | G0 transform, occupancy, crop pair |

### Validation outputs

`sim_umi/train_results/2026-09-27_aux_prep/validation/`: mapping sheets, 5 phase overlay
sheets per split, boundary zooms, `*_stats.json`.

### Provenance

The sidecars were built at HEAD `14affc8` from the builder files, then committed
unchanged. The commit hash is in the commit that adds this report.

### Not done, by instruction

Training, auxiliary heads, FiLM, loss or action changes, ViT changes, segmentation
networks, FOV re-runs, evaluator changes, timing clipping/normalisation, target
trajectory fitting.
