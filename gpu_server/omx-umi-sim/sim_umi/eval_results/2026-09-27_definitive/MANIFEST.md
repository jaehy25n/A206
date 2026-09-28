# 2026-09-27 definitive — AMP clean vs AMP clean+corrective (v2), matched and extended

**Purpose.** At a matched 5986 optimizer updates from one shared initial
state, does the corrective data change closed-loop recovery and nominal
behaviour, and does v2's nominal behaviour come back with more updates
(8000, 10000, 11400)? Full write-up:
`sim_umi/train_results/2026-09-27_definitive/experiment_summary_20260927.md`;
step-by-step log: `…/JOURNAL.md`.

**Control.** Both runs: shared init a4cd264f, fp16 autocast + GradScaler,
batch 64, val_ratio 0.0, LR 3e-4 cosine with warmup 2000 and horizon pinned
at 11400, same config except dataset and step budget. Evaluation: physical
GPU 5, one server at a time, EMA weights, deterministic preprocessing, seed
1234, rolling executor with 8 waypoints in flight, rollout code 2943963.
Start: deterministic reset -> place -> both bodies verified from free-joint
ground truth -> (perturbed pose; bin re-verified, ball nudge recorded, >25 mm
refused) -> fresh-observation gate.

| files | condition |
| --- | --- |
| `nominal_<ckpt>.json(.gz)`, `.log` | train placements 0-4 from HOME, max 600 ticks; ckpt = clean5985, clean5986, v2_5985, v2_5986, v2_8000, v2_10000, v2_11400 |
| `val18_<ckpt>.json(.gz)`, `.log` | v2_val 0-17 from their perturbed pose, max 400 ticks; ckpt = clean5986, v2_5986, v2_8000, v2_10000, v2_11400. 16/18 each: ep11 and ep13 fail their start identically in every job (infrastructure) |
| `val18_<ckpt>_infra_fail_ep{11,13}.png` | camera frame at the failed start |
| `aggregate_definitive_final.json` | the final metrics (part1 + part2 merged; both strict-secure corrections) |
| `aggregate_part1_primary.json`, `aggregate_part2_secondary.json` | the two halves of the final aggregate |
| `aggregate_nominal_provisional.json`, `aggregate_primary_provisional.json` | SUPERSEDED: made before the strict-secure corrections; record only |
| `tables_definitive.md`, `paired_and_fisher.md` | generated tables (build_tables.py; per-episode paired view; reference Fisher tests) |
| `superseded_start_order_bug/` | SUPERSEDED first nominal pass and the aborted val18 attempt, run with the old start order (bodies placed before the arm went home; episode 3's ball 158-397 mm off). Not comparable with anything else here |
| `failure_breakdown_v2_11400_nominal.{md,json}` | v2_11400 nominal, episode by episode: stages, closing geometry, ball path, refusal streaks with the gate reproduced (pinned joint, past-limit if unclipped, best pitch, yaw discarded, visibility); `failure_breakdown.py` |
| `video/v2_11400_nominal_ep{0,1,2,4}_*.mp4` | LOG REPLAYS of those exact evaluated episodes (not re-runs), `replay_video.py`: overview facing the robot, side-on close-up of the tool, policy input rebuilt from the logged state (wrist re-render -> mask_magenta -> 224 crop, as policy_bridge.observe; the unmasked re-render matched a saved live frame to 1.9/255) |
| `historical_fp32_*` + `HISTORICAL_VARIANTS.md` | old FP32 runs re-aggregated, reference only; use the `_metric0800` files |

Raw `*.json` stay on disk (not in git); git carries the `.json.gz` copies.
Server logs `server_<ckpt>.log` hold only the later (val18) job for a
checkpoint that ran both sets; each job's checkpoint line and EMA check are in
`sim_umi/train_results/2026-09-27_definitive/eval_chain2.log`.
