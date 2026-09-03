# 로컬 Capture Session Bundle 계약

## 저장과 완료 조건

모든 raw 파일은 앱 전용 외부 저장소의 `Android/data/com.ssafy.s15p21a206.tiger/files/capture/staging/<session_id>/`에 기록한다. `DATA COLLECTION END` 뒤 모든 writer를 finalize하고 필수 파일 존재·0보다 큰 크기·CSV header를 검사한다. 모든 raw file의 lowercase SHA-256을 metadata manifest에 남긴다. 검증 후 `metadata.json`을 마지막 commit marker로 작성하고 `capture/completed/<session_id>/`에 Session directory를 공개한다.

`metadata.json`은 commit marker다. 파일 누락, writer 오류, 저장 공간 부족, process death 또는 회복 불가능한 Camera/IMU 오류가 발생한 Session은 `INTERRUPTED`로 남고 completed 목록 및 upload 대상에서 제외한다.

completed로 공개된 bundle만 export 대상이다. staging은 raw recording 및 finalize 전 작업 영역이며 export 성공·실패·취소로 삭제하거나 변경하지 않는다.

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

## SAF export 계약

Android Storage Access Framework tree 선택은 Documents 위치에서 시작한다. completed bundle은 사용자가 명시적으로 선택한 접근 가능한 모든 tree URI에 export할 수 있다. UI의 기본 제안 이름은 `TigerCapture/<session_id>/`이며, 생성되는 최종 directory와 모든 child document는 반드시 선택된 tree URI 하위에 있어야 한다. 기본 제안은 선택된 tree 밖의 공용 Documents 절대 경로에 쓰도록 해석해서는 안 된다.

마지막으로 선택한 tree URI의 persistable 접근 권한은 앱 재시작 뒤에도 export 재시도에 재사용한다. 접근 권한이 철회되었거나 유효하지 않으면 export는 실패하고 사용자는 새 tree URI를 선택해야 한다.

export state는 `NOT_EXPORTED → EXPORTING → EXPORTED` 또는 `EXPORTING → EXPORT_FAILED → EXPORTING`이다. `EXPORT_FAILED`의 재시도는 동일한 immutable completed source를 사용하며, recording state·upload state·source manifest를 변경하지 않는다. 선택된 tree URI 아래에 같은 `session_id` directory가 있으면 그 대상 bundle을 덮어쓴 뒤 export한다. 대상 덮어쓰기 또는 이후 검증 실패는 `EXPORT_FAILED`이며 source bundle을 변경하지 않는다.

export는 completed bundle의 내용을 복사하는 동작이다. export 전에 source bundle을 검증하고, 대상에 기록한 뒤 아래 조건을 다시 모두 확인한 경우에만 성공으로 기록한다.

- main-only 또는 metadata가 선언한 Ultra-wide 구성과 정확히 일치하는 필수 파일 집합
- 각 CSV의 이 문서에 정의된 header
- metadata manifest의 relative filename, byte size, lowercase SHA-256과 대상 파일의 일치
- `metadata.json`의 session ID, camera stream 선언 및 manifest 선언의 일치

tree 선택 취소, persistable URI 권한 상실, 대상 directory/file 생성 실패, 공간 부족, I/O 오류 또는 사후 검증 실패는 export 실패다. 실패 시 source staging/completed bundle을 삭제·변경하지 않고 실패 원인을 표시하며 동일 Session export 재시도를 허용한다. 부분 기록된 대상은 성공 completed bundle으로 표시하지 않으며 자동 삭제하지 않는다. 다음 재시도는 같은 대상 directory를 다시 덮어쓴다.

이 계약은 공용 Documents 저장소 직접 쓰기 권한을 요구하지 않는다. 앱 삭제 전 bundle을 보존하려면 사용자가 성공적으로 export를 완료해야 하며 앱 전용 staging/completed 데이터의 삭제 방지는 제공하지 않는다.
