# Aux-supervision data preparation journal (2026-09-27)

Scope (user request, this evening): prepare and verify data assets for two follow-up experiments --
A. grasp/release timing supervision, B. ORACLE target/EE patch relation -- and stop.
No training, no model / loader / evaluator change, no segmentation network, G0 only.
Times are the machine clock (KST) at the moment of writing.

## 23:40 Mapping and timing labels (label sidecars written)
Purpose: an exact source-demo/frame <-> zarr row <-> training-sample map, and per-row
phase / event-timing labels for all 91 demos.
Control: nothing is assumed. The cut rule is demos_to_umi_zarr.py's own (split a demo at
dt > MAX_STEP_S 0.105 s; keep pieces >= MIN_SEGMENT 17 frames, each piece one episode);
which folders built which zarr is established by reproducing meta/episode_ends and every
row's gripper width / EE pos / EE rot bit for bit; the training samples are the index
list of UmiDataset instantiated from the definitive G0 run's saved hydra config.
Result:
- "91 demos -> 94 episodes" is not one mapping. omx_sim_train_v2 = train 20 + v2_train 48
  = 68 demos -> 94 episodes (23 demos cut at timing gaps; 258 frames in pieces < 17
  dropped); omx_sim_val_v2 = v2_val 18 ONLY -> 27 episodes (the first guess val + v2_val
  failed the episode_ends check -- that is how it was found); omx_sim_val (clean era) =
  val 5 -> 6 episodes. 68 + 18 + 5 = 91.
- All three: episode_ends reproduced, all rows bitwise equal on 3 lowdim keys, source
  (demo, frame) unique per row (0 duplicates, 0 unmatched), timestamps increasing and
  frames contiguous inside every episode (max step 0.104 s).
- The definitive run overrode val_ratio to 0.0, so all 94 episodes train; the sampler gives
  one sample per row whose 16-step action window fits: 22942 - 15*94 = 21532 samples
  (checked equal), obs rows {r-1, r}, action rows r..r+15.
- Events (earlier 91-demo rule reused; object_lifted = lift-off of the stretch passing the
  evaluator's strict secure-grasp test, constants imported from definitive/aggregate.py):
  found 91/91 each, exactly one close and one open hysteresis transition in every demo,
  secure lift in every demo. close - GRASP start +1..+2; lift - GRASP start +18..+21;
  open - PLACE start +6..+14 = RETREAT start -13..-12 -- identical to the earlier analysis.
  Camera-width events agree within -1..0 (close) / -2..+1 (open) frames.
- Horizon-16 coverage (train samples): close 4.6 %, lift 5.1 %, open 4.7 %.
Interpretation: the label side is ready; the mapping is exact. Files:
sim_umi/data/sidecars/{omx_sim_train_v2,omx_sim_val_v2,omx_sim_val}.labels.{npz,json}.

## 23:50 Oracle mask source audit and first renders
Purpose: find an exact, model-free source for target / EE masks.
Result: the plant simulator loads sim_umi/mjcf/collector_scene.xml (URDF <mujoco_model>),
and the demo collector already posed a mirror of that model and rendered its wrist-camera
segmentation (only to count visibility; no mask was stored). Demos store the TCP pose, not
the joints: the 5 arm joints are recovered by Gauss-Newton on the TCP site, warm-started
from the recorded home q -- over all 91 demos residuals <= 2e-8 m / 0.018 deg, <= 5 iters.
A mirror RGB render of the rebuilt state matches the recorded frame to 0.2 grey levels
(median over the crop): the state is right. Two defects found and fixed before any sidecar
was written: (1) segmentation with the model's 4x MSAA decodes blended edge colours into
unrelated geom ids (up to 35 stray "finger" px per frame at bin/paper junctions) -> seg
and depth renderers now run without multisampling; after that 0 finger px off the finger
box and 0 ball px more than 2 mm off the ball surface over 517 probe frames; (2) the
recorded ball position is ~20 ms off the image instant (the collector reads the latest
free-joint message): carried ball 2-3 px off at the edge, falling ball more -- correction
under test (next entry).
Tip region: the visible finger (y 26..64 mm in its frame) is almost entirely the pad
(contact) face, so pad-proximity or y >= 30 mm reproduce ee_gripper_mask; ee_tip_mask =
the distal 15 mm (y >= 50 mm; held ball centre at 37.7..42.6 mm), and the finger-frame y
map is stored so another band is a threshold away.

## 23:56 Ball-pose timing: how much does a time shift fix? (6 train demos, every 3rd frame)
Purpose: the recorded ball position is not taken at the image instant -- the collector
reads the latest message of the free-joint publisher, which runs at 20 Hz (so the ball
sample is 0..50 ms older than the picture, varying frame to frame). Measure the effect on
target-mask alignment and test simple corrections before building any mask sidecar.
Control: metric = mean |mirror render - recorded RGB| (grey levels) in a +-2 px band around
the rendered target boundary, inside the G0 crop, tip patches excluded; lower = better
aligned. Same frames, same renders, only the ball position differs. Arm / jaw / bin are not
affected (their band error is ~0.2-1.6 levels).
Result (median / p95 per phase):
  phase          raw          +10 ms lin   +20 ms lin   +20 ms quad  +30 ms lin
  GRASP_LIFT     5.3 / 7.8    3.9 / 5.2    2.9 / 4.2    2.9 / 4.3    3.9 / 5.4
  TRANSPORT      7.1 / 24.9   5.0 / 17.0   3.3 / 7.3    3.3 / 6.9    4.5 / 13.9
  RELEASE        5.9 / 22.6   4.1 / 24.1   3.4 / 26.6   3.5 / 19.8   4.1 / 28.2
  RETREAT_POST   5.4 / 6.7    4.7 / 5.8    4.0 / 5.8    4.0 / 6.3    3.7 / 6.2
Interpretation: a constant +20 ms shift of the ball track removes most of the carry error
(TRANSPORT p95 24.9 -> 7.3), consistent with the 20 Hz publisher's mean age; it cannot fix
the free-falling ball after release (RELEASE p95 stays ~20-27), because the per-frame age
is unknown and the ball moves up to ~1.5 m/s there. Next, not started: (a) while the ball
is held, place it rigidly in the tool frame (offset from the static PLACE-hold frames, where
lag does not matter), (b) flag the few free-fall rows as target-pose-uncertain instead of
pretending, (c) then the full mask build. Mask sidecar NOT built yet; waiting for the user.

## 00:13 (09-28) Target pose regimes, full oracle mask build, validation, prep report
Purpose (user approval after the interim report): target pose by phase -- recorded GT while
free/static, EE pose x robust T_EE->object while securely held, target_mask_valid = false
from the release until the ball is at rest; no deeper trajectory fitting. Then the full
sidecar, 50+ frame visual QA, visibility / occupancy statistics, and the report.
Control: T_EE->object = per-axis median of the tool-frame ball offset over the STATIC
secure-hold frames (TCP < 5 mm/s), where the 20 Hz publisher lag cannot matter; every
secure-hold frame's residual recorded. Alignment judged per pixel by a QA-only search of
the best render-vs-recording offset (+-4 px), comparing pose sources on the same frames.
Result:
- 14-16 static secure-hold frames per demo (no fallback). Static residual median 0.04 mm
  (max 0.65); all secure-hold frames 1.33 mm median, 3.91 max (the publisher lag while
  moving); median over all frames vs static median <= 0.57 mm. The arm still moves in
  parts of the PLACE hold (up to 0.078 m/s), so rigid_ee covers object_lifted..open_start-1.
- First release-rest rule fired at open_start+1 (the ball not yet dropped counted as "at
  rest"); fixed before building: invalid until the ball fell 10 mm and then moves < 1 mm
  per frame -> 6-9 invalid rows per demo, 606 in total.
- TRANSPORT pixel offset: raw recorded p90 2.5 px, max 3.7, 14 % of rows >= 2 px; rigid_ee
  p90 0, max 1.24, 0 %. (+20 ms shifted track: max 2.5, 2 %.) GRASP_LIFT (recorded):
  max 1.24 px, 0 % >= 2 px. The grey-level band metric had ranked rigid below the shift in
  its median -- sub-pixel shading, not offset.
- Full build: train 22942 rows in 61 s (45 MB), val_v2 6329 (12 MB), val 1650 (3 MB); every
  row rendered, 0 finger px off the finger box, 0 ball px > 2 mm off the ball surface.
- Validation: all rows' zarr RGB closest to their mapped source frame (0 rows where the
  neighbouring frame is closer); 30/30 byte-identical re-encodes per split. 60 overlay
  tiles per split (12 per phase) with the train crop applied to RGB + masks by one offset:
  aligned. crop_resize_pair == the encoder's RandomCrop->Resize bit for bit; one crop per
  call for the whole batch; patch_occupancy == ViT token order.
- Stats (train, target on valid rows): target visible 95.2 % of rows (100 % in GRASP_LIFT
  and TRANSPORT); empty targets are all explained (outside G0 crop 514 -- HOME /
  SEARCH_OBJECT; outside the frustum 518 -- below the gripper after landing and early
  RETREAT; occluded 2). Gripper never empty; tip empty in 4 rows. Patches touched
  (median, visible): target 30, gripper 16, tip 14 (7 while holding).
Interpretation: both data assets are ready. Report: PREP_REPORT.md. No training started.
