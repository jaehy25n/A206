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

- [X] T017 [P] [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewControllerTest.kt`에 권한·AR·camera preflight 성공/실패, preview-only 준비, 첫 재생 전 Session 미생성의 실패 테스트를 작성한다.
  - 구현: `CapturePreviewControllerTest`가 permission/AR/camera 실패, preview-only 준비와 recording 미생성을 검증한다.
  - 자동 검증: `./gradlew.bat testDebugUnitTest --tests "com.ssafy.s15p21a206.tiger.capture.CapturePreviewControllerTest" --no-daemon` 성공 (2026-09-10).
- [X] T018 [P] [US2] `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/CaptureWorkspaceScreenTest.kt`에 재생·일시 정지·정지 아이콘 semantics의 Compose 테스트를 작성한다.
  - 구현: `CaptureWorkspaceScreenTest`가 준비·구간 진행·구간 종료 상태의 노출 제어와 content description을 검증한다. task/object gating·종료 확인은 `MainActivity`의 입력/확인 dialog 흐름으로 연결돼 있다.
  - 자동 검증: `./gradlew.bat assembleDebugAndroidTest --no-daemon`로 instrumentation test APK 컴파일을 확인했다 (2026-09-10). 실행은 T022의 실제 기기 검증으로 남긴다.
- [X] T019 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewController.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt`에 녹화 시작과 분리된 preview 준비·해제·오류 복구 수명주기를 구현한다.
  - 구현: `CapturePreviewController`가 preflight와 `PreviewRuntime`을 분리하고, `MainActivity`의 `TextureView` 수명주기에서 preview를 준비·해제한다. Session bundle 생성은 재생 행동에서만 발생한다.
  - 자동 검증: `CapturePreviewControllerTest`; `./gradlew.bat ktlintCheck testDebugUnitTest --no-daemon` 성공 (2026-09-10).
- [X] T020 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/res/values/strings.xml`에 전체 화면 프리뷰, 프리뷰가 보이는 즉시 나타나는 공통 task/object 입력 모달, 프리뷰 하단 중앙의 표준 재생·일시 정지·정지 오버레이, 배경 없는 흰색 우측 상단 X 닫기, 접근성 라벨·툴팁, 수집 종료 확인을 구현한다.
  - 구현: `CaptureWorkspaceControls`가 상태별 표준 아이콘과 접근성 이름을 제공하고, `CaptureScreen`이 전체 화면 preview·메타데이터 dialog·X 닫기·종료 확인을 연결한다.
  - 자동 검증: `CaptureWorkspaceScreenTest` APK 컴파일 성공 (2026-09-10).
- [X] T021 [US2] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`, `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadService.kt`를 연결해 정지가 열린 Episode를 완료하고 Session finalize 성공 뒤 자동 업로드와 업로드 상태 목적지를 시작하게 한다.
  - 구현: `finalizeCapture`가 열린 marker를 완료한 후 `AndroidCaptureRuntime.stop`의 finalize 결과를 저장하고 `startUpload`로 `UploadStatus` 목적지를 연다. `SessionUploadService`가 기존 취소 시 `FAILED` 저장 계약을 유지한다.
  - 자동 검증: `./gradlew.bat testDebugUnitTest --no-daemon` 성공 (2026-09-10).
- [X] T022 [US2] `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CapturePreviewControllerTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureWorkspaceScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinatorTest.kt`를 통과시키고 실제 기기에서 프리뷰가 녹화 전 표시되는지 별도 기록한다.
  - 구현/병합 대조: 최신 `origin/develop`의 `28cc090`(MR !24, merged)와 `fd029a8`, `ac7b33d`를 확인했다. `CaptureScreen` → `CapturePreviewController.prepare`/`TextureView` → `CaptureWorkspaceControls`, 첫 재생 → `AndroidCaptureRuntime.start`, 종료 확인 → `finalizeCapture` → `startUpload` 경로와 기존 테스트를 대조했으며 Phase 4는 재구현하지 않았다. Related Jira: S15P21A206-16.
  - 자동 검증: 기존 `CapturePreviewControllerTest`·`CaptureSessionCoordinatorTest` 단위 검사 성공 기록(2026-09-10)을 유지한다. 사용자 확인(2026-09-10): `SM-G973N`(Android 12)에서 `.\gradlew.bat connectedDebugAndroidTest --no-daemon` 성공. `CaptureWorkspaceScreenTest`의 실제 경로는 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/CaptureWorkspaceScreenTest.kt`이며 이전의 재실행 필요 기록을 해소했다.
  - 실제 검증: 같은 사용자 확인에서 녹화 전 전체 화면 프리뷰·Task/Object 입력 모달·하단 중앙 수집 시작 아이콘·우측 상단 닫기 접근성 이름이 실기기에서 확인됐다. `quickstart.md` Phase 4 기록과 일치하며 이 결과를 T025의 TalkBack 검증으로 확대하지 않는다. 기존 로컬 증거 `app/build/capture-preview-before-recording.png`는 커밋 제외.

**검증 지점**: 텍스트 버튼 없이 제어 아이콘으로 Session과 Episode를 만들고, 정지는 자동 전송 상태 화면으로 이어진다.

---

## Phase 5: 사용자 스토리 3 - 제어 상태와 종료 방지 (우선순위: P2)

**목표**: 프리뷰를 가리지 않고 가능한 제어를 전달하며, 실수로 수집을 끝내지 못하게 한다.

**독립 검증**: 준비·Episode 진행·Episode 없음/Session 수집·확정 상태에서 활성 아이콘이 다르고, 정지·뒤로 가기·닫기에는 확인을 제공하는지 확인한다.

- [X] T023 [P] [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`에 네 수집 상태의 아이콘 활성화, 확정 중 중복 입력 차단, 정지·뒤로 가기·닫기 확인 테스트를 작성한다.
  - 구현: `src/test/.../ui/CaptureControlStateTest.kt`의 네 상태·준비 실패·작업 잠금·종료 확인 정책 4개 테스트와 `src/androidTest/.../ui/CaptureControlStateScreenTest.kt`의 비활성 제어/진행 표시·프리뷰 차단·툴팁·확인/취소·시스템 Back/X 5개 테스트. UI는 기존 프로젝트 구성에 따라 `androidTest`에 배치했다.
  - 자동 검증: 구현 전 `testDebugUnitTest --tests '*CaptureControlStateTest' --no-daemon`에서 새 정책/확정 상태 미구현으로 실패함을 확인한 뒤 구현했다. 구현 후 `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug connectedDebugAndroidTest --no-daemon` 성공(2026-09-10). 단위 52개·connected 14개 모두 통과하며 신규 9개 테스트를 포함한다.
  - 실제 검증: connected suite는 `SM-G973N`(Android 12)에서 실행했다. TalkBack 실사용 검증은 2026-09-11 사용자 결정으로 필수 조건에서 제외했다. Related Jira: S15P21A206-17.
- [X] T024 [US3] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureWorkspaceScreen.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`에 상태별 제어 활성화, 준비 실패·확정 중 일회성 안내, BackHandler·전체 화면 sheet X 닫기 확인을 구현한다.
  - 구현/production: `MainActivity.kt`의 `CaptureScreen.controlPolicy` → `CaptureWorkspaceControls`/`CaptureWorkspaceExitControls`와 재생·일시 정지·정지·`requestCaptureExit`/`finalizeCapture`가 같은 정책을 사용한다. `CaptureControlPolicy.kt`는 준비·Episode 진행·Session 유지·확정의 네 상태를 정의한다. 시작/저장 잠금과 확정 잠금은 비동기 실행 전에 설정하고 완료·실패 시 해제해 중복 입력을 차단한다.
  - 안내/접근성: 첫 preview frame·유효한 메타데이터가 준비되기 전 재생 차단, 프리뷰 실패 Snackbar, 확정 진행 표시, `CaptureTooltip`의 리소스 라벨과 길게 누르기, `CaptureStopConfirmation`의 공통 확인/취소를 연결했다. 확정 처리는 IO에서 수행하고 동시에 interrupt하지 않으며 백그라운드에서 끝나면 전송을 지속하지 않고 재전송 가능한 Detail로 보존한다. `contracts/capture-control-ui.md`와 `plan.md`에 제어 정책을 반영했다.
  - 자동 검증: T023의 전체 명령 성공. `CaptureControlStateTest`의 상태/잠금/확인 정책과 `CaptureControlStateScreenTest`의 `finalizing_disables_controls_and_exposes_progress`, `system_back_and_close_share_exit_callback_and_finalizing_blocks_both`, `stop_confirmation_explains_upload_and_separates_cancel_from_confirm` 통과.
  - 외부 검증: SM-G973N에서 UI instrumentation 성공. TalkBack 실사용은 필수 범위에서 제외하고, 실제 카메라·센서/확정 중 백그라운드·서버 전송은 T035에 별도 기록하며 자동 검증으로 대체하지 않는다.
- [X] T025 [US3] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateTest.kt`와 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/CaptureControlStateScreenTest.kt`로 제어 상태·입력 차단·종료 확인·아이콘 이름·툴팁 표시를 자동 검증한다.
  - 자동 검증 완료: T023의 `CaptureControlStateTest` 4개와 SM-G973N의 `CaptureControlStateScreenTest` 5개가 성공했다. 아이콘 semantics, 비활성 입력 차단, `long_press_shows_accessible_control_tooltip`을 검증했다.
  - 구현/호출 경로: T024의 `CaptureScreen.controlPolicy` → 제어 콜백·`CaptureWorkspaceControls`·`CaptureWorkspaceExitControls`·`CaptureStopConfirmation`을 대조했다. 구현 커밋 `fda4294`는 `3c26f5b`로 develop에 병합됐고 코드 변경 없이 기존 테스트 근거를 유지한다.
  - 완료 조건 변경(2026-09-11): 사용자가 배포용이 아닌 개발용 앱이므로 접근성 목적의 TalkBack 검증이 불필요하다고 결정했다. `spec.md`, `plan.md`, UI 계약과 `quickstart.md`를 함께 갱신했다. 실제 TalkBack 검증은 수행하지 않았으며 필수 인수 조건에서 제외한 결과로 완료 처리한다. Related Jira: S15P21A206-17.

### 요청 범위 수렴 대조 (2026-09-10)

- `$speckit-converge`: 사용자 지정 범위 T022·Phase 5에 한정해 US3 인수 시나리오 4개, FR-008/FR-008a/FR-009, 준비/확정 중 중복 입력 엣지 케이스, 단일 모듈·부모 상태 소유·리소스 문자열·기존 데이터/전송 계약을 코드와 대조했다. Constitution은 미작성 템플릿이므로 강제 원칙 검사는 생략했다. 확장 hook 설정은 없다.
- 당시 구현 연결·자동 검증 범위에서 추가 미구현은 발견하지 않았으나 T025의 TalkBack 실사용 검증이 남아 완료를 보류했다.
- 재대조(2026-09-11): 사용자 결정으로 TalkBack 필수 조건을 제외한 명세·계획·T022~T025를 병합된 production 코드 및 2026-09-10 자동 검사 근거와 대조했다. 요청 범위 T022·Phase 5는 `converged`이며 추가 remediation task는 없다. Phase 6·7 및 T035의 실제 수집·서버 검증은 이번 완료 판정에 포함하지 않는다.

**검증 지점**: 사용자는 상시 상태 문구 없이 가능한 다음 조작을 알 수 있고, 수집 종료 전 확인 기회를 받는다.

---

## Phase 6: 사용자 스토리 4 - Session Detail과 업로드 상태 (우선순위: P2)

> 2026-09-18, S15P21A206-34으로 별도 업로드 상태 화면을 없앴다. 이 Phase의 task는 당시 구현을
> 기록한 것이며, 전송 진행·결과는 이제 Session Detail이 맡는다. 현재 계약은
> [contracts/capture-control-ui.md](contracts/capture-control-ui.md)의 "전송 동작"을 따른다.

**목표**: Detail에서 수집 내용을 확인하고 전송·재전송을 시작하며, 별도 업로드 상태 화면에서 진행·완료·실패·취소를 관리한다.

**독립 검증**: 로컬 보관·실패 Session Detail에서 전송·재전송을 시작하고, 업로드 상태 화면에서 로딩·종료·이탈 확인·백그라운드 중단 뒤 retry를 확인한다.

- [X] T026 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/SessionDetailScreenTest.kt`에 Detail 수집 시각·길이·완료 Episode 개수·데이터 상태와 전송/재전송 행동 테스트를 작성한다.
  - 구현/production: `SessionDetailPresentation`이 `SessionDetailScreen`의 길이와 전송/재전송 행동을 결정하며, 화면은 기존 수집 시각·ID·완료 Episode 개수·데이터 상태·동영상/전체 화면 경로를 유지한다.
  - 자동 검증: `SessionDetailScreenTest`의 `detail presentation retains duration episode data source and upload action`, `failed session exposes retry while completed upload exposes no action`.
- [X] T027 [P] [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/UploadStatusScreenTest.kt`에 비결정적 진행 표시, 화면 이탈 경고 문구, 완료/실패 상태, 뒤로 가기 취소 확인, lifecycle background 취소 테스트를 작성한다.
  - 구현/production: `UploadStatusScreen`은 `UPLOADING`에서 indeterminate indicator·이탈 경고·확인 dialog를 표시하고 `uploadExitAction`으로 terminal 상태와 구분한다. `CaptureScreen`의 `ON_STOP`은 해당 화면의 Job을 즉시 취소한다.
  - 자동 검증: `UploadStatusScreenTest`의 uploading 이탈 확인·terminal 직접 복귀·lifecycle stop 취소 정책과 `SessionUploadServiceTest.cancelled upload persists failed`.
- [X] T028 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`, `app/src/main/res/drawable/`, `app/src/main/res/values/strings.xml`에 Session 식별 정보·수집 시각·길이·완료 Episode 개수·데이터 상태·로컬 원본 동영상 재생·전체 화면 확장, 상태별 전송·재전송 행동과 좌측 상단 뒤로가기 아이콘을 구현한다.
  - 구현/production: `CaptureScreen`의 `SessionDetail`/`SessionVideo` 목적지 → `SessionDetailScreen`/`FullScreenVideoScreen`과 `SessionDetailPresentation` 경로.
- [X] T029 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/upload/UploadStatusScreen.kt`와 `app/src/main/res/values/strings.xml`에 비결정적 로딩, 화면 이탈 경고, 성공·실패 표시와 취소 확인 dialog를 구현한다.
  - 구현/production: `UploadStatusScreen`의 `CircularProgressIndicator`, 상태 문구와 취소 dialog가 `CaptureScreen`의 `UploadStatus` 목적지에서 호출된다.
- [X] T030 [US4] `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`와 `app/src/main/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadService.kt`에 Detail·정지의 공통 전송 시작, Upload Status 화면 소유 Job, back/close 확인 취소, `ON_STOP` 즉시 취소 및 `FAILED` persist를 연결한다.
  - 구현/production: Detail과 capture finalize가 공통 `startUpload`를 호출하며, 확인된 이탈과 `ON_STOP`은 `uploadJob.cancel()` → `SessionUploadService`의 cancellation handler → `FAILED` 저장으로 연결된다.
- [X] T031 [US4] `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/SessionDetailScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/ui/UploadStatusScreenTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploadServiceTest.kt`, `app/src/test/java/com/ssafy/s15p21a206/tiger/upload/SessionUploaderTest.kt`를 통과시키고 MockWebServer에서 `201`, `200 duplicate`, 네트워크 실패, 취소를 확인한다.
  - 자동 검증: `./gradlew.bat ktlintCheck testDebugUnitTest --tests "com.ssafy.s15p21a206.tiger.ui.SessionDetailScreenTest" --tests "com.ssafy.s15p21a206.tiger.ui.UploadStatusScreenTest" --tests "com.ssafy.s15p21a206.tiger.upload.SessionUploadServiceTest" --tests "com.ssafy.s15p21a206.tiger.upload.SessionUploaderTest" --rerun-tasks --no-daemon --offline` 성공 (2026-09-11). `SessionUploaderTest`가 MockWebServer의 `201`, `200 duplicate`, 네트워크 실패·취소를 검증한다.

**검증 지점**: Detail은 전송을 시작하고, 업로드 상태 화면은 polling 없이 진행을 보여 주며 이탈·백그라운드 중단 후 재전송을 보장한다.

---

## Phase 7: 마무리와 교차 검증

**목적**: 사용자 흐름·계약·자동/실제 기기 검증을 하나로 확인한다.

- [X] T032 [P] `app/src/main/res/values/strings.xml`과 `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/`의 사용자 문구·content description·툴팁을 점검해 하드코딩 문자열과 접근성 누락을 수정한다.
  - 구현/검토: UI 사용자 문구와 `contentDescription`은 리소스 기반임을 대조했다. `UploadStatusScreen`의 뒤로가기 설명, 진행 표시 설명 및 취소 확인 문구를 추가하고, 재구성 시 취소 dialog 상태가 유지되도록 `remember`를 적용했다.
  - 자동 검증: `./gradlew.bat ktlintCheck lintDebug --no-daemon --offline` 성공 (2026-09-11).
- [X] T033 [P] `specs/001-episode-recorder/spec.md`, `specs/001-episode-recorder/data-model.md`, `specs/001-episode-recorder/contracts/episode-bundle.md`, `specs/002-capture-control-ux/spec.md`, `specs/002-capture-control-ux/data-model.md`, `specs/002-capture-control-ux/contracts/capture-control-ui.md`를 구현 결과와 대조해 storage·Episode·업로드 계약 불일치를 갱신한다.
  - 검토: 내부 `filesDir/capture/completed/<session_id>` 경계, `CANCELLED` 미사용, 완료 Episode 집계, 업로드 취소/백그라운드 전환의 `FAILED` 저장, legacy 외부 bundle 제외를 production 경로와 대조했다. 계약 불일치가 없어 문서 내용 변경은 필요하지 않았다.
- [X] T034 `specs/002-capture-control-ux/quickstart.md`에 따라 `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug`, `.\gradlew.bat assembleDebug`, `.\gradlew.bat ktlintCheck`를 실행하고 명령·결과를 각 완료 task의 증거로 기록한다.
  - 자동 검증: `./gradlew.bat testDebugUnitTest lintDebug assembleDebug ktlintCheck --no-daemon --offline` 성공 (2026-09-11). Lint는 오류 0건, 기존 경고 56건이며 debug APK가 생성됐다.
- [X] T035 `specs/002-capture-control-ux/quickstart.md`에 따라 실제 기기와 ingestion server에서 프리뷰, 수집 제어, 자동 업로드, 취소, 백그라운드 중단, 재전송, legacy 제외를 검증하고 결과를 `specs/002-capture-control-ux/quickstart.md`에 기록한다.
  - 부분 실제 검증(2026-09-11): `SM-G973N`(Android 12, 4KB page)의 `./gradlew.bat connectedDebugAndroidTest --no-daemon --offline`가 14개 테스트를 실패·건너뜀 없이 통과했다. 실제 camera/AR 프리뷰·ingestion server 자동 업로드·취소·백그라운드 중단·재전송·legacy 외부 bundle 수동 검증은 아직 남아 있다 (`quickstart.md`).
  - 부분 실제 검증(2026-09-14): `SM-G973N`(Android 12, page size 4096)에서 Task/Object 입력 뒤 카메라 프리뷰를 열고 실제 수집을 시작·종료했다. 종료 확인 뒤 `업로드 중` 진행 표시와 이탈 경고를 확인했고, 앱을 강제 종료·재시작한 뒤 Session Detail에서 `업로드 완료`를 확인했다. 업로드가 짧은 시간 안에 완료되어 취소·업로드 중 백그라운드 전환·실패 후 재전송은 재현하지 못했고, legacy 외부 bundle 수동 제외 검증도 남아 있다 (`quickstart.md`).
  - 완료 범위 결정(2026-09-14): 사용자 지시에 따라 내부 개발용 앱의 이번 완료 판정은 실제 프리뷰·수집 제어·ingestion server 자동 업로드 확인까지로 한정한다. 업로드 취소·업로드 중 백그라운드 중단·실패 재전송·legacy 외부 bundle 수동 검증은 통과했다고 주장하지 않으며, 후속 실제 기기 검증으로 보류한다. 관련 취소·백그라운드·재전송·legacy 경계의 자동 검증은 기존 T004·T009·T027·T031 및 저장소 테스트로 유지한다.
- [X] T037 [P] `gradle/libs.versions.toml`의 ARCore와 생성 APK를 Android 15+ 16KB 페이지 환경에서 실행해 카메라·AR 세션 생성과 수집 흐름을 검증한다. `lintDebug`의 `Aligned16KB` 경고와 `zipalign -c -P 16 -v 4` 결과를 함께 기록한다.
  - 자동 검증(2026-09-09): `com.google.ar:core:1.56.0`으로 `ktlintCheck testDebugUnitTest assembleDebug lintDebug` 성공, 강제 재실행한 Lint report에서 `Aligned16KB` 0건, `zipalign -c -P 16 -v 4 app/build/outputs/apk/debug/app-debug.apk` 성공.
  - 내부 개발용 범위 결정(2026-09-11): 사용자 지시에 따라 `SM-G973N`(Android 12, page size 4096)을 기준 기기로 삼으며, Android 15+ 16KB 페이지 실기기/에뮬레이터 검증은 요구하지 않는다.
  - 자동 검증: `./gradlew.bat lintDebug assembleDebug --no-daemon --offline` 성공했고 `Aligned16KB` 오류는 없었다. Android SDK Build Tools 36.0.0의 `zipalign.exe -c -P 16 -v 4 app/build/outputs/apk/debug/app-debug.apk`가 `Verification successful`을 반환했다.
- [X] T036 `specs/002-capture-control-ux/tasks.md`의 각 완료 task에 구현 파일·production 호출 경로·자동 검증·실제 기기 검증 근거를 기록한 뒤 `$speckit-converge`를 실행한다.
  - 수렴 검사(2026-09-14): `$speckit-converge` 절차로 `spec.md`·`plan.md`·`tasks.md`와 production 경로를 대조했다. 내부 completed root/legacy 제외, 수집 확정의 자동 업로드 전환, 업로드 이탈 확인·`ON_STOP` 취소·`FAILED` 보존이 명세와 일치하며 새 구현 remediation task는 없다. T035의 취소·업로드 중 백그라운드 중단·실패 재전송·legacy 외부 bundle 실제 검증은 구현 누락이 아닌 미완료 검증으로 남겼다. `.specify/extensions.yml`은 없다.

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

---

## 정합화 기록 (2026-09-14, 003-session-episode-tracking-gate)

T021의 대상 파일 목록에 `CaptureSessionCoordinator.kt`가 포함되어 있으나, 실제 구현은 Coordinator를
거치지 않았다. 같은 task의 증거 항목이 기록한 대로 `finalizeCapture` → `AndroidCaptureRuntime.stop`
→ `startUpload` 경로로 구현되었다.

T021이 요구한 동작(정지가 열린 Episode를 완료하고 finalize 성공 뒤 자동 업로드와 업로드 상태
목적지를 시작한다)은 충족되어 있으므로 완료 판정은 유지한다. 파일 목록의 사실관계만 여기에 기록한다.

`CaptureSessionCoordinator`는 003 기능의 T009에서 `MainActivity`에 연결되었다. 이 시점부터 Session과
Episode 상태의 단일 판단 주체는 Coordinator다.

---

## 정합화 기록 (2026-09-17, S15P21A206-40)

T014·T015·T016·T028의 완료 증거는 `AppDestination` sealed 목적지와 `CaptureScreen`의 destination
`when` 분기를 production 호출 경로로 기록했다. S15P21A206-40에서 조회 흐름을 Navigation Compose로
이관해 그 구조가 없어졌다. 현재 호출 경로는 `CaptureScreen`의 `NavHost`와 목적지별 `composable`
블록이며, 각 화면의 이탈은 `navController.popBackStack()`이다. 수집 작업 공간은 목적지에서 빠지고
`capturing` boolean이 제어하는 `NavHost` 위의 모달이 되었다.

각 task가 요구한 동작(시작 화면, Task 그룹·Session 요약·Detail 전환, 목록에서 Detail로의 이동, 좌측
상단 뒤로가기 아이콘)은 그대로 충족되므로 완료 판정은 유지한다. 구조 변경 사실만 여기에 기록한다.

이관으로 새로 충족된 범위는 다음과 같다.

- 모든 조회 화면에서 시스템 뒤로 가기가 직전 화면으로 이동한다. 이전에는 `BackHandler`가 있는 수집
  작업 공간과 업로드 상태를 뺀 화면에서 앱이 종료됐다.
- Session Detail의 이탈 대상 하드코딩(`TaskSessions(summary?.taskName.orEmpty())`)을 제거했다.
- 프로세스 재생성 시 조회 흐름의 백스택을 복원한다.

아직 남은 검증은 아래 두 task로 나눈다. 업로드 상태 화면의 뒤로 가기는 자동화할 수 있는 부분이
있어 T039로 분리했다.

- [ ] T038 [S15P21A206-40] 실기기에서 뒤로 가기 동작을 확인한다.
  - 실제 검증 완료(2026-09-17, `SM-G973N`, Android 12): 조회 화면별 시스템 뒤로 가기, Task 홈에서의
    앱 종료, 수집 작업 공간의 종료 확인, 목적지 전환 시 잔상 없음을 사용자가 확인했다.
  - 남은 항목: **업로드가 실제 진행 중인 상태에서의 뒤로 가기 취소 확인**. 이 경로는 확인되지
    않았다. `BuildConfig.UPLOAD_BASE_URL`과 도달 가능한 ingestion server가 필요하다.
  - 남은 항목: 프로세스 재생성 후 화면 복원. 개발자 옵션의 "활동 유지 안 함"으로 확인한다.
- [X] T039 [S15P21A206-40] `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/upload/UploadStatusBackNavigationTest.kt`로
  업로드 상태 화면의 `BackHandler`가 `NavHost`의 백스택 pop보다 우선하는지 고정한다.
  - 구현: `UploadStatusScreen`을 다른 목적지 위에 쌓은 `NavHost`에 넣고, `UPLOADING`에서 뒤로 가기가
    취소 확인을 띄우며 목적지를 벗어나지 않는지, 중단 확인이 이전 목적지로 돌아가는지, 종료 상태에서는
    확인 없이 돌아가는지 검사한다. 세 테스트 모두 `OnBackPressedDispatcher.onBackPressed()`를 직접
    호출한다.
  - 자동 검증: `UploadStatusBackNavigationTest.uploading_back_press_confirms_instead_of_leaving_the_destination`,
    `confirming_cancellation_cancels_the_upload_and_returns_to_the_previous_destination`,
    `terminal_state_back_press_returns_without_confirmation`;
    `.\gradlew.bat connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.ssafy.s15p21a206.tiger.ui.upload.UploadStatusBackNavigationTest`
    성공 (2026-09-18, `SM-G973N`, Android 12). 3 tests, 0 failures, 0 errors.
    목적지 안의 `BackHandler`가 `NavHost`의 pop보다 우선한다는 가정이 실기기에서 확인되었다.
  - 범위 한계: 프레임워크 동작만 고정한다. `MainActivity`의 배선을 검증하지 않으므로 T038의 실기기
    확인을 대신하지 않는다.

## 추가 범위 (2026-09-18, S15P21A206-35)

Session을 기기에서 지우는 범위를 FR-016·FR-016a~d로 명세에 추가했다. 서버에 DELETE API가 없으므로
삭제는 기기의 색인과 번들에만 미친다.

- [X] T040 [S15P21A206-35] `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`,
  `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleStore.kt`,
  `app/src/main/java/com/ssafy/s15p21a206/tiger/episode/SessionRepository.kt`에 Session 단위 삭제와
  고아 번들 회수를 구현한다.
  - 구현: `CaptureSessionDao.delete`·`allSessionIds`, `EpisodeMarkerDao.deleteForSession`,
    `SessionBundleStore.deleteCompletedBundle`·`orphanCompletedBundles`,
    `SessionRepository.delete`·`purgeOrphanBundles`와 `SessionDeleteResult`. 색인(마커·세션 행)을
    먼저 지우고 디렉터리를 지우므로, 디렉터리 삭제가 실패해도 목록에는 고아가 남지 않는다.
    `UPLOADING` 상태는 거절한다.
  - production 호출 경로: `MainActivity.kt`의 `CaptureScreen`이 `deleteSession(sessionId)`에서
    `repository.delete`를, 시작 `LaunchedEffect(repository)`에서 `repository.purgeOrphanBundles()`를
    호출한다. 회수는 `recoverInterruptedStaging()` 뒤에 돈다.
  - 자동 검증: `SessionRepositoryTest.deleting a session removes its index row, markers and bundle`,
    `deleting a session that is uploading is refused`,
    `a bundle left behind by a failed delete is purged on the next run`,
    `purging orphan bundles keeps bundles of sessions that are not completed yet`,
    `a deleted session does not come back through staging recovery`;
    `.\gradlew.bat testDebugUnitTest` 성공 (2026-09-18).
- [X] T041 [S15P21A206-35] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/session/SessionDetailPresentation.kt`,
  `app/src/main/java/com/ssafy/s15p21a206/tiger/MainActivity.kt`,
  `app/src/main/res/values/strings.xml`,
  `app/src/main/res/drawable/ic_session_delete.xml`에 상세 화면의 삭제 진입점과 확인 흐름을 붙인다.
  - 구현: `SessionDeleteAction`이 업로드 상태로 확인 문구를 가르고(`UPLOADED`는 `DeleteLocalCopy`,
    `LOCAL_ONLY`·`FAILED`는 `DeleteOnlyCopy`, `UPLOADING`은 `null`), `SessionDetailScreen`의
    헤더 메뉴가 `SessionDeleteConfirmation`을 띄운다. 삭제하면 `popBackStack()`으로 돌아가고,
    거절당하면 상세에 사유만 남는다. 문구는 전부 `strings.xml`에 있다.
  - 이후 변경(T044): 진입점이 삭제 아이콘에서 `세션 정보`·`세션 삭제`를 담은 헤더 메뉴로 바뀌었고,
    `SessionDeleteAction`과 확인 판은 목록과 공유하려고 `ui/session/SessionDelete.kt`로 옮겼다.
  - production 호출 경로: `NavHost`의 `composable<SessionDetailRoute>`가 `onDelete`에
    `deleteSession(route.sessionId)`를 넘긴다.
  - 자동 검증: `SessionDetailScreenTest.delete confirmation distinguishes an uploaded session from the only copy`,
    `a session that is uploading exposes no delete action`;
    `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug` 성공 (2026-09-18).
- [X] T042 [S15P21A206-35] `specs/002-capture-control-ux/spec.md`에 삭제 범위를 반영한다.
  - 산출물: 2026-09-18 Clarifications 두 항목, 사용자 스토리 4의 인수 시나리오 8~10, 엣지 케이스 3건,
    FR-016·FR-016a~d, 핵심 엔터티의 `Session 상세` 서술.
  - 검토 기준: 삭제가 서버 사본에 미치지 않는다는 방침, 확인 문구가 업로드 여부로 갈린다는 점,
    전송 중 삭제 금지, 색인 우선 삭제와 다음 실행 회수, 구제 경로로 되살아나지 않음이 모두 명세에 있다.
- [X] T043 [S15P21A206-35] 재생 중인 영상을 담은 Session을 실기기에서 삭제해 본다.
  - 자동화할 수 없는 이유: 상세 화면의 `ExoPlayer`가 `main_rgb.mp4`를 연 채로 그 파일이 사라진다.
    POSIX는 열린 파일의 unlink를 허용하므로 삭제 자체는 성공하지만, 파일이 사라진 뒤 재생기가
    어떻게 반응하는지는 실제 decoder로 돌려 봐야 안다. 단위 테스트에는 재생기가 없다.
  - 위험은 줄여 뒀다: 확인 판이 뜨면 `SharedVideoPlayer.pause()`로 재생을 멈추므로, 파일이
    사라질 때 재생기가 읽는 중이 아니다. 다만 파일을 연 채로 멈춰 있을 뿐 닫은 것은 아니라
    남은 경로가 완전히 없어지지는 않았다.
  - 절차: 상세 화면에서 영상을 재생한 상태로 메뉴에서 삭제하고, 확인 판이 뜰 때 재생이 멈추는지,
    목록으로 돌아간 뒤 앱이 살아 있고 소리가 남지 않는지, logcat에 재생기 예외가 없는지 본다.
    이어서 `adb shell run-as <pkg> ls files/capture/completed`로 디렉터리가 사라졌는지 함께 확인한다.
  - 실제 검증: 2026-09-21 사용자가 실기기에서 확인했다. 세부 관측 항목은 사용자가 직접 보았고
    이 기록은 그 보고에 따른다.
  - 번들 디렉터리 삭제 자체는 실기기 검증 사유가 아니다 (2026-09-18 사용자 지적).
    `SessionRepositoryTest.deleting a session removes its index row, markers and bundle`이 실제 파일을
    만들고 `assertFalse(directory.exists())`까지 본다. `File.deleteRecursively()`에 안드로이드만의
    실패 모드가 없고, 테스트가 도는 Windows 쪽이 열린 파일을 못 지워 더 엄격하다.
    다만 `AGENTS.md`가 저장소의 실기기 동작을 단위 테스트로 검증했다고 보고하지 말라고 하므로,
    이 task가 닫히기 전까지 삭제는 "단위 테스트로만 덮었고 실기기 확인은 하지 않았다"로 보고한다.
  - 범위에서 제외한 것 (2026-09-18 사용자 지적):
    - **전송 중 삭제 차단**: 사용자가 도달할 수 없는 경로다. 상세·목록 양쪽 메뉴 항목이 `UPLOADING`이면
      비활성이고, 업로드를 시작하는 경로가 모두 사용자 조작이라 확인 판이 열려 있는 동안 걸릴 수 없다.
      비활성 상태 자체는 기기가 필요 없으며
      `SessionListScreenTest.longPressOnAnUploadingSessionOffersNoEnabledDeleteAction`과
      `SessionDetailScreenTest.a session that is uploading exposes no delete action`이 고정한다.
    - **재실행 후 되살아나지 않음**: 되살릴 수 있는 경로는 `recoverInterruptedStaging()` 하나이고
      Room 행이 없으면 대상이 아니다.
      `SessionRepositoryTest.a deleted session does not come back through staging recovery`가 고정한다.
      나머지는 SQLite가 DELETE를 유지하느냐의 문제라 이 코드가 관여하지 않는다.

## 추가 범위 (2026-09-18, S15P21A206-35 후속 정비)

삭제를 실기기에서 확인하는 과정에서 진입점·확인 판·빈 상태를 다시 잡았다. FR-016 갱신과
FR-016e~g 추가가 여기에 대응한다.

- [X] T044 [S15P21A206-35] 상세 헤더의 아이콘 둘을 메뉴 하나로 접고, 목록 카드에 길게 눌러 삭제를 붙인다.
  - 구현: `MainActivity.kt`의 `SessionDetailMenu`(⋮ → `세션 정보`·`세션 삭제`),
    `SessionListScreen.kt`의 `SessionSummaryItem`이 `combinedClickable`의 `onLongClick`으로
    메뉴를 연다. 메뉴는 누른 지점에 둔 크기 0짜리 앵커에 건다. 좌표는 `PointerEventPass.Initial`에서
    기록만 하고 소비하지 않아 탭·ripple·접근성 동작이 유지된다. `SessionDeleteAction`과
    `SessionDeleteConfirmation`은 상세·목록이 같은 판단을 하도록 `ui/session/SessionDelete.kt`에 둔다.
  - production 호출 경로: `NavHost`의 `composable<TaskSessionsRoute>`가 `onDeleteSession`에
    `deleteSession`을 넘긴다. `deleteSession`은 상세에 있을 때만 `popBackStack()`한다.
  - 자동 검증: `SessionListScreenTest.longPressDeletesASessionOnlyAfterConfirmation`,
    `longPressOnAnUploadingSessionOffersNoEnabledDeleteAction`;
    `.\gradlew.bat connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.ssafy.s15p21a206.tiger.ui.session.SessionListScreenTest`
    (2026-09-18, `SM-G973N`, Android 12) 두 테스트 통과.
  - 해결됨: 같은 클래스의 `emptyListShowsStartCaptureAction`은 이 작업과 무관한 기존 결함으로
    실패하고 있었다. S15P21A206-43으로 분리했고, `fix/fab-accessible-name`이 develop에 병합된 뒤
    rebase하면서 통과한다 (2026-09-21).
- [X] T045 [S15P21A206-35] 되돌릴 수 없는 확인 판을 한 곳으로 모은다.
  - 구현: `ui/common/DestructiveConfirmationDialog.kt`. `CaptureStopConfirmation`과
    `SessionDeleteConfirmation`이 이 판을 쓴다. 확정 쪽은 채워진 error 버튼으로 통일했다.
    세션 삭제만 빨간 글씨 `TextButton`이라 같은 무게의 결정이 다르게 보였다.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug compileDebugAndroidTestKotlin`
    성공 (2026-09-21).
  - 계측 검증: `CaptureControlStateScreenTest.stop_confirmation_explains_upload_and_separates_cancel_from_confirm`이
    `CaptureStopConfirmation`의 메시지·취소·확정을 고정한다. 이 task가 그 Composable의 속을
    `DestructiveConfirmationDialog`로 바꿨으므로 기기에서 다시 돌렸고 통과한다
    (2026-09-21, `SM-G973N`, Android 12).
- [X] T046 [S15P21A206-35] 빈 목록 안내를 고쳐 쓰고 Task Session 목록에도 둔다.
  - 구현: `session_list_empty`가 FAB 이름을 불러 준다(`새 세션을 눌러 추가하세요`).
    `task_session_list_empty`를 추가했다. 마지막 세션을 삭제하면 닿게 되는 상태로, 삭제를 붙이기
    전에는 세션이 있는 Task만 홈에 나타나 도달할 수 없었다. 두 화면이 `EmptyListMessage`를
    공유하며, 비었을 때는 `LazyColumn` 대신 `Column`으로 남은 공간 가운데에 놓고 `bodyLarge`로 키운다.
  - 자동 검증: `.\gradlew.bat testDebugUnitTest`, `.\gradlew.bat lintDebug` 성공 (2026-09-18).
  - 계측 검증: 홈 빈 상태는 `emptyListShowsStartCaptureAction`이, Task 목록 빈 상태는 T054의
    `anEmptyTaskSessionListExplainsHowToAddOne`이 고정한다. 둘 다 통과 (2026-09-21, `SM-G973N`).
    앞의 것은 S15P21A206-43이 develop에 병합되기 전까지 실패해 근거로 쓸 수 없었다.
- [X] T047 [S15P21A206-35] `specs/002-capture-control-ux/spec.md`에 위 변경을 반영한다.
  - 산출물: 2026-09-18 Clarifications 2건(목록 진입점, 밀어서 삭제를 쓰지 않는 이유),
    사용자 스토리 4의 인수 시나리오 11~12, FR-016 개정, FR-016e~g, 핵심 엔터티의 `Session 상세` 보강.
  - 검토 기준: 목록 진입점과 그 형태 제약, 확인 판의 통일, 빈 목록 안내가 모두 명세에 있다.

## Phase 8: Convergence

- [X] T048 `contracts/capture-control-ui.md`의 화면·진입점 표에서 Session Detail의 "우측 상단 정보 아이콘"을 `세션 정보`·`세션 삭제`를 담은 헤더 메뉴로 고치고, Task Session 목록 행에 길게 눌러 여는 삭제 진입점을 적는다 per FR-016, FR-016e (contradicts)
- [X] T049 `contracts/capture-control-ui.md`에 삭제 동작 절을 추가한다. 기기에서만 지운다는 방침, 업로드 여부로 갈리는 확인 문구, 전송 중 금지, 색인 우선 삭제와 다음 실행 회수, 되돌릴 수 없는 확인 판의 공통 형태, 확인 판이 뜨는 동안 영상 재생을 멈춘다는 규칙을 포함한다 per FR-016, FR-016a, FR-016b, FR-016c, FR-016f (missing)
- [X] T050 `contracts/capture-control-ui.md`의 `조회 화면의 짜임`에서 "상세의 세션 정보는 상단 우측 아이콘으로 연다"를 메뉴로 접은 현재 짜임과 그 이유로 고치고, 목록 카드가 삭제 표를 상주시키지 않는다는 제약을 적는다 per FR-016, FR-016e (contradicts)
- [X] T051 `specs/002-capture-control-ux/plan.md`에 삭제의 설계 결정을 기록한다. 색인을 먼저 지우고 디렉터리를 지우는 순서, 실패 시 고아 디렉터리를 다음 실행이 회수하는 경로, 서버 DELETE API가 없다는 제약을 포함한다 per plan: 저장소 정책 (missing)
- [X] T052 `specs/002-capture-control-ux/data-model.md`에 삭제가 더한 DAO 연산(`CaptureSessionDao.delete`·`allSessionIds`, `EpisodeMarkerDao.deleteForSession`)과 고아 번들 회수 수명주기를 반영한다 per FR-016, FR-016c (missing)
- [X] T053 `specs/002-capture-control-ux/spec.md`의 성공 기준에 삭제 항목을 추가한다. 목록·번들·색인에서 사라지고 재실행 후에도 돌아오지 않는다는 측정 가능한 결과를 포함한다 per FR-016 계열 (missing)
- [X] T054 `app/src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/session/SessionListScreenTest.kt`에 Task Session 목록의 빈 상태를 고정하는 계측 테스트를 추가한다. 홈 빈 상태를 보던 `emptyListShowsStartCaptureAction`은 S15P21A206-43이 해결될 때까지 근거로 쓸 수 없다 per FR-016g (partial)

### Phase 8 완료 증거 (2026-09-21)

- T048·T049·T050 산출물: `contracts/capture-control-ui.md`. 진입점 표의 Session Detail 행을 헤더 메뉴로,
  Task Session 목록 행에 길게 눌러 삭제를 적었다. `삭제 동작` 절을 새로 두어 기기 한정 방침, 확인 문구
  분기, 전송 중 금지, 색인 우선 삭제와 고아 회수 순서, 확인 판의 공통 형태, 확인 중 재생 정지, 삭제 뒤
  이동을 기록했다. `조회 화면의 짜임`에서 세션 정보 아이콘 서술을 메뉴로 고치고 목록 진입점·메뉴 위치·
  빈 상태 규칙을 더했다.
- T051 산출물: `plan.md` 요약에 삭제 방침과 색인 우선 삭제 순서를 두 저장소에 걸친 동작으로 설명하고,
  제약에 `서버 DELETE API 없음`을 더했다.
- T052 산출물: `data-model.md`의 `삭제 연산`·`고아 번들 수명주기` 절과 저장소 불변식 한 줄. DAO 연산
  다섯과 `SessionDeleteResult` 세 값, 앱 시작 시 실행 순서를 적었다.
- T053 산출물: `spec.md` 성공 기준 SC-010~012.
- T054 구현: `SessionListScreenTest.anEmptyTaskSessionListExplainsHowToAddOne`이 Task Session 목록의
  빈 안내가 보이고 `0개의 Session`이 없는지 검사한다.
- 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug compileDebugAndroidTestKotlin` 성공
  (2026-09-21).
- 계측 검증: androidTest 전체를 실기기에서 돌렸다 (2026-09-21, `SM-G973N`, Android 12).
  **20 tests, 0 failures.**

  ```text
  ExportMigrationTest:.            SessionExportUiTest:..
  CaptureSessionOrderTest:.        CaptureControlStateScreenTest:.......
  CaptureWorkspaceScreenTest:...   SessionListScreenTest:......
  Time: 15.48 / OK (20 tests)
  ```

  실행 방법은 `AGENTS.md`의 "계측 테스트 실행"에 있다. 요약하면 APK를 만들어 `adb install -r`로
  한 번 깔고 `adb shell am instrument -w -r`로 반복 실행한다. 이 결과는 출력의 `OK (20 tests)`를
  읽어 판정했다. `am instrument`는 테스트가 실패해도 exit code 0을 돌려주므로 종료 코드로
  판정하지 않는다.

  `connectedDebugAndroidTest`는 이 기기에서 쓰지 않았다. 매 실행마다 APK를 다시 설치하는데
  앱 APK가 42MB라 기기에서 dex2oat이 수 분씩 걸린다. 32분을 기다려도 테스트가 시작되지 않았고,
  같은 테스트가 이미 설치된 APK로는 15초에 끝난다. 전송이 아니라 기기에서의 컴파일이 병목이다
  (`adb push`는 74MB/s로 측정됐다).
- `origin/develop`에 `fix/fab-accessible-name`이 병합되면서 S15P21A206-43이 해결됐다.
  그동안 실패하던 `emptyListShowsStartCaptureAction`이 통과하므로, T046의 "홈 빈 상태를
  검사하는 테스트를 근거로 쓸 수 없다"는 범위 한계는 해소됐다.

## 추가 범위 (2026-09-22, S15P21A206-45)

Task와 Object를 Session 색인에 저장하는 범위를 FR-013e·FR-013f로 명세에 추가하고, FR-013c의
세션 정보 항목에 Object를 더했다. 두 이름은 수집 시작 때 입력받지만 `episode_markers` 행에만
실려, Object는 어디에도 표시되지 않고 Episode가 0개인 Session은 Task까지 사라졌다.

- [X] T055 [S15P21A206-45] `app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt`에
  `sessions.task`·`sessions.objectName` 컬럼과 v4 → v5 이관을 두고, 목록 조회가 Episode 집계
  대신 Session 행을 읽게 한다.
  - 구현: `CaptureSessionEntity`에 두 컬럼, `SessionSummaryEntity.objectName`,
    `observeCompletedSummaries`의 `COALESCE(MIN(NULLIF(episode_markers.task, '')), '')`를
    `sessions.task AS taskName, sessions.objectName AS objectName`으로 교체. `MIGRATION_4_5`와
    `SESSION_METADATA_MIGRATION_SQL`은 컬럼 추가 두 문장과 Episode 행에서 값을 옮기는 `UPDATE`
    한 문장이다. 채워 넣기가 없으면 조회가 집계를 떠나는 순간 이미 쌓인 Session이 전부
    `이름 없는 Task`로 떨어진다.
  - production 호출 경로: `TigerApplication.database`의 `addMigrations(MIGRATION_2_3,
    MIGRATION_3_4, MIGRATION_4_5)`.
  - 자동 검증: `TigerDatabaseMigrationTest.version five migration adds the two session metadata
    columns`, `version five migration backfills both names from existing episode rows`,
    `SessionSummaryRepositoryTest.a session without episodes still carries its task and object`;
    `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22, 138 tests).
  - 계측 검증: `SessionMetadataMigrationTest`(실제 SQLite에서 v4 → v5 채워 넣기),
    `SessionMetadataQueryTest`(Episode 0개 Session의 조회 결과). 실기기에서 통과했다 (T058).

- [X] T056 [S15P21A206-45] `app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt`,
  `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureDriver.kt`에서 Session을 저장하는
  모든 경로가 입력받은 두 이름을 함께 쓰게 한다.
  - 구현: `CaptureSession.task`·`objectName`에 기본값을 두지 않아 저장 경로가 값을 명시하게
    강제한다. `coordinator.start(sessionId, displayNumber, bundlePath, task, objectName)`는
    `startEpisode`와 같은 비어 있지 않음 검사를 갖는다. `CaptureDriver`의 세 저장 지점(시작
    `INITIALIZING`, `ON_STOP` `INTERRUPTED`, 마감 `COMPLETED`)이 `state.task`·`state.objectName`을
    넘긴다.
  - production 호출 경로: `CaptureWorkspace`가 쥔 `CaptureDriver`의 재생·`ON_STOP`·정지 경로.
  - 자동 검증: `CaptureSessionCoordinatorTest.a started session carries the task and object it was
    given`, `a session cannot start without both names`,
    `SessionRepositoryTest.saving a session persists the task and object it was started with`;
    같은 `testDebugUnitTest` 실행에 포함된다.

- [X] T057 [S15P21A206-45] `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/session/SessionDetailScreen.kt`,
  `app/src/main/java/com/ssafy/s15p21a206/tiger/ui/session/SessionListScreen.kt`,
  `app/src/main/res/values/strings.xml`에 Object를 표시한다.
  - 구현: 목록 카드와 상세 본문에 `Object %1$s` 줄(`session_object`). 두 자리 모두 수집 일시에
    딸린 줄(`SupportingText`)이며, 짧은 ID는 그 아래 `MetaText`로 내린다. 값이 비어 있으면
    줄째로 뺀다.
  - production 호출 경로: `SessionSummaryItem`(Task Session 목록 카드), `SessionDetailScreen`의
    본문 `ListSectionHeader`.
  - 계측 검증: `SessionDetailObjectTest.sessionDetailNamesTheObjectThatWasCaptured`,
    `sessionDetailOmitsTheObjectLineWhenThereIsNone`, `sessionInfoLeavesTheObjectToTheBody`,
    `SessionListScreenTest.sessionSummaryShowsDetailsAndOpensDetail`(Object 줄 추가),
    `aSessionWithoutAnObjectShowsNoObjectLine`. 화면을 바꾼 작업이므로
    `.\gradlew.bat compileDebugAndroidTestKotlin` 성공만으로 완료로 보지 않는다. 실행 기록은
    T059에 있다.
  - 첫 구현은 세션 정보 시트와 목록 카드에 두었고 카드에서는 `MetaText` 층이었다. T059에서
    바꿨다. 이유는 그 task에 적었다.

- [X] T058 [S15P21A206-45] androidTest 전체를 실기기에서 실행해 T055·T057의 계측 검증을 남긴다.
  `AGENTS.md`의 "계측 테스트 실행" 절차를 따르고, 출력의 `OK (N tests)` 또는 `FAILURES!!!`로
  판정한다. 이관은 기존 DB가 있는 기기에서 앱을 갱신해 목록의 Task 이름이 그대로 남는지도 함께
  확인한다.
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **27 tests, 0 failures.** 이전 기록의 20개에서
    `ApplicationScopedDependencyTest` 1개와 이번 6개가 늘었다.

    ```text
    ApplicationScopedDependencyTest:.   ExportMigrationTest:.
    SessionExportUiTest:..              SessionMetadataMigrationTest:.
    CaptureSessionOrderTest:.           SessionMetadataQueryTest:..
    CaptureControlStateScreenTest:...   CaptureWorkspaceScreenTest:...
    SessionInfoSheetTest:..             SessionListScreenTest:.......
    Time: 18.604 / OK (27 tests)
    ```

  - 이관 검증: 같은 기기에 이미 있던 v4 `tiger.db`를 갱신했다. `문도` 묶음(2개 Session)이 그대로
    남고, 카드에 `Object 56`·`Object 때린다`가, 세션 정보(`9c0a11e8`)에 `Object 56`이 나온다. 두
    이름이 `episode_markers`에서 Session 행으로 옮겨졌다는 뜻이다. 컬럼만 더했다면 이 묶음이
    `이름 없는 Task`로 떨어졌을 자리다.
  - 기존 `이름 없는 Task` 3개(`af60ee8e`, `7e142186`, `ce9c7947`)는 모두 Episode 0개이며 이관
    뒤에도 이름이 없고 Object 줄도 세우지 않는다. 설계대로다. 이 세션들의 두 이름은 어디에도
    저장된 적이 없어 채울 값이 없다. `ce9c7947`은 이 이슈의 재현 기록에 나오는 그 Session이다.
  - 남은 한계: 이번 확인은 이관과 조회·표시까지다. 새로 수집한 Session을 Episode 0개로 끝냈을
    때 두 이름이 남는지는 실제 수집을 하지 않았으므로 기기에서 확인하지 않았다. 그 경로는
    `CaptureSessionCoordinatorTest`·`SessionRepositoryTest`와 `SessionMetadataQueryTest`가 덮는다.

- [X] T059 [S15P21A206-45] Object의 위계와 자리를 고친다. `FR-013c`를 원문으로 되돌리고
  `FR-013f`·`FR-013g`를 그에 맞게 다시 쓴다.
  - 배경: 첫 구현은 Object를 세션 정보 시트와 목록 카드의 `MetaText` 층에 두었다. 둘 다
    저장소가 이미 적어 둔 기준에 어긋났다.
    - `MetaText`의 정의는 "Episode 수·길이·해상도·ID는 **무엇을 찍은 것인지 알려 주지 않으므로**
      `SupportingText`보다 한 단계 더 내린다"이다. Object는 그 화면에서 그것만 말하는 값인데
      그 층에 넣었다. 12sp 회색 세 줄 가운데 묻혀 눈에 들어오지 않았다.
    - `SessionInfoSheet`의 정의는 "세션을 특정해 주지 않는 값들을 담는 시트"이고 `FR-013c`가
      같은 말을 한다. Object는 고를 때 쓰는 값이라 들어맞지 않았고, 넣으려고 `FR-013c`를
      고쳐야 했다. 구현에 맞추려 명세를 굽힌 것이므로 되돌린다.
    - 결정적인 것은 수집 마감 직후 경로다. `onCompleted`가 수집 화면에서 상세로 바로 넘기므로
      그 경로에서는 Task 묶음도 목록 카드도 지나오지 않는다. 방금 찍은 것이 맞는지 확인하는
      자리에서 두 이름이 화면에 한 번도 나오지 않았다.
  - 구현: 카드와 상세 본문 모두 이름은 수집 일시, 딸린 줄은 Object, 짧은 ID는 `MetaText`.
    세션 정보 시트에서 Object 행을 빼고 원래 다섯 항목으로 되돌린다. `session_info_object`를
    지우고 `session_list_object`를 두 화면이 함께 쓰는 `session_object`로 바꾼다.
  - 명세: `FR-013c` 원문 복구, `FR-013`에 Object 추가, `FR-013f`를 카드와 본문 두 곳으로,
    `FR-013g`에 위계 규칙 신설. 인수 시나리오 1·1a·1c 수정과 1d 신설. `capture-control-ui.md`의
    `조회 화면의 짜임`과 진입점 표, `data-model.md`의 `objectName` 행.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22).
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **28 tests, 0 failures.** `SessionInfoSheetTest`가
    `SessionDetailObjectTest`(3개)로 바뀌어 T058의 27개 결과는 이 task의 근거가 되지 않으므로 다시
    돌렸다.

    ```text
    SessionDetailObjectTest:...         SessionListScreenTest:.......
    SessionMetadataMigrationTest:.      SessionMetadataQueryTest:..
    Time: 18.776 / OK (28 tests)
    ```

  - 실기기 화면 확인: 같은 기기의 `문도` 묶음에서 카드가 `시각 / Object 56 / 업로드 완료 /
    Episode 1개 / ID`로, 상세 본문이 `시각 / Object 56 / ID 9c0a11e8 / 업로드 완료`로 나온다.
    Object가 딸린 줄 크기로 올라오고 ID가 한 층 내려갔다.

- [X] T060 [S15P21A206-45] 카드와 상세 본문의 층을 다시 세우고 상세에 Task를 더한다. `FR-013f`를
  고치고 `FR-013h`를 신설한다.
  - 배경: 층이 다섯이고 경계가 크기 하나에만 걸려 있었다.
    - 카드가 제목 아래 보조 줄 넷(Object / 업로드 완료 / Episode 수 / ID)을 쌓았다. Material 3
      리스트 가이드라인은 보조 줄을 1~3줄로 제한한다.
    - 2층(14sp)과 3층(12sp)이 색·굵기가 같고 크기만 2sp 달랐다. 의도한 단계가 아니라 들쭉날쭉한
      것으로 읽힌다. 타이포그래피 통념은 크기 하나에 위계를 맡기지 말고 굵기나 색을 함께 바꾸라는
      쪽이다.
    - 카드에서 `업로드 완료` 줄만 들여쓴 것처럼 보였다. 화면을 재어 보니 다섯 줄의 상자 원점은
      같고(첫 잉크 86~88px) 글리프 side bearing 차이였다. `E`·`I`는 x=88에 높이 25px짜리 세로
      획이 서지만 `업`의 ㅇ은 완만한 곡선이라 가장 짙은 열이 x=93이다. 착시이므로 정렬로 고칠
      것이 없고, 그 줄을 왼쪽 더미에서 빼는 것이 답이다.
    - Object만 있고 Task가 없어 상세가 이름의 절반만 말했다. 둘은 한 다이얼로그에서 함께
      입력받아 떨어지면 뜻이 없고, 수집 직후 경로에서는 Task도 화면에 나온 적이 없다.
  - 구현: 층을 셋으로 줄인다. 이름(`titleMedium`/`titleLarge`) → 두 이름(`SubjectText`, 14sp
    `onSurface`) → 부수(`MetaText`, 12sp `onSurfaceVariant`, `META_SEPARATOR`로 한 줄). 경계마다
    크기와 함께 굵기 또는 색이 바뀐다. 전송 상태는 카드 제목과 같은 행의 끝으로 옮긴다
    (`labelMedium`). 상세 본문은 `Task … · Object …` 한 줄이며 없는 쪽은 빠진다.
  - production 호출 경로: `SessionSummaryItem`, `SessionDetailScreen` 본문.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22).
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **29 tests, 0 failures.**
    `SessionDetailObjectTest`가 넷으로 늘었다(`sessionDetailNamesTheTaskAndObjectThatWereCaptured`,
    `sessionDetailNamesOnlyWhatItHas`, `sessionDetailDropsTheLineWhenThereAreNoNames`,
    `sessionInfoLeavesTheNamesToTheBody`).

    ```text
    SessionDetailObjectTest:....        SessionListScreenTest:.......
    Time: 19.682 / OK (29 tests)
    ```

  - 실기기 화면 확인: 카드가 `시각 … 업로드 완료 / Object 56 / Episode 1개 · ID 9c0a11e8` 세 줄로,
    상세 본문이 `시각 / Task 문도 · Object 56 / ID 9c0a11e8`로 나온다.

- [X] T061 [S15P21A206-45] 한 줄에 놓인 값 사이를 부호에서 간격으로 바꾸고, 전송 상태의 baseline을
  이름에 맞춘다. `FR-013h`를 고치고 `FR-013i`를 신설한다.
  - 배경:
    - 가운뎃점으로 이었더니 어색했다. 한국어에서 그 부호는 같은 종류의 낱말을 묶는 자리인데
      (`서울·부산`), 여기서 잇는 것은 각자 이름표를 단 서로 다른 값이다. 이름표가 이미 값의
      시작을 알리므로 벌리는 것만으로 갈린다.
    - 전송 상태가 이름보다 위로 떠 보였다. `Row`의 기본 정렬이 위 맞춤이라 12sp 글자가 16sp
      글자의 윗선에 붙었다. 화면을 재어 보니 상태의 아래 잉크가 이름보다 16px 높았다.
  - 구현: `META_SEPARATOR`를 `" · "`에서 em space 둘(`"  "`)로 바꾼다. 카드 제목 행의
    두 `Text`에 `Modifier.alignByBaseline()`을 준다.
  - production 호출 경로: `SessionSummaryItem`, `SessionDetailScreen` 본문.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22). 두 계측
    테스트는 `META_SEPARATOR`로 기대값을 만들므로 구분자가 바뀌어도 함께 따라간다.
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **29 tests, 0 failures.** `OK (29 tests)`,
    19.264초.
  - 실기기 화면 확인: 같은 기기에서 상태의 아래 잉크가 이름과 1px 안으로 들어왔다(글리프
    overshoot). 카드의 부수 줄이 `Episode 1개   ID 9c0a11e8`, 상세의 이름 줄이
    `Task 문도   Object 56`으로 나온다.

- [X] T062 [S15P21A206-45] 식별자를 부수 정보에서 떼어 내고 카드의 단을 둘로 나눈다. `FR-013g`~
  `FR-013i`를 고치고 `FR-013j`·`FR-013k`를 신설한다.
  - 배경: `Episode 1개`와 `ID 9c0a11e8`을 한 줄에 두고 구분자를 무엇으로 바꿔도 어색했다. 부호가
    아니라 두 값이 서로 관계가 없는 것이 원인이었다. 분량과 식별자다.
    - 사용자 확인: 이 앱은 배포용이 아니라 수집용이고, 서버에 올라간 영상을 찾을 때 쓰는 것은
      수집 일시가 아니라 ID다. 즉 식별자는 곁다리가 아니라 목록에서 세션을 짚는 주 수단이다.
      "시각으로 구분 가능하다"는 판단은 ID의 존재 이유를 부정하는 것이었으므로 철회한다.
    - 레퍼런스: 같은 문제를 다루는 GitHub 커밋 목록을 실제로 재 봤다. 짧은 SHA가 `fontSize: 12px`
      (가장 작은 층), `color: rgb(37,41,46)`(본문과 같은 색, 옅게 하지 않음), 행 폭 1174 중
      왼쪽 1024 지점(오른쪽 끝 trailing)에 있고 옆에 복사 버튼이 붙는다.
    - 고정폭은 두 가지를 준다. 값 대조가 이 값의 쓸모이므로 `0`/`O`, `1`/`l`이 갈려야 하고,
      글꼴이 다르면 사람이 읽는 이름과 기계가 부르는 이름이 다른 종류라는 것이 저절로 드러나
      부호로 가를 필요가 없어진다.
  - 구현: `IdentifierText`(12sp, `FontFamily.Monospace`, `onSurface`)를 새로 둔다. 카드는 단을
    둘로 나눈다 — 왼쪽은 수집 일시·Object·Episode 개수, 오른쪽은 첫 행에 식별자, 둘째 행에 전송
    상태. 두 행 모두 `alignByBaseline()`. 상세 본문은 이름표와 값을 한 줄씩 쌓는다(수집 일시 /
    Task / Object / 식별자). `META_SEPARATOR`는 쓰는 곳이 없어져 지웠다.
  - production 호출 경로: `SessionSummaryItem`, `SessionDetailScreen` 본문.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22).
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **29 tests, 0 failures.** `OK (29 tests)`,
    19.561초. `SessionDetailObjectTest`가 두 이름을 각각 검사하도록 바뀌었다.
  - 실기기 화면 확인: 카드가 `시각 … ID 9c0a11e8 / Object 56 … 업로드 완료 / Episode 1개`로,
    상세 본문이 `시각 / Task 문도 / Object 56 / ID 9c0a11e8`로 나온다. 고정폭이라 두 카드의
    `9c0a11e8`·`acc6031a`가 자리까지 맞는다.
  - 남은 것: GitHub은 SHA 옆에 복사 버튼을 둔다. 이 앱도 식별자를 서버 기록과 맞추려면 옮겨 적는
    대신 복사하는 편이 낫지만, 카드의 길게 누르기는 이미 삭제가 쓰고 있어 자리가 겹친다. 별개
    범위로 남긴다.

- [X] T063 [S15P21A206-45] 스타일 조합을 역할 셋으로 접는다. `FR-013h`·`FR-013j`를 고치고
  `FR-013l`을 신설한다.
  - 배경: 요소마다 조합을 새로 만들어 두 화면이 난잡해졌다. 카드가 요소 5개에 조합 5개였다 —
    시각(Roboto/16/Medium/진함), ID(**Mono**/12/Regular/진함), Object(Roboto/14/Regular/진함),
    전송 상태(Roboto/12/**Medium**/옅음), Episode(Roboto/12/Regular/옅음). 축 넷을 섞은 결과
    어느 요소도 다른 요소와 스타일을 공유하지 않았다. 지적을 받을 때마다 구별 축을 하나씩 더한
    것이 원인이다.
  - 레퍼런스: 실제 제품의 한 행을 재 봤다.
    - GitHub 커밋 목록(값 4개): 글꼴 1종, 크기 2종(16/12px), 굵기 2종(500/400), 색 2종 →
      **조합 3개**. 제목 `16px/500/rgb(31,35,40)`, 작성자·시각 `12px/400/rgb(89,99,110)`,
      SHA `12px/500/rgb(37,41,46)`. SHA는 고정폭이 아니다.
    - GitHub Actions 실행 목록: 크기는 12·16px 둘뿐이고 **상태는 글자가 아니라 아이콘**이다.
      고정폭(`ui-monospace`)은 브랜치 ref에만 쓴다.
    - Material 3 리스트 anatomy: 텍스트 역할이 label·supporting·trailing 셋이고 그 밖은
      badge·icon으로 처리한다.
    - 원칙: 크기는 네 가지를 넘기지 않는 것이 통념이고 굵기는 셋까지다. Apple HIG는 글꼴 하나에
      스타일 몇 개만 쓰라고 하며, 여러 글꼴을 섞으면 **정보 위계를 오히려 가린다**고 적는다.
      같은 문서가 조합을 손으로 만들지 말고 정해진 텍스트 스타일에서 고르라고 한다.
  - 구현: 역할을 셋으로 정하고(이름 16/Medium/진함, 딸린 값 14/Regular/옅음, 식별자
    12/Medium/진함) 요소를 거기 배정한다. Object·전송 상태·Episode 개수가 `SupportingText`
    하나를 함께 쓰고, 상세 본문의 Task·Object·짧은 ID 세 줄도 같은 역할을 쓴다. `SubjectText`는
    `SupportingText`와 역할이 겹쳐 지웠다. `IdentifierText`는 고정폭을 떼고 12sp Medium
    `onSurface`로 다시 정의했다. 고정폭은 세션 정보의 전체 ID 한 곳에만 남긴다
    (`SessionInfoRow(valueFontFamily = FontFamily.Monospace)`).
  - production 호출 경로: `SessionSummaryItem`, `SessionDetailScreen` 본문, `SessionInfoSheet`.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22).
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **29 tests, 0 failures.** `OK (29 tests)`.
  - 실기기 화면 확인: 카드·상세·세션 정보 셋을 모두 봤다. 카드는 글꼴 1종·조합 3개가 되었고,
    세션 정보의 전체 ID만 고정폭으로 나온다.

- [X] T064 [S15P21A206-45] 카드 오른쪽 단을 한 크기로 묶고, 상세 본문을 두 묶음으로 가르고, 세션
  정보의 고정폭과 값 크기를 고친다. `FR-013i`·`FR-013k`·`FR-013l`을 고치고 `FR-013m`을 신설한다.
  - 카드의 정렬 확인: 실기기 화면을 픽셀로 재 보니 **레이아웃 정렬은 맞았다.** 2행의 `Object 56`과
    `업로드 완료`가 cap-top 598, baseline 630으로 같고, 아래 잉크 6px 차이는 `Object`의 `j`
    꼬리다. 1행도 `ID`(555)와 시각의 숫자(555)가 같으며 3px 차이는 `오전`의 한글이 CJK 폰트 대체로
    라틴 baseline 아래로 내려가는 것이다. 어긋나 보이는 원인은 정렬이 아니라 오른쪽 단의 두 값이
    크기가 달라 한 단으로 읽히지 않는 것이었다. 같은 14sp라도 한글은 em 상자를 꽉 채워 왼쪽의 라틴
    글자보다 커 보인다. 전송 상태를 12sp로 내려 식별자와 한 크기로 묶었다. 오른쪽 단 두 값의 잉크
    높이가 25/33에서 25/29로 좁혀졌다.
  - 상세 본문: 이름과 정보 사이에 `DETAIL_TITLE_GAP`(8dp)을 두어 두 묶음으로 갈랐다. 줄 사이
    2dp보다 넓고 다음 묶음 16dp보다 좁아 이름이 정보와 갈리면서도 한 덩어리로 묶인다.
  - 세션 정보: 고정폭을 뺐다. 글자 단위 대조에는 고정폭이 낫지만 한 화면에 글꼴이 둘이면 그 이득
    보다 위계를 가리는 손해가 크다는 판단이다. 어색했던 이유는 넷이었다.
    1. 값이 `bodyLarge` 16sp라 시트 제목(`titleMedium` 16sp)과 같은 크기였다. 제목이 목록의 첫
       항목처럼 읽히고 큰 글자 다섯 개가 사다리처럼 쌓였다.
    2. 이름표 12sp 옅음과 값 16sp 진함 사이가 4sp+색+대비로 한꺼번에 벌어져 두 줄이 한 묶음으로
       붙지 않고 이름표만 따로 뜬 작은 글자가 됐다.
    3. 고정폭 값만 두 줄로 넘쳐 그 행 높이가 두 배가 되고 리듬이 깨졌다.
    4. 행 사이 16dp가 값이 큰 상태에 맞춰져 있어 시트 전체가 늘어졌다.
    고친 것: 값 `bodyLarge` → `bodyMedium`(16→14sp), 고정폭 제거, 행 사이 16 → 12dp. 제목이
    유일한 최상위가 되고, 이름표와 값의 차이가 2sp로 좁아지고, 36자 식별자가 한 줄에 들어가
    행 높이가 고르게 됐다.
  - production 호출 경로: `SessionSummaryItem`, `SessionDetailScreen` 본문, `SessionInfoRow`.
  - 자동 검증: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug` 성공 (2026-09-22).
  - 계측 검증 (2026-09-22, `SM-G973N`, Android 12): **29 tests, 0 failures.** `OK (29 tests)`.
  - 실기기 화면 확인: 카드·상세·세션 정보 셋을 모두 봤다. 세션 정보는 다섯 행이 스크롤 없이 들어
    가고 전체 식별자가 한 줄이다.
