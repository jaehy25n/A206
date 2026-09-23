# 계약: Session `metadata.json`

**작성일**: 2026-09-14 | **명세**: [spec.md](../spec.md)

Session 번들의 `metadata.json`이 수신 측에 제공하는 형식. 기존 키는 건드리지 않고 객체를 더하기만 한다. 2026-09-14에 `camera`를, 2026-09-23에 `capture_settings`를 더했다.

## 형식

```json
{
  "session_id": "0f1c8a7e-...",
  "camera_streams": {
    "main": true,
    "ultrawide": false
  },
  "capture_settings": {
    "mode": "manual",
    "requested": {
      "focus_distance_diopter": 4.0,
      "iso": 100,
      "exposure_time_ns": 8333333,
      "frame_duration_ns": 33333333,
      "fps_target": 30
    },
    "actual": {
      "focus_distance_diopter": 3.9916728,
      "iso": 100,
      "exposure_time_ns": 8333000,
      "frame_duration_ns": 33333000,
      "af_mode": "OFF",
      "ae_mode": "OFF",
      "awb_mode": "OFF",
      "awb_locked": false
    },
    "awb_fixed": true
  },
  "camera": {
    "camera_id": "0",
    "image_width": 1920,
    "image_height": 1080,
    "fx": 1485.753,
    "fy": 1491.148,
    "cx": 948.760,
    "cy": 541.121,
    "focal_length_mm": 4.32,
    "sensor_width_mm": 5.645,
    "sensor_height_mm": 4.234,
    "distortion_coefficients": [0.1234, -0.2345, 0.0012, 0.0009, 0.0456],
    "video_rotation_degrees": 0
  },
  "files": [
    { "path": "accelerometer.csv", "sizeBytes": 184320, "sha256": "…" },
    { "path": "main_rgb.mp4", "sizeBytes": 48213504, "sha256": "…" }
  ]
}
```

## 키 규약

| 키 | 상태 | 설명 |
|---|---|---|
| `session_id` | 유지 | Session UUID |
| `camera_streams.main` | 유지 | 항상 `true` |
| `camera_streams.ultrawide` | 유지 | 이번 범위에서는 항상 `false` |
| `camera` | 2026-09-14 추가 | 촬영에 사용된 Camera 정보. 획득 실패 시 키 자체가 생략된다 |
| `capture_settings` | 2026-09-23 추가 | 그 Session의 촬영 조건. 수동 설정을 쓰지 않은 Session은 키 자체가 생략된다 |
| `files` | 유지 | 번들 파일 manifest. `metadata.json` 자신은 포함하지 않는다 |

### `camera` 객체

| 키 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `camera_id` | string | 예 | ARCore가 실제로 연 Camera의 ID |
| `image_width` | int | 예 | `main_rgb.mp4`의 가로 해상도와 일치. Session마다 다를 수 있다 |
| `image_height` | int | 예 | `main_rgb.mp4`의 세로 해상도와 일치. Session마다 다를 수 있다 |
| `fx` | number | 예 | 위 해상도 기준 초점 거리 (픽셀) |
| `fy` | number | 예 | 위 해상도 기준 초점 거리 (픽셀) |
| `cx` | number | 예 | 위 해상도 기준 주점 (픽셀) |
| `cy` | number | 예 | 위 해상도 기준 주점 (픽셀) |
| `focal_length_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `sensor_width_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `sensor_height_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `distortion_coefficients` | number[] | 아니오 | 기기 미제공 시 키 생략. 순서는 Camera2 `LENS_DISTORTION` 정의를 따른다 |
| `video_rotation_degrees` | int | 아니오 | `main_rgb.mp4`에 적용된 시계 방향 회전. 기본 `0`. 아래 [영상 회전](#영상-회전-2026-09-16-갱신) 참고 |

### `capture_settings` 객체

수집자가 정한 촬영 조건과, 센서가 실제로 사용한 값. 둘을 나눠 담는 것이 이 객체의 요점이다.
`CaptureRequest`에 넣었다고 센서가 그 값을 썼다고 볼 수 없고, calibration은 실제로 쓰인 값 위에서만
뜻이 있다.

| 키 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `mode` | string | 예 | 수동 설정을 쓴 Session은 `manual` |
| `requested` | object | 아니오 | 사용자가 정해 `CaptureRequest`에 건 값 |
| `actual` | object | 아니오 | 첫 유효 프레임 이후 `CaptureResult`에서 읽은 값. 프레임을 받지 못하면 키 생략 |
| `awb_fixed` | bool | 예 | 화이트 밸런스를 고정했는지. 고정하지 않았으면 `false`로 적으며 키를 생략하지 않는다 |

`requested` 객체:

| 키 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `focus_distance_diopter` | number | 예 | `0`이 무한대, 클수록 가깝다. 단위는 diopter(1/m) |
| `iso` | int | 예 | `SENSOR_SENSITIVITY` |
| `exposure_time_ns` | int | 예 | `SENSOR_EXPOSURE_TIME` |
| `frame_duration_ns` | int | 예 | `SENSOR_FRAME_DURATION`. 30 fps면 `33333333` |
| `fps_target` | int | 예 | 항상 `30`. 기본값과 같아도 생략하지 않는다 |

`actual` 객체. 읽지 못한 항목은 **키를 생략한다.** 값을 계산해 채우지 않는다.

| 키 | 타입 | 비고 |
|---|---|---|
| `focus_distance_diopter` | number | `LENS_FOCUS_DISTANCE` |
| `iso` | int | `SENSOR_SENSITIVITY` |
| `exposure_time_ns` | int | `SENSOR_EXPOSURE_TIME` |
| `frame_duration_ns` | int | `SENSOR_FRAME_DURATION` |
| `af_mode` | string | `OFF`, `AUTO`, `CONTINUOUS_VIDEO` 등 |
| `ae_mode` | string | `OFF`, `ON` 등 |
| `awb_mode` | string | `OFF`, `AUTO` 등 |
| `awb_locked` | bool | `CONTROL_AWB_LOCK` |

수신 측이 알아 둘 것이 둘 있다.

- **`requested`와 `actual`은 정확히 같지 않다.** 센서가 노출과 프레임 간격을 µs로 양자화해 돌려주므로
  `8333333`을 요청하면 `8333000`이 온다. 초점도 렌즈 스텝 해상도만큼 어긋난다(요청 `4.0` D에 대해
  실측 `3.9916728` D). 비교할 때는 허용 오차를 둔다.
- **`awb_fixed`가 `false`인데 `actual.awb_mode`가 `AUTO`인 것은 정상이다.** 화이트 밸런스를 고정하지
  않고 찍은 Session이며, 그 Session의 색은 촬영 중 변했다고 보아야 한다.

## 불변식

1. `fx` / `fy` / `cx` / `cy`는 `camera_id`와 `image_width` × `image_height` 조합에 대응하는 값이다. 기기 일반 대표값이 아니다.
2. `image_width` × `image_height`는 같은 번들의 `main_rgb.mp4` 해상도와 일치한다.
3. 선택 키는 값을 계산해 채우지 않는다. 확보하지 못하면 키를 생략한다.
4. `camera` 객체 전체를 확보하지 못해도 Session 마감과 업로드는 정상 완료된다.
5. 기존 키 세 개(`session_id`, `camera_streams`, `files`)의 형식과 의미는 변경되지 않는다.
6. `capture_settings`의 값은 그 Session **전체**에 적용된다. 촬영 도중 조건이 바뀌지 않는 것이 이 기능의
   전제이며, 앱은 Session이 시작되면 설정을 잠근다.
7. `capture_settings` 전체를 확보하지 못해도 Session 마감과 업로드는 정상 완료된다.

## 하위 호환

수신 측 파이프라인과 앱의 `SessionBundleValidator`는 모두 `session_id`, `camera_streams`, `files`만 읽고 알 수 없는 키를 무시한다. `camera`와 `capture_settings` 추가는 모두 하위 호환 변경이며, 기존 EC2 업로드 경로 수정이 필요하지 않다.

`camera` 키가 없는 과거 Session도 계속 유효하다. 수신 측은 키 부재를 "해당 Session에 Camera 정보 없음"으로 해석한다.

`capture_settings` 키가 없는 Session은 **촬영 조건을 기기 자동에 맡긴 수집**이다. 그 Session의 노출·ISO·화이트 밸런스는 프레임마다 변했다고 보아야 하며, 다른 Session에서 구한 intrinsic이나 LUT를 그대로 적용할 근거가 없다. 수동 설정을 지원하지 않는 기기에서 찍은 Session과, 이 항목이 생기기 전에 찍은 Session이 여기 해당한다.

## 녹화 해상도 (2026-09-16 갱신)

`main_rgb.mp4`의 해상도는 Session마다 다를 수 있다. 수집자가 Session 전에 카메라 설정에서
`1920×1080` 또는 `1280×720`을 고르며, 기본값은 `1920×1080`이다.

`image_width` × `image_height`는 언제나 그 Session이 실제로 녹화한 해상도이고, `fx`·`fy`·`cx`·`cy`도
같은 해상도 기준이다. 수신 측은 해상도를 고정값으로 가정하지 말고 이 두 키에서 읽는다.

## 영상 회전 (2026-09-16 갱신)

**`main_rgb.mp4`에는 회전이 적용되지 않는다.** 폰을 가로로 눕혀 촬영하므로 센서가 내보내는 가로
프레임이 곧 똑바로 선 장면이다. 컨테이너의 회전 행렬은 항등이고 `metadata.json`의 Intrinsic도
같은 가로 기준이다. `arcore_poses.csv`의 Camera 좌표계도 같은 기준이라 추가 변환 없이 함께 쓴다.

`camera` 객체의 `video_rotation_degrees`(int, 기본 `0`)는 그 Session의 `main_rgb.mp4`에 적용된
시계 방향 회전이며, 지금은 항상 `0`이다. 값이 `90`인 번들은 2026-09-15~16 사이 회전 규약이 있던
시기의 수집분이다. 그 수집분만 다음이 성립한다.

- `image_width`·`image_height`·`fx`·`fy`·`cx`·`cy`가 **회전 후** 기하다. 컨테이너에 저장된 track
  해상도는 회전 전 값이므로, 회전을 무시하는 도구(`cv2.VideoCapture` 등)로 열면 둘이 어긋난다.
- `arcore_poses.csv`의 Pose는 회전 전 기준이다. Intrinsic과 함께 쓰려면 Camera 좌표를 광축 기준
  시계 방향 90도로 한 번 돌리거나, Intrinsic을 회전 전 값으로 되돌려야 한다.

한 학습 세트에 두 종류가 섞이면 이 값을 보고 전처리에서 통일한다.
