# 로컬 Capture Session Bundle 계약

## 저장과 완료 조건

모든 raw 파일은 `capture/staging/session_<display>_<short_session_id>/`에 기록한다. `DATA COLLECTION END` 뒤 모든 writer를 finalize하고 필수 파일 존재·0보다 큰 크기·CSV header를 검사한다. 파일 SHA-256을 계산할 수 있으면 metadata manifest에 남긴다. 검증 후 `metadata.json`을 마지막으로 작성하고 `capture/completed/`에 Session directory를 공개한다.

`metadata.json`은 commit marker다. 파일 누락, writer 오류, 저장 공간 부족, process death 또는 회복 불가능한 Camera/IMU 오류가 발생한 Session은 `INTERRUPTED`로 남고 completed 목록 및 upload 대상에서 제외한다.

## 필수 파일

main-only Session은 다음 파일을 정확히 포함한다.

```text
metadata.json
main_rgb.mp4
main_frame_timestamps.csv
accelerometer.csv
gyroscope.csv
rotation_vector.csv
arcore_poses.csv
episodes.csv
```

`metadata.camera_streams.ultrawide`가 `true`인 Session은 다음 두 파일도 정확히 포함한다.

```text
ultrawide_rgb.mp4
ultrawide_frame_timestamps.csv
```

## CSV 형식

```csv
# main_frame_timestamps.csv, ultrawide_frame_timestamps.csv
frame_number,timestamp_ns,timestamp_source

# accelerometer.csv, gyroscope.csv
timestamp_ns,x,y,z,accuracy

# rotation_vector.csv
timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy

# arcore_poses.csv
android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason

# episodes.csv
episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome
```

Camera frame timestamp는 `SENSOR_TIMESTAMP`, IMU timestamp는 sensor event의 원본 timestamp, Episode event timestamp는 monotonic timestamp를 기록한다. ARCore row의 canonical join key는 `android_camera_timestamp_ns`다. 모든 timestamp 열은 decimal nanosecond integer를 보존한다. `end_timestamp_ns`는 열린 Episode인 동안 비어 있을 수 있으나 completed Session에는 비어 있으면 안 된다.

## Metadata 최소 계약

`metadata.json`은 최소한 `session_id` UUID, display number, recording/upload state, start/end monotonic timestamp, device model, camera streams, main camera 설정, ARCore enabled/shared-camera/camera ID, timestamp comparability 결과, sample counts와 raw file manifest를 기록한다.

`camera_streams.main`은 항상 `true`다. `camera_streams.ultrawide`는 실제 optional 파일 존재 여부와 반드시 같아야 한다. 기기에서 제공되는 focal length, sensor size, intrinsic calibration, distortion 정보는 metadata에 반드시 기록한다. 지원되지 않는 값은 임의로 생성하지 않는다.

Episode는 독립 raw directory나 file manifest를 소유하지 않는다. 각 Episode row의 outcome은 `COMPLETED`, `CANCELLED`, `INVALID_TRACKING` 중 하나다.
