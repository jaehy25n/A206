# 계약: Session `metadata.json`

**작성일**: 2026-09-14 | **명세**: [spec.md](../spec.md)

Session 번들의 `metadata.json`이 수신 측에 제공하는 형식. 이번 변경은 **`camera` 객체 추가만** 수행하며 기존 키는 건드리지 않는다.

## 형식

```json
{
  "session_id": "0f1c8a7e-...",
  "camera_streams": {
    "main": true,
    "ultrawide": false
  },
  "camera": {
    "camera_id": "0",
    "image_width": 1080,
    "image_height": 1920,
    "fx": 1491.645,
    "fy": 1491.892,
    "cx": 538.478,
    "cy": 973.016,
    "focal_length_mm": 4.32,
    "sensor_width_mm": 5.645,
    "sensor_height_mm": 4.234,
    "distortion_coefficients": [0.1234, -0.2345, 0.0012, 0.0009, 0.0456],
    "video_rotation_degrees": 90
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
| `camera` | **신규** | 촬영에 사용된 Camera 정보. 획득 실패 시 키 자체가 생략된다 |
| `files` | 유지 | 번들 파일 manifest. `metadata.json` 자신은 포함하지 않는다 |

### `camera` 객체

| 키 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `camera_id` | string | 예 | ARCore가 실제로 연 Camera의 ID |
| `image_width` | int | 예 | `main_rgb.mp4`의 가로 해상도와 일치 |
| `image_height` | int | 예 | `main_rgb.mp4`의 세로 해상도와 일치 |
| `fx` | number | 예 | 위 해상도 기준 초점 거리 (픽셀) |
| `fy` | number | 예 | 위 해상도 기준 초점 거리 (픽셀) |
| `cx` | number | 예 | 위 해상도 기준 주점 (픽셀) |
| `cy` | number | 예 | 위 해상도 기준 주점 (픽셀) |
| `focal_length_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `sensor_width_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `sensor_height_mm` | number | 아니오 | 기기 미제공 시 키 생략 |
| `distortion_coefficients` | number[] | 아니오 | 기기 미제공 시 키 생략. 순서는 Camera2 `LENS_DISTORTION` 정의를 따른다 |

## 불변식

1. `fx` / `fy` / `cx` / `cy`는 `camera_id`와 `image_width` × `image_height` 조합에 대응하는 값이다. 기기 일반 대표값이 아니다.
2. `image_width` × `image_height`는 같은 번들의 `main_rgb.mp4` 해상도와 일치한다.
3. 선택 키는 값을 계산해 채우지 않는다. 확보하지 못하면 키를 생략한다.
4. `camera` 객체 전체를 확보하지 못해도 Session 마감과 업로드는 정상 완료된다.
5. 기존 키 세 개(`session_id`, `camera_streams`, `files`)의 형식과 의미는 변경되지 않는다.

## 하위 호환

수신 측 파이프라인과 앱의 `SessionBundleValidator`는 모두 `session_id`, `camera_streams`, `files`만 읽고 알 수 없는 키를 무시한다. `camera` 추가는 하위 호환 변경이며, 기존 EC2 업로드 경로 수정이 필요하지 않다.

`camera` 키가 없는 과거 Session도 계속 유효하다. 수신 측은 키 부재를 "해당 Session에 Camera 정보 없음"으로 해석한다.

## 영상 회전 (2026-09-15 추가)

`camera` 객체에 `video_rotation_degrees`(int, 기본 0)가 추가됐다. `main_rgb.mp4`에 적용한 시계 방향
회전이며, `image_width`·`image_height`·`fx`·`fy`·`cx`·`cy`는 **이 회전을 반영한 기하**다.

따라서 위 "`image_width` × `image_height`는 `main_rgb.mp4` 해상도와 일치한다"는 규칙은
**회전을 반영해 디코딩했을 때** 성립한다. 컨테이너에 저장된 track 해상도는 회전 전 값 그대로다.

값이 없거나 `0`이면 회전 이전 수집분이며, 예전 규칙이 그대로 적용된다.

Pose와 함께 쓸 때 필요한 변환은 [video-orientation.md](video-orientation.md)에 있다.
