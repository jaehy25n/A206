# 작업 목록: Session/Episode 분리와 Tracking 유효성 게이트

**입력**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**테스트 원칙**: 상태 전이, frame index 생성, 메타데이터 직렬화는 외부 환경 없이 결정론적으로 검증 가능하므로 구현 전에 자동 테스트를 작성한다. 실제 카메라·ARCore 동작과 산출 데이터 대조는 별도 실기기 작업으로 남기며, 단위 테스트 성공을 실기기 검증으로 보고하지 않는다.

**형식**: `[ID] [P?] [Story] 설명` — `[P]`는 다른 파일을 건드려 병렬 가능함을 뜻한다.

---

## 선행 확인: 001·002 작업 목록 정합화

이번 기능은 기존에 완료로 표시된 범위가 실제로는 production 호출 경로에 연결되지 않은 상태를 연결한다. `specs/AGENTS.md`의 완료 판정 규칙에 따라 그 사실을 먼저 기록한다.

**001 `tasks.md`** — T007, T008, T009는 `CaptureSessionCoordinator`에 frame timestamp writer, READY gate, tracking loss interruption을 "구현·테스트했다"고 `[X]`로 표시되어 있다. 구현과 단위 테스트는 실재하지만, 이 클래스는 테스트에서만 인스턴스화되며 `MainActivity`와 `AndroidCaptureRuntime` 어디에서도 참조되지 않는다. 즉 `미연결`이다. 완료 이력을 지우지 않고 **연결 task로 세분화**하는 방식으로 정합화하며, 그 연결 task가 아래 T008·T009·T012~T016이다.

**002 `tasks.md`** — T021은 대상 파일에 `CaptureSessionCoordinator.kt`를 열거하지만, 같은 task의 증거 항목은 `finalizeCapture` → `AndroidCaptureRuntime.stop` → `startUpload` 경로를 기록하고 있다. 실제 구현은 Coordinator를 거치지 않는다. T021이 요구한 **동작**(정지가 열린 Episode를 완료하고 finalize 뒤 자동 업로드)은 충족되어 있으므로 완료 판정 자체는 유지하되, 파일 목록의 사실관계는 T029에서 바로잡는다.

---

## Phase 1: 준비

**목적**: 기준 브랜치와 현재 동작을 확인하고, 회귀 판단의 기준선을 만든다.

- [ ] T001 `git fetch origin develop` 후 `git merge-base origin/develop HEAD`로 기준점을 확인하고, `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 현재 production 호출 경로를 작업 기록에 정리한다.
- [ ] T002 `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug`를 실행해 변경 전 기준선을 기록한다.

---

## Phase 2: 공통 기반 (선행 필수)

**목적**: 상태 어휘와 사건 전파 경로를 확정한다. US1과 US2가 이 단계에 의존한다.

**⚠️ 중요**: T003~T006이 끝나기 전에 US1·US2 구현을 시작하지 않는다. US3·US4·US5는 이 단계와 무관하게 병행할 수 있다.

- [ ] T003 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`에 다섯 상태(`Idle`, `Initializing`, `Ready`, `EpisodeActive`, `Finalizing`)별 재생·일시 정지·정지 활성화와 이탈 동작의 실패 테스트를 [contracts/capture-state-machine.md](contracts/capture-state-machine.md)의 표대로 추가한다.
- [ ] T004 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureControlPolicy.kt`의 `CaptureWorkspaceControlState`를 `Idle`·`Initializing`·`Ready`·`EpisodeActive`·`Finalizing`으로 재정의하고, `CaptureControlPolicy`의 `canPlay`·`canPause`·`canStop`·`exitAction`을 새 상태에 맞게 구현한다. 기존 `Ready`는 `Idle`로, `SessionActive`는 `Ready`로 옮긴다.
- [ ] T005 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`의 `CaptureWorkspaceControls`가 `Initializing`을 포함한 다섯 상태를 렌더링하게 하고, `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 상태 계산과 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateScreenTest.kt`를 새 이름으로 갱신한다.
- [ ] T006 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 `onEpisodeClosed: (EpisodeMarker) -> Unit` 생성자 콜백을 추가하고, `endEpisode()`와 `onTracking()`의 `INVALID_TRACKING` 자동 마감이 모두 이 콜백을 통해 Episode를 확정하게 한다. 기존 `onInterrupted` 콜백과 같은 방식을 따른다.

**검증 지점**: 다섯 상태의 제어 규칙이 테스트로 고정되고, Episode 마감 사건이 단일 출구를 갖는다. 이 시점에는 `Initializing`으로 진입하는 경로가 없어 사용자 관점 동작은 기존과 같다.

---

## Phase 3: 사용자 스토리 1 - Session과 Episode를 따로 시작한다 (우선순위: P1) 🎯 MVP

**목표**: Session START가 Episode를 시작시키지 않고, 한 Session 안에서 Episode를 반복 수집한 뒤 Session을 마감할 수 있다.

**독립 테스트**: Session 시작 → `READY` 확인 → Episode 시작·종료 2회 → Session 종료. `episodes.csv`에 Episode 2개가 있고 두 시작 시각이 Session 시작 시각보다 늦으며, Camera / IMU / ARCore 기록이 Session 전체를 연속으로 덮는다.

### 테스트

- [ ] T007 [P] [US1] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 Session 시작이 Episode를 생성하지 않는다는 것, Episode 종료 후 Session이 유지된다는 것, Episode 시작·종료를 3회 반복할 수 있다는 것, Episode가 진행 중이면 `finalizeSession()`이 거부된다는 것의 실패 테스트를 추가한다.

### 구현

- [ ] T008 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 Session 시작 경로에서 `EpisodeMarker` 자동 생성을 제거하고, Session 시작 시 화면 상태가 `Initializing`이 되게 한다. 재생 버튼은 `Idle`에서 Session START, `Ready`에서 Episode START로 분기하고 `Initializing`에서는 비활성화한다.
- [ ] T009 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`가 `CaptureSessionCoordinator`를 Session·Episode 상태의 단일 판단 주체로 사용하게 연결한다. 기존 `collecting`·`active` 지역 상태를 Coordinator의 `session`·`activeEpisode`로 대체하고, `MonotonicClock`은 `SystemClock.elapsedRealtimeNanos()`를 사용한다.
- [ ] T010 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에서 T006의 `onEpisodeClosed` 콜백이 Episode를 Room과 `episodes.csv`에 기록하게 하고(`repository.save`, `captureRuntime.appendEpisode`), Episode 시작 시점의 task/object 값을 해당 Episode에 복사한다.
- [ ] T011 [US1] `app/src/main/res/values/strings.xml`에 `INITIALIZING`·`READY`·`EPISODE ACTIVE` 상태 표시 문구를 추가하고, Episode가 진행 중일 때 Session 종료를 거부하는 안내 문구를 추가한다. 기존 `capture_ready`·`capture_idle` 문구와 중복되지 않게 정리한다.

**검증 지점**: 재생을 눌러도 Episode가 자동 시작되지 않고, 한 Session에서 Episode를 반복할 수 있으며, Episode 진행 중 Session 종료가 차단된다.

---

## Phase 4: 사용자 스토리 2 - Tracking이 불안정한 구간을 구분한다 (우선순위: P1)

**목표**: Tracking 안정화 전 Episode 시작이 차단되고, 수행 중 유실이 0.5초 이상 지속되면 해당 Episode가 `INVALID_TRACKING`으로 마감되며, 회복 후 다음 Episode를 이어서 수집할 수 있다.

**독립 테스트**: 렌즈를 가린 채 Session을 시작해 재생이 비활성인지 확인하고, `READY` 후 Episode 수행 중 렌즈를 0.3초와 2초 가려 각각 Episode 유지와 `INVALID_TRACKING` 마감을 확인한다.

**의존**: Phase 2(T006)와 Phase 3(T009). Coordinator가 화면 상태의 주체가 되어 있어야 한다.

### 테스트

- [ ] T012 [P] [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 가상 시계로 다음을 검증하는 실패 테스트를 추가한다. 1초 미만 안정화에서는 `Ready`가 되지 않는다, `Ready`가 아니면 `startEpisode()`가 거부된다, 0.5초 미만 유실 후 회복 시 Episode가 `ACTIVE`로 유지된다, 0.5초 이상 유실 시 `INVALID_TRACKING`으로 마감되고 `end_timestamp_ns`가 유실 시작 + 0.5초다, 자동 마감 후 `endEpisode()`가 중복 마감하지 않는다, 회복 후 1초 안정화로 다시 `Ready`가 된다.
- [ ] T013 [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 **Tracking 값이 `false`로 고정된 채 `onTracking()`이 반복 호출되어야 0.5초 마감이 발화한다**는 것을 명시적으로 검증하는 테스트를 추가한다. 값 변화 시 1회만 호출하는 구현이 이 테스트에서 실패해야 한다([research.md](research.md) 결정 1).

### 구현

- [ ] T014 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 pose 수집 스레드가 ARCore `camera.trackingState == TRACKING` 여부를 `StateFlow<Boolean>`로 노출하게 한다. `arcore_poses.csv`의 기록 형식은 변경하지 않는다.
- [ ] T015 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 Session 수집 중에만 도는 100ms 주기 ticker를 추가해, T014의 최신 값을 main 스레드에서 `CaptureSessionCoordinator.onTracking()`에 반복 전달한다. Coordinator 호출은 전부 main 스레드에서 수행한다.
- [ ] T016 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 화면 상태 계산이 Coordinator의 `trackingState`를 반영해 `Initializing` ↔ `Ready`를 전환하게 하고, `Initializing`에서 재생이 비활성인 이유를 화면에 표시한다.
- [ ] T017 [US2] `app/src/main/res/values/strings.xml`에 Tracking 준비 중이라 Episode를 시작할 수 없다는 안내 문구와, Episode가 Tracking 유실로 마감되었음을 알리는 문구를 추가한다.

**검증 지점**: Tracking 안정화 전 Episode가 시작되지 않고, 유실 지속 시 Episode만 무효로 마감되며 Session 수집은 계속된다.

---

## Phase 5: 사용자 스토리 3 - 영상 frame과 timestamp를 대응시킨다 (우선순위: P1)

**목표**: `main_frame_timestamps.csv`의 `frame_number`가 0부터 1씩 증가하는 순차 frame index가 된다.

**독립 테스트**: Session을 하나 수집하고 `main_frame_timestamps.csv`의 `frame_number`가 0부터 결번 없이 증가하는지, `timestamp_ns`가 단조 증가하는지 확인한다.

**의존**: 없음. Phase 2~4와 병행할 수 있다.

### 테스트

- [ ] T018 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriterTest.kt`를 새로 만들어 다음을 검증하는 실패 테스트를 추가한다. 첫 행의 `frame_number`가 0이다, 이후 1씩 증가한다, 헤더가 `frame_number,timestamp_ns,timestamp_source`로 유지된다, **동일 타임스탬프가 중복 입력되어도 행과 카운터가 1회만 증가한다**([research.md](research.md) 결정 5).

### 구현

- [ ] T019 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 `onCaptureCompleted`에서 CSV 행을 직접 문자열로 쓰는 대신, 카메라 핸들러 스레드 전용 카운터로 `frame_number`를 0부터 증가시켜 기록한다. 기존 `timestampNs != lastFrameTimestampNs` 중복 제거를 유지하고, **중복 제거를 통과한 행에 대해서만** 카운터를 증가시킨다.
- [ ] T020 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`의 기존 `FrameTimestampWriter`를 T019의 기록 경로에 사용하거나, 사용하지 않기로 결정했다면 그 판단 근거를 이 task 기록에 남긴다. 미사용 코드를 방치하지 않는다.

**검증 지점**: 수집된 번들의 `frame_number`가 순차 정수열이며 헤더가 변하지 않았다.

---

## Phase 6: 사용자 스토리 4 - Camera Intrinsic을 Session과 함께 받는다 (우선순위: P2)

**목표**: `metadata.json`에 촬영에 사용된 Camera의 ID·해상도·Intrinsic이 기록된다.

**독립 테스트**: Session을 하나 수집하고 `metadata.json`에 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 모두 있으며 해상도가 MP4와 일치하는지 확인한다.

**의존**: 없음. Phase 2~5와 병행할 수 있다.

### 테스트

- [ ] T021 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizerTest.kt`를 새로 만들어 다음을 검증하는 실패 테스트를 추가한다. `camera` 객체가 [contracts/session-metadata.md](contracts/session-metadata.md)의 키 이름으로 직렬화된다, 선택 필드가 `null`이면 키가 생략된다, `session_id`·`camera_streams`·`files` 세 키가 보존되어 `SessionBundleValidator.validate`가 통과한다, **Camera Metadata가 없어도 finalize가 `Completed`를 반환한다**.

### 구현

- [ ] T022 [P] [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 [data-model.md](data-model.md)의 `CameraMetadata` 타입을 추가한다. 필수 7개 필드와 선택 4개 필드(`focalLengthMm`, `sensorWidthMm`, `sensorHeightMm`, `distortionCoefficients`)를 구분하고 선택 필드는 nullable로 둔다.
- [ ] T023 [P] [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraMetadataReader.kt`를 새로 만들어 `CameraCharacteristics`에서 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS`, `SENSOR_INFO_PHYSICAL_SIZE`, `LENS_DISTORTION`을 읽는다. 각 값은 미제공 시 `null`을 반환하고 예외를 던지지 않는다. `CameraCapabilityPreflight`의 Galaxy S10 프로파일 판정 로직은 사용하지 않는다.
- [ ] T024 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 pose 수집 스레드가 첫 유효 프레임에서 `frame.camera.imageIntrinsics`의 `focalLength`·`principalPoint`·`imageDimensions`를 1회 획득하고, `session.cameraConfig.cameraId`와 T023의 Camera2 값을 합쳐 `CameraMetadata`를 구성해 보관한다. 획득 전체를 `runCatching`으로 감싸 실패 시 `null`로 둔다.
- [ ] T025 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizer.kt`의 `finalize()`가 `CameraMetadata?`를 선택 인자로 받아 `metadata.json`에 `camera` 객체로 기록하게 한다. `null`이면 키를 생략하고 Session 마감을 계속 진행한다. 기존 `session_id`·`camera_streams`·`files` 생성 로직은 변경하지 않는다.
- [ ] T026 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 `stop()`이 T024에서 보관한 `CameraMetadata`를 `SessionFinalizer.finalize()`에 전달하게 한다.

**검증 지점**: `metadata.json`에 `camera` 객체가 기록되고, 획득 실패 시에도 Session 마감이 완료된다.

---

## Phase 7: 사용자 스토리 5 - Timestamp 기록 구간을 녹화 구간에 맞춘다 (우선순위: P3)

**목표**: 영상 녹화가 진행 중이지 않은 구간의 Camera Timestamp가 기록되지 않는다.

**독립 테스트**: Session을 하나 수집하고 `main_frame_timestamps.csv` 행 수와 MP4 frame 수의 차이가 2 이하인지 확인한다.

**의존**: Phase 5(T019). 같은 기록 경로를 수정한다.

### 테스트

- [ ] T027 [P] [US5] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriterTest.kt`에 녹화 구간 플래그가 꺼진 동안 들어온 입력이 기록되지 않고 카운터도 증가하지 않는다는 실패 테스트를 추가한다.

### 구현

- [ ] T028 [US5] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`에 `@Volatile` 녹화 구간 플래그를 추가해 `recorder.start()` 직후 활성화하고 `mediaRecorder.stop()` 직전에 비활성화한다. 플래그가 꺼진 동안 도착한 `CaptureResult`는 CSV에 기록하지 않는다. `onActive`와 `stop()`·`interrupt()` 세 경로를 모두 처리한다.

**검증 지점**: 녹화 시작 전과 종료 후의 Camera Timestamp가 CSV에 남지 않는다.

---

## Phase 8: 마무리와 검증

**목적**: 회귀를 막고, 자동화할 수 없는 acceptance criterion을 실기기에서 확인하며, 선행 기능의 작업 목록을 정합화한다.

- [ ] T029 [P] `specs/001-episode-recorder/tasks.md`의 T007·T008·T009와 `specs/002-capture-control-ux/tasks.md`의 T021에, 해당 범위가 본 기능의 T008~T010·T012~T016·T019에서 production 호출 경로에 연결됐다는 정합화 기록을 남긴다. 002 T021은 파일 목록에서 `CaptureSessionCoordinator.kt`가 실제 구현 경로가 아니었다는 사실을 함께 기록한다.
- [ ] T030 [P] `specs/003-session-episode-tracking-gate/quickstart.md`에 자동 검증 실행 결과(명령, 테스트명, 날짜)를 기록한다.
- [ ] T031 `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug`를 실행해 T002 기준선 대비 회귀가 없음을 확인한다.
- [ ] T032 연결된 실기기에서 `./gradlew.bat connectedDebugAndroidTest`를 실행해 Compose 제어 상태 검증을 통과시킨다.
- [ ] T033 실기기에서 [quickstart.md](quickstart.md) 시나리오 1(Session과 Episode 분리)을 수행하고, `episodes.csv`의 Episode 4개와 Session 전체를 덮는 연속 기록을 확인·기록한다. SC-001, SC-004에 대응한다.
- [ ] T034 실기기에서 [quickstart.md](quickstart.md) 시나리오 2(Tracking 게이트)를 수행하고, 렌즈 가림 0.3초·2초에 대한 Episode 유지와 `INVALID_TRACKING` 마감, `end_timestamp_ns`가 유실 시작 + 0.5초임을 `arcore_poses.csv`와 대조해 기록한다. SC-002, SC-003에 대응한다.
- [ ] T035 실기기 수집 번들로 [quickstart.md](quickstart.md) 시나리오 3을 수행하고, `frame_number`의 순차성과 `main_frame_timestamps.csv` 행 수 대비 MP4 frame 수 차이를 측정해 기록한다. 차이가 2를 넘으면 시작·종료 경계에 몰려 있는지 중간 구간에 흩어져 있는지 구분해 기록한다. SC-005, SC-009에 대응한다.
- [ ] T036 실기기 수집 번들로 [quickstart.md](quickstart.md) 시나리오 4를 수행하고, `metadata.json`의 `camera` 객체 존재와 해상도가 MP4와 일치함을 확인·기록한다. SC-006, SC-007에 대응한다.
- [ ] T037 실기기 수집 Session을 기존 경로로 EC2에 업로드해 수신 측 수정 없이 성공함을 확인·기록한다. SC-008에 대응한다.
- [ ] T038 [quickstart.md](quickstart.md)의 회귀 확인 항목(SharedCamera 기반 Main RGB 녹화, Session 목록·상세·업로드 상태 화면, SAF export, `arcore_poses.csv` 형식 불변)을 실기기에서 확인·기록한다.

---

## 의존 관계와 실행 순서

### Phase 의존

- **Phase 1(준비)**: 의존 없음
- **Phase 2(공통 기반)**: Phase 1 이후. US1·US2를 차단한다
- **Phase 3(US1)**: Phase 2 이후
- **Phase 4(US2)**: Phase 3(T009) 이후. Coordinator가 화면 상태의 주체여야 한다
- **Phase 5(US3)**, **Phase 6(US4)**: Phase 1 이후 즉시 시작 가능. Phase 2~4와 독립
- **Phase 7(US5)**: Phase 5(T019) 이후
- **Phase 8(마무리)**: 위 전체 완료 후

### 사용자 스토리 의존

- **US1(P1)**: Phase 2 필요. 다른 스토리에 의존하지 않는다
- **US2(P1)**: US1에 의존한다. Tracking 게이트가 Session/Episode 분리 위에 놓인다
- **US3(P1)**: 완전 독립. 단독으로 배포 가능
- **US4(P2)**: 완전 독립. 단독으로 배포 가능
- **US5(P3)**: US3에 의존한다

### 병렬 기회

- T003과 T007, T012, T018, T021, T027은 서로 다른 테스트 파일이라 병렬 가능하다
- T022와 T023은 서로 다른 파일이라 병렬 가능하다
- US3(Phase 5)와 US4(Phase 6)는 Phase 2~4와 다른 파일 영역을 주로 건드리므로 다른 담당자가 병행할 수 있다. 다만 T019·T024·T028이 모두 `AndroidCaptureRuntime.kt`를 수정하므로 이 셋은 순차 처리한다
- T029, T030은 문서 작업이라 병렬 가능하다

### 같은 파일을 건드리는 task (순차 필수)

- `AndroidCaptureRuntime.kt`: T014 → T019 → T024 → T026 → T028
- `MainActivity.kt`: T005 → T008 → T009 → T010 → T015 → T016
- `strings.xml`: T011 → T017
- `CaptureSessionCoordinatorTest.kt`: T007 → T012 → T013

---

## 구현 전략

### MVP (US1 + US2)

명세의 P1 중 US1과 US2는 함께 나가야 의미가 있다. Episode 경계가 사용자 조작으로 그어져야 Tracking 유효성을 Episode 단위로 판정할 수 있기 때문이다.

1. Phase 1 준비
2. Phase 2 공통 기반
3. Phase 3 US1 → **중단하고 검증**: Session/Episode 분리가 단독 동작하는지 확인
4. Phase 4 US2 → **중단하고 검증**: T034 실기기 시나리오
5. 여기까지가 수신 측이 지적한 결함의 핵심이다

### 증분 배포

1. US3(Phase 5)는 언제든 단독으로 먼저 끝낼 수 있다. 변경량이 가장 작고 수신 측 파이프라인 영향이 가장 크므로, 여력이 있으면 US1보다 먼저 처리해도 좋다
2. US4(Phase 6)도 독립이며 US1·US2와 병행 가능하다
3. US5(Phase 7)는 US3 직후에 붙인다
4. Phase 8은 배포 단위마다 해당 시나리오만 수행하고, 전체 완료 시 T031·T038을 다시 실행한다

### 완료 판정

`specs/AGENTS.md`에 따라 각 task를 `[X]`로 바꾸기 전에 변경 파일과 production 호출 경로, 테스트명과 실행 결과를 해당 task 아래에 기록한다. 실기기 검증(T032~T038)이 남아 있는 한 그 시나리오가 덮는 스토리를 완료로 보고하지 않는다. 모든 task 완료 후 완료 보고·commit·push 전에 `$speckit-converge`를 실행한다.

---

## 참고

- `[P]`는 다른 파일을 건드려 병렬 가능함을 뜻한다
- 상태 이름 재정의(T004)는 되돌리기 어려우므로, 기존 테스트 갱신(T003, T005)과 같은 커밋으로 처리한다
- T013과 T018의 "중복 입력" 테스트는 [research.md](research.md)에서 특정한 두 함정에 직접 대응한다. 이 둘을 생략하면 구현이 단위 테스트를 통과하면서 실기기에서 실패하거나 결함이 악화된다
