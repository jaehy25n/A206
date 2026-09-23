# 로컬 Capture Session Bundle 계약

## 저장과 완료 조건

모든 raw 파일은 일반 파일 관리자가 직접 수정·삭제할 수 없는 앱 전용 내부 저장 영역의 `capture/staging/<session_id>/`에 기록한다. `DATA COLLECTION END` 뒤 모든 writer를 finalize하고 필수 파일 존재·0보다 큰 크기·CSV header를 검사한다. 모든 raw file의 lowercase SHA-256을 metadata manifest에 남긴다. 검증 후 `metadata.json`을 마지막 commit marker로 작성하고 `capture/completed/<session_id>/`에 Session directory를 공개한다.

`metadata.json`은 commit marker다. 파일 누락, writer 오류, 저장 공간 부족, process death 또는 회복 불가능한 Camera/IMU 오류가 발생한 Session은 `INTERRUPTED`로 남고 completed 목록 및 upload 대상에서 제외한다.

completed로 공개된 bundle만 업로드 대상이다. staging은 raw recording 및 finalize 전 작업 영역이며 업로드의 성공·실패·취소로 삭제하거나 변경하지 않는다.

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

수집자가 촬영 조건을 직접 정한 Session은 그 조건을 `capture_settings`에 기록한다. 요청한 값과 센서가 실제로 사용한 값을 나눠 담으며, 둘은 센서의 양자화만큼 어긋날 수 있다. 조건을 기기 자동에 맡긴 Session에는 이 키가 없고, 그때는 노출·ISO·화이트 밸런스가 촬영 중 변했다고 보아야 한다. 형식은 [Session `metadata.json` 계약](../../003-session-episode-tracking-gate/contracts/session-metadata.md)에 있다.

Episode는 독립 raw directory나 file manifest를 소유하지 않는다. 각 Episode row의 outcome은 `COMPLETED` 또는 `INVALID_TRACKING` 중 하나다. `CANCELLED` outcome은 사용하지 않는다.

## 번들을 기기 밖으로 내보내는 길

업로드 하나다. SAF 내보내기는 제거됐다. 그 계약이 있던 자리에는 tree 선택, persistable grant 재사용,
임시 directory에서의 publish와 재시도가 적혀 있었다.

앱을 지우기 전에 번들을 보존하려면 업로드를 마쳐야 한다. 앱 전용 staging/completed 데이터에 대한
삭제 방지는 제공하지 않는다.
