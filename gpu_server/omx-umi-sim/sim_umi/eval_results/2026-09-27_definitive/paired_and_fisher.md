## Per-episode, perturbation set (same 16 starts in every job)

Cell code: C = entered expert corridor, L = ball lifted (>20 mm), S = strict GT secure, B = ball in bin, a = 8-plan unreachable abort, . = none

| v2_val ep | perturb pitch / depth | clean5986 | v2_5986 | v2_8000 | v2_10000 | v2_11400 |
|---|---|---|---|---|---|---|
| 0 | 22.5 / +6.5 | a | a | LSa | CLB | CLSB |
| 1 | 22.5 / -0.5 | a | LSB | LB | . | LSB |
| 2 | 22.5 / -7.5 | a | a | CLa | CLa | . |
| 3 | 27.5 / +6.5 | . | a | a | LSa | . |
| 4 | 27.5 / -0.5 | a | CLa | a | . | a |
| 5 | 27.5 / -7.5 | a | CLB | LSB | LSa | La |
| 6 | 32.0 / +6.5 | a | a | a | a | a |
| 7 | 32.0 / -0.5 | a | a | a | LSa | a |
| 8 | 32.0 / -7.5 | LS | CLa | LSB | LSB | LSa |
| 9 | 22.5 / +6.5 | a | a | a | a | LS |
| 10 | 22.5 / -0.5 | a | a | La | a | LS |
| 12 | 27.5 / +6.5 | a | a | a | CLa | CLSa |
| 14 | 27.5 / -7.5 | LS | CLSa | CLSa | CLa | CLSa |
| 15 | 32.0 / +6.5 | a | a | a | CLSB | CLSB |
| 16 | 32.0 / -0.5 | a | LSa | a | La | . |
| 17 | 32.0 / -7.5 | a | a | La | CLa | CLB |

Not run (start infrastructure failure in every job, identical): v2_val 11 (bin placement intersects robot base), 13 (evaluation's HOME->perturbed-pose joint leg sweeps the bin).

## Fisher exact tests (two-sided; reference only -- raw counts are the result)

| comparison | metric | A | B | p |
|---|---|---|---|---|
| v2_5986_val18 vs clean5986_val18 | entered_corridor | 4/16 | 0/16 | 0.101 |
| v2_5986_val18 vs clean5986_val18 | object_lifted | 6/16 | 2/16 | 0.220 |
| v2_5986_val18 vs clean5986_val18 | strict_gt_secure_grasp | 3/16 | 2/16 | 1.000 |
| v2_5986_val18 vs clean5986_val18 | bin_success | 2/16 | 0/16 | 0.484 |
| v2_5986_val18 vs clean5986_val18 | consecutive_unreachable_abort | 14/16 | 13/16 | 1.000 |
| v2_11400_val18 vs clean5986_val18 | entered_corridor | 5/16 | 0/16 | 0.043 |
| v2_11400_val18 vs clean5986_val18 | object_lifted | 10/16 | 2/16 | 0.009 |
| v2_11400_val18 vs clean5986_val18 | strict_gt_secure_grasp | 8/16 | 2/16 | 0.054 |
| v2_11400_val18 vs clean5986_val18 | bin_success | 4/16 | 0/16 | 0.101 |
| v2_11400_val18 vs clean5986_val18 | consecutive_unreachable_abort | 7/16 | 13/16 | 0.066 |
| v2_11400_val18 vs v2_5986_val18 | entered_corridor | 5/16 | 4/16 | 1.000 |
| v2_11400_val18 vs v2_5986_val18 | object_lifted | 10/16 | 6/16 | 0.289 |
| v2_11400_val18 vs v2_5986_val18 | strict_gt_secure_grasp | 8/16 | 3/16 | 0.135 |
| v2_11400_val18 vs v2_5986_val18 | bin_success | 4/16 | 2/16 | 0.654 |
| v2_11400_val18 vs v2_5986_val18 | consecutive_unreachable_abort | 7/16 | 14/16 | 0.023 |
| v2_5986_nominal vs clean5986_nominal | entered_corridor | 1/5 | 0/5 | 1.000 |
| v2_5986_nominal vs clean5986_nominal | object_lifted | 1/5 | 0/5 | 1.000 |
| v2_5986_nominal vs clean5986_nominal | strict_gt_secure_grasp | 0/5 | 0/5 | 1.000 |
| v2_5986_nominal vs clean5986_nominal | bin_success | 0/5 | 0/5 | 1.000 |
| v2_5986_nominal vs clean5986_nominal | consecutive_unreachable_abort | 5/5 | 5/5 | 1.000 |
| v2_11400_nominal vs clean5986_nominal | entered_corridor | 3/5 | 0/5 | 0.167 |
| v2_11400_nominal vs clean5986_nominal | object_lifted | 3/5 | 0/5 | 0.167 |
| v2_11400_nominal vs clean5986_nominal | strict_gt_secure_grasp | 1/5 | 0/5 | 1.000 |
| v2_11400_nominal vs clean5986_nominal | bin_success | 2/5 | 0/5 | 0.444 |
| v2_11400_nominal vs clean5986_nominal | consecutive_unreachable_abort | 2/5 | 5/5 | 0.167 |
| v2_11400_nominal vs v2_5986_nominal | entered_corridor | 3/5 | 1/5 | 0.524 |
| v2_11400_nominal vs v2_5986_nominal | object_lifted | 3/5 | 1/5 | 0.524 |
| v2_11400_nominal vs v2_5986_nominal | strict_gt_secure_grasp | 1/5 | 0/5 | 1.000 |
| v2_11400_nominal vs v2_5986_nominal | bin_success | 2/5 | 0/5 | 0.444 |
| v2_11400_nominal vs v2_5986_nominal | consecutive_unreachable_abort | 2/5 | 5/5 | 0.167 |

## Runtime feasibility rejection rate (rejected / attempted waypoints)

| checkpoint | nominal | perturbation |
|---|---|---|
| clean5985 | 100/3090 = 3.24% | — |
| clean5986 | 73/2792 = 2.61% | 130/7502 = 1.73% |
| v2_5985 | 99/2053 = 4.82% | — |
| v2_5986 | 92/1719 = 5.35% | 176/3988 = 4.41% |
| v2_8000 | 72/2732 = 2.64% | 183/4822 = 3.80% |
| v2_10000 | 56/3134 = 1.79% | 132/6722 = 1.96% |
| v2_11400 | 19/2869 = 0.66% | 249/9746 = 2.55% |
