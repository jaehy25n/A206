# GPU → CPU 서버 요청 정리

2026-09-22 기준. GPU 쪽에서 막혀 있거나, 데이터만 봐서는 확인할 수 없는 것들.

우선순위는 **GPU 쪽이 실제로 막혀 있는 정도** 순이다.

---

## 먼저 — 이미 잘 되어 있는 것

pose 쪽 계보 추적은 손댈 데가 없다. `quality.json` / `metadata.json` 에
`invalid_pose_count_before_repair`, `interpolated_pose_frames`,
`trimmed_start_frames`, `original_frame_range`, `segment_index`,
`dropped_short_segment_frames` 까지 있어서 **최종 프레임 하나가 원본 어디서
왔는지 되짚을 수 있다.** `handoff_contract` 블록도 GPU 가 기계적으로 검증하고
있고 5/5 통과 중이다.

아래 요청은 전부 **pose 가 아닌 축** — 픽셀과 태스크 의미 — 에 대한 것이다.

---

## P0 — 한 줄이면 답이 나오고, 지금 제일 크게 막혀 있다

### 원본 MP4 의 해상도

`session_metadata.json` 의 `raw_manifest` 에 파일별 `sha256` 과 `size_bytes` 는
있는데 **영상 속성이 하나도 없다.**

```json
"raw_manifest": {
  "main_rgb.mp4": { "sha256": "063d7fb5…", "size_bytes": 902108 }
}
```

GPU 가 받는 프레임은 **640x480 (4:3)** 인데, 원본 MP4 가 몇 x 몇인지 알 방법이
없다. EXIF 도 비어 있다.

**왜 이게 P0 인가.** GPU 의 FOV 실험 3 arm (center crop / letterbox / 직사각형
ViT) 이 전부 여기에 달려 있다. 실험 설계와 합성 픽스처는 **16:9 전제**로
만들어졌는데 실데이터가 4:3 이다. 두 경우로 갈린다.

| 원본 MP4 | 의미 | 할 일 |
|---|---|---|
| **16:9** | CPU 전처리 어딘가에서 4:3 으로 만들고 있다 → **수평 화각을 버리는 중** | 그 단계를 찾아 고치면 설계대로 복원. 재수집 불필요 |
| **4:3** | 수집 시점에 이미 그 화각뿐 | 실험 3 arm 을 4:3 기준으로 다시 정의하거나, 16:9 로 재수집 |

192 프레임에 902 KB (≈4.7 KB/프레임) 이라 원본도 저해상도일 가능성이 높아
보이지만, **추측이고 증명이 안 된다.**

> GPU 쪽은 이 답이 나올 때까지 FOV 실험을 못 돌린다. 지금은 빌드가
> `source aspect 1.3333 ... does not match the 1.7778 this experiment declares`
> 로 거부하고 있다 (의도된 동작).

---

## P1 — Stage B 를 여는 캘리브레이션 3종

전부 GPU 가 placeholder 로 돌리고 있고, 셋 다 "값 하나 넣으면 열리는" 상태다.

### 1. `T_camera_EE` 실측

```
현재: calibration_status = "placeholder_identity_not_for_training"
      T_camera_EE = identity (4x4)
```

**막고 있는 것**: 내보내는 EE 궤적이 물리적 EE 궤적이 아니다. 지금은 카메라
궤적을 EE 궤적이라고 부르고 있는 셈. 학습은 돌지만 로봇에 쓸 수 없다.

재수집은 필요 없다 — 값이 들어오면 **재변환만** 하면 된다.

### 2. `gripper_width_m` (marker 기반)

```
현재: gripper 컬럼 자체가 없음 → GPU 가 상수 0.105 m 로 채움
```

**막고 있는 것**: action 10차원 중 gripper 축이 신호를 전혀 안 나른다. 그리고
reference 값이 상수라 **어떤 decoder 를 넣어도 parity 가 통과한다** — Jetson
쪽 검증에서 이 축은 사실상 무의미하다.

canonical 표현은 **미터 단위 물리 개구폭** (0~1 정규화 아님).

### 3. `collector_intrinsics` 실측

```
현재: hfov_deg = 63.5   # Galaxy S10 main, 데이터시트 추측
      fx, fy, cx, cy, dist_coeffs 없음
```

**막고 있는 것**: Step 1 의 `matched_center_crop` 실험. 수집 카메라(S10)와 로봇
카메라(LUAZ 100)가 다르므로 FOV 정합이 필요한데, 정합하려면 **양쪽 다** 실측
intrinsics 가 있어야 한다. 로봇 쪽은 팀원이 1920x1080 으로 작업 중이니,
남은 건 수집 카메라 쪽이다.

**프레임이 실제로 저장되는 해상도 기준**으로 주면 된다. 다른 해상도 값을 주면
aspect 가 달라지는 순간 fx/fy 가 서로 다른 배율로 늘어나서 의미가 없어지고,
GPU 변환기가 거부한다.

---

## P2 — 데이터 자체

### 현재 보유량

```
세션 5개 / 에피소드 7개 / 1,283 프레임
= 30 Hz 기준 42.8초        (10 Hz 저장 시 427 프레임)
object 라벨: {"sush", "test", "sd"}
```

**43초짜리 배관 확인용 데이터셋**이다. 파이프라인 검증에는 충분했고 실제로 P0~P3
를 다 닫았지만, 정책을 학습시킬 양은 아니다.

### 필요한 것

- **목표 태스크의 실제 시연.** 지금 `object` 가 `sush` / `test` / `sd` 라
  무엇을 하는 데이터인지 알 수 없다
- 분량 — UMI 계열은 보통 태스크당 수십 분~수 시간 단위

---

## P3 — 계약의 구멍 메우기

지금 당장 막지는 않지만, 나중에 조용히 틀어질 자리들.

### 1. 영상/픽셀 provenance 를 `session_metadata.json` 에

pose 쪽 계보는 완벽한데 **픽셀 쪽은 계보가 없다.** 최소한:

```json
"raw_manifest": {
  "main_rgb.mp4": {
    "sha256": "…", "size_bytes": 902108,
    "width": 1920, "height": 1080,      // ← 이게 P0
    "fps": 30.0, "codec": "h264"
  }
},
"rgb_decode": {
  "decoder": "ffmpeg 6.1",
  "filters": "scale=640:480",           // ← 리사이즈/크롭을 했다면 그대로
  "output_width": 640, "output_height": 480,
  "aspect_changed": true                // ← 4:3 로 바뀌었는지
}
```

`aspect_changed` 하나만 있어도 P0 질문이 애초에 안 생긴다.

### 2. 에피소드별 RGB 해상도를 `metadata.json` 에

지금 GPU 가 JPEG 를 직접 열어 확인한다. 세션마다 해상도가 다르면 변환기가
거부하는데(의도됨), **전송 전에 보이는 게 낫다.**

```json
"rgb_width": 640, "rgb_height": 480
```

### 3. `object` 라벨 규약

자유 문자열이라 GPU 가 태스크별로 묶거나 거를 수 없다. 짧은 슬러그 규약이면
충분하다 (`pick_cup`, `place_plate` 같은).

### 4. 시연 성공 여부

```
현재: outcome = "COMPLETED"  (7/7)
```

이건 **녹화가 끝까지 됐다**는 뜻이지 **시연이 성공했다**는 뜻이 아니다.
모방학습은 성공 시연만 쓰거나 최소한 구분해서 써야 한다. 실패/부분성공을
구분하는 필드가 필요하다.

```json
"demonstration_outcome": "success" | "failure" | "partial"
```

지금은 `rejected_episode_*` / `failed_episode_*` 디렉토리 규약으로 **수집
실패**만 걸러지고, **시연 실패**는 표현할 방법이 없다.

---

## 요약

| | 항목 | 막고 있는 것 |
|---|---|---|
| **P0** | 원본 MP4 해상도 | FOV 실험 3 arm 전부 |
| **P1** | `T_camera_EE` 실측 | 물리적 EE 궤적 |
| **P1** | `gripper_width_m` marker 기반 | action 10차원 중 gripper 축 |
| **P1** | `collector_intrinsics` 실측 | Step 1 카메라 정합 실험 |
| **P2** | 목표 태스크 시연 데이터 | 실제 정책 학습 |
| **P3** | 영상 provenance / RGB 해상도 / object 규약 / 시연 성공 여부 | 지금은 아님 |

**P0 는 질문 하나다.** 나머지가 시간이 걸리는 동안 이것만 먼저 답해주면 GPU 쪽
FOV 실험이 바로 열린다.

---

## 관련 문서

- `README_HANDOFF_CONTRACT.md` — 지금 검증 중인 CPU↔GPU 계약
- `README_GPU_VALIDATION.md` — GPU 쪽 수용 기준
- `REPORT_JETSON_INFERENCE_BRINGUP.md` — Jetson 배포 쪽 현황
