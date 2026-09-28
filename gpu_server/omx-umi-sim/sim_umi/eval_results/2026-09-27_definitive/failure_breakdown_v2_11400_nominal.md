# Episode breakdown — nominal_v2_11400.json

Gate reproduced: pitch from the raw finger axis, solve_ik_best with joints 2-4 clipped, refused above 2.0 mm. 'pinned' = within 0.5° of a hard limit; 'past limit if unclipped' = the same solve with the limits lifted; 'best pitch' = the pitch in a -30..90° scan with the smallest miss at that position.

### ep0 — eight plans in a row the arm could not reach (102 ticks; bin False)

- stages: SEARCH_OBJECT@0 → APPROACH_OBJECT@0 → GRASP@84 → LIFT@97
- ball max rise 40.7 mm; runtime grasped flag True; ball distance from the base 201.4 -> 163.0 mm (max 201.4)
- closing onset (GRASP entry tick 84): lateral -1.9, depth -13.0, vertical +6.9 mm, pitch 11.8°; jaw closed to 31.6 mm afterwards; object in crop True
- deepest along the finger axis before the first close: -13.99 mm; ever: -17.42 mm (expert onset -22.62 [-23.66, -15.86])
- object in crop during APPROACH/GRASP: 30/30 plans
- plans 40; with a refusal 10; nothing sendable 8
- first refusal: plan 30 at 16.92 s in GRASP (6 waypoints sent before it)
- **8-plan abort** starts plan 32 at 18.02 s in **LIFT**; plan before it sent 1
- measured joints then (deg; margin to lower / upper hard limit): joint1 +38.1 (308.1 / 321.9); joint2 -40.3 (79.7 / 130.3); joint3 +88.2 (208.2 / 1.8); joint4 -26.8 (73.2 / 126.8); joint5 +0.0 (270.0 / 270.0)
- ball then: rise 33.7 mm, tool frame [0.1, -15.5, 6.4] mm

| plan | t s | stage | obj / bin in crop | first due k | miss mm | asked pitch | pinned | past limit if unclipped (deg) | best pitch (miss) | reachable at some pitch | yaw discarded | target r / z mm | raw unreachable of 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 32 | 18.02 | LIFT | True / False | 5 | 20.62 | 23.29 | joint3 upper | {'joint3': 3.01} | 46.0 (0.0) | True | 0.0 | 166.3 / 69.0 | 8 |
| 33 | 18.43 | LIFT | True / False | 5 | 26.1 | 23.49 | joint3 upper | {'joint3': 3.54} | 50.0 (0.0) | True | 0.0 | 163.5 / 73.0 | 8 |
| 34 | 18.78 | LIFT | True / False | 5 | 25.04 | 23.39 | joint3 upper | {'joint3': 3.44} | 50.0 (0.0) | True | 0.0 | 164.1 / 72.4 | 8 |
| 35 | 19.18 | LIFT | True / False | 5 | 24.58 | 23.41 | joint3 upper | {'joint3': 3.4} | 50.0 (0.0) | True | 0.0 | 164.2 / 72.3 | 8 |
| 36 | 19.58 | LIFT | True / False | 5 | 25.48 | 23.41 | joint3 upper | {'joint3': 3.49} | 52.0 (0.0) | True | 0.0 | 164.0 / 72.3 | 9 |
| 37 | 19.98 | LIFT | True / False | 5 | 25.57 | 23.42 | joint3 upper | {'joint3': 3.5} | 52.0 (0.0) | True | 0.0 | 164.0 / 72.3 | 9 |
| 38 | 20.33 | LIFT | True / False | 5 | 25.7 | 23.43 | joint3 upper | {'joint3': 3.51} | 52.0 (0.0) | True | 0.0 | 164.0 / 72.2 | 9 |
| 39 | 20.73 | LIFT | True / False | 5 | 25.84 | 23.44 | joint3 upper | {'joint3': 3.53} | 46.0 (0.0) | True | 0.0 | 164.0 / 72.1 | 9 |

### ep1 — ran out of ticks (600 ticks; bin False)

- stages: SEARCH_OBJECT@0 → APPROACH_OBJECT@27 → GRASP@123 → APPROACH_OBJECT@143 → GRASP@147 → APPROACH_OBJECT@171 → GRASP@179 → APPROACH_OBJECT@199
- ball max rise 3.3 mm; runtime grasped flag False; ball distance from the base 225.2 -> 288.9 mm (max 288.9)
- closing onset (GRASP entry tick 123): lateral +3.2, depth -9.1, vertical +14.3 mm, pitch 20.8°; jaw closed to 38.5 mm afterwards; object in crop True
- GRASP entry tick 147: no new close -- the jaw only reopened to 48.0 mm since the last entry (open ~51.8)
- GRASP entry tick 179: no new close -- the jaw only reopened to 47.1 mm since the last entry (open ~51.8)
- deepest along the finger axis before the first close: -8.62 mm; ever: -9.09 mm (expert onset -22.62 [-23.66, -15.86])
- object in crop during APPROACH/GRASP: 146/146 plans
- plans 157; with a refusal 0; nothing sendable 0

### ep2 — the ball is in the bin (166 ticks; bin True)

- stages: SEARCH_OBJECT@0 → APPROACH_OBJECT@0 → GRASP@77 → LIFT@92 → TRANSPORT@110 → PLACE@150 → AFTER_RELEASE@166
- ball max rise 184.2 mm; runtime grasped flag True; ball distance from the base 222.4 -> 202.5 mm (max 222.4)
- closing onset (GRASP entry tick 77): lateral -2.0, depth -14.4, vertical +6.9 mm, pitch 14.4°; jaw closed to 31.3 mm afterwards; object in crop True
- deepest along the finger axis before the first close: -15.79 mm; ever: -20.15 mm (expert onset -22.62 [-23.66, -15.86])
- object in crop during APPROACH/GRASP: 27/27 plans
- plans 55; with a refusal 0; nothing sendable 0

### ep3 — the ball is in the bin (172 ticks; bin True)

- stages: SEARCH_OBJECT@0 → APPROACH_OBJECT@0 → GRASP@79 → LIFT@94 → TRANSPORT@133 → PLACE@156 → AFTER_RELEASE@172
- ball max rise 200.7 mm; runtime grasped flag True; ball distance from the base 210.3 -> 208.0 mm (max 214.1)
- closing onset (GRASP entry tick 79): lateral +3.1, depth -11.0, vertical +4.1 mm, pitch 12.1°; jaw closed to 32.3 mm afterwards; object in crop True
- deepest along the finger axis before the first close: -11.03 mm; ever: -22.46 mm (expert onset -22.62 [-23.66, -15.86])
- object in crop during APPROACH/GRASP: 29/29 plans
- plans 56; with a refusal 0; nothing sendable 0

### ep4 — eight plans in a row the arm could not reach (175 ticks; bin False)

- stages: SEARCH_OBJECT@0 → APPROACH_OBJECT@3 → GRASP@68 → APPROACH_OBJECT@80 → GRASP@155 → APPROACH_OBJECT@168
- ball max rise 3.9 mm; runtime grasped flag False; ball distance from the base 300.7 -> 445.1 mm (max 445.1)
- closing onset (GRASP entry tick 68): lateral +1.4, depth -7.9, vertical +15.6 mm, pitch 25.7°; jaw closed to 30.7 mm afterwards; object in crop True
- closing onset (GRASP entry tick 155): lateral -0.0, depth -8.7, vertical +3.0 mm, pitch -1.8°; jaw closed to 30.7 mm afterwards; object in crop True
- deepest along the finger axis before the first close: -7.86 mm; ever: -9.11 mm (expert onset -22.62 [-23.66, -15.86])
- object in crop during APPROACH/GRASP: 63/63 plans
- plans 66; with a refusal 9; nothing sendable 8
- first refusal: plan 57 at 29.36 s in GRASP (5 waypoints sent before it)
- **8-plan abort** starts plan 58 at 30.01 s in **APPROACH_OBJECT**; plan before it sent 5
- measured joints then (deg; margin to lower / upper hard limit): joint1 +7.5 (277.5 / 352.5); joint2 +75.4 (195.4 / 14.6); joint3 -49.5 (70.5 / 139.6); joint4 -30.0 (70.0 / 130.0); joint5 -0.0 (270.0 / 270.0)
- ball then: rise -0.2 mm, tool frame [4.7, 19.7, -0.6] mm

| plan | t s | stage | obj / bin in crop | first due k | miss mm | asked pitch | pinned | past limit if unclipped (deg) | best pitch (miss) | reachable at some pitch | yaw discarded | target r / z mm | raw unreachable of 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 58 | 30.01 | APPROACH_OBJECT | True / False | 5 | 7.41 | -5.53 | — | — | 12.0 (0.31) | True | 0.3 | 395.8 / 19.4 | 13 |
| 59 | 30.36 | APPROACH_OBJECT | True / False | 5 | 11.83 | -7.02 | — | — | 10.0 (3.67) | False | 0.3 | 399.5 / 20.5 | 14 |
| 60 | 30.76 | APPROACH_OBJECT | True / False | 5 | 9.66 | -6.84 | — | — | 10.0 (1.6) | True | 0.2 | 397.3 / 20.5 | 14 |
| 61 | 31.11 | APPROACH_OBJECT | True / False | 5 | 11.82 | -6.95 | — | — | 12.0 (3.58) | False | 0.3 | 399.1 / 19.4 | 14 |
| 62 | 31.51 | APPROACH_OBJECT | True / False | 5 | 12.49 | -7.15 | — | — | 12.0 (4.1) | False | 0.2 | 399.7 / 19.5 | 14 |
| 63 | 31.91 | APPROACH_OBJECT | True / False | 5 | 11.14 | -7.25 | — | — | 10.0 (2.75) | False | 0.2 | 398.5 / 20.6 | 14 |
| 64 | 32.31 | APPROACH_OBJECT | True / False | 5 | 11.97 | -7.52 | — | — | 10.0 (3.4) | False | 0.2 | 399.2 / 20.8 | 14 |
| 65 | 32.66 | APPROACH_OBJECT | True / False | 5 | 10.93 | -7.45 | — | — | 10.0 (2.44) | False | 0.2 | 398.3 / 21.3 | 14 |
