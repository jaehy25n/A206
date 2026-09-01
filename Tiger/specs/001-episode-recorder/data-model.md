# 데이터 모델: Episode Recorder MVP

## Episode

| 필드 | 규칙 |
| --- | --- |
| `episodeId` | 녹화 시작 시 생성하는 불변 UUID |
| `displayName` | `episode_0001` 형식 |
| `task`, `object` | 비어 있지 않은 자유 텍스트 |
| `recordingState` | `RECORDING` → `COMPLETED` 또는 `INTERRUPTED` |
| `syncState` | `LOCAL_ONLY` |
| `cameraConfig` | logical/selected physical ID, lens facing, focal length, sensor physical size, active/pre-correction array, size, FPS, zoom, OIS/EIS, timestamp source |
| `timebaseMetadata` | Camera `REALTIME` source와 `VERIFIED` status |
| `captureLog` | 중단 사유, 마지막 timestamp, frame/sensor 수, 오류 요약 |

```text
RECORDING --six-file validation--> COMPLETED
RECORDING --cancel/onStop/buffer-lost/capture-failed/sequence-abort/camera-session/encoder/muxer/writer error--> INTERRUPTED
INTERRUPTED --next launch--> raw staging cleanup + diagnostic log
COMPLETED --user-confirmed delete--> removed
CaptureLogs --user-confirmed clear-all--> removed
```

`COMPLETED`만 목록에 들어간다.

## 센서 record

| 파일 | 헤더 |
| --- | --- |
| `accelerometer.csv` | `timestamp_ns,x,y,z,accuracy` |
| `gyroscope.csv` | `timestamp_ns,x,y,z,accuracy` |
| `rotation_vector.csv` | `timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy` |

모든 `timestamp_ns`는 원본 나노초 정수값을 손실 없이 기록한다. rotation vector는 Android 제공 융합 이벤트값이며 roll·pitch·yaw는 저장하지 않는다. `heading_accuracy_rad`는 값이 없을 때에도 Android 원본 sentinel `-1`을 숫자로 기록한다.

## FrameTimestampRecord

각 row는 성공한 Camera capture의 `frame_number`, 원본 ns timestamp, timestamp source를 나타낸다. Camera callback의 buffer loss·capture failure·sequence abort는 즉시 interruption 사유로 기록한다. MP4 frame↔timestamp 대응의 완전 검증은 이 MVP 범위 밖이다.

## Bundle

```text
Episode
 ├── video.mp4
 ├── frame_timestamps.csv
 ├── accelerometer.csv
 ├── gyroscope.csv
 ├── rotation_vector.csv
 └── metadata.json (final commit marker)
```
