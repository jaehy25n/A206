# Deterministic sim-time evaluator (DSE) -- design, before implementation

Status: DESIGN ONLY (2026-09-27 evening). Nothing here is implemented. Four decisions
are open (section 9). The asynchronous rolling evaluator stays as it is, for runtime
robustness; the DSE is for policy / FOV / representation A-B comparison.

## 1. Why

Two asynchronous G0 runs with an exact observation contract still part (journal 17:45):
inputs differ at plan 0 in 21/21 episodes, tool positions part > 2 mm by plan 3, and the
pre-registered agreement criteria fail. What still depends on wall time (measured):

| source | measured | where |
|---|---|---|
| start state | joints <= 0.001 deg, tool 0.1-2 um, 27-833 px at plan 0 | HOME held by the controller in real time |
| goal takeover delay S' (stale node clock) | median 0.267 s, q05-q95 0.18-0.39 | send(): now() frozen during collect(); time_from_start = t_send - now |
| replan cadence | period median 0.55 s, 0.45-0.65 | next pair waits on frames that arrive in wall time |
| request latency L | median 0.216, q05-q95 0.194-0.228 | k* = 5 in 98.9% (k* = floor(10(L+0.22)) + 1) |
| extra frame waits | 18% / 58% of plans (rep1 / rep2) | keep-last-1 image subscription blocked during IK |

## 2. What the plant and the controller guarantee (isolated audit, journal 17:44-18:10)

- ResetWorld restores qpos/qvel/ctrl/warm-start, applies joint and free-joint overrides,
  keeps sim time continuous. From it, paused one-tick stepping reproduces every joint's
  q and qd bitwise across repeats.
- The command in effect in physics step i+1 is exactly the arm controller's output of the
  update on tick i (offset 1; residual <= 2.2e-16 over ~3,400 ticks).
- The controller manager skips its cycle on every tick whose /clock delta is 1,999,999 ns
  instead of 2,000,000 (floating-point sim time floored to ns; every ~146 ticks at
  t ~ 68,000 s). 24/24 absent cycles are those ticks. Effect during motion: that step keeps
  the previous command; repeats then differ by <= 4.5e-6 rad over a 0.8 s move. The skip
  ticks are fixed by absolute sim time, hence at different episode-relative ticks per run.
- JTC 4.42.1: header.stamp 0 -> the trajectory starts at the first update after it is
  installed; a future stamp -> spline from the current state to the first point at its
  absolute time; a past stamp with a future end -> jumps into the segment containing now;
  an end in the past -> rejected.
- Goal installation can lag its acceptance: rclcpp_action returns "accepted" before the
  JTC's accepted callback installs the trajectory; once, under the present CPU load, it came
  167 ticks late after a 50 ms wall wait. A stepping evaluator must confirm installation.
- The camera snapshots mjData on the sim thread every 25 ticks (stamp = snapshot time) and
  publishes from its render thread; a frame's content and stamp belong to one tick.

## 3. Clock ownership

The plant is paused for the whole episode. Sim time advances only through
StepSimulation calls issued by the DSE. Every event -- observation capture, goal delivery,
jaw command, replan -- happens at a chosen tick. Wall time (inference, IK, CPU load) decides
nothing.

Per call: StepSimulation(n), then wait until the controller cycle of the last tick is
seen (/mujoco_actuators_states stamped with it) or that tick is a known 1-ns-short tick
(its /clock delta is read, so an absent cycle there is expected, recorded, and not an
error). Any other absent cycle -> episode marked infra-invalid, never silently continued.
n = 1 near events; between events n up to 25 (the audit's 5-step calls kept the
cycle/skip lock; to be re-verified per run by the same check).

## 4. Initial-state contract

1. Pause. Send the hold goal at the start q (HOME_Q, or the perturbed start q) and the
   gripper's open command; confirm both installed (section 6).
2. ResetWorld with overrides: arm joints = start q, gripper joints = open, all qvel 0; ball
   and bin free joints at the episode's placement with zero twist.
3. Step a fixed settle (250 ticks = 0.5 s) under the hold. Deterministic, so the start state
   is the same every run even though the servo sags under gravity.
4. t0 = the next camera tick. The first observation is taken at t0 + 0.1 from the frames
   stamped t0 and t0 + 0.1 -- both exist by construction.

Fixed: timestep 0.002 (unchanged), camera 20 Hz (unchanged), policy seed 1234 per request
(unchanged), placement / perturbation from the same episode tables.

## 5. Observation contract

At an observation tick t (a camera tick):
- obs[1] = frame stamped t, obs[0] = frame stamped t - 0.100 (two camera frames back at
  20 Hz, 50 physics ticks; both on the camera's own grid).
- The robot state for each frame is the simulator state of THAT tick, taken from the
  controller cycle of that tick (/mujoco_actuators_states or /joint_states), exact; no
  interpolation, no nearest. The DSE keeps the state of every camera tick while stepping.
- While paused the DSE waits (wall time irrelevant) until both frames have arrived.
- Logged per plan: both frame stamps, obs_dt, both state stamps, image-state skew (0 by
  construction), input hash and the lowdim values.

## 6. Command contract

- Goals are sent only while paused. After "accepted", the DSE waits for the goal's
  EXECUTING status (published by the JTC's accepted callback after it installs the
  trajectory), then steps one tick and checks that the controller's reference switched to
  the new trajectory (its time_from_start restarted). If not -> infra-invalid.
- time_from_start is computed against the TRUE paused sim time of installation: with
  header.stamp 0 the trajectory starts at the next update (T_d + 1 tick), so
  tfs_k = t_send,k - (T_d + 0.002). This removes the stale-clock shift S' by construction;
  whether S' is kept as a fixed virtual delay is decision 1.
- Jaw commands: at the tick where t_send,jaw = t_event - 0.14 is reached, paused, sent and
  confirmed the same way (GripperActionController takes the goal at its next update).

## 7. Action-age contract (virtual latency)

The executor's own rule is kept: waypoint k (t_k = t + 0.1k) is kept iff
t_k - 0.21 > collected_at + 0.01. In the DSE, collected_at = t + L_v, so

    k* = floor(10 (L_v + 0.22)) + 1        k* = 5  <=>  0.18 <= L_v < 0.28

L_v = 0.216 s (rep1 median; definitive 0.214) -> k* = 5 with 64 ms slack, as 98.9% of
runtime plans. Not hard-coded: k* follows from L_v and the unchanged rule.

The old plan keeps executing while the new one is "in flight": the DSE steps from t to the
delivery tick T_d = t + L_v + D_v, then installs the new goal. Two candidates:

| | A: intended semantics | B: runtime median |
|---|---|---|
| D_v | 0 | 0.266 s (median S') |
| new goal takes over at | t + 0.216 | t + 0.482 |
| waypoint k commanded at | t_k - 0.21 (as the executor intends) | t_k - 0.21 + 0.266 |
| first kept waypoint (k=5) commanded | t + 0.29 | t + 0.556 |
| vs all G0 async runs so far | actions ~0.27 s earlier than they were executed | the same on average, without the spread |

Replan cadence: the executor starts the next inference after sending and waits for a frame
>= (newest frame at send) + 0.1. Under B this gives t' ~ t + 0.55-0.60 (the runtime
median 0.55). Under A the same rule gives ~ t + 0.35 (replans ~1.6x as often). Decision 2:
derive the cadence from the rule, or fix the period at P_v = 0.55 s.

## 8. Remaining physics-level difference

The 1-ns-short-tick skip (section 2) survives any evaluator logic: the episode-relative skip
ticks move with the absolute sim time. Options (decision 4):
- (i) accept it and test in the G0 validation whether it changes observations / policy
  outputs / outcomes (expected size: a few um of tool position per skip during motion);
- (ii) remove it: controller-manager update_rate 500 -> 505 Hz (period 1,980,198 ns <
  1,999,999), so every 2-ms tick triggers exactly one cycle. Needs a restart of the
  simulator process (ros2_control_node) with a changed controllers.yaml; physics timestep,
  camera and controllers unchanged; the JTC's one-period command look-ahead becomes
  1.980 ms instead of 2.000.
Recommendation: (i) first; (ii) only if validation shows divergence traced to skips.

## 9. Decisions for the user

1. Action timing: A (intended, D_v = 0) or B (runtime median, D_v = 0.266). Recommendation:
   A -- it is what the executor's latency compensation means; S' was a bug, and B would bake
   the bug's median into the reference evaluator. Consequence: DSE numbers are not
   comparable to any async number (they were not going to be anyway).
2. Cadence: rule-derived or fixed P_v = 0.55 s. Recommendation: rule-derived (the executor's
   semantics, no new constant).
3. Perturbed start: set the perturbed joint configuration directly with ResetWorld (no
   approach move, no body disturbance -- val ep11/13 may become valid) or replay the move
   under stepping (keeps the async procedure; ep13 stays infra-invalid). Recommendation:
   direct set, reporting ep11/13 separately so the paired 16 stay the comparison set.
4. Controller skip: (i) accept and validate, or (ii) 505 Hz with a simulator restart.
   Recommendation: (i) first.

## 10. Validation (G0 only), then freeze

G0 v2_11400, nominal episodes 0 and 1, each run twice (then a third if the two differ).
Compared per plan: reset q/object state, frame stamps, obs_dt, image-state alignment, policy
input (sha1 + max |d|), policy output (sha1 + max |d|), virtual action age (L_v, D_v, T_d),
k*, sent waypoints, commanded joint sequence (controller output), actual state trajectory
(simulator state), outcome. Target: identical observation / policy sequences; any
difference traced to a recorded cause (a skip tick) with the tool trajectories within
0.1 mm. Then freeze, and evaluate G0 / G1 / G2 on identical conditions (nominal 5 + valid
16; coverage extended with more placements rather than repeats, if needed).

## 11. Checks still to run before implementation (need the plant; not during a rollout)

- Wall cost per tick (audit steps took ~0.1-0.2 s each with its waits; a 30 s episode is
  15,000 ticks). Micro-benchmark StepSimulation(1) / (25) with only the needed waits.
- EXECUTING status as the installation signal, on arm and gripper goals.
- stream_gaps.py beside a one-episode async rollout: does the /joint_states stream itself
  stop during inference, or only the rollout's reception (diagnostic, not an outcome run).

## 12. Implementation outline (after the decisions)

- sim_umi/ros/dse_rollout.py: episode loop on the tick grid; reuses policy_bridge
  (preprocessing, geometries, server protocol) and the executor's plan code
  (decode, IK projection, k* rule, jaw merge) with an injected clock (collected_at = t + L_v)
  instead of node time; writes the same rollout JSON (plus DSE provenance) so aggregate.py,
  repeat_compare.py and fov_analysis.py work unchanged.
- The asynchronous evaluator files are not modified.

## 13. Decisions (user, 2026-09-27 ~18:25)

1. Action timing: A. L_v = 0.216 s stays as the compute latency; the stale-clock delay
   (D ~ 0.266 s) is removed -- it is neither physically nor for control a needed delay, and a
   correct timestamp / latency-compensation implementation in deployment removes it too.
2. Cadence: derived from the existing rule, NO fixed P_v. 0.55 s was the async runtime's
   result including the stale-clock delay; keeping it while removing the bug would be
   inconsistent. Cadence follows from obs spacing 0.100 s, L_v = 0.216 s and the rolling /
   replan rule, and the resulting cadence is recorded. The 10 Hz action grid (0.1 s
   waypoint spacing) is not a replan rate.
3. Perturbed start: ResetWorld direct set. start-perturbed evaluates recovery from the same
   perturbed initial state, not the move to it; contacts / body disturbance from the
   preparation move are evaluator artifacts and go. Primary set = the paired valid 16 of
   the definitive comparison; ep11/13, if valid now, are a separate secondary result, never
   pooled with the 16. The reset must canonically initialise qpos, qvel, ctrl / warm-start
   AND the JTC's trajectory / hold state, with the same sim-step / observation-readiness
   sequence before every rollout.
4. Controller skip: keep 500 Hz, accept, validate with G0 reproducibility (skip positions and
   counts, q, EE, observation, policy output, trajectory, outcome). If it does not cause
   closed-loop divergence: record as an acceptable numerical artifact and freeze. If it
   demonstrably changes results: first examine removing the 1,999,999-ns tick itself or a
   tolerance in the controller's update condition; 505 Hz only as the fallback (changing the
   rate would alter the control contract).

## 14. Sensor-ready barrier (user, 18:40): no nearest frame, ever

Found in the plant's source while designing it:
- The camera plugin's update() -- trigger decision AND snapshot -- runs inside the hardware
  interface's write(), i.e. inside a controller-manager cycle, not in the physics loop.
- The trigger compares the plugin node's ROS clock (mujoco_ros2_control_node, its own /clock
  subscription) with its last trigger: `now - last >= 0.05`. The cycle itself was woken by
  the controller manager's clock -- a different node, the same /clock, another thread.
- The snapshot is the physics thread's latest data snapshot (refreshed after a step, after
  /clock is published); the frame stamp is that snapshot's data time. Stamp and content
  always belong together; WHICH tick is captured may depend on in-process timing.
So frames are only ever taken on controller-cycle ticks (never on a skipped tick), their
spacing is 25 ticks normally and 26 where a 1-ns-short tick falls inside, and possibly
+-1 tick more where the in-process race goes the other way.

Barrier protocol (the JTC-takeover principle; wall time only to wait for a component to
catch up with the CURRENT sim time, never to decide sim timing):
1. Predict the next frame tick from the plugin's rule with a caught-up clock: the first
   controller-cycle tick c with c - (previous trigger tick) >= 50,000,000 ns.
2. Step to exactly that tick (one tick per call for the last ones).
3. Do not step further until the frame stamped with that tick has been received
   (render thread -> DDS). A frame stamped otherwise, or none, is an ANOMALY: counted,
   listed, and the observation built on it is flagged; never replaced by the nearest one.
4. Observation pairs use only frames that passed 3.
Limitation: the barrier guarantees nothing is skipped or guessed on OUR side; it cannot
decide the plugin's in-process race. How often that race changes the captured tick is
measured before the DSE is used (camera_step_test.py: single / 5 / 25 steps per call, twice
each, prediction vs actual). If it is not zero under single stepping, the remedy is on the
plant side and needs the user's approval before anything is changed: e.g. take the camera's
trigger and snapshot in the plugin's pre_step hook on the physics thread using the data time
(a small patch to camera_plugin.cpp, overlay rebuild, simulator restart).

## 15. What "collect at t + L_v" means, and how every plan proves it

Per plan n (t = the observation frame tick, all times on the 2-ms tick grid):

    sim time ->  t-0.100        t                           T_d = t+0.216   T_d+0.002        t+0.290
    frames       F(t-0.1)      F(t)
    policy                      obs + inference (plant paused: 0 s of sim time)
    arm (JTC)    ---- plan n-1 keeps executing, spline sampled every tick ---|-- plan n installed: spline
                                                                            |   from the state at T_d+0.002
                                                                            |   to waypoint k*=5 at t+0.290,
                                                                            |   then every 0.1 s
    jaw          plan n-1's events due in (t, T_d] fire on their own ticks  | merge at T_d (commit window 0.25 s)
    executor                                                   collect(now = T_d): k kept iff
                                                               t+0.1k-0.21 > T_d+0.01 -> k* = 5
    next obs     t' = (newest frame <= T_d) + 0.100 -> ~ t+0.300 (exact pair), recorded as cadence

L_v enters exactly once: as the sim time the old plan runs between the observation and the
takeover. It is not added to the waypoints (they are commanded at t_k - 0.21, the executor's
robot-latency compensation) and no stale-clock delay is added on top (decision A).
Checks written into every plan's "dse" record and summarised per episode:
- collected_at - obs_t == L_v, and the goal's start tick - obs_t == L_v + 0.002;
- takeover: the first controller cycle after the goal has reference time_from_start == 0,
  and it is the tick T_d + 0.002 (T_d + 0.004 only where T_d + 0.002 is a skipped tick);
- (t, T_d]: the JTC's trajectory clock (reference time_from_start) advances without a
  restart -- the old plan is still the one being executed;
- jaw commands fired in (t, T_d] come from plan n-1 and fire on their due tick (late 0);
- the first sent waypoint's commanded time (start tick + time_from_start) == t_k* - 0.21.
One episode's full trace (per-tick controller output around two plan boundaries, the jaw
queue, the frames) is exported as a table and a timeline figure after the first DSE smoke.

## 16. Camera plugin: a deterministic sim-state trigger (PROPOSAL -- needs approval)

Why (journal 19:25): under the current plugin the capture tick depends on (a) the plugin
node's clock delivery inside the controller cycle -- 5- and 25-step calls moved captures by
+-1 tick or dropped one; (b) absolute sim time -- the trigger chain runs through ResetWorld
from wherever it was, and 1-ns-short ticks stretch intervals to 26 at time-dependent places.
Single steps make a run exact against the rule, but repeats still differ ([19, 44, ...] vs
[18, 44, ...]). No barrier outside the plant can fix (b).

Change (camera_plugin.cpp only; the plugin base already provides both hooks):
- a parameter `trigger`: `node_clock` (default: today's behaviour, untouched) or `sim_state`;
- `sim_state`: the trigger decision and the snapshot move to `pre_step(data)` -- physics
  thread, immediately before every mj_step, sim mutex held, live mjData -- and the rule is a
  step counter: capture when n % 25 == 0, n = physics steps since the last world reset
  (`on_reset()` sets n = 0; 25 = round(1 / (20 Hz * 0.002 s))). Stamp = data->time; content =
  that tick's state. `update()` then serves polled cameras only.
- optional, same patch: publish the arm and gripper joint positions of the same snapshot,
  stamped identically (`/wrist_camera/joint_snapshot`), so every frame has its exact state
  even on a tick whose controller cycle was skipped (today: interpolated across 4 ms).
Result by construction: captures at reset + 25k ticks in every repeat, independent of ROS
clock delivery, controller cycles, ns flooring, stepping speed and absolute time. The frame
of tick t is taken as the step t -> t+1 begins; the DSE's barrier then holds after that step
until frame t has arrived.
Deployment: rebuild only the overlay package mujoco_ros2_control_plugins; a separate plugin
file for DSE runs (config/mujoco_plugins_dse.yaml with `trigger: sim_state`) selected by a
new launch argument of mujoco_bringup.launch.py, default unchanged; restart the simulator
(ros2_control_node + its spawners; move_group untouched). Rollback: relaunch with the
default file. The asynchronous evaluator keeps the default trigger, so its behaviour and
its historical numbers stay comparable.
Not changed: physics timestep, controllers (500 Hz), JTC, the 1-ns clock skips (decision 4).
Verification before any DSE result: camera_step_test (1 / 5 / 25 steps per call, twice
each) must give expected (reset + 25k) == actual in every run and identical ticks across
repeats; then the DSE smoke's hard gates.

## 17. Definition changed: a TIMING-CONTROLLED evaluator (user, ~20:52)

After the capture and integer-tick fixes (journal 20:20-20:52) every timing / scheduling
contract is deterministic and gated per plan, and two runs of G0 ep0 reproduce the policy's
input and output, the first command and >1300 ticks of controller output and state bitwise.
They then part on the renderer's +-1-level pixel noise (policy output ~1e-7, amplified by the
closed loop). The renderer is not modified. The evaluator is therefore defined as
timing-controlled, not strictly deterministic; its residual outcome variance is measured by
repeats (G0 nominal 5 + perturbation valid 16, twice) before any G1/G2 comparison.
Timeline rule (user): a JTC restart at tick >= the in-flight trajectory's end tick is a normal
hold transition; only < end tick fails.

## 18. Cadence (supersedes decision 2)

The replanning cadence is the policy's chunking contract, not "as soon as a frame after
delivery exists": the next observation is steps_per_inference (6, UMI eval_real.py) action
steps after the current one, 0.6 s. The rule-derived cadence collapsed to 0.3 s once the
stale-clock delay was removed (3 commanded points per plan) -- a design error, found by the
user.

## 19. Frozen canonical condition for the G0 / G1 / G2 representation comparison (user, 22:00)

- Evaluator: timing-controlled (this file; sim_umi/ros/dse_rollout.py), plant paused, one
  physics step per StepSimulation call (DSE_BATCH=1), hard gates per episode.
- Cadence: 0.6 s = steps_per_inference 6 x 0.1 s action steps (UMI eval_real.py default);
  L_v 0.216 s; k* from the executor's rule (5); takeover at delivery + 1 tick; integer-tick
  time_from_start; 8 waypoints sent per plan.
- Camera: patched plugin, sim_state trigger (reset + 25k ticks), paired joint snapshot.
- Episodes: nominal 5 (train placements 0-4, start at HOME by ResetWorld). Perturbation
  only after the FOV comparison, if time remains or for the final candidate's robustness.
- Code: evaluator files at hash f7bf1da64e75 (GATE_PASS_f7bf1da64e75.json); G0 reference =
  t2_g0_repA and t2_g0_nomB (hard gates 10/10, outcomes 5/5 agree, aggregates equal but
  corridor 2 vs 3).
This 0.6 s cadence is the canonical condition of THIS comparison only. It is separate from
the project's original 0.8 s deployment contract (the rolling executor keeping 8 waypoints,
0.8 s, in flight) -- neither replaces the other, and deployment numbers are not taken from here.
