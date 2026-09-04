---
description: "Capture Session Recorder MVP and SAF export task ledger"
---

# Tasks: Capture Session Recorder MVP — SAF Export

**Input**: `specs/001-episode-recorder/`의 `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/episode-bundle.md`, `quickstart.md`

**Tests**: export 구현 전 unit test를 작성한다. `connectedDebugAndroidTest`는 연결된 기기 또는 emulator가 있을 때만 실행하며, SAF provider behavior는 Galaxy S10 실기기 검증이 필요하다.

## Historical Baseline: 완료된 Capture Session 기능

**Purpose**: 전체 명세의 FR-001–018 및 SC-001–008 추적을 보존한다. T001–T017은 기존 구현·자동 검증 완료 기록이며, T018은 아직 실기기 검증이 필요하다.

- [X] T001 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 CaptureSession·EpisodeMarker·recording/upload state와 전이 규칙을 구현·테스트했다.
- [X] T002 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`에 staging/completed bundle store와 metadata-last publish를 구현·테스트했다.
- [X] T003 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidator.kt`에 main-only/UW file 구성·CSV header·manifest 검사를 구현·테스트했다.
- [X] T004 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`에 Session catalog·Episode marker와 interrupted staging recovery를 구현했다.
- [X] T005 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 REALTIME timestamp와 storage preflight를 구현·테스트했다.
- [X] T006 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 continuous camera·IMU·pose writer lifecycle을 구현·테스트했다.
- [X] T007 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 frame timestamp와 ARCore pose CSV writer를 구현·테스트했다.
- [X] T008 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 READY gate와 Episode marker lifecycle을 구현·테스트했다.
- [X] T009 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 tracking loss·onStop·writer 오류 interruption을 구현·테스트했다.
- [X] T010 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizer.kt`에 finalize·checksum·metadata-last·completed publish를 구현·테스트했다.
- [X] T011 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizer.kt`에 Session metadata와 CSV serialization을 구현·테스트했다.
- [X] T012 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadClient.kt`에 bundle pre-upload validator와 multipart request를 구현·테스트했다.
- [X] T013 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadClient.kt`에 upload receipt/error와 same-session retry를 구현·테스트했다.
- [X] T014 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 Capture Session·Episode control UI를 구현·테스트했다.
- [X] T015 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/UltraWideProbe.kt`에 Ultra-wide probe/main-only fallback을 구현했다.
- [X] T016 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/UltraWideProbe.kt`에 UW metadata/file/upload consistency를 구현·테스트했다.
- [X] T017 `specs/001-episode-recorder/quickstart.md`에 unit test·lint·assemble 결과를 기록했다.
- [ ] T018 `specs/001-episode-recorder/quickstart.md`에 따라 Galaxy S10 main-only capture, tracking loss, interrupted recovery, upload retry, UW probe를 수동 검증한다.

---

## Phase 1: 승인과 SAF 경계

**Purpose**: schema-change gate와 provider capability 정책을 확정한다.

- [X] T019 `specs/001-episode-recorder/plan.md`의 Room schema migration 승인 gate를 사용자에게 받고, 승인 결과를 구현 시작 기록에 남겼다 (2026-09-03).
- [X] T020 `app/src/main/AndroidManifest.xml`과 `app/build.gradle.kts`를 점검해 broad storage permission·새 dependency를 추가하지 않는 export 경계를 확인했다 (broad storage permission 및 새 dependency 없음).

**Checkpoint**: T019 승인 기록이 완료되어 T030의 Room schema 변경 작업을 시작할 수 있다.

---

## Phase 2: 기반 계약과 source bundle

**Purpose**: completed source만 export 후보가 되고, source/destination exact-bundle 검사 기준이 하나가 되게 한다.

- [X] T021 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleStoreTest.kt`에서 `capture/staging/<session_id>/`, completed publish path, metadata-last 전 export 차단을 먼저 실패하는 테스트로 작성했다.
- [X] T022 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleValidatorTest.kt`에 필수 파일·CSV header·metadata stream declaration·manifest size/SHA-256·unexpected document mismatch 거부 테스트를 추가했다.
- [X] T023 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`에서 app-specific external-files root와 session-id staging directory 계약을 구현하고 T021을 통과시켰다.
- [X] T024 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidator.kt` 및 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizer.kt`에서 metadata-last source validator와 exact manifest/metadata 일치 검증을 구현하고 T022를 통과시켰다.

**Checkpoint**: metadata commit marker와 exact manifest를 가진 completed source만 export service에 전달할 수 있다.

---

## Phase 3: User Story 3 — 완료 Session을 사용자 선택 tree에 export (Priority: P1) 🎯 MVP

**Goal**: completed bundle을 Documents에서 시작한 SAF picker의 selected tree에 새 임시 attempt directory로 copy·검증하고, 성공한 attempt만 `TigerCapture/<session_id>/`로 publish한다.

**Independent Test**: valid completed fixture가 fake document tree의 unique attempt directory에서 검증된 뒤 `EXPORTED`가 된다. invalid source, unexpected document, capability/grant/copy/publish failure는 `EXPORT_FAILED`이며 app-private source는 보존된다.

### Tests for User Story 3

- [X] T025 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionExportModelsTest.kt`에서 `NOT_EXPORTED → EXPORTING → EXPORTED`와 `EXPORTING → EXPORT_FAILED → EXPORTING` 전이, recording/upload state 독립성, unique attempt ID를 먼저 테스트했다.
- [X] T026 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionExportRepositoryTest.kt`에서 export state·tree URI·failure reason의 repository round-trip과 migration contract를 테스트했다.
- [X] T027 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleExporterTest.kt`에서 fake `DocumentTreeGateway`로 attempt copy, metadata-last, exact destination validation, overwrite publish, source preservation, new-attempt retry를 테스트했다.
- [X] T028 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/DocumentTreeGatewayTest.kt`에서 persisted grant loss와 provider capability 부족을 테스트하고 tree-boundary escape 거부를 exporter test로 검증했다.

### Implementation for User Story 3

- [X] T029 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 `ExportState`, `SessionExport`, `attemptId`를 추가하고 T025를 통과시켰다.
- [X] T030 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`에 export state·last tree URI·failure reason 영속화와 migration을 추가하고 T026을 통과시켰다.
- [X] T031 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeRepository.kt`에 export state update와 immutable completed source 조회 API를 구현하고 T026을 통과시켰다.
- [X] T032 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/DocumentTreeGateway.kt`를 추가해 persistable URI grant, tree-boundary 및 provider capability inspection을 구현하고 T028을 통과시켰다.
- [X] T033 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleExporter.kt`를 추가해 new attempt directory copy, metadata-last, exact destination validation, overwrite publish, failure reason·new-attempt retry와 source preservation을 구현하고 T027을 통과시켰다.
- [X] T034 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`와 `app/src/main/res/values/strings.xml`에 tree selection, `EXPORTING`/`EXPORT_FAILED`/`EXPORTED`, Retry UI를 연결했다.
- [X] T035 [US3] `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/SessionExportUiTest.kt`에서 export/retry control과 failure reason rendering을 instrumented test로 추가하고 APK 컴파일을 검증했다.

**Checkpoint**: User Story 3은 exact completed source를 안전한 attempt directory에서 validate한 뒤 publish하고, 자동 cleanup/resume 없이 재시도를 안내한다.

---

## Phase 4: 마무리와 실기기 검증

**Purpose**: 자동 품질 gate와 Galaxy S10에서만 가능한 SAF 동작을 완료한다.

- [ ] T036 `specs/001-episode-recorder/quickstart.md`에 맞춰 `./gradlew.bat testDebugUnitTest`, `./gradlew.bat lintDebug`, `./gradlew.bat assembleDebug`를 실행하고 결과를 기록한다.
- [ ] T037 `specs/001-episode-recorder/quickstart.md`의 Galaxy S10 시나리오로, 연결된 실제 기기에서 `./gradlew.bat connectedDebugAndroidTest`를 실행하고 Documents-start picker, Documents 밖 tree URI, persisted grant restart, grant loss, capability failure, cancel, provider I/O/공간 부족, attempt publish/retry, exported SHA-256을 수동 검증·기록한다.

---

## Dependencies & Execution Order

```text
T021–T024 → T025–T029
T019 → T030 → T031 → T032 → T033 → T034–T035 → T036–T037
T020 must pass before T032/T034.
T029 + T031 + T032 → T033
```

- T019은 Room schema migration만 차단하며 T021–T029을 막지 않는다.
- T021/T022와 T025–T028은 각각 parallel test authoring task다.
- T033은 domain model, repository, gateway가 모두 준비된 뒤 시작한다.
- T037은 T035와 T036 뒤에 Galaxy S10에서만 실행한다.

## Parallel Opportunities

```text
# Source foundation
T021 + T022

# Export tests after source foundation
T025 + T026 + T027 + T028
```

## Implementation Strategy

1. T019 승인과 병렬로 source path/validator 기반을 끝낸다.
2. export model과 tests를 완료한 뒤 migration·repository·gateway·exporter를 순서대로 구현한다.
3. attempt validation/publish/retry와 UI를 확인하고 build gate를 통과한다.
4. Galaxy S10에서 connected UI test와 SAF manual scenario를 수행한 뒤 완료 처리한다.
