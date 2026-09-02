# 기능 명세: Episode Recorder MVP

**기능 브랜치**: `master`  
**작성일**: 2026-09-01  
**상태**: 초안  
**입력**: Galaxy S10 로봇 End-Effector 데이터 수집 MVP를 위한 사용자 제공 Ouroboros Seed YAML.

## 목표

로봇 End-Effector 측 브래킷에 Galaxy S10을 강체 고정하고, 후면 메인 1× 카메라 영상과 accelerometer·gyroscope·`TYPE_ROTATION_VECTOR` 데이터를 동기화하여 episode 단위로 로컬 기록·저장하는 Android 데이터 수집 MVP를 구축한다.

## 명확화

### 세션 2026-09-01

- Q: 녹화 시작 전에 수집자가 1080p 또는 720p를 선택하고, 시작 후 그 설정을 고정하도록 할까요? → A: 기본값은 1080p이며, 수집자가 녹화 전에 1080p 또는 720p를 선택하고 시작 후 고정한다.
- Q: MVP에서 accelerometer·gyroscope 원시 x/y/z만 저장하고, roll·pitch·yaw는 서버 후처리에서 계산할까요? → A: accelerometer·gyroscope·`TYPE_ROTATION_VECTOR`가 제공하는 원시값을 저장하고, roll·pitch·yaw는 서버 후처리에서 계산한다.
- Q: IMU 원시 샘플 저장 형식으로 JSON, CSV, 다른 형식을 비교했을 때 무엇을 사용할까요? → A: `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`로 센서별 CSV 파일을 분리해 저장한다.
- Q: 센서별 CSV 열을 어떻게 명명할까요? → A: 대상 Galaxy S10 SM-G973N의 실제 sensor service 출력에 맞춰, 센서 값 의미가 드러나는 `x`, `y`, `z` 등의 열을 사용한다. accelerometer·gyroscope는 3개 값, `TYPE_ROTATION_VECTOR`는 5개 값을 기록한다.
- Q: video frame과 camera timestamp의 대응을 어디에서 검증할까요? → A: 앱은 Camera capture timestamp와 source를 원본대로 보존한다. MP4 frame↔timestamp 대응·frame 유실·동기화 품질 검증은 모바일 업로드 MVP 범위 밖인 서버 측 후속 범위에서 다룬다.
- Q: 대상 Galaxy S10의 Camera와 IMU timebase를 어떻게 처리할까요? → A: SM-G973N 후면 Camera device 0의 실제 `SENSOR_INFO_TIMESTAMP_SOURCE`는 `REALTIME`이다. Camera2 `SENSOR_TIMESTAMP`와 `SensorEvent.timestamp`를 같은 monotonic timebase로 기록하고, `timebaseVerificationStatus`는 `VERIFIED`로 기록한다. 이 조건이 다르면 지원 대상 capability 불일치 오류로 녹화를 시작하지 않는다.
- Q: 녹화 중 앱 화면이 완전히 보이지 않게 되면 언제 episode를 중단 처리할까요? → A: Activity가 완전히 보이지 않는 `onStop`에서 `INTERRUPTED`로 전환한다. 일시적인 `onPause`만으로는 중단하지 않는다.
- Q: Galaxy S10 후면 main camera의 광학 손떨림 보정(OIS)을 녹화 중 어떻게 처리할까요? → A: OIS를 OFF로 고정하고 metadata에 stabilization 상태를 기록한다.
- Q: 저장 공간이 부족할 때 completed episode와 구조화 로그를 어떻게 처리할까요? → A: completed episode와 로그는 사용자가 직접 삭제할 때까지 보존한다. 자동 삭제하지 않으며, 저장 공간이 부족하면 새 녹화를 시작하지 않는다.
- Q: 서버 설정 여부와 업로드 상태를 어떻게 표현할까요? → A: `SERVER_UNCONFIGURED`는 사용하지 않는다. 서버 존재 여부와 무관하게 아직 업로드하지 않은 completed episode는 `LOCAL_ONLY`로 표현한다.
- Q: 서버 전송을 이번 MVP에 포함할까요? → A: 포함한다. completed episode는 먼저 `LOCAL_ONLY`로 보존하고, 수집자가 수동으로 서버에 업로드·재전송할 수 있다. 모바일 통신 계약은 `contracts/episode-upload.md`를 따른다.
- Q: 프레임 유실을 어떻게 처리할까요? → A: `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, encoder·muxer·writer 오류처럼 앱이 명시적으로 감지한 실패는 즉시 `INTERRUPTED`로 처리한다. MP4와 Camera capture의 완전 대응 검증은 모바일 업로드 MVP 범위 밖인 서버 측 후속 범위에서 다룬다.
- Q: metadata의 nullable 정책은 무엇일까요? → A: SM-G973N Camera device 0에서 실제 제공되는 필수 metadata만 non-null으로 기록한다. `intrinsicCalibration`, `distortion`, `poseRotation`, `poseTranslation`, `poseReference`는 이 기기에서 제공되지 않으므로 metadata 계약에 포함하지 않는다.
- Q: 로컬 데이터 삭제는 어떻게 제공할까요? → A: completed episode는 개별 삭제할 수 있게 하고, CaptureLog는 열람·개별 삭제 없이 전체 삭제만 제공한다. 어느 데이터도 자동 삭제하지 않는다.

## 사용자 시나리오 및 테스트 *(필수)*

### 사용자 스토리 1 - 완결된 로컬 episode 기록 (우선순위: P1)

수집자는 작업 이름과 대상 물체를 입력하고 후면 메인 1× 카메라 프리뷰 및 센서 상태를 확인한 뒤, 로봇 End-Effector에 강체 고정된 장치로 카메라·IMU 동기화 episode 한 건을 기록한다. IMU 기록에는 accelerometer, gyroscope, `TYPE_ROTATION_VECTOR`가 제공하는 원시값이 포함된다.

**우선순위 근거**: 완결된 원시 데이터 episode의 로컬 저장이 MVP의 핵심 가치다.

**독립 테스트**: Galaxy S10에서 후면 메인 1× 카메라로 1920×1080, 30 FPS episode 한 건을 기록하고, 필수 episode 파일과 앱 상태를 확인한다.

**인수 시나리오**:

1. **Given** 작업 이름 또는 대상 물체가 비어 있고, **When** 수집자가 녹화를 시작하려 하면, **Then** 녹화가 시작되지 않는다.
2. **Given** 두 필수 텍스트 입력이 모두 채워져 있고, **When** 수집자가 녹화를 시작하면, **Then** 녹화 화면에 후면 메인 카메라 실시간 프리뷰, 녹화 경과 시간, 카메라 상태, IMU 상태가 표시된다.
3. **Given** 녹화가 진행 중이고, **When** 수집자가 녹화를 정상 종료하면, **Then** `video.mp4`, `frame_timestamps.csv`, `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`, `metadata.json`을 포함한 로컬 completed episode 한 건이 생성된다.
4. **Given** episode 녹화가 진행 중이고, **When** 수집자가 카메라 설정을 변경하려 하면, **Then** 해당 episode 동안 카메라 설정은 변경되지 않는다.

---

### 사용자 스토리 2 - 완료된 로컬 episode 확인 (우선순위: P2)

수집자는 로컬에서 완료된 episode를 검토하여 작업, 대상 물체, 녹화 시각, 길이, 동기화 상태를 식별한다.

**우선순위 근거**: 수집 직후 운영자가 유효한 episode 묶음과 중단 데이터를 구분할 수 있어야 한다.

**독립 테스트**: episode 한 건을 정상 완료하고 목록을 열어 필수 표시 필드와 동기화 상태를 확인한다.

**인수 시나리오**:

1. **Given** 여섯 개의 필수 파일을 모두 가진 녹화가 정상 완료되었고, **When** 수집자가 로컬 episode 목록을 열면, **Then** 해당 episode에 작업, 대상 물체, 녹화 시각, 길이, 동기화 상태가 표시된다.
2. **Given** 완료 episode가 있고, **When** 수집자가 로컬 episode를 확인하면, **Then** 로컬 데이터는 유지되고 현재 업로드 상태가 표시된다.
3. **Given** completed episode가 목록에 있고, **When** 수집자가 삭제를 확인하면, **Then** 해당 episode bundle만 삭제되고 목록에서 사라진다.

---

### 사용자 스토리 3 - 중단 녹화 제외 (우선순위: P1)

수집자는 취소·중단·실패한 녹화가 완결된 episode로 오인되지 않는다는 것을 신뢰할 수 있으며, 진단 정보는 로컬에 남아 있다.

**우선순위 근거**: episode 무결성은 후속 로봇 데이터 처리의 필수 조건이다.

**독립 테스트**: 취소, 앱 전면 이탈, Camera 또는 IMU 오류, 앱 재시작으로 녹화를 중단하고, 완료 episode가 목록에 없으며 중단 정보가 로그에 남았는지 확인한다.

**인수 시나리오**:

1. **Given** 녹화가 진행 중이고, **When** 수집자가 녹화를 취소하거나 앱이 전면을 이탈하거나 Camera 또는 IMU 오류가 발생하면, **Then** 완료 episode는 목록에 포함되지 않는다.
2. **Given** 녹화가 비정상 종료되었거나 완료 전에 앱이 재시작되었고, **When** 앱을 다음에 실행하면, **Then** 미완료 원시 데이터는 정리되며 중단 사유, 마지막 timestamp, 샘플 수, 오류 요약을 포함한 구조화된 로컬 진단 로그는 보존된다.
3. **Given** CaptureLog가 남아 있고, **When** 수집자가 전체 삭제를 확인하면, **Then** 모든 CaptureLog만 삭제되고 completed episode는 유지된다.

### 예외 상황

- 후면 메인 1× 카메라를 사용할 수 없거나 기본 촬영 설정을 유지할 수 없는 경우.
- 수집자가 녹화 전에 1280×720, 30 FPS를 선택한 경우. 기본값은 1920×1080, 30 FPS이며 episode 중 설정은 변경할 수 없다.
- 기기에서 Camera와 IMU timestamp를 하나의 monotonic timebase로 검증할 수 없는 경우에는 capability 불일치로 녹화를 시작하지 않는다.
- 녹화를 정상 종료했으나 필수 completed-episode 파일 여섯 개 중 하나라도 없거나 유효하지 않은 경우.
- `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, encoder·muxer·writer 오류가 발생한 경우에는 녹화를 중단하고 CaptureLog를 남긴다.

## 요구사항 *(필수)*

### 기능 요구사항

- **FR-001**: 시스템은 로봇 End-Effector 측 브래킷에 강체 고정된 Galaxy S10에서 후면 메인 1× 카메라, accelerometer, gyroscope, `TYPE_ROTATION_VECTOR`가 제공하는 원시값을 수집해야 한다.
- **FR-002**: 시스템은 녹화 시작 전에 비어 있지 않은 자유 텍스트 작업 이름과 대상 물체 입력을 요구해야 하며, 두 입력에 고정 카테고리 목록을 제공해서는 안 된다.
- **FR-003**: 시스템은 녹화 중 후면 메인 카메라 실시간 프리뷰, 녹화 경과 시간, 카메라 상태, IMU 상태를 표시해야 한다.
- **FR-004**: 시스템은 1920×1080, 30 FPS 및 고정 zoom ratio 1.0을 기본 촬영 설정으로 사용해야 하며, episode 중 카메라 설정 변경을 막아야 한다.
- **FR-005**: 시스템은 녹화 시작 전에 수집자가 1920×1080, 30 FPS 또는 1280×720, 30 FPS를 선택할 수 있게 해야 한다. 기본값은 1920×1080, 30 FPS이며, 선택된 설정은 episode 중 변경할 수 없다.
- **FR-005a**: 시스템은 Galaxy S10 후면 main camera의 OIS를 OFF로 고정하고, 사용 가능한 electronic stabilization 상태와 함께 실제 OIS 상태를 episode metadata에 기록해야 한다.
- **FR-006**: 시스템은 `video.mp4`, `frame_timestamps.csv`, `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`, `metadata.json`을 모두 포함한 경우에만 episode를 정상 완료로 확정해야 한다.
- **FR-007**: 시스템은 성공한 Camera capture의 `frame_number`, `SENSOR_TIMESTAMP`, timestamp source와 accelerometer·gyroscope·`TYPE_ROTATION_VECTOR` 각각이 제공하는 timestamp와 원시 샘플 값을 기록해야 한다. `frame_timestamps.csv`의 열은 `frame_number,timestamp_ns,timestamp_source`다. IMU 원시 샘플은 센서별 CSV 파일에 분리해 기록하며, 대상 Galaxy S10 SM-G973N의 실제 sensor service 출력에 맞춰 다음 열을 사용해야 한다: `accelerometer.csv`와 `gyroscope.csv`는 `timestamp_ns`, `x`, `y`, `z`, `accuracy`; `rotation_vector.csv`는 `timestamp_ns`, `x`, `y`, `z`, `scalar_component`, `heading_accuracy_rad`, `accuracy`다. 모든 `timestamp_ns`는 나노초 정밀도를 보존해야 한다. `heading_accuracy_rad`가 제공되지 않으면 Android 원본 sentinel 값 `-1`을 기록한다. roll·pitch·yaw는 앱에서 계산하거나 저장하지 않는다.
- **FR-008**: 시스템은 frame 및 IMU 기록의 원본 나노초 timestamp 값과 timestamp source/timebase metadata를 보존해야 한다.
- **FR-009**: 시스템은 대상 Galaxy S10 SM-G973N 후면 Camera device 0의 `SENSOR_INFO_TIMESTAMP_SOURCE = REALTIME`를 preflight에서 확인해야 한다. Camera2 `SENSOR_TIMESTAMP`와 `SensorEvent.timestamp`를 같은 monotonic timebase로 기록하고, episode metadata의 timebase verification status를 `VERIFIED`로 기록해야 한다. 이 조건이 다르면 capability 불일치 오류로 녹화를 시작해서는 안 된다.
- **FR-010**: 시스템은 Galaxy S10 SM-G973N Camera device 0에서 실제 제공되는 non-null metadata를 episode metadata에 포함해야 한다: logical/selected physical camera ID, lens facing, focal length `4.32000017 mm`, sensor physical size `[5.64499998, 4.23400021] mm`, active array 및 pre-correction active array `[0, 0, 4032, 3024]`, 해상도, FPS, zoom ratio, OIS/EIS 상태, timestamp source `REALTIME`, timebase verification status `VERIFIED`. `intrinsicCalibration`, `distortion`, `poseRotation`, `poseTranslation`, `poseReference`는 포함해서는 안 된다.
- **FR-011**: 시스템은 완료된 episode만 목록에 표시하고, 각 목록 항목에 작업, 대상 물체, 녹화 시각, 길이, 동기화 상태를 표시해야 한다.
- **FR-012**: 시스템은 Activity가 완전히 보이지 않는 `onStop`, 사용자 취소, Camera 또는 IMU 오류, 비정상 앱 종료로 중단된 녹화를 완료 episode 목록에서 제외해야 한다. 일시적인 `onPause`만으로는 녹화를 중단해서는 안 된다.
- **FR-013**: 시스템은 다음 앱 실행 시 중단 원시 데이터를 정리하되, 중단 사유, 마지막 timestamp, frame 및 sensor 샘플 수, 오류 요약을 포함한 구조화된 로컬 진단 로그는 보존해야 한다.
- **FR-013a**: 시스템은 completed episode와 구조화된 진단 로그를 자동 삭제해서는 안 되며, 저장 공간이 부족하면 새 녹화를 시작해서는 안 된다.
- **FR-013b**: 시스템은 수집자가 확인한 completed episode bundle 하나를 개별 삭제할 수 있게 해야 한다.
- **FR-013c**: 시스템은 수집자가 확인한 경우에만 모든 CaptureLog를 한 번에 삭제할 수 있게 해야 하며, completed episode를 삭제해서는 안 된다.
- **FR-014**: 시스템은 수명주기 상태 `RECORDING`, `COMPLETED`, `INTERRUPTED` 및 업로드 상태 `LOCAL_ONLY`, `UPLOADING`, `UPLOADED`, `FAILED`를 표현해야 한다.
- **FR-015**: 정상 완료 episode는 먼저 로컬 `LOCAL_ONLY` 상태로 유지하고, 수집자가 수동 업로드를 시작할 수 있게 해야 한다.
- **FR-016**: 시스템은 [episode upload 계약](contracts/episode-upload.md)이 정의한 `POST /episodes` multipart 통신 계약으로 completed episode를 서버에 전송하고, 서버 수신 성공 전에는 원본 bundle을 삭제하거나 변경해서는 안 된다.
- **FR-017**: 시스템은 `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, encoder·muxer·writer 오류를 앱에서 감지하면 해당 녹화를 `INTERRUPTED`로 처리하고 정식 episode에서 제외해야 한다. 앱은 Camera capture timestamp와 frame number를 보존하되, MP4 frame↔timestamp 대응·frame 유실·동기화 품질의 완전 검증은 이 MVP 범위 밖이다.

### 제약사항

- 기존 단일 Android app 모듈 및 Kotlin·Jetpack Compose·Material 3 구조를 유지해야 한다.
- Camera 권한, 새 라이브러리, Manifest 변경은 구현 직전에 사용자 확인을 받아야 한다.
- ORB-SLAM3, 카메라-EE 외부 보정, Task Representation 생성은 Android 앱 책임 범위 밖이며 서버 후처리 책임이다.

### 범위 외

- 서버 측 ORB-SLAM3 처리.
- 카메라-EE 외부 보정.
- Task Representation 생성.
- 서버의 데이터베이스·저장소·배포·후처리 구현과 서버 측 MP4 frame↔timestamp 최종 검증.

### 핵심 엔터티

- **Episode**: 불변 `episodeId`와 표시 이름으로 식별되는 로컬 데이터 수집 단위. 작업, 대상 물체, 녹화 상태, 업로드 상태, 카메라 설정, timestamp 기록, timebase metadata, capture log를 가진다.
- **카메라 설정**: 기록된 episode를 설명하는 기기 및 Camera 식별, lens facing, 해상도, FPS, zoom, stabilization, 사용 가능한 Camera metadata다.
- **Frame timestamp 기록**: 성공한 Camera capture의 frame number, 원본 timestamp, source 및 timebase 맥락이다.
- **IMU 샘플**: 원본 timestamp 맥락을 보존하는 accelerometer, gyroscope, 또는 `TYPE_ROTATION_VECTOR`의 제공 원시 측정값이다. 각 센서의 샘플은 해당 CSV 파일에 분리해 기록한다.
- **Timebase metadata**: `REALTIME` timestamp source와 `VERIFIED` monotonic timebase 검증 결과다.
- **Capture log**: 중단 녹화의 사유, 마지막 timestamp, 샘플 수, 오류 요약을 포함하는 구조화된 로컬 진단 정보다.

## 성공 기준 *(필수)*

### 측정 가능한 결과

- **SC-001**: 수집자는 작업 이름과 대상 물체에 모두 텍스트를 입력하기 전에는 녹화를 시작할 수 없고, 진행 중인 녹화 화면에는 카메라 프리뷰, 경과 시간, 카메라 상태, IMU 상태의 네 가지 필수 실시간 표시가 모두 나타난다.
- **SC-002**: 정상 완료된 녹화마다 `video.mp4`, `frame_timestamps.csv`, `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`, `metadata.json`을 모두 포함하는 로컬 completed episode가 정확히 한 건 생성된다.
- **SC-003**: 모든 completed episode는 성공한 Camera capture의 frame number와 timestamp, accelerometer·gyroscope·`TYPE_ROTATION_VECTOR` 원시 샘플의 timestamp와 제공 값을 timestamp source/timebase 검증 정보와 함께 보존한다. roll·pitch·yaw는 앱에서 계산·저장하지 않는다.
- **SC-004**: 사용자 취소, 앱 전면 이탈, Camera 또는 IMU 오류, 비정상 앱 종료로 중단된 녹화의 100%는 completed-episode 목록에서 제외되며, 지정된 구조화 진단 로그 필드를 보존한다.
- **SC-005**: Galaxy S10에서 수집자는 후면 메인 1× 카메라로 1920×1080, 30-FPS episode 한 건을 기록하고, 완료 episode 파일 여섯 개와 상태 UI를 확인할 수 있다.
- **SC-006**: 완료 episode는 로컬에서 계속 이용 가능하며, 수집자는 수동 업로드·완료·재전송 필요 상태를 구분할 수 있다. 업로드 성공 전·실패 후에도 원본 bundle은 유지된다.

## 검증 근거

| Seed 인수 기준 | 검증 | 기대 결과 |
| --- | --- | --- |
| 입력·상태·표시 모델 검증 | `.\gradlew.bat testDebugUnitTest` | `BUILD SUCCESSFUL` |
| 여섯 파일 bundle·목록 필드의 저장 규칙 검증 | `.\gradlew.bat testDebugUnitTest` | `BUILD SUCCESSFUL` |
| Camera 및 기기 metadata 직렬화 | `.\gradlew.bat testDebugUnitTest` | `BUILD SUCCESSFUL` |
| Frame/IMU timestamp 및 timebase metadata 직렬화 | `.\gradlew.bat testDebugUnitTest` | `BUILD SUCCESSFUL` |
| 중단·진단 로그·삭제의 상태 및 저장 규칙 검증 | `.\gradlew.bat testDebugUnitTest` | `BUILD SUCCESSFUL` |
| Camera/IMU/권한/실제 파일의 end-to-end 검증 | Galaxy S10 수동 검증 | `quickstart.md`의 정상 수집·중단·삭제 흐름 통과 |
| Galaxy S10 후면 메인 카메라 녹화 | Galaxy S10 수동 녹화 | 1920×1080, 30-FPS episode 한 건 및 완료 파일 여섯 개·상태 UI 확인 |
