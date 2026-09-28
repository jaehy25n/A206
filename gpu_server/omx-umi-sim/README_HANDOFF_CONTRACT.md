# CPU ↔ GPU Handoff Contract

양쪽이 같은 의미를 공유해야 하는 것만 모은 문서.
구현 상세는 각 문서로:

| 문서 | 다루는 것 |
|---|---|
| [`README_CPU_GPU_SYNC.md`](README_CPU_GPU_SYNC.md) | 전송 — READY gate, staging, rsync, 재-publish 처리 |
| [`README_GPU_VALIDATION.md`](README_GPU_VALIDATION.md) | 검증 게이트 — 무엇이 왜 FAIL 하는가 |
| [`README_GPU_WORKFLOW.md`](README_GPU_WORKFLOW.md) | 학습 — zarr, 실험, 로봇 핸드오프 |
| [`REPORT_STAGE_A_INTEGRATION.md`](REPORT_STAGE_A_INTEGRATION.md) | **2026-09-21 실데이터 통합 실행 결과** |
| [`README_JETSON_HANDOFF.md`](README_JETSON_HANDOFF.md) | **GPU → Jetson runtime contract** |
| [`README_JETSON_SETUP.md`](README_JETSON_SETUP.md) | **Jetson 수령 후 작업 절차** |

---

## 1. 책임 분리

| 항목 | CPU | GPU |
|---|---|---|
| RGB / timestamp 정렬 | **생성** | 검증 |
| ARCore pose alignment | **생성** | 검증 |
| tracking validity 판정 | **생성** | 검증 |
| start / end trim | **수행** | 안 함 |
| short gap interpolation | **수행** | 안 함 |
| SLERP | **수행** | 안 함 |
| long gap split | **수행** | 안 함 |
| unusable episode reject | **수행** | 안 함 |
| short segment reject | **수행** | 검증 |
| `pose_interpolated` | **생성** | 해석 |
| `READY` | **생성** | gate 로 사용 |
| rsync | 읽힐 데이터 제공 | **pull** |
| 30 → 10 Hz | 안 함 | **수행** |
| `T_camera_EE` | 안 함 | **적용** |
| UMI Zarr | 안 함 | **생성** |
| model training | 안 함 | **수행** |

한 줄로: **CPU = repair, GPU = strict gate.**

GPU 는 trajectory repair 를 새로 만들지 않는다. 같은 정제 로직이 두 곳에 있으면
한쪽만 고쳤을 때 dataset 이 조용히 갈라지고, GPU 가 고쳐버리면 CPU output 이
깨졌다는 사실 자체가 드러나지 않는다.

---

## 2. `frames.csv` 스키마

RGB frame 하나당 한 행. **행 개수 == `rgb_frames/` 이미지 개수.**

| 컬럼 | 필수 | 의미 |
|---|---|---|
| `frame_idx` | 권장 | 0 부터 연속 |
| `timestamp_ns` | **필수** | 정렬된 timestamp. `timestamp`(초)도 허용 |
| `rgb_path` | 권장 | episode 디렉토리 기준 상대 경로 |
| `camera_tx/ty/tz` | **필수** | `T_world_camera` translation, **meter** |
| `camera_qx/qy/qz/qw` | **필수** | `T_world_camera` rotation, **[x,y,z,w]** |
| `tracking_state` | 권장 | ARCore 원본 상태. **보간해도 덮어쓰지 않는다** |
| `pose_valid` | 권장 | 이 행의 pose 를 써도 되는가 (보간 후 최종 판단) |
| `pose_valid_original` | 권장 | 보간 전, 원본 측정이 유효했는가 |
| `pose_interpolated` | 권장 | CPU 가 채워 넣은 행인가 |
| `gripper_width_m` | **필수(Stage B)** | finger opening, **meter** |

컬럼명이 다르면 코드를 고치지 말고 `configs/collector/default.yaml` 의
`field_map` 에 한 줄 추가한다.

```yaml
field_map: {timestamp_ns: t_ns, gripper: gripper_width_m}
```

### 값 규약

```
world frame      ARCore session-local, Y-up. GPU 는 축 변환을 하지 않는다
position         meter
quaternion       [qx, qy, qz, qw],  |q| = 1 (tolerance 1e-2)
gripper          meter. physical finger opening (0~1 normalized 아님)
usable tracking  tracking / normal / ok / good / true / 1
timestamp        strictly increasing
```

### provenance 조합

```
직접 ARCore 측정   pose_valid_original=true   pose_interpolated=false  pose_valid=true
CPU 보간           pose_valid_original=false  pose_interpolated=true   pose_valid=true
                   tracking_state 는 PAUSED/MISSING 원본 그대로 유지
```

이 두 가지 외의 조합은 GPU 가 contract 위반으로 잡는다 (§5 참고).

---

## 3. CPU 가 보장하는 것

`READY` 를 쓰는 시점에 아래가 전부 참이어야 한다.

```
1.  RGB 개수 == frames.csv 행 개수, rgb_path 전부 실제 파일
2.  frame_idx 연속, timestamp strictly increasing
3.  pose 컬럼에 blank 셀 없음        ← 값을 못 구했으면 그 행을 남기지 않는다
4.  quaternion 전부 finite, norm ≈ 1
5.  pose_valid=false 인 행이 남아있지 않음
       trim / 보간 / split / reject 로 전부 처리됨
6.  비정상 tracking_state 행은 반드시 pose_interpolated=true
7.  usable segment 가 없으면 READY 를 쓰지 않는다
8.  segment 길이 >= 46 source frames (= 10 Hz 에서 16 stored frames)
9.  rejected 결과물은 rejected_episode_* / failed_episode_* 로 분리
10. READY 는 위 전부가 성공한 뒤 '마지막에' 생성
```

`READY` 는 **`(session_output_dir / "READY").touch()`** 한 줄이고,
반드시 validation 성공 후여야 한다. 중간에 쓰면 GPU 가 미완성 session 을 가져간다.

---

## 4. GPU 가 보장하는 것

```
1.  READY 없는 session 은 읽지 않는다
2.  .incoming / .superseded / rejected_* / failed_* 는 읽지 않는다
3.  CPU 데이터를 수정하지 않는다  (mirror 는 읽기 전용)
4.  blank 셀을 숫자로 채우지 않는다  (NaN 으로 두고 FAIL)
5.  invalid frame 을 조용히 버리지 않는다
6.  짧은 segment 를 조용히 버리지 않는다
7.  CPU 가 보간한 행(pose_interpolated=true)은 정상 데이터로 받아들인다
8.  inspector 와 converter 의 판정이 항상 같다  (테스트로 고정)
9.  실패하면 session / episode / 컬럼 / row 까지 보고한다
10. 사용한 calibration 과 설정을 zarr metadata 와 W&B 에 남긴다
```

---

## 5. 경계에서 일어나는 일

```
CPU  /srv/processed/v1/<session>/READY
        │  rsync over SSH   (GPU 가 pull, CPU 는 push 하지 않음)
        ▼
GPU  <mirror>/.incoming/<session>.partial        staging
        │  READY 있음? frames.csv 1개 이상?
        ▼
GPU  <mirror>/<session>/                         atomic mv
        │
        ▼  strict validation   ← 여기가 gate
        │
        ├─ BLOCKED            → CPU ACTION ITEMS 출력. GPU 에서 고치지 않음
        ├─ INTEGRATION ONLY   → 통합 테스트는 가능, 결과로 보고 불가
        └─ READY              → 학습 가능
        ▼
     30→10 Hz → T_camera_EE → rotvec → RGB preprocess → UMI Zarr
```

### 재-publish / reject 처리

| 상황 | GPU 동작 |
|---|---|
| 새 session | pull |
| 내용 동일 | `already synced, skipping` |
| **CPU 가 같은 UUID 로 재정제** | `STALE` 보고. **조용히 넘기지 않음**. `--resync` 로 교체 |
| **CPU 가 reject 해서 READY 가 사라짐** | `orphaned` 보고. `--prune-orphans` 로 치움 |

교체·정리는 전부 **삭제가 아니라 `.superseded/` 로 이동**이다.

### GPU 가 잡는 위반

| | |
|---|---|
| blank / 파싱 불가 pose 셀 | 항상 error (정책 무관) |
| blank timestamp | 즉시 error |
| position/quaternion non-finite | error |
| quaternion norm ≠ 1 | error |
| timestamp 비단조 | error |
| RGB 개수 ≠ 행 개수 | error |
| `rgb_path` 미해결 | error |
| `frame_idx` 불연속 | error |
| `pose_valid=false` 잔존 | error |
| 비정상 tracking **AND** `pose_interpolated=false` | error |
| 비정상 tracking **AND** `pose_interpolated=true` | **통과** |
| provenance 모순 | error |
| segment < 46 source frames | error |

---

## 6. Stage 구분

| | `T_camera_EE` | gripper | Training Status |
|---|---|---|---|
| **Stage A (현재)** | identity placeholder | placeholder / 없음 | `INTEGRATION ONLY` |
| **Stage B** | 실제 calibration | marker 기반 meter | `READY` |

placeholder 는 **hard failure 가 아니다.** 상태만 낮춘다.
Stage B 로 넘어갈 때 **raw 재수집은 필요 없다** — raw ARCore camera pose 가 보존돼
있으므로 같은 converter 를 다시 돌리면 된다.

```bash
# T_camera_EE 확보 후
$EDITOR configs/collector/default.yaml     # camera_to_ee.status: calibrated
python -m omx.cli build omx_pick_raw_center_v1 --overwrite
```

---

## 7. 작업 현황

### GPU 측

| | 항목 | 상태 |
|---|---|---|
| GPU-1 | `pose_interpolated` semantics 반영 | 완료 |
| GPU-2 | inspector / converter 동일 규칙 (공용 helper) | 완료 + 회귀 테스트 |
| GPU-3 | provenance 일관성 검증 | 완료 |
| GPU-4 | `rejected_*` / `failed_*` discovery 제외 | 완료 |
| GPU-5 | 기존 mirror 7개 전량 교체 경로 | 구현 완료, **CPU 대기** |
| GPU-6 | fresh sync 후 strict inspection | **CPU 대기** |
| GPU-7 | real-data dry-run | **CPU 대기** |
| GPU-8 | real zarr build | **CPU 대기** |
| GPU-9 | zarr inspection | **CPU 대기** |
| GPU-10 | real smoke training | **CPU 대기** |
| GPU-11 | CPU 반환용 validation report | 완료 |

GPU-2 회귀 테스트를 작성하는 과정에서 실제 불일치 3건을 발견해 수정했다.

* provenance 위반이 inspector 에서만 FAIL → `provenance_policy` 도입
* **짧은 segment 를 converter 가 조용히 버리고 있었음** → 위반으로 승격
* 최소 길이 계산이 서로 달랐음 (근사 48 vs 실제 46) → 계산식 공용화

```bash
python tests/test_omx_contract.py     # 9 checks
```

### CPU 측 (GPU 가 기다리는 것)

| | 필요한 것 | 없으면 |
|---|---|---|
| P0 | pose-validity 기반 trim / reject | GPU 가 `BLOCKED` |
| P0 | pose 전무한 episode reject | GPU 가 `BLOCKED` |
| P0 | usable segment 존재 후에만 `READY` | GPU 가 빈 session 을 가져감 |
| P0 | 기존 7 session 재-preprocess | GPU mirror 가 옛 데이터 |
| P1 | short gap interpolation + `pose_interpolated` | 해당 구간이 통째로 버려짐 |
| P1 | long gap split | 동일 |
| — | SSH public key 등록 | sync 불가 |
| — | `gripper_width_m` (marker 기반) | Stage B 진입 불가 |
| — | `T_camera_EE` calibration | Stage B 진입 불가 |

---

## 8. CPU 수정 완료 후 실행 순서

```bash
conda activate umi
cd ~/universal_manipulation_interface

# 1. 기존 mirror 교체 + reject 된 것 정리
./scripts/sync_processed_from_cpu.sh -n --force-resync    # 확인
./scripts/sync_processed_from_cpu.sh    --force-resync
./scripts/sync_processed_from_cpu.sh    --prune-orphans

# 2. strict inspection  ← 여기서 막히면 CPU 로 반환
python scripts/inspect_synced_processed.py -v

# 3~5. zarr
python -m omx.cli build   omx_pick_raw_center_v1 --dry-run
python -m omx.cli build   omx_pick_raw_center_v1 --overwrite
python -m omx.cli inspect omx_pick_raw_center_v1

# 6. smoke training (성능이 아니라 통과 여부만 본다)
python -m omx.cli train omx_pick_raw_center_v1 --profile smoke
```

기대값:

```
2.  Transfer OK / RGB/Pose Align OK / Training Status INTEGRATION ONLY
3.  contract violation 0
5.  action.shape == [16, 10], short episode silent drop 없음
```

`BLOCKED` 이 나오면 마지막의 `CPU ACTION ITEMS` 블록을 그대로 CPU 에 넘긴다.
**GPU 에서 고치지 않는다.**

---

## 9. 합의해야 할 한 줄

> 데이터가 깨져 있으면 GPU 는 그것을 **고치지 않고 멈춘다.**
> 멈췄다는 것은 CPU 가 고칠 것이 있다는 뜻이지, GPU 가 관대해져야 한다는 뜻이 아니다.
