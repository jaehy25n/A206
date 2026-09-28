# Documentation index (chronological)

## Real-data path and robot handoff (2026-09-21 .. 09-23)

| Document | What it is |
|---|---|
| [README_GPU_WORKFLOW.md](../README_GPU_WORKFLOW.md) | GPU server workflow: environment, `processed_v1` -> zarr, training, offline inference |
| [README_CPU_GPU_SYNC.md](../README_CPU_GPU_SYNC.md) | CPU -> GPU session sync (rsync pull, READY markers) |
| [README_GPU_VALIDATION.md](../README_GPU_VALIDATION.md) | Validation of the GPU pipeline |
| [README_HANDOFF_CONTRACT.md](../README_HANDOFF_CONTRACT.md) | The data / action contract between the layers |
| [REQUESTS_TO_CPU_SERVER.md](../REQUESTS_TO_CPU_SERVER.md) | Open requests to the CPU server team |
| [README_JETSON_HANDOFF.md](../README_JETSON_HANDOFF.md), [README_JETSON_SETUP.md](../README_JETSON_SETUP.md), [HANDOFF_MESSAGE_TO_JETSON.md](../HANDOFF_MESSAGE_TO_JETSON.md), [jetson_handoff/](../jetson_handoff/README.md) | Jetson inference handoff |
| [REPORT_JETSON_INFERENCE_BRINGUP.md](../REPORT_JETSON_INFERENCE_BRINGUP.md), [REPORT_STAGE_A_INTEGRATION.md](../REPORT_STAGE_A_INTEGRATION.md) | Jetson bring-up and Stage A integration reports (the Stage A checkpoint is integration-only) |

## Simulated cell (2026-09-24 .. 09-26)

| Document | What it is |
|---|---|
| [sim_umi/PROJECT_STATUS.md](../sim_umi/PROJECT_STATUS.md) | The simulated cell: model, camera matched to the real collector, gripper, MoveIt + 5-DoF projection, regression |
| [sim_umi/ros/OVERLAY.md](../sim_umi/ros/OVERLAY.md) | Why and how `mujoco_ros2_control` is built as an overlay |
| [sim_umi/eval_results/2026-09-26/MANIFEST.md](../sim_umi/eval_results/2026-09-26/MANIFEST.md), [.../2026-09-27/MANIFEST.md](../sim_umi/eval_results/2026-09-27/MANIFEST.md) | Early closed-loop evaluations |

## Definitive experiment: clean vs v2 data (2026-09-27)

| Document | What it is |
|---|---|
| [experiment_summary_20260927.md](../sim_umi/train_results/2026-09-27_definitive/experiment_summary_20260927.md) | The summary: provenance, checkpoints, results, verdict |
| [JOURNAL.md](../sim_umi/train_results/2026-09-27_definitive/JOURNAL.md) | Time-ordered journal |
| [tables_definitive.md](../sim_umi/eval_results/2026-09-27_definitive/tables_definitive.md), [paired_and_fisher.md](../sim_umi/eval_results/2026-09-27_definitive/paired_and_fisher.md), [failure_breakdown_v2_11400_nominal.md](../sim_umi/eval_results/2026-09-27_definitive/failure_breakdown_v2_11400_nominal.md), [HISTORICAL_VARIANTS.md](../sim_umi/eval_results/2026-09-27_definitive/HISTORICAL_VARIANTS.md) | Tables, paired tests, failure breakdown, historical variants |

## Input geometry (FOV) and the timing-controlled evaluator (2026-09-27)

| Document | What it is |
|---|---|
| [JOURNAL.md](../sim_umi/train_results/2026-09-27_fov/JOURNAL.md) | FOV Step 1, evaluator fixes, the DSE, G0 / G1 / G2 on the frozen condition, demo phase segmentation |
| [DSE_DESIGN.md](../sim_umi/train_results/2026-09-27_fov/DSE_DESIGN.md) | Design of the deterministic / timing-controlled evaluator (sections 1-19) |
| [dse_audit/analysis_2.md](../sim_umi/train_results/2026-09-27_fov/dse_audit/analysis_2.md) | JTC / pause-step audit |
| [fov_nominal_all.md](../sim_umi/eval_results/2026-09-27_dse/fov_nominal_all.md), [fov_nominal_G0_G1_G2.md](../sim_umi/eval_results/2026-09-27_dse/fov_nominal_G0_G1_G2.md) | The FOV comparison tables |
| [r4_repeat_compare.md](../sim_umi/eval_results/2026-09-27_fov/r4_repeat_compare.md), [r5_screen_g12/screen_g12.md](../sim_umi/eval_results/2026-09-27_fov/r5_screen_g12/screen_g12.md) | Asynchronous-evaluator repeats and G1/G2 screening |

## Data preparation for the ablations (2026-09-27 .. 09-28)

| Document | What it is |
|---|---|
| [PREP_REPORT.md](../sim_umi/train_results/2026-09-27_aux_prep/PREP_REPORT.md) | Mapping, timing labels, oracle masks, validation |
| [JOURNAL.md](../sim_umi/train_results/2026-09-27_aux_prep/JOURNAL.md) | Journal |

## Ablations A (timing aux) and B (oracle relation FiLM) (2026-09-28)

| Document | What it is |
|---|---|
| [DESIGN.md](../sim_umi/train_results/2026-09-28_aux_ablations/DESIGN.md) | Architecture and loss flow of both ablations |
| [JOURNAL.md](../sim_umi/train_results/2026-09-28_aux_ablations/JOURNAL.md) | Implementation, twin gate, training, evaluations, the arm_continuity timebox |
| [eval_A_vs_G0.md](../sim_umi/train_results/2026-09-28_aux_ablations/eval_A_vs_G0.md), [eval_B_vs_G0control.md](../sim_umi/train_results/2026-09-28_aux_ablations/eval_B_vs_G0control.md) | Per-episode comparison tables |
| `eval_*_repeat_compare.md` | Run-vs-run item comparisons |
| [arm_continuity_timebox_table.md](../sim_umi/train_results/2026-09-28_aux_ablations/arm_continuity_timebox_table.md) | +-8-tick evidence table of the single-tick violation |

## Elsewhere

- [git/COMMITS.md](git/COMMITS.md): all 177 local commits.
- [upstream/UMI_README.md](upstream/UMI_README.md): the original UMI README.
- The owner's Claude Docs work log (work-log and defects-and-fixes tabs) mirrors the
  journal entries: https://claude.ai/code/artifact/c95e4cb4-a2e3-495a-a57c-2f44c4d85f42
