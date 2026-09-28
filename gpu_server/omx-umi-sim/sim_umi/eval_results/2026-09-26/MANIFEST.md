# 2026-09-26 evaluation results

Every number quoted about this day's checkpoints came from one of these files.
They lived in a session-scoped temporary directory until now, which meant the
conclusions could be read but never re-derived.

The conditions differ between runs, and the differences matter more than the
numbers: three of them were changed *because* of what an earlier run got
wrong, so a file from before that change cannot be compared with one from
after it. Each group below says what its condition was.

Checkpoints are from `data/omx/train/omx_sim_visual_v1/2026.09.26/12.25.09/`,
trained on `omx_sim_train.zarr.zip` (25 segments, 6455 frames) with the config
untouched from the previous run except `exp_name`.

## The comparison to read: `rollout_e20`, `e40`, `e60` and `interv_e20/40/60`

One condition, three checkpoints, run back to back:

| | |
| --- | --- |
| preprocessing | CenterCrop(212) → Resize(224), no ColorJitter |
| diffusion seed | 1234, re-seeded before every inference |
| task clock | 600 executed actions = 60 s of policy time |
| reset | the deterministic protocol (PRE_HOME → settle → fixed leg → HOME → settle) |
| placements | the first five training episodes' own ball and bin |
| rollouts | 5 per checkpoint, 4 of 16 actions executed per replan |

`rollout_*.json.gz` carries, per replan: the stage an evaluator would call it,
whether each target was inside the policy's crop, the tool's distance to the
ball with its horizontal and vertical parts, the per-tick projected tool
targets, the whole 16-step plan in absolute pose (`plan_abs`, for the
receding-horizon consistency measurement), the projection correction, and the
true jaw width. `interv_*.json` carries ten placements × three inferences on
one captured observation each.

## `determinism.json` and `obs0/`

Three runs of e40 on one placement, deliberately started from three different
poses, under the deterministic reset. `determinism.json` has the start state
and, per replan, hashes of the observation and of the raw prediction plus what
was made of them. `obs0/run{0,1,2}.npz` is the first observation of each run in
full — the arrays actually sent over the socket — because hashes could say the
three differed but not by how much.

## Earlier conditions, kept because the document cites them

- `rollout_e20b.json.gz`, `interv_e20b_det.json`, `interv_e20b_aug.json` —
  epoch 20 under the **augmented** inference path beside the deterministic one.
  This pair is where the encoder's inference-time RandomCrop and ColorJitter
  were shown to cost about half the directional signal (cosine 0.858 against
  0.575). The rollout there still used a 60 s **wall clock**, which is why it
  reports 234–271 ticks.
- `rollout_ep20.json.gz`, `rollout_ep40.json.gz`, `interv_ep20.json`,
  `interv_ep40.json` — the first pass, before the rollout stopped aborting an
  episode at the first unreachable action and before the tick-based clock.
  Their "0/5, stopped immediately" is an artifact of that abort and should not
  be quoted.

## `ol_*.txt`

Open-loop error over the whole horizon and per step, train and held out. These
run through the policy's normal path, so the encoder's augmentation is on and
the diffusion sampler is unseeded: the numbers carry that noise.

## A label to be careful with

`grasped` in a rollout summary means the jaw closed, not that the ball came
away with it. Whether the ball actually left the table is `stage_ticks` having
any `LIFT` or `TRANSPORT`, and that is 0 of 5 for every checkpoint here.

## `rollout_e60_prefix` and `teacher_forced_e60` — the prefix-only rerun

**Purpose.** The executor's feasibility check did `continue`, so a plan whose
second waypoint was unreachable was executed as first-then-third and the arm
was driven across a hole nobody planned; 46 of 543 plans in the previous
rolling run carried such a gap. This rerun asks how much of the closed-loop
failure that was hiding.

**Control.** Everything else identical to the rolling run: e60, CenterCrop(212)
→ Resize(224) with no ColorJitter, seed 1234 re-seeded before every inference,
the deterministic reset, the same five training placements, K=8 in flight, 600
executed actions. No weight, architecture, encoder or controller-gain change.
The two metric bugs (per-chunk IK rate, per-spin stage ticks) were fixed first
and the old formulas are not reused. `teacher_forced_e60.json` is the control
run: the same checkpoint on the recorded expert observations, no simulator.

**Result.** 0/5 in the bin, 0/5 held, 0/5 LIFT, 1/5 reached GRASP, and all five
stopped on eight consecutive plans with nothing reachable. 324 of 2161
waypoints refused; the valid prefix has median 1 and is ≤2 in 54.2% of plans.
The refusals are not far misses: the median IK residual at the refused
waypoint is 3.0 mm against a 2.0 mm gate, and the raw step from the last
accepted waypoint to the refused one is 0.65 mm at the median. What changes is
the demanded tool pitch. The demonstrations never leave [7.9, 46.3] degrees --
SEARCH is pinned at 46.0 +- 0.1 -- and the rollouts climb monotonically
through it: episode 4 runs 50.5, 59.0, 70.2, 77.8 degrees over successive
fifths. 95.1% of refused targets sit outside the demonstrations' 1--99%
envelope in pitch. The one rollout that stayed inside the band (episode 2,
42.8 -> 29.1 -> 25.9) is the one that reached GRASP and shut the jaw, 6.7 mm
off in XY and 5.2 mm below the ball centre.

In the control, standing in the expert's own states, the same checkpoint asks
for at most 48.4 degrees -- two degrees past the ceiling, never seventy-eight
-- and its valid prefix is 7.6 to 8.0 of 8 on the two placements whose
rollouts abort.

`analyse_e60_prefix.txt` is the full table. The mm/tick chain in APPROACH is
raw 2.36, projected 3.34, commanded 4.51, actually executed 1.00, against the
expert's 4.84.

**Interpretation.** The hole-skipping was not the cause; removing it made the
failure visible instead of driving through it. The closed-loop departure is
one scalar with no restoring demonstration: a systematic over-pitch of a
fraction of a degree per step, which the training set contains no example of
correcting, integrated over a rollout until the pose leaves the arm's 5-DoF
reachable set. Truncated prefixes then re-open the command gap this executor
had closed -- the arm has no waypoint ahead of it for 0.226 s of every 0.540 s
replan, 72.9% of the time -- which is a consequence of the refusals, not a
separate defect.

## `audit_signed_axis_e60.txt` — where the sign flips, and it does not

**Purpose.** Six plans from the moment episode 2's jaw first read shut appeared
to ask for a net rise while the tool fell 14.91 mm over the following 1.5 s.
If the sign reverses between the prediction and the joints, the layer it
reverses at decides whether the fix belongs to the projection or to the
controller.

**Control.** No re-run and no simulator stepping: every number is read from
`rollout_e60_prefix.json.gz`. The IK joint targets in the log are put back
through MuJoCo's forward kinematics to check that the projection reports what
it returns. Nothing was changed -- no gain, no architecture.

**Result.** The sign does not flip anywhere. Over each plan's sent window the
raw, projected, IK-refed-through-FK and commanded net z are equal to the
second decimal, and every IK target FKs back to its projected pose within
0.05 mm. Over the 1.5 s window the command asks for -15.70 mm of z and the
tool delivers -16.52 mm, sitting +0.10 mm from where it was told to be on
average and 2.74 mm away in all.

The apparent +3.15 mm was an error of mine: it was the net z over the whole
16-step horizon, against an actual measured over the 1.5 s that was executed.
Over the part that is actually sent -- k=3 to k=10, the rest being either
already past or beyond the horizon in flight -- those same six plans ask for
-4.52, -2.42, -2.04, -1.34, +1.54, +1.04 mm.

The commanded-against-actual shortfall is the same kind of artefact. Measured
as path length the arm does 42% of the commanded motion in APPROACH; measured
as net displacement over 1.0 s windows it does 14.82 of 16.93 mm, 88%. The
command's own straightness -- net over path -- is 0.42 in APPROACH and 0.28 in
GRASP: it doubles back on itself, and the arm low-passes the doubling back.
The controller is not the problem.

What the audit did find is in the jaw channel. The policy does ask for a real
grasp: episode 2's plans go down to 30.64 mm, the expert's own holding width
being 31.3 mm, and the closing action sits at k=6 -- 0.6 s into the horizon,
inside the k=3..10 window that is sent. But the executor replaces the whole
plan every 0.54 s and drops the jaw events that had not yet come due, so the
narrowest width ever commanded to the gripper was 42.33 mm. The true jaw's
dips to 31.7 mm are overshoot from a command oscillating between 42 and 52 mm,
not a grasp.

**Interpretation.** Two different things, and only one of them is the policy's.
The jaw never closes because the executor discards an action whose moment
falls after the next replan; that is an execution defect, in the layer between
the projected target and the plant, and it is fixable without touching gains
or architecture. The tool never lifts because the policy puts the rise at
k=12, 1.2 s out, where 10 of 48 plans put it inside the executed window at
all -- each replan re-issues a descending near term with the rise pushed out
again. That one is not the executor's.

## `rollout_e60_jawfix_ep2` — the jaw queue given commit semantics, and q logged

**Purpose.** The previous entry claimed the gripper was never commanded
narrower than 42.33 mm. That was wrong, and the correction matters enough to
record: `jaw_cmd_mm` is a plan's *first* jaw action, not the widths it goes on
to command. Replaying the old scheduler offline over the recorded plans shows
it commanded 34.01 mm in episode 2, against the 30.64 mm the policy asked for
and the expert's 31.3 mm holding width. The defect in the executor -- a jaw
action whose instant fell after the next replan was discarded with the plan it
belonged to -- is real, but it was costing about a millimetre, not twelve.

**Control.** One placement, episode 2. Everything else as before: e60,
CenterCrop(212) with no ColorJitter, seed 1234, deterministic reset, K=8, 600
ticks, no gain or architecture change. Two changes went in: the jaw queue now
keeps whatever is due before the new plan's own coverage begins, or within a
0.25 s commit window, whichever is later, and marks it committed so a later
replan cannot move it; and `ee_track` now carries the joint angles and the
tool pitch alongside the tool position, which is instrumentation only.

**Result.** The fix works as designed: 179 events survived a replan that would
have dropped them, 425 came due, 21 passed the 3 mm change threshold and were
sent. The narrowest width commanded is now 33.00 mm and the true jaw reached
32.97 mm -- 1.7 mm from the expert's holding width. Events fire 135 ms after
their own timestamp on average, which is more than one action tick and worth
its own look.

The ball was still not held, and there was still no LIFT. What the log shows
instead is the width channel oscillating: from the first sub-40 mm command the
commanded sequence runs 39.6, 35.1, 48.2, 44.6, 40.3, 36.1, 33.0, 39.8, 34.8,
42.9, 38.8, 46.5, 43.0, 51.1 mm. Every approach to a grasp width is undone by
the next plan, and the trend drifts open. At the moment of the first closing
command the tool was 6.88 mm off in XY, on a ball of 25 mm radius.

The question this run was meant to settle: after the jaw closes, the rise does
**not** move into the near horizon. Over the 47 plans after the first close
its first upward step sits at k=14 at the median, and falls inside the sent
window k=3..10 in 2.1% of them -- against 20.8% before the fix. It recedes.

Actual tool pitch, now measured rather than inferred, runs -42.8 to +47.6
degrees against demonstrations that never leave [7.9, 46.3].

**Interpretation.** With the executor defect removed and the gripper verified
to reach grasp width under closed-loop control, the grasp still fails and the
lift still never arrives. The reading that the previous entry set aside is
restored, now on measured ground rather than on a mis-derived number: what is
missing is in the policy, and it is the same shape in the width channel as in
the pitch channel -- a correct behaviour is predicted at the far end of the
horizon, the near end contradicts it, and nothing in the training set
demonstrates holding the commitment once it has been made.

## `obsaudit_ep2_*` and `teacher_forced_width_e60` — is the policy given the real state?

**Purpose.** Before calling the jaw oscillation and the pitch drift the
policy's own, rule out that the state entering each inference is stale, cached
or reconstructed from a previous action rather than measured now.

**Control.** Episode 2, e60, same deterministic settings. Per replan the
executor now records both observation frames' image and joint stamps, the
simulator's jaw width (evaluation only), the camera-derived width, the width
actually inside the tensor, whether the camera failed and a previous width was
reused, the width currently commanded to the gripper, the tool pitch from FK
of the measured joints, and the tool pitch read back out of the tensor through
`robot0_eef_rot_axis_angle_wrt_start` and the episode's start pose. The
comparison of P0 against the state handed in is the control: the sampler takes
the action chunk as `input_arr[current_idx:]` while the observation window ends
at `current_idx`, so action[0] IS the observation's own state.

The code path was read rather than assumed. `observe()` takes the newest
camera frame and pairs it with the joint state nearest that frame's own stamp
from a 400-deep buffer; the width comes from `jaw_from_camera`, never from the
joint. There is exactly one cache: when the tip detector finds no pixel gap,
`self.last_width` is reused. It is now logged.

**Result.** The state pipeline is clean. The two frames of a window were
always distinct. The camera width fell back on a cached value in 4.5% and 5.2%
of replans, 7 and 10 misses over 176 and 232 frames. The width inside the
tensor sits 0.13 to 0.17 mm from the simulator's jaw on average. The pitch
read back out of the tensor equals the FK pitch of the measured joints to
**0.000000 degrees** in every replan. Image-to-joint stamp skew is 12 ms at
the mean, 48 ms at p95.

The policy's reconstruction of that state is not clean:

| | width error of P0 | |max| | pitch error of P0 |
| --- | --- | --- | --- |
| expert states (teacher-forced, 175 windows) | +0.002 mm | 0.956 mm | -- |
| closed loop, all replans | +3.76 / +1.38 mm | 17.1 mm | -0.21 deg |
| closed loop, jaw actually shut (<40 mm) | **+12.4 mm** | **17.1 mm** | -- |

At replan 27 of run 3 the true jaw is 30.7 mm, the camera reads 30.6 mm, the
tensor carries 30.6 mm -- and the policy's P0 says 47.7 mm. It is told the
gripper is shut and asserts it is open, by 17 mm. Its P8, 0.8 s out, says 34.8
mm: every replan re-issues the same "I am open, I will close shortly" ramp, so
what reaches the gripper is the open early part and the close at the far end
is never held. On the expert's own states the same checkpoint reproduces the
width it was handed to 0.002 mm, including 94 windows with the jaw already
shut.

The pitch channel fails differently: P0's pitch is right to 0.21 degrees, so
the drift there is a small per-step bias integrating over a rollout, not a
misread of the present.

**Interpretation.** The condition set for this check is met: GT, camera and
tensor widths agree, the tensor's pitch equals the measured pitch exactly, and
the policy still asserts an open gripper and a larger pitch. This is closed-loop
inconsistency in the policy, not a plumbing fault. The width channel is the
sharper of the two -- a gross failure to represent the present once the state
leaves the demonstrations -- and it explains the oscillation directly.

Run-to-run spread on one placement was 54, 289, 402, 428 and 601 ticks, which
is the closed-loop sensitivity already recorded in `determinism.json`; two runs
reached GRASP and both are kept.

## `latch2_ep2_*` — holding the gripper command once the camera says it shut

**Purpose.** Separate the jaw's reopening from everything else. If the grasp
fails only because the command oscillates, then holding the command -- and
only the command -- once an observable grasp has formed should let the run
reach LIFT.

**Control.** Episode 2, e60, same deterministic settings, no change to
architecture, gains, dataset or checkpoint. Nothing the policy sees is
touched: the width in the observation stays the camera's live reading, the
picture and pose stay live, and the policy goes on predicting whatever it
predicts. Only what is sent to the gripper is held. The grasp test uses the
magenta-tip width alone -- never the simulator's jaw or its contacts --
sampled at the camera's own 20 Hz rather than at the replan rate, with frames
the detector could not read excluded from the stability window and breaking
the run rather than extending it.

Two bugs in the first attempt, both mine. The stability window was trimmed to
200 ms and then required to span 200 ms, a knife edge that never held, so
nothing latched in three runs. And `close_intent` compared against the last
width that passed the 3 mm send threshold rather than the width the policy was
currently asking for, which lags by up to 3 mm and inverts the comparison.

The condition itself turned out not to be satisfiable as specified.
`close_intent` encodes contact as the command being narrower than the fingers
achieved -- true when something stops them. The collector asks for 0 mm and
lets the ball do the stopping; this policy predicts a width and the fingers
reach it, so the test cannot fire however the margin is set. It is kept,
logged and made optional rather than tuned into a false positive; the runs
below latch on width and stability alone.

**Result.** The latch engaged in 3 of 4 runs, at 37.66, 35.11 and 32.41 mm,
around tick 121--129. The hold is better than the expert's own: 37.63 +- 0.04,
35.03 +- 0.05 and 32.30 +- 0.04 mm held over 71 to 80 s, against the expert's
31.4 +- 0.18.

| | run 2 | run 3 | run 4 |
| --- | --- | --- | --- |
| latched width | 37.66 mm | 35.11 mm | 32.41 mm |
| lift first-k, after latch (median) | 12 | 12 | 12 |
| inside the executed window k=3..10 | 12.6% | 3.7% | 17.1% |
| sent dz per plan after latch | -2.14 mm | -1.83 mm | -3.21 mm |
| tool z after latch | 11.5 -> 91.9 mm | 17.8 -> 74.3 | 19.0 -> 91.1 |
| tool pitch after latch | 29.9 -> -18.0 deg | 29.1 -> -14.8 | 28.1 -> -17.8 |
| ball final z | 24.8 mm | 24.8 | 24.8 |

**Interpretation.** The second branch. The jaw is stable and the lift still
does not come into the near horizon -- median k=12 in every run, no better
than the 20.8% baseline -- and no object was lifted: the ball's final height
is 24.8 mm in all three, which is a 25 mm ball sitting on the table. It did
move 200 to 300 mm horizontally, and the tool did rise 60 to 80 mm after
latching. So the gripper closed beside the ball, pushed it away, and later
rose empty. That is consistent with the 6.88 mm XY error already measured at
the closing moment, and with the latched widths sitting at 32 to 38 mm rather
than at the 31.4 mm the ball itself would impose.

The pitch drift is untouched by any of this: it runs on to -15 and -18 degrees
while the jaw is held perfectly still.

So jaw reopening was not the blocker. What is left is approach precision and
the pitch drift, both of which are the policy's, and both of which fall in
APPROACH -> GRASP -> LIFT.

One caveat by design: the experiment never unlatches, so the policy could not
reopen and try the grasp again. That was the instruction for this diagnostic
and it is not how a final controller should behave.

## `video/` — the failure, watchable

Two rollouts of e60 on episode 2, recorded with `policy_rollout.py --video`.
Left pane is a debug camera on the kinematics copy, posed from the measured
joints and the true ball and bin: ground truth, for looking at, never fed to
the policy. Right pane is the wrist frame after the magenta patches are
painted out. The overlay carries the tick and stage, the tool's height and
pitch with the demonstrations' range beside it, the width the camera reads
against the width the gripper was told, the distance to the ball and its
height, and which step of the sixteen the current plan first rises at.

`e60_ep2_nolatch.mp4` -- 604 ticks, APPROACH 358, GRASP 233, no LIFT. The
right pane here is the whole 320x180 wrist frame; the policy is given the
centre square of it, so this pane shows more than the policy sees.

`e60_ep2_latched.mp4` -- the grasp latch on, engaged at 31.08 mm, which is the
expert's own holding width to within 0.3 mm. 600 ticks, GRASP 470, no LIFT.
The right pane is the 224 crop the encoder actually receives.

What the second one shows, and what no table said as plainly: by tick 467 the
gripper is shut at the correct width and empty, the ball is still on the table
at z=24.8 mm and 74.8 mm away, the tool has risen to 84.5 mm and pitched to
-36.1 degrees -- eighty degrees past where any demonstration goes -- and the
wrist camera is looking at nothing, so the tip detector has lost the patches
and the width channel reads nothing at all. The arm has tipped over backwards
holding an empty grip.

## `geom_ep2_*` and `grasp_corridor_e60_ep2.txt` — was the tool ever in a position to grasp?

**Purpose.** The latch reading is withdrawn: the video shows no secure grasp
was ever formed, so a policy reopening a bad grip is sensible behaviour, not
the fault. The question is whether the arm reaches a good grasp pose, fails to
close, wanders, and closes from a worse one.

**Control.** The no-latch rollout only. Euclidean distance is not used as the
test: the expert holds the ball within 0.61 mm laterally of one pose in the
tool frame, so being near the ball and being able to grasp it are different.
The corridor is built from the demonstrations -- the ball's position in the
tool frame at the instant each expert's jaw starts to shut, and through every
frame it holds afterwards. The true ball pose is used here and only here,
after the fact; it reaches no observation and no command. The existing log
could not answer this (it kept only the scalar distance), so ball position was
added to `ee_track` as evaluation-only instrumentation and the rollout re-run.
Nothing else changed.

**The corridor.** The fingers separate along tool x; their inner faces sit at
tool y = -9.25 mm open, -7.06 mm at 31.4 mm.

| | expert onset | corridor |
| --- | --- | --- |
| lateral (tool x, the closing axis) | -0.62 +- 0.76 mm | [-2.26, +2.20] |
| depth (tool y, the approach axis) | -22.62 +- 0.76 mm | [-23.66, -15.86] |
| vertical (tool z) | +4.30 +- 1.48 mm | [+0.51, +8.19] |
| tool pitch | +12.57 +- 2.38 deg | [+7.91, +17.40] |
| EE speed at the instant it shuts | 0.15 +- 0.05 mm/tick | -- |

The expert holds the ball centre 8 to 13 mm *beyond* the inner finger faces:
the fingers cup a 50 mm ball, they do not pinch it.

**Result.** Across two rollouts, **0 of 8915 and 0 of 10666 samples were inside
the corridor**. One axis is responsible:

| axis | inside its own band | best gap |
| --- | --- | --- |
| lateral | 21.3% / 17.0% | 0.00 mm |
| **depth** | **0.0% / 0.0%** | **14.88 / 16.53 mm** |
| vertical | 1.8% / 1.5% | 0.00 mm |
| pitch | 3.5% / 2.2% | 0.00 deg |

Lateral alignment is good throughout, around -1.2 mm. Depth never once reaches
the band: it runs +23.6 to +2.2 mm and stops, on the far side of the finger
faces, where the expert is at -22.6. The ball ends up 6.1 mm from the tool
origin where the expert keeps it 23.1 mm, and about 12 mm on the near side of
the plane the fingers close in. So the fingers meet in front of the ball and
shove it.

And there is no wandering. The approach is monotonic at 0.02 to 0.07 mm/tick,
and the jaw shuts 0.38 s after the best pose the run ever reaches, having
travelled 3.79 mm, with the geometry 19.08 mm outside the corridor before and
19.20 mm after. In the second run the jaw shut 0.15 s *before* the best
moment. The policy's own plans were converging on a close the whole time --
first-close step 12, 8, 7, 7, 4, 3 over successive replans -- never reversing.
Plan boundaries jump 2.0 to 8.2 mm and add +0.36 to +1.36 degrees of pitch
each, always in the same direction, away from the corridor.

**Interpretation.** Case C: approach pose precision. The corridor was never
entered, so nothing was missed and nothing was mistimed -- the policy closed
at essentially its own optimum, and its optimum is 15 to 17 mm short in depth
and 11 degrees off in pitch. Case D is superficially true, since the close did
happen outside the corridor, but it is not a separate defect: the trigger is
correct relative to the trajectory the policy flies, and the trajectory is
what is wrong. A and B are ruled out by the 0.38 s and 3.79 mm between the
best pose and the close.

The depth shortfall and the pitch offset are the same error seen before from
another side: a tool held 16 degrees too steep puts the ball where this one is.

## `grasp_transition_*` and `teacher_forced_grasp_e60` — how many grasps does this dataset contain?

**Purpose.** The rollout never enters the grasp corridor and fails on depth and
pitch. Before proposing data, establish how much variety the twenty clean
demonstrations actually hold in that transition, and whether the checkpoint
reproduces it when it is standing in the expert's own states.

**Control.** No new data, no dataset change, no training, no architecture or
executor change. The expert windows are t_g-1.5 s to t_g+0.5 s, aligned on the
instant each jaw starts to shut, everything in the tool frame from the
demonstrations' own recorded ball pose. Teacher-forced uses the same e60, the
same deterministic preprocessing and seed 1234, on the expert's own frames.

**Result, and it corrects an earlier reading of mine.** The transition is not a
coupled lowering of the nose while inserting. The nose is already down:

| relative to the close | pitch | depth | EE speed |
| --- | --- | --- | --- |
| -1.5 s | +12.42 +- 2.38 deg | -13.44 +- 4.60 mm | 5.48 mm/tick |
| -1.0 s | +12.41 +- 2.38 | -19.12 +- 3.26 | 5.59 |
| -0.5 s | +12.37 +- 2.38 | -22.18 +- 1.55 | 5.33 |
| 0 | +12.57 +- 2.38 | -22.62 +- 0.76 | 0.148 |

The pitch changes by **+0.16 +- 0.05 degrees** across the whole second before
the close. What happens is an insertion at fixed pitch, 13 mm to 23 mm, with a
hard stop in the last 0.3 s (5.33, 2.69, 1.06, 0.44, 0.15 mm/tick), and the
spread across episodes funnels from 4.60 mm to 0.76 mm. The path length equals
the net displacement to 1.00 +- 0.00 in every one of the twenty: a straight
line, twenty times.

Placement does not change it. Ball radius spans 65 to 294 mm and azimuth -135
to -31 degrees, and the strongest correlation with any transition feature is
0.50 (depth change against azimuth); pitch change is 0.16 +- 0.05 regardless.

Counting honestly: 6153 training windows, 620 of them starting within 1.5 s of
a closing jaw -- but **20 independent transitions**, the 620 overlapping by
96.8%. The window count is the same twenty events resampled.

Given the expert's own observations the checkpoint reproduces that transition.
Pitch within 0.4 degrees throughout, depth within 2 mm, and it plans the close:
narrowest jaw in the horizon 28.83 mm against the expert's 27.96. The one thing
it does not reproduce is the stop -- 4.86 mm/tick at the end of the horizon
where the expert is at 0.15.

Where the rollout leaves that manifold is exact, and it is not at the grasp:

| relative to the close | expert pitch | rollout b | rollout c |
| --- | --- | --- | --- |
| -6.0 s | +44.57 +- 1.30 | +39.49 | +38.58 |
| -4.0 s | +30.09 +- 2.61 | +33.03 | +32.96 |
| -3.0 s | +22.12 +- 2.79 | +30.45 | +29.86 |
| -2.0 s | +14.87 +- 2.60 | +28.49 | +27.43 |
| -1.0 s | +12.41 +- 2.38 | +28.12 | +27.35 |
| 0 | +12.57 +- 2.38 | +29.22 | +28.40 |

The expert lowers the nose from 44.6 to 12.4 degrees over six seconds and then
holds it flat. The rollout tracks that descent as far as -4 s and then stalls
at 28 degrees, sixteen short, and never resumes. It spends **0 of 2076 and 0 of
2010 samples below 20 degrees**, where the expert spends its last 2.66 +- 0.37
seconds there. By depth the rollout is +5.0 sd out at -1.5 s and +33.6 sd at
the close.

**Interpretation.** Case A. The twenty transitions are very nearly one path;
the checkpoint reproduces that path from the expert's own states; the rollout
fails because it never completes the pitch descent that puts it on the path,
and the dataset contains no state in which a stalled descent is resumed. The
failure begins three to four seconds before the grasp, not at it.

`grasp_transition.png` overlays all twenty: a funnel in depth, twenty flat
lines in pitch, and a phase plot that is twenty horizontal segments.

### Addendum: the support the proposal assumes is missing, counted

The proposal above rested on an assertion that the dataset holds no example of
a stalled pitch descent being resumed. Counted over all 6493 expert frames:

Frames at pitch 25--32 degrees with the ball at tool-frame depth 0 to +10 mm --
the rollout's own state when it closes -- number **0**. Loosened to depth -5 to
+15 mm, still **0**.

The pitch bands the rollout parks in are pure transit. Between 20 and 30
degrees, the fraction of expert frames whose pitch is changing by less than
2 deg/s is **0.0%**: the expert never holds the tool still in pitch there, it
passes through. A tool parked at 28 degrees is a state the demonstrations do
not contain at any depth.

And what support there is points both ways. Of the 324 open-jaw frames between
25 and 32 degrees, 52.8% are descending and the rest are rising -- APPROACH on
the way down and RETREAT on the way back up, sharing the band. The mean pitch
rate there is +0.02 +- 8.77 deg/s, so the proprioceptive state alone carries no
signal about which way to go; only the picture separates them. That is thin
support for a vision-conditioned decision: 20 episodes, 324 frames, half of
them the wrong direction.

## `phase_ambiguity_e60` — is the band actually ambiguous to the policy?

**Purpose.** I proposed that between 25 and 32 degrees APPROACH and RETREAT
share the band with nothing but the picture to separate them, and that the
support for that visual decision is thin. That was a hypothesis about the arm's
state, not about the policy's input, and it needed testing against the whole
observation before any data was built on it.

**Control.** The same e60, deterministic preprocessing, seed 1234, on the
expert's own frames: 171 APPROACH and 153 RETREAT observations at pitch 25-32
degrees with the jaw open. The measure is the sign and size of the predicted
pitch change over the first 0.8 s of the horizon. Three passes: every sample;
then only pairs whose arm state is as close as the dataset allows; then the
same pairs with the pictures swapped between them. Nothing was trained,
generated or changed.

**Result. The hypothesis is wrong.** The policy separates the two phases
perfectly and it does so from the picture.

| | predicted pitch rate | sd | correct sign |
| --- | --- | --- | --- |
| APPROACH (expert -7.98 deg/s) | -7.60 | 0.30 | 100.0% |
| RETREAT (expert +9.15 deg/s) | +9.57 | 0.15 | 100.0% |

Not one sample of 324 falls inside +-1 deg/s. On the 30 pairs whose arm states
differ by 9.6 mm in x and 0.75 degrees in pitch, it is still 100% and 100%,
separated by 17.29 deg/s. And the swap settles which input carries it:

| observation | predicted pitch rate |
| --- | --- |
| APPROACH state + APPROACH picture | -7.63 |
| APPROACH state + RETREAT picture | **+8.37** |
| RETREAT state + RETREAT picture | +9.62 |
| RETREAT state + APPROACH picture | **-6.34** |

Changing only the picture moves the answer by 16.0 deg/s against a 17.3 deg/s
gap between the phases, and flips the sign in **100%** of pairs. The answer
follows the picture, not the arm.

What happens in the rollout is the opposite of ambiguity -- it is collapse:

| | plans starting at 25-32 deg | predicted pitch rate | downward |
| --- | --- | --- | --- |
| rollout b | 20 | **-0.94 +- 2.20** | 40% |
| rollout c | 14 | **-1.87 +- 2.54** | 71% |

Eight to ten times smaller than either expert mode, and not consistently
signed. It is not uniform: over the same 0.8 s those plans still ask for -9.78
and -13.68 mm of height, so the tool is still being driven down while the
pitch command has gone flat.

**Interpretation.** Case C. Phase discrimination from vision is learned, and
learned sharply. What fails is the prediction itself once the joint state
leaves the demonstrations -- the same pitch value, but reached with the ball
12 mm on the wrong side of the finger plane and a history no demonstration
contains, and the pitch channel goes to zero. So the missing coverage is not
of the APPROACH/RETREAT contrast, which is well covered; it is of states off
the clean manifold.
