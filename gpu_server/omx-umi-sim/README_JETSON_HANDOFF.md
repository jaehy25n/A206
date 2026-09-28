# GPU → Jetson Runtime Handoff

Jetson Orin 의 `omx_jetson_runtime` 이 **아무것도 추측하지 않고** 동일 결과를
재현할 수 있도록, GPU 학습/추론 코드의 contract 를 실제 source 에서 확정해
reference bundle 로 전달한다.

```bash
python scripts/make_jetson_handoff.py -e omx_pick_raw_center_v1
python jetson_handoff/verify_bundle.py        # repo 를 import 하지 않는 독립 검증
```

전달은 **zip 하나**로 한다. SSH/네트워크 설정이 필요 없고 전송 수단을 가리지
않는다 (scp / USB / 공유 드라이브).

```
omx_jetson_handoff_<commit>_<date>.zip     620 MB
  └─ jetson_handoff/                       checkpoint 685 MB 포함
     ├─ INSTALL.md          ← zip 안에 같이 들어가는 설치·검증 가이드
     ├─ SHA256SUMS          ← 전송 무결성
     └─ verify_bundle.py    ← repo 없이 도는 독립 검증
```

Jetson 수령 후 절차: **[`README_JETSON_SETUP.md`](README_JETSON_SETUP.md)**

관련 문서: [CPU↔GPU contract](README_HANDOFF_CONTRACT.md) ·
[validation](README_GPU_VALIDATION.md) · [workflow](README_GPU_WORKFLOW.md) ·
[Stage A 실행](REPORT_STAGE_A_INTEGRATION.md)

> **INTEGRATION ONLY — NOT FOR LIVE TASK EXECUTION.**
> 현재 checkpoint 는 load / shape / latency / decoder parity / preprocessing
> parity 확인용이다. OMX actuator command 에 연결하지 않는다.

---

## 1. 성공 조건

```
동일 RGB        → 동일 preprocessing
동일 observation → 동일 decode
동일 timestamp  → 동일 action-time 의미
```

문서를 옮겨 적는 방식이 아니라, bundle 생성 스크립트가 **매번 repo 의 pose
utility 를 직접 호출해 값을 재유도하고 assert** 한다. 따라서 코드가 바뀌면
bundle 생성이 실패하지, 조용히 낡은 값이 남지 않는다.

---

## 2. 책임 분리

| 항목 | GPU | Jetson |
|---|---|---|
| action semantics 정의 | **확정·문서화** | 해석 |
| decoder 정답 제공 | **생성** | parity 검증 |
| RGB preprocessing 정의 | **확정** | 재현 |
| action time 의미 | **확정** | stale-prefix 계산 |
| checkpoint / manifest | **생성** | live-ready gate |
| observation 동기화 | 안 함 | **수행** |
| receding horizon / 안전 | 안 함 | **수행** |
| 5DoF projection / IK | 안 함 | **수행** |

---

## 3. Action contract — `[16, 10]`

```
action[k, 0:3]   position    relative
action[k, 3:9]   rotation    rot6d, relative
action[k, 9]     gripper     absolute width [m]
```

| | 확정 내용 |
|---|---|
| **position** | T0 기준 relative 이고 **T0 EE 프레임에서 표현**. `p_rel[k] = R0ᵀ (p_abs[k] − p0)`. world 변위 **아님**, sequential delta **아님** |
| **rot6d** | 상대 회전행렬의 **첫 두 ROW**, row-major flatten `[R00,R01,R02,R10,R11,R12]` |
| **곱셈 순서** | `R_abs = R_base @ R_rel` (base 를 **왼쪽**). `R_rel @ R_base` 는 틀림 |
| **position 복원** | `p_abs[k] = R_base @ p_rel[k] + p_base` |
| **gripper** | **absolute** target width, `robot0_gripper_width` 와 같은 단위(meter). relative 아님, normalized 아님 |
| **base pose T0** | 마지막 observation timestep 의 EE pose (= 추론 시점 자세) |

### Decode

```python
T_rel  = pose10d_to_mat(action[:, :9])     # [16,4,4]
T_abs  = T_base @ T_rel                    # base 좌곱
p_abs  = R_base @ p_rel + p_base
R_abs  = R_base @ R_rel
```

### 근거 — `diffusion_policy/dataset/umi_dataset.py` `UmiDataset.__getitem__`

```python
action_pose_mat = convert_pose_mat_rep(action_mat,
                                       base_pose_mat=pose_mat[-1],   # ← t0, 상수
                                       pose_rep=self.obs_pose_repr,
                                       backward=False)
action_pose    = mat_to_pose10d(action_pose_mat)
action_gripper = data["action"][..., 7*r+6 : 7*r+7]                  # ← 변환 없음
```

* `base_pose_mat=pose_mat[-1]` 이 **16 step 내내 상수** → 전부 t0 기준. 직전
  action 기준이 아니다.
* `convert_pose_mat_rep(..., 'relative')` 는 `inv(base) @ pose` (forward) /
  `base @ pose` (backward) → 위의 곱셈 순서가 여기서 나온다.
* `mat_to_rot6d` 는 `mat[..., :2, :]` 즉 **행** 2개를 취한다.

> ⚠️ action 분기가 `action_pose_repr` 가 아니라 **`obs_pose_repr`** 를 쓴다.
> 현재 `task/umi_omx.yaml` 에서 둘 다 `relative` 라 결과가 같지만, action 을
> 실제로 지배하는 필드는 `pose_repr.obs_pose_repr` 다.

### 수치 probe (bundle 생성 시마다 실행·assert)

```
position is base-frame         True
position is world delta        False
rot6d = first two ROWS         True
rot6d = first two COLUMNS      False
R_abs == R_base @ R_rel        True
R_abs == R_rel @ R_base        False
forward/backward roundtrip     3.3e-16
```

---

## 4. Action time contract — **Case A**

```
action_dt_s            = 0.1
first_action_offset_s  = 0.0
action[k] target time  = t0 + k × 0.1
obs timestamps         = [-0.1, 0.0]
```

`t0` 는 **마지막** observation frame 의 시각이다.

### 근거 — `diffusion_policy/common/sampler.py` `sample_sequence`

```python
# action
slice_end = min(end_idx, current_idx + (action_horizon-1)*action_down_sample_steps + 1)
output    = input_arr[current_idx : slice_end : action_down_sample_steps]

# rgb observation
slice_start = current_idx - (num_valid-1)*this_downsample_steps
output      = input_arr[slice_start : current_idx+1 : this_downsample_steps]
```

두 window 가 **모두 `current_idx` 에서 끝난다** → action[0] 의 대상 frame 과
마지막 observation frame 이 같다.

데이터로도 확인: ground-truth `action[0]` 의 position `[3.7e-09, 0, 0]`,
rot6d `[1,0,0,0,1,0]` (항등).

> **`action[0]` 은 로봇이 이미 있는 자세다.** 운동량이 없으므로 실행 대상이
> 아니라 정렬 기준이다. Jetson 의 stale-prefix 계산은 이 점을 전제로 해야 한다.

> `action[0] ≈ 0` 은 **데이터의 성질**이지 정책 출력의 성질이 아니다. 학습된
> 정책이라야 근사적으로 만족한다. 현재 Stage A checkpoint(7 step 학습)에는
> 성립하지 않으므로 이걸로 검증하면 안 된다.

---

## 5. RGB preprocessing contract

```
color        cv2.imread → BGR → cv2.cvtColor(BGR2RGB)     (다른 모든 단계보다 먼저)
rotate_k     0
crop         중앙 정사각.  640×480 입력 → box (x,y,w,h) = (80, 0, 480, 480)
resize       cv2.resize(..., (224,224), interpolation=cv2.INTER_AREA)
range        uint8/255 → float32 [0,1]
layout       (C, H, W),  C = R,G,B
normalize    없음
```

### 경로

| 단계 | 위치 |
|---|---|
| 1. BGR→RGB | `omx/data/processed_v1.py` `read_rgb_indices` |
| 2. crop + resize | `omx/data/rgb_preprocess.py` `RgbPreprocessor.__call__` |
| 3. zarr 저장 (uint8) | `scripts/convert_processed_to_umi_zarr.py` |
| 4. `/255`, CHW | `diffusion_policy/dataset/umi_dataset.py` `__getitem__` |
| 5. normalizer | `diffusion_policy/common/normalize_util.py` `get_image_identity_normalizer` — scale 1, offset 0 |

---

## 6. 코드에서만 드러난 것 3가지

문서만 읽었으면 놓쳤을 것들이다. Jetson 구현에 직접 영향을 준다.

### 6.1 mean/std 정규화가 **없다**

`TimmObsEncoder.__init__` 은 `imagenet_norm` 인자를 받고 config 들이 `True` 로
주지만, **그 클래스는 이 인자를 한 번도 읽지 않는다.**

```bash
grep -n imagenet_norm diffusion_policy/model/vision/timm_obs_encoder.py
# 67:            imagenet_norm: bool=False,      ← 시그니처가 전부
```

`multi_image_obs_encoder.py:106` 은 실제로 쓰기 때문에 놓치기 쉽다. 결과적으로
CLIP ViT 는 **raw `[0,1]`** 을 받는다. CLIP/ImageNet mean·std 를 넣으면 안 된다.

### 6.2 정책이 **추론 시 자기 입력을 무작위화**한다

`TimmObsEncoder.forward`:

```python
img = self.key_transform_map[key](img)      # `if self.training` 가드 없음
```

```
Sequential(
  RandomCrop(size=(212, 212)),
  Resize(size=224, interpolation=bilinear, antialias=True),
  ColorJitter(brightness=(0.7,1.3), contrast=(0.6,1.4),
              saturation=(0.5,1.5), hue=(-0.08,0.08)),
)
```

torchvision 의 `RandomCrop` / `ColorJitter` 는 `self.training` 을 보지 않으므로
`policy.eval()` 로 꺼지지 않는다. 실측: 같은 입력 2회 forward 가 **1.9997** 차이.
상류 배포 스크립트 `scripts_real/eval_real_umi.py:216` 도 `policy.eval()` 만 하고
제거하지 않으므로 upstream 동작이다.

결론:

* **preprocessing contract 는 float tensor 까지가 정확**하다. 그 지점을
  `preprocessed_rgb.npy` 가 고정한다.
* **정책 출력은 bit 재현 불가**하다. Jetson 은 정책 출력이 아니라 **decoder** 를
  맞춰야 한다.
* ONNX / TensorRT export 시 이 transform 을 그래프에 넣을지 **명시적으로**
  정해야 한다. 빼면 학습 시 입력 분포와 달라지고, 넣으면 무작위성이 남는다.

### 6.3 학습 zarr 의 JpegXl 은 **손실 압축**이다

`JpegXl(level=99)` 은 무손실이 아니다 (난수 이미지 max 94 / 실제 reference
frame max 34, mean 0.61, uint8 기준). 즉:

```
학습  : 원본 → preprocess → JpegXl 왕복 → 모델
Jetson: 원본 → preprocess →              → 모델
```

Jetson 은 zarr 가 없으므로 **raw 경로가 재현 가능한 유일한 대상**이다. 그래서
`preprocessed_rgb.npy` 는 raw 경로 tensor 이고, 실제 encoder 가 받았던
zarr 경로 tensor 는 `preprocessed_rgb_from_zarr.npy` 로 **따로** 넣어 차이를
볼 수 있게 했다. ColorJitter 범위보다 훨씬 작지만 0 은 아니다.

---

## 7. Bundle 구성

`jetson_handoff/` (gitignore 됨 — 스크립트로 재생성)

| 파일 | 내용 |
|---|---|
| `model_manifest.json` | 위 전부의 기계 판독 형태 |
| `raw_rgb.png` | GPU preprocessing **직전** 원본 RGB |
| `preprocessed_rgb.npy` | **Jetson 목표**: raw → preprocess, `(3,224,224)` float32 [0,1] |
| `preprocessed_rgb_from_zarr.npy` | encoder 가 실제로 받았던 tensor (JpegXl 왕복 포함) |
| `observation_reference.npz` | observation dict 전체 + 절대 EE pose/gripper + frame index/시각 |
| `reference_action.npy` | 정책 raw 출력 `[16,10]` |
| `reference_decoded_pose.npz` | 위를 GPU decoder 로 푼 결과 |
| `decoder_reference.npz` | base pose + raw action + 기대 decode, **그리고** 모델 없이 검증 가능한 ground-truth action 세트 |
| `model_config.yaml` | checkpoint 에 저장된 hydra config |
| `decoder_source_reference.md` | 모든 값의 file/function 근거 |
| `README.md` | provenance + 재현 방법 |
| `verify_bundle.py` | repo 를 import 하지 않는 독립 검증 |
| `INSTALL.md` | Jetson 쪽 설치·검증 가이드 (zip 안에 동행) |
| `SHA256SUMS` | 전 파일 체크섬 — 전송 후 `sha256sum -c` |
| `checkpoint.ckpt` | EMA 가중치만 (685 MB). `model` 은 추론에 쓰이지 않아 제외 |

### Reference sample (고정, 무작위 아님)

```
dataset index          227
replay-buffer frame    304
episode                e4942008-…__episode_80b873e4-…
source frame           249   (rgb_frames/frame_000249.jpg)
obs frames             [303, 304]
action frames          [304 … 319]
torch seed             42
```

가장 긴 에피소드의 중간점이라 observation horizon 2 가 **서로 다른 두 프레임**
이다 (에피소드 첫 프레임을 쓰면 padding 된 중복 프레임이 된다).

---

## 8. 전달 방법

```bash
# GPU
python scripts/make_jetson_handoff.py -e omx_pick_raw_center_v1
#   -> omx_jetson_handoff_<commit>_<date>.zip  (620 MB)

# Jetson
unzip omx_jetson_handoff_*.zip        # unzip 없으면 python3 -m zipfile -e <zip> .
cd jetson_handoff
sha256sum -c SHA256SUMS               # 모든 줄이 OK 여야 함
python3 verify_bundle.py              # ALL BUNDLE CHECKS PASSED
```

### checkpoint 패키징

`--checkpoint-mode` 로 고른다.

| mode | 크기 | |
|---|---|---|
| `ema` | 685 MB | **기본값.** 추론이 실제로 쓰는 EMA 가중치만. `model` 685 MB 제외 |
| `full` | 1370 MB | 학습 checkpoint 와 byte 동일 |
| `ema-fp16` | 343 MB | 더 작지만 수치가 달라진다 |
| `none` | — | manifest 에 경로/sha256 만 |

`ema` 로 줄여도 `reference_action.npy` 가 **오차 0 으로 재현**되는 것을 zip 왕복
후 확인했다. 단 이 파일에는 `ema_model` 밖에 없으므로 **`ema_model` 을 로드해야
한다** — `model` 을 로드하면 학습되지 않은 네트워크를 얻는다. manifest 의
`packaged_checkpoint.load_with` 와 `verify_bundle.py` 가 이를 검사한다.

---

## 9. Jetson parity 절차

1. **preprocessing** — `raw_rgb.png` 를 자체 파이프라인에 통과시켜
   `preprocessed_rgb.npy` 와 float32 정밀도로 일치할 것.
   (`preprocessed_rgb_from_zarr.npy` 는 학습 코덱 영향을 *보기* 위한 것이지
   맞출 대상이 아니다.)
2. **decoder, 모델 없이** — `decoder_reference.npz` 의 `groundtruth_raw_action`
   + `base_pose6` 를 decode 해 `groundtruth_true_position` /
   `groundtruth_true_rotvec` 와 비교. 모델이 개입하지 않으므로 ~1e-6 으로
   일치해야 한다.
3. **decoder, 정책 출력** — `raw_action` 을 decode 해 `expected_position` /
   `expected_rotvec` 와 비교.
4. **timing** — `action_target_times_s` 가 `t0 + k×action_dt_s` (k 는 0 부터)
   와 같은지.

**정책 출력의 bit 일치를 assert 하지 말 것** (§6.2).

---

## 10. 자체 parity 결과

```
preprocessed_rgb.npy roundtrip            0.000e+00
raw_rgb.png → preprocess vs saved tensor  0.000e+00
decoded position / rotation / gripper     0.000e+00

decoder vs 기록된 궤적 (ground-truth action, 모델 무관)
  position  1.49e-08 m
  rotation  8.40e-08 rad
  gripper   0.0 m

정책 결정성
  같은 seed   0.000e+00
  seed 없음   1.9997        ← §6.2 in-policy augmentation

JpegXl 왕복 (학습 프레임 vs Jetson 이 넣을 프레임, uint8)
  max 34 / mean 0.6095

latency 141.02 ms/call  (B=1, 16 denoise steps, Tesla V100)
```

그리고 `verify_bundle.py` 가 **repo 를 전혀 import 하지 않고** README 의
contract 만 보고 decoder 를 새로 구현해 대조한다. 전부 통과 → bundle 이
자립적이다.

---

## 11. 현재 상태

```json
"verified": true,          // contract 범위 (semantics / time / preprocessing / decoder)
"live_ready": false
```

`live_ready` blocker 3건:

1. `T_camera_EE` 가 placeholder (`placeholder` / `none`) — EE 궤적이 물리적으로
   보정되지 않음
2. gripper 가 placeholder — `robot0_gripper_width` 가 이 dataset 에서 상수
3. checkpoint 가 Stage A 통합 실행 결과 (task 영상이 아닌 7 segment, 7 step 학습)

`verified` 는 **contract 가 코드로 확인되었다**는 뜻이지 checkpoint 가 task 에
적합하다는 뜻이 아니다. Jetson 의 live gate 는 `live_ready` 를 봐야 한다.

---

## 12. Stage B 에서 바뀌는 것 / 안 바뀌는 것

**바뀌지 않는다** — action semantics, rot6d layout, 곱셈 순서, gripper 의미,
`action_dt_s`, `first_action_offset_s`, RGB preprocessing. Jetson 구현을 다시
고칠 필요 없다.

**바뀐다**:

| | |
|---|---|
| `checkpoint` / `checkpoint_sha256` | 실제 학습된 정책으로 교체 |
| `live_ready` | blocker 해소 시 `true` |
| gripper 값 | 상수 → marker 기반 실제 width |
| EE 궤적 | `T_camera_EE` 보정 반영 |
| `rgb_preprocess.effective_hfov_deg` | 실제 intrinsics 보정 후 값 |

Stage B 로 넘어가면 같은 명령으로 bundle 을 다시 만들고, Jetson 은
`checkpoint_sha256` 과 `live_ready` 만 다시 확인하면 된다.

```bash
python scripts/make_jetson_handoff.py -e omx_pick_raw_center_v1
python jetson_handoff/verify_bundle.py
```
