# G1/G2 rough screening (asynchronous evaluator; screening only)

## nominal
| run | C | L | S | B | a | close depth med | close vertical med |
|---|---|---|---|---|---|---|---|
| G0 def | 3 | 3 | 1 | 2 | 2 | -11.0 | 6.9 |
| G0 v1 | 3 | 3 | 1 | 0 | 3 | -9.5 | 8.4 |
| G0 v2 | 2 | 4 | 0 | 1 | 4 | -11.7 | 7.7 |
| G0 rep1 | 2 | 2 | 1 | 0 | 4 | -10.3 | 10.3 |
| G0 rep2 | 3 | 3 | 0 | 3 | 2 | -12.4 | 5.9 |
| **G0 range** | 2-3 | 2-4 | 0-1 | 0-3 | 2-4 | -12.4..-9.5 | 5.9..10.3 |
| **G1** | 2 | 3 | 3 | 1 | 3 | -10.2 | 6.7 |
| **G2** | 0 | 2 | 1 | 1 | 2 | -10.8 | 2.9 |

## val18
| run | C | L | S | B | a | close depth med | close vertical med |
|---|---|---|---|---|---|---|---|
| G0 def | 5 | 10 | 8 | 4 | 7 | -10.7 | 7.8 |
| G0 v1 | 7 | 14 | 10 | 6 | 7 | -13.0 | 6.4 |
| G0 v2 | 5 | 10 | 6 | 4 | 7 | -11.7 | 5.6 |
| G0 rep1 | 6 | 10 | 7 | 5 | 8 | -12.3 | 7.6 |
| G0 rep2 | 4 | 10 | 6 | 3 | 9 | -10.7 | 7.1 |
| **G0 range** | 4-7 | 10-14 | 6-10 | 3-6 | 7-9 | -13.0..-10.7 | 5.6..7.8 |
| **G1** | 4 | 10 | 6 | 3 | 7 | -11.8 | 6.2 |
| **G2** | 4 | 8 | 4 | 4 | 10 | -14.7 | 5.6 |

## Rule (registered 18:15)
- G1: (1) perturbation lifted 10 (G0 10-14) and bin 3 (G0 3-6) outside by >= 2 in one direction: False; (2) nominal not opposite: True; (3) close median depth -11.8 / vertical 6.2 beyond G0 range by 3 mm: False -> similar: no provisional selection
- G2: (1) perturbation lifted 8 (G0 10-14) and bin 4 (G0 3-6) outside by >= 2 in one direction: False; (2) nominal not opposite: True; (3) close median depth -14.7 / vertical 5.6 beyond G0 range by 3 mm: False -> similar: no provisional selection

## Per episode, perturbation (C L S B a)
| ep | G0 def | G0 v1 | G0 v2 | G0 rep1 | G0 rep2 | G1 | G2 |
|---|---|---|---|---|---|---|---|
| 0 | CLSB. | CLSB. | ..... | CLSB. | CL.B. | ....a | CLSB. |
| 1 | .LSB. | .LSB. | .LSB. | .L.B. | .LSB. | .LSB. | .LSB. |
| 2 | ..... | ....a | .L..a | CL..a | ....a | .L..a | CL..a |
| 3 | ..... | CLSB. | CLSB. | ..... | ..... | ..... | ..... |
| 4 | ....a | ..... | ....a | ..... | ..... | CL..a | ....a |
| 5 | .L..a | .LS.. | .LSB. | .LSB. | .L..a | .LSB. | .LS.a |
| 6 | ....a | .L..a | ..... | ....a | ....a | CLS.. | ....a |
| 7 | ....a | .L..a | .L... | .LS.a | .L... | ..... | .L..a |
| 8 | .LS.a | .LSB. | .LS.. | .LS.a | .LS.a | .LSB. | .L.B. |
| 9 | .LS.. | CLS.a | CLS.. | CL.B. | ....a | .L..a | ....a |
| 10 | .LS.. | CLSB. | ....a | CLS.. | CLS.a | ....a | ..... |
| 12 | CLS.a | CL..a | CL..a | ....a | ..... | ....a | ....a |
| 14 | CLS.a | .LS.a | CLS.a | CLS.a | CLS.a | CLS.. | CLS.a |
| 15 | CLSB. | CLS.. | ....a | ....a | .L..a | CLS.. | ....a |
| 16 | ..... | .L..a | ....a | ....a | .LS.a | ....a | ....a |
| 17 | CL.B. | CLSB. | CL.B. | CLSB. | CLSB. | .L... | CL.B. |
