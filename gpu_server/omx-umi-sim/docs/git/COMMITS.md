# Local commit history (branch omx-gpu-baseline, on top of upstream UMI main d095ba9)

This package is the tree of HEAD 3c3d9aabee992c34a1a3b6e4fda8b04e43634569 plus the files listed in PACKAGE_CONTENTS.md.
The commits exist only in the local repository on the training host (never pushed).

| # | commit | date | subject |
|---|---|---|---|
| 1 | `84c2a3b` | 2026-09-21 10:11 | Add OMX GPU pipeline: CPU sync, processed_v1 -> UMI zarr, training, inference |
| 2 | `b256b76` | 2026-09-21 10:16 | Document the CPU -> GPU sync layer |
| 3 | `30aa574` | 2026-09-21 10:19 | Keep the processed/v1 namespace in the GPU mirror path |
| 4 | `6bef46d` | 2026-09-21 11:15 | Make the GPU a strict gate: fail on broken CPU output instead of crashing |
| 5 | `7bbe9ea` | 2026-09-21 11:18 | Document the GPU validation gate |
| 6 | `dc34568` | 2026-09-21 11:26 | Detect re-published sessions instead of skipping them |
| 7 | `9efbfa5` | 2026-09-21 11:57 | Accept CPU-repaired rows, and put the validity rule in exactly one place |
| 8 | `de8c18c` | 2026-09-21 12:00 | Add the CPU/GPU handoff contract |
| 9 | `7e83048` | 2026-09-21 12:13 | Validate the CPU handoff contract, and fix the trajectory cross-check |
| 10 | `2db3729` | 2026-09-21 12:19 | Report the Stage A integration run on real CPU data |
| 11 | `bea4444` | 2026-09-21 12:30 | Record the .superseded cleanup in the Stage A report |
| 12 | `dda9863` | 2026-09-21 12:41 | Upgrade wandb so the new API key format works, and log in |
| 13 | `d8983c9` | 2026-09-22 12:25 | Generate the GPU -> Jetson handoff bundle from code, not from documentation |
| 14 | `0d9d30d` | 2026-09-22 12:29 | Document the GPU -> Jetson runtime contract |
| 15 | `d620add` | 2026-09-22 12:55 | Package the Jetson handoff as a single self-contained zip |
| 16 | `b7b59b5` | 2026-09-22 13:45 | Add the Stage A checkpoint smoke test and the Jetson source snapshot |
| 17 | `6f7ad95` | 2026-09-22 13:51 | Add the Jetson-side setup guide |
| 18 | `4900d03` | 2026-09-22 14:00 | Fix the smoke test's two device-dependent assertions |
| 19 | `12d57ad` | 2026-09-22 14:19 | Make the handoff actually installable on a Jetson |
| 20 | `f57e922` | 2026-09-22 14:32 | Verify the handoff against a JetPack-era torch, and sign-post the environment |
| 21 | `25bf166` | 2026-09-22 14:36 | Connect the handoff's entry points to the procedure |
| 22 | `a2d7aef` | 2026-09-22 14:43 | Stop the handoff docs from carrying values that go stale |
| 23 | `6b42bd4` | 2026-09-22 14:46 | Audit the handoff mechanically instead of by memory |
| 24 | `3f7dea3` | 2026-09-22 15:11 | Give the Jetson a latency budget, not just a latency number |
| 25 | `acb45b4` | 2026-09-22 15:13 | Name the receding-horizon stride the way the repo names it |
| 26 | `fd0f4c6` | 2026-09-22 15:26 | Point the Jetson at a CUDA wheel, and stop the smoke from hiding a CPU one |
| 27 | `dab4ff3` | 2026-09-22 15:58 | Audit the copy-paste message too, not just the archives |
| 28 | `b57070d` | 2026-09-22 16:42 | Write down the Orin bring-up, including what we got wrong |
| 29 | `6b5276d` | 2026-09-22 17:41 | Add the third FOV arm: a ViT that takes a rectangle |
| 30 | `c9cbf24` | 2026-09-22 17:54 | Refuse to build an FOV experiment on the wrong source aspect |
| 31 | `5c696b0` | 2026-09-22 18:12 | Collect what the GPU side needs from the CPU side |
| 32 | `ea0c7ed` | 2026-09-24 10:48 | Carry MuJoCo demos through the real UMI dataset path |
| 33 | `c6b5a63` | 2026-09-24 11:03 | Put signal in the axes the demonstrations were flat in |
| 34 | `69063a8` | 2026-09-24 11:29 | Match the scene to the room, and the gripper to the real robot |
| 35 | `eaccdcd` | 2026-09-24 11:37 | Read the collector's jaw off its camera, then hide the cue |
| 36 | `02afa6d` | 2026-09-24 11:44 | Train on the width the collector can actually measure |
| 37 | `40ba78f` | 2026-09-24 11:52 | Recollect against the real-like scene |
| 38 | `605beef` | 2026-09-24 12:18 | Swap the parallel jaw for the pivot one it should have been |
| 39 | `ce72138` | 2026-09-24 16:33 | Take the grasp failure apart before touching friction |
| 40 | `c48d8e4` | 2026-09-24 16:41 | Follow the finger's contour instead of flattening it |
| 41 | `a5bf480` | 2026-09-24 16:49 | Model the finger as a surface, and record what the width command keeps breaking |
| 42 | `8514625` | 2026-09-24 17:00 | Give the jaw the controller the real one has, and an object its cavity can hold |
| 43 | `2bd54ea` | 2026-09-24 17:39 | Match the camera to the footage instead of to a guess |
| 44 | `4aad580` | 2026-09-24 19:13 | Point the wrist camera where the footage points it |
| 45 | `b732698` | 2026-09-24 19:21 | Give the camera a room to look at, and record what it still cannot see |
| 46 | `85b0d3f` | 2026-09-24 19:46 | Fix the wrist camera against the collector's own photo |
| 47 | `bd007ac` | 2026-09-24 19:47 | Record the camera choice and retire the solved blocker |
| 48 | `6f00734` | 2026-09-24 20:12 | Measure the bin clearance without disturbing it |
| 49 | `245ceff` | 2026-09-24 21:53 | Put the real arm under the gripper, and ROBOTIS's controllers on top of it |
| 50 | `a1c3aae` | 2026-09-24 22:02 | Run the demo through MoveIt, and see what it does not do yet |
| 51 | `2a5260a` | 2026-09-25 16:20 | Grasp the ball, with the reason the last object could not be grasped |
| 52 | `263c6ac` | 2026-09-25 21:50 | Give MoveIt the room it is planning in, then place the ball in the bin |
| 53 | `8e9e9cf` | 2026-09-25 21:59 | Stop the camera cutting holes in what it is looking at |
| 54 | `a07cef4` | 2026-09-25 22:15 | Take only the magenta, and give the raw stream the camera's real shape |
| 55 | `d52adda` | 2026-09-25 22:21 | Fill the patch from its own neighbourhood, not from one averaged colour |
| 56 | `93a121e` | 2026-09-25 22:26 | Fill the patch with the fingertip it is stuck to |
| 57 | `e5bb1a6` | 2026-09-25 22:50 | Close one loop from the trained checkpoint to MuJoCo and back |
| 58 | `cd3573e` | 2026-09-25 23:27 | Render the policy's picture from the plant itself |
| 59 | `f2e0bda` | 2026-09-25 23:38 | Take the gripper width off the camera, not off the joint |
| 60 | `aba7525` | 2026-09-26 00:10 | Read the gripper width off a picture taken now |
| 61 | `d66466c` | 2026-09-26 00:24 | Do not throw away the tip the ball has nearly covered |
| 62 | `196f2cb` | 2026-09-26 00:45 | Put the patch where the ball it is holding cannot cover it |
| 63 | `67f7005` | 2026-09-26 08:16 | Split the action error into units a person can judge |
| 64 | `9fed538` | 2026-09-26 08:34 | Replay a saved episode, and watch it from outside |
| 65 | `c94012b` | 2026-09-26 08:50 | Make the expert look before it moves |
| 66 | `cb0dd1a` | 2026-09-26 09:12 | Audit the demonstrations against what they could see |
| 67 | `565e4b2` | 2026-09-26 09:39 | Prove the goal pose reaches nothing the policy sees |
| 68 | `c7ee8e5` | 2026-09-26 09:49 | Record on the grid the dataset says it is on |
| 69 | `9690a03` | 2026-09-26 10:11 | Put both halves of an observation on one clock |
| 70 | `e5650b2` | 2026-09-26 10:31 | Take one row every two pictures, not every tenth of a second |
| 71 | `1bfbce6` | 2026-09-26 10:51 | Walk the grid forward, never re-phase it |
| 72 | `2b2178a` | 2026-09-26 11:13 | Check acquisition and occlusion apart from each other |
| 73 | `dc4b020` | 2026-09-26 11:20 | Ask the encoder where the ball is, before trusting it with the task |
| 74 | `859b0f4` | 2026-09-26 12:31 | Take the randomness out before asking whether the policy sees |
| 75 | `9b64369` | 2026-09-26 13:28 | Stop the rollout on the task's clock, and say where it stalled |
| 76 | `d585099` | 2026-09-26 13:32 | Tell the grasp apart from the lift, and record where the ball was let go |
| 77 | `a6c5b06` | 2026-09-26 14:33 | Ask why the approach takes 580 ticks when the expert takes 72 |
| 78 | `334ae12` | 2026-09-26 15:47 | Measure whether the policy agrees with the plan it made four ticks ago |
| 79 | `74cfab1` | 2026-09-26 15:58 | Arrive at HOME the same way every time |
| 80 | `43c12ed` | 2026-09-26 16:11 | Reset the rollout by protocol, and record what still differs |
| 81 | `d05a7ac` | 2026-09-26 17:06 | Keep the measurements, not just the conclusions |
| 82 | `0c43d68` | 2026-09-26 17:25 | Keep a trajectory in flight while the next one is being thought about |
| 83 | `56e5d07` | 2026-09-26 17:42 | Count ticks and IK refusals as they now happen |
| 84 | `b4b3136` | 2026-09-26 18:01 | Stop at the first waypoint the arm cannot reach |
| 85 | `86be080` | 2026-09-26 18:13 | Find out what the arm is actually being asked to do |
| 86 | `adde7ad` | 2026-09-26 18:24 | Follow one axis through every layer, and find the jaw is dropped |
| 87 | `f93713f` | 2026-09-26 18:33 | Let a jaw action outlive the plan that asked for it |
| 88 | `4787431` | 2026-09-26 18:59 | Check the state that reaches the policy, and find it is the right one |
| 89 | `92190f2` | 2026-09-26 19:34 | Hold the gripper command, and find the lift still does not come |
| 90 | `4f727bb` | 2026-09-26 20:03 | Record the rollout so the failure can be watched |
| 91 | `12da8ef` | 2026-09-26 20:19 | Ask whether the tool was ever in a position to grasp, and find it was not |
| 92 | `3a2ad14` | 2026-09-26 20:30 | Count the grasps, and find there are twenty of one |
| 93 | `7c578ac` | 2026-09-26 20:37 | Count the states the proposal claims are missing |
| 94 | `e6c20b3` | 2026-09-26 20:44 | Test my own ambiguity hypothesis, and refute it |
| 95 | `572bb42` | 2026-09-26 20:56 | Command each action early enough to be reached on time |
| 96 | `b0aa756` | 2026-09-26 21:47 | Demonstrate the way back onto the manifold |
| 97 | `4aa3412` | 2026-09-26 21:53 | Measure how much of the corrective set is actually corrective |
| 98 | `d344500` | 2026-09-26 22:27 | Make two runs on different-sized datasets comparable at the same step |
| 99 | `c8308fe` | 2026-09-26 22:31 | Count training updates with a counter that means it |
| 100 | `00756d1` | 2026-09-27 02:34 | Fill the empty support, and watch the grasp geometry move |
| 101 | `ad87c92` | 2026-09-27 03:34 | Make a step-N checkpoint mean N applied updates, in every part |
| 102 | `b4e41e8` | 2026-09-27 03:42 | Evaluation only: start each episode from a verified fresh observation |
| 103 | `987ebe4` | 2026-09-27 03:44 | Evaluation only: keep the evidence when a start is not ready |
| 104 | `a721932` | 2026-09-27 06:16 | Evaluation only: home the arm before placing the bodies, and check them |
| 105 | `2943963` | 2026-09-27 06:17 | Evaluation only: name the infra-failure frame after its job |
| 106 | `319f890` | 2026-09-27 08:31 | Analysis only: judge starts and grasps on what actually happened |
| 107 | `2c5e2d1` | 2026-09-27 08:31 | Definitive overnight experiment: training, evaluation, summary |
| 108 | `d2e75b9` | 2026-09-27 08:32 | Manifest the definitive results; flag the invalid starts in the historical one |
| 109 | `b63c39a` | 2026-09-27 08:59 | Analysis only: take v2_11400's nominal failures apart, and replay them |
| 110 | `f08a08e` | 2026-09-27 09:06 | Analysis only: show the policy's masked input in the replay videos |
| 111 | `b131a99` | 2026-09-27 09:14 | Analysis only: where the tip patch sits, and since when |
| 112 | `3ea849c` | 2026-09-27 09:59 | FOV ablation, preflight only: geometries, rectangular ViT, init, config |
| 113 | `a8d4dbf` | 2026-09-27 09:59 | FOV journal: correct the entry times (they were written ahead of the clock) |
| 114 | `b670f8b` | 2026-09-27 10:29 | FOV ablation, pre-training: datasets, data order, evaluator instrumentation |
| 115 | `c259153` | 2026-09-27 10:33 | Keep the AMP probe's own fields when other probes write first |
| 116 | `0352476` | 2026-09-27 10:36 | FOV journal: smoke results |
| 117 | `3beba56` | 2026-09-27 10:40 | FOV: production launch record, evaluation phases, analysis script, pre-registered G0 regression rule |
| 118 | `6331d00` | 2026-09-27 12:00 | FOV: G1/G2 training complete, all checkpoints audited PASS |
| 119 | `57dd304` | 2026-09-27 15:15 | Evaluator: take every added measurement off the inference/execution path |
| 120 | `bf95c7d` | 2026-09-27 15:19 | FOV journal: v1 regression failure and cause, v2 evaluator, pre-registered recovery rule; offline FOV post-processing |
| 121 | `2170bf3` | 2026-09-27 15:49 | FOV journal: v2 G0 re-evaluation -- latency restored, episodes still branch |
| 122 | `0ef875e` | 2026-09-27 16:00 | FOV journal: the evaluator is timing-dependent through its observation pairing |
| 123 | `f2f983c` | 2026-09-27 16:15 | Evaluator: build the observation pair on the simulation clock, as training did |
| 124 | `ffc0e76` | 2026-09-27 16:19 | Evaluator: when a dropped frame leaves no exact [t-0.1, t] pair, wait for the next frame |
| 125 | `025c1aa` | 2026-09-27 16:26 | Evaluator: align observations against complete stream buffers filled off the main loop |
| 126 | `abc9201` | 2026-09-27 16:32 | Evaluator: joint states for observation alignment from a separate recorder process |
| 127 | `48db6d3` | 2026-09-27 16:39 | FOV journal: observation contract fix iterations; G0 repeat criteria registered before the runs |
| 128 | `5e9843c` | 2026-09-27 16:41 | FOV journal: correct the times of the observation-fix entries (16:05-16:35, not 16:30-17:50); registration committed 48db6d3 before the 16:39 start |
| 129 | `29cb0be` | 2026-09-27 16:47 | FOV: repeat_compare.py -- two evaluations of one checkpoint, plan by plan |
| 130 | `9376944` | 2026-09-27 16:59 | FOV journal: action-side root cause -- goals timed against a stale node clock (recorded, not changed during the repeats) |
| 131 | `df418e1` | 2026-09-27 17:44 | FOV: G0 x2 repeats with the observation fix do not converge; step/JTC audit and stream-gap tools |
| 132 | `9594c8f` | 2026-09-27 17:55 | step_audit: record the simulator's per-update state (/mujoco_actuators_states) and raw streams; case selection; clean shutdown |
| 133 | `2a1a029` | 2026-09-27 18:13 | FOV journal: G1/G2 rough screening rule registered before the runs; step audit analyzer |
| 134 | `a052fee` | 2026-09-27 18:17 | DSE audit: controller cycles skip exactly on 1-ns-short clock ticks; offset 1 otherwise; goal installation can lag |
| 135 | `4889d7a` | 2026-09-27 18:19 | DSE design draft: clock ownership, contracts, virtual action age options, open decisions |
| 136 | `6f3a102` | 2026-09-27 18:24 | DSE design: user's decisions (A, rule-derived cadence, ResetWorld perturbed start, 500 Hz kept) |
| 137 | `dbb4b1d` | 2026-09-27 18:40 | DSE design: sensor-ready barrier (camera trigger lives in the controller cycle) and the L_v timeline with per-plan checks |
| 138 | `3aadece` | 2026-09-27 18:43 | DSE: first implementation (not yet run) -- paused tick stepping, exact-state observations, sensor-ready barrier, takeover confirmation, per-plan L_v timeline checks; camera phase test |
| 139 | `e204ef3` | 2026-09-27 19:12 | DSE hard gates before any outcome (timeline, arm/jaw continuity, exact obs ticks, JTC takeover, no anomalies); full runs refused without a gate pass for the evaluator code hash; camera test judges expected vs actual capture ticks and repeat identity |
| 140 | `71c4d7e` | 2026-09-27 19:23 | FOV journal: G1/G2 rough screening -- both within the G0 spread by the registered rule, no provisional selection |
| 141 | `224ccec` | 2026-09-27 19:25 | FOV journal: camera capture ticks -- exact within a run only with single steps; never identical across repeats under the current plugin |
| 142 | `019f737` | 2026-09-27 19:28 | run_eval_dse.sh: the busy-check looks at python processes only (a shell mentioning the names matched itself) |
| 143 | `aa0d982` | 2026-09-27 19:30 | DSE: callbacks named _on_* (rclpy.Node's own _clock shadowed the /clock callback) |
| 144 | `7ee5aca` | 2026-09-27 19:31 | DSE design: proposal for a deterministic sim-state camera trigger (pre_step, step counter, reset anchor) |
| 145 | `9efdb03` | 2026-09-27 19:42 | Camera plugin sim-state trigger + paired joint snapshot (overlay patch, DSE plugin config, launch selector); DSE uses the reset-anchored capture schedule and the paired snapshot as its state source; camera test for both triggers |
| 146 | `c05893b` | 2026-09-27 19:43 | Per-call wall-time breakdown (service round trip / clock wait / cycle-message wait) in the step tests and in the DSE; camera test records snapshot-vs-cycle differences |
| 147 | `5d49742` | 2026-09-27 19:46 | FOV journal: camera plugin patched and verified -- capture ticks deterministic and identical across repeats, paired snapshot exact; per-call wall times |
| 148 | `e793389` | 2026-09-27 19:48 | DSE: record the policy's exact input (sha1 per plan, raw low-dim) and raw action output per episode; first smoke with the patched camera passed every hard gate |
| 149 | `de19252` | 2026-09-27 19:50 | DSE smoke s3 (G0 nominal ep0, patched camera, policy I/O recorded): every hard gate passes; gate marked for the evaluator code hash |
| 150 | `cd63146` | 2026-09-27 20:14 | DSE: capture schedule counted in issued physics steps from the reset stamp (a missing /clock message desynced the message-counted one); missing /clock messages recorded as anomalies; JSON written after every episode; a JTC hold after the old trajectory's last point allowed and counted separately |
| 151 | `9a3a567` | 2026-09-27 20:19 | FOV journal: plan-0 observation differences -- stale snapshot kinematics under back-to-back steps (fixable at capture) and a <=3 px renderer nondeterminism (blocker for bitwise equality) |
| 152 | `dd5b409` | 2026-09-27 20:29 | Camera capture recomputes kinematics + camlight for this tick's qpos (image and joint snapshot are the same tick under back-to-back steps); /clock drain barrier after pause / reset in the DSE and the test harness |
| 153 | `716896b` | 2026-09-27 20:31 | FOV journal: capture fix verified; renderer noise tolerated (policy output changes at float32 ulp, no discrete decision changes) |
| 154 | `4bf12cc` | 2026-09-27 20:38 | FOV journal: DSE G0 ep0 x2 -- plan-0 observation and policy output reproduced; trajectories part from the first takeover by 1e-12 rad (float tfs from absolute times) |
| 155 | `55ba046` | 2026-09-27 20:45 | DSE on reset-relative integer ticks: time_from_start = (send tick - takeover tick) x PHYSICS_DT_NS with every tick derived from the executor's own durations (checked integral); no tolerance anywhere; jaw firing and waypoint retirement on ticks; timeline gate records the in-flight trajectory's end tick and JTC restart ticks and allows a hold only strictly after the end; compare adds EE trajectory and the first command |
| 156 | `45be8ed` | 2026-09-27 20:49 | FOV journal: integer-tick DSE reproduces plan-0..4 policy I/O, the first command and the first 1308 ticks; the loops then part on renderer noise; gate fails only on restarts at the trajectory end tick |
| 157 | `412b25d` | 2026-09-27 20:53 | Evaluator redefined as timing-controlled (renderer noise not controlled); hold at/after the trajectory end tick allowed; G0 x2 residual-variance runs and the stability rule registered before running |
| 158 | `b9bbb7c` | 2026-09-27 20:59 | Correct timestamps written ahead of the clock (journal / design / docstrings) |
| 159 | `a22ed07` | 2026-09-27 21:05 | Gate smokes: s4 caught a dropped-/clock controller skip (timing-dependent); s5 passes every gate; marked |
| 160 | `244661f` | 2026-09-27 21:05 | FOV journal: correct a timestamp |
| 161 | `a241a1e` | 2026-09-27 21:06 | TCE repeat summary (registered stability rule) and mode-aware repeat comparison |
| 162 | `80184aa` | 2026-09-27 21:35 | Replanning cadence = steps_per_inference (6) action steps per inference -- the chunking contract; the 0.3 s rule-derived cadence was a design error (found by the user); nominal comparison helper |
| 163 | `47b3d72` | 2026-09-27 21:37 | run_eval_dse.sh: DSE_BATCH selects steps per call (logged); smoke s6 (0.6 s cadence) nominal ep0 SUCCESS but one dropped /clock |
| 164 | `3d616cf` | 2026-09-27 21:39 | Gate at the 0.6 s cadence with one step per call (s7 passes; s6 dropped a /clock at 5 per call); nominal ep0 now succeeds |
| 165 | `a291b3d` | 2026-09-27 21:49 | G0 0.6 s nominal run A recorded; nominal-only phase; nominal repeat launched |
| 166 | `c65c5b1` | 2026-09-27 21:58 | FOV journal: G0 nominal reproduces on the timing-controlled evaluator (registered rule passes: agreement 5/5 on lifted, bin, abort) |
| 167 | `a35cd58` | 2026-09-27 21:58 | FOV journal: correct a timestamp (21:58) |
| 168 | `1bfcc78` | 2026-09-27 22:05 | Frozen canonical condition for the FOV comparison (0.6 s timing-controlled nominal 5; separate from the 0.8 s deployment contract); G1/G2 nominal phases |
| 169 | `0c9c86d` | 2026-09-27 22:31 | FOV comparison on the frozen condition, run 1: G0 > G1 > G2 on nominal (lifted 4/2/1, bin 1/0/0); second runs of G1 and G2 follow |
| 170 | `49eb5dc` | 2026-09-27 22:55 | FOV comparison, frozen condition, run 2: G0 > G1 > G2 reproduces (lifted over two runs 8/4/2 of 10); G0 stays the geometry |
| 171 | `14affc8` | 2026-09-27 23:14 | FOV journal: demos can be phase-segmented from the gripper alone (91/91; aligned with the expert's stages) |
| 172 | `45a3a41` | 2026-09-28 00:13 | Aux-supervision data prep: exact row mapping, timing labels, ORACLE target/EE masks (G0); no training |
| 173 | `63048c5` | 2026-09-28 00:56 | Aux ablations A (timing aux) and B (oracle tip relation FiLM): implementation, unit tests, twin gate PASS |
| 174 | `e13718c` | 2026-09-28 02:50 | Ablation A evaluated (timing-controlled nominal 5 x2); B's mask-capable evaluator prepared; renderer proven identical |
| 175 | `e5a10d4` | 2026-09-28 02:57 | B mask evaluator: masks exact in both smokes; B smoke hit a sporadic single-tick arm_continuity violation (re-run clean) -- gate not marked, stopped for a decision |
| 176 | `d389856` | 2026-09-28 03:04 | arm_continuity timebox: the single-tick violation is a logged-effort artifact (motion follows the correct command); one-shot re-gate on a fresh mask plant PASS, marker written |
| 177 | `3c3d9aa` | 2026-09-28 03:43 | B (oracle tip relation FiLM) vs same-evaluator G0 control, nominal 5 x2 each: strict 6/10 vs 3/10, bin 4/10 vs 2/10, lifted 6 vs 7; B run 2 ep2 infra-invalid (goal never EXECUTING), reported |
