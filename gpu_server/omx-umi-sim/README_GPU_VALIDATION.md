# GPU 검증 게이트

CPU processed_v1 이 GPU 로 넘어온 뒤의 검증 계층.
GPU 는 **복구자가 아니라 마지막 gate** 다.

관련 문서: **[`README_HANDOFF_CONTRACT.md`](README_HANDOFF_CONTRACT.md)** (책임 분리 · 스키마) ·
[`README_CPU_GPU_SYNC.md`](README_CPU_GPU_SYNC.md) (전송 계층) ·
[`README_GPU_WORKFLOW.md`](README_GPU_WORKFLOW.md) (학습 파이프라인 전체) ·
[`REPORT_STAGE_A_INTEGRATION.md`](REPORT_STAGE_A_INTEGRATION.md) (실데이터 실행 결과)

---

## 1. 원칙

```
CPU   pose validity → start/end trim → short gap interpolation
      → long gap split → invalid/short segment reject → quality metadata → READY

GPU   strict sanity check → 통과하면 변환, 아니면 FAIL
```

CPU 가 고친 것은 **받아들여야 한다.** 이게 GPU-1 의 핵심이다.

```
tracking_state = PAUSED     +  pose_interpolated = false   ->  FAIL
tracking_state = PAUSED     +  pose_interpolated = true    ->  PASS
                               (+ pose 가 수치적으로 유효할 때)
```

보간된 row 는 **원본 `tracking_state` 를 그대로 유지**한다 (provenance 보존).
따라서 `tracking_state` 만 보고 판단하면 CPU 가 방금 고친 row 를 정확히 골라
거부하게 된다.

GPU 에서 다음을 **하지 않는다.**

```
long gap interpolation      episode splitting        tracking recovery
blank 값 채우기              invalid frame 조용히 버리기
```

이유는 두 가지다.

1. **중복 구현.** 같은 정제 로직이 두 곳에 있으면 한쪽만 고쳤을 때 dataset 이
   조용히 갈라진다. 어느 쪽 규칙으로 만들어진 zarr 인지 나중에 알 수 없다.
2. **은폐.** GPU 가 고쳐버리면 CPU output 이 깨졌다는 사실 자체가 드러나지 않는다.
   깨진 채로 학습이 돌고, 결과가 나쁠 때 원인을 데이터가 아니라 모델에서 찾게 된다.

---

## 2. 고친 버그

`frames.csv` 의 pose 셀이 비어 있으면 (`camera_tx=""`) 두 도구가
**처리되지 않은 예외로 죽었다.** CPU tracking dropout 이 실제로 남기는 형태다.

```
scripts/inspect_synced_processed.py:138   ValueError: could not convert string to float: ''
omx/data/processed_v1.py:147              ValueError: could not convert string to float: ''
```

두 곳 모두 컬럼 **존재 여부만** 확인한 뒤 모든 row 를 바로 `float()` 에 넣고 있었다.

```python
# before
pos = np.array([[float(r[col[k]]) for k in ("tx","ty","tz")] for r in rows])
```

inspector 뿐 아니라 **converter 의 reader 도 같은 버그**였다. 재현해서 확인했다.

---

## 3. 한 곳에만 구현한다 (GPU-2)

inspector 와 converter 가 **같은 reader 와 같은 validity 함수**를 쓴다.
판정 로직이 두 벌 있으면 한쪽만 고쳤을 때 `inspect PASS → build FAIL` 이 난다.

```
ProcessedV1Reader.read_lowdim()          <- 파싱 한 곳
        │
        ▼
compute_effective_pose_validity()        <- 판정 한 곳
        │
   ┌────┴────┐
   ▼         ▼
inspector  converter
```

`tests/test_omx_contract.py::test_inspector_and_converter_agree` 가 케이스마다
두 도구의 판정이 같은지 확인한다. 개발 중 이 테스트가 실제로 불일치 두 건을
잡아냈다.

* provenance 위반이 inspector 에서만 FAIL 이었다 → `provenance_policy` 를 두어 양쪽이 같은 값을 읽게 함
* 짧은 segment 를 converter 가 **조용히 버리고** 있었다 → `invalid_policy=error` 에서 위반으로 승격
* 최소 길이 계산이 서로 달랐다 (근사치 48 vs 실제 46) → `stored_frames_for()` / `min_source_frames()` 공용화

```bash
python tests/test_omx_contract.py     # 9 checks
```

---

## 4. 파싱 규칙 — blank 는 NaN, 절대 0 이 아니다

```python
# omx/data/processed_v1.py
def _parse_float_column(rows, key) -> (values, indices_of_unparseable_cells)
```

| 입력 | 결과 |
|---|---|
| `"0.123"` | `0.123` |
| `""`, `none`, `null`, `na`, `n/a`, `-` | `NaN` + 해당 row index 기록 |
| 그 외 파싱 실패 | `NaN` + 해당 row index 기록 |

**왜 0 으로 채우면 안 되는가.**
`camera_tx=""` 를 `0.0` 으로 읽으면 end effector 가 world origin 으로 순간이동한
궤적이 만들어진다. 그게 그대로 학습 데이터가 되고, 값이 finite 하므로 어떤
검사에도 걸리지 않는다. 숫자 기본값을 넣는 경로는 코드에 존재하지 않는다.

NaN 은 validity mask 를 타고 내려가 build 를 멈춘다.

### timestamp 만 예외

pose 는 마스킹 정책의 대상이 될 수 있지만, **timestamp 가 비면 즉시 raise** 한다.
timestamp 없는 frame 은 timeline 에 올릴 방법 자체가 없어서 어떤 정책으로도
복구되지 않는다.

```
[<session>__<episode>] frames.csv column 'timestamp_ns' has blank or unparseable
values: 3/210 rows, at index 40, 41, 42.
  This is a CPU processed_v1 contract violation. The GPU side does not repair it
  -- fix the CPU output and re-sync.
```

---

## 5. Effective validity — 판정 규칙

`omx/data/validity.py` 한 곳에만 있다.

```python
numeric_pose_valid = (position finite
                      and quaternion finite
                      and |quaternion| - 1 <= 1e-2)

tracking_ok        = (tracking_state in usable_tracking_states
                      or pose_interpolated is True)

effective_valid    = pose_valid and numeric_pose_valid and tracking_ok
```

| tracking_state | pose_valid | pose_interpolated | pose | 결과 |
|---|---|---|---|---|
| TRACKING | true | false | 유효 | PASS |
| TRACKING | **false** | false | 유효 | FAIL |
| **PAUSED** | true | **false** | 유효 | FAIL |
| **PAUSED** | true | **true** | 유효 | **PASS** |
| TRACKING | true | false | **NaN/blank** | FAIL |
| PAUSED | true | true | **NaN** | FAIL |

컬럼이 아예 없으면 해당 조건은 통과로 본다. 단 **수치 유효성은 예외가 없다** —
blank 셀이 만든 NaN 은 어떤 경우에도 FAIL 이다.

### provenance 일관성 (GPU-3)

`pose_interpolated` / `pose_valid_original` 이 서로 모순되면 수치가 멀쩡해도
dataset 을 추적할 수 없게 된다. `validity.provenance_policy` (기본 `error`).

기대하는 조합:

```
직접 ARCore 측정   pose_valid_original=true,  pose_interpolated=false
CPU 보간           pose_valid_original=false, pose_interpolated=true,
                   pose_valid=true, tracking_state 는 원본 유지
```

잡아내는 모순:

| 조합 | 문제 |
|---|---|
| `pose_interpolated=true` + `pose_valid_original=true` | 이미 유효한 측정값을 왜 보간했는가 |
| `pose_interpolated=true` + `pose_valid=false` | 보간해놓고 무효 표시. 버렸어야 함 |
| `pose_valid=true` + `original=false` + `interpolated=false` | 유효성이 어디서 나왔는가 |
| `pose_interpolated=true` + `tracking_state=TRACKING` | 원본 상태를 덮어써서 repair 흔적이 사라짐 |

---

## 6. `invalid_policy` 기본값이 `error`

`configs/collector/default.yaml`

```yaml
validity:
  invalid_policy: error
```

| 값 | 동작 | 용도 |
|---|---|---|
| `error` | 유효하지 않은 frame 이 하나라도 있으면 build 거부 | **contract. 기본값** |
| `trim` | 가장 긴 유효 구간만 남김 | 알려진 불량 export 조사용 |
| `split` | 내부 불량 구간에서 잘라 나눔 | 알려진 불량 export 조사용 |
| `keep` | 그대로 통과 (값은 NaN 으로 남고 0 이 되지 않음) | 디버깅용 |

`trim` / `split` / `keep` 으로 **학습 dataset 을 만들면 안 된다.** config 주석에도
명시돼 있다. 이전 기본값이 `split` 이었는데, 그건 GPU 가 CPU 의 일을 대신 하는
것이라 `error` 로 바꿨다.

---

## 7. 검사 항목

`scripts/inspect_synced_processed.py`

| 검사 | strict (기본) | `--no-strict` |
|---|---|---|
| pose column 존재 | error | error |
| **pose 값 전부 parse 가능** | error | **error** |
| position / quaternion finite | error | error |
| quaternion norm ≈ 1 (tol 1e-2) | error | error |
| timestamp parse 가능 | error | error |
| timestamp 단조 증가 | error | error |
| RGB 이미지 개수 == `frames.csv` row 개수 | error | error |
| `rgb_path` 전부 resolve (**전체 row**) | error | error |
| `frame_idx` 연속성 | error | error |
| `pose_valid=false` 잔존 | error | 경고 |
| `tracking_state` 비정상 **AND** `pose_interpolated=false` | error | 경고 |
| `tracking_state` 비정상 **AND** `pose_interpolated=true` | **통과** | 통과 |
| provenance 모순 (GPU-3) | error | 경고 |
| episode 길이 부족 | error | 경고 |
| 측정 fps vs `timing.source_fps` (1 Hz 초과 차이) | 경고 | 경고 |
| frame interval jitter (max/min > 3) | 경고 | 경고 |
| `quality.json` 존재 / gripper 컬럼 | 집계 | 집계 |

`--no-strict` 는 **triage 전용**이고 세 항목만 낮춘다.

* **blank pose cell 은 어느 모드에서도 error** — 정책 선택이 아니라 복구 불가능한 결손
* CPU 가 보간한 row (`pose_interpolated=true`) 는 **정상 데이터로 취급**한다. 실패가 아니다
* `--no-strict` 는 이 리포트만 바꾼다. **converter 는 여전히 build 를 거부한다**

`rgb_path` 는 이전에 첫 2000 row 만 확인했는데 전체 row 로 바꿨다.

### episode 길이 기준

```
converter  : (action_horizon - 1) x obs_down_sample_steps + 1  = 16 stored frames
inspector  : 16 x converter_stride                             = 48 source frames  (30 Hz 기준)
```

이보다 짧은 segment 는 `SequenceSampler(action_padding=False)` 에서 샘플을 하나도
만들지 못하고 **경고 없이 통째로 사라진다.** CPU 의 reject 단계가 걸렀어야 하는
것이므로 strict 에서는 error 다.

---

## 8. 실패 출력

### converter

모든 episode 를 검사한 뒤 **한 번에** 보고한다. 첫 episode 에서 죽으면 CPU 담당자가
고칠 때마다 왕복하게 된다.

```
==============================================================================
CPU processed_v1 CONTRACT VIOLATION in 2 of 4 episode(s)
==============================================================================

[<session>__<episode>] 15/210 frames fail validation and validity.invalid_policy='error'.
  causes: non_finite_pose=15
          blank/unparseable cells in camera_tx (15/210 rows, at index 40, 41, 42,
          43, 44, 45 ... (+9 more)), camera_ty (...), camera_qw (...)
          quaternion_norm=15
          pose_valid_false=15
          tracking_state_bad=15
  This is a CPU processed_v1 contract violation: the CPU side is responsible for
  trimming, interpolating short gaps, splitting long gaps and rejecting unusable
  segments before writing READY.
  The GPU side is the final gate, not a repair step -- fix the CPU output and
  re-sync rather than relaxing this setting.
  (validity.invalid_policy=trim|split exists for debugging a known-bad export;
  it must not be used to produce a training dataset.)

Error: 2 episode(s) violate the processed_v1 contract. Nothing was written.
```

**어느 컬럼의 몇 번째 row 인지까지** 찍는다 (앞 6개 + 나머지 개수).
exit code 1, zarr 은 생성되지 않는다.

### inspector

```
  FAIL <sess>../<ep>..: blank/unparseable pose cells -- CPU processed contract
       violation: camera_tx (15/210 rows, at index 40, 41, 42, 43, 44, 45 ...)
  FAIL <sess>../<ep>..: 15/210 rows have pose_valid=false. CPU preprocessing
       should have trimmed, interpolated or split these out before writing READY
  FAIL <sess>../<ep>..: 15/210 rows have a non-tracking tracking_state

==============================================================================
DATASET STATUS
--------------
Transfer         : OK
RGB/Pose Align   : FAIL
T_camera_EE      : PLACEHOLDER
Gripper Width    : PRESENT (calibration not marked final)
Training Status  : BLOCKED
==============================================================================

The CPU processed_v1 contract is violated. The GPU side is the final gate, not
a repair step:
  - blank pose cells are never filled in with 0
  - invalid frames are never silently dropped
  Fix CPU preprocessing (trim / interpolate short gaps / split long gaps /
  reject unusable segments, then write READY) and re-sync.
  `--no-strict` only changes this report; the converter still refuses the build.
```

`BLOCKED` 일 때는 `next: build ...` 안내를 출력하지 않는다.

---

## 9. `Training Status` 3 단계

| | 의미 | 조치 |
|---|---|---|
| `BLOCKED` | 정합 자체가 깨짐 | CPU 수정 후 재-preprocess → 재-sync |
| `INTEGRATION ONLY` | 파이프라인은 정상, calibration/gripper 가 placeholder | 통합 테스트는 진행 가능. 결과로 보고하면 안 됨 |
| `READY` | `T_camera_EE` 가 실제 calibration + gripper 가 marker 기반 meter | baseline 학습 가능 |

placeholder 와 gripper 누락은 **hard failure 가 아니다.** 상태만 낮춘다.
현재 Stage A 에서는 `INTEGRATION ONLY` 가 정상 상태다.

---

## 10. 재현

```bash
# 세션당 첫 episode 의 row 40..54 에 blank pose 를 심은 good/bad 혼합 트리
python scripts/make_synthetic_processed_v1.py \
    -o data/omx/_violation -n 4 --sessions 2 --duration 5 --blank-pose-rows 40:55

python scripts/inspect_synced_processed.py --root data/omx/_violation      # exit 1
python scripts/convert_processed_to_umi_zarr.py -i data/omx/_violation \
    -o /dev/null --dry-run                                                 # exit 1
```

`--blank-pose-rows START:END` 는 해당 row 에 `pose_valid=0`,
`tracking_state=PAUSED`, 그리고 7개 pose 컬럼을 **빈 문자열**로 쓴다
(0 이 아니라 blank — 실제 실패 형태).

---

## 11. 변경된 파일

| 파일 | 변경 |
|---|---|
| `omx/data/validity.py` | **신규.** `compute_effective_pose_validity()` / `check_pose_provenance()` — inspector 와 converter 의 유일한 판정 지점 |
| `tests/test_omx_contract.py` | **신규.** GPU-1/2/3/4 회귀 테스트 9종 |
| `omx/data/processed_v1.py` | `_parse_float_column()` / `_summarise_bad()`, `pose_interpolated` / `pose_valid_original` 컬럼, `rejected_episode_*` · `failed_episode_*` discovery 제외 |
| `omx/data/build.py` | `compute_valid_mask()` 가 공용 모듈로 위임, provenance 위반과 짧은 segment 를 위반으로 승격, `stored_frames_for()` / `min_source_frames()` |
| `omx/collector_config.py` | `ValidityConfig.invalid_policy` 기본값 `split` → `error` |
| `configs/collector/default.yaml` | 동일 + 각 모드의 용도 주석 |
| `scripts/convert_processed_to_umi_zarr.py` | `ContractError` 수집 후 일괄 보고, 깨끗한 CLI 실패 |
| `scripts/inspect_synced_processed.py` | `ProcessedV1Reader` + 공용 validity 로 재작성, strict gate, `--strict/--no-strict`, CPU ACTION ITEMS 리포트 |
| `scripts/make_synthetic_processed_v1.py` | `--blank-pose-rows`, `--interpolate-rows`, provenance 컬럼 생성 |
| `scripts/sync_processed_from_cpu.sh` | stale 감지, `--resync` / `--force-resync` / `--prune-orphans` |
| `omx/collector_config.py`, `configs/collector/default.yaml` | `provenance_policy` |

---

## 12. 검증 결과

| 케이스 | 결과 |
|---|---|
| 정상 fixture (10 ep) → build | 성공, 700 frames @ 10 Hz |
| 정상 fixture → inspect | `ALL CHECKS PASSED`, `action == [16,10]`, exit 0 |
| 정상 fixture → synced inspect | `INTEGRATION ONLY`, exit 0 |
| 위반 fixture → synced inspect (strict) | `BLOCKED`, 컬럼/row 명시, exit 1 |
| 위반 fixture → synced inspect (`--no-strict`) | blank 는 여전히 FAIL, 나머지 2개는 warn, exit 1 |
| 위반 fixture → converter | `CONTRACT VIOLATION in 2 of 4`, 아무것도 쓰지 않음, exit 1 |

---

## 13. CPU 담당자에게 의미하는 것

GPU inspector 가 `BLOCKED` 을 내면 **GPU 쪽에 고칠 것은 없다.**
출력에 어느 session / episode / 컬럼 / row 인지 다 들어 있으므로 그대로 CPU
preprocessing 을 고치고 재-preprocess → 재-sync 하면 된다.

특히 최종 output 에 다음이 남아 있으면 안 된다.

```
pose_valid = false          ← trim / interpolation / split 로 처리됐어야 함
camera_* 컬럼이 blank       ← 위와 동일. 값을 못 구했으면 그 frame 은 남기지 않는다
action_horizon 을 못 채우는 짧은 segment   ← reject 됐어야 함
```

`READY` 는 **usable segment 가 남아 있을 때만** 쓴다. pose 가 하나도 없는 episode 는
CPU 에서 reject 한다.
