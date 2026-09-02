# API 명세: Episode Upload

이 문서는 Android 앱과 ingestion server 사이의 외부 HTTP 계약이다. 서버 내부 데이터베이스·저장소·후처리 구조는 정의하지 않는다.

## 1. 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| Base URL | build-time 주입 HTTPS URL. 실제 값은 저장소·문서에 기록하지 않는다. |
| Encoding | JSON과 CSV는 UTF-8을 사용한다. |
| 인증 | 폐쇄망 MVP에서는 사용하지 않는다. `Authorization`, cookie, custom credential header를 보내지 않는다. |
| Redirect | 앱은 redirect를 따라가지 않는다. `3xx`는 업로드 실패로 기록하며, 사용자는 base URL을 수정한 새 빌드에서 수동 업로드를 다시 시작할 수 있다. |
| 계약 변경 | multipart part·metadata·receipt 형식을 변경하면 모바일 앱과 server를 함께 갱신한다. |

## 2. Episode 수신

### Request

```http
POST {BASE_URL}/episodes HTTP/1.1
Content-Type: multipart/form-data; boundary=<boundary>
Content-Length: <calculated-byte-length>
Idempotency-Key: <episode-id>
```

- `{BASE_URL}`은 `https` scheme이어야 하고 신뢰 가능한 인증서여야 한다.
- `Content-Length`는 multipart boundary까지 포함한 request body의 정확한 byte length여야 한다.
- `<episode-id>`는 로컬 episode의 불변 UUID 문자열이다.
- `Idempotency-Key`는 `metadata` part의 `episode_id`와 정확히 같아야 한다.
- 같은 episode의 모든 재시도는 같은 `Idempotency-Key`를 사용한다.
- metadata 전체와 파일 metadata는 HTTP header에 넣지 않는다.
- 서버가 `POST /episodes` 외의 경로를 지원할 의무는 없다.

### Multipart body

multipart body에는 아래 여섯 part만 정확히 한 번씩 있어야 한다. 누락·중복·추가 part는 `400 MALFORMED_MULTIPART`다. 파일을 분할하거나 ZIP으로 묶지 않는다.

| 순서 | Part name | `filename` | `Content-Type` | 전송 내용 |
| --- | --- | --- | --- | --- |
| 1 | `metadata` | `metadata.json` | `application/json; charset=utf-8` | 로컬 `metadata.json`의 원문 |
| 2 | `video` | `video.mp4` | `video/mp4` | `video.mp4` |
| 3 | `frame_timestamps` | `frame_timestamps.csv` | `text/csv; charset=utf-8` | `frame_timestamps.csv` |
| 4 | `accelerometer` | `accelerometer.csv` | `text/csv; charset=utf-8` | `accelerometer.csv` |
| 5 | `gyroscope` | `gyroscope.csv` | `text/csv; charset=utf-8` | `gyroscope.csv` |
| 6 | `rotation_vector` | `rotation_vector.csv` | `text/csv; charset=utf-8` | `rotation_vector.csv` |

서버는 part 순서가 달라도 part name으로 해석해야 한다. 앱은 위 순서로 쓴다.

### metadata JSON

`metadata` part는 아래 JSON object여야 한다. 모든 필드는 필수이며, object에 없는 추가 field는 server가 무시해야 한다. JSON key는 snake_case를 사용한다.

| JSON field | 형식 | 규칙 |
| --- | --- | --- |
| `episode_id` | UUID string | `Idempotency-Key`와 동일 |
| `task` | non-empty string | task 폴더명과 동일 |
| `object` | non-empty string | 수집자가 입력한 대상 물체 |
| `outcome` | string enum | 정확히 `COMPLETED` |
| `recording_start_monotonic_timestamp_ns` | string | 나노초 정수 문자열 |
| `recording_end_monotonic_timestamp_ns` | string | 나노초 정수 문자열 |
| `recording_duration_ns` | string | end - start와 같은 0 이상 나노초 정수 문자열 |
| `device` | object | 아래 device object |
| `camera` | object | 아래 camera object |
| `timebase` | object | 아래 timebase object |
| `sample_counts` | object | 아래 sample_counts object |
| `files` | object | 아래 five-file manifest |

```json
{
  "episode_id": "0d1d9f98-8b05-4b90-82bc-519540937b31",
  "task": "pick_cup",
  "object": "cup",
  "outcome": "COMPLETED",
  "recording_start_monotonic_timestamp_ns": "123456789000000",
  "recording_end_monotonic_timestamp_ns": "123456799000000",
  "recording_duration_ns": "10000000",
  "device": { "manufacturer": "samsung", "model": "SM-G973N", "android_sdk": 31, "app_version": "1.0" },
  "camera": {
    "logical_camera_id": "0", "selected_physical_camera_id": "0", "lens_facing": "BACK", "lens_label": "main_1x",
    "focal_length_mm": 4.32000017, "sensor_physical_size_mm": { "width": 5.64499998, "height": 4.23400021 },
    "active_array": { "left": 0, "top": 0, "right": 4032, "bottom": 3024 },
    "pre_correction_active_array": { "left": 0, "top": 0, "right": 4032, "bottom": 3024 },
    "resolution": { "width": 1920, "height": 1080 }, "target_fps": 30, "zoom_ratio": 1.0,
    "ois_enabled": false, "eis_enabled": false, "timestamp_source": "REALTIME"
  },
  "timebase": { "camera_imu_comparability": "VERIFIED" },
  "sample_counts": { "frame_timestamps": 300, "accelerometer": 900, "gyroscope": 900, "rotation_vector": 300 },
  "files": {
    "video.mp4": { "path": "video.mp4", "size_bytes": 1234567, "sha256": "0000000000000000000000000000000000000000000000000000000000000000" },
    "frame_timestamps.csv": { "path": "frame_timestamps.csv", "size_bytes": 12345, "sha256": "0000000000000000000000000000000000000000000000000000000000000000" },
    "accelerometer.csv": { "path": "accelerometer.csv", "size_bytes": 12345, "sha256": "0000000000000000000000000000000000000000000000000000000000000000" },
    "gyroscope.csv": { "path": "gyroscope.csv", "size_bytes": 12345, "sha256": "0000000000000000000000000000000000000000000000000000000000000000" },
    "rotation_vector.csv": { "path": "rotation_vector.csv", "size_bytes": 12345, "sha256": "0000000000000000000000000000000000000000000000000000000000000000" }
  }
}
```

- 모든 나노초 timestamp와 duration은 JSON number가 아닌 decimal string이다.
- `device.android_sdk`, 모든 count, `size_bytes`는 0 이상의 JSON integer이며, `size_bytes`는 해당 part의 byte length와 같다.
- `sha256`은 lowercase 64자리 hexadecimal SHA-256 digest다.
- `files`의 key와 `path`는 표에 정한 다섯 filename과 각각 정확히 같아야 한다. path는 episode directory 기준 상대 경로이며 `/`, `\\`, `..`를 포함해서는 안 된다.
- 다섯 원본 file part의 실제 byte length와 SHA-256은 `files`의 기록과 일치해야 한다. `metadata` part는 원문 JSON을 전송하며 자신의 manifest 항목을 갖지 않는다.
- JSON object member 순서는 의미가 없다. 이 문서에 없는 metadata field는 server가 보존 여부와 관계없이 수신 검증에서 무시한다.

| Object | 필수 member와 형식 |
| --- | --- |
| `device` | `manufacturer`, `model`, `app_version`: non-empty string; `android_sdk`: integer |
| `camera` | `logical_camera_id`, `selected_physical_camera_id`, `lens_label`: non-empty string; `lens_facing`: 정확히 `BACK`; `focal_length_mm`, `zoom_ratio`: JSON number; `sensor_physical_size_mm.width/height`: JSON number; `active_array`와 `pre_correction_active_array`의 `left/top/right/bottom`: integer; `resolution.width/height`, `target_fps`: positive integer; `ois_enabled`, `eis_enabled`: boolean; `timestamp_source`: 정확히 `REALTIME` |
| `timebase` | `camera_imu_comparability`: 정확히 `VERIFIED` |
| `sample_counts` | `frame_timestamps`, `accelerometer`, `gyroscope`, `rotation_vector`: 0 이상의 integer |
| `files.<filename>` | `path`: 위 filename과 같은 string; `size_bytes`: 0 이상의 integer; `sha256`: lowercase 64자리 hex string |

## 3. Success response

공통 header:

```http
Content-Type: application/json; charset=utf-8
```

### 신규 수신

```http
HTTP/1.1 201 Created
Content-Type: application/json; charset=utf-8

{
  "episode_id": "0d1d9f98-8b05-4b90-82bc-519540937b31",
  "result": "created"
}
```

### 중복 수신

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8

{
  "episode_id": "0d1d9f98-8b05-4b90-82bc-519540937b31",
  "result": "duplicate"
}
```

| Field | 형식 | 규칙 |
| --- | --- | --- |
| `episode_id` | UUID string | 요청의 `Idempotency-Key`와 정확히 같아야 한다. |
| `result` | string enum | `201`은 `created`, `200`은 `duplicate`만 허용한다. |

앱은 status, `Content-Type: application/json`(charset parameter 허용), `episode_id`, `result`가 모두 일치할 때만 `UPLOADED`로 전이한다. 본문 누락·JSON 파싱 실패·값 불일치·다른 `2xx`는 `FAILED`로 기록한다.

## 4. Error response

서버가 `4xx`를 반환할 때는 다음 JSON body를 반환해야 한다.

```json
{
  "code": "BUNDLE_INVALID",
  "message": "metadata files manifest does not match uploaded files"
}
```

| Field | 형식 | 규칙 |
| --- | --- | --- |
| `code` | string enum | 아래 error code 중 하나 |
| `message` | non-empty string | 사용자에게 그대로 표시하지 않아도 되는 진단용 짧은 설명 |

| HTTP status | `code` | 의미 | 앱 상태 |
| --- | --- | --- | --- |
| `400` | `MALFORMED_MULTIPART` | boundary, part name, header, JSON 형식이 잘못됨 | `FAILED` |
| `409` | `IDEMPOTENCY_CONFLICT` | 같은 key가 다른 `episode_id` 또는 다른 file manifest와 이미 연결됨 | `FAILED` |
| `409` | `IDEMPOTENCY_IN_PROGRESS` | 동일 key bundle의 다른 요청이 아직 수신 결과를 확정하지 않음 | `FAILED` |
| `413` | `PAYLOAD_TOO_LARGE` | 서버 body-size 제한 초과 | `FAILED` |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | part content type이 계약과 다름 | `FAILED` |
| `422` | `BUNDLE_INVALID` | metadata·size·SHA-256·필수 파일 검증 실패 | `FAILED` |
| `429` | `RATE_LIMITED` | 일시적인 요청 제한 | `FAILED` |

- `401`, `403`은 인증 없는 MVP 서버가 반환해서는 안 된다. 반환되면 앱은 `FAILED`로 기록한다.
- `408`, `5xx`, TLS/연결 오류, request 취소, `3xx`도 `FAILED`다. server는 이 상태에서 error JSON을 보장하지 않아도 된다.
- status와 무관하게 성공 조건을 만족하지 않은 모든 요청은 `FAILED`다. error JSON이 유효하면 `code`·`message`를 마지막 시도 정보로 저장하고, 없거나 파싱할 수 없으면 generic failure summary를 저장한다. 수집자는 `FAILED` episode를 명시적으로 다시 업로드할 수 있다.

## 5. Idempotency 규칙

1. 서버는 `Idempotency-Key`와 `metadata.episode_id`가 같지 않으면 `400 MALFORMED_MULTIPART`를 반환한다.
2. 서버가 처음 보는 key와 유효한 bundle을 수신하면 `201`과 `created` receipt를 반환한다.
3. 같은 key와 동일한 `episode_id`·다섯 원본 파일 manifest를 다시 수신하면 새 episode를 만들지 않고 `200`과 `duplicate` receipt를 반환한다.
4. 같은 key가 다른 `episode_id` 또는 다른 file manifest와 연결되면 `409 IDEMPOTENCY_CONFLICT`를 반환한다.
5. 같은 key·같은 `episode_id`·같은 manifest 요청이 이미 처리 중이면 `409 IDEMPOTENCY_IN_PROGRESS`를 반환한다. 앱은 이를 `FAILED` 마지막 시도로 기록한다.
6. 앱은 `FAILED` episode를 사용자가 재전송할 때 여섯 파일 전체를 새 요청으로 보낸다. offset, resumable session, background retry는 지원하지 않는다.

## 6. 전송 한계와 timeout

- API는 numeric payload-size limit를 고정하지 않는다. 배포 환경의 limit를 초과하면 server는 `413 PAYLOAD_TOO_LARGE`를 반환하며 앱은 `FAILED`로 표시한다.
- 앱은 connect timeout 10초, read timeout 30초, write timeout 120초를 사용한다. 전체 call timeout은 설정하지 않는다. 영상 용량이 episode마다 달라 고정 전체 timeout을 두지 않기 때문이다.
- write timeout은 socket에 진행이 없는 시간을 뜻하며, timeout·TLS/연결 실패·사용자 request 취소는 `FAILED` 마지막 시도로 기록한다.

## 7. 모바일 검증 규칙

- request 전: completed 상태와 여섯 파일 존재, 다섯 원본 파일에 대한 `metadata.files`의 path·size·SHA-256 일치를 로컬에서 검증한다.
- request 중: UI를 즉시 `UPLOADING`으로 갱신한다.
- response 후: receipt가 계약과 맞으면 `UPLOADED`, 그 밖의 모든 결과는 `FAILED`로 갱신한다.
- 어떤 분기에서도 로컬 `metadata.json`과 원본 파일을 수정하거나 자동 삭제하지 않는다.
