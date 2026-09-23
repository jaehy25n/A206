# Tiger MASK — Manual Acquisition Setting Keeper

Tiger를 포크해 **수동 카메라 설정**만 얹은 앱입니다. 이름이 하는 일을 그대로 말합니다 —
사람이 손으로(**M**anual) 수집(**A**cquisition) 설정(**S**etting)을 정하고, 그 값을 촬영
내내 지킵니다(**K**eeper).

```text
Tiger  Target-Interaction Grounded Episode Recorder
MASK   Manual Acquisition Setting Keeper
```

목적은 카메라 기능 연구가 아니라, checkerboard calibration과 color reference 촬영과 실제
dataset 수집을 **같은 광학 조건**에서 하는 것입니다. 그 조건을 사람이 프리뷰로 보면서 정하고
Session 내내 고정합니다.

`applicationId`가 `com.ssafy.s15p21a206.tigermask`라 원본 Tiger와 같은 기기에 함께
설치됩니다. 원본 Tiger 저장소는 건드리지 않았습니다.

포크 기준은 Tiger `a4b16d2`(`refactor(capture): 카메라 열기를 한 번의 시도로 묶는다`)입니다.

## Tiger와 다른 점

Tiger는 카메라를 전부 자동에 맡깁니다. 정확히는 ARCore에 맡깁니다 — ARCore의 기본
`FocusMode`는 `FIXED`이고 초점을 **1.0 D(1 m)** 에 못 박아 둡니다. gripper가 흐렸던 원인은
autofocus 실패가 아니라 이것이었습니다.

이 포크가 더한 것은 **카메라 파라미터 층 하나**입니다. Surface 구성, MediaRecorder,
pose·IMU 기록 구조는 그대로입니다. 새 Surface나 `ImageReader`를 만들지 않습니다.

| | Tiger | Tiger MASK |
| --- | --- | --- |
| 초점 | ARCore 고정(1.0 D) | 사용자가 0 D ~ 기기 최대 diopter에서 선택 |
| 노출·ISO | 자동 | 사용자가 선택, 촬영 내내 고정 |
| 화이트 밸런스 | 자동(촬영 중 변함) | 프리뷰에서 수렴시킨 값으로 고정 |
| 프레임 간격 | 자동 | `SENSOR_FRAME_DURATION` 33,333,333 ns |
| OIS / EIS | 기본값 | OFF |
| `metadata.json` | `camera` | `camera` + `capture_settings` |

### 고르는 것과 지키는 것

이 앱의 한 줄은 **사람이 고른 값으로 찍힌다**입니다. 둘 중 하나만으로는 문장이 성립하지
않습니다. 어느 쪽이 모자랐는지는 항목마다 다릅니다.

**초점은 고를 수 없던 쪽입니다.** Tiger에서도 초점은 고정이었습니다 — ARCore가 1.0 D(1 m)에
못 박아 두었고, 그 값은 바꿀 방법이 없었습니다. 작업 영역이 흐렸던 원인은 값이 움직여서가
아니라 **고를 수 없어서**입니다. 여기서 새로 생긴 것은 오직 "고를 수 있다"입니다.

**노출·ISO·화이트 밸런스는 지켜지지 않던 쪽입니다.** 고정이 아니라 매 프레임 움직이고
있었습니다. 같은 기기에서 수동 설정 없이 10초를 찍은 기록입니다.

```text
frame#4  iso=50    exposure=16.7ms  gains=1.9599/…/1.8486
frame#9  iso=685
frame#14 iso=1175
frame#18 iso=1200  exposure=25.0ms
frame#20 iso=1218  exposure=33.3ms  gains=2.0332/…/1.8808
```

0.5초 만에 ISO가 50에서 1218로, 노출이 16.7 ms에서 33.3 ms로 올라갔습니다. 10초 동안 설정이
**74번** 바뀌었습니다. 같은 10초를 수동으로 찍으면 **0번**입니다.

그래서 고르는 것만으로도, 지키는 것만으로도 부족합니다. 틀린 값으로 고정되면 dataset을 쓸 수
없고, 고른 값이 다음 프레임에 자동으로 돌아가면 슬라이더는 장식입니다. 실제로 ARCore는
`resume()`에서 요청을 되가져가므로(아래 참고) 되받는 장치가 없으면 후자가 그대로 일어납니다.

calibration으로 구한 intrinsic과 LUT를 dataset에 갖다 쓰려면 세 촬영의 광학 조건이 같아야
합니다. 고르는 것은 그 조건을 정하는 일이고, 지키는 것은 그 조건이 세 촬영에 걸쳐 남게 하는
일입니다.

## 구현한 것

### 촬영 설정 패널

수집 화면 우측에 **카메라** 패널이 생겼습니다. Session 시작 전에 값을 고르고, 고른 값은
**바꾸는 즉시 프리뷰에 걸립니다**. 초점을 화면으로 보고 찾는 것이 목적이라 확인 버튼을 눌러야
반영되는 구조로 두지 않았습니다.

```text
카메라                    적용
초점                     4.00 D
FAR ────────●─────  NEAR
ISO                    ISO 100
────●────────────────
셔터                   8333 µs
[1/30] [1/60] [1/120] [1/240] [1/500]
FPS 30 고정
화이트 밸런스              고정됨
[ AUTO로 되돌리기 ]
```

### 걸리는 Camera2 key

| 항목 | key |
| --- | --- |
| Focus | `CONTROL_AF_MODE_OFF` + `LENS_FOCUS_DISTANCE` |
| ISO | `CONTROL_AE_MODE_OFF` + `SENSOR_SENSITIVITY` |
| Shutter | `SENSOR_EXPOSURE_TIME` |
| 30 fps | `SENSOR_FRAME_DURATION` |
| White balance | `CONTROL_AWB_MODE_OFF` + `COLOR_CORRECTION_GAINS` / `TRANSFORM` |
| 흔들림 보정 | `CONTROL_VIDEO_STABILIZATION_MODE_OFF`, `LENS_OPTICAL_STABILIZATION_MODE_OFF` |

### 하나의 설정 객체

`ManualCameraConfig` 하나를 프리뷰(`CameraPreviewController`)와 녹화
(`ArSharedCameraSession`)가 함께 씁니다. 화면용 값과 카메라용 값을 따로 들지 않습니다. 둘이
어긋나면 영상만 봐서는 보이지 않는 채로 조건이 달라지기 때문입니다.

### 기기 범위 안으로만

값의 범위는 **ARCore가 실제로 녹화에 쓰는 `cameraId`**에서 읽습니다. 프리뷰가 여는 첫 후면
카메라가 아닙니다 — 논리 카메라가 여럿인 기기에서는 ISO·노출 범위가 다르고, 프리뷰 기준으로
고른 값이 녹화 카메라에서는 범위 밖이면 조용히 다른 값으로 찍힙니다.

읽는 항목은 `REQUEST_AVAILABLE_CAPABILITIES`, `CONTROL_AE/AF/AWB_AVAILABLE_MODES`,
`SENSOR_INFO_SENSITIVITY_RANGE`, `SENSOR_INFO_EXPOSURE_TIME_RANGE`,
`SENSOR_INFO_MAX_FRAME_DURATION`, `LENS_INFO_MINIMUM_FOCUS_DISTANCE`,
`CONTROL_AWB_LOCK_AVAILABLE`입니다.

지원하지 않는 항목은 감추지 않고 **끈 채로 두고 이유를 보여 줍니다**. 수동 설정을 아예 쓸 수
없는 기기에서는 수집을 막지 않고 기존 자동 동작 그대로 찍습니다.

`exposure ≤ frame duration` 제약은 코드로 강제합니다. 노출이 프레임 간격보다 길면 센서가 간격을
늘려 30 fps가 깨집니다.

### Session 시작 후 고정

Session이 시작되면 패널이 접히고 값이 잠깁니다. 화면에서 막는 것과 별개로 상태 전이에서도
막습니다(`CaptureIntent.EditManualCamera`는 `Idle`에서만 받습니다). 촬영 도중 조건이 바뀌면 그
Session의 데이터를 한 조건으로 찍었다고 말할 수 없기 때문입니다.

### 요청값과 실제값

`CaptureRequest`에 넣었다고 센서가 그 값을 썼다고 보지 않습니다. 매 프레임 `CaptureResult`를
읽어 마지막 값을 `metadata.json`에 남기고, 요청과 다르면 logcat에 남깁니다.

```json
"capture_settings": {
  "mode": "manual",
  "requested": { "focus_distance_diopter": 4.0, "iso": 100,
                 "exposure_time_ns": 8333333, "frame_duration_ns": 33333333, "fps_target": 30 },
  "actual":    { "focus_distance_diopter": 3.9916728, "iso": 100,
                 "exposure_time_ns": 8333000, "frame_duration_ns": 33333000,
                 "af_mode": "OFF", "ae_mode": "OFF", "awb_mode": "OFF", "awb_locked": false },
  "awb_fixed": true
}
```

기존 `camera` 항목은 그대로이고 모든 필드에 기본값이 있어, 이 값이 없는 예전 Session을 읽는
쪽이 깨지지 않습니다. 업로드는 파일 multipart라 계약이 바뀌지 않습니다.

### ARCore가 요청을 덮는 것에 대하여

`Session.resume()`에서 ARCore가 repeating request를 자기 것으로 갈아 끼웁니다. resume 전에 건
수동 값은 **한 프레임만** 살아남고 그다음부터 노출과 화이트 밸런스가 자동으로 돌아갑니다.

```text
frame#1  request[af=OFF ae=OFF  awb=OFF  focus=4.0]   ← 우리 request
frame#2  request[af=OFF ae=ON   awb=AUTO focus=1.0]   ← ARCore가 갈아 끼운 것
```

기기(SM-G973N)에서 확인한 사실입니다. 그래서 `ArSharedCameraSession`이 요청이 바뀐 것을
알아채면 우리 요청을 되돌립니다. 되돌린 뒤로는 ARCore가 다시 가져가지 않습니다. 되받기는
횟수와 간격으로 묶어 두었습니다.

`SharedCamera` 문서는 ARCore가 도는 동안 `setRepeatingRequest`를 부르지 말라고 합니다. 그러나
ARCore 공식 샘플도 초점 모드를 바꿀 때 같은 일을 하고, 1분 녹화에서 프레임 공급도 pose 수급도
끊기지 않았습니다. 이 한 번 없이는 기능 자체가 성립하지 않습니다.

## 구현하지 않은 것

- **원본 Tiger에는 반영하지 않았습니다.** 이 저장소에만 있습니다. 여기서 확인한 구현을
  나중에 Tiger로 옮기는 것은 별도 작업입니다.
- **`CONTROL_AWB_LOCK` 방식.** lock은 절대값이 아니라 "지금 수렴한 값을 유지"라는 상대
  상태입니다. 프리뷰의 `CameraDevice`를 닫고 ARCore가 새 session을 열면 AWB는 처음부터 다시
  수렴하므로, 프리뷰에서 잠근 색이 녹화본으로 넘어가지 않습니다. gain과 transform을 숫자로
  들고 건너가는 방식으로 대신했습니다.
- **Kelvin·RGB gain을 직접 고르는 UI.** 목적이 정확한 색을 지정하는 것이 아니라 촬영 내내
  색이 변하지 않게 하는 것이라 만들지 않았습니다.
- **수치 직접 입력, 설정 프리셋 여러 개 저장.** 슬라이더와 preset 다섯뿐이고, 마지막에 쓴 값
  하나만 기억합니다.
- **조리개(`LENS_APERTURE`).** 이 기기는 F1.5와 F2.4를 고를 수 있지만 걸지 않고 기본값에
  맡깁니다. 심도가 모자라 앞뒤가 함께 맞지 않을 때 꺼낼 수단으로 남겨 둡니다.
- **촬영 도중 설정 변경.** 의도적으로 막았습니다. 위 "Session 시작 후 고정" 참고.
- **`specs/` 갱신.** 수집 흐름에 설정 단계가 생기고 `metadata.json`에 항목이 늘었으므로
  원래는 해당 명세를 함께 고쳐야 하지만, 포크된 `specs/`는 Tiger 시점 그대로입니다.
- **Jira 이슈 연결.** 등록하지 않았습니다.

## 실기기 확인 (SM-G973N / Android 12 / ARCore 1.56)

| 항목 | 결과 |
| --- | --- |
| 설정이 실제 녹화에 적용 | `actual`의 af·ae·awb 모두 `OFF` |
| 고른 값이 그대로 | 초점 9.813 D → **9.815 D**, ISO 3147 → **3147**, 노출 2,000,000 → **2,000,000 ns** |
| 촬영 내내 유지 | 되받기 1회 뒤 0회 |
| 30 fps | 1904프레임 **29.99 fps**, 969프레임 **29.97 fps**, 531프레임 **30.00 fps** |
| 노출과 프레임 간격이 따로 | 셔터를 1/120 → 1/500로 줄여도 프레임 간격은 33.3 ms 유지 |
| 화이트 밸런스 이관 | 프리뷰 수렴값 `gains=1.927/1.0/1.0/1.769`와 transform이 녹화 요청으로 전달됨 |
| 프리뷰 즉시 반영 | ISO 90 → 3147에서 밝아지고, 셔터 1/120 → 1/500에서 어두워지는 것이 화면으로 보임 |
| 설정 기억 | `am force-stop` 뒤 다시 열어도 초점·ISO·셔터·WB 고정이 그대로 복원 |
| 기존 산출물 | mp4·pose·IMU 3종·episodes·metadata 전부 정상 |

값은 세 벌(4.00 D/ISO 100, 3.08 D/ISO 90, 9.81 D/ISO 3147)로 확인했습니다. 서로 멀리 떨어진
값에서도 요청과 실제가 따라오므로, 특정 값에서만 맞는 것이 아닙니다.

`SENSOR_INFO_SENSITIVITY_RANGE=[50, 3200]`, `EXPOSURE_TIME_RANGE=[85 µs, 100 ms]`,
`LENS_INFO_MINIMUM_FOCUS_DISTANCE=10.0 D`(10 cm), 1920×1080 최소 프레임 간격 16.67 ms.
30 fps는 하드웨어 제약이 아닙니다.

기기 없이 도는 검사도 함께 통과했습니다.

| 검사 | 결과 |
| --- | --- |
| `testDebugUnitTest` | 151개 통과 (수동 설정 범위·제약 11개, 설정 → 산출물 8개 포함) |
| `am instrument` 계측 | `OK (34 tests)` |
| `ktlintCheck` | 통과 |
| `lintDebug` | 통과 |

### 아직 확인하지 못한 것

소프트웨어가 아니라 실제 배치와 조명이 있어야 답이 나오는 둘이 남았습니다.

**1. 한 초점에서 필요한 영역이 다 식별되는지.** 렌즈가 요청한 위치로 가는 것은 확인했지만,
그 초점면의 피사계 심도가 작업 대상과 gripper tip을 한꺼번에 덮는지는 물건을 놓고 봐야
압니다. 심도가 모자라면 이 기기 메인 카메라는 조리개가 **F1.5 / F2.4 둘**
(`lens.info.availableApertures=[1.5, 2.4]`)이므로 `LENS_APERTURE`로 조여 심도를 벌 수
있습니다. 지금은 그 키를 걸지 않고 기기 기본값에 맡깁니다. 폰을 뒤로 빼는 것도 같은 효과를
냅니다.

**2. ARCore TRACKING과 Episode 경로.** 확인한 세션은 모두 `arcore_poses.csv`가 `PAUSED`뿐이라
Episode를 시작할 수 없었고, 그래서 `episodes.csv`도 헤더만 남았습니다. 실패 이유는 계속
`INSUFFICIENT_LIGHT`였고 수동 설정을 걸지 않은 실행에서도 같았으므로 원인은 설정이 아니라
촬영 환경입니다. 다만 **수동 노출은 밝기를 잠그므로**, 자동이었다면 ISO를 1600까지 올려
버텼을 장면에서 ARCore가 못 볼 수 있습니다. 화질과 tracking이 맞서는 지점입니다.
tracking이 살지 않으면 ISO를 올리거나 셔터를 1/60·1/30으로 늦춥니다. 1/30(33.3 ms)까지는
30 fps 프레임 간격 안에 들어가 fps를 깨지 않습니다.

## 그대로 남아 있는 기능

- ARCore Shared Camera와 Camera2로 main RGB 영상 및 `SENSOR_TIMESTAMP` 기록
- 가속도계·자이로스코프·회전 벡터와 ARCore camera pose 기록
- Task/Object 단위 Episode START, END, CANCEL 기록
- raw file, CSV header, metadata manifest, SHA-256을 검증한 completed bundle 생성
- completed bundle의 multipart 업로드와 재전송

## 현재 범위

| 영역 | 상태 |
| --- | --- |
| 수동 촬영 설정(초점·ISO·셔터·WB 고정) | 구현됨 |
| 로컬 Capture Session·Episode 기록 | 구현됨 |
| main RGB, frame timestamp, IMU, ARCore pose bundle 생성 | 구현됨 |
| HTTP multipart 요청 생성 | 구현됨 |
| 앱 UI에서 서버 업로드·상태 전이·재시도 | 구현됨 |
| SAF 내보내기 | 제거됨 |

서버 `BASE_URL`은 `local.properties`의 `tigerUploadBaseUrl`로 주입합니다. 값이 없으면 앱에 전송 기능이 없습니다.

SAF 내보내기는 2026-09-22에 제거했습니다(S15P21A206-52). 번들을 기기 밖으로 내보내는 길은 업로드 하나입니다.

## 기술 구성

- Kotlin, Jetpack Compose, Material 3, Pretendard
- Android Camera2, ARCore Shared Camera
- Room, Kotlin Coroutines, kotlinx.serialization
- OkHttp
- 최소 SDK 28, target SDK 37

## 시작하기

### 요구 환경

- Android Studio 및 JDK 11
- Android SDK Platform 37
- ARCore 지원 Android 기기와 최신 Google Play Services for AR

저장소에는 Gradle Wrapper가 포함되어 있으므로 별도의 전역 Gradle 설치 없이 아래 명령을 실행할 수 있습니다.

```powershell
.\gradlew.bat assembleDebug
```

생성 APK:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 검증

저장소 루트에서 실행합니다.

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

연결된 실기기 또는 emulator가 있을 때만 instrumented test를 실행합니다.

```powershell
.\gradlew.bat connectedDebugAndroidTest
```

카메라, IMU, ARCore, 런타임 권한은 단위 테스트만으로 검증할 수 없습니다. 실기기 검증 절차는 [Capture Session 검증 가이드](specs/001-episode-recorder/quickstart.md)를 따릅니다.

## 데이터 흐름

```text
Camera2 + ARCore + IMU
        │
        ▼
capture/staging/<session_id>/
        │  finalize + file/manifest 검증
        ▼
capture/completed/<session_id>/
        │  사용자가 SAF tree 선택
        ▼
<selected tree>/TigerCapture/<session_id>/
```

completed bundle에는 다음 파일이 포함됩니다.

```text
main_rgb.mp4
main_frame_timestamps.csv
accelerometer.csv
gyroscope.csv
rotation_vector.csv
arcore_poses.csv
episodes.csv
metadata.json
```

completed bundle은 공개된 뒤 수정하지 않습니다. 업로드는 그것을 읽기만 하며, 실패하거나 중단되어도 원본은 남습니다.

## 업로드 계약

서버 연동을 위한 HTTP multipart 계약은 [Capture Session Upload 계약](specs/001-episode-recorder/contracts/episode-upload.md)에 정의돼 있습니다. 요청 생성기는 `POST {BASE_URL}/sessions`와 `Idempotency-Key: <session_id>`를 사용하지만, 실제 server URL 주입과 앱 흐름 연결은 아직 구현되지 않았습니다.

## 문서와 작업 방식

- 기능 명세·계획·작업: [`specs/001-episode-recorder/`](specs/001-episode-recorder/)
- SDD/Spec Kit 완료 판정 규칙: [`specs/AGENTS.md`](specs/AGENTS.md)
- 프로젝트 공통 작업 규칙: [`AGENTS.md`](AGENTS.md)

## 라이선스

현재 라이선스가 정의되지 않았습니다.
