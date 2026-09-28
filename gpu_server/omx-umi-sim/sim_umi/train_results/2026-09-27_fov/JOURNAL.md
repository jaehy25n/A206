# FOV / input-geometry ablation — journal (started 2026-09-27)

Each entry: purpose / control / result / interpretation. Times KST.

G0 = definitive v2_11400 (not retrained). G1 = full-FOV letterbox into the
square ViT. G2 = full-FOV rectangular ViT (288x176 canvas, 198 patch tokens).
Frozen: tip patch, width calibration, dataset labels, expert trajectories,
robot/camera/physics, action space, executor, evaluator episode set.

## ~09:30 Raw-image source audit — full FOV exists, exact (no HARD STOP)
Purpose: before any code change, find what camera0_rgb actually stores and
whether the original full-FOV frames can be recovered exactly.
Result:
- combined zarr camera0_rgb: (22942, 224, 224, 3) uint8, chunks (1,224,224,3),
  JpegXl level 99, lossless=False. The training set stores ONLY the centre
  crop, lossy.
- Source: sim_umi/data/demos/{train (20 eps), v2_train (48 eps)}/*.npz, key
  rgb (N, 180, 320, 3) uint8, magenta already masked at record time, stored
  deflate (lossless). Re-running the converter's own segmentation on those
  directories gives 94 segments / 22942 rows with lengths equal to the zarr's
  episode_ends; eef_pos and gripper_width rows are bitwise equal.
- For 60 frames spread over the set, npz frame -> center_crop_resize (INTER_AREA,
  224) -> JpegXl(level 99) is byte-identical to the stored zarr frame (60/60).
  The JPEG-XL loss itself: max |diff| median 5, worst 8; mean |diff| 0.13.
Interpretation: the full 320x180 frames behind every training frame exist
bit-exactly; G1/G2 inputs can be derived from them without re-rendering or
re-collecting anything.

## ~09:40 G0 image path, measured on the production objects (preflight/01_input_path.*)
Purpose: the exact G0 call chain, not the remembered one. Control: production
UmiDataset from the definitive v2 config and overrides; policy from the
v2_11400 checkpoint cfg with its EMA weights; each stage is the module the
policy calls. Result — training:
  sim camera plugin 320x180 RGB
  -> mask_magenta (collect_demos.py:973)                       npz rgb (180,320,3) uint8
  -> center_crop_resize: centre 180x180, cv2 INTER_AREA -> 224 (demos_to_umi_zarr.py:51,113)
  -> JpegXl level 99, lossy (demos_to_umi_zarr.py:193)          zarr (N,224,224,3) uint8
  -> UmiDataset.__getitem__: moveaxis, /255 (umi_dataset.py:266) (2,3,224,224) float32 [0,1]
  -> normalizer camera0_rgb = identity, scale 1 offset 0 (umi_dataset.py:246)
  -> TimmObsEncoder.forward (timm_obs_encoder.py:266): RandomCrop(212) -> Resize(224,
     bilinear, antialias) -> ColorJitter(b .3, c .4, s .5, h .08); one set of random
     parameters per call for the whole (B*T) batch
  -> CLIP ViT-B/16: patch 16, grid 14x14, 1 CLS, pos_embed [1,197,768], 197 tokens,
     strict_img_size True, no register tokens
  -> CLS [B*T,768] -> global_cond [B,1568] (2x768 + 32 low-dim)
Evaluation: live frame -> mask_magenta (policy_bridge.py:254) -> preprocess_rgb
(centre crop, INTER_AREA 224, /255; policy_bridge.py:63) -> identity normalizer ->
CenterCrop(212) -> Resize(224) (policy_server.py --deterministic, ColorJitter dropped)
-> ViT. Ranges: [0,1] everywhere; imagenet_norm=True in the config is inert (never
read by TimmObsEncoder). CLS norm mean 26.8 on 8 eval-transformed frames.
Interpretation: the remembered 320x180 -> centre crop -> RandomCrop 212 -> Resize 224
is right; add JPEG-XL loss in training only, no mean/std normalization at all,
and batch-shared augmentation parameters. All of it stays as is for G1/G2.
Padding value: with an identity normalizer there is no mean/std to cancel; the
normalizer's own declared stats are mean 0.5, so neutral = 0.5 gray, stored as
uint8 128 (0.50196; 127.5 is not representable) in training and used as 128/255
at run time, identical in both. The CLIP pretraining mean is not used by this
pipeline, so it is not the contract's neutral value.

## ~09:45-10:00 Contract checks before any training (all PASS; training NOT started, waiting for approval)
- Geometry (sim_umi/src/rgb_geometry.py; test preflight/geometry/test_geometry.json):
  G0 frozen -- production center_crop_resize and preprocess_rgb, taken from their
  source files, vs the module on 100 real frames: max |diff| 0 (uint8) and 0.0
  (float). Synthetic coordinate frame: circle 56 px -> 55x55 (G1), 72 -> 72x72
  (G2); corners in place with the right colours (no flip, no H/W swap, no channel
  swap); R rises with x and G with y (corr 1.0); padding 128; the frame's edge
  rows/columns reach the content edges (no crop). Real frames: the same ball,
  located by mapping its raw position, keeps h/w 0.95-1.06 (G1) and 0.97-1.04
  (G2) -- pixel rounding. One earlier "1.25/1.53" reading was the detector
  picking up the white bin that only the wider view contains. In ball-at-right-
  edge frames the G0 crop has no ball at all; G1/G2 show it. No demo frame has
  the ball at the LEFT edge (searched all demo splits), so that case is absent.
- Dataset noise found and kept: UmiDataset adds N(0, 0.05) to the episode start
  pose on every read (umi_dataset.py:313 "HACK"), numpy global RNG. Part of the
  G0 contract; unchanged for G1/G2.
- Rectangular ViT (TimmObsEncoder): square images take the original code path;
  H != W builds timm ViT with img_size=(H, W), RandomCrop(int(H*.95), int(W*.95)),
  Resize((H, W)). G0 regression (v2_11400 EMA, fixed seeded batch, CPU): transform
  repr identical, train- and eval-path encoder outputs bitwise equal before/after.
- Positional embedding (posembed.py, preflight/02_posembed_tests.txt): 11/11 pass --
  identity at 14x14, CLS copied bit for bit, row index runs down 11 rows and
  column index across 18 (no swap), equal to timm resample_abs_pos_embed (bicubic,
  no antialias, max |d| 0), deterministic, ViT(176x288) grid 11x18 pos_embed
  [1,199,768] -> 199 tokens, CLS [.,768]; a 224x224 input is refused.
- Init (shared_init/init_audit.json): source a4cd264f...; G1 uses the same file,
  strict load, policy checksum a4cd264f. G2 init_state_g2.pt: changed keys =
  obs_encoder.key_model_map.camera0_rgb.pos_embed only ([1,197,768]->[1,199,768]),
  CLS row identical, checksum of everything else equal to the source; strict load;
  global_cond [B,1568] in both.
- Config (preflight/03_config_diff.txt): G0 recomposed from its own overrides
  reproduces the saved .hydra config exactly (0 lines). G0->G1: 6 keys (exp_name,
  tags, dataset path x2, task.rgb_geometry, resume False). G0->G2: 12 keys (the same
  plus camera0_rgb.shape x5 and init_state_path). Found on the way: the dataset's
  shape_meta is a YAML-anchor copy the task override does not reach; G2 overrides
  it too. Training values read off the resolved config match the protocol
  (batch 64, AdamW 3e-4 / encoder 3e-5, wd 1e-6, cosine, warmup 2000, total and max
  11400, fp16, accum 1, EMA power 0.75 max 0.9999, horizon 16, obs 2, action 10,
  DDIM 50/16, val_ratio 0).
- Eval crops (torchvision CenterCrop, measured): G1 rows/cols 6..217 (0.9464, as
  G0); G2 rows 4..170, cols 8..280 (0.9489 x 0.9479; int rounding of 0.95).

## 10:05-10:30 Pre-training work (user approved configuration A: G1 on GPU 0, G2 on GPU 5, training only in parallel; all evaluation afterwards on GPU 5; the simulator is left running as it is)
- G1/G2 zarrs (build_geometry_zarr.py, preflight/04_build_zarr.log): non-image keys copied
  from G0's zarr byte for byte; images from the npz source frames through rgb_geometry,
  JPEG-XL level 99. Full G0 check over ALL 22942 rows: rebuilding G0's frame and
  encoding it with G0's codec gives G0's stored COMPRESSED bytes 22942/22942.
  G1 128.4 MB sha256 6c9e98a3..., G2 175.4 MB sha256 f1d8853d... (sidecar .json next to each).
- Zarr audit through the production UmiDataset (preflight/05_zarr_audit.json): non-image
  keys identical bytes; N 21532, DataLoader 337, batch 64, drop_last False; samples
  [2,3,224,224] and [2,3,176,288]; low-dim obs and actions equal to G0's at the same
  index and seed. Padding: the first check asked |band-128| <= 2, set before measuring
  what JPEG-XL does to a thin flat band beside an edge; measured, G1's band is exact
  except the row touching the content (<= 7) and G2's 7-row band is within 3 (touching
  row <= 5) -- the codec's error, the same size as on the content (4-9). The criterion
  is now "within the codec's content error"; at run time the band is exactly 128.
- Sample order (user item 5): G1 and G2 construct models that draw different amounts of
  randomness (pos_embed size), which would shuffle differently. Added opt-in
  training.dataloader_seed (a torch.Generator for the DataLoader: sampler permutation and
  worker base seed) and training.log_batch_fingerprints (hashes of eef_pos and action per
  batch for the first N batches, plus the start-pose-noise obs). Also the first-step probe
  now records the image batch shape, the ViT token sequence and global_cond. Without the
  keys the DataLoader is built as before; G0 used neither, so G0's order is its own.
- Evaluator (code + static tests only; no rollout, no simulator, no camera, no GPU):
  policy_server writes <socket>.meta.json (checkpoint, EMA, rgb_geometry, input HxW, eval
  transform), strips "_" keys, and with --dump-dir saves the exact ViT input for every Nth
  request; policy_bridge.policy_image picks the checkpoint's geometry (G0 = preprocess_rgb
  itself); the bridge logs every frame it gives the policy (masked full frame + canvas) by
  stamp and tags each request with an id; the executor records req_id and fov_diag
  metrics per plan; the rollout saves the frames per episode (lossless npz) and records the
  server sidecar. fov_diag maps ground-truth masks through the policy's exact geometry and
  eval crop (14/14 static tests, mask mapping within 1 px of the real image path).
  test_evaluator_static.py (CPU server, G0 checkpoint): 15/15 pass -- G0 policy_image equals
  preprocess_rgb bitwise, the sidecar is right, an old request without an id still gets
  the same action, the dumped encoder input equals CenterCrop(212)+Resize(224) of what was
  sent exactly.
- Config diff with the two data-order keys: G1 8 keys, G2 14 keys, all allowed.

## 10:30-10:36 Smoke runs, parallel (G1 physical GPU 0, G2 physical GPU 5), 100 updates each
- smoke/ (10:30): launch GPU check PASS (G1 pid on GPU 0, G2 on GPU 5). Everything passed
  EXCEPT one instrumentation defect of mine: the new image-shape probe wrote into the probe
  dict before the forward, and the AMP probe only wrote into an EMPTY dict, so autocast and
  the denoiser dtype were not recorded. Fixed (c259153: the AMP probe keys on its own field).
  Kept on disk, not used.
- smoke2/ (10:34-10:36), same launcher: GPU check PASS. Both: resumed_from None,
  opt_steps_at_start 0, train N 21532, DataLoader 337, fp16, autocast True, denoiser
  float16, non-finite 0, skipped 0, stopped at 100. step100.ckpt reloaded from disk: PASS --
  opt_steps = EMA count = scheduler = 100, AdamW step histogram {100: 299} (no CPU-alias race),
  LR 1.5e-5 / 1.5e-6 (warmup), scale 65536, init checksum G1 a4cd264f / G2 ab5362b5.
  G1 batch [64,2,3,224,224], 197 tokens; G2 [64,2,3,176,288], 199 tokens; global_cond [64,1568]
  both. Batch fingerprints: G1 vs G2 identical on eef_pos, action and the start-pose-noise obs
  for 100/100 batches; smoke2 G1 vs smoke G1 identical too (order reproducible run to run).
- Note: W&B syncs these runs to the project's wandb.ai workspace despite WANDB_MODE=offline --
  the config's logging.mode=online is passed to wandb explicitly and wins. The definitive v2
  run did the same (its log shows the sync); config left as is.

## 10:36 Production training started, parallel (launch_production.json)
G1 pid 1015383 on physical GPU 0 -> sim_umi/train_results/2026-09-27_fov_g1_letterbox224;
G2 pid 1015384 on physical GPU 5 -> sim_umi/train_results/2026-09-27_fov_g2_rect288x176.
Fresh shared init (G1 a4cd264f, G2 ab5362b5), resume False, 11400 updates, checkpoints
5985/5986/8000/10000/11400, dataloader_seed 42, fingerprints for 300 batches. GPU check PASS.
No rollout, evaluation, camera rendering or simulator diagnostic of mine runs until both
are complete; the simulator keeps its own idle rendering on GPU 0 (user's decision).
While training: G2 server path checked on CPU with the smoke2 G2 checkpoint -- sidecar g2,
176x288, eval CenterCrop(167,273)+Resize(176,288), dumped encoder input exact; a 224x224
request to the G2 server is refused (empty answer, "inference failed" logged).

## Pre-registered BEFORE the G0 regression runs: what counts as "meaningful"
Reference (definitive v2_11400): nominal n=5 corridor 3, LIFT 3, bin 2, abort 2;
perturbation n=16 corridor 5, LIFT 10, strict 8, bin 4, abort 7; infra-invalid starts
v2_val 11 and 13 only. Rollouts are not bitwise repeatable (timing), so the rule is:
PASS if the infra-invalid set is exactly {11, 13} (val18) and {} (nominal), and every one
of corridor / LIFT / strict / bin / abort is within +-1 of the reference on nominal and
within +-3 on the perturbation set, and per-plan inference latency is not visibly shifted
by the added per-plan ground-truth render. Otherwise STOP before G1/G2 and find the cause.
Whatever G0 moves by here is also the noise floor the G1/G2 differences are read against.

## 11:56 / 11:58 Both trainings complete (G2 11:56:20, G1 11:58:21); all checkpoints PASS
Both: opt_steps 11400, skipped 0 (G0 v2 had 1), non-finite 0, stopped by max_opt_steps,
resumed_from None. Every step checkpoint reloaded from disk (audit_checkpoint.py):
5985 / 5986 / 8000 / 10000 / 11400 all PASS in both runs -- opt_steps = EMA count =
scheduler = N, AdamW histogram {N: 299}, LR = the schedule (1.8550e-4, 1.8546e-4,
8.6860e-5, 1.6122e-5, 0), init checksum G1 a4cd264f / G2 ab5362b5; final scaler 2097152.
Production batch fingerprints: G1 vs G2 identical for 300/300 batches (eef_pos, action,
start-pose-noise obs). Final train loss G1 0.0127, G2 0.0122 (last logged batch).
After exit: no train.py process left, GPU 5 at 1 MiB, GPU 0 at the simulator's 244 MiB.
Only now does evaluation start (phase g0: G0 regression).

## 12:24 G0 regression, evaluator v1 -- FAIL under the pre-registered rule; G1/G2 not evaluated
Evaluator v1 = run_eval_fov_v1_inpath_instrumentation.sh + commit 6331d00 (outputs in
sim_umi/eval_results/2026-09-27_fov/ top folder). Result vs definitive v2_11400:
nominal corridor 3->3, LIFT 3->3, strict 1->1, bin 2->0 (OUTSIDE +-1), abort 2->3;
perturbation corridor 5->7, LIFT 10->14 (OUTSIDE +-3), strict 8->10, bin 4->6, abort 7->7;
infra-invalid {11, 13} as before. Episode agreement with definitive, per metric:
nominal 3/5 (abort 2/5); perturbation 12/16 (abort 10/16).
Cause looked for in the logs (no new rollouts): request latency median 0.215 -> 0.238 s
(nominal) and 0.220 -> 0.232 s (perturbation) -- my instrumentation sat on the critical
path: a ground-truth render before every inference request (~15-20 ms) and the server's
encoder-input dump before its reply (a further ~18 ms on every 10th request). Sent-waypoint
and stale-drop averages were unchanged, but outcomes flipped in both directions.
The user's reading, adopted: in a rolling executor with a 10 Hz horizon, asynchronous
inference and stale discarding, ~20 ms moves which waypoints make the next plan, so the
closed-loop trajectory branches differently; giving the same delay to G0/G1/G2 would be
fair but would evaluate a different runtime contract. Delay removal comes first.

## 15:10 Evaluator v2: nothing added between an observation and its action (57dd304)
FOV masks are rendered after the rollout (fov_postprocess.py; the loop records only the
bin's pose, a message lookup); G0's image path is preprocess_rgb alone (no canvas); the
server writes its dump after the reply. Static tests (preflight/08_*): reply received
+0.343 s, dump file +0.370 s; a dumped request answered in 0.343 s as one without.
Live smoke, G0 nominal episodes 0 and 1 (r2_offpath_smoke/): request latency median
0.216 s / p90 0.238 (definitive 0.214 / 0.234; v1 0.236 / 0.259); stale-dropped mean
5.01 (definitive 5.02). Latency restored.

## Pre-registered BEFORE the v2 G0 re-evaluation (r2_offpath/)
"Recovered" = the earlier aggregate rule passes (nominal +-1, perturbation +-3 on
corridor / LIFT / strict / bin / abort; infra-invalid exactly {11, 13}) AND episode-level
agreement with definitive on object_lifted, bin_success and unreachable abort is >= 4/5
(nominal) and >= 12/16 (perturbation) each. Recovered -> freeze evaluator v2, evaluate G1
then G2 once each. Not recovered -> report before G1/G2 and move to a repeated-evaluation
design.

## 15:42 G0 re-evaluation, evaluator v2 (r2_offpath/) -- NOT "recovered" under the pre-registered rule
Latency restored: request median nominal 0.220 s (definitive 0.215), perturbation 0.220
(0.220); stale-dropped 5.00-5.01 as definitive. Counts definitive / v1 / v2:
nominal corridor 3/3/2, lifted 3/3/4, strict 1/1/0, bin 2/0/1, abort 2/3/4 (+2, outside +-1);
perturbation corridor 5/7/5, lifted 10/14/10, strict 8/10/6, bin 4/6/4, abort 7/7/7.
Episode agreement with definitive (v2): nominal lifted 4/5, bin 4/5, abort 3/5 (< 4/5);
perturbation lifted 10/16 (< 12), bin 12/16, abort 8/16 (< 12). v1 vs v2 (two reruns of the
same checkpoint): perturbation 10-12/16 per metric.
Interpretation: removing the delay brought the perturbation AGGREGATE back to definitive
almost exactly, but individual episodes still swap outcomes both ways (e.g. ep0 CLSB -> .,
ep3 . -> CLSB, ep15 CLSB -> a). The closed loop itself branches from run to run -- the
policy is deterministic given its input (--deterministic, re-seeded per request), but frame
and joint-state arrival and inference timing are not. Single evaluations therefore cannot
resolve a difference of a few episodes; this also bears on the definitive single-run
comparisons (e.g. nominal abort 4/5 vs 2/5 between v2 checkpoints lies inside what G0 alone
now shows: 2, 3, 4). Per the user's instruction: G1/G2 not started; reported; proposed a
repeated-evaluation design (3 runs per variant; definitive + v2 count as two G0 runs).

## 16:00 Timing dependency of the G0 rollouts, from logs (preflight/09_timing_dependency.*)
Purpose: before any FOV comparison, find what makes two rollouts of the same checkpoint and
episode part (user's hypothesis: the first executed action index shifts with latency).
Data: definitive, evaluator v1, evaluator v2 runs of v2_11400 (1541-1767 plans each).
Result:
- First executed waypoint k*: 5 in 95% of plans (def 1673/1767; v2 1431/1541); slack to the
  drop boundary median 60 ms, < 20 ms in 0.7% (def) / 0.6% (v2). v1's latency cut the slack
  to 46 ms (< 20 ms in 7.4%, 12 plans at k* = 6). k* mean 5.00 in lifted and not-lifted
  episodes alike; k* differs in the 4 plans before two runs part in 5/63 run pairs. Before
  GRASP in every outcome-flipping pair examined, k* = 5,5,5,5,5 in both runs. The
  hypothesis (k* shift) is not what separates runs here.
- Observation frame-pair spacing (obs horizon 2): TRAINING rows are 0.100 s apart in image
  time (99th percentile 0.100; 66 of 23132 over 0.105). EVALUATION (v2): 0.100 s in 63% of
  plans, 0.150 s in 24%, 0.2 s 5%, 0.3-0.45 s 7%. The executor takes a frame, waits 0.1 s of
  WALL clock, takes the newest frame; on a 20 Hz camera that lands one or more frames late.
  With relative-pose observations a 0.15 s pair reads as 1.5x the motion the policy was
  trained on. Present in every evaluation so far, definitive included.
- Two runs of the same episode part (> 2 mm observed tool position) in 63/63 pairs, at plan
  6 median (t = 3.5 s), stage APPROACH in 51, SEARCH 6, GRASP 6 -- well before any grasp.
  Outcome-flipping pairs close at different geometry (e.g. val ep3: def depth +3.1 /
  vertical -23.3, v2 -11.2 / +4.3) even where the pre-GRASP spacing sequence was the same
  (val ep10), i.e. the trajectories had already diverged.
Interpretation: the evaluator is timing-dependent through its OBSERVATIONS (wall-clock frame
pairing, off the training contract in ~37% of plans), not through action indexing; small
early input differences grow into different closes. Evaluation runtime determinism must be
fixed before a representation comparison (user's conclusion, adopted). Proposed: (1) pair
observation frames by simulation stamp exactly 0.1 s apart from a buffer; (2) a
simulation-time deterministic evaluator (pause during inference, apply actions at fixed
sim timestamps) if the simulator stack allows it -- to be checked first.

## 16:05-16:35 Observation timing contract, minimal fix (user's instruction: obs contract first)
Purpose: make every policy observation obs[0] = frame(t - 0.100 s), obs[1] = frame(t) by
SIMULATION stamp, with the joint state of each image aligned to that image's stamp, without
touching the action side (rolling executor, absolute action stamps, latency compensation,
k*, stale discard, prefix, jaw scheduler, policy server, inference steps, realtime sim).
Control: definitive v2_11400 nominal episodes 0,1 (latency median 0.214, k* = 5 in 187/189,
stale 5.02, slack median 66 ms; obs_dt 0.100 s in only 115/197 plans).
Iterations (all G0 nominal episodes 0,1 smokes, kept in their own subdirs):
- r3_obsfix_smoke (f2f983c): frames picked from a buffer by sim stamp. obs_dt 0 in 10 plans --
  a dropped frame left no frame at t - 0.1 and the nearest was reused. Not silently
  accepted; fixed next.
- r3b_obsfix_smoke (ffc0e76): if [t-0.1, t] is not both in the buffer, wait for the next
  frame (counted: obs_extra_wait_frames). obs_dt 0.100 s in 211/211, pairs exact 211/211;
  latency 0.220, k* 5 in 202/203, stale 5.03, sent 7.65 -- action side unchanged. BUT the
  joint state at t - 0.1 was interpolated across a 292 ms bracket (median; max 414) in
  204/422 frames: the main loop takes no callbacks during collect()'s IK (~200 ms), so the
  keep-last-1 joint-state subscription has a hole exactly there. Not acceptable as "aligned".
- r3d_obsfix_bg_smoke (025c1aa): a background thread in the rollout process buffering every
  joint state. States exact 254/254, but the thread's 455 Hz callbacks slowed the loop's IK
  through the GIL: collect() 724 ms median (vs ~210), request latency 0.240 / p90 0.277,
  k* = 6 in 10/127 plans, stale 5.13. The ACTION side changed -> rejected.
- r3e_obsfix_recorder_smoke (abc9201): joint states kept by a SEPARATE process
  (sim_umi/ros/state_recorder.py, unix socket lookup exact/interp/nearest; 2 lookups per
  plan). Result: obs_dt 0.100 s 212/212, pairs exact 212/212 (extra wait: 1 frame in 1
  plan, 2 frames in 16), states exact/recorder 424/424 (image-state skew 0, no interp, no
  nearest), latency median 0.210 / p90 0.224 (def 0.214 / 0.234), k* = 5 in 191/192 (the
  other: 11, as def's 10), stale 5.03 (5.02), slack median 66 ms / q05 52 (66 / 42), sent
  in plans without unreachable waypoints 7.95 / 8.00 (def 7.93 / 8.00), collect() 210 /
  266 ms per episode. Outcome ep0 SUCCESS, ep1 failed (not a criterion for a smoke).
  Per-plan provenance present: frame stamps (requested/used, exact flag), obs_dt,
  joint_stamp, image-state skew, state mode+source, req_id, request send/recv wall, collect
  start/end wall, send end wall, latency, k*, sent prefix.
Interpretation: the observation contract now holds exactly with the action-side timing
statistics as definitive. Smoke PASS -> G0 x2 repeats.

## 16:38 Pre-registered BEFORE the G0 x2 repeats (r4_obsfix_rep1/, r4_obsfix_rep2/, evaluator abc9201; runs started 16:39)
Same checkpoint (definitive v2_11400), nominal 5 + perturbation val18 (valid 16, 11/13
infra-excluded as before), run one after the other on the same GPUs.
"Converged" (the two repeats against EACH OTHER) =
  (a) contract held in both: obs_dt 0.100 s and pairs exact in every plan, every state
      exact or interp with bracket <= 10 ms, no nearest -- any exception counted & listed;
  (b) aggregate difference within nominal +-1 / perturbation +-3 on corridor, LIFT, strict,
      bin, abort, and infra-invalid set exactly {11, 13} in both;
  (c) episode agreement rep1 vs rep2 on object_lifted, bin_success and unreachable abort
      >= 4/5 (nominal) and >= 12/16 (perturbation) each.
Descriptive, not criteria: first plan whose policy input (image + lowdim hash) differs
between the repeats, first plan whose observed tool position differs > 2 mm (before the fix:
63/63 pairs part, plan 6 median, t = 3.5 s), selected obs stamp / obs_dt / k* sequences,
first-close geometry, and agreement with definitive (definitive was off contract, so
disagreement with it is expected).
Converged -> freeze evaluator abc9201, evaluate G1 then G2 (only after reporting).
Not converged -> hold G1/G2; design (not implement) a deterministic sim-time evaluator
that keeps the [t-0.1, t] contract and does not zero action age; report first.

## 17:05 Separate root cause, ACTION side: goals are timed against a stale node clock (recorded, not changed)
Found while auditing for the deterministic-evaluator design; the running G0 repeats are
left exactly as registered (evaluator abc9201), and this is NOT fixed in this step.
Path (rolling_executor.py send()):
  collect() starts: node now() = newest /joint_states stamp the main node has received = t
  -> fut.result(), decode, IK projection, plan build: the main loop does not spin, so no
     /joint_states and no /clock are processed; now() stays t
  -> send(): now = self.now() (still t); time_from_start = t_send - now for each waypoint;
     trajectory header.stamp left 0 (JTC: start when it takes the goal)
  -> JTC takes the goal at the real sim time t + S and waits the full relative durations
  => every sent waypoint executes ~S later than its intended absolute time t_send.
Measured (r3e smoke, 192 plans): node clock advance between collect() and send() 0.0000 s
(median and max); wall collect-start -> goal accepted median 0.262 s, p90 0.373, max 0.551;
plant real-time factor between requests 0.999 (q05 0.962, q95 1.036), so S ~= that wall
interval in sim time. S varies plan to plan with wall timing (IK, GIL, scheduling).
Relation to k*: separate. k* (first kept waypoint) comes from collected_at = obs_t + L
(L = request latency; k kept iff 0.1k - 0.21 > L + 0.01, so k* = 5 for 0.18 <= L < 0.28,
which holds in ~95% of plans). S shifts the EXECUTION timeline of whatever was kept; it
does not enter k*. It is present in every evaluation so far, definitive included.
Consequence for the repeats: the observation fix removes the obs-side timing variation
only; S remains a plan-to-plan variable action-side source. If the repeats still part,
the deterministic sim-time evaluator must fix S too (user's instruction), after a JTC
header.stamp / time_from_start audit -- no header.stamp or k* hard-coding before that.
Also found (design input): two different smoke runs already differ at plan 0 -- joints
<= 0.001 deg, tool position 0.1-2 um, 80-437 edge pixels of 57,600 (max |d| 49) -- the
realtime start (HOME held by the controller) is not bitwise identical. Not treated as a
bug; to be tested for whether it causes divergence under the deterministic evaluator.

## 17:45 G0 x2 repeats with the observation fix (r4_obsfix_rep1 16:39-17:01, rep2 17:01-17:25) -- NOT converged
Evaluator identical in both (git diff 48db6d3..9376944 touches only this journal and the
offline repeat_compare.py). Aggregates: r4_obsfix_rep{1,2}/aggregate_G0.json; plan-by-plan
comparison: r4_repeat_compare.{md,json}.
(a) contract HELD in both: obs_dt 0.100 s in 1458/1458 and 1525/1525 plans, pairs exact,
    frames exact; states exact/recorder 2916/2916 and 3049/3050 (1 interp <= 10 ms);
    no nearest. Extra frame waits: rep1 18% of plans, rep2 58%.
(b) aggregate rep1 vs rep2: nominal corridor 2/3, lifted 2/3, strict 1/0, bin 0/3 (+3,
    outside +-1), abort 4/2 (outside +-1); perturbation corridor 6/4, lifted 10/10, strict
    7/6, bin 5/3, abort 8/9 (all within +-3); infra-invalid {11, 13} in both. -> FAIL (nominal)
(c) episode agreement: nominal lifted 4/5, bin 2/5 (<4), abort 1/5 (<4); perturbation
    lifted 12/16, bin 14/16, abort 11/16 (<12). -> FAIL
Descriptive:
- The policy input already differs at plan 0 in 21/21 episode pairs: 27-833 of 57,600
  pixels per frame, lowdim max |d| 1e-6 (one 9.7e-5), tool position 0.001-0.010 mm.
- Selected obs stamps (relative to the episode's first) differ from plan 1 in 21/21: obs_dt
  is 0.100 everywhere, but WHEN the next pair is taken follows the goal/IK timing.
- Tool position apart > 2 mm first at plan 3 median (1-12); before the fix, run pairs parted
  at plan 6 median. Not later.
- k* first differs late (plan 8-126) or never; k* = 5 in 94-99.7% of plans.
- Stale-clock interval S' (collect start -> goal accepted, wall; RTF 0.999): rep1 median
  0.265-0.279 s / p90 0.35; rep2 0.225-0.296 / p90 0.36-0.40. Plan period median 0.55 s
  (rep1) vs 0.60 (rep2).
- First close differs, e.g. nominal ep3 depth -4.1 vs -13.5 mm; val ep3 onset 8.3 vs 35.0 s;
  val ep10 depth -20.6 vs -12.3.
- Agreement of each repeat with definitive (off-contract) is at the same level as the
  repeats with each other (perturbation lifted 12/16 both; bin 13 and 15).
Caveat: from 17:12 another user's llama-server (j-j15a202, ~20 cores, GPU 6) ran during
rep2 val18: k* = 5 94.2% vs 98.6%, S' p90 0.400 vs 0.356. rep2 NOMINAL ran before it
(17:01-17:06) and already fails (b) and (c), so the verdict does not rest on it; rep2's
extra frame waits were high in nominal too (63% vs 8%), cause not established.
Interpretation: fixing the observation contract makes each observation exactly right but
does not make the closed loop reproducible: two runs differ from the first observation
(start state) and the action timeline (S', replanning cadence) varies plan to plan; the
loops part within ~1.5 s. Per the user's rule: no further asynchronous repeats, G1/G2
stay on hold, next is the JTC timing / pause-step audit and the deterministic sim-time
evaluator design (report before implementation).

## 18:15 Pre-registered BEFORE the G1/G2 rough screening (r5_screen_g12/, asynchronous evaluator abc9201)
User's instruction: while the GPU is idle, G1 and G2 once each on the CURRENT asynchronous
evaluator, for candidate SCREENING ONLY -- never recorded as a definitive FOV result, no
winner from a 1-2 episode difference. Policy on physical GPU 5 only; no sim/JTC step
audit while it runs. Condition note: another user's llama-server (~20-30 cores, GPU 6)
has been running since 17:12 (load average ~30 at launch vs ~3 during G0 rep1).
Reference = spread of the five G0 asynchronous runs (def, v1, v2, rep1, rep2):
  perturbation valid16: corridor 4-7, lifted 10-14, strict 6-10, bin 3-6, abort 7-9,
                        first-close median depth -13.0..-10.7 mm, vertical 5.6..7.8 mm
  nominal 5:            corridor 2-3, lifted 2-4, strict 0-1, bin 0-3, abort 2-4,
                        median depth -12.4..-9.5, vertical 5.9..10.3
A variant counts as "obviously different" (-> provisional baseline candidate) only if ALL:
  1. perturbation lifted AND bin both outside the G0 range by >= 2 episodes beyond the
     nearest bound, in the same direction (better: lifted >= 16 and bin >= 8; worse:
     lifted <= 8 and bin <= 1), and abort not moving the other way;
  2. nominal not outside the G0 range in the opposite direction;
  3. first-close median depth or vertical (perturbation) beyond the G0 range of medians by
     >= 3 mm, or the same direction of change visible episode by episode;
  4. a consistent qualitative difference in trajectory / LIFT / bin behaviour in the
     per-episode table (described, not scored).
Otherwise "similar": no provisional selection; wait for the deterministic evaluator,
then G0/G1/G2 formally under identical conditions.

## 17:44-18:10 Isolated pause/step and JTC timing audit (dse_audit/; plant paused only during the test)
Purpose: before any deterministic evaluator, establish (1) JTC 4.42.1 header.stamp /
time_from_start semantics, (2) whether paused one-step stepping gives a fixed command
offset, separating real controller-update skips from mere message loss by the SIMULATOR
state, not by topic presence. Tools: sim_umi/scripts/dse/step_audit.py (v1 17:44, v2 with
/mujoco_actuators_states 17:55/18:05), analyze_step_audit.py. JTC source = ros2_controllers
4.42.1 (installed header identical to the fetched one).
Method: ResetWorld to HOME (free bodies to initial poses, jaw as it stood) with a hold goal,
100 settle steps, then a joint1 +0.10 rad goal; one StepSimulation(1) per tick (A, and A0 with
no wall settle) or 5 per call (A5); 2-3 repeats. The command actually in effect in each
physics step is inverted from the simulator's own state: u_i = (qfrc_i + kp q_{i-1} +
kv qd_{i-1}) / kp (joint1 position servo, kp 50, kv 4.86944 -- fitted from the data, equal
to the compiled model; |force| below the 3.5 limit).
Results:
- Semantics (v1, code agrees): stamp 0 -> starts at the first controller update after the
  goal is installed (2.0 ms = next tick); future stamp -> spline from the current state to
  the first point at its absolute time; past stamp with a future end -> accepted, samples
  the segment containing now (no interpolation from the current state); end in the past ->
  rejected (D: 2/2).
- Offset: wherever observable (~490 ticks per repeat, 7 repeats), the command in effect in
  step i+1 equals update i's output exactly (residual <= 2.2e-16): offset 1, always.
- Controller-manager cycle absent (controller_state AND actuator_states both missing) on
  24 ticks; they are EXACTLY the ticks whose /clock delta is 1,999,999 ns (24/24, single and
  5-step stepping; the audit node received every /clock tick). Mechanism: the cm loop sleeps
  until clock >= previous + 2,000,000 ns; sim time accumulates 0.002 in floating point and
  /clock is floored to ns, so every ~146 ticks (at t ~ 68,000 s) a tick is 1 ns short and the
  cycle waits for the next one (the following update reports a 3,999,999-ns period). Real
  skipped updates, deterministic in absolute sim time, at different episode-relative ticks in
  each repeat.
- Message loss only: 2 ticks (A5 repeat 1, 282-283): controller_state missing, actuator_state
  present, and a new command was in effect in the next step -> the update ran.
- Physics across repeats: all joints' q and qd bitwise identical from the reset until the
  first skip during the move (skips during the hold change nothing: same command); from the
  next tick on they differ, max |dq| 4.5e-6 rad over the 0.8 s move. ResetWorld + paused
  stepping itself is reproducible.
- Goal installation race: A0 repeat 0 -- the hold goal and the move goal were installed
  ~334 ms (167 ticks) late although acceptance had been received and 50 ms of wall time had
  passed. rclcpp_action sends the acceptance before running the JTC's accepted callback that
  writes the trajectory; under the present CPU load that callback can lag. A stepping
  evaluator must confirm installation before stepping, not wait a fixed wall time.
Correction: an earlier line to the user said 5-step batches broke the skip/clock coincidence;
that came from an analyzer bug (it counted 80 ticks for 400 steps). Fixed; coincidence holds.

## 18:25 DSE design reported (DSE_DESIGN.md, 4889d7a); user's decisions recorded in its section 13
A (no stale-clock delay, L_v 0.216), cadence from the existing rule (recorded, not fixed),
perturbed start by ResetWorld direct set (primary = paired valid 16; ep11/13 secondary),
500 Hz kept and the 1-ns-short-tick skip validated rather than removed. Implementation
starts in code only while the G1/G2 screening occupies the plant; plant-side checks
(per-tick wall cost, EXECUTING as installation signal, stream-gap diagnostic) after it.

## 19:20 G1/G2 rough SCREENING (asynchronous evaluator abc9201; r5_screen_g12/) -- no provisional selection
Screening only, NOT a definitive FOV result (user's rule). Runs 18:13-19:01, policy on
GPU 5; another user's llama-server loaded the CPU throughout (load average 25-31).
Counts C / L / S / B / abort (screen_g12.md):
  perturbation valid16: G1 4 / 10 / 6 / 3 / 7;  G2 4 / 8 / 4 / 4 / 10;  G0 range (5 runs)
                        4-7 / 10-14 / 6-10 / 3-6 / 7-9
  nominal 5:            G1 2 / 3 / 3 / 1 / 3;   G2 0 / 2 / 1 / 1 / 2;   G0 range 2-3 / 2-4 / 0-1 / 0-3 / 2-4
  first-close median (perturbation): G1 depth -11.8 / vertical 6.2; G2 -14.7 / 5.6;
                        G0 medians -13.0..-10.7 / 5.6..7.8
Registered rule: (1) lifted AND bin outside the G0 range by >= 2 in one direction -- G1 no;
G2 lifted 8 (2 below) but bin 4 inside -> no; (3) close shift >= 3 mm -- neither.
-> Both "similar": no provisional baseline; wait for the deterministic evaluator.
Noted, not concluded: G2 leans worse on perturbation (lifted 8, strict 4, abort 10 -- each
1-2 outside the G0 spread) and has nominal corridor 0; G1 nominal strict 3 (G0 0-1).
Episode outcomes flip between G0 runs as much as between variants (screen_g12.md table).

## 19:25 Camera capture ticks under paused stepping (dse_audit/camera_1/, camera_step_test.py v2)
Purpose (user's criterion): does each EXPECTED capture tick equal the ACTUAL one, and are
capture ticks identical across repeats -- not "did a frame eventually arrive".
Expected = the plugin's own rule with a caught-up clock (first controller-cycle tick c with
c - last capture >= 50,000,000 ns). From a reset to HOME, 250 ticks per run, twice per mode.
Results (capture ticks relative to the reset):
- 1 step per call (+ waiting at each capture tick): expected == actual in both runs (21/21,
  10/10). Intervals 25 ticks, 26 where a 1-ns-short tick falls inside.
- 5 per call: run 1 actual one tick LATE from the 4th capture on (96 -> 97, then shifted);
  run 2 equal.
- 25 per call: run 1 one tick EARLY from 176; run 2 missed the capture due at tick 1
  entirely (next at 25), then realigned. -> fast stepping changes the capture tick itself
  (the plugin decides on its node clock inside the controller cycle); a barrier after the
  fact cannot restore it and it is not counted as recovered.
- Repeats: capture ticks relative to the reset differ in every mode (e.g. 1-step runs
  [19, 44, 69, ...] vs [18, 44, 69, ...]): the camera chain continues through ResetWorld from
  wherever it was (prior capture at -6 vs -7), and the 1-ns-short ticks that stretch an
  interval to 26 sit at different episode ticks in each repeat.
Interpretation: under the current plugin the capture schedule is a function of absolute
sim time and of in-process clock delivery, so identical observation ticks across repeats
are not reachable from outside the plant. Per the user: report a plugin-side design
(deterministic sim-state trigger) before changing anything.

## 19:30-19:48 Camera plugin patched (sim-state trigger + paired joint snapshot); simulator restarted
User-approved (19:33): one rebuild / restart for both. Patch: sim_umi/ros/overlay_patches/
camera_sim_state_trigger.patch (camera_plugin.cpp/.hpp only, +127 lines; overlay source
58f465b + patch). `trigger: sim_state` captures in pre_step (physics thread, live mjData)
every 25th physics step from the last world reset (on_reset zeroes the counter) and
publishes /wrist_camera/joint_snapshot (sensor_msgs/JointState, 7 joints) from the SAME
snapshot with the SAME stamp; a render-busy flag makes a capture wait for the previous
render, so no snapshot is overwritten or dropped. Default `node_clock` = original
behaviour. /joint_states, ros2_control and controller feedback untouched. DSE config:
sim_umi/ros/config/mujoco_plugins_dse.yaml via OMX_MUJOCO_PLUGINS (mujoco_bringup.launch.py
default unchanged). Old bringup stopped 19:39:22 (SIGINT), plugin rebuilt (colcon,
mujoco_ros2_control_plugins only, 17 s), bringup relaunched with the DSE config; the three
controllers active; the sim still renders on GPU 0. Sim time restarted near 0.
Checks, realtime: 20.0 Hz, every image interval 50.0 ms, 56/56 images with a snapshot of
identical stamp.
Camera test, sim_state (camera_2 and camera_3, 1 / 5 / 25 steps per call, twice each):
expected (reset + 25k) == actual in 12/12 runs; capture ticks identical across repeats in
every mode; snapshot stamp == image stamp 10/10 per run; snapshot q == controller-cycle q
bitwise in 9/10 per run -- the 10th is tick 0, the reset tick, whose controller cycle ran
BEFORE the reset (pre-reset state), expected and not a defect.
Per-call wall time (camera_3; median / p90 / max): 1 step: service 2.4 / 3.8-472 / 369-6973 ms;
5 steps: service 8.0-8.6, clock wait 3-4, total 12-13 ms (2.4-2.6 ms per tick); 25 steps:
service 33-34, clock wait 20-24 (the /clock publisher trails the physics ~1 ms per tick),
total 55-57 ms (2.2 ms per tick). The earlier ~100 ms per tick was not the service round
trip: it was the old DSE camera tracking waiting 50 ms per step. Scattered 0.1-7 s service
stalls (75/250 calls > 50 ms in one run) coincided with the other user's CPU load (load
average 13.9 -> 2.6 as it ended); they cost wall time only -- the plant is paused.
Note: no 1-ns-short ticks since the restart (sim time small); they return as time grows.

## 19:50-20:18 G0 rep run A: gate fail and stall; canonical-reset state test (15-min timebox) -> two causes
Run A (r1_g0rep_A, ep 0,1): ep0 hard gate FAIL (old_plan_ran_through_Lv 46/47) with one
1-ns-short skip at tick 6876 -- outside every L_v window, so not the skip; the failing plan's
record was lost because ep1 then stalled (the capture schedule counted RECEIVED /clock
messages; one missing -- /clock is try-published -- shifted it by a tick and every later
capture waited out its 2 s barrier) and the JSON was only written at the end. Stopped 20:10;
plant unpaused. Fixed (cd63146): schedule in ISSUED steps from the reset stamp, missing
/clock recorded as an anomaly (the controller manager may miss that tick too), JSON after
every episode, a JTC hold after the old trajectory's last point allowed and counted.
Runs A vs s3 (same ep0, before any skip): arm q bitwise equal until the first takeover (tick
410), but the plan-0 RGB differed (69 / 351 px) -> policy output differed from plan 0.
Canonical-reset test (dse_audit/reset_state_{1,2,3_prior}; ResetWorld twice, 310 ticks one
step per call, also from different prior histories): all 7 joints (incl. coupled finger 2)
q / qd bitwise equal at all 13 captures; ball pose/twist equal; bin equal to 1e-16 (compared
at different message ticks); RGB differs by <= 3 px of 1 level, always at the same pixels
(rows 81-82 / cols 270-279, row 111 / col 164), also at the reset tick itself.
Cause 1 (the 69 / 351 px): each DSE run has ONE of its two first frames identical to the
test's frame of that tick (0 px) and the other differing by exactly those counts -> stamp
right, content one tick off. While paused with no pending step the physics loop runs
mj_forward every iteration (render positions follow qpos); steps queued back-to-back (a
5-step call) have no idle mj_forward between them, so the pre_step snapshot's xpos is the
previous tick's. Which one a capture gets depends on WALL timing of the step requests; the
joint snapshot (qpos) is always tick t, so image and state can also be a tick apart.
Proposed fix (not applied; needs another rebuild / restart): recompute the snapshot's
kinematics (mj_kinematics + mj_camlight) at capture.
Cause 2 (the <= 3 px, 1 level): identical state, different RGB -> renderer nondeterminism;
removing it needs a renderer-side change -> recorded as a BLOCKER for bitwise equality.
Per the user's rule: no G0 full / repeat rollout until the plan-0 observation reproduces.

## 20:20-20:40 Capture kinematics fixed (dd5b409); renderer noise judged on the policy
Approved by the user. The sim_state capture now runs mj_kinematics + mj_camlight on this
tick's qpos before snapshotting (patch file updated), so the image is tick t whatever the
step batching. Rebuild 17.7 s; restart: SIGINT did not bring the old bringup down, and a
second instance was briefly launched on top (camera 40.9 Hz) -- both stopped with SIGTERM,
one instance relaunched (controllers active, camera 20.0 Hz, sim renders on GPU 0).
A test-harness artifact was found and fixed on the way: right after a pause the node still
held queued realtime /clock messages, so the "reset tick" read too early (101 ticks) and
pre-reset frames entered the window. A /clock drain barrier after pause / reset (until 0.3 s
with no new tick) now precedes any reading of the current tick -- in the DSE too.
Verification (reset_state_4_batch25, reset_state_5_batch5; rep0 one step per call with
idle mj_forward = tick-t content, rep1 5 or 25 steps back to back): capture ticks identical,
all 7 joints bitwise equal at 13/13 captures, RGB difference <= 4 px / <= 2 levels at every
capture (renderer noise only) -- the t / t-1 (69 / 351 px) difference is gone; RGB and joint
snapshot are the same tick.
Renderer noise on G0 (render_noise_policy_test.py, policy server on GPU 5, identical low-dim,
5 render pairs of identical states): raw action max |d| <= 1.2e-7 (0 where the inputs were
equal -- the policy is deterministic), decoded position <= 7.4e-5 mm, gripper <= 7e-6 mm,
IK reachability of all 16 waypoints unchanged, jaw change <= 2e-6 of the 3 mm send
threshold, camera width identical (52.01 mm). Several noise pixels lie outside G0's centre
crop. -> Recorded as a TOLERATED renderer artifact (user's criterion); no renderer change.
Next: G0 ep0 x2 in the DSE (initial observation / timeline / trajectory reproducibility).

## 20:31-20:45 G0 ep0 x2 in the DSE (r2_ep0_rep1 / rep2, capture fix in place) -- initial observation reproduced, trajectory not
Stopped after the two runs, per the user; reported.
- Plan-0 policy input AND output bitwise identical in both runs (first difference: plan 1).
  Observation frame ticks and obs_dt identical wherever both runs had plans; every frame
  paired with its joint snapshot (rgb_snapshot, skew 0).
- Controller output identical until the first takeover (tick 409), then differs by 3.7e-12
  rad, growing linearly (7.4e-12 at 410, 2.2e-10 at 450); simulator state differs from tick
  410; the loops then part: outcomes 39 actions / grasped / LIFT vs 105 actions / not grasped
  (both ended by eight unreachable plans). No controller-cycle skip in either run.
- Cause (plan 0, identical plan and waypoints): time_from_start is computed from ABSOLUTE
  sim times in floating point (t_send - start); the two runs sit at different absolute times
  (plan-0 observation 0.600000000 vs 0.599999999 s after their resets as floats), so tfs
  differs below the ns and the JTC spline timing with it. Also the executor's 10-us tick
  tolerance leaked into the goal start (first tfs 0.07199 instead of 0.072 s).
  Proposed fix (not applied): tfs from integer tick counts relative to the observation tick
  (k*50 - 105 - (L_v ticks + 1)) x 2 ms, exact in every run; no tolerance in the start.
- Gate: rep1 FAIL on one plan (plan 40, old_plan_ran_through_Lv), rep2 PASS. In rep1 the
  plan in flight (plan 38, 5 points) ended at tick 6346 inside plan 40's L_v window
  (6300-6408); the JTC then holds the last point (its success path, in the RT loop on sim
  time). The allowance did not classify it -- most likely the end-time estimate in the check
  (it adds one tick); restart ticks are not recorded yet, so not confirmed.

## 20:40-20:52 DSE on integer ticks (55ba046): G0 ep0 x2 (r3_ep0_rep1 / rep2)
Approved changes applied: time_from_start = (send tick - takeover tick) x PHYSICS_DT_NS, the
ticks derived from the executor's own durations (action 50, robot latency 105, gripper 70,
minimum lead 10, L_v 108 -- each checked to be a whole number of ticks), no tolerance; jaw
firing and waypoint retirement on integer ticks; the timeline gate records the in-flight
trajectory's end tick and the JTC restart ticks.
Reproduced now: plan-0 (to plan 4) policy input and output bitwise; the first command (send
ticks, takeover tick, target joints) identical; controller output identical to tick 1308,
state to 1309, tool position to 1424 (ticks after reset).
First divergence: tick 1309 = plan 6's takeover. Plans 5 and 6 observed at ticks 1050 and
1200 with the physical state still bitwise identical, but their RGB inputs differed by the
renderer's noise (plan 5's output happened to stay identical, plan 6's did not). From
there the loops part (tool up to 255 mm apart; 88 vs 94 actions, both grasped). The 1-ns
controller skips came later (rep1 tick 13108, rep2 tick 1777) and are not the cause.
-> The remaining nondeterminism is the renderer: ~1e-7 in the policy output (offline
measure), amplified by the closed loop over ~100 plans into a different trajectory.
Timeline gate: rep1 FAIL, 5 plans (78, 83, 87, 89, 90), each with its only restart exactly
ON the in-flight trajectory's end tick (e.g. end 12095 = restart 12095) -- the JTC reaching
its last point; none before the end. The rule as coded requires strictly after; whether
the end tick itself counts as "after the end" is the user's call. rep2 PASS.

## 20:53 Evaluator redefined as TIMING-CONTROLLED; G0 x2 residual-variance runs pre-registered (committed 412b25d before the runs)
User's decisions: restart_tick >= end tick is a normal hold (only < fails); the renderer is
not modified; the DSE is a timing-controlled evaluator, not a strictly deterministic one.
Runs (after a gate-passing smoke of this code): G0 v2_11400, nominal 5 + perturbation val18
(primary = the paired valid 16 of the definitive comparison; ep11/13, if valid under
ResetWorld starts, reported separately), twice: t1_g0_repA, t1_g0_repB.
Pre-registered "stable enough to compare G1/G2 on this evaluator" (the same thresholds the
asynchronous repeats were held to, for an apples-to-apples comparison):
  (0) every hard gate passes in every episode of both runs (else the run is not valid);
  (1) aggregate difference within nominal +-1 / perturbation +-3 on corridor, LIFT, strict,
      bin, abort;
  (2) episode agreement on object_lifted, bin_success and unreachable abort >= 4/5
      (nominal) and >= 12/16 (perturbation) each.
Reference: the asynchronous pair (r4 rep1 vs rep2) had nominal lifted 4/5, bin 2/5, abort 1/5;
perturbation lifted 12/16, bin 14/16, abort 11/16 -- it failed (1) and (2).
Stable -> G1 and G2 on the same conditions, 2 runs each. Not stable -> no FOV winner today;
the G1/G2 rough results stay provisional screening only.

## 21:04 Gate smokes before the G0 x2 runs (runs started 21:05)
s4 (412b25d): every gate passed except no_anomalies -- one /clock message missing (a 4-ms gap
at ~1605.955 s), and the controller cycle of that tick is ABSENT too: the plant's /clock is
try-published and a dropped message makes the controller manager skip that tick -- a
TIMING-DEPENDENT control skip (unlike the 1-ns-short ticks). Seen once in 58,899 ticks at
5 steps per call; never in the one-step tests. The gate caught it as designed.
s5 (b9bbb7c, the code of the runs; comment-only difference): every gate passes over 54,553
ticks (two 1-ns skips, no missing /clock). Gate marked for this code hash.
The G0 x2 runs keep the registered and validated configuration (5 steps per call); an
episode hit by a missing /clock fails its gate and, by criterion (0), makes that run
invalid for the G1/G2 decision -- counted, not hidden.

## 21:36 Replanning cadence corrected to the chunking contract (my design error); G0 x2 restarted
The user pointed out that replanning every 0.3 s cannot be right for a policy that predicts
16 steps and is meant to execute 6 (UMI eval_real.py steps_per_inference default 6 = 0.6 s at
10 Hz). Confirmed: with the stale-clock delay gone, the executor's "next frame after
delivery" rule collapsed to 0.3 s -- each plan commanded 3 points and only 1 waypoint
(median) retired while it was in flight (asynchronous runs: 0.55 s, 3 retired). I had
written "~0.35 s under A" into the design without flagging the conflict with the chunking
contract; decision 2 (rule-derived cadence) is superseded.
Fix: next observation tick = observation tick + steps_per_inference (6) x ticks_per_action
(50) = 300 ticks; L_v, k* rule, takeover and integer-tick tfs unchanged -> each plan commands
exactly k = 5..10 between its takeover (t + 0.218) and the next (t + 0.818).
The runs t1_g0_repA / B (0.3 s) were stopped at 21:34 (run A: nominal 5 done -- 0/5 grasped,
one gate FAIL; perturbation 4 done); kept as the record of the wrong cadence. The G0 x2 runs
restart with the same registered criteria (JOURNAL 20:53). Per the user, every nominal
episode is compared with the same episode of the 0.3 s run as it finishes.

## 21:39 Gate smokes at the 0.6 s cadence; G0 x2 launched with one step per call
s6 (80184aa, 5 steps per call): nominal ep0 SUCCESS (164 actions, 42 plans; APPROACH 80,
GRASP 12, LIFT 20, TRANSPORT 33, PLACE 19 ticks) -- the 0.3 s run's ep0 had failed (559
actions, 614 plans, never grasped, unreachable abort). Gate FAIL: one missing /clock again
(4-ms gap; the controller cycle of that tick absent), this time after 13,516 ticks -- far more
often than the one in 58,899 of s4. With back-to-back steps the plant's try-published /clock
drops ticks.
s7 (47b3d72, DSE_BATCH=1: one step per call): every gate passes, no missing /clock; nominal
ep0 SUCCESS (160 actions; identical stage ticks to s6 up to PLACE 15 vs 19; ball final
(40.1, -125.4) vs (40.2, -130.3) mm) -- 45.5 s wall. Gate marked for this code.
The G0 x2 runs use one step per call (DSE_BATCH=1), as the gated smoke did; the registered
criteria are unchanged (the step batching is a configuration of the stepping, needed for
criterion 0).

## 21:49 Run A nominal done; perturbation stopped (user); nominal repeated alone
t2_g0_repA nominal (0.6 s, one step per call): gates 5/5; bin 1/5 (ep0), grasped 4/5 (ep0-3);
ep1-3 lifted and lost the ball or aborted right after (LIFT 39 / 10 / 2 ticks); ep4 never
grasped. The 0.3 s run: 0/5 grasped. Asynchronous G0 (5 runs): bin 0-3/5, grasp 2-4/5.
Per the user the perturbation part (1 episode in) was stopped at 21:49 and the nominal 5 is
run once more (t2_g0_nomB, same code / cadence / stepping) to see whether it reproduces.

## 21:58 G0 nominal reproduces on the timing-controlled evaluator (0.6 s cadence, one step per call)
t2_g0_repA vs t2_g0_nomB (same code 3d616cf/a291b3d evaluator files, gate f7bf1da64e75):
(0) gates 5/5 and 5/5; (1) counts C/L/S/B/a 2/4/2/1/4 vs 3/4/2/1/4 (all within +-1);
(2) episode agreement lifted 5/5, bin 5/5, abort 5/5, strict 5/5, corridor 4/5 -> the
registered rule passes for nominal. First-close depth / vertical per episode within ~1 mm
(ep0-3; ep4 3 mm). Trajectories still part (renderer noise), e.g. ep1 148 vs 347 actions,
ep4 GRASP 188 vs 16 ticks, but the outcomes agree; ep3 is the same run to the mm.
Reference, asynchronous pair (r4): nominal agreement bin 2/5, abort 1/5 -- failed.
G0 nominal on this evaluator: bin 1/5 (ep0, 4 of 4 runs incl. smokes), lifted 4/5, strict
2/5, abort 4/5; the failures after a grasp end within 2-48 LIFT ticks (ball lost, or an
unreachable pose right after the lift). Perturbation not yet repeated (stopped by the user
after 1 episode of run A).

## 22:00 Canonical condition frozen for the FOV comparison; G1 then G2, nominal 5, once each
User: G0 perturbation repeats skipped -- the aim is G0/G1/G2 representation comparison, not
certifying the evaluator; G0 nominal x2 (gates 10/10, outcomes 5/5, aggregates equal but
one corridor) is enough repeatability for a nominal comparison. The 0.6 s timing-controlled
nominal-5 condition is frozen (DSE_DESIGN.md section 19; separate from the project's 0.8 s
deployment contract). G1 and G2 once each; a second run only if a difference looks
meaningful. Perturbation later, only if time remains / for the final candidate.

## 22:28 FOV comparison, frozen condition (0.6 s timing-controlled, nominal 5): G1 and G2, run 1
All gates pass (G1 5/5, G2 5/5). Counts C/L/S/B/abort: G0 2/4/2/1/4 and 3/4/2/1/4 (two
runs), G1 1/2/1/0/3, G2 0/1/1/0/4 (fov_nominal_G0_G1_G2.md).
Per episode: ep0 -- G0 bin in both (4 of 4 incl. smokes), G1 and G2 lifted, carried and lost
it (G2 reached PLACE); ep1, ep2 -- G0 lifted in both runs, G1 never grasped (APPROACH 459 /
556 ticks, timed out), G2 never lifted; ep3 -- G0 and G1 lifted (same code CL..a), G2 stayed in
APPROACH 601 ticks; ep4 -- all fail around the grasp.
Reading: a consistent ordering G0 > G1 > G2 (lifted 4 / 2 / 1, bin 1 / 0 / 0); G0 reproduces
here, so a one-run gap of 2-3 lifted episodes is more likely signal, but G1/G2 have not been
repeated. Full-FOV variants are WORSE -- against the "narrow FOV is the bottleneck" hypothesis
(hypotheses: G1's letterbox shrinks the scene to 224x126; G2's pos-embed interpolation 14x14 ->
11x18). Per the user's plan, a second run of G1 and G2 on the same condition follows.

## 22:55 FOV comparison, frozen condition: G1 and G2 run 2 -- the ordering G0 > G1 > G2 reproduces
Second runs (t3_g1_nomB, t3_g2_nomB), all gates pass (5/5 each). Counts C/L/S/B/abort:
  G0  2/4/2/1/4 | 3/4/2/1/4   repeat agreement lifted 5/5, bin 5/5, abort 5/5
  G1  1/2/1/0/3 | 1/2/1/0/4   lifted 5/5, bin 5/5, abort 4/5
  G2  0/1/1/0/4 | 0/1/1/1/2   lifted 5/5, bin 4/5, abort 1/5 (fail mode timeout vs abort)
Over both runs: lifted G0 8/10, G1 4/10, G2 2/10; bin G0 2/10, G1 0/10, G2 1/10 (G2's one bin:
run 2 ep0, which in run 1 failed just before PLACE -- a borderline episode). Lifted is
reproduced episode by episode: G0 lifts ep0-3, G1 ep0 and ep3, G2 ep0, in both runs
(fov_nominal_all.md).
Interpretation: on the frozen 0.6 s timing-controlled nominal-5 condition, with identical
data order and step budget, the centre crop (G0) is the best geometry and the full-FOV
variants are worse, reproducibly. The "narrow FOV is the bottleneck" hypothesis is not
supported here. Untested hypotheses for the loss: G1's letterbox shrinks the scene to 224x126;
G2's pos-embed interpolation 14x14 -> 11x18 under the same fine-tuning budget. Limits: nominal
5 only; no perturbation. Per the rule: G0 stays the geometry; G1/G2 not promoted.

## 23:05 Can the demos be phase-segmented automatically? (analysis only, no GPU / sim)
Question (user): segment each demo by the gripper -- closing starts = grasp, opening starts =
release -> start..grasp = move to the object, grasp..release = move to the bin -- and label
automatically.
Data: demos/{train 20, val 5, v2_train 48, v2_val 18} = 91 episodes, 10 Hz, per frame: wrist
RGB, EE pose, camera gripper width (policy input), and evaluation-only GT jaw width, GT ball
position, the scripted expert's own stage label (10 stages), visibility flags, stamps; per
episode the placement spec (object_xy, ball_r, bin_xy, bin_yaw, pitch, standoff, depth, lift,
carry_z, release_z).
Result: every episode has exactly one close and one open cycle and the same stage order
HOME>SEARCH_OBJECT>APPROACH_OBJECT>GRASP>LIFT>SEARCH_BIN>TRANSPORT>PLACE>RETREAT>SETTLE.
Gripper-only events (open ~51.8 mm, holding ~31.7 mm; rule: close = first drop 1 mm below open,
release = first rise back above the open/hold midpoint, walked back to where the opening
began), camera width and GT alike, 91/91 found:
  close onset  = GRASP start +1..+2 frames; ball lifted (GT) = GRASP start +18..+21;
  opening start = PLACE start +6..+14 = RETREAT start -12..-13 frames.
(A first attempt with a 1-mm opening threshold fired wrongly; the width creeps ~0.5 mm while
carrying.) The training zarr (94 episodes) holds only the policy keys; its episodes are the
68 train+v2_train demos cut at timing gaps (dt > 0.105 s, min 17 frames), a deterministic
mapping (build_geometry_zarr.segments()) -> per-row labels can be attached exactly.
