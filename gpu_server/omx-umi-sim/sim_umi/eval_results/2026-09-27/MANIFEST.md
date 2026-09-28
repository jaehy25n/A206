# 2026-09-27 — clean vs clean+corrective, at matched optimizer updates

> **Later finding (2026-09-27 overnight).** Some episodes in this folder did not start as described: the start placed the bodies before the arm went home, and the arm swept them (every nominal run's episode 3; val18 clean e60 episodes 5, 8, 10, 15, 16; v2 5985 episodes 10, 14, 15, 16, 17), and the not-ready retry skipped the perturbed pose (clean e60 3, 6; v2 5985 1, 3 began at HOME). The numbers below include them. Re-aggregation with those episodes marked invalid: `../2026-09-27_definitive/HISTORICAL_VARIANTS.md`.

**Purpose.** Whether filling the empty state support changed the closed-loop
behaviour. Not whether the ball reaches the bin -- nothing reliably did that
before -- but whether the arm still parks at twenty-eight degrees and closes
twenty millimetres short of a ball it never encloses.

**Control.** Same five training placements from HOME, and the same eighteen
validation placements started at their own perturbed pre-grasp pose. Same
executor, same deterministic reset, deterministic preprocessing, seed 1234,
K=8, both policy servers on GPU 5 with training stopped. The two checkpoints
differ in their training data and in nothing else that was allowed to vary:
the cosine horizon was pinned to the baseline's 11400 steps so the learning
rate at every optimizer step matches to 0.05%, EMA decay depends only on its
own step count and is identical at 5985, and gradient accumulation is 1 in
both. Everything is float32; no AMP anywhere.

`step5985.provenance.json` and `step5986.provenance.json` record where each
checkpoint sits: the scalar count of optimizer.step() calls, the
per-parameter step histogram, the learning rate and the EMA step. The
baseline has no such record -- its own parameters sit at 5985 (235 of them)
and 5986 (64), so its update count cannot be recovered exactly and both
neighbours were saved rather than one of them called a match.

## From HOME, the five training placements

| | clean e60 | +v2 step5986 | step5985 |
| --- | --- | --- | --- |
| time parked at 25-32 deg | 1.1 +- 0.9 s | **0.3 +- 0.1 s** | -- |
| reached pitch < 20 deg | 5/5 | 5/5 | -- |
| entered the grasp corridor | 0/5 | 0/5 | -- |
| GRASP reached | **3/5** | 0/5 | 0/5 |
| LIFT | **1/5** | 0/5 | 0/5 |
| ticks | 336 | 118 | 128 |

A regression, and a stable one: step5985 and step5986 are one update apart and
give 129/166/125/101/121 against 108/159/118/89/115 ticks, so evaluation noise
is not what this is.

The baseline itself is not the old baseline. It reaches pitch below 20 degrees
in 5 of 5 where the same checkpoint managed it in 0 of 2076 samples before --
that is the executor's latency compensation, not the data.

## From the perturbed starts, the eighteen validation placements

This is what the corrective set was built for, and the picture reverses.

| | expert | clean e60 | +v2 step5985 |
| --- | --- | --- | --- |
| **entered the grasp corridor** | -- | **0/18** | **4/18** |
| lateral at close | -0.62 mm | -23.14 | **+0.97** |
| depth at close | -22.62 mm | +28.86 | **-13.01** |
| vertical at close | +4.30 mm | -16.78 | **+3.91** |
| pitch at close | +12.57 deg | +21.10 | **+5.93** |
| EE speed at close | 0.15 mm/tick | 38.38 | **9.31** |
| GT secure grasp | -- | 0/18 | **2/18** |
| ball off the table | -- | 2/18 | **6/18** |
| ball in the bin | -- | 1/18 | **2/18** |
| time parked at 25-32 deg | -- | 0.7 s | 0.4 s |

Every axis of the closing geometry moves toward the expert at once, and the
vertical and lateral land on it: +3.91 against +4.30 mm, +0.97 against -0.62.
The corridor is entered at all for the first time in this project -- it was
0 of 8915 and 0 of 10666 samples in every rollout measured before.

The binary counts are too few to carry this on their own: 6/18 against 2/18
grasped is Fisher p = 0.228, and 2/18 against 1/18 in the bin is p = 1.00. The
evidence is in the continuous geometry, where five independent axes move the
same way by large margins, not in nineteen coin flips.

## Interpretation

The corrective data taught what it was built to teach. From a pose the clean
demonstrations never visit, the policy now closes roughly where the expert
closes rather than twenty-nine millimetres past the ball with the tool tipped
the wrong way, and it reaches the corridor.

It cost the ordinary approach. At matched updates the new model reaches GRASP
in 0 of 5 from HOME where the baseline reaches it in 3 of 5. The two runs have
seen their data a very different number of times for the same number of
updates -- 17.8 epochs against 63 -- so underfit is the obvious candidate and
is not yet ruled out.

## A caveat recorded rather than fixed

The first observation of an episode occasionally cannot be taken: the picture
stays as it was at the end of the previous rollout, the bin filling the frame
with one fingertip hidden, for more than five seconds, while a HOME frame
taken cleanly gives the same reading for all five placements. It fired in
roughly one episode in six. The rollout now waits for a valid observation and
resets again rather than starting on a stale one -- it never substitutes a
width -- and `obs_wait_s` records the wait. The cause is not diagnosed.
