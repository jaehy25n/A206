# 로컬 Capture Session Bundle 계약

## 저장과 완료 조건

모든 raw 파일은 일반 파일 관리자가 직접 수정·삭제할 수 없는 앱 전용 내부 저장 영역의 `capture/staging/<session_id>/`에 기록한다. Session 종료 뒤 모든 writer를 finalize하고 필수 파일 존재·0보다 큰 크기·CSV header를 검사한다. 모든 raw file의 lowercase SHA-256을 metadata manifest에 남긴다. 검증 후 `metadata.json`을 마지막 commit marker로 작성하고 `capture/completed/<session_id>/`에 Session directory를 공개한다.

`metadata.json`은 commit marker다. 마감되지 못하고 staging에 남은 Session(화면 중단, process death, 마감 실패)은 다음 실행에서 다시 마감한다. 필수 파일·CSV header 검사를 통과하면 metadata를 쓰고 completed로 공개하며, 통과하지 못한 Session만 `INTERRUPTED`로 남아 completed 목록 및 upload 대상에서 제외된다(003 FR-027~FR-030).

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

`metadata.json`은 `session_id`(UUID), `camera_streams`(`main`·`ultrawide`), raw file manifest `files`를 기록한다. 촬영 Camera 정보를 확보하면 `camera`를, 수동 촬영 조건을 건 Session은 `capture_settings`를 더한다. 키 규약과 형식은 [Session `metadata.json` 계약](../../003-session-episode-tracking-gate/contracts/session-metadata.md)이 정한다.

이 절에 처음 적혀 있던 display number, recording/upload state, 시작·종료 monotonic timestamp, device model, ARCore 설정, timestamp comparability 결과, sample count는 metadata에 기록된 적이 없다. 번호와 상태·시각은 Room 색인이 들고, timebase는 Camera timestamp source가 `REALTIME`인지 Session 시작 전에 확인해 보장한다.

`camera_streams.main`은 항상 `true`다. `camera_streams.ultrawide`는 실제 optional 파일 존재 여부와 반드시 같아야 한다. 첫 유효 프레임에서 ARCore가 쓰는 Intrinsic을 확보하면, 기기에서 제공되는 focal length, sensor size, distortion 정보와 함께 `camera`에 기록한다. 지원되지 않는 값은 키를 생략하고 임의로 생성하지 않는다.

수동 제어를 지원하는 기기에서 찍은 Session은 그 촬영 조건을 `capture_settings`에 기록한다. 수집자가 값을 건드리지 않았으면 직전에 쓴 값이나 기본값이 걸린다. 요청한 값과 센서가 실제로 사용한 값을 나눠 담으며, 둘은 센서의 양자화만큼 어긋날 수 있다. 이 키가 없는 Session을 어떻게 읽을지는 위 계약의 하위 호환 절에 있다.

Episode는 독립 raw directory나 file manifest를 소유하지 않는다. 각 Episode row의 outcome은 `COMPLETED` 또는 `INVALID_TRACKING` 중 하나다. `CANCELLED` outcome은 사용하지 않는다.

## 번들을 기기 밖으로 내보내는 길

업로드 하나다. SAF 내보내기는 제거됐다. 그 계약이 있던 자리에는 tree 선택, persistable grant 재사용,
임시 directory에서의 publish와 재시도가 적혀 있었다.

앱을 지우기 전에 번들을 보존하려면 업로드를 마쳐야 한다. 앱 전용 staging/completed 데이터에 대한
삭제 방지는 제공하지 않는다.
