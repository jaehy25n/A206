# 구현 계획: Episode Recorder MVP

**브랜치**: `001-episode-recorder` | **작성일**: 2026-09-01 | **명세**: [spec.md](spec.md)

## 요약

Galaxy S10 SM-G973N의 후면 main 1× 영상과 accelerometer·gyroscope·rotation vector 이벤트를 로컬 episode로 수집한다. 여섯 파일 bundle이 완결되면 completed episode로 공개하며, 서버 API·전송·MP4 최종 검증은 구현하지 않는다. Camera2·SensorManager·MediaCodec/MediaMuxer 플랫폼 API를 사용한다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11, Android API 28 이상; compile/target SDK 37  
**주요 의존성**: 기존 Compose·Material 3·Lifecycle 및 Android 플랫폼 Camera2, SensorManager, MediaCodec, MediaMuxer  
**저장소**: 앱 전용 내부 영구 저장소의 staging/completed episode 디렉터리  
**테스트**: JUnit, Gradle lint/build, Galaxy S10 SM-G973N 연결 기기·수동 검증  
**대상**: Galaxy S10 SM-G973N(Android 12 실기기 확인), Android API 28 이상  
**성능 목표**: 1080p 또는 720p, 30 FPS; 실제 frame·sample 수와 timestamp로 검증  
**제약사항**: 후면 main 1×, zoom 1.0, episode 중 설정 변경 금지. 새 라이브러리·Camera 권한·Manifest 변경은 구현 직전 사용자 승인 필요.  
**범위**: 로컬 수집·보존·개별 episode 삭제·CaptureLog 전체 삭제·상태 UI. 서버 API/전송/검증, ORB-SLAM3, 외부 보정, Task Representation은 범위 밖.

## 확정된 결정

- 녹화 전 1080p/720p 선택, 기본 1080p 30 FPS, 시작 후 고정
- `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv` 분리 저장
- SM-G973N 실측에 따라 accelerometer·gyroscope 3성분, rotation vector 5성분 기록
- `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session·encoder·muxer·writer 오류는 `INTERRUPTED`
- S10 device 0의 실제 non-null metadata만 기록하고, 제공되지 않는 calibration/pose key는 제외

## 확정 운영 정책

- OIS는 OFF로 고정하고 metadata에 기록한다.
- 녹화 중 Activity `onStop`은 interruption이며 일시적인 `onPause`만으로는 interruption이 아니다.
- completed episode와 진단 로그는 자동 삭제하지 않으며, 저장 공간이 부족하면 새 녹화를 시작하지 않는다.
- Camera capture frame number·timestamp·source는 앱이 보존한다. MP4 frame↔timestamp 대응의 완전 검증은 MVP 범위 밖이다.
- completed episode는 개별 삭제하고, CaptureLog는 전체 삭제만 제공한다.

## Constitution Check

constitution은 템플릿 상태라 적용 가능한 원칙이 없다. 대신 저장소 작업 지침을 게이트로 적용한다.

- 단일 app 모듈과 Kotlin·Compose·Material 3 구조 유지
- 권한·Manifest·새 라이브러리는 사용자 승인 후 변경
- 실기기 동작을 단위 테스트만으로 검증했다고 보고하지 않음
- bundle 검증 전 completed 공개 금지

**게이트 상태**: 통과. 실제 서버 API·전송·검증은 MVP 범위 밖이다.

## 프로젝트 구조

```text
specs/001-episode-recorder/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── episode-bundle.md
└── checklists/requirements.md

app/src/main/java/com/ssafy/s15p21a206/tiger/
├── capture/     # Camera2, capture timestamp, encoder
├── sensor/      # SensorManager, flush, CSV
├── episode/     # lifecycle, staging/finalization, catalog
└── ui/          # Compose views
```

**구조 결정**: 기존 단일 모듈 안에서 기능 패키지를 분리하며 서버·업로드 모듈을 만들지 않는다.

## 구현 순서

1. 사용자 승인 후 camera capability preflight: physical main camera ID, 해상도·30 FPS·zoom 1.0, 세 센서를 확인한다.
2. episode 상태 전이, staging bundle writer, commit marker, completed catalog 및 CaptureLog를 구현한다.
3. SensorManager 등록·종료 flush·센서별 CSV 기록을 구현한다.
4. Camera2 preflight·preview·Camera capture timestamp·metadata와 video 경로를 구현한다.
5. 입력 검증, 녹화/목록/`LOCAL_ONLY` 상태 UI, episode 개별 삭제, CaptureLog 전체 삭제 및 확정 lifecycle interruption 정책을 연결한다.
6. 단위 테스트·linter·build·Galaxy S10 six-file bundle/중단·삭제 흐름을 검증한다.

## 복잡성 추적

| 항목 | 필요한 이유 | 단순 대안이 부족한 이유 |
| --- | --- | --- |
| staging bundle + commit marker | crash·취소 data의 completed 노출 방지 | 파일별 완료만으로 여섯 파일 bundle의 원자적 공개를 보장할 수 없다 |
