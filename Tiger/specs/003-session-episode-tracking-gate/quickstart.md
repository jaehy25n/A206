# 검증 가이드: Session/Episode 분리와 Tracking 유효성 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](spec.md) | **계획**: [plan.md](plan.md)

구현이 끝난 뒤 이 기능이 실제로 동작하는지 확인하는 절차. 자동 검증과 실기기 검증을 나누어 기술한다. 계약 세부는 [contracts/](contracts/)를, 필드 정의는 [data-model.md](data-model.md)를 참조한다.

## 사전 조건

- 저장소 루트에서 Gradle Wrapper를 실행한다.
- 실기기 검증에는 ARCore(Google Play Services for AR)가 설치된 Android API 28 이상 기기가 필요하다. 기준 기기는 Galaxy S10 계열이다.
- 새 clone 또는 worktree라면 `.\gradlew.bat installGitHooks`를 한 번 실행한다.

## 자동 검증

```bash
./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug
```

Compose 제어 상태 검증은 연결된 기기 또는 에뮬레이터가 있을 때만 실행한다.

```bash
./gradlew.bat connectedDebugAndroidTest
```

### 자동 검증이 덮는 범위

| 대상 | 확인 내용 | 대응 요구사항 |
|---|---|---|
| 상태 기계 | 가상 시계로 1초 안정화 후 `Ready` 전이, 0.5초 미만 유실 시 Episode 유지, 0.5초 이상 유실 시 `INVALID_TRACKING` 마감, 마감 시각이 유실 시작 + 0.5초 | FR-008, FR-010~FR-012 |
| 상태 기계 | `Ready`가 아닌 상태에서 Episode 시작 거부 | FR-009 |
| 상태 기계 | 자동 마감된 Episode를 사용자 조작으로 다시 마감하지 않음 | 불변식 6 |
| 제어 정책 | 다섯 상태별 재생·일시 정지·정지 활성화 여부 | FR-003, FR-006, FR-009 |
| frame index | 0부터 1씩 증가, 결번 없음. 중복 콜백 입력 시에도 프레임당 1회만 증가 | FR-017 |
| frame index | 녹화 구간 플래그가 꺼진 동안 행이 기록되지 않음 | FR-020 |
| 메타데이터 | `camera` 객체 직렬화, 선택 필드 미확보 시 키 생략 | FR-021, FR-023, FR-024 |
| 메타데이터 | 메타데이터 획득 실패를 주입해도 Session 마감이 완료됨 | FR-025 |
| 메타데이터 | 기존 세 키가 보존되어 `SessionBundleValidator`가 통과 | FR-026 |

**중요**: 상태 기계 테스트는 가상 시계를 쓰되, ticker가 실제로 `onTracking()`을 반복 호출하는 경로까지 포함해야 한다. 값 변화에만 반응하는 구현은 단위 테스트에서 통과하면서 실기기에서 0.5초 마감이 영영 발화하지 않을 수 있다([research.md](research.md) 결정 1).

## 실기기 검증

자동화할 수 없는 항목이며, 이 절이 끝나지 않은 상태로 기능을 완료로 보고하지 않는다.

### 시나리오 1 — Session과 Episode 분리 (US1)

1. 수집 화면에 진입해 task와 object를 입력한다.
2. 재생을 눌러 Session을 시작한다.
   - **기대**: 화면이 `INITIALIZING`을 표시한다. Episode가 시작되지 않는다.
3. 기기를 천천히 움직여 ARCore Tracking을 안정화시킨다.
   - **기대**: 화면이 `READY`로 바뀌고 재생이 활성화된다.
4. 재생을 눌러 Episode를 시작하고, 잠시 뒤 일시 정지로 종료한다.
   - **기대**: 화면이 `READY`로 돌아가고 프리뷰가 끊기지 않는다.
5. 3번 더 반복해 총 4개의 Episode를 수집한다.
6. 정지를 눌러 Session을 종료한다.

**확인**: 번들의 `episodes.csv`에 Episode 4개가 있고, 모든 `start_timestamp_ns`가 Session 시작 시각보다 크다. `accelerometer.csv`, `gyroscope.csv`, `arcore_poses.csv`의 시각 범위가 Session 전체를 연속으로 덮으며 Episode 사이에 공백이 없다. (SC-001, SC-004)

### 시나리오 2 — Tracking 게이트 (US2)

1. 렌즈를 가린 채 재생을 눌러 Session을 시작한다.
   - **기대**: 화면이 `INITIALIZING`에 머무르고 재생이 비활성이며 사유가 표시된다. 재생을 눌러도 Episode가 시작되지 않는다. (SC-003)
2. 가림을 풀어 `READY`가 되면 Episode를 시작한다.
3. 렌즈를 **0.3초 정도만** 가렸다 뗀다.
   - **기대**: Episode가 계속 진행되고 화면이 `EPISODE ACTIVE`를 유지한다.
4. 렌즈를 **2초 이상** 가린다.
   - **기대**: Episode가 자동 마감되고 화면이 `INITIALIZING`으로 바뀐다. 프리뷰와 수집은 계속된다.
5. 가림을 풀어 `READY`가 되면 Episode를 하나 더 수집하고 정상 종료한다.
6. 정지를 눌러 Session을 종료한다.

**확인**: `episodes.csv`에서 4번에서 마감된 Episode의 `outcome`이 `INVALID_TRACKING`이고, 5번 Episode는 `COMPLETED`다. `INVALID_TRACKING` Episode의 `end_timestamp_ns`가 `arcore_poses.csv`에서 `tracking_state`가 `TRACKING`이 아닌 값으로 바뀐 시각보다 약 0.5초 뒤다. Session 전체 데이터가 손실되지 않았다. (SC-002, SC-004)

### 시나리오 3 — frame index와 영상 대응 (US3, US5)

시나리오 1의 번들을 사용한다.

**확인**:

- `main_frame_timestamps.csv`의 헤더가 `frame_number,timestamp_ns,timestamp_source`로 유지된다. (FR-019)
- 첫 데이터 행의 `frame_number`가 `0`이고, 이후 행마다 1씩 증가하며 결번이 없다. (SC-005)
- `timestamp_ns`가 단조 증가하고 중복이 없다.
- 데이터 행 수와 `main_rgb.mp4`의 총 frame 수 차이가 2 이하다. (SC-009)

차이가 2를 넘으면 영상 중간의 지속적 frame drop 여부를 먼저 확인한다. 시작·종료 경계에만 몰려 있다면 수신 측의 서버 전처리 범위이며, 중간 구간에 흩어져 있다면 별도 조사가 필요하다.

### 시나리오 4 — Camera Metadata (US4)

시나리오 1의 번들을 사용한다.

**확인**:

- `metadata.json`에 `camera` 객체가 있고 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 모두 존재한다. (SC-006)
- `image_width` × `image_height`가 `main_rgb.mp4`의 실제 해상도와 일치한다. (SC-007)
- `cx`와 `cy`가 각각 `image_width`, `image_height`의 대략 절반 부근이다. 크게 벗어나면 잘못된 스트림의 intrinsics를 읽고 있을 가능성이 있다.
- `session_id`, `camera_streams`, `files` 세 키가 기존 형식 그대로다. (FR-026)
- 기기가 제공하지 않는 선택 필드는 키가 생략되어 있고, 0이나 임의 값으로 채워져 있지 않다. (FR-024)

### 시나리오 5 — 업로드 호환 (SC-008)

시나리오 1의 Session을 기존 경로로 EC2에 업로드한다.

**확인**: 수신 측 수정 없이 업로드가 성공하고, Session UUID 단위로 저장된다.

## 회귀 확인

이번 변경이 건드리지 않아야 하는 범위다.

- ARCore `SharedCamera` 기반 Main RGB 녹화가 정상 동작한다. 영상이 재생되고 길이가 수집 시간과 맞는다.
- Session 목록, Session 상세, 업로드 상태 화면의 동작이 그대로다.
- SAF export가 계속 동작한다.
- `arcore_poses.csv`의 헤더와 `tracking_state` 기록 형식이 변경되지 않았다.

## 자동 검증 실행 기록

**2026-09-14** · 브랜치 `feature/session-episode-tracking-gate`

```bash
./gradlew.bat ktlintFormat testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest --no-daemon
```

`BUILD SUCCESSFUL` (49s). 변경 전 기준선도 같은 명령으로 통과했다(53s).

추가·수정된 테스트:

| 파일 | 테스트 |
|---|---|
| `capture/FrameTimestampWriterTest.kt` (신규) | 헤더 불변, `frame_number` 0부터 증가, 중복 timestamp 무시, 녹화 구간 밖 입력 무시, 녹화 공백을 건너뛴 연속 증가 |
| `capture/CaptureSessionCoordinatorTest.kt` | Session 시작이 Episode를 만들지 않음, Episode 3회 반복, 진행 중 Episode가 finalize 차단, READY gate 이전 시작 거부, 0.5초 미만 유실 유지, **값 고정 반복 호출로 마감 발화**, 중복 마감 방지, 회복 후 재개 |
| `ui/CaptureControlStateTest.kt` | 다섯 상태별 제어 표, `Initializing` 재생 차단, `Idle` 준비 게이트, 이탈 동작 |
| `episode/SessionFinalizerTest.kt` (신규) | `camera` 직렬화, 선택 필드 생략·기록, 메타데이터 없이 finalize 완료, 기존 키 보존 및 `SessionBundleValidator` 통과 |
| `ui/CaptureControlStateScreenTest.kt` | `Initializing` 재생 차단과 상태 표시, `Ready` 재생 허용 (Compose, 실기기 실행은 T032) |

`assembleDebugAndroidTest`는 instrumentation APK 컴파일만 확인한 것이며 실행은 T032의 실기기 작업으로 남는다.

## 완료 판정

`specs/AGENTS.md`에 따라, 위 자동 검증과 실기기 시나리오 1~5가 모두 통과하고 그 근거(실행한 명령, 테스트명, 기기와 결과)가 `tasks.md`에 기록된 경우에만 완료로 보고한다. 단위 테스트 통과만으로 실기기 동작을 검증했다고 판단하지 않는다.

## 실기기 검증 기록

**2026-09-14** · `SM-G973N`(Galaxy S10, Android 12) · Session `45f255d0-41e3-493a-9573-4f35ac67bcac`

### T032 · Compose 제어 상태

`./gradlew.bat connectedDebugAndroidTest --no-daemon` → 16개 테스트 전부 통과, 실패 0 (11.6s).
신규 `initializing_blocks_episode_start_and_shows_its_state`, `ready_state_enables_episode_start` 포함.

### T033 · Session과 Episode 분리 (SC-001, SC-004)

한 Session에서 Episode 4개를 수집했다. `episodes.csv`의 모든 `start_timestamp_ns`가 Session 시작
(영상 첫 timestamp `19141231810688`)보다 늦다.

Session 전체 55.6초 동안 모든 스트림이 끊김 없이 기록됐다. Episode 사이 공백이 없다.

| 스트림 | 범위 | 길이 | 최대 간격 |
|---|---|---|---|
| `accelerometer.csv` | 19141437241344 ~ 19196800269221 | 55.4초 | 21 ms |
| `gyroscope.csv` | 19141037242344 ~ 19196800269221 | 55.8초 | 22 ms |
| `rotation_vector.csv` | 19141057241344 ~ 19196800269221 | 55.7초 | 21 ms |
| `arcore_poses.csv` | 19141331794842 ~ 19196917367687 | 55.6초 | 42 ms |
| `main_frame_timestamps.csv` | 19141231810688 ~ 19196750724610 | 55.5초 | — |

### T034 · Tracking 게이트 (SC-002, SC-003)

`episodes.csv` 결과:

```
2bf129ba… 19148077977530 19155623725947 test test COMPLETED
41c5ac96… 19159733022598 19166958714747 test test COMPLETED
a77ac39d… 19171699700782 19177565158201 test test INVALID_TRACKING
3024d3ee… 19190212819576 19193833541805 test test COMPLETED
```

Tracking이 끊긴 Episode만 `INVALID_TRACKING`으로 마감됐다. `arcore_poses.csv` 대조 결과
`COMPLETED` Episode 3개 구간에는 `PAUSED` pose가 **0건**이다(각각 TRACKING 226·216·108건).
Session 전체로는 `TRACKING` 1486건, `PAUSED` 182건이다.

`INVALID_TRACKING` 마감 후에도 Session 수집이 계속됐고, Tracking 회복 뒤 Episode 4를 정상 수집했다.
SC-004(다른 Episode와 기록이 손실되지 않음)가 충족된다.

**편차**: 마감 시각과 첫 `PAUSED` pose의 간격이 **0.717초**로, 명세의 0.5초보다 **217 ms** 크다.
원인은 아래 `관측된 편차` 절에 기록한다.

### T035 · frame_number와 영상 대응 (SC-005, SC-009)

- 헤더 `frame_number,timestamp_ns,timestamp_source` 유지 ✓
- `frame_number`가 0에서 시작해 1665행까지 **결번 없이 1씩 증가** ✓
- `timestamp_ns` 단조 증가, 중복 없음 ✓
- CSV 데이터 행 1665 · MP4 sample_count 1667 → **차이 2 frame**. SC-009(2 이하) 충족.
  수신 측이 보고한 기존 3~9 frame 차이가 줄었다. 영상 중간 구간의 drop은 관측되지 않았다.

MP4 frame 수는 `stsz` box의 `sample_count`로 확인했다(ffprobe 미설치).

### T036 · Camera Metadata (SC-006, SC-007)

`metadata.json`의 `camera` 객체:

```json
{"camera_id":"0","image_width":640,"image_height":480,
 "fx":497.29745,"fy":497.2151,"cx":324.0054,"cy":240.17395,
 "focal_length_mm":4.32,"sensor_width_mm":5.645,"sensor_height_mm":4.234}
```

- 필수 7개 필드 모두 존재 ✓
- MP4 `avc1` 해상도 `640 x 480`으로 `image_width`/`image_height`와 **일치** ✓ (SC-007)
- `cx`≈324, `cy`≈240으로 해상도의 절반 부근 — 올바른 스트림의 intrinsics다
- `distortion_coefficients`는 기기가 `LENS_DISTORTION`을 제공하지 않아 **키가 생략**됐다.
  FR-024대로 값을 계산해 채우지 않았다 ✓
- `session_id`·`camera_streams`·`files` 세 키 형식 그대로 유지 ✓ (FR-026)

### T038 · 회귀

- ARCore `SharedCamera` 기반 Main RGB 녹화 정상. MP4 7.7 MB, 55.6초, H.264 640×480
- `arcore_poses.csv` 헤더와 `tracking_state` 기록 형식 변경 없음 ✓
- Session 목록 화면에서 완료 Session이 정상 표시됨

### 관측된 편차

**`INVALID_TRACKING` 마감 시각이 첫 `PAUSED` pose + 0.5초보다 217 ms 늦다.**

원인은 두 지연의 합이다.

1. ARCore pose 처리 지연. `arcore_poses.csv`의 시각은 camera sensor timestamp이지만,
   `session.update()`가 그 프레임을 내놓고 `tracking` 플래그가 바뀌는 시점은 그보다 뒤다.
2. Tracking 평가 주기 100 ms. `lossSinceNs`는 첫 `onTracking(false)` **호출 시각**으로 잡히므로
   최대 한 tick만큼 늦게 시작한다.

Episode 유효성 판정 자체는 의도대로 동작하므로 기능 결함은 아니다. 다만
[contracts/capture-state-machine.md](contracts/capture-state-machine.md)가 명시한
`end = 유실 시작 + 0.5초`를 `arcore_poses.csv` 기준으로 재면 이 편차만큼 어긋난다.
수신 측이 pose CSV로 경계를 재계산할 경우를 위해 허용 오차를 문서화하거나,
pose timestamp를 유실 시작 시각으로 쓰도록 바꾸는 선택지가 있다. 이번 범위에서는 기록만 남긴다.

### T037 · 미검증

EC2 업로드는 수행하지 않았다. 별도 확인이 필요하다.

---

## 수집 중 라이브 프리뷰 (Phase 12) · 2026-09-15 · `SM-G973N`, Android 12

`adb push` + `pm install`로 설치하고 설치 시각을 대조해 새 빌드임을 확인했다.

### 확인된 것

- 유휴 프리뷰 640×480 정상. 수집 중 프리뷰가 60초 내내 갱신됨(5초 간격 12개 표본 전부 상이)
- 수집 시작·Session 마감·업로드 정상
- `frame_number` 0~4961 결번 없음, `timestamp_ns` 단조 증가
- 실효 FPS 29.998 (프리뷰 없는 대조군 30.004) — 회귀 없음
- CSV 4962행 대 MP4 4965 frame → 차이 3. 같은 날 대조군도 차이 3으로 동일
- `metadata.json` 해상도 640×480이 MP4와 일치

### 접근 전환의 근거가 된 측정

프리뷰 surface를 `setAppSurfaces`에 등록하는 방식은 이 기기에서 실패한다.

```text
I TigerCapture: shared camera streams: arcore=2 app=2 total=4 preview=true valid=true
E TigerCapture: CAMERA_ERROR (3): endConfigure:704: Camera 0: Error configuring streams: Broken pipe (-32)
```

프리뷰만 뺀 3 stream에서는 정상 동작한다. 4 stream 조합을 기기가 거부한다.

### 미검증

- **Tracking 게이트(SC-002·SC-003)**: 기기를 고정한 채 원격 조작해 ARCore가 시차를 얻지 못했고
  Tracking이 `INITIALIZING`을 벗어나지 않았다. Episode 시작, `INVALID_TRACKING` 자동 마감,
  회복 후 재수집은 사람이 기기를 들고 움직이며 확인해야 한다.
- 프리뷰 화각과 저장 영상의 눈 대조. 구조적으로는 같은 해상도·같은 표시 기하를 쓴다.

### 기존 결함 (이번 변경과 무관)

수집 중 홈 버튼 중단 시 `SharedCamera.onCaptureSessionClosed`에서 프로세스가 죽는다.
프리뷰를 완전히 끈 빌드에서도 동일하게 재현된다. `releaseResources()`의 종료 순서 문제로 보인다.
데이터는 Phase 11의 구제 경로로 복구된다.

### 프리뷰 방향·화각 수정 (2026-09-15 추가 확인)

첫 GL 구현은 `setDisplayGeometry(ROTATION_0, imageSize)`를 썼고, 녹화본과 90도 어긋난 채
가로 화각도 크게 잘렸다. ARCore가 돌려주는 텍스처 좌표로 확인했다.

| | NDC 네 꼭짓점의 UV | 해석 |
|---|---|---|
| 수정 전 | `0.711,1.000 / 0.711,0.000 / 0.289,1.000 / 0.289,0.000` | 축 교환(90도 회전), u 범위 0.42 → 가로 58% 손실 |
| 회전만 수정 | `0.125,1.000 / 0.875,1.000 / 0.125,0.000 / 0.875,0.000` | 회전 없음, u 범위 0.75 → 가로 25% 손실 |
| 최종 | `0.000,1.000 / 1.000,1.000 / 0.000,0.000 / 1.000,0.000` | 회전 없음, 잘림 없음 |

기기의 ARCore Camera 구성은 다음과 같다.

```text
camera config: image=640x480 texture=1920x1080 fps=[30, 30]
```

녹화는 `imageSize`(4:3), 프리뷰가 그리는 GPU 텍스처는 `textureSize`(16:9)로 **서로 다른 스트림**이다.
표시 기하에 녹화 해상도를 주면 ARCore가 4:3에 맞춰 16:9 텍스처를 잘라낸다(0.75 = (4/3)/(16/9)).
텍스처 크기를 그대로 주어야 잘리지 않는다.

**남는 차이**: 프리뷰는 16:9, 녹화는 4:3이므로 세로 화각이 녹화본보다 좁다.
프리뷰가 그릴 수 있는 것은 ARCore GPU 텍스처뿐이므로 이 경로에서는 해소할 수 없다.
없애려면 texture와 image 비율이 같은 ARCore Camera 구성을 `CameraConfigFilter`로 고르는 방법이
있으나, 녹화 해상도와 Intrinsic이 바뀌므로 수신 측과 합의가 필요하다.

**MP4 방향**: `main_rgb.mp4`는 tkhd 회전 행렬이 항등이고 `setOrientationHint`를 주지 않아
Sensor 방향 그대로 저장된다. 수집 상세 화면이 영상을 돌려서 보여 주는 것이 아니라 원본이 가로다.
