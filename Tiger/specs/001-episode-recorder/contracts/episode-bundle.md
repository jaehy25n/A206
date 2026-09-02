# 로컬 Episode Bundle 계약

## 완료 조건

completed episode는 `video.mp4`, `frame_timestamps.csv`, `accelerometer.csv`, `gyroscope.csv`, `rotation_vector.csv`, `metadata.json`을 모두 포함한다. `metadata.json`은 파일 완결성 검증 뒤 마지막으로 작성하는 commit marker다.

필수 파일 누락·파싱 실패·`onCaptureBufferLost`·`onCaptureFailed`·capture sequence abort·Camera device/session·encoder·muxer·writer 오류는 `INTERRUPTED`이며 completed 목록에서 제외한다.

## 센서 CSV

```csv
# accelerometer.csv / gyroscope.csv
timestamp_ns,x,y,z,accuracy

# rotation_vector.csv
timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy
```

각 row는 Android callback 하나다. timestamp와 값은 제공 원본을 보존한다.

## Frame timestamp

`frame_timestamps.csv`의 헤더는 다음과 같다.

```csv
frame_number,timestamp_ns,timestamp_source
```

각 row는 성공한 Camera capture 하나다. MP4 frame↔timestamp 대응의 완전 검증은 이 MVP 범위 밖이다.

## Metadata

JSON은 `episode_id`(불변 UUID 문자열), `task`, `object`, `outcome`, `recording_start_monotonic_timestamp_ns`, `recording_end_monotonic_timestamp_ns`, `recording_duration_ns`, `device`, `camera`, `timebase.camera_imu_comparability`, `sample_counts`, `files`를 기록한다. 정확한 nested schema는 `episode-upload.md`를 따른다. 로컬 클래스의 `episodeId`는 metadata JSON에서 `episode_id`로 직렬화한다. `intrinsicCalibration`, `distortion`, `poseRotation`, `poseTranslation`, `poseReference`는 기록하지 않는다.

`files` object에는 `metadata.json`을 제외한 다섯 원본 파일 각각의 상대 path, `size_bytes`, `sha256`을 기록한다. `metadata.json` 자신의 크기·해시를 그 안에 기록하면 내용을 수정할 때마다 값이 바뀌므로 manifest 대상에서 제외한다. 이 값은 finalized bundle의 실제 파일과 일치해야 하며, 서버 업로드 계약의 `metadata` part는 이 `metadata.json` 원문을 변경 없이 사용한다.
