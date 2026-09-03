---
description: "Capture Session Recorder MVP 구현 작업"
---

# Tasks: Capture Session Recorder MVP

**Input**: `specs/001-episode-recorder/`의 spec, plan, contracts
**Prerequisites**: `spec.md`, `plan.md`, `contracts/episode-bundle.md`, `contracts/episode-upload.md`

## Phase 1: Session domain과 로컬 bundle 기반

- [X] T001 `CaptureSession`, `EpisodeMarker`, recording/upload state, tracking state, probe result 모델과 전이 규칙을 구현하고 테스트한다.
- [X] T002 Session ID/display number, staging/completed directory, Session raw file 경로와 metadata-last commit을 관리하는 store를 구현한다.
- [X] T003 main-only/UW file 구성, CSV header, marker row, SHA-256 manifest, metadata stream 선언을 검사하는 validator와 테스트를 구현한다.
- [X] T004 기존 episode catalog를 Session catalog와 child Episode marker catalog로 바꾸고 interrupted staging recovery를 구현한다.

## Phase 2: P1 연속 수집

- [X] T005 REALTIME timestamp source와 저장 공간 preflight를 구현하고 시작 불가 상태를 UI에 연결한다.
- [X] T006 Session start/end가 main camera recording, raw accelerometer·gyroscope·rotation-vector writer, ARCore pose writer를 각각 한 번만 시작·종료하도록 coordinator를 구현한다.
- [X] T007 main frame timestamp와 ARCore pose CSV writer를 구현해 canonical Android camera timestamp와 tracking failure reason을 보존한다.
- [X] T008 tracking 1초 READY gate, task와 object가 모두 비어 있지 않을 때만 허용되는 Episode marker START/END/CANCEL, metadata snapshot, Episode 사이 raw stream 유지 규칙을 구현하고 테스트한다.
- [X] T009 0.5초 tracking loss 시 임계 timestamp로 `INVALID_TRACKING` Episode를 자동 종료하고, `onStop`·Camera·encoder·IMU·storage 오류 시 writers를 안전하게 finalize한 뒤 Session을 `INTERRUPTED`로 기록하는 로직과 structured diagnostics를 구현·테스트한다.

## Phase 3: P1 finalize와 업로드

- [X] T010 Session finalize 순서, file validation, checksum, metadata-last commit, completed/LOCAL_ONLY 공개를 구현하고 테스트한다.
- [X] T011 Session metadata와 main-only CSV schema를 `contracts/episode-bundle.md`에 맞게 직렬화하는 writer와 테스트를 구현한다.
- [X] T012 Session bundle pre-upload validator와 `POST /sessions` multipart request factory를 구현하고, `Authorization`·cookie·custom credential header 없이 `Idempotency-Key = session_id`만 전송되는 contract test를 작성한다.
- [X] T013 receipt/transport error를 `UPLOADED` 또는 `FAILED`로 기록하고 same-session manual retry를 구현·테스트한다.

## Phase 4: P1 UI와 P2 Ultra-wide probe

- [ ] T014 DATA COLLECTION START/END, ARCore·Camera·IMU·Episode 상태, Episode metadata 입력, ACTIVE 제어와 finalization/upload 상태 UI를 구현한다. ACTIVE Episode 중에는 DATA COLLECTION END를 차단하고 Episode END 또는 CANCEL을 먼저 안내하는 UI·테스트를 포함한다.
- [ ] T015 main-only baseline이 안정된 뒤 camera topology·ARCore camera ID를 기록하고, 10~30분 timebox 안에 low-rate Ultra-wide probe의 `UW_SUPPORTED` 또는 `UW_UNSUPPORTED_FOR_MVP` 결론을 기록하는 debug flow를 구현한다. probe 실패 시 추가 UW 디버깅 없이 main-only MVP를 계속한다.
- [ ] T016 UW_SUPPORTED일 때만 UW writers, files, metadata declaration, upload parts를 추가하고 contract consistency test를 작성한다.

## Phase 5: 검증

- [ ] T017 `./gradlew.bat testDebugUnitTest`, `./gradlew.bat lintDebug`, `./gradlew.bat assembleDebug`를 실행하고 결과를 quickstart에 기록한다.
- [ ] T018 Galaxy S10에서 main-only 2분 Session, Episode idle/reposition, tracking loss, interrupted recovery, upload retry를 수동 검증하고 결과를 기록한다. UW probe를 수행하면 10~30분 timebox 내 supported/unsupported 판정과 실패 시 main-only fallback 여부를 함께 기록한다.

## 의존성 순서

`T001–T004 → T005–T009 → T010–T014 → T015–T016 → T017–T018`

Ultra-wide 작업은 main-only baseline과 P1 verification이 통과한 뒤에만 시작한다.
