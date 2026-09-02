# 보조 계획: Mobile Episode Transfer

**상위 기능**: `001-episode-recorder` | **작성일**: 2026-09-02 | **명세**: [spec.md](spec.md)

## 요약

완결된 여섯 파일 episode bundle을 신뢰 가능한 인증서의 HTTPS 서버에 `POST /episodes` multipart 요청으로 수동 업로드한다. 앱은 `episode_id`를 `Idempotency-Key`로 사용하고, 신규 수신 `201`·중복 수신 `200`의 JSON 결과를 `UPLOADED`로 처리한다. 성공 조건을 만족하지 않는 모든 응답·전송 오류는 `FAILED` 마지막 시도로 저장하며, 수집자는 같은 key로 여섯 파일 전체를 수동 재전송할 수 있다. 앱은 redirect를 따르지 않으며, 어떤 경우에도 로컬 원본을 변경·삭제하지 않는다.

서버 내부의 데이터베이스·파일 저장소·후처리·배포는 이 계획의 범위 밖이다.

## 기술 맥락

**언어/버전**: Kotlin 2.2.10, Java 11, Android API 28 이상; compile/target SDK 37
**주요 의존성**: OkHttp(런타임 HTTP/TLS/multipart), OkHttp MockWebServer(test), Room Runtime/KTX·KSP Compiler·Room Testing, Kotlin Coroutines Android, Lifecycle Runtime Compose, Kotlinx Serialization JSON·compiler plugin, Compose·Lifecycle. Retrofit·DataStore·WorkManager는 추가하지 않는다.
**저장소**: 앱 전용 completed episode bundle과 Room episode catalog. Upload state·last attempt·CaptureLog는 원본 파일과 분리한 Room entity로 저장한다.
**테스트**: JUnit의 multipart body·상태 전이·오류 분류 테스트, 계약을 재현하는 테스트 서버 또는 서버 계약 테스트, Galaxy S10 SM-G973N 실제 HTTPS 수동 검증
**대상**: Android 앱 단일 `:app` 모듈, Galaxy S10 SM-G973N(Android 12) 및 Android API 28 이상
**프로젝트 유형**: 모바일 앱의 외부 HTTPS API 통합
**성능 목표**: 사용자가 시작한 뒤 5초 이내에 `UPLOADING` 상태를 표시하고, video를 포함한 multipart body를 메모리에 전체 적재하지 않고 전송한다.
**제약사항**: 인증 없는 폐쇄망 MVP, 신뢰 가능한 인증서의 HTTPS만 허용, server base URL은 빌드 시 주입, 앱 내 URL 입력 화면 없음, 자동/백그라운드 업로드 및 offset 재개 없음, 원본 bundle 자동 삭제 없음.
**규모/범위**: 한 번에 사용자가 선택한 completed episode 하나만 전송한다. 실제 base URL과 server body-size 제한은 저장소에 기록하지 않는다. 앱 timeout은 connect 10초/read 30초/write 120초로 API 계약에 고정한다.

## Constitution Check

Constitution은 템플릿 상태라 적용할 프로젝트 원칙이 없다. 대신 저장소 지침을 게이트로 적용한다.

- 단일 Android 앱 모듈 및 Kotlin·Compose·Material 3 구조를 유지한다.
- OkHttp·MockWebServer·Room·Coroutines·Lifecycle Compose·Kotlinx Serialization만 새 의존성으로 추가하며, 버전은 `gradle/libs.versions.toml`에서 관리한다. Retrofit·DataStore·WorkManager·CameraX·Hilt는 추가하지 않는다.
- `INTERNET`, `ACCESS_NETWORK_STATE`, network security config 및 Manifest 변경은 구현 직전 사용자 승인을 받아야 한다.
- 실제 base URL·인증서·기타 환경 설정은 저장소에 기록하지 않는다.
- JUnit 또는 계약 테스트만으로 Galaxy S10의 실제 HTTPS·인증서·파일 전송을 검증했다고 보고하지 않는다.

**게이트 상태**: 조건부 통과. 구현은 권한/Manifest 변경 승인과 신뢰 가능한 HTTPS 서버의 실제 계약 제공 후 시작한다.

## 프로젝트 구조

### 문서

```text
specs/001-episode-recorder/
├── spec.md
├── plan.md
├── mobile-transfer-spec.md
├── mobile-transfer-plan.md
├── mobile-transfer-research.md
├── mobile-transfer-data-model.md
├── mobile-transfer-quickstart.md
└── contracts/
    └── episode-upload.md
```

### Android 소스

```text
app/
├── src/main/
│   ├── AndroidManifest.xml
│   ├── java/com/ssafy/s15p21a206/tiger/
│   │   ├── episode/   # completed catalog 및 UploadState 영속화
│   │   ├── data/local/ # Room entity, DAO, database, migration
│   │   ├── upload/    # OkHttp multipart, 응답/오류 매핑, 재전송 조정
│   │   └── ui/        # 목록의 업로드/재전송 이벤트와 상태 표시
│   └── res/xml/       # cleartext를 허용하지 않는 network security config
└── src/test/java/com/ssafy/s15p21a206/tiger/upload/
    ├── EpisodeUploadClientTest.kt
    └── EpisodeUploadCoordinatorTest.kt
```

**구조 결정**: 기존 `episode/`는 bundle·catalog·상태 영속화만 소유한다. `upload/`는 검증된 bundle을 읽어 HTTPS 계약을 실행하고 응답을 상태 전이로 변환한다. `ui/`는 사용자의 수동 업로드·재전송 요청과 표시만 담당한다. 서버 구현 모듈은 만들지 않는다.

## 구현 순서

1. 사용자 승인 후 네트워크 권한, cleartext 차단 설정, 빌드 주입 base URL 경계를 추가한다.
2. Room으로 episode catalog·upload attempt·CaptureLog를 영속화하고, Kotlinx Serialization으로 metadata·receipt schema를 직렬화한다. 상태 전이·원본 불변 규칙을 단위 테스트한다.
3. 여섯 파일의 존재·크기·SHA-256을 업로드 직전에 다시 검증한다.
4. OkHttp `MultipartBody` request factory와 HTTPS client를 구현한다. part 순서와 이름, `Idempotency-Key`, redirect 거부, `201`/`200` JSON 검증을 계약대로 처리한다.
5. 성공 조건을 만족하지 않는 모든 결과를 `FAILED` 마지막 시도로 기록하고, 재전송은 같은 key로 bundle 전체를 새 요청에 넣는다.
6. episode 목록에 업로드·재전송 제어, 진행·성공·실패·마지막 시도 표시를 연결한다.
7. JUnit·계약 테스트·Gradle 검증 후 Galaxy S10에서 실제 인증서와 서버를 사용해 수동 검증한다.

## 복잡성 추적

| 항목 | 필요한 이유 | 단순 대안이 부족한 이유 |
| --- | --- | --- |
| OkHttp + MockWebServer | multipart·TLS·connection lifecycle을 검증된 Android HTTP client에 맡기고 실제 wire contract를 단위 테스트한다 | `HttpsURLConnection` 직접 구현은 multipart framing·응답 처리·test server를 모두 유지해야 하며, Retrofit은 단일 대용량 multipart endpoint에 필요한 저수준 제어를 줄이지 못한 채 추가 계층을 만든다 |
| Room + Kotlinx Serialization | episode catalog·upload attempt를 query 가능한 schema로 보존하고 metadata/receipt를 타입 안전하게 계약화한다 | file catalog 수동 직렬화와 `org.json`은 schema 변경·상태 recovery·쿼리 테스트가 늘어날수록 오류 표면이 커진다 |
