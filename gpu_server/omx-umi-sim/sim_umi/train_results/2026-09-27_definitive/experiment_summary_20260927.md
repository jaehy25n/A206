# Definitive experiment — 2026-09-27 (overnight) — summary

## 아침 요약 (먼저 읽을 것)

- **Preflight 전부 PASS.** 물리 GPU 5만 사용 확인, dataset N (clean 6080 / combined 21532), val_ratio 0.0, shared init `a4cd264f…` 재현, resume smoke test PASS, 7개 step checkpoint 전부 디스크 재로딩 audit PASS (opt_steps = EMA count = scheduler last_epoch = AdamW step = N).
- **clean AMP step5986 nominal (n=5):** GRASP 5/5, LIFT 0/5, corridor 0/5, bin 0/5, 8-plan unreachable abort 5/5.
- **v2 AMP step5986 nominal (n=5):** GRASP 3/5, LIFT 1/5, corridor 1/5, bin 0/5, abort 5/5. Feasibility rejection 5.35% (clean 2.61%), 평균 154 ticks (clean 266) — 더 일찍 abort.
- **v2 nominal 8000 → 10000 → 11400:** LIFT 0 → 1 → 3/5, bin 0 → 0 → 2/5, corridor 0 → 0 → 3/5, abort 5 → 4 → 2/5, rejection 2.64 → 1.79 → 0.66%.
- **Perturbation (v2_val, 모든 job 동일한 16 start; 18개 중 2개는 모든 job에서 똑같이 start infra failure):** corridor / lifted / strict GT secure / bin / unreachable abort — clean5986 0/2/2/0/13, v2_5986 4/6/3/2/14, v2_8000 2/8/4/3/13, v2_10000 6/11/5/3/11, v2_11400 5/10/8/4/7 (모두 /16).
- **Matched step (5986):** v2가 recovery 쪽으로 방향은 좋지만 (corridor 4 vs 0, lifted 6 vs 2) n=16에서 Fisher p ≥ 0.10. v2_11400 vs clean5986: lifted 10 vs 2 (p = 0.009), strict 8 vs 2 (p = 0.054) — 참고용.
- **Abort:** 모든 checkpoint에서 주된 실패 모드는 "eight plans in a row the arm could not reach". v2_11400에서만 줄어듦 (nominal 2/5, perturbation 7/16).
- **Rejection reason:** 대부분 joint limit (v2_11400 perturbation 223/249, clean5986 nominal 61/73), 나머지는 limit 없이 position unreachable. "pitch unattainable" 0건. IK 재계산이 log와 0.05 mm 이내 일치: 11개 run 100%, 1개 99.97%.
- **AMP skipped update:** clean 0, v2 1 (10000–11400 사이, scale 2097152 → 1048576). non-finite loss 0.
- **판정: CASE A에 가장 가까움 (확장 dataset에 대한 under-training 영향이 강함).** 5986에서 이미 recovery ↑, 추가 학습하며 nominal이 점진적으로 회복되고 recovery도 유지·개선. 단, nominal n=5 (3/5 vs 0/5, p = 0.17), LR annealing과 dataset-pass 효과가 분리되지 않음, trade-off 배제 불가, underfit 수학적 배제 아님 (v2 11400 = 33.9 passes vs clean 63).
- **남은 blocker:** (1) 같은 schedule로 11400까지 학습한 clean AMP control이 없음 → "annealing" vs "v2 data 추가 pass" 분리 불가, 동일 budget에서의 trade-off 측정 불가. (2) nominal n=5 — placement 확대 필요. (3) 평가 start 절차 결함 두 개 (v2_val ep11: bin spec이 robot base와 겹침; ep13: 평가의 HOME→perturbed-pose joint leg가 bin을 침) + 주된 실패인 joint-limit 기반 unreachable abort, grasp depth가 expert보다 ~11 mm 얕음.

**밤사이 발견하고 고친 것 (결과 해석에 영향):**
- Start 순서 버그: body를 먼저 놓고 arm을 HOME으로 보냈음 → arm이 새로 놓인 ball/bin을 쓸고 지나감. 첫 nominal pass는 ep3 ball이 158–397 mm 밀린 채 시작 → **nominal 5개 job 전부 수정 후 재실행** (옛 결과는 `superseded_start_order_bug/`에 보존). 과거 FP32 run도 같은 문제 (nominal ep3, val18 여러 episode) → historical은 invalid-start로 표시해 재집계.
- Strict GT secure grasp metric을 두 번 수정 (threshold는 불변). ① release 후 낙하까지 포함하던 window → 이 정의로는 expert demo가 전부 실패. ② 첫 lifted stretch만 보던 것 → 0.04–0.11 s짜리 20 mm 선 스침을 판정하고 실제 운반을 놓침. 수정본은 expert demo 20/20, 48/48, 18/18, 5/5 통과. 옛 값은 `whole_lifted_*`로 결과에 남김.

---

## 1–2. Git commit / code diff

| 무엇 | commit |
|---|---|
| 기준 (protocol 시작 전) | `00756d1` |
| training path: checkpoint/resume/AMP 인프라 | `ad87c92` (clean run이 이 commit에서 실행) |
| evaluation only: fresh-observation gate, full-start retry | `b4e41e8` |
| evaluation only: not-ready 증거 저장 | `987ebe4` (v2 run이 이 HEAD에서 실행. provenance상 tracked dirty file 있음: 04:00 commit 이후 04:19 v2 시작 전까지 수정된 tracked 파일은 historical 재집계용 `aggregate.py`뿐이며 training이 import하지 않음; training-path 변경 없음은 03:42 check에서 확인) |
| evaluation only: HOME 먼저, 그다음 place, body 위치 검증 | `a721932` |
| evaluation only: infra-failure frame 이름에 job 표시 | `2943963` (definitive 평가 전부 이 commit에서 실행) |
| analysis scripts, results, 이 summary | 이 문서를 포함한 다음 commit |

Training-path 파일은 clean run 시작(`ad87c92`) 이후 변경 없음 (`preflight/06_training_path_frozen.txt`). Clean과 v2의 resolved config 차이는 정확히 의도된 6줄 (dataset path, step budget, checkpoint 목록; `config_diff_clean_vs_v2.txt`).

허용된 변경만 적용: AMP FP16 (Accelerate `mixed_precision='fp16'`, `model.half()`/BF16/TF32 조작 없음), v2 val_ratio 0.0, checkpoint/resume 인프라, update budget 11400. Architecture, encoder, action representation, horizons, DDIM, augmentation, optimizer/LR 3e-4/encoder 0.1×/warmup 2000/wd, batch 64, accum 1, EMA, seed 42, dataset 내용, sampler, executor, latency compensation, jaw scheduler, feasibility threshold, placements는 전부 동결.

## 3–9. Dataset / sampler / precision / batch / init

아래 "Provenance" 표 참조 (artefact에서 자동 생성). 요약: clean `omx_sim_train.zarr.zip` sha256 `b7fbfddc…` 25 segments, N 6080, DataLoader 95; combined `omx_sim_train_v2.zarr.zip` sha256 `905749cd…` 94 segments (앞 25개가 clean과 동일), N 21532, DataLoader 337; val_ratio 0.0, held-out 0, drop_last False; batch 64; precision fp16 autocast + GradScaler (forward 내부에서 autocast True, denoiser output float16 확인); shared init checksum `a4cd264f…` (normalizer 제외; seed만으로 bit 단위 재현).

AMP 사전 점검 (FP32 vs FP16, 같은 seed/batch64/dataset, 300 step): non-finite 0 / 0, skipped update 0 / 0, 속도 402 s vs 122 s (3.3×), 마지막 50 step loss 평균 0.0562 vs 0.0543, 고정 held-out batch loss 차이 1–5% (예외: step 100에서 35.7%, 급하강 구간). 300 step 후 같은 고정 observation에서 action 위치 최대 23.5 mm 차이 — 서로 독립적으로 진행한 두 학습의 차이이며 precision 결함의 증거로 해석하지 않음.

## 10. Optimizer / scheduler / EMA / scaler semantics

- step N checkpoint = 성공적으로 적용된 optimizer update가 정확히 N회 반영된 상태. `opt_steps`가 기준이고 `global_step`은 logging counter (accum=1에서 gradient-accumulation guard는 항상 참).
- 한 update의 순서: `accelerator.backward` → `optimizer.step()` → `step_was_skipped` 확인 → `zero_grad` → `lr_scheduler.step()` (AcceleratedScheduler는 skip된 step에서 진행하지 않음) → skip이 아니면 EMA step → `opt_steps += 1` → 해당 step이면 checkpoint → `max_opt_steps` 도달 시 정지.
- Scheduler: diffusers cosine with warmup, warmup 2000, horizon을 두 run 모두 11400으로 고정 → clean 5986과 v2 5986의 LR이 동일 (1.8546e-4 / encoder 1.8546e-5). v2 11400에서 LR 0 (cosine 끝).
- EMA: decay = 1 − (1+step)^−0.75, 상한 0.9999; 모든 checkpoint에서 EMA update count = opt_steps. 평가는 전부 EMA weights (`weights ema`를 server log에서 확인, 아니면 job 중단).
- GradScaler: 상태 저장·복원. AMP-skip된 step은 opt_steps/EMA/scheduler를 증가시키지 않음. 연속 skip은 HARD FAIL 조건 (발생 없음).
- Checkpoint 내용: raw model, EMA model, optimizer (항상), scheduler/scaler/EMA counter/RNG (python, numpy, torch CPU/CUDA)/counters/provenance (`payload['extra']`), 임시 이름으로 쓰고 fsync 후 rename. 인프라 작업 중 실제 버그 발견·수정: CPU tensor를 writer thread에 참조로 넘겨서 AdamW step counter가 저장 도중 증가 → clone으로 수정. 과거 baseline의 `{5985: 235, 5986: 64}` 분열이 같은 race임.

## 11–13. Checkpoint / LR / skipped AMP updates

아래 "Checkpoints" 표 참조. 전부 PASS. skipped update: clean 0, v2 1 (10000–11400 사이). Dataset passes: clean 63.0 @5986; v2 17.8 @5986, 23.8 @8000, 29.7 @10000, 33.9 @11400.

## 14–16. 평가 결과

평가 조건: 물리 GPU 5, policy server 하나씩, EMA weights, deterministic preprocessing, seed 1234, 같은 rolling executor (`--horizon-steps 8`), 같은 placements. Nominal = train placement 0–4, HOME start, max 600 ticks. Perturbation = v2_val 0–17, perturbed start, max 400 ticks.

Start 절차 (`a721932`): deterministic reset → body 배치 → free-joint ground truth로 두 body 확인 (≤2 mm, bin yaw ≤1°, 0.3 s 동안 정지; 아니면 infra retry) → perturbed pose (perturbation set) → bin 재확인 + ball 정지 확인; perturbed move로 ball이 밀리는 것은 기록만 함 (**모든 demonstration도 같은 pose에서 ball을 민다**: v2_val 2.4–16.0 mm, clean train은 grasp 전 3.1–8.9 mm). 25 mm 넘게 밀린 경우만 거부 → fresh-observation gate. 모든 counted start의 ball 편차: nominal 0.19 mm, perturbation 최대 12.83 mm; bin 0.75 mm (resting contact offset).

**Completeness** — 아래 표 참조. Nominal 7개 job은 5/5 complete. Perturbation 5개 job은 16/18 PARTIAL: v2_val **ep11** (bin spec이 robot base link0와 최대 5.4 mm 겹침 → HOME에서도 bin이 밀림; placement spec 결함)과 **ep13** (평가의 HOME→perturbed-pose joint leg가 bin을 8.4 mm 관통 → bin 102 mm / 117° 밀림; collector의 ring+blend 경로는 bin을 피함). 둘 다 policy와 무관하고 모든 job에서 3회 동일하게 실패 → 모든 비교는 같은 16 episode에서의 paired 비교. 평가 도중 경로를 바꾸면 이미 끝난 job과 start가 달라지므로 수정하지 않음.

Close geometry (첫 실제 GRASP 시도의 closing onset; perturbation 평균, expert 대비):

| axis | expert | clean5986 | v2_5986 | v2_11400 | 이동 방향 |
|---|---|---|---|---|---|
| lateral mm | −0.62 | −2.70 | +0.93 | +0.89 | 오차 2.1 → 1.6 → 1.5 |
| depth mm | −22.62 | −2.55 | −11.90 | −11.68 | 오차 20.1 → 10.7 → 10.9 (절반 남음) |
| vertical mm | +4.30 | −9.61 | +2.07 | +4.88 | 오차 13.9 → 2.2 → 0.6 |
| pitch deg | +12.57 | +29.36 | +5.85 | +7.83 | 오차 16.8 → 6.7 → 4.7 (sd 11.8) |
| EE speed mm/tick | ~0.15 | 3.55 | 1.56 | 0.41 | 3.4 → 1.4 → 0.26 |

다섯 축 모두 expert 쪽으로 이동. depth는 여전히 expert보다 ~11 mm 얕음.

## 17. Feasibility rejection

Runtime gate는 하나: `solve_ik_best` in-plane position residual > 2 mm. 거부된 target을 같은 IK, 같은 kinematics 파일로 다시 풀어 원인을 분해함 (log와 0.05 mm 이내 재현: 11개 run 100%, v2_11400 perturbation 99.97%). 원인은 joint limit이 대부분, 나머지는 limit 없이 position unreachable; "pitch unattainable"은 0건. Rejection rate와 abort 표는 아래 참조. 거부 비율 자체는 낮지만 (0.7–5.4%) abort는 흔함: 거부가 episode 끝에 몰림 — 8-plan abort로 끝난 89개 episode에서 거부된 waypoint 1242개 중 712개 (57.3%)가 마지막 8 plan에 있음. policy가 도달 불가 영역으로 들어가 거기 머물다 abort하는 패턴.

## 18. Infra retry / stale frame

Definitive 평가 (수정된 start): counted start 115개 전부 첫 시도에 fresh-observation gate 통과 (대기 중앙값 0.053 s, 최대 0.110 s; 새 frame 1–2개). Retry 0. Infra failure = perturbation job마다 2개 (ep11, ep13; 각 3회 시도), task outcome으로 세지 않음. 첫 (superseded) nominal pass의 not-ready 3건은 전부 밀려난 bin이 camera에 보이던 경우. 이것은 오늘 밤의 not-ready 사례에 대한 설명이며, 과거에 관찰된 stale-frame 현상 전체를 반증한 것으로 보지 않음.

## 19. Under-training vs trade-off 판정

- **CASE A 조건:** v2 5986에서 recovery ↑ (corridor 4 vs 0, lifted 6 vs 2, bin 2 vs 0) / nominal ↓는 feasibility 쪽에서만 (rejection 5.35% vs 2.61%, 더 이른 abort, GRASP 3/5 vs 5/5). clean 자체가 nominal LIFT 0/5라 LIFT/bin에서는 ↓가 드러날 여지가 없음. 8000 → 10000 → 11400에서 nominal LIFT 0 → 1 → 3, bin 0 → 0 → 2, abort 5 → 4 → 2, rejection 2.64 → 1.79 → 0.66% 로 점진적 회복, recovery는 유지·개선 (lifted 6 → 8 → 11 → 10, strict 3 → 4 → 5 → 8, abort 14 → 13 → 11 → 7). → **CASE A 패턴.**
- **CASE B** (11400까지 nominal early abort 지속): 해당 안 됨 — v2_11400 nominal abort 2/5. **CASE C** (recovery 소멸): 해당 안 됨. **CASE D** (clean AMP가 FP32 clean과 크게 다름): 해당 안 됨 — 아래 20 참조.
- **한계 (결론을 이 이상으로 쓰지 않음):** nominal은 n=5 (v2_11400 vs clean5986 LIFT 3/5 vs 0/5, p = 0.17). 5986 → 11400 개선에는 v2 data pass 증가와 LR annealing (1.85e-4 → 0)이 섞여 있고, clean은 11400까지 학습하지 않았으므로 annealed clean과의 비교가 없음 → trade-off 배제 불가. v2 11400도 33.9 passes로 clean 63 passes에 못 미침 → underfit을 수학적으로 배제한 것 아님. Episode 단위로 보면 checkpoint 사이 변동이 커서 (아래 per-episode 표) 추세는 집계 수준에서만 말할 수 있음.
- **최종:** 현재 계획된 scheduler/budget 안에서 nominal 성능은 회복됨 (v2_11400이 clean5986보다 모든 nominal 지표에서 같거나 좋음), recovery도 유지 → **under-training (CASE A)**. 동일 budget의 annealed clean control 없이는 trade-off 크기를 판정할 수 없음.

## 20. 기존 FP32 historical 결과와의 차이

Historical은 참고용 (start 검사 + 수정된 metric으로 재집계, `HISTORICAL_VARIANTS.md`, `*_metric0800.json`). Historical start는 오늘 밤 start와 물리적으로 다름 (예: clean e60 val ep1은 settle 안 된 채 ~10 mm 높게, pitch 20.7°로 시작; 수정된 절차는 ball을 12.4 mm 밀고 23.5°에 settle) → episode 단위 비교 불가.

| run | n | GRASP | LIFT | strict | bin | corridor | abort |
|---|---|---|---|---|---|---|---|
| FP32 clean e60 nominal (ep3 invalid) | 4 | 4 | 1 | 1 | 0 | 0 | 4 |
| **AMP clean5986 nominal** | 5 | 5 | 0 | 0 | 0 | 0 | 5 |
| FP32 v2 5986 nominal (ep3 invalid) | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| **AMP v2_5986 nominal** | 5 | 3 | 1 | 0 | 0 | 1 | 5 |
| FP32 clean e60 val18 (valid 11) | 11 | 11 | 2 | 1 | 1 | 0 | 9 |
| **AMP clean5986 perturbation** | 16 | 16 | 2 | 2 | 0 | 0 | 13 |
| FP32 v2 5985 val18 (valid 11, 다른 subset) | 11 | 10 | 6 | 4 | 2 | 4 | 9 |
| **AMP v2_5986 perturbation** | 16 | 14 | 6 | 3 | 2 | 4 | 14 |

AMP clean은 FP32 clean과 크게 다르지 않음 (둘 다 nominal에서 grasp 단계에서 실패, perturbation corridor 0) → CASE D 아님. FP32 v2는 val_ratio 0.05 (train N 19898)로 학습됐고 checkpoint save race가 있던 시기의 run이라 새 AMP A/B와 섞어 단정하지 않음. Protocol에 적힌 historical 숫자 (clean corridor 0/18, lift 2/18, bin 1/18; v2 5985 corridor 4/18, lift 6/18, bin 2/18)는 invalid start (HOME start, 밀린 ball)를 포함한 값임. 이전에 보고한 "historical run에는 strict secure grasp가 없음"은 깨진 metric에서 나온 것이라 철회함.

## 환경 메모

- 우리 프로세스는 전부 물리 GPU 5. Simulator의 EGL context는 GPU 0 (source에 hardcode, 기존과 동일).
- ROS graph에 오래된 `move_group` (9/26 17:25)와 `robot_state_publisher` (9/25)가 계속 떠 있었음. 모든 run에서 동일하게 존재했고, rollout은 MoveIt으로 planning하지 않음 (projection). 실험 도중 환경을 바꾸지 않으려고 그대로 둠.
- `server_<label>.log`는 nominal job과 perturbation job이 같은 이름을 써서 perturbation 쪽이 덮어씀. 각 job의 checkpoint와 EMA 확인 기록은 `eval_chain2.log`에 남아 있음.

## 파일

- Journal (purpose/control/result/interpretation, 시간순): `sim_umi/train_results/2026-09-27_definitive/JOURNAL.md`
- 최종 aggregate: `sim_umi/eval_results/2026-09-27_definitive/aggregate_definitive_final.json` (part1 + part2 병합; provisional 파일은 기록용)
- 표: `tables_definitive.md`, `paired_and_fisher.md` (아래에 그대로 붙임)
- Rollout log: `*.json` (원본, disk), `*.json.gz` (git). Infra failure frame: `val18_*_infra_fail_ep{11,13}.png`
- Superseded 첫 nominal pass: `superseded_start_order_bug/`
- Checkpoint (git 제외): `sim_umi/train_results/2026-09-27_amp_{clean,v2}_definitive/checkpoints/step*.ckpt` + `.audit.json`

---

# 자동 생성 표 (tables_definitive.md)

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
