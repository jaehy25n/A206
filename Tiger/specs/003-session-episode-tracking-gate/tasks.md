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

- [X] T001 `git fetch origin develop` 후 `git merge-base origin/develop HEAD`로 기준점을 확인하고, `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 현재 production 호출 경로를 작업 기록에 정리한다.
- [X] T002 `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug`를 실행해 변경 전 기준선을 기록한다.

---

## Phase 2: 공통 기반 (선행 필수)

**목적**: 상태 어휘와 사건 전파 경로를 확정한다. US1과 US2가 이 단계에 의존한다.

**⚠️ 중요**: T003~T006이 끝나기 전에 US1·US2 구현을 시작하지 않는다. US3·US4·US5는 이 단계와 무관하게 병행할 수 있다.

- [X] T003 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`에 다섯 상태(`Idle`, `Initializing`, `Ready`, `EpisodeActive`, `Finalizing`)별 재생·일시 정지·정지 활성화와 이탈 동작의 실패 테스트를 [contracts/capture-state-machine.md](contracts/capture-state-machine.md)의 표대로 추가한다.
- [X] T004 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureControlPolicy.kt`의 `CaptureWorkspaceControlState`를 `Idle`·`Initializing`·`Ready`·`EpisodeActive`·`Finalizing`으로 재정의하고, `CaptureControlPolicy`의 `canPlay`·`canPause`·`canStop`·`exitAction`을 새 상태에 맞게 구현한다. 기존 `Ready`는 `Idle`로, `SessionActive`는 `Ready`로 옮긴다.
- [X] T005 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`의 `CaptureWorkspaceControls`가 `Initializing`을 포함한 다섯 상태를 렌더링하게 하고, `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 상태 계산과 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateScreenTest.kt`를 새 이름으로 갱신한다.
- [X] T006 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 `onEpisodeClosed: (EpisodeMarker) -> Unit` 생성자 콜백을 추가하고, `endEpisode()`와 `onTracking()`의 `INVALID_TRACKING` 자동 마감이 모두 이 콜백을 통해 Episode를 확정하게 한다. 기존 `onInterrupted` 콜백과 같은 방식을 따른다.

**검증 지점**: 다섯 상태의 제어 규칙이 테스트로 고정되고, Episode 마감 사건이 단일 출구를 갖는다. 이 시점에는 `Initializing`으로 진입하는 경로가 없어 사용자 관점 동작은 기존과 같다.

---

## Phase 3: 사용자 스토리 1 - Session과 Episode를 따로 시작한다 (우선순위: P1) 🎯 MVP

**목표**: Session START가 Episode를 시작시키지 않고, 한 Session 안에서 Episode를 반복 수집한 뒤 Session을 마감할 수 있다.

**독립 테스트**: Session 시작 → `READY` 확인 → Episode 시작·종료 2회 → Session 종료. `episodes.csv`에 Episode 2개가 있고 두 시작 시각이 Session 시작 시각보다 늦으며, Camera / IMU / ARCore 기록이 Session 전체를 연속으로 덮는다.

### 테스트

- [X] T007 [P] [US1] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 Session 시작이 Episode를 생성하지 않는다는 것, Episode 종료 후 Session이 유지된다는 것, Episode 시작·종료를 3회 반복할 수 있다는 것, Episode가 진행 중이면 `finalizeSession()`이 거부된다는 것의 실패 테스트를 추가한다.

### 구현

- [X] T008 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 Session 시작 경로에서 `EpisodeMarker` 자동 생성을 제거하고, Session 시작 시 화면 상태가 `Initializing`이 되게 한다. 재생 버튼은 `Idle`에서 Session START, `Ready`에서 Episode START로 분기하고 `Initializing`에서는 비활성화한다.
- [X] T009 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`가 `CaptureSessionCoordinator`를 Session·Episode 상태의 단일 판단 주체로 사용하게 연결한다. 기존 `collecting`·`active` 지역 상태를 Coordinator의 `session`·`activeEpisode`로 대체하고, `MonotonicClock`은 `SystemClock.elapsedRealtimeNanos()`를 사용한다.
- [X] T010 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에서 T006의 `onEpisodeClosed` 콜백이 Episode를 Room과 `episodes.csv`에 기록하게 하고(`repository.save`, `captureRuntime.appendEpisode`), Episode 시작 시점의 task/object 값을 해당 Episode에 복사한다.
- [X] T011 [US1] `app/src/main/res/values/strings.xml`에 `INITIALIZING`·`READY`·`EPISODE ACTIVE` 상태 표시 문구를 추가하고, Episode가 진행 중일 때 Session 종료를 거부하는 안내 문구를 추가한다. 기존 `capture_ready`·`capture_idle` 문구와 중복되지 않게 정리한다.

**검증 지점**: 재생을 눌러도 Episode가 자동 시작되지 않고, 한 Session에서 Episode를 반복할 수 있으며, Episode 진행 중 Session 종료가 차단된다.

---

## Phase 4: 사용자 스토리 2 - Tracking이 불안정한 구간을 구분한다 (우선순위: P1)

**목표**: Tracking 안정화 전 Episode 시작이 차단되고, 수행 중 유실이 0.5초 이상 지속되면 해당 Episode가 `INVALID_TRACKING`으로 마감되며, 회복 후 다음 Episode를 이어서 수집할 수 있다.

**독립 테스트**: 렌즈를 가린 채 Session을 시작해 재생이 비활성인지 확인하고, `READY` 후 Episode 수행 중 렌즈를 0.3초와 2초 가려 각각 Episode 유지와 `INVALID_TRACKING` 마감을 확인한다.

**의존**: Phase 2(T006)와 Phase 3(T009). Coordinator가 화면 상태의 주체가 되어 있어야 한다.

### 테스트

- [X] T012 [P] [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 가상 시계로 다음을 검증하는 실패 테스트를 추가한다. 1초 미만 안정화에서는 `Ready`가 되지 않는다, `Ready`가 아니면 `startEpisode()`가 거부된다, 0.5초 미만 유실 후 회복 시 Episode가 `ACTIVE`로 유지된다, 0.5초 이상 유실 시 `INVALID_TRACKING`으로 마감되고 `end_timestamp_ns`가 유실 시작 + 0.5초다, 자동 마감 후 `endEpisode()`가 중복 마감하지 않는다, 회복 후 1초 안정화로 다시 `Ready`가 된다.
- [X] T013 [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 **Tracking 값이 `false`로 고정된 채 `onTracking()`이 반복 호출되어야 0.5초 마감이 발화한다**는 것을 명시적으로 검증하는 테스트를 추가한다. 값 변화 시 1회만 호출하는 구현이 이 테스트에서 실패해야 한다([research.md](research.md) 결정 1).

### 구현

- [X] T014 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 pose 수집 스레드가 ARCore `camera.trackingState == TRACKING` 여부를 `StateFlow<Boolean>`로 노출하게 한다. `arcore_poses.csv`의 기록 형식은 변경하지 않는다.
- [X] T015 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 Session 수집 중에만 도는 100ms 주기 ticker를 추가해, T014의 최신 값을 main 스레드에서 `CaptureSessionCoordinator.onTracking()`에 반복 전달한다. Coordinator 호출은 전부 main 스레드에서 수행한다.
- [X] T016 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 화면 상태 계산이 Coordinator의 `trackingState`를 반영해 `Initializing` ↔ `Ready`를 전환하게 하고, `Initializing`에서 재생이 비활성인 이유를 화면에 표시한다.
- [X] T017 [US2] `app/src/main/res/values/strings.xml`에 Tracking 준비 중이라 Episode를 시작할 수 없다는 안내 문구와, Episode가 Tracking 유실로 마감되었음을 알리는 문구를 추가한다.

**검증 지점**: Tracking 안정화 전 Episode가 시작되지 않고, 유실 지속 시 Episode만 무효로 마감되며 Session 수집은 계속된다.

---

## Phase 5: 사용자 스토리 3 - 영상 frame과 timestamp를 대응시킨다 (우선순위: P1)

**목표**: `main_frame_timestamps.csv`의 `frame_number`가 0부터 1씩 증가하는 순차 frame index가 된다.

**독립 테스트**: Session을 하나 수집하고 `main_frame_timestamps.csv`의 `frame_number`가 0부터 결번 없이 증가하는지, `timestamp_ns`가 단조 증가하는지 확인한다.

**의존**: 없음. Phase 2~4와 병행할 수 있다.

### 테스트

- [X] T018 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriterTest.kt`를 새로 만들어 다음을 검증하는 실패 테스트를 추가한다. 첫 행의 `frame_number`가 0이다, 이후 1씩 증가한다, 헤더가 `frame_number,timestamp_ns,timestamp_source`로 유지된다, **동일 타임스탬프가 중복 입력되어도 행과 카운터가 1회만 증가한다**([research.md](research.md) 결정 5).

### 구현

- [X] T019 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 `onCaptureCompleted`에서 CSV 행을 직접 문자열로 쓰는 대신, 카메라 핸들러 스레드 전용 카운터로 `frame_number`를 0부터 증가시켜 기록한다. 기존 `timestampNs != lastFrameTimestampNs` 중복 제거를 유지하고, **중복 제거를 통과한 행에 대해서만** 카운터를 증가시킨다.
- [X] T020 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`의 기존 `FrameTimestampWriter`를 T019의 기록 경로에 사용하거나, 사용하지 않기로 결정했다면 그 판단 근거를 이 task 기록에 남긴다. 미사용 코드를 방치하지 않는다.

**검증 지점**: 수집된 번들의 `frame_number`가 순차 정수열이며 헤더가 변하지 않았다.

---

## Phase 6: 사용자 스토리 4 - Camera Intrinsic을 Session과 함께 받는다 (우선순위: P2)

**목표**: `metadata.json`에 촬영에 사용된 Camera의 ID·해상도·Intrinsic이 기록된다.

**독립 테스트**: Session을 하나 수집하고 `metadata.json`에 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 모두 있으며 해상도가 MP4와 일치하는지 확인한다.

**의존**: 없음. Phase 2~5와 병행할 수 있다.

### 테스트

- [X] T021 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizerTest.kt`를 새로 만들어 다음을 검증하는 실패 테스트를 추가한다. `camera` 객체가 [contracts/session-metadata.md](contracts/session-metadata.md)의 키 이름으로 직렬화된다, 선택 필드가 `null`이면 키가 생략된다, `session_id`·`camera_streams`·`files` 세 키가 보존되어 `SessionBundleValidator.validate`가 통과한다, **Camera Metadata가 없어도 finalize가 `Completed`를 반환한다**.

### 구현

- [X] T022 [P] [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 [data-model.md](data-model.md)의 `CameraMetadata` 타입을 추가한다. 필수 7개 필드와 선택 4개 필드(`focalLengthMm`, `sensorWidthMm`, `sensorHeightMm`, `distortionCoefficients`)를 구분하고 선택 필드는 nullable로 둔다.
- [X] T023 [P] [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraMetadataReader.kt`를 새로 만들어 `CameraCharacteristics`에서 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS`, `SENSOR_INFO_PHYSICAL_SIZE`, `LENS_DISTORTION`을 읽는다. 각 값은 미제공 시 `null`을 반환하고 예외를 던지지 않는다. `CameraCapabilityPreflight`의 Galaxy S10 프로파일 판정 로직은 사용하지 않는다.
- [X] T024 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 pose 수집 스레드가 첫 유효 프레임에서 `frame.camera.imageIntrinsics`의 `focalLength`·`principalPoint`·`imageDimensions`를 1회 획득하고, `session.cameraConfig.cameraId`와 T023의 Camera2 값을 합쳐 `CameraMetadata`를 구성해 보관한다. 획득 전체를 `runCatching`으로 감싸 실패 시 `null`로 둔다.
- [X] T025 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionFinalizer.kt`의 `finalize()`가 `CameraMetadata?`를 선택 인자로 받아 `metadata.json`에 `camera` 객체로 기록하게 한다. `null`이면 키를 생략하고 Session 마감을 계속 진행한다. 기존 `session_id`·`camera_streams`·`files` 생성 로직은 변경하지 않는다.
- [X] T026 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 `stop()`이 T024에서 보관한 `CameraMetadata`를 `SessionFinalizer.finalize()`에 전달하게 한다.

**검증 지점**: `metadata.json`에 `camera` 객체가 기록되고, 획득 실패 시에도 Session 마감이 완료된다.

---

## Phase 7: 사용자 스토리 5 - Timestamp 기록 구간을 녹화 구간에 맞춘다 (우선순위: P3)

**목표**: 영상 녹화가 진행 중이지 않은 구간의 Camera Timestamp가 기록되지 않는다.

**독립 테스트**: Session을 하나 수집하고 `main_frame_timestamps.csv` 행 수와 MP4 frame 수의 차이가 2 이하인지 확인한다.

**의존**: Phase 5(T019). 같은 기록 경로를 수정한다.

### 테스트

- [X] T027 [P] [US5] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/FrameTimestampWriterTest.kt`에 녹화 구간 플래그가 꺼진 동안 들어온 입력이 기록되지 않고 카운터도 증가하지 않는다는 실패 테스트를 추가한다.

### 구현

- [X] T028 [US5] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`에 `@Volatile` 녹화 구간 플래그를 추가해 `recorder.start()` 직후 활성화하고 `mediaRecorder.stop()` 직전에 비활성화한다. 플래그가 꺼진 동안 도착한 `CaptureResult`는 CSV에 기록하지 않는다. `onActive`와 `stop()`·`interrupt()` 세 경로를 모두 처리한다.

**검증 지점**: 녹화 시작 전과 종료 후의 Camera Timestamp가 CSV에 남지 않는다.

---

## Phase 8: 마무리와 검증

**목적**: 회귀를 막고, 자동화할 수 없는 acceptance criterion을 실기기에서 확인하며, 선행 기능의 작업 목록을 정합화한다.

- [X] T029 [P] `specs/001-episode-recorder/tasks.md`의 T007·T008·T009와 `specs/002-capture-control-ux/tasks.md`의 T021에, 해당 범위가 본 기능의 T008~T010·T012~T016·T019에서 production 호출 경로에 연결됐다는 정합화 기록을 남긴다. 002 T021은 파일 목록에서 `CaptureSessionCoordinator.kt`가 실제 구현 경로가 아니었다는 사실을 함께 기록한다.
- [X] T030 [P] `specs/003-session-episode-tracking-gate/quickstart.md`에 자동 검증 실행 결과(명령, 테스트명, 날짜)를 기록한다.
- [X] T031 `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug`를 실행해 T002 기준선 대비 회귀가 없음을 확인한다.
- [X] T032 연결된 실기기에서 `./gradlew.bat connectedDebugAndroidTest`를 실행해 Compose 제어 상태 검증을 통과시킨다.
- [X] T033 실기기에서 [quickstart.md](quickstart.md) 시나리오 1(Session과 Episode 분리)을 수행하고, `episodes.csv`의 Episode 4개와 Session 전체를 덮는 연속 기록을 확인·기록한다. SC-001, SC-004에 대응한다.
- [X] T034 실기기에서 [quickstart.md](quickstart.md) 시나리오 2(Tracking 게이트)를 수행하고, 렌즈 가림 0.3초·2초에 대한 Episode 유지와 `INVALID_TRACKING` 마감, `end_timestamp_ns`가 유실 시작 + 0.5초임을 `arcore_poses.csv`와 대조해 기록한다. SC-002, SC-003에 대응한다.
- [X] T035 실기기 수집 번들로 [quickstart.md](quickstart.md) 시나리오 3을 수행하고, `frame_number`의 순차성과 `main_frame_timestamps.csv` 행 수 대비 MP4 frame 수 차이를 측정해 기록한다. 차이가 2를 넘으면 시작·종료 경계에 몰려 있는지 중간 구간에 흩어져 있는지 구분해 기록한다. SC-005, SC-009에 대응한다.
- [X] T036 실기기 수집 번들로 [quickstart.md](quickstart.md) 시나리오 4를 수행하고, `metadata.json`의 `camera` 객체 존재와 해상도가 MP4와 일치함을 확인·기록한다. SC-006, SC-007에 대응한다.
- [ ] T037 실기기 수집 Session을 기존 경로로 EC2에 업로드해 수신 측 수정 없이 성공함을 확인·기록한다. SC-008에 대응한다.
- [X] T038 [quickstart.md](quickstart.md)의 회귀 확인 항목(SharedCamera 기반 Main RGB 녹화, Session 목록·상세·업로드 상태 화면, SAF export, `arcore_poses.csv` 형식 불변)을 실기기에서 확인·기록한다.

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

---

## 완료 증거 (2026-09-14)

### Phase 1~2 · 공통 기반

- 구현: `ui/capture/CaptureControlPolicy.kt`의 `CaptureWorkspaceControlState`를 `Idle`·`Initializing`·`Ready`·`EpisodeActive`·`Finalizing`으로 재정의하고 `canPlay`·`canStop`·`exitAction`을 새 상태에 맞췄다. `ui/capture/CaptureWorkspaceScreen.kt`가 다섯 상태를 렌더링하고 `CaptureWorkspaceStatus`로 현재 상태를 프리뷰 위에 표시한다. `capture/CaptureSessionCoordinator.kt`에 `onEpisodeClosed` 생성자 콜백을 추가해 사용자 종료와 자동 마감이 같은 출구를 쓰게 했다.
- production 호출 경로: `MainActivity.CaptureScreen` → `controlPolicy()` → `CaptureWorkspaceControls` / `CaptureWorkspaceStatus`.
- 자동 검증: `CaptureControlStateTest` 6개 테스트. 기준선과 동일하게 `BUILD SUCCESSFUL`.

### Phase 3 · US1 Session/Episode 분리

- 구현: `MainActivity.kt`의 Session 시작 경로에서 `EpisodeMarker` 자동 생성을 제거하고 `coordinator.start(...)`만 호출한다. 재생 버튼이 `Idle`에서 Session START, `Ready`에서 `coordinator.startEpisode(task, objectName)`로 분기한다. 일시 정지는 `coordinator.endEpisode()`를 호출하고 기록은 `onEpisodeClosed`가 `repository.save` + `captureRuntime.appendEpisode`로 수행한다. `finalizeCapture()`는 진행 중 Episode가 있으면 `active_episode_end_required`를 표시하고 마감하지 않는다.
- production 호출 경로: `CaptureWorkspaceControls.onPlay` / `onPause` → `CaptureSessionCoordinator` → `onEpisodeClosed` → `SessionRepository` · `AndroidCaptureRuntime.appendEpisode`.
- 자동 검증: `CaptureSessionCoordinatorTest`의 `starting a session does not open an episode`, `episodes repeat inside one session without restarting it`, `an active episode blocks session finalization`.

### Phase 4 · US2 Tracking 게이트

- 구현: `AndroidCaptureRuntime`이 pose 스레드에서 `tracking: StateFlow<Boolean>`을 갱신한다. `MainActivity`의 `LaunchedEffect(collecting)`가 100ms 주기로 `coordinator.onTracking(...)`을 반복 호출해 안정화·유실 판정을 발화시킨다. 화면 상태는 `trackingReady`로 `Initializing` ↔ `Ready`를 전환한다.
- production 호출 경로: `AndroidCaptureRuntime.startPoseCollection` → `tracking` → `MainActivity` ticker → `CaptureSessionCoordinator.onTracking`.
- 자동 검증: `CaptureSessionCoordinatorTest`의 `episode start is rejected before the ready gate elapses`, `brief tracking loss keeps the episode active`, `repeated calls with an unchanged loss signal still fire the deadline`, `an automatically invalidated episode is not closed twice`, `tracking recovery reopens episode collection after the ready gate`.
- 주의: `arcore_poses.csv`의 헤더와 `tracking_state` 기록 형식은 변경하지 않았다.

### Phase 5·7 · US3/US5 frame_number와 녹화 구간

- 구현: `FrameTimestampWriter`가 `recording` 플래그와 0부터의 순차 카운터, timestamp 중복 제거를 소유한다. `AndroidCaptureRuntime.onCaptureCompleted`가 `frameTimestamps?.record(timestampNs)`만 호출한다. `recorder.start()` 직후 `recording = true`, `stop()`·`interrupt()`에서 `mediaRecorder.stop()` 직전에 `false`로 되돌린다.
- production 호출 경로: `AndroidCaptureRuntime.writeHeaders` → `FrameTimestampWriter` → `openSharedCamera`의 `captureCallback`.
- 자동 검증: `FrameTimestampWriterTest` 5개 테스트.
- 001 T007의 `미연결` 해소: `FrameTimestampWriter`가 이제 실제 기록 경로다.

### Phase 6 · US4 Camera Metadata

- 구현: `episode/EpisodeModels.kt`에 `CameraMetadata`를 추가하고 `capture/CameraMetadataReader.kt`가 Camera2의 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS`·`SENSOR_INFO_PHYSICAL_SIZE`·`LENS_DISTORTION`을 실패 허용으로 읽는다. `AndroidCaptureRuntime`이 첫 유효 프레임에서 ARCore `camera.imageIntrinsics`로 필수 값을 확보해 보관하고, `stop()`이 `SessionFinalizer.finalize(active, camera = camera)`로 전달한다. 확보 실패 시 `null`이며 Session 마감은 계속된다.
- production 호출 경로: `AndroidCaptureRuntime.startPoseCollection` → `readCameraMetadata` → `stop()` → `SessionFinalizer.finalize`.
- 자동 검증: `SessionFinalizerTest` 5개 테스트. `existing keys stay intact and the bundle still validates`가 `SessionBundleValidator` 통과까지 확인한다.

### Phase 8 · 문서

- T029: `specs/001-episode-recorder/tasks.md`와 `specs/002-capture-control-ux/tasks.md`에 정합화 기록을 남겼다.
- T030: `quickstart.md`에 자동 검증 실행 기록을 남겼다.
- `contracts/capture-state-machine.md`의 `EpisodeActive` 정지 동작을 구현과 일치하도록 정정했다. 버튼을 비활성화하지 않고 누르면 안내를 표시한다.

### 남은 범위

T031~T038은 실기기·실서버가 필요해 자동화할 수 없다. 이 항목이 남아 있는 한 US1~US5를 완료로 보고하지 않는다.

---

## Phase 9: Convergence

- [X] T039 CRITICAL: `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 Session 마감 시 `session`을 비우는 경로를 추가하고, `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 `finalizeCapture()` 성공 경로와 ON_STOP interrupt 경로에서 이를 호출해, 한 앱 실행에서 두 번째 Session START가 `check(session == null)`에 걸리지 않게 한다 per FR-001, FR-002, US1/AC1 (contradicts)
- [X] T040 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`의 Session 초기화가 `readySinceNs`·`lossSinceNs`·`trackingState`·`activeEpisode`·`latestClosedEpisode`도 함께 되돌리게 하여, 새 Session이 이전 Session의 Tracking 판정을 물려받지 않게 한다 per FR-014, plan: Coordinator 단일 판단 주체 (partial)
- [X] T041 `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 Session 마감 후 새 Session을 시작할 수 있고, 새 Session이 `INITIALIZING`에서 출발해 READY gate를 다시 통과해야 Episode를 시작할 수 있다는 테스트를 추가한다 per FR-001, FR-008 (missing)
- [X] T042 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 ticker가 Episode 자동 마감 시 로컬 `activeEpisode` marker 상태도 Coordinator와 일치시키게 한다 per FR-011 (partial)

### Phase 9 완료 증거 (2026-09-14)

- 구현: `CaptureSessionCoordinator.release()`를 추가해 `session`·`activeEpisode`·`latestClosedEpisode`·`trackingState`·`readySinceNs`·`lossSinceNs`를 되돌린다. `MainActivity`의 `finalizeCapture()` 성공 경로와 ON_STOP interrupt 경로가 이를 호출하고 `trackingReady`도 함께 내린다. ticker가 `activeEpisode`를 Coordinator 값으로 동기화한다.
- production 호출 경로: `finalizeCapture()` / `LifecycleEventEffect(ON_STOP)` → `CaptureSessionCoordinator.release()`.
- 자동 검증: `CaptureSessionCoordinatorTest`의 `a new session can start after the previous one is released`, `a released session does not carry its tracking verdict into the next one`, `release clears the closed episode of the previous session`.
- 재검증: `./gradlew.bat ktlintFormat testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest --no-daemon` → `BUILD SUCCESSFUL` (55s).

### Phase 8 실기기 검증 기록 (2026-09-14)

기기 `SM-G973N`(Galaxy S10, Android 12), Session `45f255d0-41e3-493a-9573-4f35ac67bcac`.
상세 수치는 [quickstart.md](quickstart.md)의 `실기기 검증 기록` 절에 있다.

| Task | 결과 |
|---|---|
| T032 | `connectedDebugAndroidTest` 16개 전부 통과, 실패 0 (11.6s) |
| T033 | Episode 4개 수집, Session 55.6초 전 구간 스트림 연속. SC-001·SC-004 충족 |
| T034 | Episode 3개 `COMPLETED`(구간 내 `PAUSED` 0건), 1개 `INVALID_TRACKING`. 자동 마감 후 수집 계속·회복 뒤 재수집 확인. SC-002·SC-003 충족 |
| T035 | `frame_number` 0~1664 결번 없음, timestamp 단조 증가. CSV 1665행 대 MP4 1667 frame → 차이 2. SC-005·SC-009 충족 |
| T036 | `metadata.json`의 `camera` 필수 7필드 존재, 해상도 640×480이 MP4와 일치, `distortion_coefficients` 미제공으로 키 생략. SC-006·SC-007 충족 |
| T038 | SharedCamera 녹화·`arcore_poses.csv` 형식·Session 목록 정상 |

**관측된 편차 1건**: `INVALID_TRACKING` 마감 시각이 첫 `PAUSED` pose + 0.5초보다 217 ms 늦다.
ARCore pose 처리 지연과 100 ms 평가 주기의 합이다. 기능 결함은 아니나
`contracts/capture-state-machine.md`의 불변식을 pose CSV 기준으로 재면 어긋난다. quickstart에 기록했다.

**T037 미수행**: EC2 업로드는 확인하지 않았다.

---

## Phase 10: Convergence (2차)

`quickstart.md`의 실기기 검증에서 관측된 217 ms 편차를 해소한다.

- [X] T043 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`의 `onTracking`이 pose 카메라 시각을 선택 인자로 받아, 판정용 경과 시간은 단조 시계로 재고 `end_timestamp_ns` 기록에만 pose 시각을 쓰도록 두 시각을 분리한다 per FR-012, contracts: 유실 시작 시각의 기준 (partial)
- [X] T044 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`에 pose 시각이 진행 중 Episode 시작보다 이르거나 현재보다 미래이면 버리고 인지 시각으로 폴백하는 가드를 추가해, 카메라 timestamp 소스가 `REALTIME`이 아닌 기기에서 시간축이 뒤섞인 값이 기록되지 않게 한다 per FR-012 (missing)
- [X] T045 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 tracking 노출을 `TrackingSample(isTracking, observedAtNs)`로 바꾸고 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`의 ticker가 pose 시각을 함께 전달하게 한다 per FR-012 (partial)
- [X] T046 `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`에 pose 시각이 기록에 쓰인다는 것, pose 지연이 0.4초 유실을 무효로 만들지 않는다는 것, 다른 시간축·미래 시각이 폴백된다는 것의 테스트를 추가한다 per FR-010, FR-012 (missing)
- [X] T047 갱신된 앱으로 Session을 다시 수집해 `INVALID_TRACKING`의 `end_timestamp_ns`가 `arcore_poses.csv`의 첫 유실 행 + 0.5초와 일치하는지 실기기에서 확인한다 per FR-012 (실기기)

### Phase 10 완료 증거 (2026-09-14)

- 구현: `lossSinceNs`를 `lossDetectedAtNs`(판정용, 단조 시계)와 `lossObservedAtNs`(기록용, pose 시각)로 분리했다. `trustedObservation()`이 시간축이 다른 값을 걸러 인지 시각으로 폴백한다. `TrackingSample` 타입을 추가해 pose 시각을 함께 전달한다.
- production 호출 경로: `AndroidCaptureRuntime.startPoseCollection` → `tracking: StateFlow<TrackingSample>` → `MainActivity` ticker → `CaptureSessionCoordinator.onTracking(isTracking, observedAtNs)`.
- 자동 검증: `CaptureSessionCoordinatorTest`의 `the recorded loss start comes from the pose timestamp`, `pose latency does not shorten the tracking loss gate`, `a pose timestamp from another timebase is ignored`, `a pose timestamp in the future is ignored`.
- `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest --no-daemon` → `BUILD SUCCESSFUL` (45s).
- 계약 갱신: `contracts/capture-state-machine.md`에 `유실 시작 시각의 기준` 절을 추가해 두 시각의 용도와 폴백을 명시했다.

**설계 함정 기록**: 처음 검토한 단순안(pose 시각 하나로 통일)은 `now - lossSinceNs`가 서로 다른 시계를 빼게 되어 판정 간격에 pose 지연이 더해진다. 실기기 측정치 217 ms 기준으로 0.28초 유실도 마감되어 FR-010을 위반한다. T046의 `pose latency does not shorten the tracking loss gate`가 이 회귀를 막는다.

---

## Phase 11: 중단된 Session 구제

실기기 검증 중 홈 버튼으로 수집 화면이 중단되자 Session 하나가 통째로 목록에서 사라졌다.
파일은 staging에 온전히 남아 있었으나 `INTERRUPTED`로 기록되어 완료 목록에 나타나지 않았다.

Session이 Episode 여러 개를 담는 긴 단위가 되면서 002의 "백그라운드 전환은 즉시 취소" 정책의 비용이
커졌다. 홈 버튼은 `ON_STOP`을 취소하거나 확인 다이얼로그를 띄울 수 없으므로 원천 차단이 불가능하다.
따라서 중단을 막는 대신 **중단돼도 수집분을 정상 Session으로 마감**한다.

- [X] T048 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`의 `recoverInterruptedStaging()`이 staging 번들을 `SessionFinalizer`로 마감해 `COMPLETED`로 전환하게 한다. 마감할 수 없는 번들만 `INTERRUPTED`로 남긴다
- [X] T049 `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`에 `recoverableSessions()`를 추가해 이전 실행에서 `INTERRUPTED`로 남은 Session도 구제 대상에 포함시킨다. 기존 `activeSessions()`는 `INTERRUPTED`를 제외해 한 번 중단된 Session이 영구히 복구 불가였다
- [X] T050 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionRepositoryTest.kt`에 온전한 staging 번들이 `COMPLETED`로 복구되고 손상 번들은 `INTERRUPTED`로 남는다는 테스트를 추가한다
- [X] T051 실기기에서 중단된 Session이 앱 재실행 시 복구되는지 확인한다

### Phase 11 완료 증거 (2026-09-14)

- 구현: `recoverInterruptedStaging()`이 `SessionFinalizer(bundleStore).finalize(bundle)` 결과에 따라 `COMPLETED`(+ completed 경로로 `bundlePath` 갱신) 또는 `INTERRUPTED`로 기록한다. 예외는 `runCatching`으로 감싸 한 번들의 실패가 다른 Session 구제를 막지 않게 했다.
- production 호출 경로: `MainActivity`의 `LaunchedEffect(repository)` → `repository.recoverInterruptedStaging()`.
- 자동 검증: `SessionRepositoryTest`의 `an interrupted staging bundle is finalized instead of discarded`, `a staging bundle that cannot be finalized stays interrupted`.
- 실기기 검증(T051): `SM-G973N`. 홈 버튼으로 중단돼 staging에 묶여 있던 Session `6d6db240-ec0d-4f5e-bf3c-ac93d55e9160`(영상 4.2 MB, Episode 3개)이 앱 재실행 시 `metadata.json`(968 B, 파일 7개 manifest)이 생성되며 `completed/`로 이동했다. staging은 비었다.
- `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug --no-daemon` → `BUILD SUCCESSFUL` (2m 19s).

**진단 기록**: 처음 두 번의 기기 확인에서 복구가 돌지 않았는데, 원인은 코드가 아니라 **복구 변경 이전에 빌드된 APK가 설치돼 있던 것**이었다. 올바른 APK 설치 후 첫 실행에서 바로 복구됐다. `adb install` 스트리밍이 이 기기에서 자주 멈춰, `adb push` + `pm install`로 우회해야 했다.

---

## Phase 12: 수집 중 라이브 프리뷰 유지

수집을 시작하면 프리뷰가 시작 직전 프레임에서 멈춘 정지 화면으로 남았다. 사용자는 수집 내내 얼어붙은
화면을 봤다. Session이 Episode 여러 개를 담는 긴 단위가 되면서 체감 비용이 커졌다.

원인은 두 단계다. `MainActivity`의 `onPlay`가 같은 camera id를 ARCore에 넘기기 위해 유휴 프리뷰용
Camera2 세션을 닫는다(필요한 동작이다). 그런데 `AndroidCaptureRuntime.openSharedCamera`가
MediaRecorder surface만 SharedCamera의 app surface로 등록해, 프리뷰 TextureView가 capture session에도
repeating request target에도 포함되지 않았다. ARCore 자신의 카메라 텍스처는 `OffscreenEgl`의 1×1
PBuffer로 가므로 그쪽에서도 프리뷰가 나올 수 없었다.

- [X] T052 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`에 `PreviewSurfaceProvider`를 추가하고 `start()`가 이를 받아, ARCore가 고른 `cameraConfig.imageSize`를 호출 측에 알려 준 뒤 받은 Surface를 `openSharedCamera`에 넘기게 한다 per FR-031, FR-032
- [X] T053 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureEgl.kt`(구 `OffscreenEgl`)가 preview Surface 위에 EGL window surface를 만들 수 있게 하고, `CameraTextureRenderer`가 ARCore Camera OES 텍스처를 그 surface에 그리게 한다. Camera2 출력 stream을 늘리지 않는다 per FR-031, FR-033
- [X] T054 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`가 `SurfaceTexture`를 보관하고 하드코딩된 `1920×1080` 대신 `DEFAULT_PREVIEW_SIZE`(640×480)를 쓰며, 수집 시작 시 provider로 ARCore 해상도를 받아 버퍼를 다시 맞추게 한다 per FR-032
- [X] T055 같은 파일에 `restoreIdlePreview()`를 추가하고 ARCore 시작 실패·`finalizeCapture` 실패 잔류·`ON_START` 복귀 경로에서 유휴 프리뷰를 되살린다 per FR-031
- [X] T056 `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewControllerTest.kt`에 Ready 상태에서 release 후 다시 prepare하면 프리뷰가 실제로 재개된다는 테스트를 추가한다 per FR-031
- [X] T062 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 pose 루프가 `session.update()` 실패와 `eglSwapBuffers` 거부를 남기고 다음 프레임으로 넘어가게 해, 한 번의 실패로 프리뷰와 pose 수집이 함께 멈추지 않게 한다 per FR-031
- [X] T063 같은 파일이 마감·중단 시 `stopRepeating()`으로 프레임 공급을 먼저 끊고, 진행 중인 프레임이 정리된 뒤에 타임스탬프 기록 창을 닫게 한다 per FR-033, SC-009
- [X] T057 실기기에서 수집 중 프리뷰가 실시간으로 갱신되는지, 프리뷰가 저장된 MP4와 같은 방향으로 잘림 없이 보이는지, `main_frame_timestamps.csv` 행 수와 MP4 frame 수 차이 및 실효 FPS에 회귀가 없는지 확인한다 per FR-031, FR-032, FR-033, SC-009, SC-011 (실기기)


**접근 전환**: 처음에는 프리뷰 surface를 `SharedCamera.setAppSurfaces`에 recorder와 함께 등록했다.
실기기에서 `createCaptureSession`이 `Error configuring streams: Broken pipe (-32)`로 실패했다.
로그로 stream 구성을 재보니 `arcore=2 app=2 total=4`였고, 프리뷰만 뺀 3 stream에서는 수집·마감·업로드가
모두 정상이었다. 즉 대상 기기가 4 stream 조합을 받아들이지 못한다. 그래서 stream을 늘리지 않는
GL 렌더링으로 전환했다. `research.md` 결정 10에 기록한 대안 경로다.

### Phase 12 완료 증거 (2026-09-15)

- 구현: `PreviewSurfaceProvider`가 ARCore `cameraConfig.imageSize`를 알려 주고 프리뷰 Surface를 받는다. 받은 Surface는 Camera2 출력이 아니라 `CaptureEgl`의 EGL window surface 대상이 되며, pose 수집 스레드가 매 프레임 `CameraTextureRenderer`로 ARCore Camera OES 텍스처를 그린다. 카메라 출력 stream 수는 변경 전과 같다.
- 방향과 잘림: 표시 회전을 Sensor 방향과 같게 주어 ARCore의 회전 보정을 상쇄하고, 표시 크기는 `cameraConfig.textureSize`로 준다. 처음에는 `ROTATION_0`과 `imageSize`를 줬는데, 녹화본과 90도 어긋난 데다 가로 화각의 58%가 잘렸다. 실기기에서 `transformCoordinates2d`의 UV로 확인하고 바로잡았다. 자세한 측정은 [quickstart.md](quickstart.md)에 있다.
- production 호출 경로: `MainActivity.onPlay` → `AndroidCaptureRuntime.start(displayNumber) { w, h -> previewSurface }` → `openSharedCamera` → `onActive` → `startPoseCollection(session, previewSurface)` → `CaptureEgl(previewSurface)` + `CameraTextureRenderer.draw`.
- 부수 수정: `start()` 실패 경로가 `bundle`을 비우지 않아 다음 `start()`가 막히던 잠복 버그, 그리고 `CameraPreviewController`가 release 직후 재개될 때 앞선 열기의 콜백이 닫힌 device를 건드려 프로세스가 죽던 경합(`CameraDevice was already closed`)을 함께 고쳤다. 후자는 `restoreIdlePreview()` 도입으로 드러났다.
- 자동 검증: `CapturePreviewControllerTest`의 `preview can be reopened after a capture releases the camera`. `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug` → `BUILD SUCCESSFUL` (32s).

#### 실기기 검증 (T057) · `SM-G973N`, Android 12

`adb push` + `pm install`로 설치하고 설치 시각을 대조해 새 빌드임을 확인한 뒤 수행했다.

| 항목 | 결과 |
|---|---|
| 유휴 프리뷰 | 정상. `Camera3-OutputStream: First frame for stream 0, width 640, height 480` |
| **수집 중 프리뷰 갱신** | **정상.** 60초 동안 5초 간격 12개 표본이 모두 서로 다름. 연속 5프레임도 모두 다름 |
| 수집 시작 | 정상 (GL 경로). surface 등록 방식에서는 실패했다 |
| Session 마감·업로드 | 정상 |
| `frame_number` 결번 | 0건 (0..4961) |
| `timestamp_ns` 단조 증가 | 위반 0건 |
| 실효 FPS | **29.998** (프리뷰 없는 대조군 30.004). 회귀 없음 |
| CSV 행 수 대 MP4 frame 수 | **정상 마감 1111 대 1113, 중단 841 대 843 → 모두 차이 2**. SC-009 충족 |
| `metadata.json` 해상도 | 640×480, MP4와 일치. `camera` 필수 7필드 존재 |

FPS 대조군은 같은 기기·같은 날 프리뷰를 끈 빌드로 수집한 `82c11c1c`다.

**SC-009를 맞추기 위한 수정**: 처음 측정에서는 차이가 3으로 명세의 2 이하를 넘겼다.
프리뷰를 끈 대조군도 3이었으므로 이번 변경의 회귀는 아니었고, 마감 경로 자체의 경계 문제였다.

원인은 두 가지다. 마감 시 프레임 공급이 계속되는 상태에서 타임스탬프 기록 창만 닫아,
`MediaRecorder.stop()`이 끝날 때까지 인코딩된 프레임이 CSV에 남지 않았다. 또 `stopRepeating()`을
불러도 이미 진행 중인 프레임은 계속 인코딩되므로, 그 프레임의 `onCaptureCompleted`를 받기 전에
창을 닫으면 같은 차이가 남는다.

`stopRepeating()`으로 공급을 먼저 끊고, 진행 중인 프레임이 정리될 시간을 준 뒤 창을 닫도록 고쳤다.
정상 마감과 중단 경로 모두 차이가 **2**로 내려와 SC-009를 충족한다.

**미검증**: Tracking 게이트(SC-002·SC-003)를 확인하지 못했다. 기기를 책상에 고정한 채 원격으로
조작해 ARCore가 시차를 얻지 못했고 Tracking이 `INITIALIZING`을 벗어나지 않았다.
Episode 시작·`INVALID_TRACKING` 자동 마감·회복 후 재수집은 사람이 기기를 들고 움직이며 확인해야 한다.
프리뷰와 저장 영상을 눈으로 대조하지도 못했다. 방향이 같다는 것은 UV 측정으로 확인했으나,
두 이미지를 나란히 놓고 본 것은 아니다.

**별건 결함 발견**: 수집을 끝낼 때 ARCore 종료에서 프로세스가 죽는다. 프리뷰를 완전히 끈 빌드에서도
동일한 스택으로 재현되므로 **기존 결함이며 이번 변경과 무관**하다. 별도 이슈 S15P21A206-31로 등록해
아래 Phase 13에서 고쳤다.

---

## Phase 13: 수집 종료 시 ARCore 종료 순서

수집을 끝낼 때 ARCore 종료 과정에서 앱 프로세스가 죽었다. 홈 버튼 중단에서 먼저 발견했고,
이후 프리뷰 작업의 프레임 수 측정 중 **정상 마감(수집 종료) 경로에서도 같은 스택으로** 나는 것을
확인했다. 둘 다 같은 `releaseResources()`를 지나므로 원인과 수정이 같다. 다만 마감 경로는
간헐적이어서 처음에는 중단 전용 결함으로 보였다.

```text
FATAL EXCEPTION: TigerCamera
java.lang.IllegalArgumentException
  at com.google.ar.core.SharedCamera.nativeSharedCameraCaptureSessionClosed(Native Method)
  at com.google.ar.core.SharedCamera.onCaptureSessionClosed(SharedCamera.java:1)
```

`releaseResources()`가 ARCore Session을 capture session보다 **먼저** 닫았다. `captureSession.close()`가
ARCore의 래핑된 `onClosed`를 camera 핸들러 스레드에서 발화시키는데, 그 시점에 native Session이 이미
닫혀 있어 예외가 났다. 콜백 안에서 나므로 잡히지 않고 프로세스가 죽는다.

Phase 11의 구제 경로가 있어 데이터는 다음 실행에서 복구되지만, 사용자에게는 앱이 갑자기 종료되는
것으로 보였다. Phase 11의 진단 기록에 남은 "홈 버튼으로 중단되자 Session이 사라졌다"의 실제 모습이
이것이었다.

- [X] T058 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`의 `openSharedCamera`가 capture session의 `onClosed`를 받아 `CountDownLatch`를 내리게 한다
- [X] T059 같은 파일의 `releaseResources()`가 `pause` → `captureSession.close()` → 닫힘 대기 → `cameraDevice.close()` → `arSession.close()` 순서로 정리하게 바꾼다. 핸들러 스레드는 콜백이 모두 전달된 뒤에 정리한다
- [X] T060 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CameraPreviewController.kt`가 세대 번호로 오래된 열기의 콜백을 버리고, 열기와 요청 호출을 `runCatching`으로 감싸 닫힌 `CameraDevice` 접근이 프로세스를 죽이지 않게 한다 per FR-034
- [X] T064 대기가 한계를 넘으면 경고를 남겨, 종료를 확인하지 못한 채 진행한 경우를 알 수 있게 한다
- [X] T061 실기기에서 수집 중 홈 버튼과 정상 마감 양쪽에서 프로세스가 생존하는지, 복귀와 재실행 시 중단 Session 복구가 정상인지, 업로드에 회귀가 없는지 확인한다 (실기기)

### Phase 13 완료 증거 (2026-09-15)

- 구현: `openSharedCamera`가 session마다 `CountDownLatch`를 만들어 inner `CameraCaptureSession.StateCallback.onClosed`에서 내린다. `releaseResources()`는 `arSession.pause()` → `captureSession.close()` → latch 대기(최대 2초) → `cameraDevice.close()` → `arSession.close()` 순서로 정리하며, `cameraThread.quitSafely()`는 그 뒤에 부른다. 대기가 한계를 넘으면 `Log.w`로 남긴다.
- production 호출 경로: `MainActivity`의 `LifecycleEventEffect(ON_STOP)` → `AndroidCaptureRuntime.interrupt()` → `releaseResources()`. 정상 마감 경로인 `stop()`도 같은 함수를 쓴다.
- 자동 검증: 없음. `AndroidCaptureRuntime`은 `Session`·`CameraManager`·`MediaRecorder`를 직접 만들어 JVM에서 테스트할 수 없고, 이번 변경으로 seam을 새로 만들지 않았다. 종료 순서는 실기기로만 확인된다.
- `./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug` → `BUILD SUCCESSFUL`.

#### 실기기 검증 (T061) · `SM-G973N`, Android 12

`adb push` + `pm install`로 설치하고 설치 시각을 대조해 새 빌드임을 확인한 뒤 수행했다.

| 항목 | 결과 |
|---|---|
| 수집 중 홈 버튼 → 프로세스 생존 | **정상.** 2회 모두 PID 유지, `FATAL EXCEPTION` 0건 |
| 정상 마감 → 프로세스 생존 | **정상.** 수정 전에는 간헐적으로 죽었다. 수정 후 연속 4회 마감에서 PID 유지, `FATAL EXCEPTION` 0건 |
| 복귀 후 수집 화면 | 정상. `IDLE`로 복귀 |
| 재실행 시 중단 Session 복구 | 정상. staging 번들이 `completed/`로 이동하며 `metadata.json` 생성 |
| 정상 마감·업로드 | 정상. `업로드 완료`까지 확인 |
| 종료 대기 한계 초과 | 0건. `onClosed`가 제때 도착해 2초 대기에 걸리지 않는다 |
| ANR·프레임 누락 | 관측되지 않음 |

수정 전에는 홈 버튼 중단에서 매번, 정상 마감에서 간헐적으로 위 스택으로 죽었다. 프리뷰를 완전히 끈 빌드에서도
동일하게 재현되어, 이 결함이 프리뷰 작업과 무관한 기존 결함임을 이분법으로 확인했다.

**함께 고친 기존 결함**: 종료 순서만 고친 빌드로 검증하던 중 3회 중 1회 프로세스가 죽었다.
원인은 다른 결함이었다. 유휴 프리뷰를 닫자마자 다시 열 때 앞선 열기의 `onConfigured`가 이미 닫힌
`CameraDevice`에 `setRepeatingRequest`를 불러 `CameraPreviewController`에서 죽는다.
이 역시 develop에 있던 기존 결함이므로 같은 브랜치에서 함께 고쳤다. 세대 번호로 오래된 열기의
콜백을 버리고, 열기와 요청 호출을 `runCatching`으로 감싼다.

두 수정을 함께 넣은 빌드로 위 표를 측정했다. 한쪽만 고치면 "수집을 끝낼 때 앱이 죽지 않는다"가
성립하지 않는다.

**staging에 남은 번들 1건**: `0dcbd597`은 `main_rgb.mp4`가 0바이트라 마감할 수 없어 staging에 남는다.
이번 검증 이전의 다른 실험에서 생긴 것이며, 마감 불가 번들만 남기는 FR-029의 의도대로 동작한 결과다.
