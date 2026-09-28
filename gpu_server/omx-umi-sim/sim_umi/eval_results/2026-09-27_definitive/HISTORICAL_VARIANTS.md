# Historical FP32 results, re-aggregated under the definitive metric definitions

Reference only. The definitive conclusions use the new AMP clean/v2 evaluations
in this directory, not these files.

The historical perturbed (v2_val) evaluations had a start-procedure bug: when
the first-observation check failed, the retry repeated place + reset but not
the move to the perturbed pose, so those episodes began at HOME. Their
`started_perturbed` field is populated anyway (it was written before the
retry), so the logs themselves overstate the perturbed count.

- clean e60 val18: episodes 3 and 6 began at HOME
- v2 step5985 val18: episodes 1 and 3 began at HOME

Three variants, kept apart on purpose:

| file | what it counts |
| --- | --- |
| `historical_fp32_nominal_and_val18_ALL_including_invalid_starts.json` | nominal runs, plus the val18 runs with all 18 episodes -- INCLUDING the invalid HOME starts. Not a valid perturbation result. |
| `historical_fp32_val18_valid_only.json` | each val18 run on its own valid perturbed starts: clean e60 16 episodes, v2 5985 16 episodes (different subsets) |
| `historical_fp32_val18_common15.json` | both val18 runs on the 15 episodes that were a valid perturbed start in BOTH (1, 3, 6 excluded) -- the only historical like-for-like A/B |

Metric definitions are those of `sim_umi/scripts/definitive/aggregate.py`. In
particular the strict GT secure grasp is stricter than the 6 mm check used in
the earlier `compare_ab.py` report (which gave "2/18"): it requires the ball
held for at least 0.5 s, its tool-frame position within 4 mm of its mean, and
at least 30 mm of tool travel while held. Under it no historical run has a
strict secure grasp. Historical logs carry no jaw track, so close geometry is
N/A for all of them.


## Update 06:40 — displaced-body starts (supersedes the valid-only and common-15 files above)

A second start defect was found at 06:05: every historical run placed the ball
and bin BEFORE sending the arm home, and the arm's way home swept through them.
Checked post hoc against the logged free-joint ball at the first rollout
sample (tolerance 2 mm from HOME, 25 mm at a perturbed pose -- every
demonstration nudges the ball by up to 16 mm there):

- nominal (clean e60, v2 5986, v2 5985): episode 3's ball 275-340 mm off in all three
- clean e60 val18: episodes 5, 8, 10, 15, 16 (99 mm to 5 m, i.e. off the table)
- v2 5985 val18: episodes 10, 14, 15, 16, 17

So `historical_fp32_val18_valid_only.json` and `historical_fp32_val18_common15.json`
still COUNT displaced-ball starts. They are kept, unmodified, as a record, and are
superseded by:

| file | what it counts |
| --- | --- |
| `historical_fp32_valid_only_startchecked.json` | every historical run on its own valid starts: nominal 4/5 each (episode 3 out); clean e60 val18 11 (3, 5, 6, 8, 10, 15, 16 out); v2 5985 val18 11 (1, 3, 10, 14, 15, 16, 17 out) |
| `historical_fp32_val18_common8_startchecked.json` | both val18 runs on the 8 episodes valid in BOTH (0, 2, 4, 7, 9, 11, 12, 13) -- the only historical like-for-like A/B left |

Common-8 (reference only): clean e60 -- GRASP 8/8, LIFT 0/8, lifted 0/8,
corridor 0/8, strict secure 0/8, bin 0/8, unreachable abort 8/8;
v2 5985 -- GRASP 7/8, LIFT 3/8, lifted 3/8, corridor 2/8, strict secure 0/8,
bin 0/8, unreachable abort 8/8. n=8: no statistical claim.

The historical perturbed starts were also not the same physical starts as the
definitive ones (e.g. clean e60 val episode 1 began unsettled, ~10 mm higher,
pitch 20.7 deg, where the fixed procedure pushes the ball 12.4 mm and settles at
23.5 deg), so historical and definitive val18 are not comparable episode by
episode.

## Update 07:05 — corrected strict-secure metric: the `_final` files are the ones to use

The strict GT secure grasp was first measured over every lifted sample, which
includes the ball's fall after release; that definition fails every expert
demonstration. Corrected (same thresholds) to the lifted stretch from lift-off
while the ball rides with the tool; expert demos then pass 20/20, 48/48, 18/18.
The statement above that "no historical run has a strict secure grasp" came
from the broken definition and is withdrawn.

Use these (start-checked AND corrected metric):

| file | contents |
| --- | --- |
| `historical_fp32_valid_only_final.json` | each run on its own valid starts |
| `historical_fp32_val18_common8_final.json` | both val18 runs on the 8 episodes valid in both |

valid-only: clean e60 nominal (n=4) GRASP 4, LIFT 1, lifted 1, strict secure 0, bin 0;
v2 5986 / 5985 nominal (n=4 each) all 0 beyond APPROACH/GRASP;
clean e60 val18 (n=11) GRASP 11, LIFT 2, lifted 2, strict secure 1, bin 1;
v2 5985 val18 (n=11, a different subset) GRASP 10, LIFT 6, lifted 6, strict secure 4, bin 2.

common-8: clean e60 GRASP 8, LIFT 0, lifted 0, strict secure 0, bin 0;
v2 5985 GRASP 7, LIFT 3, lifted 3, strict secure 1, bin 0. n=8: reference only.

`*_startchecked.json` (06:40) have the right starts but the broken metric;
`historical_fp32_val18_valid_only.json` / `_common15.json` have neither fix.
All kept unmodified as a record.

## Update 08:20 — metric correction #2; the `_metric0800` files are the ones to use

The 06:50 strict-secure version judged only the FIRST lifted stretch, which
can be a 0.04-0.11 s graze of the 20 mm line; now every lifted stretch is
judged from its own lift-off (same thresholds; expert demos 20/20, 48/48,
18/18, 5/5). USE:

- `historical_fp32_valid_only_metric0800.json`
- `historical_fp32_val18_common8_metric0800.json`

valid-only: clean e60 nominal (n=4) GRASP 4, LIFT 1, lifted 1, strict 1, bin 0, abort 4;
v2 5986 and v2 5985 nominal (n=4 each) GRASP 0, all later stages 0, abort 4;
clean e60 val18 (n=11) GRASP 11, LIFT 2, strict 1, bin 1, corridor 0, abort 9;
v2 5985 val18 (n=11, different subset) GRASP 10, LIFT 6, strict 4, bin 2, corridor 4, abort 9.
common-8: clean e60 GRASP 8, LIFT 0, strict 0, bin 0, corridor 0;
v2 5985 GRASP 7, LIFT 3, strict 1, bin 0, corridor 2.

The `_final` files (07:05) carry correction #1 only; kept as a record.
