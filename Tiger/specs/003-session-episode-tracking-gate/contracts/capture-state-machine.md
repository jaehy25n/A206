# 계약: 수집 화면 상태 기계와 Tracking 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](../spec.md)

수집 작업 공간이 사용자에게 노출하는 상태 전이와 제어 가능 여부. UI 계약이므로 화면 구성 요소가 아니라 **관찰 가능한 동작**을 규정한다.

## 상태

| 상태 | 화면 표시 | 재생 | 일시 정지 | 정지 | 화면 이탈 |
|---|---|---|---|---|---|
| `Idle` | `IDLE` | Session START | 비활성 | 비활성 | 즉시 이탈 |
| `Initializing` | `INITIALIZING` | **비활성** (사유 표시) | 비활성 | Session END | 확인 후 이탈 |
| `Ready` | `READY` | Episode START | 비활성 | Session END | 확인 후 이탈 |
| `EpisodeActive` | `EPISODE ACTIVE` | 비활성 | Episode END | 확인 후 Session END | 확인 후 이탈 |
| `Finalizing` | `FINALIZING` | 비활성 | 비활성 | 비활성 | 무시 |

`Idle`에서 재생은 task/object 입력이 완료되고 프리뷰가 준비된 경우에만 활성화된다(기존 동작 유지).

## 전이

### 사용자 조작

```text
Idle          ──재생──>  Initializing     Session 생성, Camera/IMU/ARCore 수집 시작
Ready         ──재생──>  EpisodeActive    Episode를 ACTIVE로 시작
EpisodeActive ──일시정지──> Ready          Episode를 COMPLETED로 마감
Initializing  ──정지──>  Finalizing       Session 마감
Ready         ──정지──>  Finalizing       Session 마감
EpisodeActive ──정지──>  (거부)           진행 중 Episode를 먼저 종료하도록 안내
Finalizing    ──완료──>  Idle
```

### Tracking 신호

```text
Initializing  ──TRACKING 1.0초 연속 유지──>  Ready
Ready         ──TRACKING 유실──>             Initializing
EpisodeActive ──유실 0.5초 미만 후 회복──>    EpisodeActive  (변화 없음, 기록 계속)
EpisodeActive ──유실 0.5초 이상 지속──>       Initializing   (Episode를 INVALID_TRACKING으로 마감)
```

## 불변식

1. **Session 시작이 Episode를 시작시키지 않는다.** `Idle → Initializing` 전이는 Episode marker를 생성하지 않는다.
2. **`Ready`가 아닌 상태에서 Episode가 시작되지 않는다.** `Initializing`에서 재생은 비활성이며, 그 이유가 화면에 표시된다.
3. **Episode 종료가 Session을 종료시키지 않는다.** `EpisodeActive → Ready` 전이에서 Camera / IMU / ARCore 수집은 중단되지 않는다.
4. **`INVALID_TRACKING`이 Session을 종료시키지 않는다.** 자동 마감 후에도 수집은 계속되고, Tracking 회복 시 다음 Episode를 시작할 수 있다.
5. **Episode 반복에 횟수 제한이 없다.** `Ready ↔ EpisodeActive`를 임의 횟수 왕복할 수 있다.
6. **Episode 마감은 한 번만 일어난다.** `INVALID_TRACKING`으로 자동 마감된 Episode는 이후 사용자 조작으로 다시 마감되지 않는다.

## 임계값

| 이름 | 값 | 용도 |
|---|---|---|
| 안정화 판정 시간 | 1.0초 | `Initializing → Ready` |
| 유효성 판정 시간 | 0.5초 | `EpisodeActive → INVALID_TRACKING` |
| Tracking 평가 주기 | 0.1초 | 위 두 판정의 발화 주기 |

앞의 두 값은 기존 `CaptureSessionCoordinator`의 `READY_GATE_NS`, `TRACKING_LOSS_NS` 상수와 동일하다. 평가 주기는 두 임계값보다 충분히 촘촘해야 한다는 것이 요구이며, 0.1초는 판정 오차를 임계값의 20% 이내로 유지한다.

## 기록되는 결과

| 상황 | `episodes.csv`의 `outcome` | `end_timestamp_ns` |
|---|---|---|
| 사용자가 일시 정지로 종료 | `COMPLETED` | 조작 시각 |
| Tracking 유실 0.5초 지속 | `INVALID_TRACKING` | 유실 시작 시각 + 0.5초 |

두 경로 모두 동일한 형식으로 `episodes.csv`와 로컬 색인에 기록된다.
