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

episode ID/name, task/object, 상태, logical/selected physical camera ID, lens facing, focal length, sensor physical size, active/pre-correction array, size/FPS/zoom/OIS/EIS, timestamp source/timebase status, row/frame count를 기록한다. `intrinsicCalibration`, `distortion`, `poseRotation`, `poseTranslation`, `poseReference`는 기록하지 않는다.
