---
description: "Episode Recorder MVP 구현 작업"
---

# Tasks: Episode Recorder MVP

**Input**: `specs/001-episode-recorder/`의 설계 문서

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: 명세가 JUnit 검증을 요구하므로 상태 전이, bundle 완결성, 입력 검증, 삭제 규칙, 목록·업로드 상태 및 multipart 요청 규칙의 단위 테스트를 포함한다. Camera·IMU·권한·저장소와 실제 서버 연결은 Galaxy S10 SM-G973N 수동 검증이 필요하다.

**Organization**: 작업은 사용자 스토리별로 묶는다. 모든 사용자 표시 문자열은 `res/values/strings.xml`에 둔다.

## Phase 1: Setup (공유 기반)

**Purpose**: 구현을 시작할 수 있는 앱 권한과 공통 리소스를 준비한다.

- [X] T001 사용자 승인을 받은 뒤 Camera 권한을 `app/src/main/AndroidManifest.xml`에 추가한다.
- [X] T002 [P] 녹화·업로드 상태·오류·삭제 확인 화면의 사용자 표시 문자열을 `app/src/main/res/values/strings.xml`에 정의한다.
- [X] T003 [P] 사용자 승인을 확인한 뒤 `gradle/libs.versions.toml`, 최상위 `build.gradle.kts`, `app/build.gradle.kts`에 OkHttp·MockWebServer·Room Runtime/KTX·Room compiler(KSP)·Room testing·Kotlin Coroutines Android·Lifecycle Runtime Compose·Kotlinx Serialization JSON/compiler plugin을 추가하고, 수동 constructor injection을 전제로 `capture/`, `sensor/`, `episode/`, `data/local/`, `upload/`, `ui/` 패키지 진입점을 만든다.

---

## Phase 2: Foundational (모든 스토리를 막는 선행 조건)

**Purpose**: episode 상태, 로컬 bundle, CaptureLog, 기기 capability를 일관되게 다루는 기반을 만든다.

**⚠️ CRITICAL**: 이 단계가 끝나기 전에는 실제 녹화 화면을 연결하지 않는다.

- [ ] T004 [P] Episode, CameraConfig, TimebaseMetadata, CaptureLog, RecordingState, `LOCAL_ONLY`·`UPLOADING`·`UPLOADED`·`FAILED` UploadState 및 metadata/receipt/error의 `@Serializable` 모델을 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 구현한다.
- [ ] T005 [P] 한국어를 포함한 UTF-8 task·object 입력과 task의 경로 구분자·제어 문자 거부, 허용 해상도/30 FPS 설정을 검증하는 순수 함수를 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingInputValidator.kt`에 구현한다.
- [ ] T006 [P] UTF-8 task·object 입력 검증과 녹화 상태 전이를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/RecordingInputValidatorTest.kt` 및 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModelsTest.kt`를 작성한다.
- [ ] T007 staging directory, episode UUID/display name, 여섯 출력 파일 경로, metadata 최종 commit marker를 관리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`를 구현한다.
- [ ] T008 필수 여섯 파일·CSV 헤더·metadata commit marker를 검사하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidator.kt`를 구현한다.
- [ ] T009 [P] bundle 완결성·누락 파일 거부·display name 생성 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidatorTest.kt`를 작성한다.
- [ ] T010 Room의 `EpisodeEntity`, `EpisodeDao`, `TigerDatabase`와 이를 사용한 `EpisodeRepository`를 `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`에 구현하여 staging recovery와 completed catalog의 Flow 조회·갱신을 처리한다.
- [ ] T011 Room의 `CaptureLogEntity`, `CaptureLogDao`와 `CaptureLogStore`를 `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/CaptureLogStore.kt`에 구현하여 CaptureLog 영속화와 전체 삭제를 처리한다.
- [ ] T012 [P] physical main 1× 후보, 1080p/720p 30 FPS, zoom 1.0, OIS OFF, `SENSOR_INFO_TIMESTAMP_SOURCE = REALTIME`와 S10 기준 focal length `4.32000017 mm`·sensor physical size `[5.64499998, 4.23400021] mm`·active/pre-correction array `[0, 0, 4032, 3024]`의 존재 및 일치를 확인하고 불일치 시 시작을 막는 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraCapabilityPreflight.kt`를 구현한다.
- [ ] T013 [P] accelerometer·gyroscope·`TYPE_ROTATION_VECTOR` 존재와 rotation vector 5값을 확인하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorCapabilityPreflight.kt`를 구현한다.
- [ ] T014 저장 공간 부족 및 preflight 실패를 녹화 시작 불가 상태로 표현하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingReadiness.kt`를 구현한다.

**Checkpoint**: staging bundle, 업로드 상태를 보존할 completed catalog, CaptureLog store, capability 및 시작 가능 여부가 준비된다.

---

## Phase 3: User Story 1 - 완결된 로컬 episode 기록 (Priority: P1) 🎯 MVP

**Goal**: task·object를 입력한 수집자가 후면 main 1× 영상과 세 IMU 원시 스트림을 한 개의 완결된 로컬 episode로 저장한다.

**Independent Test**: Galaxy S10에서 1080p 30 FPS로 정상 종료한 뒤 여섯 파일, CSV 헤더, metadata의 `VERIFIED` timebase와 초기 `LOCAL_ONLY` 상태를 확인한다.

### Tests for User Story 1

- [ ] T015 [P] [US1] S10 필수 non-null metadata, `contracts/episode-upload.md`의 metadata JSON nested schema, 세 센서 CSV·frame timestamp 형식을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeMetadataWriterTest.kt`를 작성한다.
- [ ] T016 [P] [US1] 정상 종료 시에만 completed로 공개되는 흐름을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeFinalizationTest.kt`를 작성한다.

### Implementation for User Story 1

- [ ] T017 [P] [US1] `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`의 정확한 헤더와 원본 `SensorEvent` 값 및 heading-accuracy sentinel을 쓰는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorCsvWriter.kt`를 구현한다.
- [ ] T018 [US1] SensorManager 등록, callback 기록, 종료 flush, 정확도·샘플 수 상태를 처리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorRecorder.kt`를 구현한다.
- [ ] T019 [US1] Camera2 preview, 선택된 1080p/720p 30 FPS·zoom 1.0·OIS OFF capture request, capture callback의 frame number/timestamp 기록을 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraRecorder.kt`에 구현한다.
- [ ] T020 [US1] MediaCodec/MediaMuxer video 출력과 encoder·muxer 오류 전달을 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/VideoEncoder.kt`에 구현한다.
- [ ] T021 [US1] Kotlinx Serialization으로 `contracts/episode-upload.md`의 metadata JSON 필수 field와 다섯 원본 파일 manifest를 쓰고, `frame_number,timestamp_ns,timestamp_source` CSV와 S10의 실제 non-null camera metadata를 기록하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeMetadataWriter.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriter.kt`를 구현한다.
- [ ] T022 [US1] preflight부터 recorder 시작·정상 종료·bundle 검증·completed 공개까지 조정하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingCoordinator.kt`를 구현한다.
- [ ] T023 [US1] task/object 입력, 해상도 선택, preview, 경과 시간, Camera/IMU 상태, 시작·정지 제어 상태를 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/RecordingViewModel.kt`에 구현한다.
- [ ] T024 [US1] 녹화 화면 Composable을 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/RecordingScreen.kt`에 구현하고 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 연결한다.

**Checkpoint**: 정상 녹화가 여섯 파일의 `COMPLETED` / `LOCAL_ONLY` episode 하나를 만든다.

---

## Phase 4: User Story 3 - 중단 녹화 제외 및 CaptureLog 관리 (Priority: P1)

**Goal**: 감지 가능한 녹화 실패는 completed episode가 되지 않고 CaptureLog에 남으며, 수집자는 CaptureLog 전체를 삭제할 수 있다.

**Independent Test**: 취소, `onStop`, buffer loss/capture failure/sequence abort, Camera·IMU·encoder/muxer/writer 오류, 앱 재시작에서 completed episode가 없고 CaptureLog 필수 필드가 있는지 확인한다. 전체 로그 삭제 후 episode가 유지되는지 확인한다.

### Tests for User Story 3

- [ ] T025 [P] [US3] 취소·`onStop`·buffer loss·capture failure·sequence abort·오류의 `INTERRUPTED` 전이와 `onPause` 무시를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/RecordingInterruptionTest.kt`를 작성한다.
- [ ] T026 [P] [US3] 다음 실행의 staging 정리·CaptureLog 보존·전체 로그 삭제를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/CaptureLogStoreTest.kt`를 작성한다.

### Implementation for User Story 3

- [ ] T027 [US3] Camera callback의 buffer loss·capture failure·sequence abort와 device/session·IMU·encoder/muxer/writer 오류를 `INTERRUPTED`와 CaptureLog로 변환하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingInterruptionHandler.kt`를 구현한다.
- [ ] T028 [US3] Activity의 `onStop`에서만 진행 중 녹화를 중단하고 `onPause`에서는 계속 유지하도록 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/RecordingViewModel.kt`를 연결한다.
- [ ] T029 [US3] 앱 시작 시 미완료 staging 원시 데이터를 삭제하고 구조화된 진단 로그를 유지하도록 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 확장한다.
- [ ] T030 [US3] 확인 후 CaptureLog 전체를 삭제하는 ViewModel 상태와 화면 제어를 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/CaptureLogViewModel.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`에 구현한다.

**Checkpoint**: 감지 가능한 실패는 completed episode를 만들지 않으며, 사용자는 episode를 건드리지 않고 CaptureLog 전체만 비울 수 있다.

---

## Phase 5: User Story 2 - 완료된 로컬 episode 확인 및 삭제 (Priority: P2)

**Goal**: 수집자가 완료된 로컬 episode의 필드를 확인하고, 원하는 bundle 하나만 삭제한다.

**Independent Test**: 정상 완료 episode 한 건을 만든 후 목록에서 다섯 표시 필드와 업로드 상태를 확인하고, 삭제 확인 후 해당 bundle과 목록 항목만 사라지는지 확인한다.

### Tests for User Story 2

- [ ] T031 [P] [US2] Room in-memory database를 사용해 completed episode만 정렬·표시하고 업로드 상태를 보존하는 repository 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepositoryTest.kt`를 작성한다.
- [ ] T032 [P] [US2] 앱 전용 completed root 안의 `UPLOADING`이 아닌 episode bundle만 개별 삭제하는 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeDeletionTest.kt`를 작성한다.
- [ ] T033 [P] [US2] 목록 항목의 task·object·시각·길이·sync state와 삭제 확인 상태를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModelTest.kt`를 작성한다.

### Implementation for User Story 2

- [ ] T034 [US2] completed catalog을 목록 표시 모델로 변환하고, `UPLOADING`이 아닌 경우에만 확인 후 단일 bundle을 안전하게 삭제하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModel.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 구현한다.
- [ ] T035 [US2] Room Flow를 `collectAsStateWithLifecycle`로 수집하는 완료 episode 목록·필수 다섯 필드·`UPLOADING` 중 비활성화되는 개별 삭제 확인 UI를 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`에 구현하고 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 연결한다.

**Checkpoint**: 사용자는 completed episode와 현재 업로드 상태를 식별하고 필요한 bundle 하나만 삭제한다.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 검증, 회귀 방지, 실제 기기 수동 검증을 마무리한다.

- [ ] T036 [P] recording/list 화면의 화면 상태와 오류 메시지를 `app/src/main/res/values/strings.xml` 기준으로 점검하고 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/RecordingScreen.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`를 정리한다.
- [ ] T037 `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug`, `.\gradlew.bat assembleDebug`를 실행하고 결과를 `specs/001-episode-recorder/quickstart.md`에 기록한다.
- [ ] T038 Galaxy S10 SM-G973N에서 `specs/001-episode-recorder/quickstart.md`의 정상 수집·중단·episode 삭제·CaptureLog 전체 삭제 흐름을 수동 검증하고 결과를 기록한다.

---

## Phase 7: 서버 업로드 기반 (공유 선행 조건)

**Purpose**: API 명세의 HTTPS·build-time URL·업로드 상태를 로컬 Recorder 뒤에 추가한다.

**⚠️ CRITICAL**: T039–T040은 Manifest·Gradle 변경을 포함하므로 구현 직전에 사용자 승인을 다시 확인한다.

- [ ] T039 사용자 승인을 확인한 뒤 `INTERNET`, `ACCESS_NETWORK_STATE`, HTTPS-only network security config 참조를 `app/src/main/AndroidManifest.xml`에 추가하고 cleartext를 차단하는 `app/src/main/res/xml/network_security_config.xml`을 만든다.
- [ ] T040 [P] 사용자 승인을 확인한 뒤 `app/build.gradle.kts`에서 source에 실제 URL을 남기지 않는 build-time `EPISODE_UPLOAD_BASE_URL` 주입·BuildConfig 노출을 구성한다.
- [ ] T041 build-time URL이 비어 있거나 HTTPS가 아니면 업로드를 시작하지 않도록 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/UploadServerConfig.kt`를 구현하고 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/UploadServerConfigTest.kt`를 작성한다.
- [ ] T042 [P] `UploadAttempt`, `RemoteReceipt`, `LOCAL_ONLY`·`UPLOADING`·`UPLOADED`·`FAILED` 상태와 마지막 HTTP status·server error code·실패 요약의 Room catalog mapping 및 Kotlinx Serialization 직렬화 규칙을 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/`, `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModelsTest.kt`에 추가한다.

**Checkpoint**: 앱은 build-time HTTPS endpoint만 사용하며, 로컬 completed episode에 업로드 상태와 마지막 시도 결과를 보존할 수 있다.

---

## Phase 8: User Story 4 - completed episode 수동 업로드 (Priority: P1)

**Goal**: 수집자가 여섯 파일 completed bundle 하나를 API 명세대로 서버에 전송하고 `201 created` 또는 `200 duplicate` 결과를 `UPLOADED`로 확인한다.

**Independent Test**: API 계약 fixture로 six-part request의 part 이름·content type·`Content-Length`·`Idempotency-Key`를 확인하고, 일치하는 receipt만 성공 상태로 전이하는지 검증한다.

### Tests for User Story 4

- [ ] T043 [P] [US4] completed 상태·여섯 파일 존재와 `metadata.json`을 제외한 다섯 원본 파일의 `metadata.files` relative path·`size_bytes`·`sha256` 불일치를 요청 전에 거부하는 테스트를 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadValidatorTest.kt`에 작성한다.
- [ ] T044 [P] [US4] MockWebServer로 여섯 multipart part만 전송하는지와 각 part의 name·고정 filename·UTF-8 content type·content length·`Idempotency-Key`를 검증하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/OkHttpEpisodeUploadClientTest.kt`를 작성한다.
- [ ] T045 [US4] MockWebServer fixture로 `201/{episode_id, created}`, `200/{episode_id, duplicate}`, 누락·불일치 receipt·잘못된 success content type·예상 밖 `2xx`·redirect 거부를 검증하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/OkHttpEpisodeUploadClientTest.kt`를 확장한다.

### Implementation for User Story 4

- [ ] T046 [US4] 전송 직전 completed bundle과 `metadata.json`의 다섯 원본 파일 manifest를 다시 검사하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadValidator.kt`를 구현한다.
- [ ] T047 [US4] OkHttp `MultipartBody`로 여섯 파일을 전체 heap buffering 없이 request로 조합하고 `Idempotency-Key`를 설정하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadRequestFactory.kt`를 구현한다.
- [ ] T048 [US4] OkHttpClient의 HTTPS 기본 인증서 신뢰·redirect 거부·connect 10초/read 30초/write 120초 timeout·전체 call timeout 미설정을 적용하고 `POST /episodes` success receipt를 처리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/OkHttpEpisodeUploadClient.kt`를 구현한다.
- [ ] T049 [US4] 수동 업로드 시작·receipt 검증·원본 bundle 불변성을 조정하고 성공 결과를 catalog에 기록하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadCoordinator.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 구현한다.

**Checkpoint**: 유효한 completed bundle은 서버 `201 created` 또는 `200 duplicate` receipt 뒤에만 `UPLOADED`가 되며, 로컬 여섯 파일은 유지된다.

---

## Phase 9: User Story 5 - 실패 업로드 수동 재전송 (Priority: P2)

**Goal**: 수집자가 실패한 episode를 원본 손상·중복 생성 없이 전체 bundle로 다시 전송한다.

**Independent Test**: 연결 오류, `408`, `429`, `5xx`, `3xx`, 모든 `4xx`, 앱 종료 후 미수신 결과를 재현해 `FAILED` 기록과 수동 재전송 request를 검증한다.

### Tests for User Story 5

- [ ] T050 [P] [US5] 연결/TLS 오류·request 취소·`3xx`·`4xx`·`5xx`·invalid success receipt를 `FAILED`로 기록하고, 가능한 HTTP status·server error code·실패 요약을 보존하는 테스트를 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadCoordinatorTest.kt`에 작성한다.
- [ ] T051 [P] [US5] 앱 재시작 시 receipt 없는 `UPLOADING`을 `FAILED`로 복구하고, 재전송마다 동일 `episode_id`·`Idempotency-Key`와 six-file 전체 body를 쓰는 테스트를 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadRetryTest.kt`에 작성한다.

### Implementation for User Story 5

- [ ] T052 [US5] 성공 조건을 만족하지 않는 HTTP/transport 결과를 `FAILED`와 사용자 표시용 오류 요약으로 기록하고, receipt 없는 진행 상태를 catalog recovery에서 `FAILED`로 바꾸는 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadCoordinator.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 확장한다.
- [ ] T053 [US5] 사용자가 재전송할 때 업로드 세션·offset 없이 같은 key로 여섯 파일 bundle 전체를 새 request에 넣도록 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/EpisodeUploadRequestFactory.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/OkHttpEpisodeUploadClient.kt`를 확장한다.

**Checkpoint**: 성공하지 않은 업로드는 모두 `FAILED` 마지막 시도로 남고, 사용자의 수동 재전송은 원본을 보존한 채 중복 없이 처리된다.

---

## Phase 10: User Story 6 - 업로드 상태 확인 (Priority: P2)

**Goal**: 수집자가 목록에서 수동 업로드·재전송 제어와 현재 상태·마지막 시도 결과를 확인한다.

**Independent Test**: `LOCAL_ONLY`, `UPLOADING`, `UPLOADED`, `FAILED` episode를 fixture로 만들어 표시·버튼 활성화·마지막 HTTP status·server error code·오류 요약이 구분되는지 확인한다.

### Tests for User Story 6

- [ ] T054 [P] [US6] 상태별 업로드/재전송 제어, 마지막 시도 시각·결과 표시, 업로드 중 중복 시작 차단을 검증하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModelTest.kt`를 작성한다.

### Implementation for User Story 6

- [ ] T055 [US6] 목록 ViewModel에 upload·retry 이벤트와 진행 중 중복 요청 차단을 추가하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModel.kt`를 구현한다.
- [ ] T056 [US6] Lifecycle-aware state collection으로 상태·마지막 시도·오류 요약·수동 업로드/재전송 버튼을 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`에 구현하고 필요한 문자열을 `app/src/main/res/values/strings.xml`에 추가한다.

**Checkpoint**: 수집자는 어떤 completed episode가 아직 로컬인지, 업로드 중인지, 완료됐는지, 재전송 또는 수정이 필요한지 구분할 수 있다.

---

## Phase 11: 네트워크 검증 및 마무리

**Purpose**: 계약 준수와 실제 Galaxy S10 HTTPS 연결을 검증한다.

- [ ] T057 [P] API 명세의 `201 created`와 `200 duplicate` receipt는 `UPLOADED`로, `400`, `409` error code 둘, `413`, `415`, `422`, `429` fixture는 `FAILED` 마지막 시도로 기록되는지 `contracts/episode-upload.md` 및 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/` 테스트에 대조한다.
- [ ] T058 `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug`, `.\gradlew.bat assembleDebug`를 실행하고 네트워크 관련 결과를 `specs/001-episode-recorder/mobile-transfer-quickstart.md`에 기록한다.
- [ ] T059 Galaxy S10 SM-G973N에서 신뢰 가능한 HTTPS 인증서와 실제 server base URL로 신규 업로드·duplicate·연결 중단·재전송·`4xx` 흐름과 업로드 시작 후 5초 이내 `UPLOADING` 표시를 `specs/001-episode-recorder/mobile-transfer-quickstart.md`에 따라 수동 검증하고 결과를 기록한다.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 즉시 시작 가능. T001과 T003의 Manifest·의존성·플러그인 변경은 명세에 따라 사용자 승인이 선행된다.
- **Foundational (Phase 2)**: Setup 이후. 모든 사용자 스토리를 막는다.
- **US1 (Phase 3)**: Foundational 이후. 정상 녹화 MVP다.
- **US3 (Phase 4)**: US1의 recorder lifecycle 이후. 중단과 CaptureLog를 연결한다.
- **US2 (Phase 5)**: Foundational의 catalog 이후 시작 가능하나, 실제 데이터 검증을 위해 US1 이후 수행한다.
- **Polish (Phase 6)**: 로컬 Recorder 사용자 스토리 완료 후 수행한다.
- **서버 업로드 기반 (Phase 7)**: completed bundle과 catalog가 준비된 뒤 수행한다. HTTPS server base URL·수신 응답 계약 제공 및 T039·T040의 사용자 승인이 선행된다.
- **US4 (Phase 8)**: Phase 7 이후. 신규·duplicate receipt를 처리하는 수동 업로드의 P1 범위다.
- **US5 (Phase 9)**: US4 이후. 오류 분류·catalog recovery·whole-bundle 재전송을 확장한다.
- **US6 (Phase 10)**: US4의 coordinator와 catalog state 이후. 목록 표시·사용자 제어를 연결한다.
- **네트워크 검증 (Phase 11)**: US4–US6 이후 실제 서버·인증서가 준비된 상태에서 수행한다.

### Parallel Opportunities

- Phase 1의 T002는 T001과 병렬 가능하며, T003은 의존성·플러그인 승인을 받은 뒤 진행한다.
- Phase 2의 T004–T006, T012, T013은 서로 다른 파일이므로 병렬 가능하다. T007 이후 T008–T011을 진행한다.
- US1의 T015, T016, T017은 서로 병렬 가능하다. T018과 T019는 각자의 writer/preflight가 준비된 후 병렬 가능하다.
- US3의 T025와 T026, US2의 T031–T033, Phase 7의 T040·T042, US4의 T043–T045, US5의 T050·T051, US6의 T054는 병렬 가능하다.

## Parallel Example: User Story 1

```text
Task: "T015 S10 metadata와 CSV 형식 단위 테스트"
Task: "T016 정상 종료 completed 공개 단위 테스트"
Task: "T017 SensorCsvWriter 구현"
```

## Implementation Strategy

### MVP First

1. T001–T014로 권한 승인 후 기반을 완성한다.
2. T015–T024로 US1 정상 녹화를 구현한다.
3. US3 중단 격리와 US2 목록·삭제를 구현한다.
4. T039–T042로 승인된 네트워크 기반과 upload state를 추가한다.
5. US4–US6으로 서버 업로드·상태·수동 재전송을 연결하고 실제 서버와 검증한다.

### Incremental Delivery

1. US1: 정상 수집과 완결 bundle
2. US3: 감지 가능한 실패 격리와 CaptureLog 전체 삭제
3. US2: completed episode 목록과 개별 삭제
4. Phase 7: HTTPS·build-time URL·upload state 기반
5. US4: 신규/duplicate 수동 업로드
6. US5: 오류 분류와 whole-bundle 재전송
7. US6: 업로드 상태 표시와 제어
8. Phase 11: 계약·실기기 네트워크 검증

## Notes

- `[P]`는 서로 다른 파일이며 선행 작업이 끝난 뒤 병렬로 수행할 수 있는 작업이다.
- 서버 내부 구현·후처리·MP4 frame↔timestamp 최종 검증은 MVP에 포함하지 않는다. 모바일의 서버 업로드·응답 처리·수동 재전송은 MVP에 포함한다.
- 앱은 명시적으로 감지 가능한 Camera/encoder 실패를 중단 처리하고, 성공 Camera capture의 frame number·timestamp·source를 원본대로 보존한다.
