# 계약: 수집 화면 상태 기계와 Tracking 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](../spec.md)

수집 작업 공간이 사용자에게 노출하는 상태 전이와 제어 가능 여부. UI 계약이므로 화면 구성 요소가 아니라 **관찰 가능한 동작**을 규정한다.

## 상태

| 상태 | 화면 표시 | 재생 | 일시 정지 | 정지 | 화면 이탈 |
|---|---|---|---|---|---|
| `Idle` | `IDLE` | Session START | 비활성 | 비활성 | 즉시 이탈 |
| `Initializing` | `INITIALIZING` | **비활성** (사유 표시) | 비활성 | Session END | 확인 후 이탈 |
| `Ready` | `READY` | Episode START | 비활성 | Session END | 확인 후 이탈 |
| `EpisodeActive` | `EPISODE ACTIVE` | 비활성 | Episode END | 활성이지만 거부 후 안내 | 확인 후 이탈 |
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

`EpisodeActive`에서 정지 버튼은 비활성이 아니라 **활성 상태로 두고 누르면 안내를 표시한다.** 버튼을 비활성화하면
사용자가 왜 종료할 수 없는지 알 수 없기 때문이다. 실제 Session 마감은 일어나지 않는다.

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

### 유실 시작 시각의 기준

`INVALID_TRACKING`의 `end_timestamp_ns`를 계산하는 **유실 시작 시각은 `arcore_poses.csv`에서
`tracking_state`가 처음 `TRACKING`이 아닌 값으로 바뀐 행의 `android_camera_timestamp_ns`다.**
수신 측이 pose 기록만으로 경계를 재계산할 수 있어야 하기 때문이다.

이 값은 시스템이 유실을 **알아챈** 시각과 다르다. ARCore가 프레임을 처리해 내보내기까지의 지연과
평가 주기(0.1초) 때문에 인지 시각이 더 늦다. 실기기에서 측정된 차이는 217 ms였다.

따라서 두 시각을 분리해 쓴다.

| 용도 | 기준 | 이유 |
|---|---|---|
| 0.5초 경과 판정 | 단조 시계 | pose 지연이 섞이면 실제보다 짧은 유실에도 마감된다 |
| `end_timestamp_ns` 기록 | pose 카메라 시각 | `arcore_poses.csv`와 정확히 대응시킨다 |

판정에 pose 시각을 쓰면 지연만큼 게이트가 앞당겨져, 0.5초 미만 유실도 무효로 마감된다.
이는 "짧은 유실은 Recording 계속"이라는 요구와 어긋난다.

**폴백**: 카메라 timestamp 소스가 `REALTIME`이 아닌 기기에서는 pose 시각이 단조 시계와 다른
시간축이다. 그 값이 진행 중 Episode의 시작보다 이르거나 현재보다 미래이면 다른 시간축으로 보고
버리며, 이때는 인지 시각을 기록에 사용한다. 그 Session의 `end_timestamp_ns`는 최대
평가 주기 + pose 지연만큼 늦어지지만, 시간축이 뒤섞인 값이 기록되지는 않는다.

### Session 중 화면 프리뷰

Session이 진행되는 동안 화면 프리뷰는 **ARCore가 채우는 Camera 텍스처를 pose 수집 스레드가
프리뷰 Surface에 그려서** 채운다. 카메라 출력 stream은 ARCore의 것과 MediaRecorder surface뿐이며,
프리뷰 때문에 늘어나지 않는다. 대상 기기가 프리뷰를 포함한 4 stream 조합을 거부하기 때문이다.

프리뷰의 화각은 저장되는 영상과 같다. 프리뷰 버퍼 크기와 `setDisplayGeometry`를 모두
`cameraConfig.imageSize`로 잡기 때문이다.

이 구성은 상태와 전이를 바꾸지 않는다. 프리뷰 Surface를 얻지 못한 Session(`null`)도 정상 Session이며,
그리기 실패는 기록되되 pose 수집을 멈추지 않는다. 프레임 타임스탬프는 `SENSOR_TIMESTAMP` 기준
중복 제거로 기록되므로 프리뷰 표시 여부와 무관하다.
