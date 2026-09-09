# 구현 계획: Capture Control UX

**브랜치**: `002-capture-control-ux` | **작성일**: 2026-09-08 | **명세**: [spec.md](spec.md)

## 요약

단일 수집 폼을 Session 목록, 전체 화면 수집 작업 공간, Session 상세, 별도 업로드 상태 화면으로 교체한다. 작업 공간은 전체 화면 프리뷰 위에 즉시 task/object 입력 모달을 띄우고, 확인 뒤 프리뷰 하단 중앙 오버레이의 재생·일시 정지·정지로 Episode 경계를 만든다. 정지는 Session을 확정한 뒤 기존 서버 전송을 즉시 시작한다.

원시 bundle은 파일 형식을 유지한 채 앱 전용 내부 저장소로 옮기고, Room은 목록·상세·상태를 위한 색인으로만 사용한다. 기존 외부 저장소 bundle은 복사·삭제하지 않고 제외한다. 업로드 상태 화면은 취소 가능한 전송을 소유하며, 뒤로 가기·닫기는 확인 후 취소하고 백그라운드 전환은 즉시 취소한다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11 바이트코드 대상

**주요 의존성**: Jetpack Compose Material 3, Activity Compose, Lifecycle Compose, Room 2.8.4, Kotlin coroutines, OkHttp 5.3.2, ARCore

**저장소**: Room `sessions`·`episode_markers` 색인 및 Detail 수집 시각용 로컬 벽시계 값, 앱 전용 `filesDir/capture/{staging,completed}/<session_id>/` 원시 bundle, 기존 SAF export 대상

**테스트**: JUnit, Room testing, MockWebServer, 화면 전환·접근성 검증이 필요한 Compose UI 테스트, Gradle 단위·lint·assemble 검사

**대상 플랫폼**: Android API 28 이상, target SDK 37

**프로젝트 유형**: 단일 모듈 Android 모바일 앱

**성능 목표**: 제어 조작에도 카메라·센서 수집이 끊기지 않고 반응성을 유지한다. 업로드 중 서버 진행률 조회는 하지 않는다.

**제약**: 서버 API·multipart 전송 계약·새 의존성 추가 없음, 백그라운드 업로드 없음, 업로드 상태 화면 이탈 시 취소, 일반 파일 관리자가 원시 bundle을 수정할 수 없음, legacy 외부 bundle은 이전·삭제 없이 제외, 첫 재생 전 프리뷰는 녹화하지 않음. Android 15+ 16KB 페이지 호환을 위해 기존 ARCore 의존성은 1.56.0으로 올리고 APK 정렬 및 16KB 환경을 검증한다.

**범위**: Session 목록·수집 작업 공간·Session 상세·업로드 상태, 내부 저장소 전환, Episode 취소 상태 제거 및 자동 테스트. export는 지원을 유지하되 UX를 재설계하지 않는다.

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

**구조 결정**: 기존 단일 Android 앱 모듈을 유지한다. 새로운 navigation 의존성을 추가하지 않고, 상위로 hoisting한 sealed 화면 목적지와 명시적 콜백으로 목록·작업 공간·상세·업로드 상태를 전환한다.

## 조사 결정

[research.md](research.md)의 모든 결정이 해결됐으며 추가 확인 항목은 없다.

## 설계 후 규칙 점검

통과. 단일 모듈과 기존 라이브러리를 유지하며, 서버 API 및 multipart bundle 계약을 보존한다. 리소스 기반 사용자 문구와 저장소·상태 계약 변경을 명세 산출물에 명확히 기록한다.
