# Definitive experiment journal — 2026-09-27 (overnight)

Each entry: purpose / control / result / interpretation. Times KST.

## 03:16 Preflight: GPU and environment — PASS
Purpose: run only on physical GPU 5. Control: allocate a 512 MiB marker on
torch cuda:0 under CUDA_VISIBLE_DEVICES=5 and read which physical card holds
it from nvidia-smi. Result: physical index 5 (GPU-6ac93a16…). GPU 5 was idle;
seven stale shell waiters (self-matching pgrep loops, no GPU use) were
killed by PID. GPU 0 carries only the simulator's EGL context (242 MiB,
pre-existing, source-hardcoded EGL_DEFAULT_DISPLAY). Software: python 3.9.18,
torch 2.1.0 / CUDA 12.1, accelerate 0.24.1, V100 sm70, bf16 unsupported.
Interpretation: environment fit for the protocol.

## 03:20 Preflight: dataset through the production path — PASS
Purpose: no hand-computed counts. Control: hydra-composed config from the
same file and overrides the runs use, production UmiDataset, workspace
DataLoader settings. Result: clean 25 segments / 6455 frames / N=6080 /
DataLoader 95; combined 94 / 22942 / N=21532 / DataLoader 337; v2_train
69 / 16487 / N=15452; val_ratio 0.0, zero held-out segments, drop_last
False; the combined zarr's first 25 segments are identical to the clean zarr.
Interpretation: exactly the expected numbers.

## 03:21 Config audit
Both historical runs resolve to identical policy/optimizer/EMA/dataloader
sections; the old clean run used train_diffusion_unet_timm_omx_workspace
(val_ratio 0.0 override), the old v2 run the umi workspace + task=umi_omx
(val_ratio 0.05 default). Both definitive runs use the omx workspace config
with identical overrides except dataset path and step budget.

## 03:22–03:33 Checkpoint / AMP infrastructure (training path, commit ad87c92)
Purpose: a step-N checkpoint must be the state after exactly N applied
updates in every part, and resumable. Changes: always save the optimizer;
save scheduler, GradScaler, EMA counter, RNG in payload['extra']; atomic
serialized writes; EMA before the checkpoint hook; update count gated on
non-skipped optimizer steps; Accelerate fp16 with accelerator.backward;
shared init state; max_opt_steps stop.
Result — a real bug found by the independent on-disk audit: CPU tensors were
handed to the writer thread by reference (.to('cpu') is a no-op on CPU) and
AdamW's per-parameter step counters are CPU tensors incremented in place, so
a checkpoint triggered at update 3 was written with counters at 3, 4 and 5.
Fixed by cloning CPU tensors. Interpretation: the historical baseline's
{5985: 235, 5986: 64} split is this serialization race, not parameters
missing a gradient; the earlier "≥5986, most likely 5986 calls" reading of
the baseline was wrong.

## 03:24 Shared initial state
init_state.pt from the production workspace constructor at seed 42;
checksum (excluding the dataset-fitted normalizer) a4cd264f…; a second
seeded construction reproduces it bit for bit.

## 03:25–03:33 Resume smoke test through train.py — PASS
5 updates → checkpoint → resume → 1 update: opt_steps 5→6, AdamW steps
{6: 299}, LR 9e-7 (= schedule), scheduler last_epoch 6, EMA 6 / decay
0.70093, scaler growth tracker continued (not reset), torch CPU RNG restored
bit for bit. All four smoke checkpoints pass the reload audit after the
copy fix (step3 had failed before it). AMP proven from inside the forward:
autocast enabled, denoiser output float16.

## 03:34 Training chain started (clean AMP → audit → v2 AMP → audit)
training.resume=True in both runs loads only <run_dir>/checkpoints/latest.ckpt
if it exists; the clean run's log has no "Resuming" line and its
run_provenance shows resumed_from=None, opt_steps_at_start=0, init checksum
a4cd264f…, EMA==model at start. Kept identical for v2 so the configs differ
only in dataset and step budget (and the chain script must not be edited
while it executes).
global_step: logging counter only (plus the gradient-accumulation guard,
inert at accumulate_every=1); the 4→4 across the smoke resume is a mid-epoch
checkpoint capturing it before its post-logging increment.

## 03:46–04:00 Evaluation-side changes (commits b4e41e8, 987ebe4; no training-path file)
Episode start is now one procedure (place, planning scene, deterministic
reset, perturbed pose, fresh-observation gate) retried as a whole; infra
failures are logged separately and never counted. The old retry skipped the
perturbed placement: historical val18 clean e60 episodes 3 and 6 and
v2 step5985 episodes 1 and 3 began at HOME. CPU-server smoke test on a new
checkpoint: the gate, the new fields and the perturbed start all work. One
start attempt failed with 97 fresh frames in 5 s and unreadable tips — one
case pointing at something other than a stalled camera for that instance;
it does not by itself settle the earlier stale-frame observations. Failed
attempts now save the frame, jaw width, joints and crop contents.

## 04:05 Historical FP32 re-aggregation (reference only)
Three variants kept apart: ALL (including invalid HOME starts), valid-only,
common-valid-15. Definitive conclusions use only the new evaluations.

## 03:35–05:39 Training — both runs complete, every checkpoint audited PASS
Purpose: matched-update and extended comparison from one initial state.
Control: same config file and overrides except dataset path and step budget
(the chain's config gate found exactly those 6 diff lines), shared init
a4cd264f… in both, val_ratio 0.0, batch 64, Accelerate fp16, cosine horizon
pinned at 11400, warmup 2000.
Result:
- clean AMP (N=6080, DL 95): 03:35–04:18, stopped at opt_steps 5986,
  0 skipped updates, 0 non-finite losses.
- v2 AMP (N=21532, DL 337): 04:19–05:38, stopped at opt_steps 11400,
  1 skipped update (between 10000 and 11400; scale 2097152 -> 1048576),
  0 non-finite losses.
- Every step checkpoint reloaded from disk: opt_steps = EMA count =
  scheduler last_epoch = N, AdamW step histogram {N: 299}, LR equal to the
  schedule at N. clean and v2 at 5985/5986: identical LR (1.8550e-4 /
  1.8546e-4) and scale (262144).
- dataset passes at the compared points: clean 63.0 @5986; v2 17.8 @5986,
  23.8 @8000, 29.7 @10000, 33.9 @11400.
Interpretation: the controlled comparison the protocol asked for exists.
The single skip was handled as designed (count, EMA and schedule aligned).

## 05:39 Evaluation chain started (GPU 5, EMA weights, one server at a time)

## 05:39–06:03 First nominal pass (5 jobs) — SUPERSEDED, kept in superseded_start_order_bug/
All five nominal jobs ran; episode 1's first start was "not ready" in three
of them with 97 fresh frames, arm at HOME, jaw open, and the BIN in the crop.

## 06:05 Evaluation stopped: the start order let the arm sweep freshly placed bodies
Purpose: find why a HOME start could show the bin in the crop.
Finding: prepare_start placed the ball and bin while the arm still stood
where the previous rollout ended, and only then reset. The arm's way home
swept through them. Checked against the logged free-joint ball at the first
rollout sample:
- definitive nominal (first pass): episode 3's ball 158–397 mm from its
  placement in all five jobs; episode 1's bin pushed (the not-ready retries).
- historical FP32 nominal (clean e60, v2 5986, v2 5985): episode 3's ball
  275–340 mm off in all three.
- historical val18: clean e60 episodes 5, 8, 10, 15, 16 (99 mm to 5 m —
  off the table) and v2 5985 episodes 10, 14, 15, 16, 17, besides the HOME
  starts already known (clean 3, 6; v2 1, 3).
The collector has always homed before placing.
Fix (a721932, evaluation only): deterministic reset -> place -> read both
bodies back (≤2 mm from placement, bin yaw ≤1°, still over 0.3 s) or infra
retry -> perturbed pose -> fresh-observation gate.

## 06:10 Perturbed starts nudge the ball — and so does every demonstration
Smoke test of the fix: v2_val episode 1's move to its perturbed pose pushed
the ball 12.4 mm, identically on three attempts. The kinematic copy
(collector_scene.xml) says the pad clears the ball by 0.3–10.6 mm at every
v2_val perturbed pose and neither route (joint leg, collector's ring+blend)
comes closer on the way — so the simulator's contact outcome is what moves
it, not the path. Measured in the recorded demonstrations (free-joint ball,
max displacement before GRASP): clean train 3.1–8.9 mm (20/20 >2 mm),
v2_train 1.5–10.5 (43/48), v2_val 2.4–16.0 (18/18; episode 1: 15.95 mm at
the dwell). So a nudge at the perturbed pose is part of the perturbed start
as the data define it. Rule: after the perturbed move the bin must still be
at its placement and the ball still; the ball's nudge is recorded, and only
a knock past 25 mm is refused. The same rule, applied post hoc, marks the
historical displaced starts above as invalid.
Also found: the historical perturbed starts were not the same physical
starts as tonight's — historical clean e60 val episode 1 began unsettled,
~10 mm higher, pitch 20.7° (jaw apparently resting on the ball), where the
fixed procedure pushes the ball 12.4 mm and settles at 23.5°. Historical
and definitive val18 are therefore not comparable episode by episode.

## 06:17 Evaluation chain relaunched (run_eval2.sh, rollout code 2943963)
Same jobs, order and arguments; all nominal jobs re-run from scratch.

## 06:43 Nominal re-run complete (fixed start) — all 25 starts valid, 0 retries
Both bodies within 0.8 mm of their placement at every start (ball 0.19,
bin 0.75 — resting-contact offsets); no not-ready retries at all, which is
what the displaced-bin explanation predicted. Provisional aggregate:
clean5986 GRASP 5/5, LIFT 0/5, bin 0/5, unreachable abort 5/5;
v2_5986 GRASP 3/5, LIFT 1/5, bin 0/5; v2_8000 GRASP 5/5, LIFT 0/5;
v2_10000 GRASP 5/5, LIFT 1/5; v2_11400 GRASP 5/5, LIFT 3/5, bin 2/5,
corridor 3/5, unreachable abort 2/5. n=5 each.

## 06:50 Metric correction: strict GT secure grasp measured the wrong window
Purpose: v2_11400 put the ball in the bin twice with "strict secure 0/5".
Finding: the deviation was taken over every lifted sample, which includes
the ball's fall after the jaw opens over the bin (20.9 mm in one episode).
Control: applied to the expert demonstrations, that definition fails every
one of them (whole-lifted deviation 15–61 mm), so it was broken, not strict.
Fix (thresholds unchanged: lift 20 mm, 0.5 s, 4 mm, 30 mm): from lift-off,
over the first unbroken lifted stretch, the longest prefix in which the
ball's tool-frame position stays within 4 mm of that prefix's mean; it must
last ≥0.5 s with ≥30 mm tool travel. Expert demos under it: clean 20/20,
v2_train 48/48, v2_val 18/18. Whole-window numbers kept as whole_lifted_*.
Corrected before any val18 result was aggregated. The historical "no strict
secure grasp anywhere" statement came from the broken definition and is
withdrawn; historical files are being regenerated (…_final.json).

## 07:34 Primary val18 complete — 16/18 valid in every job; 2 deterministic start failures
clean5986 val18 06:43–07:00, v2_5986 07:00–07:13, v2_11400 07:13–07:33.
Runtime summary line: bin 0/16, 2/16, 4/16; runtime grasped 2, 6, 10.
v2_val episodes 11 and 13 failed all three start attempts in every job,
identically (policy-independent: the start happens before the policy is
asked anything):
- ep 11: with the arm at HOME the placed bin sits 4.7 mm off and creeps.
  Kinematic copy: the spec'd bin intersects the robot base (link0) by up to
  5.4 mm. A placement defect in the v2_val spec itself.
- ep 13: the move to the perturbed pose knocks the bin 102 mm / 117 deg.
  Kinematic copy (06:10 analysis): the evaluation's HOME->pose joint leg
  passes 8.4 mm into the bin; the collector's ring+blend route clears it.
  A defect of the evaluation's route, not of the placement.
Not fixed mid-evaluation (it would change every start after three jobs had
run). Paired comparisons are on the same 16 episodes in every job.

## 07:55 Metric correction #2: strict secure judged a graze instead of the carry
Purpose: v2_11400 val18 had bin successes with a "rigid carry" of 0.04 s.
Finding: the 06:50 version judged only the FIRST unbroken lifted stretch.
In v2_11400 val18 episodes 0, 9, 10, 12 that stretch was a 0.04–0.11 s
graze of the 20 mm line while the jaw took the load; the real carry
(19–57 s long, rising 130–150 mm) began ~0.6 s later and was never judged.
Fix (same thresholds, same rigid-prefix-from-lift-off rule): every lifted
stretch is judged from its own lift-off; secure if any passes. A ball that
shifts >4 mm right after lift-off and then rides still FAILS, as defined
(e.g. v2_11400 val18 ep17: one 13 s stretch, 213 mm rise, but a 4.0+ mm
shift within 0.05 s of lift-off). Expert demos: 20/20, 48/48, 18/18, 5/5.
Provisional aggregates made before this (aggregate_nominal_provisional,
aggregate_primary_provisional) are kept and superseded by aggregate_part*.

## 08:14 Evaluation chain complete; 08:25 final aggregate
Secondary jobs: v2_8000 val18 07:34–07:47, v2_10000 val18 07:48–08:04,
clean5985 nominal 08:04–08:09, v2_5985 nominal 08:10–08:14. Every counted
start (115) passed the fresh-observation gate first time (wait ≤0.11 s);
0 retries; 2 infra failures per perturbation job (ep11, ep13). Final aggregate
(both metric corrections) = aggregate_part1_primary + aggregate_part2_secondary
-> aggregate_definitive_final.json; tables via build_tables.py.
Result (n=5 nominal / n=16 perturbation):
- nominal LIFT: clean5985 0, clean5986 0, v2_5985 1, v2_5986 1, v2_8000 0,
  v2_10000 1, v2_11400 3; bin only v2_11400 (2); unreachable abort 5,5,5,5,5,4,2.
- perturbation corridor/lifted/strict/bin/abort: clean5986 0/2/2/0/13,
  v2_5986 4/6/3/2/14, v2_8000 2/8/4/3/13, v2_10000 6/11/5/3/11,
  v2_11400 5/10/8/4/7.
- rejections mostly joint limit; 57.3% of rejected waypoints in aborted
  episodes fall in the final 8 plans.
Interpretation: CASE A pattern within the planned budget (nominal recovers
by 11400, recovery kept). Not separable from LR annealing without a clean
run to 11400 on the same schedule; nominal n=5; underfit not excluded.
Summary: experiment_summary_20260927.md (this directory).

## 08:40–09:00 v2_11400 nominal: episode breakdown and replay videos (analysis only)
Purpose: split v2_11400's three nominal failures into feasibility (A),
insertion depth (B) and field of view (C). Control: the runtime gate
reproduced exactly (pitch from the raw finger axis, solve_ik_best with
joints 2-4 clipped, refused above 2 mm), plus the same solve with limits
lifted, a pitch scan at each refused position, and the yaw the projection
discards; expert demos of the SAME placements (nominal = train 0-4).
Result:
- ep0 (lifted, abort in LIFT): streak from plan 32 at 18.0 s in LIFT; asks
  r 164 mm, z 72 mm at pitch 23.4 deg -> joint3 pinned at +90, 3.0-3.5 deg
  past it if unclipped; the same positions are reachable at pitch 46-52 deg
  (the expert lifts this placement pitching 16.5 -> 45.7 deg, joint3 <= 69.6).
  Yaw discarded 0.0 deg, 8-9 of 16 raw waypoints unreachable in every plan,
  object in crop, bin not. Measured joint3 88.2 deg at streak start (1.8 deg
  margin), 89.9 by 19.5 s. Grasp itself shallow (onset -13.0 mm vs expert
  -23.7 on this placement) but held; strict secure failed on travel (24 mm
  < 30) because the run aborted, not on slip.
- ep1 (ran out of 600 ticks, 0 refusals): one real close at depth -9.1,
  vertical +14.3 mm, pitch 20.8 (expert on this placement -22.8 / +3.4 /
  13.8); jaw only reached 38.5 mm and never reopened past 48 mm; ball pushed
  225 -> 289 mm from the base; object in crop 146/146 plans. Pure B.
- ep4 (abort in APPROACH): first close depth -7.9, vertical +15.6, pitch 25.7
  (expert -22.3 / +4.6 / 13.8) pushed the ball from 301 mm out to 445 mm; the
  policy followed it: streak from plan 58 at 30.0 s asks r 396-400 mm, z 20 mm,
  pitch -5.5..-7.5 deg; no joint pinned, unclipped solve misses too -> beyond
  the arm's reach (~396 mm at table height); reachable at some pitch in 2 of 8
  plans; 13-14 of 16 raw waypoints unreachable; yaw discarded 0.2-0.3 deg;
  object in crop. Measured joint2 75.4 deg at streak start, 87.4 by 31 s. B -> A.
- depth at the first close, all five: -13.0, -9.1, -14.4 (bin), -11.0 (bin),
  -7.9 mm; expert on the same placements -22.3 to -23.7.
- C: object in the crop in every APPROACH/GRASP plan of all five episodes;
  no evidence for C in this set ("in crop" = >= 12 px, a coarse measure).
Interpretation: both aborts are raw requests outside the joint-limited
workspace, not projection artefacts. ep0 is A on its own (the lift pitch the
expert uses is not reproduced); ep4 is A caused by B; ep1 is B. Videos are
log replays of these exact episodes (wrist pane re-rendered, approximate).

## 09:10 Replay videos: the magenta tips (user question)
Question: should the tips be painted out, and why do they look like they
float? Checked, not assumed: a live frame saved by the evaluation (v2_val
ep11 start) and my re-render of that exact state agree to 1.9/255 mean
absolute difference with the same 21 magenta pixels in the same places, so
the live simulator shows the same dots. The patches are 2 x 2 mm boxes on the
fingertip ends, child geoms of the finger bodies (they cannot detach); white
fingers on a white ball leave only the magenta visible, which reads as
floating. mask_magenta on the live frame leaves 0 magenta pixels, and the
masking path (gripper_vision.py 09-26 00:24, policy_bridge.py 09-26 19:34)
predates the AMP runs -- nothing about it changed. The earlier videos' right
pane was the masked policy frame; mine showed the unmasked re-render. Fixed:
the right pane now runs the bridge's own steps (mask_magenta with
TipDetectorConfig(), centre square, 224); 0 magenta pixels left in every frame
of all four videos.

## 09:30 Magenta tip patch placement (user: "it used to sit inside the fingertip")
Checked against history and pictures, not memory:
- The patch moved once, in 196f2cb (09-26 00:45, "Put the patch where the
  ball it is holding cannot cover it"): from the middle of the fingertip's top
  face (x +-6.0 mm, 3 mm square) to its inner edge (x +-2.5 mm, 2 mm). Reason
  recorded there: a held 50 mm ball covered the old spot in the wrist camera
  and the width froze at "open" in a third of samples. Side effect, visible at
  4x render: the new patch overhangs the fingertip outline, and masking leaves
  a 1-2 px white nub at the tip corner.
- Every training demo was recorded after that commit (clean 09-26
  10:53-11:09, v2 21:08-22:01); the nub is in the training images, in
  tonight's live evaluation frames and in the replay alike. Train and eval
  match; every evaluated model (FP32 e60/v2, AMP clean/v2) was trained on
  those images. Nothing here changed with AMP.
- Why the 09-26 video looked clean: e60_ep2_nolatch.mp4 (19:54) predates the
  recorder fix (4f727bb, 20:03) and squashed the whole 320x180 frame into a
  square (the ball measures 1.33-1.69x taller than wide there, 0.95-1.05 in
  the data and live frames), which shrinks the nub; the policy's input is the
  centre crop, unsquashed, as in the replay.
Images: sim_umi/eval_results/2026-09-27_definitive/video/tip_patch_check/.
Not changed: moving the patch back inside would change every training image
(re-fit with fit_tip_patch.py, re-collect, retrain) -- a separate decision.
