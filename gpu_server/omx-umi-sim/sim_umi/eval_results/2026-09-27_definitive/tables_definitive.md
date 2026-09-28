## Provenance

```
python      3.9.18
torch       2.1.0  cuda 12.1  cudnn 8902
accelerate  0.24.1
numpy       1.24.4
CUDA_VISIBLE_DEVICES = 5
torch device count   = 1
cuda:0 name          = Tesla V100-PCIE-32GB  31.7 GB  sm70
cuda:0 uuid (torch)  = None
physical index match = []
bf16 supported       = False
AcceleratedOptimizer.step_was_skipped present: True
DEVICE CHECK: pid 942259 allocated on physical GPU index 5 (GPU-6ac93a16-5d21-4921-2db9-a9cd274aeec2), 818 MiB
DEVICE CHECK PASSED: cuda:0 == physical GPU 5
```

| dataset | file | sha256 | segments | frames | sampler N | DataLoader len | batch | drop_last | val_ratio | held-out segs |
|---|---|---|---|---|---|---|---|---|---|---|
| clean | omx_sim_train.zarr.zip (49.7 MB) | `b7fbfddc672d9b6b…` | 25 | 6455 | 6080 | 95 | 64 | False | 0.0 | 0 |
| combined | omx_sim_train_v2.zarr.zip (173.4 MB) | `905749cd56e34b2f…` | 94 | 22942 | 21532 | 337 | 64 | False | 0.0 | 0 |
| v2_train (combined minus clean prefix) | — | — | 69 | 16487 | 15452 | — | — | — | — | — |

Shared initial state: `a4cd264fbf9439ef…` (excluding the dataset-fitted normalizer); a second seeded construction reproduces it: True.

| run | started | finished | init checksum | resumed from | AMP probe | train N | DL len | val_ratio | opt_steps at end | skipped | non-finite |
|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 2026-09-27T03:35:10+0900 | 2026-09-27T04:17:51+0900 | `a4cd264fbf9439ef…` | None | autocast True, torch.float16 | 6080 | 95 | 0.0 | 5986 | 0 | 0 |
| v2 | 2026-09-27T04:19:07+0900 | 2026-09-27T05:38:05+0900 | `a4cd264fbf9439ef…` | None | autocast True, torch.float16 | 21532 | 337 | 0.0 | 11400 | 1 | 0 |

## Checkpoints (reloaded from disk and audited)

| run | step | opt_steps | EMA updates | scheduler last_epoch | AdamW step histogram | LR group0 | LR group1 | scaler scale | skipped so far | epoch | dataset passes | audit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 5985 | 5985 | 5985 | 5985 | {'5985': 299} | 1.8550e-04 | 1.8550e-05 | 262144 | 0 | 62 | 63.0 | PASS |
| clean | 5986 | 5986 | 5986 | 5986 | {'5986': 299} | 1.8546e-04 | 1.8546e-05 | 262144 | 0 | 63 | 63.0 | PASS |
| v2 | 5985 | 5985 | 5985 | 5985 | {'5985': 299} | 1.8550e-04 | 1.8550e-05 | 262144 | 0 | 17 | 17.8 | PASS |
| v2 | 5986 | 5986 | 5986 | 5986 | {'5986': 299} | 1.8546e-04 | 1.8546e-05 | 262144 | 0 | 17 | 17.8 | PASS |
| v2 | 8000 | 8000 | 8000 | 8000 | {'8000': 299} | 8.6860e-05 | 8.6860e-06 | 1048576 | 0 | 23 | 23.8 | PASS |
| v2 | 10000 | 10000 | 10000 | 10000 | {'10000': 299} | 1.6122e-05 | 1.6122e-06 | 2097152 | 0 | 29 | 29.7 | PASS |
| v2 | 11400 | 11400 | 11400 | 11400 | {'11400': 299} | 0.0000e+00 | 0.0000e+00 | 1048576 | 1 | 33 | 33.9 | PASS |

## Evaluation completeness

| kind | checkpoint | set | status | episodes run | valid starts (counted) | invalid starts (listed, not counted) | expected | infra-failed starts |
|---|---|---|---|---|---|---|---|---|
| primary | clean5986 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| primary | v2_5986 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| primary | v2_8000 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| primary | v2_10000 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| primary | v2_11400 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| primary | clean5986 | val18 | PARTIAL | 16 | 16 | 0 | 18 | 2 |
| primary | v2_5986 | val18 | PARTIAL | 16 | 16 | 0 | 18 | 2 |
| primary | v2_11400 | val18 | PARTIAL | 16 | 16 | 0 | 18 | 2 |
| secondary | v2_8000 | val18 | PARTIAL | 16 | 16 | 0 | 18 | 2 |
| secondary | v2_10000 | val18 | PARTIAL | 16 | 16 | 0 | 18 | 2 |
| secondary | clean5985 | nominal | complete | 5 | 5 | 0 | 5 | 0 |
| secondary | v2_5985 | nominal | complete | 5 | 5 | 0 | 5 | 0 |

## Start validity (free-joint ground truth; never given to the policy)

| run | counted | invalid starts | infra retries | ball dev at first sample, mm (median / max) | perturbed starts settled | bodies after place, max dev mm (ball / bin) |
|---|---|---|---|---|---|---|
| clean5985_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| clean5986_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| v2_5985_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| v2_5986_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| v2_8000_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| v2_10000_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| v2_11400_nominal | 5 | none | 0 | 0.19 / 0.19 | — | 0.19 / 0.75 |
| clean5986_val18 | 16 | none | 0 | 0.19 / 12.83 | 16/16 | 0.19 / 0.75 |
| v2_5986_val18 | 16 | none | 0 | 0.19 / 12.83 | 16/16 | 0.19 / 0.75 |
| v2_8000_val18 | 16 | none | 0 | 0.19 / 12.83 | 16/16 | 0.19 / 0.75 |
| v2_10000_val18 | 16 | none | 0 | 0.19 / 12.83 | 16/16 | 0.19 / 0.75 |
| v2_11400_val18 | 16 | none | 0 | 0.19 / 12.83 | 16/16 | 0.19 / 0.75 |

## Nominal 5 placements (HOME start, training placements)

| checkpoint | n | GRASP stage | LIFT stage | runtime grasped | ball lifted | strict GT secure | bin | corridor | pitch<20 | unreachable abort | ticks (per ep) | trap dwell s (mean) | prefix<=2 (mean) | infra retries |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean5985 | 5 | 5/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 5/5 | [256, 288, 231, 245, 377] | 2.85 | 0.167 | 0 |
| clean5986 | 5 | 5/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 5/5 | [329, 328, 231, 236, 205] | 3.52 | 0.142 | 0 |
| v2_5985 | 5 | 3/5 | 1/5 | 1/5 | 1/5 | 0/5 | 0/5 | 0/5 | 5/5 | 5/5 | [155, 171, 195, 260, 137] | 1.80 | 0.284 | 0 |
| v2_5986 | 5 | 3/5 | 1/5 | 1/5 | 1/5 | 0/5 | 0/5 | 1/5 | 5/5 | 5/5 | [183, 141, 181, 153, 114] | 1.47 | 0.291 | 0 |
| v2_8000 | 5 | 5/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 5/5 | [228, 312, 235, 190, 270] | 2.05 | 0.174 | 0 |
| v2_10000 | 5 | 5/5 | 1/5 | 1/5 | 1/5 | 0/5 | 0/5 | 0/5 | 5/5 | 4/5 | [600, 510, 218, 112, 115] | 1.60 | 0.122 | 0 |
| v2_11400 | 5 | 5/5 | 3/5 | 3/5 | 3/5 | 1/5 | 2/5 | 3/5 | 5/5 | 2/5 | [102, 600, 166, 172, 175] | 3.38 | 0.069 | 0 |

Stage ticks (mean per episode):

| checkpoint | SEARCH_OBJECT | APPROACH_OBJECT | GRASP | LIFT | SEARCH_BIN | TRANSPORT | PLACE | AFTER_RELEASE |
|---|---|---|---|---|---|---|---|---|
| clean5985 | 10 | 134 | 135 | 0 | 0 | 0 | 0 | 0 |
| clean5986 | 11 | 133 | 121 | 0 | 0 | 0 | 0 | 0 |
| v2_5985 | 11 | 159 | 13 | 1 | 0 | 0 | 0 | 0 |
| v2_5986 | 9 | 134 | 9 | 2 | 0 | 0 | 0 | 0 |
| v2_8000 | 12 | 211 | 24 | 0 | 0 | 0 | 0 | 0 |
| v2_10000 | 43 | 239 | 29 | 0 | 0 | 0 | 0 | 0 |
| v2_11400 | 6 | 179 | 26 | 12 | 0 | 13 | 6 | 0 |

Close geometry at the onset of closing of the first real GRASP attempt (N/A = no GRASP attempt):

| checkpoint | n closes | lateral mm | depth mm | vertical mm | pitch deg | EE speed mm/tick |
|---|---|---|---|---|---|---|
| expert | 20 | -0.62 [-2.26, +2.20] | -22.62 [-23.66, -15.86] | +4.30 [+0.51, +8.19] | +12.57 [+7.91, +17.40] | ~0.15 |
| clean5985 | 5 | -1.04 (med -0.48, sd 2.09) | -3.38 (med -3.46, sd 2.15) | -8.76 (med -13.65, sd 13.59) | +20.85 (med +20.90, sd 0.78) | +1.84 (med +0.97, sd 1.54) |
| clean5986 | 5 | +0.49 (med +0.08, sd 1.22) | -2.58 (med -3.23, sd 3.84) | -12.25 (med -12.37, sd 3.19) | +21.33 (med +21.32, sd 0.66) | +1.61 (med +1.61, sd 0.69) |
| v2_5985 | 3 | +0.62 (med +0.96, sd 0.95) | -9.10 (med -9.12, sd 0.95) | +2.69 (med +3.52, sd 1.68) | +0.71 (med +2.46, sd 4.67) | +1.47 (med +0.99, sd 1.22) |
| v2_5986 | 3 | +0.91 (med +1.20, sd 0.95) | -8.02 (med -9.15, sd 1.61) | +4.02 (med +2.41, sd 2.53) | +3.83 (med +4.85, sd 1.68) | +0.89 (med +0.96, sd 0.19) |
| v2_8000 | 5 | +1.60 (med +1.39, sd 0.90) | -6.34 (med -6.32, sd 0.94) | +11.51 (med +15.54, sd 5.33) | +15.14 (med +19.28, sd 7.15) | +0.19 (med +0.15, sd 0.10) |
| v2_10000 | 5 | -0.65 (med -0.20, sd 1.26) | -8.92 (med -8.81, sd 0.63) | +7.99 (med +8.24, sd 2.29) | +13.66 (med +9.75, sd 5.26) | +0.39 (med +0.22, sd 0.39) |
| v2_11400 | 5 | +0.74 (med +1.38, sd 2.30) | -11.06 (med -11.00, sd 2.40) | +9.55 (med +6.89, sd 4.53) | +16.95 (med +14.43, sd 5.46) | +0.47 (med +0.57, sd 0.22) |

Feasibility (runtime gate: solve_ik_best in-plane position residual > 2 mm; causes from re-solving each rejected target):

| checkpoint | attempted | rejected | joint limit | pitch unattainable | position unreachable, no limit | IK reproduction | asked pitch acc/rej | orientation residual acc/rej deg |
|---|---|---|---|---|---|---|---|---|
| clean5985 | 3090 | 100 | 92 | 0 | 8 | 1.0 | 8.6 / -4.3 | 0.5 / 1.6 |
| clean5986 | 2792 | 73 | 61 | 0 | 12 | 1.0 | 12.8 / -3.0 | 0.5 / 1.7 |
| v2_5985 | 2053 | 99 | 84 | 0 | 15 | 1.0 | 12.2 / 10.0 | 0.6 / 1.9 |
| v2_5986 | 1719 | 92 | 85 | 0 | 7 | 1.0 | 18.1 / 14.8 | 0.7 / 1.9 |
| v2_8000 | 2732 | 72 | 65 | 0 | 7 | 1.0 | 14.4 / 1.2 | 0.4 / 1.8 |
| v2_10000 | 3134 | 56 | 31 | 0 | 25 | 1.0 | 7.5 / -11.2 | 0.6 / 2.6 |
| v2_11400 | 2869 | 19 | 10 | 0 | 9 | 1.0 | 17.3 / 8.8 | 0.4 / 3.1 |

Abort reasons:

- clean5985_nominal: {'eight plans in a row the arm could not reach': 5}
- clean5986_nominal: {'eight plans in a row the arm could not reach': 5}
- v2_5985_nominal: {'eight plans in a row the arm could not reach': 5}
- v2_5986_nominal: {'eight plans in a row the arm could not reach': 5}
- v2_8000_nominal: {'eight plans in a row the arm could not reach': 5}
- v2_10000_nominal: {'ran out of ticks': 1, 'eight plans in a row the arm could not reach': 4}
- v2_11400_nominal: {'eight plans in a row the arm could not reach': 2, 'ran out of ticks': 1, 'the ball is in the bin': 2}

## Perturbation 18 (unseen intermediate cells, perturbed start)

| checkpoint | n | GRASP stage | LIFT stage | runtime grasped | ball lifted | strict GT secure | bin | corridor | pitch<20 | unreachable abort | ticks (per ep) | trap dwell s (mean) | prefix<=2 (mean) | infra retries |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean5986 | 16 | 16/16 | 2/16 | 2/16 | 2/16 | 2/16 | 0/16 | 0/16 | 13/16 | 13/16 | [215, 55, 185, 400, 153, 109, 181, 365, 400, 80, 150, 140, 400, 183, 159, 177] | 2.96 | 0.145 | 0 |
| v2_5986 | 16 | 14/16 | 6/16 | 6/16 | 6/16 | 3/16 | 2/16 | 4/16 | 16/16 | 14/16 | [58, 112, 33, 102, 74, 121, 101, 176, 185, 70, 52, 52, 172, 108, 151, 98] | 1.08 | 0.266 | 0 |
| v2_8000 | 16 | 16/16 | 8/16 | 8/16 | 8/16 | 4/16 | 3/16 | 2/16 | 15/16 | 13/16 | [85, 93, 39, 179, 186, 115, 105, 283, 143, 94, 184, 188, 123, 109, 135, 84] | 0.82 | 0.197 | 0 |
| v2_10000 | 16 | 16/16 | 11/16 | 11/16 | 11/16 | 5/16 | 3/16 | 6/16 | 15/16 | 11/16 | [156, 403, 43, 287, 400, 129, 398, 143, 128, 224, 238, 54, 176, 140, 101, 73] | 1.28 | 0.162 | 0 |
| v2_11400 | 16 | 16/16 | 10/16 | 10/16 | 10/16 | 8/16 | 4/16 | 5/16 | 15/16 | 7/16 | [223, 106, 400, 400, 268, 236, 155, 174, 254, 400, 400, 311, 259, 141, 403, 119] | 1.95 | 0.121 | 0 |

Stage ticks (mean per episode):

| checkpoint | SEARCH_OBJECT | APPROACH_OBJECT | GRASP | LIFT | SEARCH_BIN | TRANSPORT | PLACE | AFTER_RELEASE |
|---|---|---|---|---|---|---|---|---|
| clean5986 | 6 | 73 | 85 | 28 | 0 | 5 | 0 | 13 |
| v2_5986 | 2 | 56 | 10 | 14 | 0 | 5 | 2 | 14 |
| v2_8000 | 7 | 81 | 14 | 17 | 0 | 6 | 5 | 4 |
| v2_10000 | 1 | 93 | 42 | 18 | 1 | 5 | 5 | 28 |
| v2_11400 | 13 | 100 | 40 | 44 | 0 | 21 | 6 | 42 |

Close geometry at the onset of closing of the first real GRASP attempt (N/A = no GRASP attempt):

| checkpoint | n closes | lateral mm | depth mm | vertical mm | pitch deg | EE speed mm/tick |
|---|---|---|---|---|---|---|
| expert | 20 | -0.62 [-2.26, +2.20] | -22.62 [-23.66, -15.86] | +4.30 [+0.51, +8.19] | +12.57 [+7.91, +17.40] | ~0.15 |
| clean5986 | 16 | -2.70 (med -4.27, sd 3.42) | -2.55 (med -0.83, sd 5.68) | -9.61 (med -9.50, sd 6.82) | +29.36 (med +29.29, sd 4.22) | +3.55 (med +3.83, sd 2.13) |
| v2_5986 | 14 | +0.93 (med +1.70, sd 2.43) | -11.90 (med -11.41, sd 4.36) | +2.07 (med +5.95, sd 9.83) | +5.85 (med +9.44, sd 10.88) | +1.56 (med +0.97, sd 1.35) |
| v2_8000 | 16 | +1.26 (med +2.13, sd 2.30) | -12.50 (med -11.17, sd 4.86) | +2.42 (med +4.90, sd 8.63) | +6.49 (med +9.45, sd 12.34) | +1.02 (med +0.70, sd 1.05) |
| v2_10000 | 16 | +1.74 (med +2.18, sd 1.51) | -13.15 (med -12.00, sd 4.47) | +6.65 (med +6.83, sd 2.73) | +10.26 (med +11.64, sd 7.31) | +0.43 (med +0.38, sd 0.28) |
| v2_11400 | 16 | +0.89 (med +1.39, sd 2.02) | -11.68 (med -10.71, sd 5.30) | +4.88 (med +7.78, sd 8.33) | +7.83 (med +13.53, sd 11.82) | +0.41 (med +0.42, sd 0.22) |

Feasibility (runtime gate: solve_ik_best in-plane position residual > 2 mm; causes from re-solving each rejected target):

| checkpoint | attempted | rejected | joint limit | pitch unattainable | position unreachable, no limit | IK reproduction | asked pitch acc/rej | orientation residual acc/rej deg |
|---|---|---|---|---|---|---|---|---|
| clean5986 | 7502 | 130 | 109 | 0 | 21 | 1.0 | 21.4 / -19.0 | 0.4 / 1.9 |
| v2_5986 | 3988 | 176 | 163 | 0 | 13 | 1.0 | 12.2 / 4.0 | 0.8 / 3.0 |
| v2_8000 | 4822 | 183 | 162 | 0 | 21 | 1.0 | 8.2 / -7.2 | 0.5 / 3.5 |
| v2_10000 | 6722 | 132 | 97 | 0 | 35 | 1.0 | 6.1 / 3.7 | 0.4 / 7.3 |
| v2_11400 | 9746 | 249 | 223 | 0 | 26 | 0.9996921814077571 | 16.3 / 8.5 | 0.5 / 5.2 |

Abort reasons:

- clean5986_val18: {'eight plans in a row the arm could not reach': 13, 'ran out of ticks': 3}
- v2_5986_val18: {'eight plans in a row the arm could not reach': 14, 'the ball is in the bin': 2}
- v2_8000_val18: {'eight plans in a row the arm could not reach': 13, 'the ball is in the bin': 3}
- v2_10000_val18: {'the ball is in the bin': 3, 'ran out of ticks': 2, 'eight plans in a row the arm could not reach': 11}
- v2_11400_val18: {'the ball is in the bin': 4, 'ran out of ticks': 5, 'eight plans in a row the arm could not reach': 7}
