# 구현 계획: Episode Recorder MVP

**작성일**: 2026-09-01 | **명세**: [spec.md](spec.md)

## 요약

Galaxy S10 SM-G973N의 후면 main 1× 영상과 accelerometer·gyroscope·rotation vector 이벤트를 로컬 episode로 수집한다. 여섯 파일 bundle이 완결되면 completed episode로 공개하고, 수집자가 이를 `POST /episodes` multipart 요청으로 서버에 수동 업로드·재전송할 수 있게 한다. Camera2·SensorManager·MediaCodec/MediaMuxer 플랫폼 API를 사용한다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11, Android API 28 이상; compile/target SDK 37  
**주요 의존성**: Compose·Material 3·Lifecycle Runtime Compose, Android 플랫폼 Camera2·SensorManager·MediaCodec·MediaMuxer, OkHttp·MockWebServer, Room Runtime/KTX·KSP Compiler·Room Testing, Kotlin Coroutines Android, Kotlinx Serialization JSON·compiler plugin. Retrofit·DataStore·WorkManager·CameraX·Hilt는 추가하지 않는다.
**저장소**: 앱 전용 내부 영구 저장소의 staging/completed episode 디렉터리와 Room database의 episode catalog·UploadAttempt·CaptureLog
**테스트**: JUnit, Gradle lint/build, Galaxy S10 SM-G973N 연결 기기·수동 검증  
**대상**: Galaxy S10 SM-G973N(Android 12 실기기 확인), Android API 28 이상  
**성능 목표**: 1080p 또는 720p, 30 FPS; 실제 frame·sample 수와 timestamp로 검증  
**제약사항**: 후면 main 1×, zoom 1.0, episode 중 설정 변경 금지. 새 라이브러리·Camera 권한·Manifest 변경은 구현 직전 사용자 승인 필요. MVP 서버는 폐쇄망에서 인증 없이 접근하되, 신뢰 가능한 인증서의 HTTPS만 사용한다.
**범위**: 로컬 수집·보존·개별 episode 삭제·CaptureLog 전체 삭제·상태 UI와 completed episode의 수동 서버 업로드·상태 표시·수동 재전송. 서버 내부 구현·후처리·ORB-SLAM3·외부 보정·Task Representation은 범위 밖.

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
- Camera capture frame number·timestamp·source는 앱이 보존한다. MP4 frame↔timestamp 대응의 완전 검증과 후처리는 서버 측 후속 범위다.
- completed episode는 개별 삭제하고, `UPLOADING` 중인 episode의 삭제는 비활성화한다. CaptureLog는 전체 삭제만 제공한다.
- 업로드는 completed episode 한 건을 단위로 수동 시작하며, 성공 전·실패 후에도 원본 bundle을 유지한다. 중단된 요청은 업로드 세션·오프셋 재개 없이 같은 `episode_id`·`Idempotency-Key`로 여섯 파일 전체를 재전송한다. 단일 `POST /episodes` multipart 요청, 상태·오류는 `contracts/episode-upload.md`를 따른다.

## Constitution Check

constitution은 템플릿 상태라 적용 가능한 원칙이 없다. 대신 저장소 작업 지침을 게이트로 적용한다.

- 단일 app 모듈과 Kotlin·Compose·Material 3 구조 유지
- 권한·Manifest·새 라이브러리는 사용자 승인 후 변경
- 실기기 동작을 단위 테스트만으로 검증했다고 보고하지 않음
- bundle 검증 전 completed 공개 금지

**게이트 상태**: 조건부 통과. 모바일 업로드 구현 전에 HTTP 클라이언트 선택·의존성 추가·인터넷 권한 추가 여부는 사용자 승인이 필요하며, 서버 base URL은 빌드 시 주입하고 수신 응답 계약은 별도 통신 계약으로 제공돼야 한다.

## 프로젝트 구조

```text
specs/001-episode-recorder/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── mobile-transfer-spec.md
├── mobile-transfer-plan.md
├── mobile-transfer-research.md
├── mobile-transfer-data-model.md
├── mobile-transfer-quickstart.md
├── contracts/
│   ├── episode-bundle.md
│   └── episode-upload.md
└── checklists/requirements.md

app/src/main/java/com/ssafy/s15p21a206/tiger/
├── capture/     # Camera2, capture timestamp, encoder
├── sensor/      # SensorManager, flush, CSV
├── episode/     # lifecycle, staging/finalization, domain models
├── data/local/  # Room entity, DAO, database, migration
├── upload/      # multipart upload, response/state mapping, retry
└── ui/          # Compose views
```

**구조 결정**: 기존 단일 모듈 안에서 기능 패키지를 분리하고, `upload/`가 completed bundle과 `contracts/episode-upload.md`의 외부 통신 계약을 연결한다. 서버의 내부 구현 모듈은 만들지 않는다.

## 구현 순서

1. 사용자 승인 후 camera capability preflight: physical main camera ID, 해상도·30 FPS·zoom 1.0, 세 센서를 확인한다.
2. episode 상태 전이, staging bundle writer, commit marker, completed catalog 및 CaptureLog를 구현한다.
3. SensorManager 등록·종료 flush·센서별 CSV 기록을 구현한다.
4. Camera2 preflight·preview·Camera capture timestamp·metadata와 video 경로를 구현한다.
5. completed bundle의 파일 hash·크기 재검증, 수동 multipart 업로드, idempotent 재전송과 로컬 업로드 상태 보존을 구현한다.
6. Room catalog의 Flow를 lifecycle-aware Compose state로 수집해 UTF-8 task 입력 검증, 녹화/목록/업로드 상태 UI, `UPLOADING` 중 비활성화되는 episode 개별 삭제, CaptureLog 전체 삭제 및 확정 lifecycle interruption 정책을 연결한다.
7. 단위 테스트·linter·build·Galaxy S10 six-file bundle/중단·삭제·서버 연동 흐름을 검증한다.

## 복잡성 추적

| 항목 | 필요한 이유 | 단순 대안이 부족한 이유 |
| --- | --- | --- |
| staging bundle + commit marker | crash·취소 data의 completed 노출 방지 | 파일별 완료만으로 여섯 파일 bundle의 원자적 공개를 보장할 수 없다 |
