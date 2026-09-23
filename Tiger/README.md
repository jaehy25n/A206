# Tiger — Target-Interaction Grounded Episode Recorder

**T**arget-**I**nteraction **G**rounded **E**pisode **R**ecorder(Tiger)는 Android 기반 Capture Session 수집 앱입니다. 카메라 영상, 프레임 타임스탬프, IMU, ARCore pose와 작업 단위 Episode를 하나의 immutable Session bundle로 저장하고, ingestion server로 전송합니다.

여기에 촬영 조건을 사람이 정하는 **MASK** 확장이 얹혀 있습니다. 아래 [MASK](#mask--manual-acquisition-setting-keeper)를 보세요.

## 주요 기능

- ARCore Shared Camera와 Camera2로 main RGB 영상 및 `SENSOR_TIMESTAMP` 기록
- 가속도계·자이로스코프·회전 벡터와 ARCore camera pose 기록
- Task/Object 단위 Episode START, END, CANCEL 기록
- raw file, CSV header, metadata manifest, SHA-256을 검증한 completed bundle 생성
- completed bundle의 multipart 업로드와 재전송
- **초점·ISO·셔터를 수집자가 직접 정하고 Session 내내 고정 (MASK)**

## 현재 범위

| 영역 | 상태 |
| --- | --- |
| 로컬 Capture Session·Episode 기록 | 구현됨 |
| main RGB, frame timestamp, IMU, ARCore pose bundle 생성 | 구현됨 |
| HTTP multipart 요청 생성 | 구현됨 |
| 앱 UI에서 서버 업로드·상태 전이·재시도 | 구현됨 |
| 수동 촬영 설정 (MASK) | 구현됨 |
| SAF 내보내기 | 제거됨 |

서버 `BASE_URL`은 `local.properties`의 `tigerUploadBaseUrl`로 주입합니다. 값이 없으면 앱에 전송 기능이 없습니다.

SAF 내보내기는 2026-09-22에 제거했습니다(S15P21A206-52). 번들을 기기 밖으로 내보내는 길은 업로드 하나입니다.

## MASK — Manual Acquisition Setting Keeper

Tiger 위에 얹은 촬영 조건 확장입니다. 사람이 손으로(**M**anual) 수집(**A**cquisition) 설정(**S**etting)을 정하고, 그 값을 촬영 내내 지킵니다(**K**eeper).

```text
Tiger  Target-Interaction Grounded Episode Recorder
MASK   Manual Acquisition Setting Keeper
```

수집 구조는 그대로입니다. Surface 구성, MediaRecorder, pose·IMU 기록에 손대지 않고 **카메라 파라미터 층 하나**를 더했을 뿐이며, 새 Surface나 `ImageReader`를 만들지 않습니다. 수동 제어를 지원하지 않는 기기에서는 수집을 막지 않고 기존 자동 동작 그대로 찍습니다.

`applicationId`가 `com.ssafy.s15p21a206.tigermask`라 MASK 없는 Tiger와 같은 기기에 함께 설치됩니다. 같은 장면을 두 조건으로 비교할 수 있습니다.

### 왜 필요한가

목적은 checkerboard calibration과 color reference 촬영과 실제 dataset 수집을 **같은 광학 조건**에서 하는 것입니다. Tiger는 카메라를 ARCore에 맡기는데, 두 가지가 동시에 걸립니다.

**고를 수 없습니다.** ARCore의 기본 `FocusMode`는 `FIXED`이고 초점을 1.0 D(1 m)에 못 박습니다. 가까운 작업 영역이 흐린 원인은 autofocus 실패가 아니라 이것입니다. 초점은 이미 고정이었고 값을 고를 방법이 없었습니다.

**지켜지지 않습니다.** 노출·ISO·화이트 밸런스는 반대로 매 프레임 움직입니다. 같은 기기에서 수동 설정 없이 10초를 찍은 기록입니다.

```text
frame#4  iso=50    exposure=16.7ms  gains=1.9599/…/1.8486
frame#9  iso=685
frame#14 iso=1175
frame#18 iso=1200  exposure=25.0ms
frame#20 iso=1218  exposure=33.3ms  gains=2.0332/…/1.8808
```

0.5초 만에 ISO가 50에서 1218로, 노출이 16.7 ms에서 33.3 ms로 올라갑니다. 10초 동안 설정이 **74번** 바뀝니다. 같은 10초를 수동으로 찍으면 **0번**입니다.

고르는 것과 지키는 것 중 하나만으로는 성립하지 않습니다. 틀린 값으로 고정되면 dataset을 쓸 수 없고, 고른 값이 다음 프레임에 자동으로 돌아가면 슬라이더는 장식입니다.

### 무엇이 늘었나

수집 화면 좌측 상단의 톱니바퀴가 카메라 설정을 엽니다. 화면 우측에서 열리는 모달 시트이고, 옆의 프리뷰는 어두워지지 않습니다. Session 시작 전에 값을 고르고, **바꾸는 즉시 프리뷰에 걸립니다**. 초점을 화면으로 보고 찾는 것이 목적이라 확인 버튼을 눌러야 반영되는 구조로 두지 않았습니다. 녹화 해상도도 여기서 고릅니다. Session이 시작되면 톱니바퀴가 사라지고 설정은 잠깁니다.

```text
카메라 설정                  ✕
녹화 해상도              1920×1080
[1920×1080] [1280×720]
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

| 항목 | 거는 key |
| --- | --- |
| Focus | `CONTROL_AF_MODE_OFF` + `LENS_FOCUS_DISTANCE` |
| ISO | `CONTROL_AE_MODE_OFF` + `SENSOR_SENSITIVITY` |
| Shutter | `SENSOR_EXPOSURE_TIME` |
| 30 fps | `SENSOR_FRAME_DURATION` (33,333,333 ns), `exposure ≤ frame duration` 강제 |
| White balance | `CONTROL_AWB_MODE_OFF` + `COLOR_CORRECTION_GAINS` / `TRANSFORM` |
| 흔들림 보정 | `CONTROL_VIDEO_STABILIZATION_MODE_OFF`, `LENS_OPTICAL_STABILIZATION_MODE_OFF` |

하나의 설정 객체를 프리뷰(`CameraPreviewController`)와 녹화(`ArSharedCameraSession`)가 함께 씁니다. Session이 시작되면 화면과 상태 전이 양쪽에서 잠깁니다. 값의 범위는 **ARCore가 실제로 녹화에 쓰는 `cameraId`**에서 읽고, 마지막에 쓴 값 한 벌을 기억합니다.

`metadata.json`에 `capture_settings`가 더해집니다. 요청값과 실제값을 나눠 담는 것은 `CaptureRequest`에 넣었다고 센서가 그 값을 썼다고 볼 수 없기 때문입니다. 형식은 [Session `metadata.json` 계약](specs/003-session-episode-tracking-gate/contracts/session-metadata.md)에 있습니다.

### ARCore가 요청을 되가져가는 것

`Session.resume()`에서 ARCore가 repeating request를 자기 것으로 갈아 끼웁니다. resume 전에 건 수동 값은 **한 프레임만** 살아남습니다.

```text
frame#1  request[af=OFF ae=OFF  awb=OFF  focus=4.0]   ← 우리 request
frame#2  request[af=OFF ae=ON   awb=AUTO focus=1.0]   ← ARCore가 갈아 끼운 것
```

그래서 `ArSharedCameraSession`이 요청이 바뀐 것을 알아채면 되돌립니다. 되돌린 뒤로는 ARCore가 다시 가져가지 않습니다. `SharedCamera` 문서는 ARCore가 도는 동안 `setRepeatingRequest`를 부르지 말라고 하지만, ARCore 공식 샘플도 초점 모드를 바꿀 때 같은 일을 하고 1분 녹화에서 프레임 공급도 pose 수급도 끊기지 않았습니다. 이 한 번 없이는 기능 자체가 성립하지 않습니다.

화이트 밸런스에 `CONTROL_AWB_LOCK`을 쓰지 않은 것도 같은 이유입니다. lock은 "지금 수렴한 값을 유지"라는 상대 상태라 `CameraDevice`가 바뀌면 처음부터 다시 수렴합니다. 프리뷰에서 잠근 색이 녹화본으로 넘어가지 않으므로 gain과 transform을 숫자로 들고 건너갑니다.

### 실기기 확인 (SM-G973N / Android 12 / ARCore 1.56)

| 항목 | 결과 |
| --- | --- |
| 설정이 실제 녹화에 적용 | `actual`의 af·ae·awb 모두 `OFF` |
| 고른 값이 그대로 | 초점 9.813 D → **9.815 D**, ISO 3147 → **3147**, 노출 2,000,000 → **2,000,000 ns** |
| 값 세 벌로 확인 | 4.00 D/ISO 100, 3.08 D/ISO 90, 9.81 D/ISO 3147 |
| 촬영 내내 유지 | 되받기 1회 뒤 0회 |
| 30 fps | 1022프레임 평균 **33.362 ms (29.97 fps)** |
| 노출과 프레임 간격이 따로 | 셔터 1/120 → 1/500에서도 프레임 간격 33.3 ms 유지 |
| 프리뷰 즉시 반영 | ISO·셔터 변경이 화면 밝기로 보임 |
| 설정 기억 | `force-stop` 뒤에도 복원 |
| 기존 산출물 | mp4·pose·IMU 3종·episodes·metadata 정상 |

`SENSOR_INFO_SENSITIVITY_RANGE=[50, 3200]`, `EXPOSURE_TIME_RANGE=[85 µs, 100 ms]`, `LENS_INFO_MINIMUM_FOCUS_DISTANCE=10.0 D`(10 cm), 1920×1080 최소 프레임 간격 16.67 ms. 30 fps는 하드웨어 제약이 아닙니다.

### 아직 확인하지 못한 것

소프트웨어가 아니라 실제 배치와 조명이 있어야 답이 나오는 둘이 남았습니다.

1. **한 초점에서 필요한 영역이 다 식별되는지.** 렌즈가 요청한 위치로 가는 것은 확인했지만, 그 초점면의 피사계 심도가 작업 대상과 gripper tip을 한꺼번에 덮는지는 물건을 놓고 봐야 압니다. 모자라면 이 기기는 조리개가 **F1.5 / F2.4** 둘이므로 `LENS_APERTURE`로 조여 심도를 벌 수 있습니다. 지금은 그 키를 걸지 않고 기기 기본값에 맡깁니다.
2. **ARCore TRACKING과 Episode 경로.** 확인한 세션은 모두 `arcore_poses.csv`가 `PAUSED`뿐이라 Episode를 시작할 수 없었습니다. 실패 이유는 계속 `INSUFFICIENT_LIGHT`였고 수동 설정을 걸지 않은 실행에서도 같았으므로 원인은 촬영 환경입니다. 다만 **수동 노출은 밝기를 잠그므로**, 자동이었다면 ISO를 1600까지 올려 버텼을 장면에서 ARCore가 못 볼 수 있습니다. tracking이 살지 않으면 ISO를 올리거나 셔터를 1/60·1/30으로 늦춥니다. 1/30(33.3 ms)까지는 30 fps 프레임 간격 안에 들어가 fps를 깨지 않습니다.

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
