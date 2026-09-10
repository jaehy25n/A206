# 작업 목록: Capture Control UX

**입력**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/capture-control-ui.md`, `quickstart.md`

**테스트 원칙**: 상태 전이·저장소 필터·업로드 취소·오류 처리는 구현 전에 자동 테스트를 작성한다. 실제 카메라·ARCore·ingestion server 검증은 별도 실제 기기 작업으로 남기며, 단위 테스트 성공을 실제 기기 검증으로 보고하지 않는다.

## Phase 1: 준비

**목적**: 기존 단일 화면 구조와 공개 계약을 보존하면서 구현 단위를 만들 준비를 한다.

- [X] T001 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`와 `app/src/main/res/values/strings.xml`의 현재 수집·업로드·export 진입점을 확인하고, 화면 분리에 필요한 기존 사용자 문구 및 production 호출 경로를 작업 기록에 정리한다.
  - 구현/검토: `CaptureScreen`이 기존 수집 시작·Episode·종료와 `UploadControls`·`ExportControls`를 단일 화면에서 연결한다. 사용자 노출 문구는 다음 UI MR에서 `strings.xml`로 이동한다.
  - 자동 검증: `./gradlew.bat ktlintCheck testDebugUnitTest` 성공 (2026-09-08).
- [X] T002 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleStoreTest.kt`와 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionRepositoryTest.kt`에 내부 root, legacy 외부 bundle 제외, 직접 업로드 차단의 실패 테스트 fixture를 추가한다.
  - 자동 검증: `SessionBundleStoreTest.only direct child of internal completed root is managed`, `SessionRepositoryTest.legacy external completed bundle is excluded from listing and upload`.
- [X] T003 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabaseMigrationTest.kt`에 수집 벽시계 시작 시각 migration의 실패 테스트를 추가한다.
  - 자동 검증: `TigerDatabaseMigrationTest.version four migration adds a non null wall clock start timestamp`가 version과 non-null default migration SQL을 검증한다.
- [X] T004 [P] `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadServiceTest.kt`와 `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploaderTest.kt`에 사용자 취소·백그라운드 취소가 HTTP 요청과 `FAILED` 상태까지 전달되는 실패 테스트를 추가한다.
  - 자동 검증: `SessionUploadServiceTest.cancelled upload persists failed`, `SessionUploaderTest.cancelling upload cancels the in flight HTTP request`.

---

## Phase 2: 공통 기반

**목적**: 모든 화면이 공유하는 내부 저장소, Room 색인, Episode·업로드 상태 전이를 구현한다.

**⚠️ 중요**: 이 단계가 완료되기 전에는 사용자 스토리 구현을 시작하지 않는다.

- [X] T005 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`의 `SessionBundleStore`를 `Context.filesDir` 기반 내부 root로 전환하고, canonical 경로 containment로 관리되는 completed bundle 여부를 판별한다.
  - 구현: `SessionBundleStore(Context)` → `filesDir/capture`, `isManagedCompletedDirectory`가 canonical direct-child containment를 검증한다.
  - 자동 검증: `SessionBundleStoreTest.only direct child of internal completed root is managed`; `./gradlew.bat ktlintCheck testDebugUnitTest` 성공 (2026-09-08).
- [X] T006 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`에서 목록·상세·업로드 source가 T005의 관리 경로 검증을 공통으로 사용하게 하여 legacy 외부 bundle을 복사·삭제하지 않고 제외하고, 검증 위치를 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`에 유지한다.
  - 구현: `observeCompleted`, `completedSource`, `exportFor`가 단일 store 경계 검증을 사용한다. production 호출은 `CaptureScreen`의 목록·업로드·export 경로다.
  - 자동 검증: `SessionRepositoryTest.legacy external completed bundle is excluded from listing and upload`; `./gradlew.bat ktlintCheck testDebugUnitTest` 성공 (2026-09-08).
- [X] T007 `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`에 로컬 벽시계 수집 시작 시각을 추가하고 Room version·migration·entity/model 변환을 갱신한다.
  - 구현: `recordingStartEpochMs`, Room v4 migration, entity/model 변환과 `CaptureScreen` 신규 Session 저장 경로.
- [X] T008 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`에서 `CANCELLED` Episode 상태·전이·취소 API를 제거하고 완료·추적 실패 경계만 유지한다.
  - 구현: `EpisodeState`와 `CaptureSessionCoordinator.endEpisode`에서 취소 상태/인자를 제거했고, 기존 `CaptureScreen` 취소 버튼 생산 경로도 제거했다.
  - 자동 검증: `CaptureSessionModelsTest.episode outcome is terminal after active`; `./gradlew.bat ktlintCheck testDebugUnitTest` 성공 (2026-09-08).
- [X] T009 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadClient.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadService.kt`에 취소 가능한 OkHttp 요청과 취소 시 `FAILED`를 보존하는 upload operation 경계를 구현한다.
  - 구현: cancellable OkHttp callback과 cancellation handler가 active call을 취소하고, service가 `CancellationException`에서 `FAILED`를 persist한다.
- [X] T010 `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionBundleStoreTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionRepositoryTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabaseMigrationTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/CaptureSessionModelsTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadServiceTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploaderTest.kt`를 실행해 T002~T004의 테스트와 기존 계약 테스트를 통과시킨다.
  - 자동 검증: `./gradlew.bat ktlintCheck testDebugUnitTest --no-daemon` 성공 (2026-09-08).

**검증 지점**: 내부 bundle만 관리·업로드 가능하고, legacy 외부 bundle은 보존된 채 제외되며, 새 Session은 표시 가능한 수집 시각과 취소 가능한 업로드 상태를 가진다.

---

## Phase 3: 사용자 스토리 1 - 목록에서 새 수집 시작 (우선순위: P1) 🎯 MVP

**목표**: 사용자가 완료 Session의 요약·Episode 개수·전송 상태를 보고 Detail로 열거나, 새 수집 작업 공간으로 들어간다.

**독립 검증**: 내부 완료 Session, 전송 완료/실패 Session, legacy 외부 Session fixture로 목록을 열어 요약과 빈 상태를 확인하고, 항목 선택과 새 수집 선택의 화면 목적지를 확인한다.

- [X] T011 [P] [US1] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionSummaryRepositoryTest.kt`에 완료 Episode만 집계하는 Session 목록 projection과 legacy 제외 테스트를 작성한다.
  - 구현: `SessionSummaryRepositoryTest.managed summaries retain completed episode count and exclude legacy bundles`가 managed bundle의 완료 Episode 집계와 legacy 외부 경로 제외를 검증한다.
  - 자동 검증: `./gradlew.bat testDebugUnitTest --tests "com.ssafy.s15p21a206.tiger.episode.SessionSummaryRepositoryTest" --no-daemon` 성공 (2026-09-10).
- [X] T012 [P] [US1] `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/session/SessionListScreenTest.kt`에 빈 상태, Session 요약, Episode 개수, 전송 상태, 새 수집 및 Detail 선택의 Compose semantics 테스트를 작성한다.
  - 구현: 빈 목록의 새 수집 행동, Task 선택, Session 요약 표시와 Detail 선택을 검증하는 instrumentation test를 추가했다.
  - 자동 검증: `SessionListScreenTest.emptyListShowsStartCaptureAction`, `taskSelectionOpensItsSessionList`, `sessionSummaryShowsDetailsAndOpensDetail`; `./gradlew.bat connectedDebugAndroidTest --no-daemon` 성공 (2026-09-10, `SM-G973N`, Android 12).
- [X] T013 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`에 완료 Episode 개수를 포함하는 managed Session summary 조회를 구현한다.
  - 구현: `CaptureSessionDao.observeCompletedSummaries`가 `COMPLETED` marker만 집계하고, `SessionRepository.observeCompletedSummaries`가 managed completed root만 노출한다. production 호출은 `CaptureScreen`의 `completedSummaries` 수집이다.
  - 자동 검증: `SessionSummaryRepositoryTest.managed summaries retain completed episode count and exclude legacy bundles`; `./gradlew.bat testDebugUnitTest --tests "com.ssafy.s15p21a206.tiger.episode.SessionSummaryRepositoryTest" --no-daemon` 성공 (2026-09-10).
- [X] T014 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 hoisted sealed 화면 목적지와 선택된 Session id를 추가하고, Session 목록 화면을 앱의 시작 화면으로 연결한다.
  - 구현: `AppDestination`과 hoisted `destination`이 `SessionList`를 시작 화면으로 두고 `TaskSessions`·`SessionDetail(sessionId)`를 전환한다. production 호출은 `CaptureScreen`의 destination `when` 분기다.
  - 실제 검증: 2026-09-09 `SM-G973N`에서 Task 홈과 Task 선택 후 Session Detail 진입을 확인했다 (`quickstart.md`).
- [X] T015 [US1] `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/session/SessionListScreen.kt`, `app/src/main/res/values/strings.xml`에 Task 이름 홈, Task별 Session 목록, 수집 시각·짧은 식별자·Episode 개수·전송 상태, 새 수집 및 Detail 행동을 구현한다.
  - 구현: `SessionListScreen`과 `TaskSessionListScreen`이 Task 그룹, 새 수집, 수집 시각·짧은 ID·완료 Episode 수·전송 상태 및 Detail 콜백을 제공한다. production 호출은 `CaptureScreen`의 `SessionList`·`TaskSessions` 목적지다.
  - 실제 검증: 2026-09-09 `SM-G973N`에서 Task 홈과 Session 요약·Detail 동작을 확인했다 (`quickstart.md`).
- [X] T016 [US1] `app/src/test/java/com/ssafy/s15p21a206/tiger/episode/SessionSummaryRepositoryTest.kt`와 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/session/SessionListScreenTest.kt`를 통과시키고, 목록 항목이 수집 작업 공간이 아니라 Detail 목적지로 이동함을 확인한다.
  - 자동 검증: `SessionSummaryRepositoryTest.managed summaries retain completed episode count and exclude legacy bundles`와 `SessionListScreenTest` 3개가 통과했다. `./gradlew.bat testDebugUnitTest --no-daemon`, `./gradlew.bat connectedDebugAndroidTest --no-daemon` 성공 (2026-09-10, `SM-G973N`, Android 12).
  - 실제 검증: 목록 Task 선택과 Session 요약 카드 선택이 수집 작업 공간이 아닌 Detail 목적지 콜백을 호출함을 `SessionListScreenTest`에서 확인했다.

**검증 지점**: 목록만으로 새 수집을 시작하거나 완료 Session의 Detail로 이동할 수 있다.

---

## Phase 4: 사용자 스토리 2 - 아이콘 수집 제어와 라이브 프리뷰 (우선순위: P1)

**목표**: 카메라 프리뷰에서 task/object를 준비한 뒤 재생·일시 정지·정지로 Session과 Episode를 제어하고, 정지 후 자동 전송으로 이어간다.

**독립 검증**: 프리뷰 준비 후 재생·일시 정지·재생·정지를 수행해 Session 하나와 완료 Episode 두 개가 기록되고 업로드 상태 목적지로 전환되는지 확인한다.

- [ ] T017 [P] [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewControllerTest.kt`에 권한·AR·camera preflight 성공/실패, preview-only 준비, 첫 재생 전 Session 미생성의 실패 테스트를 작성한다.
- [ ] T018 [P] [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureWorkspaceScreenTest.kt`에 task/object gating, 재생·일시 정지·정지 아이콘 semantics, Episode 완료 경계, 정지 확인의 Compose 테스트를 작성한다.
- [ ] T019 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewController.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`에 녹화 시작과 분리된 preview 준비·해제·오류 복구 수명주기를 구현한다.
- [ ] T020 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/res/values/strings.xml`에 전체 화면 프리뷰, 프리뷰가 보이는 즉시 나타나는 공통 task/object 입력 모달, 프리뷰 하단 중앙의 표준 재생·일시 정지·정지 오버레이, 배경 없는 흰색 우측 상단 X 닫기, 접근성 라벨·툴팁, 수집 종료 확인을 구현한다.
- [ ] T021 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadService.kt`를 연결해 정지가 열린 Episode를 완료하고 Session finalize 성공 뒤 자동 업로드와 업로드 상태 목적지를 시작하게 한다.
- [ ] T022 [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewControllerTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureWorkspaceScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`를 통과시키고 실제 기기에서 프리뷰가 녹화 전 표시되는지 별도 기록한다.

**검증 지점**: 텍스트 버튼 없이 제어 아이콘으로 Session과 Episode를 만들고, 정지는 자동 전송 상태 화면으로 이어진다.

---

## Phase 5: 사용자 스토리 3 - 제어 상태와 종료 방지 (우선순위: P2)

**목표**: 프리뷰를 가리지 않고 가능한 제어를 전달하며, 실수로 수집을 끝내지 못하게 한다.

**독립 검증**: 준비·Episode 진행·Episode 없음/Session 수집·확정 상태에서 활성 아이콘이 다르고, 정지·뒤로 가기·닫기에는 확인을 제공하는지 확인한다.

- [ ] T023 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`에 네 수집 상태의 아이콘 활성화, 확정 중 중복 입력 차단, 정지·뒤로 가기·닫기 확인 테스트를 작성한다.
- [ ] T024 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 상태별 제어 활성화, 준비 실패·확정 중 일회성 안내, BackHandler·전체 화면 sheet X 닫기 확인을 구현한다.
- [ ] T025 [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`를 통과시키고 TalkBack에서 아이콘의 접근성 이름과 툴팁을 실제 기기에서 확인한다.

**검증 지점**: 사용자는 상시 상태 문구 없이 가능한 다음 조작을 알 수 있고, 수집 종료 전 확인 기회를 받는다.

---

## Phase 6: 사용자 스토리 4 - Session Detail과 업로드 상태 (우선순위: P2)

**목표**: Detail에서 수집 내용을 확인하고 전송·재전송을 시작하며, 별도 업로드 상태 화면에서 진행·완료·실패·취소를 관리한다.

**독립 검증**: 로컬 보관·실패 Session Detail에서 전송·재전송을 시작하고, 업로드 상태 화면에서 로딩·종료·이탈 확인·백그라운드 중단 뒤 retry를 확인한다.

- [ ] T026 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/SessionDetailScreenTest.kt`에 Detail 수집 시각·길이·완료 Episode 개수·데이터 상태와 전송/재전송 행동 테스트를 작성한다.
- [ ] T027 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/UploadStatusScreenTest.kt`에 비결정적 진행 표시, 화면 이탈 경고 문구, 완료/실패 상태, 뒤로 가기 취소 확인, lifecycle background 취소 테스트를 작성한다.
- [ ] T028 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/res/drawable/`, `app/src/main/res/values/strings.xml`에 Session 식별 정보·수집 시각·길이·완료 Episode 개수·데이터 상태·로컬 원본 동영상 재생·전체 화면 확장, 상태별 전송·재전송 행동과 좌측 상단 뒤로가기 아이콘을 구현한다.
- [ ] T029 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/upload/UploadStatusScreen.kt`와 `app/src/main/res/values/strings.xml`에 비결정적 로딩, 화면 이탈 경고, 성공·실패 표시와 취소 확인 dialog를 구현한다.
- [ ] T030 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadService.kt`에 Detail·정지의 공통 전송 시작, Upload Status 화면 소유 Job, back/close 확인 취소, `ON_STOP` 즉시 취소 및 `FAILED` persist를 연결한다.
- [ ] T031 [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/SessionDetailScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/UploadStatusScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadServiceTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploaderTest.kt`를 통과시키고 MockWebServer에서 `201`, `200 duplicate`, 네트워크 실패, 취소를 확인한다.

**검증 지점**: Detail은 전송을 시작하고, 업로드 상태 화면은 polling 없이 진행을 보여 주며 이탈·백그라운드 중단 후 재전송을 보장한다.

---

## Phase 7: 마무리와 교차 검증

**목적**: 사용자 흐름·계약·자동/실제 기기 검증을 하나로 확인한다.

- [ ] T032 [P] `app/src/main/res/values/strings.xml`과 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/`의 사용자 문구·content description·툴팁을 점검해 하드코딩 문자열과 접근성 누락을 수정한다.
- [ ] T033 [P] `specs/001-episode-recorder/spec.md`, `specs/001-episode-recorder/data-model.md`, `specs/001-episode-recorder/contracts/episode-bundle.md`, `specs/002-capture-control-ux/spec.md`, `specs/002-capture-control-ux/data-model.md`, `specs/002-capture-control-ux/contracts/capture-control-ui.md`를 구현 결과와 대조해 storage·Episode·업로드 계약 불일치를 갱신한다.
- [ ] T034 `specs/002-capture-control-ux/quickstart.md`에 따라 `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug`, `.\gradlew.bat assembleDebug`, `.\gradlew.bat ktlintCheck`를 실행하고 명령·결과를 각 완료 task의 증거로 기록한다.
- [ ] T035 `specs/002-capture-control-ux/quickstart.md`에 따라 실제 기기와 ingestion server에서 프리뷰, 수집 제어, 자동 업로드, 취소, 백그라운드 중단, 재전송, legacy 제외를 검증하고 결과를 `specs/002-capture-control-ux/quickstart.md`에 기록한다.
- [ ] T037 [P] `gradle/libs.versions.toml`의 ARCore와 생성 APK를 Android 15+ 16KB 페이지 환경에서 실행해 카메라·AR 세션 생성과 수집 흐름을 검증한다. `lintDebug`의 `Aligned16KB` 경고와 `zipalign -c -P 16 -v 4` 결과를 함께 기록한다.
  - 자동 검증(2026-09-09): `com.google.ar:core:1.56.0`으로 `ktlintCheck testDebugUnitTest assembleDebug lintDebug` 성공, 강제 재실행한 Lint report에서 `Aligned16KB` 0건, `zipalign -c -P 16 -v 4 app/build/outputs/apk/debug/app-debug.apk` 성공.
  - 남은 실제 검증: 16KB 페이지(`adb shell getconf PAGE_SIZE`가 `16384`) 기기 또는 에뮬레이터에서 AR 세션·카메라·수집을 실행한다.
- [ ] T036 `specs/002-capture-control-ux/tasks.md`의 각 완료 task에 구현 파일·production 호출 경로·자동 검증·실제 기기 검증 근거를 기록한 뒤 `$speckit-converge`를 실행한다.

---

## 의존성 및 실행 순서

```text
Phase 1 준비
  ↓
Phase 2 공통 기반
  ├── US1 Session 목록 (P1)
  └── US2 수집 제어·프리뷰 (P1)
        ↓
      US3 제어 상태·종료 방지 (P2)
        ↓
      US4 Detail·업로드 상태 (P2)
        ↓
      Phase 7 교차 검증
```

- US1과 US2는 Phase 2 완료 뒤 병렬로 시작할 수 있다.
- US3는 US2의 수집 작업 공간을 확장한다.
- US4는 Phase 2의 취소 가능한 업로드 기반을 사용하며, US1 목록의 Detail 진입을 연결한다.
- Phase 7은 원하는 모든 사용자 스토리 완료 뒤에만 시작한다.

## 병렬 작업 예시

```text
# 공통 기반 테스트를 병렬로 작성
T002: 내부 저장소·legacy 필터 테스트
T003: Room migration 테스트
T004: 업로드 취소 테스트

# Phase 2 완료 후 서로 다른 파일을 병렬 구현
T011/T012: US1 repository·목록 화면 테스트
T017/T018: US2 preview·작업 공간 테스트
T026/T027: US4 Detail·업로드 상태 테스트
```

## 구현 전략

### MVP

1. Phase 1과 Phase 2를 완료한다.
2. US1을 완료해 Session 목록·새 수집 진입·Detail 목적지를 검증한다.
3. US2를 완료해 실제 프리뷰와 미디어 아이콘 수집 제어를 검증한다.
4. 실제 기기에서 프리뷰와 수집이 성립하는지 확인한 뒤 US3·US4를 확장한다.

### 점진적 제공

1. 목록과 프리뷰 기반 수집을 먼저 독립 검증한다.
2. 종료 방지와 제어 상태를 추가한다.
3. Detail과 업로드 상태·취소를 추가한다.
4. 자동 검사와 실제 기기/서버 검증을 완료한 뒤 converge로 명세와 코드를 대조한다.

## 완료 증거 기록 양식

작업을 `[X]`로 바꾸기 전에 해당 작업 아래 또는 같은 phase 검증 기록에 다음을 남긴다.

- 구현: 변경 파일과 실제 production 호출 경로
- 자동 검증: 테스트 파일·테스트명·실행 명령·결과
- 실제 검증: 기기·서버·권한 조건과 결과, 또는 남은 별도 작업
