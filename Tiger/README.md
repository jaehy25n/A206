# Tiger — Target-Interaction Grounded Episode Recorder

**T**arget-**I**nteraction **G**rounded **E**pisode **R**ecorder(Tiger)는 Android 기반 Capture Session 수집 앱입니다. 카메라 영상, 프레임 타임스탬프, IMU, ARCore pose와 작업 단위 Episode를 하나의 immutable Session bundle로 저장하고, 사용자가 선택한 Storage Access Framework(SAF) 폴더로 내보냅니다.

## 주요 기능

- ARCore Shared Camera와 Camera2로 main RGB 영상 및 `SENSOR_TIMESTAMP` 기록
- 가속도계·자이로스코프·회전 벡터와 ARCore camera pose 기록
- Task/Object 단위 Episode START, END, CANCEL 기록
- raw file, CSV header, metadata manifest, SHA-256을 검증한 completed bundle 생성
- 사용자가 선택한 SAF tree 아래의 안전한 export publish 및 재시도

## 현재 범위

| 영역 | 상태 |
| --- | --- |
| 로컬 Capture Session·Episode 기록 | 구현됨 |
| main RGB, frame timestamp, IMU, ARCore pose bundle 생성 | 구현됨 |
| SAF export와 destination bundle 검증 | 구현됨 |
| HTTP multipart 요청 생성 | 구현됨 |
| 앱 UI에서 실제 서버 업로드·상태 전이·재시도 | 미구현 |

서버 `BASE_URL`과 실제 ingestion server 연동은 아직 구성하지 않았습니다. 따라서 현재 앱의 완결된 사용자 흐름은 로컬 수집과 SAF export까지입니다.

## 기술 구성

- Kotlin, Jetpack Compose, Material 3
- Android Camera2, ARCore Shared Camera
- Room, Kotlin Coroutines, kotlinx.serialization
- OkHttp, Storage Access Framework
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

카메라, IMU, ARCore, 런타임 권한, SAF provider 동작은 단위 테스트만으로 검증할 수 없습니다. 실기기 검증 절차는 [Capture Session SAF Export 검증 가이드](specs/001-episode-recorder/quickstart.md)를 따릅니다.

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

SAF export는 선택된 tree 하위의 임시 attempt directory에 파일을 복사하고 검증한 뒤, 성공한 bundle만 `TigerCapture/<session_id>/`로 publish합니다. 원본 completed bundle은 export 실패 또는 재시도 시에도 유지됩니다.

## 업로드 계약

서버 연동을 위한 HTTP multipart 계약은 [Capture Session Upload 계약](specs/001-episode-recorder/contracts/episode-upload.md)에 정의돼 있습니다. 요청 생성기는 `POST {BASE_URL}/sessions`와 `Idempotency-Key: <session_id>`를 사용하지만, 실제 server URL 주입과 앱 흐름 연결은 아직 구현되지 않았습니다.

## 문서와 작업 방식

- 기능 명세·계획·작업: [`specs/001-episode-recorder/`](specs/001-episode-recorder/)
- SDD/Spec Kit 완료 판정 규칙: [`specs/AGENTS.md`](specs/AGENTS.md)
- 프로젝트 공통 작업 규칙: [`AGENTS.md`](AGENTS.md)

## 라이선스

현재 라이선스가 정의되지 않았습니다.
