# 계약: 수집 화면 상태 기계와 Tracking 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](../spec.md)

수집 작업 공간이 사용자에게 노출하는 상태 전이와 제어 가능 여부. UI 계약이므로 화면 구성 요소가 아니라 **관찰 가능한 동작**을 규정한다.

## 상태

| 상태 | 화면 표시 | 재생 | 일시 정지 | 정지 | 화면 이탈 |
|---|---|---|---|---|---|
| `Idle` | (배지 없음. 그 자리에 카메라 설정 톱니바퀴) | Session START | 비활성 | 비활성 | 즉시 이탈 |
| `Initializing` | `INITIALIZING` | **비활성** (사유 표시) | 비활성 | 확인 후 Session END | 확인 후 이탈 |
| `Ready` | `READY` | Episode START | 비활성 | 확인 후 Session END | 확인 후 이탈 |
| `EpisodeActive` | `EPISODE ACTIVE` | 비활성 | Episode END | 확인 후 거부·안내 | 확인 후 거부·안내 |
| `Finalizing` | (배지 없음. 마감 판이 화면을 덮는다) | 비활성 | 비활성 | 비활성 | 무시 |

`Idle`에서 재생은 task/object 입력이 완료되고 프리뷰가 준비된 경우에만 활성화된다(기존 동작 유지).

표의 `비활성`은 그 조작을 받지 않는다는 뜻이다. 화면에는 상태마다 쓰는 아이콘만 그린다. `Idle`은 재생 하나, `EpisodeActive`는 일시 정지와 정지, `Initializing`·`Ready`는 재생과 정지이며, `Finalizing`에는 제어가 없다.

정지와 화면 이탈(X·시스템 뒤로 가기)은 수집 중이면 같은 종료 확인을 거친다. `EpisodeActive`에서는 확인해도 Session을 마감하지 않고, 진행 중인 Episode를 먼저 종료하라고 안내한 뒤 작업 공간에 머문다. 확인을 먼저 받는 것은 [알려진 결함](../../../KNOWN_ISSUES.md)이다.

촬영 설정(녹화 해상도·초점·ISO·셔터·화이트 밸런스)은 `Idle`에서만 바꿀 수 있다. (2026-09-23) 설정 시트도 `Idle`에서만 열린다. 다른 상태에서는 톱니바퀴가 없고, 여는 요청이 와도 상태 전이가 무시한다. `Idle → Initializing` 전이에서 열린 시트를 접는다.

## 전이

### 사용자 조작

```text
Idle          ──재생──>  Initializing     Session 생성, Camera/IMU/ARCore 수집 시작
Idle          ──재생──>  Idle             카메라 timestamp 소스가 REALTIME이 아니면 시작 거부. 번들을 지우고 사유를 알린다
Ready         ──재생──>  EpisodeActive    Episode를 ACTIVE로 시작
EpisodeActive ──일시정지──> Ready          Episode를 COMPLETED로 마감
Initializing  ──정지(확인)──>  Finalizing   Session 마감
Ready         ──정지(확인)──>  Finalizing   Session 마감
EpisodeActive ──정지(확인)──>  (거부)       진행 중 Episode를 먼저 종료하도록 안내
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

Episode 중 짧은 유실(0.5초 미만)이 있었으면, 회복한 뒤 안정화 판정 시간(1초)을 다시 채우기 전까지 Tracking은 `READY`가 아니다. 그 사이 일시 정지하면 화면은 `Ready`를 거쳐 다음 평가(0.1초 뒤)에 `Initializing`으로 가고, 1초가 차면 `Ready`로 돌아온다. 그 짧은 `Ready` 동안 재생을 눌러도 Episode는 시작되지 않는다.

## 불변식

1. **Session 시작이 Episode를 시작시키지 않는다.** `Idle → Initializing` 전이는 Episode marker를 생성하지 않는다.
2. **`Ready`가 아닌 상태에서 Episode가 시작되지 않는다.** `Initializing`에서 재생은 비활성이며, 그 이유가 화면에 표시된다.
3. **Episode 종료가 Session을 종료시키지 않는다.** `EpisodeActive → Ready` 전이에서 Camera / IMU / ARCore 수집은 중단되지 않는다.
4. **`INVALID_TRACKING`이 Session을 종료시키지 않는다.** 자동 마감 후에도 수집은 계속되고, Tracking 회복 시 다음 Episode를 시작할 수 있다.
5. **Episode 반복에 횟수 제한이 없다.** `Ready ↔ EpisodeActive`를 임의 횟수 왕복할 수 있다.
6. **Episode 마감은 한 번만 일어난다.** `INVALID_TRACKING`으로 자동 마감된 Episode는 이후 사용자 조작으로 다시 마감되지 않는다.
7. **촬영 조건은 Session 안에서 변하지 않는다.** `Idle`을 벗어나면 설정 변경 의도는 상태 전이에서 무시된다. 화면에서 막는 것과 별개로 한 번 더 막는 이유는, 도중에 조건이 바뀌면 그 Session의 데이터를 한 조건으로 찍었다고 말할 수 없기 때문이다. 그 Session에 적용된 값은 `metadata.json`의 `capture_settings`에 남는다.

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

**첫 유실 pose를 걸어 둔다**: 유실 구간에서 매 프레임 최신 pose 시각을 실어 보내면, 화면 ticker의
평가 주기(0.1초) 사이에 진행한 pose 시각이 기록에 들어가 `end_timestamp_ns`가 늦어진다. 마지막
`TRACKING` 이후 첫 유실 pose 시각을 걸어 두고 회복할 때까지 그 값을 보낸다. 실기기에서 편차 0 ms를
확인했다.

**폴백**: (2026-09-23) 카메라 timestamp 소스가 `REALTIME`이 아니거나 알려지지 않은 기기에서는 Session을
시작하지 않는다. 카메라를 열기 전에 거부하므로 기록되는 pose 시각은 단조 시계와 같은 시간축이다.
그래도 걸어 둔 pose 시각이 진행 중 Episode의 시작보다 이르거나 현재보다 미래이면 버리고 인지 시각을
기록에 쓰는 방어는 남아 있다.

### Session 중 화면 프리뷰

Session이 진행되는 동안 화면 프리뷰는 **ARCore가 채우는 Camera 텍스처를 pose 수집 스레드가
프리뷰 Surface에 그려서** 채운다. 카메라 출력 stream은 ARCore의 것과 MediaRecorder surface뿐이며,
프리뷰 때문에 늘어나지 않는다. 대상 기기가 프리뷰를 포함한 4 stream 조합을 거부하기 때문이다.

프리뷰 버퍼 크기와 `setDisplayGeometry`, MediaRecorder 해상도를 모두 `cameraConfig.textureSize`로
잡는다. `metadata.json`의 Intrinsic도 같은 stream 기준인 `textureIntrinsics`에서 읽는다.
세 값이 같은 크기·비율이므로 프리뷰의 화각은 저장되는 영상과 같다. 화각이 갈리는 것은 비율이
다를 때이며, 종전에는 프리뷰가 16:9 텍스처, 녹화가 4:3 CPU 이미지 기준이라 어긋나 있었다.

ARCore가 추적에 쓰는 CPU 이미지(`cameraConfig.imageSize`)는 640×480으로 남는다. 화면에도
파일에도 나가지 않으며 추적 품질만 좌우한다. `imageSize`를 올리면 CPU 이미지 stream과 녹화
stream이 함께 커지면서 대상 기기가 stream 조합을 거부한다(`Error configuring streams`).
실기기에서 1280×720과 1920×1080 모두, textureSize를 낮춰도 실패했다.

### 녹화 해상도 선택

`textureSize`는 Session마다 다를 수 있다. 수집자가 Session 전에 카메라 설정에서 `1920×1080` 또는
`1280×720`을 고르면, `INITIALIZING`으로 들어가기 전에 그 `textureSize`와 `imageSize` 640×480을
함께 가진 ARCore Camera config를 골라 `setCameraConfig()`로 지정한다. 위 문단대로 `imageSize`는
항상 640×480으로 남긴다.

고른 해상도를 가진 후보가 없으면 기본 config로 수집을 이어가고 선택 결과만 로그에 남긴다.
해상도 하나 때문에 Session 시작을 막지 않는다. 두 해상도 모두 16:9라 프리뷰 레이아웃은 같다.

**세 경로가 한 값을 쓴다**: 수집 전 유휴 프리뷰, 수집 중 프리뷰, 녹화가 모두 같은 해상도 하나를
따른다. 수집 전에는 사용자가 고른 값이고, 수집을 시작하면 ARCore가 실제로 고른 `textureSize`로
갱신된다. 위 폴백으로 기본 config에 머문 Session에서도 프리뷰와 저장본이 어긋나지 않는다.

유휴 프리뷰는 Camera2 경로라 stream 크기가 capture session을 만들 때 정해진다. 카메라 설정에서
고른 해상도가 직전과 다르면 `SurfaceTexture` 버퍼를 바꾼 뒤 session을 다시 연다.
버퍼만 바꾸면 이미 열린 session에는 반영되지 않는다.

이 선택은 상태와 전이를 바꾸지 않는다. `metadata.json`의 `image_width`·`image_height`가 고른
해상도를 따라가며, Intrinsic도 같은 stream 기준인 `textureIntrinsics`에서 읽으므로 함께 따라간다.

이 구성은 상태와 전이를 바꾸지 않는다. 프리뷰 Surface를 얻지 못한 Session(`null`)도 정상 Session이며,
그리기 실패는 기록되되 pose 수집을 멈추지 않는다. 프레임 타임스탬프는 `SENSOR_TIMESTAMP` 기준
중복 제거로 기록되므로 프리뷰 표시 여부와 무관하다.
