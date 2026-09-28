# Results

Every number here links to the journal entry or table it comes from. The format is
C / L / S / B / a = corridor / lifted / strict GT secure / bin / 8-plan unreachable
abort (definitions: [ARCHITECTURE.md §6](ARCHITECTURE.md#6-metrics-sim_umiscriptsdefinitiveaggregatepy)).
All policy numbers are EMA weights at a step fixed in advance. With n = 5 to 16 per
condition, no difference is claimed as significant unless a test is quoted.

## 1. Simulated cell and scripted expert (2026-09-25)

The regression suite passes 6/6 on the plant (MoveIt -> 5-DoF projection ->
ros2_control -> MuJoCo):

| check | result |
|---|---|
| gripper fully open | 51.63 mm |
| gripper half closed | 26.35 mm |
| gripper fully closed | 0.13 mm |
| grasp | stalls holding 31.4 mm |
| lift | ball 24.8 -> 137 mm |
| place | ball ends inside the bin |

Source: [sim_umi/PROJECT_STATUS.md](sim_umi/PROJECT_STATUS.md). Video:
`sim_umi/outputs/pick_place_h264.mp4`.

## 2. Definitive experiment: clean vs clean + corrective (v2) data (2026-09-27)

This used the historical asynchronous evaluator. The two datasets start from the same
initial state, and v2 is trained to 11 400 updates.

| checkpoint | nominal LIFT / bin / abort (n=5) | perturbation C / L / S / B / a (n=16) |
|---|---|---|
| clean 5986 | 0 / 0 / 5 | 0 / 2 / 2 / 0 / 13 |
| v2 5986 | 1 / 0 / 5 | 4 / 6 / 3 / 2 / 14 |
| v2 11400 | 3 / 2 / 2 | 5 / 10 / 8 / 4 / 7 |

v2 11400 vs clean 5986 on perturbation lifted: 10 vs 2, Fisher p = 0.009. The verdict
was "closest to CASE A" (under-training on the larger dataset); v2 11400 became the G0
baseline. Sources:
[experiment_summary_20260927.md](sim_umi/train_results/2026-09-27_definitive/experiment_summary_20260927.md),
[tables_definitive.md](sim_umi/eval_results/2026-09-27_definitive/tables_definitive.md),
[failure_breakdown_v2_11400_nominal.md](sim_umi/eval_results/2026-09-27_definitive/failure_breakdown_v2_11400_nominal.md).

## 3. The evaluator became timing-controlled (DSE)

**Finding.** Repeats of the same checkpoint on the asynchronous evaluator did not
reproduce (nominal bin 0 vs 3). The cause was a stale node clock that let actions
execute about 0.27 s late (median).

**Fix.** The DSE pauses the plant and puts every event on an integer tick. On it, G0
nominal x2 gives 2/4/2/1/4 and 3/4/2/1/4, and lifted / bin / abort / strict agree
episode by episode in 5/5.

A 0.3 s replanning cadence turned out to be a design error and was replaced by 6
action steps = 0.6 s. The frozen canonical condition is timing-controlled nominal 5,
0.6 s cadence, L_v = 0.216 s, one physics step per call.

Source: [DSE_DESIGN.md](sim_umi/train_results/2026-09-27_fov/DSE_DESIGN.md) and the
FOV [JOURNAL.md](sim_umi/train_results/2026-09-27_fov/JOURNAL.md).

## 4. Input geometry (FOV) on the canonical condition

| geometry | run 1 | run 2 | lifted | bin |
|---|---|---|---|---|
| G0 center crop 224 | 2/4/2/1/4 | 3/4/2/1/4 | 8/10 | 2/10 |
| G1 letterbox 224 | 1/2/1/0/3 | 1/2/1/0/4 | 4/10 | 0/10 |
| G2 rect ViT 288x176 | 0/1/1/0/4 | 0/1/1/1/2 | 2/10 | 1/10 |

G0 stays the geometry: a wider field of view did not help. Source:
[fov_nominal_all.md](sim_umi/eval_results/2026-09-27_dse/fov_nominal_all.md).

## 5. Data for the follow-up ablations (labels and oracle masks)

- **Mapping.** Rows map exactly to their source frames: 91 demos -> 3 zarrs; 68 demos ->
  94 train episodes because of timing-gap cuts. There are 0 unmatched and 0 duplicate
  rows, and 21 532 training samples.
- **Events.** close / lift / open / retreat are found in 91/91 demos, and each demo has
  exactly one close and one open.
- **Oracle masks.** They come from MuJoCo segmentation of the plant's own model, with
  MSAA off. The renderer reproduces the frozen sidecar bit for bit.
- **Target alignment.** Rigid T_EE->object for the held ball brings the target
  alignment to <= 1.24 px (raw recorded pose: 3.7 px).

Source: [PREP_REPORT.md](sim_umi/train_results/2026-09-27_aux_prep/PREP_REPORT.md).

## 6. Ablation A: phase-masked time-to-event auxiliary regression (canonical, unchanged evaluator)

| | G0 | A timing aux |
|---|---|---|
| runs (C/L/S/B/a) | 2/4/2/1/4 · 3/4/2/1/4 | 2/2/2/1/3 · 2/3/1/1/3 |
| lifted / strict / bin / abort | 8 / 4 / 2 / 8 of 10 | 5 / 3 / 2 / 6 of 10 |
| first-close depth / pitch (expert -22.6 mm / 12.6 deg) | -10.5 mm / 9.0 deg | -14.2 mm / 1.6 deg |

- A closes deeper, which is the intended effect, but nearly level. It does not do
  better.
- A run 1 ep1 is infra-invalid: a lock residual of 6e-7 exceeded the 1e-7 limit.

Sources: [eval_A_vs_G0.md](sim_umi/train_results/2026-09-28_aux_ablations/eval_A_vs_G0.md),
[JOURNAL.md](sim_umi/train_results/2026-09-28_aux_ablations/JOURNAL.md).

## 7. Ablation B: oracle target / fingertip relation FiLM (canonical, mask-capable evaluator)

| | G0 control (same evaluator, masks ignored) | B |
|---|---|---|
| runs (C/L/S/B/a) | 2/3/1/1/4 · 3/4/2/1/4 | 3/3/3/2/3 · 3/3/3/2/3 |
| lifted / strict / bin / abort | 7 / 3 / 2 / 8 of 10 | 6 / **6** / **4** / 6 of 10 |
| first-close depth / vertical (expert -22.6 / 4.3 mm) | -10.3 / 8.3 mm | -13.8 / 4.4 mm |
| episodes whose outcome repeats across runs | 4/5 | 5/5 |

- **Evaluator effect.** The G0 control matches G0 on the unchanged evaluator (lifted 8,
  strict 4, bin 2), so the mask path does not shift results.
- **Infra-invalid episode.** B run 2 ep2 is infra-invalid: the goal was never
  EXECUTING. It is reported, not dropped, and its outcome equals run 1's.
- **Gate history.** Before these runs, a single-tick arm_continuity trip was traced to
  a corrupted logged effort sample; the motion followed the correct command. The
  one-shot re-gate on a fresh plant passed.
- **Interpretation.** B is oracle. It shows that explicit target-fingertip relations
  help on this task; it is not a deployable policy.

Sources: [eval_B_vs_G0control.md](sim_umi/train_results/2026-09-28_aux_ablations/eval_B_vs_G0control.md),
[arm_continuity_timebox_table.md](sim_umi/train_results/2026-09-28_aux_ablations/arm_continuity_timebox_table.md),
[JOURNAL.md](sim_umi/train_results/2026-09-28_aux_ablations/JOURNAL.md).
