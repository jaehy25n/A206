# API 명세: Capture Session Upload

이 문서는 Android 앱과 ingestion server의 Session 단위 HTTP 계약이다. 서버 내부 저장·후처리 구조는 정의하지 않는다.

## Request

```http
POST {BASE_URL}/sessions HTTP/1.1
Content-Type: multipart/form-data; boundary=<boundary>
Idempotency-Key: <session_id>
```

- `{BASE_URL}`은 신뢰 가능한 인증서의 HTTPS URL이다.
- endpoint는 신뢰된 폐쇄망에서 운영하며, MVP 앱은 `Authorization`, cookie 또는 custom credential header를 전송하지 않는다.
- `session_id`는 immutable UUID이며 `Idempotency-Key`와 metadata의 `session_id`가 정확히 같아야 한다.
- 재시도는 같은 key로 전체 multipart를 다시 보낸다. background, resumable, partial upload는 지원하지 않는다.
- 앱은 redirect를 따르지 않으며 성공 전·실패 후 원본 bundle을 수정·삭제하지 않는다.

## Multipart body

main-only Session은 다음 part를 한 번씩 보낸다. `metadata` 외 part의 filename은 동명의 로컬 raw file이고, CSV는 UTF-8, video는 `video/mp4`다.

| Part name | 파일 |
| --- | --- |
| `metadata` | `metadata.json` |
| `main_video` | `main_rgb.mp4` |
| `main_frame_timestamps` | `main_frame_timestamps.csv` |
| `accelerometer` | `accelerometer.csv` |
| `gyroscope` | `gyroscope.csv` |
| `rotation_vector` | `rotation_vector.csv` |
| `arcore_poses` | `arcore_poses.csv` |
| `episodes` | `episodes.csv` |

`metadata.camera_streams.ultrawide=true`일 때만 `ultrawide_video` (`ultrawide_rgb.mp4`)와 `ultrawide_frame_timestamps` (`ultrawide_frame_timestamps.csv`)를 추가한다. 선언과 part 구성이 다르거나 part가 누락·중복·추가되면 요청은 유효하지 않다.

## Metadata 검증

metadata JSON은 최소한 `session_id`, device, camera streams, camera, arcore, timebase, recording start/end timestamp, sample counts, raw file manifest를 포함한다. 파일 manifest는 metadata 자신을 제외한 모든 전송 raw file의 relative filename, byte size, lowercase SHA-256을 기록한다.

서버는 `session_id`, streams 선언, manifest size/hash, 필수 file 구성, timestamp comparability 결과를 검증한다. `main=true`와 `arcore.enabled=true/shared_camera=true`가 main-only MVP의 정상 선언이며, `ultrawide=false`에 UW part 또는 `ultrawide=true`에 UW 누락 part는 reject한다.

## Receipt와 오류

유효한 신규 수신은 `201`과 `{ "session_id": "…", "result": "created" }`, 동일 bundle 재수신은 `200`과 `result: "duplicate"`를 반환한다. 앱은 status·JSON content type·session ID·result가 모두 일치할 때만 `UPLOADED`로 표시한다.

`400 MALFORMED_MULTIPART`, `409 IDEMPOTENCY_CONFLICT`, `409 IDEMPOTENCY_IN_PROGRESS`, `413 PAYLOAD_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`, `422 BUNDLE_INVALID`, `429 RATE_LIMITED`, TLS/연결 오류, redirect, 그 밖의 성공 조건 불일치는 `FAILED`다. 실패한 completed Session은 수동으로 재전송할 수 있다.
