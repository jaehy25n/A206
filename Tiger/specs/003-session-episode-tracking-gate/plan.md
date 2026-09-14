# 구현 계획: Session/Episode 분리와 Tracking 유효성 게이트

**브랜치**: `feature/session-episode-tracking-gate` | **작성일**: 2026-09-14 | **명세**: [spec.md](spec.md)

## 요약

수집 화면의 Session 시작과 Episode 시작을 분리하고, ARCore Tracking 상태를 Episode 유효성 판정에 연결한다. 또한 `main_frame_timestamps.csv`의 `frame_number`를 순차 frame index로 정정하고, 촬영에 사용된 Camera의 ID·해상도·Intrinsic을 `metadata.json`에 기록한다.

핵심 접근은 **신규 상태 기계 설계가 아니라 기존 도메인 로직의 배선**이다. [`CaptureSessionCoordinator`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt)에 안정화 게이트(1초), 유실 판정(0.5초), `INVALID_TRACKING` 마감, `startEpisode`의 `READY` 선행 조건이 이미 구현되어 단위 테스트까지 있으나 production 호출 경로에 연결되어 있지 않다. `FrameTimestampWriter`도 올바른 `frame_number` 형식을 갖고 있으나 미사용이다. 이번 작업은 이 둘을 수집 화면과 `AndroidCaptureRuntime`의 유일한 판단 주체로 승격시킨다.

ARCore pose 스레드가 Tracking 여부를 노출하고, 수집 화면이 100ms ticker로 Coordinator에 반복 전달해 시간 기반 판정이 발화하도록 한다. Camera Intrinsic은 첫 유효 ARCore 프레임에서 1회 획득해 Session 마감 시 기록하며, 획득 실패가 Session 마감을 막지 않는다. 파일 레이아웃과 업로드 계약은 `metadata.json`에 `camera` 객체를 추가하는 것 외에 바꾸지 않는다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11 바이트코드 대상

**주요 의존성**: Jetpack Compose Material 3, Lifecycle Compose, Room 2.8.4, Kotlin coroutines, OkHttp 5.3.2, ARCore 1.56.0, Camera2. 새 의존성을 추가하지 않는다.

**저장소**: 앱 전용 `filesDir/capture/{staging,completed}/<session_id>/` 원시 bundle, Room `sessions`·`episode_markers` 색인. 스키마 변경 없음.

**테스트**: JUnit 단위 테스트(상태 기계, frame index, 메타데이터 직렬화), Compose UI 테스트(제어 활성화 규칙), 실기기 검증(Tracking 게이트 실동작, 산출 데이터 형식)

**대상 플랫폼**: Android API 28 이상, target SDK 37

**프로젝트 유형**: 단일 모듈 Android 모바일 앱

**성능 목표**: Tracking 평가 주기 100ms로 판정 오차를 임계값의 20% 이내로 유지한다. 상태 전이와 Episode 마감이 Camera / IMU / ARCore 수집을 끊지 않는다.

**제약**: 서버 API·multipart 전송 계약·의존성·권한 추가 없음. 번들 파일 구성과 CSV 헤더 불변. `metadata.json`은 기존 키를 보존한 추가만 허용. Ultra-wide 경로를 구현하지 않는다.

**범위**: 수집 화면 상태 기계, Tracking 게이트 연결, frame index 정정, Camera Metadata 기록, 관련 자동 테스트. 업로드·export·Session 목록·상세 화면은 변경하지 않는다.

## 프로젝트 규칙 점검

프로젝트 constitution(`.specify/memory/constitution.md`)은 미작성 템플릿이므로 강제 게이트가 없다. 대신 저장소 규칙(`AGENTS.md`, `specs/AGENTS.md`)을 적용한다.

- 단일 `:app` 모듈과 Kotlin·Compose·Material 3 구성을 유지하고, 의존성·권한·SDK 버전·서버 endpoint를 추가하지 않는다.
- 사용자 노출 문자열은 `res/values/strings.xml`에 둔다. 새 상태 표시와 Episode 시작 차단 사유 문구가 여기에 해당한다.
- 데이터 계약(`metadata.json`, `episodes.csv`, `main_frame_timestamps.csv`)을 바꾸므로 명세와 계약 문서를 함께 갱신한다. 이 계획의 `contracts/`가 그 산출물이다.
- 결정론적 동작(상태 전이, frame index, 메타데이터 직렬화)은 fake와 단위 테스트로 검증한다. 외부 환경 부재를 미구현 사유로 쓰지 않는다.
- 실기기에서만 확인 가능한 항목(실제 Tracking 유실 동작, MP4와 timestamp 행 수 대조)은 별도 task로 분리하고, 그 항목이 남아 있는 한 원래 task를 완료로 표시하지 않는다.
- 변경 경계를 지킨다. 미연결 코드를 연결하는 과정에서 무관한 리팩터링을 하지 않는다.

**설계 전 결과**: 통과. 명시된 UI 상태·Episode 유효성·CSV 값 의미·`metadata.json` 추가 필드만 변경하며, 의존성·권한·서버 API·백그라운드 서비스를 추가하지 않는다.

## 프로젝트 구조

### 문서

```text
specs/003-session-episode-tracking-gate/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── session-metadata.md
│   └── capture-state-machine.md
├── checklists/
│   └── requirements.md
└── tasks.md             # $speckit-tasks에서 생성
```

### 소스

```text
app/
├── src/main/java/com/ssafy/s15p21a206/tiger/
│   ├── MainActivity.kt                      # 상태 계산, ticker, Episode 마감 저장
│   ├── capture/
│   │   ├── AndroidCaptureRuntime.kt         # frame index, 녹화 구간 게이트, tracking 노출, intrinsics 획득
│   │   ├── CaptureSessionCoordinator.kt     # 상태 기계 (기존 로직 + 마감 콜백)
│   │   └── CameraMetadataReader.kt          # 신규 — Camera2 부가 광학 값 읽기
│   ├── episode/
│   │   ├── EpisodeModels.kt                 # CameraMetadata 타입 추가
│   │   └── SessionFinalizer.kt              # metadata.json에 camera 객체 기록
│   └── ui/capture/
│       ├── CaptureControlPolicy.kt          # 상태 5종 재정의
│       └── CaptureWorkspaceScreen.kt        # 상태별 제어 렌더링
├── src/main/res/values/strings.xml          # 상태 표시·차단 사유 문구
├── src/test/java/com/ssafy/s15p21a206/tiger/
│   ├── capture/                             # 상태 기계, frame index, 메타데이터
│   ├── episode/                             # finalize 산출물
│   └── ui/                                  # 제어 활성화 규칙
└── src/androidTest/java/com/ssafy/s15p21a206/tiger/ui/   # Compose 제어 상태 검증
```

**구조 결정**: 기존 단일 Android 앱 모듈과 패키지 구성을 유지한다. 새 파일은 `CameraMetadataReader.kt` 하나이며, 나머지는 기존 파일의 수정이다. `CaptureSessionCoordinator`를 옮기거나 재작성하지 않고, 마감 사건 전파용 콜백만 추가해 수집 화면에 연결한다.

## 조사 결정

[research.md](research.md)에 아홉 개 결정을 기록했다. 구현에 직접 영향을 주는 것은 다음 넷이다.

**Tracking 신호 전달 (결정 1)**: pose 스레드가 `StateFlow<Boolean>`로 Tracking 여부를 노출하고, 수집 화면이 100ms ticker로 최신 값을 `onTracking()`에 반복 전달한다. `onTracking()`은 호출 시점 기준으로 경과 시간을 판정하므로, 값 변화에만 반응하는 구독으로는 0.5초 마감이 영영 발화하지 않는다. Coordinator 호출은 전부 main 스레드에서 수행한다.

**상태 이름 재정의 (결정 2)**: 기존 `CaptureWorkspaceControlState.Ready`는 "Session 미시작"을 뜻해 명세와 수신 측의 `READY`와 정반대다. `Idle` / `Initializing` / `Ready` / `EpisodeActive` / `Finalizing`으로 재정의한다. 영향 범위는 enum, 정책 클래스, `MainActivity` 상태 계산, 테스트 두 개로 한정된다.

**frame index 중복 방지 (결정 5)**: 현재 동일한 `CaptureCallback` 인스턴스가 `setRepeatingRequest`와 `sharedCamera.setCaptureCallback`으로 두 번 등록되어 있고, 기존 타임스탬프 중복 제거가 그 결과를 걸러내고 있다. 이 방어를 유지한 채 **중복 제거를 통과한 행에 대해서만** 카운터를 증가시킨다. 방어를 걷어내면 `frame_number`가 프레임당 2씩 증가해 결함이 악화된다.

**Intrinsic 출처 (결정 7)**: ARCore `Frame.getCamera().getImageIntrinsics()`를 1차 출처로 쓴다. 현행 구현이 MediaRecorder 해상도를 `session.cameraConfig.imageSize`로 설정하므로 intrinsics 기준 해상도와 녹화 해상도가 구조적으로 일치하며, 수신 측이 요구한 "실제 촬영 Camera ID 및 Resolution에 대응하는 값"이 별도 보정 없이 충족된다. Camera2 `CameraCharacteristics`로 `focal_length`, `sensor_size`, `distortion_coefficients`를 보완하되 미제공 시 생략한다.

추가 확인이 필요한 미해결 항목은 없다.

## 구현 단계

의존 관계 순서이며, 각 단계는 독립적으로 검증 가능하다. 상세 분해는 `$speckit-tasks`에서 생성한다.

**1단계 — 데이터 형식 정정 (US3, US5)**: `AndroidCaptureRuntime`에 frame 카운터와 녹화 구간 플래그를 추가한다. 다른 단계와 결합이 없어 먼저 끝낼 수 있고, 실기기 1회 수집으로 바로 확인된다.

**2단계 — 상태 이름 재정의 (US1 기반)**: `CaptureWorkspaceControlState`와 `CaptureControlPolicy`를 다섯 상태로 재정의하고 기존 테스트를 갱신한다. 이 시점에는 `Initializing`으로 진입하는 경로가 아직 없어 동작이 기존과 같다.

**3단계 — Tracking 게이트 연결 (US1, US2)**: `AndroidCaptureRuntime`이 Tracking 여부를 노출하고, `CaptureSessionCoordinator`에 Episode 마감 콜백을 추가하며, `MainActivity`가 ticker로 둘을 잇는다. Session START가 Episode를 생성하지 않도록 분리하는 것도 이 단계다. 명세의 핵심이자 가장 결합도가 높은 단계다.

**4단계 — Camera Metadata (US4)**: `CameraMetadataReader`를 추가하고, 첫 유효 프레임에서 intrinsics를 획득해 `SessionFinalizer`가 `metadata.json`에 기록한다. 1~3단계와 독립적이라 병행 가능하다.

**5단계 — 실기기 검증**: 자동화할 수 없는 acceptance criterion을 별도 task로 분리한다. 실제 Tracking 유실·회복 동작, MP4와 timestamp 행 수 대조, `metadata.json` 해상도와 영상 해상도 일치 확인이 여기에 해당한다.

## 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| ticker가 판정을 발화시키지 못함 | 0.5초 마감이 동작하지 않아 결함이 그대로 남음 | 가상 시계 기반 단위 테스트로 ticker 호출과 마감 발화를 함께 검증. 실기기에서 카메라를 가려 재현 |
| 중복 콜백으로 `frame_number` 2배 증가 | 수신 측 동기화가 더 크게 어긋남 | 타임스탬프 중복 제거를 유지하고, 통과한 행에만 카운터 증가. 단위 테스트로 중복 입력을 주입해 확인 |
| 상태 이름 재정의로 기존 동작 회귀 | 수집 조작이 막히거나 잘못 활성화됨 | 기존 단위·Compose 테스트를 새 이름으로 갱신하고 상태별 제어 가능 여부를 표로 고정 |
| intrinsics 획득 실패가 Session을 실패시킴 | 수집 데이터 전체 손실 | 메타데이터 수집 전체를 실패 허용으로 감싸고, 실패 주입 테스트로 Session 마감이 계속되는지 확인 |
| ARCore 프레임이 끊겨 Tracking 신호가 갱신되지 않음 | 판정이 오래된 값으로 고정됨 | ticker는 최신 값을 읽으므로 신호가 `false`로 고정되면 마감이 정상 발화한다. 신호 자체가 멈추는 경우는 실기기 검증 항목으로 둔다 |

## 설계 후 규칙 점검

통과. 단일 모듈과 기존 라이브러리를 유지하며, 서버 API와 multipart 전송 계약을 보존한다. `metadata.json` 변경은 기존 키를 보존하는 추가이며, `SessionBundleValidator`가 알 수 없는 키를 무시하므로 하위 호환이다. CSV 헤더와 번들 파일 구성은 불변이다. 사용자 문구는 리소스로 관리하고, 데이터 계약 변경을 `contracts/` 산출물에 기록했다.

`specs/AGENTS.md`의 완료 판정 규칙과 관련해 한 가지를 명시한다. 이번 작업이 연결하는 `CaptureSessionCoordinator`와 `FrameTimestampWriter`는 **구현은 존재하나 production 호출 경로에 연결되지 않은 미연결 코드**다. 002 기능의 `tasks.md`에 이 범위를 완료로 표시한 task가 있다면 `$speckit-tasks` 단계에서 함께 정합화해야 한다.
