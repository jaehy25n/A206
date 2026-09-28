# Aux ablations journal (A: timing aux regression on GPU 0, B: oracle relation FiLM on GPU 5)

## 00:23 Design only (no code changed)
Purpose: design the two single-change ablations on G0 before implementing (user request).
Findings from the code that shape the design: for a ViT, TimmObsEncoder keeps only CLS
(attention_pool_2d is ignored), so the 196 patch tokens are computed and discarded today;
the optimizer has two groups (UNet 3e-4, obs encoder 3e-5), so any new module needs its own
group; the shared init loads strict; no dataloader_seed, so shuffle / worker seeds / crop /
jitter all come from the global RNG after model construction -> new modules must be built
in a forked RNG. Checked: an explicit crop path (get_params + resized_crop + ColorJitter)
gives the same image AND the same RNG state as G0's Sequential.
Numbers used: G0 L_diff 1.06 (step 0) -> 0.046 (1k) -> 0.0125 (11.4k); phase-masked samples
inside T_cap 3.2 s: close 26 %, lift 23 %, open 11 %.
Result: DESIGN.md. Open decisions listed there (lambda / T_cap, head input, EE mask for B,
B's evaluation-time oracle masks). Waiting for approval.

## 00:44 Implementation (user-approved design with the user's revisions) and CPU unit tests
Revisions adopted: A supervises ONLY the next event of the current phase (APPROACH->close,
GRASP_LIFT->lift, TRANSPORT->open; RELEASE/RETREAT_POST none), per-event scale = P95 of dt
over that phase's training samples (close 12.3118 s / lift 1.7000 s / open 13.6000 s, n
7819 / 1197 / 9319; val never used; re-derived and asserted at start-up), head LayerNorm ->
256 -> SiLU -> 3, no output activation, lambda 0.1 fixed, SmoothL1 beta 1.0. B uses the
tip mask, masks for both obs frames, patches from the same final-normalised token tensor
as CLS, relation [f_T, f_E, f_T-f_E, f_T*f_E, dcx, dcy, log area ratio, presence_T,
presence_E] -> LN -> 256 -> SiLU -> 1536 (zero weight + bias), hard per-frame fallback
CLS' = CLS when target_mask_valid is false or the post-crop target < 12 px.
Code: policy/diffusion_unet_timm_timing_aux_policy.py, policy/diffusion_unet_timm_relation_film_policy.py,
model/vision/timm_relation_film_obs_encoder.py, dataset/umi_aux_dataset.py,
workspace/twin_probe.py; workspace: shared init loaded strict on G0 keys (only the new
module's keys may be missing), shared-parameter hash, third optimizer group (new module,
lr 3e-4, same schedule; groups 1-2 unchanged), loss terms logged, provenance (sidecar
sha256, scales, seeds, groups); UmiDataset: opt-in sample index (twin only). New modules
are built inside torch.random.fork_rng with seed 20260928.
Unit tests (CPU, gates/unit_tests.json): 22/22 PASS -- config diffs only in the intended
keys; global RNG after construction equal to G0 (A, B); shared-init hash equal (a4cd264f...,
= the definitive INIT_SHA); only new-module keys missing; B last Linear zero; A labels =
current-row sidecar labels (41 checked); B masks = obs rows {r-1, r} with the start
padding, same rows as the RGB; B transformed RGB bit-exact vs G0's Sequential and RNG
state equal after it; B global_cond == G0 at zero init (max abs 0); a forced non-zero FiLM
changes exactly the frames the hard gate allows and never the low-dim part.

## 00:56 Twin gate: FAIL (r1) -> cause fixed -> PASS (r2)
Purpose: prove that A and B see exactly G0's randomness and start from G0's state.
Control: G0 / A / B code paths, the definitive overrides, seed 42, shared init, 20
optimizer steps each, one after the other on GPU 5, probe on (twin_probe.py);
compare_twin.py. Checks in gates/twin_gate*.json.
Result r1 (twin/): FAIL. Sample indices, crops, jitter and the CPU RNG equal at all 20
steps, but the CUDA RNG state differed from step 0, so the diffusion timesteps / noise and
the step-0 L_diff differed (G0 1.10184, A = B 1.11579). Cause: the new modules were built
inside fork_rng(devices=[]) after torch.manual_seed(20260928), which also reseeds CUDA;
fork_rng restored only the CPU state. Fix: torch.default_generator.manual_seed (CPU only).
The CPU unit test had not seen it (CUDA was hidden); the construction check now also
compares the CUDA RNG state (unit_tests_r2.json, PASS).
Result r2 (twin_r2/): PASS, every check. All 20 steps: sample indices, crop draws, jitter
draws, CPU and CUDA RNG, UNet timesteps and noisy-trajectory hashes equal to G0 (A and B).
Step 0: shared-init hash a4cd264f... in all three, L_diff bits equal (1.1018394), global
condition equal (max abs 0), B CLS' == CLS (0.0; 124 of 128 frames active). No skip, no
NaN, no OOM at batch 64. Afterwards the FiLM starts to move (max |CLS'-CLS| 9e-6 at step 2,
growing) and the losses separate from step 2.
Noise floor: G0 r1 vs G0 r2 -- same code, same everything -- are identical in data and
RNG at all 20 steps, but L_diff differs from step 2 by ~1e-5 (GPU atomics in backward), so
later-step loss differences below that are not attributable to the ablations.
Interpretation: the gate the user set is met by the final code; per the agreed procedure
(fix, re-verify, then start) both full runs start now.

## 01:09 While training: B's mask-capable evaluator written (not run, not built into the plant)
Purpose: step 8 needs oracle masks at inference, from the SAME simulator tick as each RGB
frame, without changing what A is evaluated with.
Control / design: the unchanged evaluator stays unchanged -- dse_rollout.py, policy_bridge.py,
policy_server.py and friends are not touched (hash f7bf1da64e75, its hard-gate pass stands;
A gets one new runner phase, anom). The mask path is additive:
- plugin: the camera plugin's joint snapshot (same mjData copy, same stamp as the image)
  optionally appends every free joint's 7 qpos, named by body (object/x..qz, bin/x..qz --
  the model's free joints are unnamed; first build named them "", fixed before any use).
  Built from a copy of the plugin package into a SEPARATE overlay (~/omx_overlay_masks),
  enabled only by mujoco_plugins_dse_masks.yaml (joint_snapshot_free_joints: true) +
  env_overlay_masks.sh. Patch: overlay_patches/camera_snapshot_free_joints.patch.
- one renderer: sim_umi/src/oracle_render.py is the prep builder's per-frame code moved
  verbatim; build_oracle_masks.py now calls it. oracle_render_regression.py will prove it
  reproduces the frozen sidecar bit for bit (needs EGL -> after training).
- dse_rollout_masks.py wraps Bridge.observe_at / build_batch and runs dse_rollout's own main:
  masks from the frame's exact snapshot; B gets them as policy keys, the G0 control gets
  the same arrays under "_" names (policy_server strips "_" keys) -> same rendering and
  transfer cost, masks ignored.
- dse_mask_gate.py: dse_gate's hard gates + per-frame mask provenance (exact snapshot,
  snapshot stamp == image stamp, free joints present, fingers inside the finger box,
  mirror-vs-image QA median < 1 grey level); marker keyed by evaluator + mask-path code.
- run_eval_dse_masks.sh (msmoke_g0, msmoke_b, g0mask, bmask) refuses a full phase without
  that marker and refuses a plant that is not the mask variant; bringup.sh plain|masks
  relaunches the plant exactly as captured before training.
Known difference, recorded: at evaluation target_mask_valid is true whenever the snapshot is
exact (the state is exact there), including release frames, which training gated off
because the demo ball pose was uncertain there.

## 01:41 Training audit at the first checkpoint (step 5986, both runs)
Purpose: catch a broken run before it costs the full budget.
Control: audit_checkpoint.py (the definitive runs' audit; for a run with a new module it now
checks the shared-parameter hash, for G0 the full init checksum exactly as before -- re-run
on G0 step11400: still PASS); loss_diff compared with the G0 definitive run's train_loss
(= its diffusion loss) as a +-250-step mean at the same steps.
Result: A and B step5986 PASS -- opt_steps / EMA / scheduler 5986, all 305 parameter tensors
at AdamW step 5986 (148 + 151 + 6), LRs on the cosine schedule in all three groups
(1.8546e-4 / 1.8546e-5 / 1.8546e-4), fp16 scaler finite, 0 skipped updates, 0 non-finite
losses, shared init a4cd264f. loss_diff G0 / A / B: 1k 0.0447 / 0.0443 / 0.0443,
3k 0.0210 / 0.0210 / 0.0213, 5.9k 0.0170 / 0.0171 / 0.0172. A's aux loss 0.0152 (~500) ->
0.0038 (~3k) -> 0.0021 (~5.9k); training-batch MAE close 1.36 -> 0.74 s, lift 0.33 -> 0.09 s,
open 1.38 -> 0.45 s.
Interpretation: both runs are healthy; neither change disturbs the diffusion objective
(curves within ~1 % of G0). Nothing is concluded about behaviour from losses.

## 02:19 Both full trainings finished; every checkpoint audit PASS
Result: A (GPU 0) exit 0 at 02:17:55, B (GPU 5) exit 0 at 02:18:22, both 11400 successful
updates in 11402 batches (one AMP skip each, as in the G0 definitive run). audit_checkpoint.py
PASS on step 5986 / 8000 / 10000 / 11400 of both: opt_steps = EMA = scheduler = N, all 305
tensors at AdamW step N, LRs on the schedule in all three groups, scaler finite, 0
non-finite losses, shared init a4cd264f. Diffusion loss (+-250 steps) G0 / A / B:
8k 0.01458 / 0.01452 / 0.01465, 10k 0.01272 / 0.01266 / 0.01276, last 500 batches
0.01229 / 0.01225 / 0.01235. A, last 500 batches: aux 0.0008, MAE close 0.456 s, lift 0.055 s,
open 0.277 s (training batches, clipped-target seconds).
Runs: sim_umi/train_results/2026-09-28_g0_timing_aux_v1, ..._g0_oracle_tip_relation_film_v1
(run_provenance.json: git 63048c5 clean, seed 42, resolved config, sidecar sha256, shared
init hash, optimizer groups; .hydra/config.yaml).
Primary checkpoint fixed in advance: EMA step 11400 (no selection among intermediates).

## 02:29 Renderer proven identical; A's canonical evaluation started
Result (renderer): oracle_render_regression.py PASS -- the shared renderer, through the
refactored builder, reproduces the frozen sidecar bit for bit on 6 demos / 2060 rows (three
masks, finger-y map, pixel counts). oracle_render_crossenv.py PASS -- the ROS env the
evaluator renders in (python 3.12, cv2 5.0, EGL device 5) gives the same masks as the
sidecar on 663 rows (cv2 INTER_NEAREST 180->224 also checked identical 4.7 vs 5.0). One
refactor slip found by the regression and fixed first: the builder's empty-target reason
code lost its camera pose variables (QA only, not the masks).
A evaluation: plain plant relaunched exactly as captured (mujoco_plugins_dse.yaml, original
overlay -- the log shows the original plugin's "7 joints" line, CUDA_VISIBLE_DEVICES=5, EGL 5,
GPU 0 244 MiB as before); unchanged evaluator (code hash f7bf1da64e75, its GATE_PASS);
frozen canonical condition (timing-controlled nominal 5, 0.6 s cadence, DSE_BATCH 1);
A's EMA step11400 (server: EMA weights, CenterCrop 212 -> Resize). Two runs:
a1_timing_aux_nomA, a1_timing_aux_nomB. (A first attempt did not start: the runner is not
executable and was called directly -- nothing was produced; re-run with bash.)
Two harness slips of mine, fixed: bringup.sh / the mask runner detected the plant with
pgrep -f, which matched my own shell; now by executable name.

## 02:50 A (timing aux) on the frozen canonical condition, 2 runs -- vs G0's 2 runs
Purpose: step 7 -- does the timing supervision change closed-loop behaviour?
Control: unchanged evaluator (hash f7bf1da64e75), plain plant as captured, timing-controlled
nominal 5, 0.6 s cadence, DSE_BATCH 1, EMA step 11400 fixed in advance; G0 = the canonical
runs t2_g0_repA / t2_g0_nomB of the same evaluator. aggregate.py, fov_nominal_table.py
(eval_A_vs_G0.md), dse_repeat_compare.py (eval_A_repeat_compare / eval_G0_repeat_compare).
Result (C/L/S/B/a = corridor / lifted / strict / bin / abort):
  G0 run 1  2/4/2/1/4   G0 run 2  3/4/2/1/4   -> lifted 8/10, strict 4/10, bin 2/10, abort 8/10
  A  run 1  2/2/2/1/3   A  run 2  2/3/1/1/3   -> lifted 5/10, strict 3/10, bin 2/10, abort 6/10
  A run 1 ep1 FAILED a hard gate (arm_continuity): 2 of 46346 ticks with a lock residual of
  6.0e-7 / 6.2e-7 rad (limit 1e-7; neighbours exact to 5e-12). Not a missed update (that
  would be the tick's whole command step, 2e-5 -- the residual is 3 % of it); cause not
  pursued further. Per the DSE rule the episode is INFRA-INVALID (kept in the table, marked,
  not counted as a task outcome either way; its outcome was "....." like run 2). First such
  violation in the 35 canonical episodes so far (G0/G1/G2: 0). Run 2: every gate PASS.
  Invalid starts 0 in all runs.
  Rejected waypoints (IK) G0 35 / 34, A 27 / 29 (mostly the eight-in-a-row abort streaks).
  First-close geometry, mean of 5 (ball in the tool frame at close onset; expert mean in
  brackets): depth G0 -10.2 / -10.8 mm, A -13.5 / -14.8 mm (expert -22.6); vertical G0 8.1 /
  8.0, A 0.9 / 4.7 (4.3); pitch G0 8.9 / 9.0 deg, A 1.0 / 2.2 deg (12.6, range 7.9..17.4).
  Repeat agreement (valid pairs): G0 5/5 on lifted / strict / bin / abort; A 3/4, 3/4, 2/4, 2/4.
  Both checkpoints' repeats diverge early (policy input differs from plan 1-6, the tolerated
  renderer noise; G0's EE paths differ by up to 312 mm too) -- G0's 5/5 agreement was in
  part the luck of its outcomes; A ep4's divergence starts at a controller skip tick.
Interpretation: on this condition A does not do better: fewer lifts (5 vs 8 of 10), bin equal
(2 vs 2), fewer aborts. It does close DEEPER -- toward the expert, the failure the timing
supervision was meant to address -- but with the tool nearly level (pitch ~1-2 deg, outside
the expert's range) where G0 closes at ~9 deg. n = 10 episodes per arm with an evaluator
whose repeats diverge on their own; no significance is claimed.

## 02:57 B's mask-capable evaluator: masks exact, but the first B smoke failed arm_continuity -> stopped
Purpose: step 8 -- the mask path must pass the hard timing gate before any G0-control / B run.
Control: plain plant stopped; mask plant launched (bringup.sh masks): the process maps the
separately built plugin (omx_overlay_masks), log "7 joints, 2 free joints", one received
snapshot = 21 entries (7 hinge + object/x..qz + bin/x..qz, plausible values). Smokes:
msmoke_g0 (G0, masks generated, sent under "_" names) and msmoke_b (B, masks used), then
dse_mask_gate.py (mask code hash 1e5175afc0f6).
Result:
- Masks: both smokes PASS every mask check -- 82 / 56 observation frames, all from the
  joint snapshot of the image's own stamp (0 not exact, 0 stamp mismatch, 0 invalid), 0
  finger px off the box, gripper and tip always present, mirror of the snapshot state vs the
  image the policy got: median 0.0001 grey levels (max 0.0009) -- the plant image and the
  oracle render of the same state are practically identical. Render cost ~9.5 ms / frame,
  paused plant. Servers: 0 inference failures; G0's policy I/O shows the "_" keys (ignored),
  B's the policy keys.
- DSE gates: G0 smoke PASS; B smoke ep0 FAIL arm_continuity -- one tick (5919 -> 5920) where
  the command applied differs from the controller output by 2.06e-5 rad (about two ticks'
  command change; not equal to any neighbouring output), all neighbours exact to 8e-10, no
  /clock-detected skip. Same kind as A run 1 ep1 (6e-7) on the UNCHANGED evaluator.
- Diagnostic re-run of the B smoke (m0_smoke_b_diag_rerun, not a retry-until-pass): the same
  9257 ticks, 0 violations, every gate PASS -> sporadic, not tied to the trajectory.
Interpretation: the mask path itself is verified; a sporadic single-tick plant/controller
glitch has appeared twice since the plant was relaunched after training (0 in the 35
canonical episodes before), once without any mask code. The gate marker was NOT written and
no G0-control / B evaluation was started. Waiting for the user's decision on how to treat it.

## 03:01 15-min timebox: the single-tick arm_continuity violation is a LOGGING artifact (B), not a control jump (A)
Purpose (user): tell apart A = the applied command / control trajectory jumped for one tick,
B = the cycle message / logging / sampling ordering made the gate see a jump that was not.
Control: B smoke's violation (tick 5920, 2.06e-5) and A run 1 ep1's two (6e-7), +-10 ticks:
expected command (previous controller_state output), applied command (inferred from the
cycle's effort), controller_state stamp vs cycle stamp, plan / waypoint position, cycle
stamps on the tick grid, detected /clock skips, duplicate / dropped cycles. Physical test:
fit dqd = alpha * effort + trend on the 20 neighbouring ticks and check the violating one.
Not recorded by the evaluator, so not checked: per-tick /clock values and receipt order.
Result (arm_continuity_timebox_table.md):
- B smoke: the cycle's effort is +1.05e-3 N m off its neighbours (= KP x 2.11e-5, the whole
  "violation"), but the joint's motion does NOT show it: actual dqd 4.100e-5 vs 4.056e-5
  predicted from the smooth effort (fit rms 1.2e-7) vs 6.25e-5 if the spiked effort had
  acted; q's second differences carry no kick. No dropped / duplicate cycle (all 2 ms apart,
  no identical consecutive state), no /clock-detected skip, cstate stamp = cycle stamp,
  25 ticks from the nearest waypoint (not a trajectory handoff), not a camera capture tick.
  -> B: the plant applied the correct command; only the recorded effort sample is wrong.
- A run 1 ep1 (6e-7 x 2): below the motion test's resolution -- undecided.
- Plant-restart state and the exact publication path of the bad sample: not pursued (timebox).
Interpretation: the gate tripped on a measurement artifact of the cycle stream. The gate is
NOT relaxed: the pre-fixed re-gate runs once, now.

## 03:04 Pre-fixed one-shot re-gate: PASS -> marker written, G0 control 5x2 and B 5x2 started
Control: fresh mask plant (killed and relaunched), then exactly one G0 smoke (masks generated,
ignored) and one B smoke (masks used), no retries (user rule).
Result: both PASS every DSE hard gate incl. arm_continuity (lock violations 0) and every mask
check (86 / 62 frames exact-snapshot, 0 invalid, mirror MAD median 0.0, max 0.0011); 0
inference failures; both smokes put the ball in the bin. Marker
GATE_PASS_MASKS_1e5175afc0f6.json (files m1_regate_g0, m1_regate_b).
Next, one after the other on this plant: g0mask m2_g0ctl_A, m2_g0ctl_B; bmask m3_b_A, m3_b_B.
A violation during these is marked infra-invalid and reported with every episode.

## 03:43 B (oracle tip relation FiLM) vs its same-evaluator G0 control, 2 runs each
Purpose: steps 9-10 -- the model effect of B, separated from the evaluator change.
Control: mask-capable evaluator (marker 1e5175afc0f6), one mask plant for all four runs,
frozen canonical condition (timing-controlled nominal 5, 0.6 s, DSE_BATCH 1); G0 EMA 11400
with masks generated and sent under "_" names (ignored) vs B EMA 11400 with the masks as
policy input; same episodes, same order. eval_B_vs_G0control.md, eval_G0c_ / eval_B_repeat_compare.
Result (C/L/S/B/a):
  G0 control run 1  2/3/1/1/4   run 2  3/4/2/1/4  -> C 5, L 7, S 3, bin 2, abort 8 of 10
  B          run 1  3/3/3/2/3   run 2  3/3/3/2/3  -> C 6, L 6, S 6, bin 4, abort 6 of 10
  Hard gates: G0 control 10/10 episodes PASS; B run 1 5/5 PASS; B run 2 ep2 FAIL no_anomalies
  ("arm: accepted but never EXECUTING", lock violations 0) -> INFRA-INVALID, kept in the
  table; its outcome ("....a") equals run 1's. Without it B is C 6, L 6, S 6, bin 4, abort 5
  of 9. Invalid starts 0 everywhere; 0 inference failures.
  Per episode: ep0 both arms succeed in all runs; ep1 B lifts + secures in both runs, G0c in
  one of two; ep2 G0c lifts in both runs, B in neither; ep3 B puts the ball in the bin in both
  runs, G0c in neither; ep4 all abort.
  First-close geometry (mean of 5; expert): depth G0c -10.0 / -10.7, B -14.1 / -13.6 mm (-22.6);
  vertical G0c 8.4 / 8.2, B 4.4 / 4.4 mm (4.3); pitch G0c 9.4 / 9.3, B 4.0 / 4.1 deg (12.6).
  Rejected waypoints G0c 37 / 46, B 26 / 33.
  Repeat agreement: B's two runs give the same outcome code in all 5 episodes; G0c in 4 of 5
  (ep1). Both arms' repeats still diverge early in policy input (plans 1-7), as before.
  Evaluator effect: G0 control here vs G0 on the unchanged evaluator (t2): L 7 vs 8, S 3 vs 4,
  bin 2 vs 2, abort 8 vs 8 -- no visible shift from the mask path.
  Mask QA only (not a gate): 26 frames of G0c run 1 ep1 and a few elsewhere have empty EE masks
  -- the wrist camera is pressed against a surface there; the plant image shows no fingers
  either (mirror MAD 0), so the masks are right.
Interpretation: with oracle target/fingertip relations as input, B doubles the strict secure
grasps (6 vs 3) and bin placements (4 vs 2) of its own control on this condition and closes
deeper and vertically centred (vertical 4.4 mm = the expert's 4.3). Lifts are equal (6 vs 7).
n = 10 per arm, gains from two of five episodes (1, 3), one loss (2); no significance is
claimed. B is ORACLE: the masks come from the simulator state; not a deployable policy.
