# 보조 데이터 모델: Mobile Episode Transfer

## UploadableEpisode

기존 Recorder가 `COMPLETED`로 공개한 여섯 파일 bundle이다. 업로드는 recording lifecycle을 변경하지 않는다.

| 필드 | 규칙 |
| --- | --- |
| `episodeId` | 불변 UUID. `Idempotency-Key`와 success receipt의 `episode_id`가 이 값과 일치해야 한다. |
| `recordingState` | `COMPLETED`만 업로드할 수 있다. |
| `bundle` | `video.mp4`, `frame_timestamps.csv`, `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`, `metadata.json`의 완결된 집합. |
| `uploadState` | 아래 상태 전이 규칙을 따른다. |
| `lastUploadAttempt` | 마지막 요청의 UTC 시각, HTTP status(있는 경우), server error code(있는 경우), 사용자 표시용 실패 요약 또는 receipt 결과. |

## UploadAttempt

한 번의 사용자가 시작한 `POST /episodes` 요청을 나타낸다.

| 필드 | 규칙 |
| --- | --- |
| `episodeId` | bundle의 불변 `episodeId`와 같다. |
| `idempotencyKey` | `episodeId`와 정확히 같다. 재전송에도 변경하지 않는다. |
| `startedAtUtc` | 요청 시작 시각. UI의 진행·마지막 시도 표시에 사용한다. |
| `httpStatus` | 응답을 받지 못한 경우에는 없음. |
| `resultKind` | `CREATED`, `DUPLICATE`, `FAILED` 중 하나. |
| `failureSummary` | 사용자 표시용 짧은 오류 요약. 성공 시 없음. |

## RemoteReceipt

서버가 수신 성공으로 응답할 때의 최소 JSON이다.

| 필드 | 규칙 |
| --- | --- |
| `episode_id` | 요청의 `episodeId`와 정확히 일치해야 한다. 다르면 성공으로 처리하지 않는다. |
| `result` | `created` 또는 `duplicate`만 허용한다. |

## 업로드 상태 전이

```text
COMPLETED + LOCAL_ONLY --user starts upload--> UPLOADING
COMPLETED + FAILED --user starts retry--> UPLOADING
UPLOADING --201 + matching { episode_id, created }--> UPLOADED
UPLOADING --200 + matching { episode_id, duplicate }--> UPLOADED
UPLOADING --all non-success HTTP/transport results or malformed/mismatched receipt--> FAILED
UPLOADING --app process ends / no receipt--> FAILED on next catalog recovery
```

- `UPLOADED`, `FAILED` 모두 recording state는 `COMPLETED`다.
- `FAILED`는 요청·입력 문제를 수정하지 않는 한 같은 요청을 자동으로 다시 보내지 않는다. MVP는 수동 재전송 제어만 제공한다.
- 모든 상태에서 원본 bundle과 `metadata.json`은 변경·삭제하지 않는다.

## 업로드 직전 불변성 검증

1. `recordingState == COMPLETED`인지 확인한다.
2. 여섯 필수 파일이 모두 존재하는지 확인한다.
3. `metadata.json`의 다섯 원본 파일 path·size·SHA-256이 실제 파일과 일치하는지 확인한다. `metadata.json` 자신은 self-hash가 불가능하므로 manifest 대상이 아니다.
4. 검증에 실패하면 HTTP 요청을 만들지 않고 `FAILED` 및 실패 요약을 기록한다.
