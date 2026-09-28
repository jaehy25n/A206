# rep1 vs rep2

contract rep1: holds=True  plans 1458  obs_dt!=0.1 0  pair not exact 0  frame not exact 0  state {'exact/recorder': 2916}  interp>10ms 0  nearest/none 0  extra-wait frames {'0': 1188, '2': 195, '1': 55, '3': 11, '4': 9}
contract rep2: holds=True  plans 1525  obs_dt!=0.1 0  pair not exact 0  frame not exact 0  state {'exact/recorder': 3049, 'interp/recorder': 1}  interp>10ms 0  nearest/none 0  extra-wait frames {'2': 431, '1': 280, '0': 642, '3': 82, '4': 86, '7': 1, '5': 3}

## nominal (n=5; infra {'rep1': [], 'rep2': []})
counts entered_corridor: 2 vs 3  object_lifted: 2 vs 3  strict_gt_secure_grasp: 1 vs 0  bin_success: 0 vs 3  consecutive_unreachable_abort: 4 vs 2
episode agreement rep1-rep2: entered_corridor 4/5  object_lifted 4/5  strict_gt_secure_grasp 4/5  bin_success 2/5  consecutive_unreachable_abort 1/5
  vs def (descriptive, n=5): rep1 C 4 L 4 S 5 B 3 a 3 | rep2 C 5 L 5 S 4 B 4 a 3
  vs v1 (descriptive, n=5): rep1 C 4 L 4 S 3 B 5 a 4 | rep2 C 3 L 3 S 4 B 2 a 0
  vs v2 (descriptive, n=5): rep1 C 3 L 3 S 4 B 4 a 3 | rep2 C 4 L 4 S 5 B 3 a 3
| ep | outcome a / b | plans | first diff plan: t_rel obs_dt k img lowdim ee>0.1 ee>2 | first input diff | first close a / b |
|---|---|---|---|---|---|
| 0 | CL..a / CL.B. | 40/54 | 1 None 32 0 0 1 3 | plan 0 t 0.00s px [567, 596] low 2.00e-06 ee 0.010mm | t15.83 d-12.4 v6.8 / t14.23 d-12.1 v5.1 |
| 1 | ..... / ....a | 175/143 | 1 None 126 0 1 1 1 | plan 0 t 0.00s px [354, 46] low 0.00e+00 ee 0.000mm | t28.42 d-10.3 v13.8 / - |
| 2 | CLS.a / CL.B. | 49/48 | 1 None 41 0 0 3 7 | plan 0 t 0.00s px [673, 730] low 2.00e-06 ee 0.010mm | t14.46 d-12.7 v7.9 / t14.12 d-12.7 v6.6 |
| 3 | ....a / CL.B. | 68/53 | 1 None None 0 0 1 4 | plan 0 t 0.00s px [833, 563] low 9.70e-05 ee 0.004mm | t15.92 d-4.1 v10.3 / t14.47 d-13.5 v2.8 |
| 4 | ....a / ....a | 66/62 | 1 None 54 0 0 2 2 | plan 0 t 0.00s px [147, 164] low 2.00e-06 ee 0.007mm | t10.62 d-6.9 v15.9 / t11.5 d-7.3 v16.9 |

## val18 (n=16; infra {'rep1': [11, 13], 'rep2': [11, 13]})
counts entered_corridor: 6 vs 4  object_lifted: 10 vs 10  strict_gt_secure_grasp: 7 vs 6  bin_success: 5 vs 3  consecutive_unreachable_abort: 8 vs 9
episode agreement rep1-rep2: entered_corridor 14/16  object_lifted 12/16  strict_gt_secure_grasp 11/16  bin_success 14/16  consecutive_unreachable_abort 11/16
  vs def (descriptive, n=16): rep1 C 11 L 12 S 9 B 13 a 11 | rep2 C 13 L 12 S 10 B 15 a 8
  vs v1 (descriptive, n=16): rep1 C 11 L 10 S 11 B 11 a 13 | rep2 C 11 L 12 S 10 B 13 a 10
  vs v2 (descriptive, n=16): rep1 C 11 L 12 S 9 B 13 a 11 | rep2 C 11 L 8 S 10 B 13 a 10
| ep | outcome a / b | plans | first diff plan: t_rel obs_dt k img lowdim ee>0.1 ee>2 | first input diff | first close a / b |
|---|---|---|---|---|---|
| 0 | CLSB. / CL.B. | 38/57 | 1 None None 0 0 1 2 | plan 0 t 0.00s px [77, 64] low 1.00e-06 ee 0.001mm | t6.52 d-13.5 v3.3 / t9.35 d-11.0 v2.1 |
| 1 | .L.B. / .LSB. | 36/31 | 1 None None 0 1 1 3 | plan 0 t 0.00s px [43, 447] low 0.00e+00 ee 0.002mm | t4.16 d-11.0 v7.7 / t4.55 d-15.3 v7.2 |
| 2 | CL..a / ....a | 18/104 | 1 None 10 0 1 2 4 | plan 0 t 0.00s px [27, 330] low 0.00e+00 ee 0.001mm | t3.81 d-12.5 v1.7 / t4.54 d-9.4 v4.9 |
| 3 | ..... / ..... | 115/105 | 1 None 58 0 0 1 2 | plan 0 t 0.00s px [492, 490] low 1.00e-06 ee 0.005mm | t8.26 d-10.7 v5.1 / t35.02 d-5.0 v-29.4 |
| 4 | ..... / ..... | 112/89 | 1 None 55 0 0 1 11 | plan 0 t 0.00s px [468, 152] low 1.00e-06 ee 0.006mm | t7.92 d-8.9 v10.8 / t5.76 d-9.8 v7.2 |
| 5 | .LSB. / .L..a | 38/60 | 1 None 12 0 0 1 9 | plan 0 t 0.00s px [510, 499] low 1.00e-06 ee 0.004mm | t4.01 d-20.4 v10.0 / t4.24 d-16.3 v11.4 |
| 6 | ....a / ....a | 53/46 | 1 None 38 0 0 1 3 | plan 0 t 0.00s px [244, 614] low 1.00e-06 ee 0.007mm | t4.22 d-7.4 v8.0 / t3.9 d-8.1 v5.7 |
| 7 | .LS.a / .L... | 56/103 | 1 None 11 0 1 1 2 | plan 0 t 0.00s px [145, 436] low 0.00e+00 ee 0.005mm | t4.74 d-13.8 v12.6 / t4.69 d-15.4 v10.4 |
| 8 | .LS.a / .LS.a | 62/78 | 1 None 23 0 0 1 3 | plan 0 t 0.00s px [114, 108] low 1.00e-06 ee 0.006mm | t4.18 d-19.0 v10.3 / t4.13 d-21.0 v9.3 |
| 9 | CL.B. / ....a | 114/58 | 1 None 50 0 0 1 12 | plan 0 t 0.00s px [518, 192] low 1.00e-06 ee 0.006mm | t9.36 d-12.1 v1.4 / t9.14 d-9.6 v3.4 |
| 10 | CLS.. / CLS.a | 147/105 | 1 None 33 0 0 1 3 | plan 0 t 0.00s px [479, 464] low 1.00e-06 ee 0.004mm | t10.9 d-20.6 v1.1 / t8.33 d-12.3 v1.0 |
| 12 | ....a / ..... | 62/102 | 1 None 38 0 0 1 6 | plan 0 t 0.00s px [472, 469] low 1.00e-06 ee 0.002mm | t10.24 d-6.2 v1.8 / t7.09 d-7.8 v3.7 |
| 14 | CLS.a / CLS.a | 76/50 | 1 None 13 0 0 1 3 | plan 0 t 0.00s px [44, 387] low 1.00e-06 ee 0.001mm | t3.97 d-20.8 v10.2 / t4.14 d-20.3 v11.0 |
| 15 | ....a / .L..a | 42/89 | 1 None 8 0 0 1 2 | plan 0 t 0.00s px [60, 397] low 1.00e-06 ee 0.002mm | t4.85 d-6.5 v6.7 / t6.32 d-10.0 v9.4 |
| 16 | ....a / .LS.a | 49/45 | 1 None 15 0 0 1 6 | plan 0 t 0.00s px [163, 134] low 1.00e-06 ee 0.005mm | t4.21 d-10.1 v7.5 / t4.2 d-10.4 v9.1 |
| 17 | CLSB. / CLSB. | 42/43 | 3 None None 0 1 2 2 | plan 0 t 0.00s px [115, 94] low 0.00e+00 ee 0.003mm | t5.19 d-15.6 v7.8 / t5.1 d-13.2 v7.1 |
