---
description: "Episode Recorder MVP 구현 작업"
---

# Tasks: Episode Recorder MVP

**Input**: `specs/001-episode-recorder/`의 설계 문서

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: 명세가 JUnit 검증을 요구하므로 상태 전이, bundle 완결성, 입력 검증, 삭제 규칙, 목록 표시 규칙의 단위 테스트를 포함한다. Camera·IMU·권한·저장소의 실제 동작은 Galaxy S10 SM-G973N 수동 검증이 필요하다.

**Organization**: 작업은 사용자 스토리별로 묶는다. 모든 사용자 표시 문자열은 `res/values/strings.xml`에 둔다.

## Phase 1: Setup (공유 기반)

**Purpose**: 구현을 시작할 수 있는 앱 권한과 공통 리소스를 준비한다.

- [ ] T001 사용자 승인을 받은 뒤 Camera 권한을 `app/src/main/AndroidManifest.xml`에 추가한다.
- [ ] T002 [P] 녹화·상태·오류·삭제 확인 화면의 사용자 표시 문자열을 `app/src/main/res/values/strings.xml`에 정의한다.
- [ ] T003 [P] Episode Recorder 기능 패키지의 진입점을 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/`, `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/`, `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/`, `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/` 아래에 만든다.

---

## Phase 2: Foundational (모든 스토리를 막는 선행 조건)

**Purpose**: episode 상태, 로컬 bundle, CaptureLog, 기기 capability를 일관되게 다루는 기반을 만든다.

**⚠️ CRITICAL**: 이 단계가 끝나기 전에는 실제 녹화 화면을 연결하지 않는다.

- [ ] T004 [P] Episode, CameraConfig, TimebaseMetadata, CaptureLog, RecordingState, `LOCAL_ONLY` SyncState 모델을 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 구현한다.
- [ ] T005 [P] task·object 입력과 허용 해상도/30 FPS 설정을 검증하는 순수 함수를 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingInputValidator.kt`에 구현한다.
- [ ] T006 [P] 입력 검증과 녹화 상태 전이를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/RecordingInputValidatorTest.kt` 및 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModelsTest.kt`를 작성한다.
- [ ] T007 staging directory, episode UUID/display name, 여섯 출력 파일 경로, metadata 최종 commit marker를 관리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`를 구현한다.
- [ ] T008 필수 여섯 파일·CSV 헤더·metadata commit marker를 검사하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidator.kt`를 구현한다.
- [ ] T009 [P] bundle 완결성·누락 파일 거부·display name 생성 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidatorTest.kt`를 작성한다.
- [ ] T010 staging recovery와 completed catalog 조회·갱신을 처리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 구현한다.
- [ ] T011 CaptureLog의 영속화와 전체 삭제를 처리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/CaptureLogStore.kt`를 구현한다.
- [ ] T012 [P] physical main 1× 후보, 1080p/720p 30 FPS, zoom 1.0, OIS OFF, `SENSOR_INFO_TIMESTAMP_SOURCE = REALTIME`와 S10 기준 focal length `4.32000017 mm`·sensor physical size `[5.64499998, 4.23400021] mm`·active/pre-correction array `[0, 0, 4032, 3024]`의 존재 및 일치를 확인하고 불일치 시 시작을 막는 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraCapabilityPreflight.kt`를 구현한다.
- [ ] T013 [P] accelerometer·gyroscope·`TYPE_ROTATION_VECTOR` 존재와 rotation vector 5값을 확인하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorCapabilityPreflight.kt`를 구현한다.
- [ ] T014 저장 공간 부족 및 preflight 실패를 녹화 시작 불가 상태로 표현하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/RecordingReadiness.kt`를 구현한다.

**Checkpoint**: staging bundle, `LOCAL_ONLY` catalog, CaptureLog store, capability 및 시작 가능 여부가 준비된다.

---

## Phase 3: User Story 1 - 완결된 로컬 episode 기록 (Priority: P1) 🎯 MVP

**Goal**: task·object를 입력한 수집자가 후면 main 1× 영상과 세 IMU 원시 스트림을 한 개의 완결된 로컬 episode로 저장한다.

**Independent Test**: Galaxy S10에서 1080p 30 FPS로 정상 종료한 뒤 여섯 파일, CSV 헤더, metadata의 `VERIFIED` timebase와 `LOCAL_ONLY` 상태를 확인한다.

### Tests for User Story 1

- [ ] T015 [P] [US1] S10 필수 non-null metadata와 세 센서 CSV·frame timestamp 형식을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeMetadataWriterTest.kt`를 작성한다.
- [ ] T016 [P] [US1] 정상 종료 시에만 completed로 공개되는 흐름을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeFinalizationTest.kt`를 작성한다.

### Implementation for User Story 1

- [ ] T017 [P] [US1] `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`의 정확한 헤더와 원본 `SensorEvent` 값 및 heading-accuracy sentinel을 쓰는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorCsvWriter.kt`를 구현한다.
- [ ] T018 [US1] SensorManager 등록, callback 기록, 종료 flush, 정확도·샘플 수 상태를 처리하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/sensor/SensorRecorder.kt`를 구현한다.
- [ ] T019 [US1] Camera2 preview, 선택된 1080p/720p 30 FPS·zoom 1.0·OIS OFF capture request, capture callback의 frame number/timestamp 기록을 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraRecorder.kt`에 구현한다.
- [ ] T020 [US1] MediaCodec/MediaMuxer video 출력과 encoder·muxer 오류 전달을 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/VideoEncoder.kt`에 구현한다.
- [ ] T021 [US1] `frame_number,timestamp_ns,timestamp_source` CSV와 S10의 실제 non-null camera metadata를 쓰는 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeMetadataWriter.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriter.kt`를 구현한다.
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

**Independent Test**: 정상 완료 episode 한 건을 만든 후 목록에서 다섯 표시 필드와 `LOCAL_ONLY`를 확인하고, 삭제 확인 후 해당 bundle과 목록 항목만 사라지는지 확인한다.

### Tests for User Story 2

- [ ] T031 [P] [US2] completed episode만 정렬·표시하고 `LOCAL_ONLY`를 유지하는 repository 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepositoryTest.kt`를 작성한다.
- [ ] T032 [P] [US2] 앱 전용 completed root 안의 episode bundle만 개별 삭제하는 규칙을 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/EpisodeDeletionTest.kt`를 작성한다.
- [ ] T033 [P] [US2] 목록 항목의 task·object·시각·길이·sync state와 삭제 확인 상태를 단위 테스트하는 `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModelTest.kt`를 작성한다.

### Implementation for User Story 2

- [ ] T034 [US2] completed catalog을 목록 표시 모델로 변환하고 확인 후 단일 bundle을 안전하게 삭제하는 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListViewModel.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`를 구현한다.
- [ ] T035 [US2] 완료 episode 목록·필수 다섯 필드·개별 삭제 확인 UI를 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`에 구현하고 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 연결한다.

**Checkpoint**: 사용자는 서버 없이 completed episode를 식별하고 필요한 bundle 하나만 삭제한다.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 검증, 회귀 방지, 실제 기기 수동 검증을 마무리한다.

- [ ] T036 [P] recording/list 화면의 화면 상태와 오류 메시지를 `app/src/main/res/values/strings.xml` 기준으로 점검하고 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/RecordingScreen.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/EpisodeListScreen.kt`를 정리한다.
- [ ] T037 `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug`, `.\gradlew.bat assembleDebug`를 실행하고 결과를 `specs/001-episode-recorder/quickstart.md`에 기록한다.
- [ ] T038 Galaxy S10 SM-G973N에서 `specs/001-episode-recorder/quickstart.md`의 정상 수집·중단·episode 삭제·CaptureLog 전체 삭제 흐름을 수동 검증하고 결과를 기록한다.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 즉시 시작 가능. T001은 명세에 따라 사용자 승인이 선행된다.
- **Foundational (Phase 2)**: Setup 이후. 모든 사용자 스토리를 막는다.
- **US1 (Phase 3)**: Foundational 이후. 정상 녹화 MVP다.
- **US3 (Phase 4)**: US1의 recorder lifecycle 이후. 중단과 CaptureLog를 연결한다.
- **US2 (Phase 5)**: Foundational의 catalog 이후 시작 가능하나, 실제 데이터 검증을 위해 US1 이후 수행한다.
- **Polish (Phase 6)**: 원하는 사용자 스토리 완료 후 수행한다.

### Parallel Opportunities

- Phase 1의 T002, T003은 T001과 병렬 가능하다.
- Phase 2의 T004–T006, T012, T013은 서로 다른 파일이므로 병렬 가능하다. T007 이후 T008–T011을 진행한다.
- US1의 T015, T016, T017은 서로 병렬 가능하다. T018과 T019는 각자의 writer/preflight가 준비된 후 병렬 가능하다.
- US3의 T025와 T026, US2의 T031–T033, Polish의 T036은 병렬 가능하다.

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
3. Galaxy S10에서 여섯 파일 bundle과 `LOCAL_ONLY` 상태를 수동 검증한다.
4. 이어서 US3 중단 격리, US2 목록·삭제를 구현하고 각각 검증한다.

### Incremental Delivery

1. US1: 정상 수집과 완결 bundle
2. US3: 감지 가능한 실패 격리와 CaptureLog 전체 삭제
3. US2: completed episode 목록과 개별 삭제
4. Polish: 자동 검증 및 실기기 검증

## Notes

- `[P]`는 서로 다른 파일이며 선행 작업이 끝난 뒤 병렬로 수행할 수 있는 작업이다.
- 서버 API, 인증, 전송, 서버 검증, UploadClient는 MVP에 포함하지 않는다.
- 앱은 명시적으로 감지 가능한 Camera/encoder 실패를 중단 처리하고, 성공 Camera capture의 frame number·timestamp·source를 원본대로 보존한다.
