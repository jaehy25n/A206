# 수신 측 안내: 영상 회전과 좌표계

**대상**: Tiger Session 번들을 읽어 학습 데이터로 쓰는 쪽
**적용 시점**: 2026-09-15 이후 수집분
**관련**: [S15P21A206-30](https://ssafy.atlassian.net/browse/S15P21A206-30)

---

## 요약

`main_rgb.mp4`에 **시계 방향 90도 회전 정보**가 붙었다. `metadata.json`의 Camera Intrinsic도 같은
회전을 반영해 바뀌었다. **`arcore_poses.csv`의 Pose는 바뀌지 않았다.**

Pose와 Intrinsic을 함께 쓰려면 아래 §4의 변환을 한 번 적용해야 한다.

---

## 1. 왜 바뀌었나

Android 기기의 Camera 센서는 물리적으로 90도 눕혀 장착돼 있다(`SENSOR_ORIENTATION = 90`).
그래서 인코더에 들어가는 프레임은 가로로 누운 상태다.

이전 수집분은 이 회전을 보정하지 않아, 저장된 영상이 90도 돌아간 채였다. 수집 화면에서는
Android가 프리뷰를 자동으로 세워 주기 때문에 이 사실이 드러나지 않았다.

이번 변경으로 영상과 Intrinsic이 모두 세운 기준으로 맞춰졌다.

---

## 2. `main_rgb.mp4`

`MediaRecorder.setOrientationHint(90)`으로 회전 정보를 남긴다. **픽셀은 다시 인코딩하지 않는다.**
저장된 프레임 자체는 여전히 가로(1920×1080)이고, 컨테이너의 track 행렬에 회전이 기록된다.

```text
tkhd matrix:  0,  65536, 0
             -65536,  0, 0
              0,      0, 1073741824     ← 시계 방향 90도
```

**도구에 따라 결과가 다르다. 이 점이 가장 중요하다.**

| 도구 | 동작 | 디코딩 결과 |
|---|---|---|
| `ffmpeg` / `ffprobe` | 회전 행렬 반영 | **1080×1920** (세움) |
| Android·Windows 기본 플레이어 | 반영 | 1080×1920 (세움) |
| OpenCV `cv2.VideoCapture` | **무시** | 1920×1080 (누운 원본) |
| PyAV | 기본 무시, 옵션으로 반영 | 설정에 따름 |

`metadata.json`의 Intrinsic은 **회전을 반영한 1080×1920 기준**이다. 회전을 무시하는 도구를 쓴다면
§5의 확인 절차를 반드시 거칠 것.

---

## 3. `metadata.json`

`camera` 객체가 회전 후 기하를 담는다. 어떤 회전이 적용됐는지 `video_rotation_degrees`로 밝힌다.

```json
"camera": {
  "camera_id": "0",
  "image_width": 1080,
  "image_height": 1920,
  "fx": 1491.6453,
  "fy": 1491.8923,
  "cx": 538.47815,
  "cy": 973.0162,
  "video_rotation_degrees": 90
}
```

회전 전 값과의 대응은 다음과 같다. `W`, `H`는 회전 전 가로·세로(1920, 1080)다.

| 필드 | 회전 후 |
|---|---|
| `image_width` | `H` |
| `image_height` | `W` |
| `fx` | 회전 전 `fy` |
| `fy` | 회전 전 `fx` |
| `cx` | `H - 회전 전 cy` |
| `cy` | 회전 전 `cx` |

픽셀 좌표 기준으로는 회전 전 `(x, y)`가 회전 후 `(H - y, x)`로 옮겨진다.
연속 좌표계를 쓰며 픽셀 중심 보정(−1)은 하지 않는다.

`video_rotation_degrees`가 없거나 `0`이면 회전 이전 수집분이다.

---

## 4. `arcore_poses.csv` — 반드시 읽을 것

**Pose는 회전하지 않았다.** ARCore가 준 값을 그대로 기록한다. 원본 기록을 보존하기 위해서다.

Pose는 World → Camera 변환이고, Camera 좌표계는 **회전 전 이미지 기준**이다.
반면 Intrinsic은 회전 후 기준이다. 그대로 곱하면 90도 어긋난다.

투영할 때 둘 중 하나를 택한다.

### 방법 A. Camera 좌표를 돌린다 (권장)

Camera 좌표계의 점을 Intrinsic에 넣기 전에 광축(Z축) 기준으로 한 번 돌린다.

```python
import numpy as np

# 시계 방향 90도로 저장한 영상에 대응하는 Camera 좌표 회전
R_Z = np.array([[0.0, 1.0, 0.0],
                [-1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0]])

K = np.array([[fx, 0.0, cx],
              [0.0, fy, cy],
              [0.0, 0.0, 1.0]])   # metadata.json의 회전 후 값

def project(point_world, R_wc, t_wc):
    """R_wc, t_wc는 arcore_poses.csv에서 만든 World → Camera 변환."""
    p_cam = R_wc @ point_world + t_wc
    p_cam = R_Z @ p_cam
    p_img = K @ p_cam
    return p_img[:2] / p_img[2]
```

### 방법 B. 영상을 되돌린다

회전을 무시하고 1920×1080 원본으로 디코딩한 뒤, `video_rotation_degrees`를 역으로 적용해
Intrinsic을 회전 전 값으로 되돌린다(§3 표의 역변환). 그러면 Pose와 Intrinsic이 모두 회전 전
기준이 되어 추가 변환이 필요 없다. 기존 파이프라인을 바꾸고 싶지 않다면 이쪽이 간단하다.

`arcore_poses.csv`의 쿼터니언 `(qx, qy, qz, qw)`는 ARCore Camera Pose의
`rotationQuaternion`이며 회전 적용 여부와 무관하게 형식이 같다.

---

## 5. 수신 측에서 확인할 것

1. **영상 디코딩 도구가 회전 행렬을 반영하는가?**
   ```bash
   ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation -of csv main_rgb.mp4
   python -c "import cv2; c=cv2.VideoCapture('main_rgb.mp4'); print(c.get(3), c.get(4))"
   ```
   두 결과의 가로세로가 다르면 도구별로 다르게 읽고 있다는 뜻이다.

2. **디코딩된 프레임 크기가 `metadata.json`의 `image_width`/`image_height`와 같은가?**
   다르면 §2의 표에서 어느 경우인지 확인하고 §4의 방법 A 또는 B를 적용한다.

3. **투영 검산.** ARCore Pose로 3D 점을 투영해 영상 위 위치와 맞는지 한 프레임만 확인한다.
   90도 어긋나 있으면 §4를 적용하지 않은 것이다.

---

## 6. 영향 범위

| 파일 | 변경 |
|---|---|
| `main_rgb.mp4` | 회전 행렬 추가. **픽셀·frame 수·해상도는 그대로** |
| `metadata.json` | `camera` 기하가 회전 후 기준. `video_rotation_degrees` 추가 |
| `arcore_poses.csv` | **변경 없음** |
| `main_frame_timestamps.csv` | 변경 없음 |
| `episodes.csv`, IMU CSV | 변경 없음 |
| 번들 파일 구성·업로드 방식 | 변경 없음 |

`frame_number`와 `timestamp_ns`의 대응은 그대로다. 회전은 frame 수에 영향을 주지 않는다.

---

## 7. 이전 수집분과 섞일 때

`video_rotation_degrees`로 구분한다.

| 값 | 의미 |
|---|---|
| 없음 또는 `0` | 2026-09-15 이전 수집분. 영상·Intrinsic·Pose가 모두 회전 전 기준. §4 변환 불필요 |
| `90` | 이번 변경 이후. §4 적용 필요 |

한 학습 세트에 두 종류를 섞을 경우, 이 값을 보고 전처리에서 통일할 것.

---

## 8. 논의가 필요한 사항

Pose를 앱에서 미리 돌려 내보내는 선택지도 있다. 그러면 수신 측 변환이 불필요해지지만
`arcore_poses.csv`가 더 이상 ARCore 원본 기록이 아니게 된다. 현재는 원본 보존을 택했다.

수신 측에서 Pose까지 회전된 상태를 원하면 알려 주기 바란다.

---

## 부록: 실기기 확인값

아래는 해상도를 올리기 전(640×480) 기록이다. 회전 규약 자체는 그대로이며 숫자만 달라졌다.

`SM-G973N`, Android 12, 2026-09-15 수집분 `72e463a1`.

```text
tkhd matrix       0, 65536, 0 / -65536, 0, 0 / 0, 0, 1073741824   (시계 방향 90도)
track 해상도      640 x 480   (회전 전 픽셀. 회전을 반영하면 480 x 640)
metadata.camera   image_width 480, image_height 640,
                  fx 497.2151, fy 497.29745, cx 239.82605, cy 324.0054,
                  video_rotation_degrees 90
```

같은 번들의 `main_frame_timestamps.csv` 721행 대 MP4 722 frame(차이 1), `frame_number` 결번 0건으로
회전이 frame 대응에 영향을 주지 않음을 확인했다.

### 1920×1080 전환 후

`SM-G973N`, Android 12, 2026-09-16 수집분. 6초 수집.

```text
track 해상도      1920 x 1080   (회전 전 픽셀. 회전을 반영하면 1080 x 1920)
metadata.camera   image_width 1080, image_height 1920,
                  fx 1491.6453, fy 1491.8923, cx 538.47815, cy 973.0162,
                  video_rotation_degrees 90
frame 수          179 frame / 5.991초 = 29.9 FPS
```

회전 전 기준으로 `fx`·`fy`가 모두 정확히 3배가 됐다(497.29745 → 1491.8923, 497.2151 → 1491.6453).
가로는 640 → 1920으로 3배라 초점 거리와 같은 비율이므로 **화각이 그대로**다. 세로는 480 → 1080으로
2.25배뿐인데 초점 거리는 3배가 됐으므로 **화각이 좁아졌다**. 4:3 CPU 이미지 대신 16:9 GPU 텍스처
스트림을 녹화 기준으로 삼으면서 위아래가 잘린 결과다.
