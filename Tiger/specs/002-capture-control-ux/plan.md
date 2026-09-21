# 구현 계획: Capture Control UX

**브랜치**: `002-capture-control-ux` | **작성일**: 2026-09-08 | **명세**: [spec.md](spec.md)

## 요약

단일 수집 폼을 Session 목록, 전체 화면 수집 작업 공간, Session 상세로 교체한다. 작업 공간은 전체 화면 프리뷰 위에 즉시 task/object 입력 모달을 띄우고, 확인 뒤 프리뷰 하단 중앙 오버레이의 재생·일시 정지·정지로 Episode 경계를 만든다. 정지는 Session을 확정한 뒤 기존 서버 전송을 즉시 시작한다.

원시 bundle은 파일 형식을 유지한 채 앱 전용 내부 저장소로 옮기고, Room은 목록·상세·상태를 위한 색인으로만 사용한다. 기존 외부 저장소 bundle은 복사·삭제하지 않고 제외한다. 전송 진행과 결과는 Session 상세가 보여 준다. 사용자가 중간에 끊는 수단은 두지 않고, 백그라운드 전환만 즉시 취소한다.

수집한 Session은 기기에서 지울 수 있다. 서버에 DELETE API가 없으므로 삭제는 기기의 색인과 번들에만 미치며, 이미 업로드된 데이터는 서버에 그대로 남는다. 저장 공간을 비우는 동작이지 업로드를 취소하는 동작이 아니다.

삭제는 **색인을 먼저 지우고 번들 디렉터리를 지운다**. 두 저장소에 걸친 동작이라 사이에서 끊기면 한쪽만 지워지는데, 이 순서에서 남는 것은 목록에 보이지 않는 고아 디렉터리뿐이고 저장 공간만 차지한다. 반대 순서에서 남는 것은 번들이 사라진 Session이며 목록에 보이면서 재생도 전송도 되지 않는다. 고아는 다음 실행이 회수하고, 회수는 staging 구제가 끝난 뒤에 돈다. 구제가 옮겨 온 번들은 색인에 행이 있어 고아가 아니지만 순서를 뒤집으면 옮겨지기 전 상태를 보고 판단하게 된다.

전송이 번들을 읽고 있는 동안은 지우지 않는다. 전송을 끊는 수단을 두지 않기로 했으므로 전송이 끝나거나 실패한 뒤에 삭제한다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11 바이트코드 대상

**주요 의존성**: Jetpack Compose Material 3, Activity Compose, Lifecycle Compose, Room 2.8.4, Kotlin coroutines, OkHttp 5.3.2, ARCore

**저장소**: Room `sessions`·`episode_markers` 색인 및 Detail 수집 시각용 로컬 벽시계 값, 앱 전용 `filesDir/capture/{staging,completed}/<session_id>/` 원시 bundle, 기존 SAF export 대상

**테스트**: JUnit, Room testing, MockWebServer, 화면 전환·접근성 검증이 필요한 Compose UI 테스트, Gradle 단위·lint·assemble 검사

**대상 플랫폼**: Android API 28 이상, target SDK 37

**프로젝트 유형**: 단일 모듈 Android 모바일 앱

**성능 목표**: 제어 조작에도 카메라·센서 수집이 끊기지 않고 반응성을 유지한다. 업로드 중 서버 진행률 조회는 하지 않는다.

**제약**: 서버 API·multipart 전송 계약·새 의존성 추가 없음, 서버 DELETE API 없음(삭제는 기기에만 미침), 백그라운드 업로드 없음, 백그라운드 전환 시 전송 취소, 일반 파일 관리자가 원시 bundle을 수정할 수 없음, legacy 외부 bundle은 이전·삭제 없이 제외, 첫 재생 전 프리뷰는 녹화하지 않음. Android 15+ 16KB 페이지 호환을 위해 기존 ARCore 의존성은 1.56.0으로 올리고 APK 정렬 및 16KB 환경을 검증한다.

**범위**: Session 목록·수집 작업 공간·Session 상세, 내부 저장소 전환, Episode 취소 상태 제거 및 자동 테스트. export는 지원을 유지하되 UX를 재설계하지 않는다.

## 프로젝트 규칙 점검

프로젝트 constitution은 미작성 템플릿이므로 강제 게이트가 없다. 대신 저장소 규칙을 적용한다. Kotlin·Compose·Material 3와 단일 앱 모듈을 유지하고, 의존성·권한·서버 endpoint를 추가하지 않는다. 사용자 노출 문자열은 리소스로 관리하고, 데이터·업로드 계약 및 관련 명세를 갱신한다. 구현 완료 전 포맷·단위 테스트·lint·빌드를 검증한다.

**설계 전 결과**: 통과. 명시된 저장소·Episode 상태 계약만 변경하며, 의존성·권한·서버 API·백그라운드 서비스는 추가하지 않는다.

## 프로젝트 구조

### 문서

```text
specs/002-capture-control-ux/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── capture-control-ui.md
└── tasks.md             # $speckit-tasks에서 생성
```

### 소스

```text
app/
├── src/main/java/com/ssafy/s15p21a206/tiger/
│   ├── MainActivity.kt                 # 루트 UI 상태와 화면 구성
│   ├── capture/                        # 카메라 프리뷰와 AR/IMU 녹화 수명주기
│   ├── data/local/                     # Room 데이터베이스와 DAO
│   ├── episode/                        # Session·Episode·bundle·repository 모델
│   └── upload/                         # multipart 업로드와 취소 가능한 작업
├── src/main/res/values/strings.xml     # 사용자 문구·접근성 라벨
└── src/test/java/com/ssafy/s15p21a206/tiger/
    ├── capture/
    ├── episode/
    ├── upload/
    └── ui/
```

**구조 결정**: 기존 단일 Android 앱 모듈을 유지한다. 조회 흐름(목록·Task Session 목록·상세·전체 화면 동영상)은 `androidx.navigation:navigation-compose`의 `NavHost`와 type-safe route로 전환하고, 이탈은 `popBackStack()`으로 통일한다. 수집 작업 공간은 목적지가 아니라 `NavHost` 위에 얹는 모달이며 boolean 상태로 관리한다. 2026-09-17에 S15P21A206-40으로 갱신했다. 이전 결정과 뒤집는 이유는 `research.md`에 있다.

## 조사 결정

### Phase 5 구현 단위

`CaptureControlPolicy`의 네 상태·준비 여부·작업 잠금을 단위 테스트하고, `CaptureScreen`의 production 콜백과 제어 UI가 같은 정책을 사용한다. 종료 확인·BackHandler·툴팁은 `CaptureWorkspaceScreen.kt`에서 렌더링하고 부모가 확인 상태와 비동기 작업을 소유한다. Compose 검증은 기존 환경에 맞게 `src/androidTest/.../ui/CaptureControlStateScreenTest.kt`에 두고, T025는 제어 상태와 UI semantics·툴팁 자동 검사로 완료 판정한다. 개발용 앱이라는 사용자 결정(2026-09-11)에 따라 TalkBack 실사용 검증은 필수 범위에서 제외한다.

[research.md](research.md)의 모든 결정이 해결됐으며 추가 확인 항목은 없다.

## 설계 후 규칙 점검

통과. 단일 모듈과 기존 라이브러리를 유지하며, 서버 API 및 multipart bundle 계약을 보존한다. 리소스 기반 사용자 문구와 저장소·상태 계약 변경을 명세 산출물에 명확히 기록한다.
