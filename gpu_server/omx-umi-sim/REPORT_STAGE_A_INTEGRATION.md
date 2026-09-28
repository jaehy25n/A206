# Stage A 통합 실행 보고서

**2026-09-21 · 실 CPU 데이터 end-to-end 완주**

CPU `omx_processed_v1_posefix_1` 출력이 GPU 파이프라인을 통과해
`[16, 10]` trajectory 를 내는 것까지 확인했다.

```
Transfer         : OK
RGB/Pose Align   : OK
Handoff Contract : OK
T_camera_EE      : PLACEHOLDER
Gripper Width    : MISSING
Training Status  : INTEGRATION ONLY
```

Stage A 이므로 `INTEGRATION ONLY` 가 정상이다.
**이 실행 결과를 baseline 성능으로 보고하면 안 된다** (§7 참고).

관련 문서: [contract](README_HANDOFF_CONTRACT.md) ·
[sync](README_CPU_GPU_SYNC.md) · [validation](README_GPU_VALIDATION.md) ·
[workflow](README_GPU_WORKFLOW.md)

---

## 1. 실행 환경

| | |
|---|---|
| 일시 | 2026-09-21 12:06 ~ 12:17 KST |
| branch / commit | `omx-gpu-baseline` @ `7e83048` |
| env | `~/.conda/envs/umi` (py3.9.18, torch 2.1.0+cu121) |
| GPU | physical **5** — Tesla V100-PCIE-32GB (sm_70) |
| mirror | `~/omx_data/processed/v1` |
| collector config | `configs/collector/default.yaml` (`v0-stageA-placeholder`) |

---

## 2. Republish

기존 mirror 를 수동 삭제하지 않고 구현된 republish flow 를 사용했다.

```bash
./scripts/sync_processed_from_cpu.sh -n --force-resync
./scripts/sync_processed_from_cpu.sh    --force-resync
./scripts/sync_processed_from_cpu.sh    --prune-orphans
```

```
dry-run           READY 5 · 교체대상 5 · 고아 2
--force-resync    synced 5 (replaced 5), 옛 사본 → .superseded/
--prune-orphans   15769f88, e096668c → .superseded/*.orphan.*
재실행             already synced, skipping ×5      (멱등 확인)
```

고아 2개는 CPU 가 `NO_VALID_TRACKING_POSE` 로 reject 한 session 이다.
**삭제하지 않고 이동**했으므로 되돌릴 수 있다.

### CPU 보고 대비

| | CPU | GPU 실측 |
|---|---|---|
| READY sessions | 5 | **5** |
| published segments | 7 | **7** |
| published rows | 1,283 | **1,283** |
| rejected episodes | 2 | 고아 2로 처리됨 |

세션별 분포: `1a1574b7` 1 · `2804e7e7` 1 · `778c65a6` 1 · `9828e36e` 1 ·
`e4942008` **3**

---

## 3. Strict inspection

```bash
python scripts/inspect_synced_processed.py -v
```

```
[handoff contract]
  ok   omx_processed_v1_posefix_1 (source 30 Hz, policy 10 Hz,
                                   action_horizon 16, min_publish_segment_frames 48)
  ok   CPU publish gate is 48 source frames vs the GPU requirement of 46
       -- the CPU is 2 frame(s) more conservative, which is fine.
  sessions validated : 5/5

[episodes]
  count              : 7
  total frames       : 1283
  length (source)    : min=53 max=496 mean=183.3
  measured fps       : 30.00 / 30.00 / 30.00      (config 30.0)
  min usable length  : 16 stored (~46 source)
  CPU-interpolated   : 0/1283 frames across 7 episodes carrying provenance columns

  ok  1a1574b7../episode_..  rows=  96  3.2s 30.0fps invalid=0 interp=0
  ok  2804e7e7../episode_..  rows=  98  3.2s 30.0fps invalid=0 interp=0
  ok  778c65a6../episode_..  rows= 295  9.8s 30.0fps invalid=0 interp=0
  ok  9828e36e../episode_..  rows= 169  5.6s 30.0fps invalid=0 interp=0
  ok  e4942008../episode_..  rows= 496 16.5s 30.0fps invalid=0 interp=0
  ok  e4942008../episode_..  rows=  76  2.5s 30.0fps invalid=0 interp=0
  ok  e4942008../episode_..  rows=  53  1.7s 30.0fps invalid=0 interp=0
```

**invalid frame 0, blank pose 0.** `pose_interpolated` 컬럼은 존재하지만
이번 출력에서는 실제 보간된 행이 없다 (CPU trim 만으로 해결된 것으로 보임).

exit 0.

---

## 4. Handoff contract 검증

이번에 추가한 공통 검증 (`omx/data/handoff_contract.py`) 결과.

| 항목 | CPU | GPU | 판정 |
|---|---|---|---|
| `version` | `omx_processed_v1_posefix_1` | 지원 목록에 존재 | OK |
| `source_hz_reference` | 30.0 | 30.0 | OK (exact) |
| `policy_hz_reference` | 10.0 | 10.0 | OK (exact) |
| `action_horizon_reference` | 16 | 16 | OK (exact) |
| `min_publish_segment_frames` | 48 | 요구 46 | **OK (48 ≥ 46)** |

`min_publish_segment_frames` 만 부등호 검사다. CPU 가 **2 frame 더 보수적**인
것이므로 mismatch 가 아니며, 그렇게 보고된다.
session / segment metadata 사본이 모두 일치함도 확인.

---

## 5. Pose chain 독립 검증

`frames.csv` (GPU 가 소비) 와 `trajectory.npz` (CPU 가 계산) 는 서로 다른 코드
경로의 산물이다. GPU 가 pose chain 을 다시 계산해 비교했다.

| npz 배열 | GPU 재계산과의 최대 차이 |
|---|---|
| `T_world_camera` | **4.4e-16** |
| `T_world_EE` | **4.4e-16** |
| `T_episode0_EE` | **5.3e-16** |
| `T_camera_EE` | **0** |
| `pose_valid` / `pose_interpolated` / `pose_valid_original` | 0 rows differing |

기계정밀도 일치는 quaternion ordering, 단위, world frame, `T_camera_EE` 적용,
episode-relative 변환이 양쪽에서 같은 의미라는 독립적 증거다.

---

## 6. 파이프라인

### dry-run

```bash
python -m omx.cli build omx_pick_raw_center_v1 --dry-run
```

```
found 7 episode(s)
handoff contract : ok × 5 sessions
7 episode(s), 431 frames @ 10 Hz (43.1 s)
  episode length  min=18 max=166 mean=61.6
  usable training samples (action_padding=False): ~326
  robot0_eef_pos              (431,3) min=-0.22197 max=+0.22085
  robot0_eef_rot_axis_angle   (431,3) min=-0.97415 max=+0.73154
  robot0_gripper_width        (431,1) 0.10500 (constant placeholder)
contract violation : 0
```

### build

```bash
python -m omx.cli build omx_pick_raw_center_v1 --overwrite
```

```
rgb: 640x480 --center_crop--> 224x224
     crop_box_xywh [80, 0, 480, 480]   effective HFOV 49.79 deg
done: data/omx/zarr/omx_pick_raw_center_v1.zarr.zip  (8.8 MB)
```

### zarr inspection

```bash
python -m omx.cli inspect omx_pick_raw_center_v1
```

```
[ok] keys == required set
[ok] episode_ends strictly increasing, matches n_steps
[ok] camera0_rgb uint8 (431,224,224,3)
[ok] no NaN/Inf in any low-dim array
[ok] 0 episode(s) too short to sample from
[ok] task obs_down_sample_steps (1) matches what the converter recorded
[ok] action shape == (16, 10)
[ok] camera0_rgb obs shape == (2, 3, 224, 224)
[ok] robot0_eef_rot_axis_angle obs shape == (2, 6)
[ok] dataset[0] is entirely finite
[ok] camera0_rgb scaled to [0,1]
[ok] all sampled actions finite
[ok] action[0] position ~0  (relative-to-observation semantics)

train samples 309 · val samples 17 · val episode [0]
position XYZ  x[-0.0720,+0.1401] y[-0.0602,+0.2209] z[-0.2220,+0.2039] m
|rotvec|      0.000 ~ 1.009 rad
frame-to-frame |dp|  median 0.0065  p99 0.0595  max 0.1021 m

ALL CHECKS PASSED (3 warnings)
```

### smoke training

```bash
python -m omx.cli train omx_pick_raw_center_v1 --profile smoke
```

```
CUDA_VISIBLE_DEVICES=5
CLIP ViT-B/16 loaded · obs encoder 85.8M params · UNet 85.5M params
"vit will use the CLS token. feature_aggregation (attention_pool_2d) is ignored!"
train dataset 309 (78 batches) · val dataset 17 (5 batches)

train_loss 1.1206 -> 1.0947      (forward · loss · backward 통과)
checkpoints  latest.ckpt, epoch=0000-train_loss=1.108.ckpt   (각 1.3 GB)
```

`meta.*` provenance 22개 항목이 hydra config 에 기록되어 W&B 로도 그대로 간다
(dataset sha256, calibration version, git commit, GPU, profile 포함).

> `meta.git_dirty=True` 로 기록되는데, 이는 repo 에 원래 있던 untracked 파일
> (`cup_in_the_wild.zarr.zip`, `umi_working_env.yml` 등) 때문이고 이번 파이프라인
> 코드는 전부 커밋된 상태였다.

---

## 7. 이번 실행에서 발견해 고친 것

### 7.1 trajectory.npz 교차검증이 틀려 있었다

healthy 데이터에서 7/7 전부 MISMATCH 를 냈다. `[N,4,4]` 배열 중 **첫 번째**를
집었는데 알파벳 순으로 `T_episode0_EE` 가 먼저였고, 그걸 `T_world_camera` 와
비교하고 있었다. 서로 다른 양을 비교한 것이다.

이름으로 매칭하도록 고치고, 겸사겸사 pose chain 전체 + provenance 컬럼까지
비교하도록 확장했다 (§5 가 그 결과). CPU 와 GPU 양쪽에 non-identity
`T_camera_EE` 가 동시에 있으면 이중 적용 위험이므로 경고도 추가했다.

### 7.2 collector intrinsics 해상도가 실제와 달랐다

processed_v1 은 **640×480 (4:3)** 로 기록되는데 config 는 1920×1080 (16:9) 였다.
종횡비가 다른 상태로 intrinsics 를 rescale 하면 `fx` 와 `fy` 가 서로 다른 배율로
늘어나 실제 렌즈로선 의미가 없다.

* `matched_center_crop` → **거부** (reprojection 이 기하학적으로 틀림)
* `center_crop` / `letterbox` → 경고 후 FOV 수치 생략 (crop/resize 자체는 무관)
* config 를 640×480 으로 수정

> **남은 것**: `hfov_deg: 63.5` 는 여전히 datasheet 추정치다. Step 1 camera
> matching 실험 전에 collector / robot 양쪽의 실제 `fx, fy, cx, cy` 캘리브레이션이
> 필요하다.

### 7.3 상수 gripper 를 hard FAIL 로 잡고 있었다

Stage A 에서는 CPU 가 `gripper_width_m` 을 아직 내보내지 않으므로 상수
placeholder 가 **의도된 상태**다. `gripper.status == calibrated` 일 때만 FAIL 하고
그 외에는 dataset 을 integration-only 로 낮추도록 바꿨다 — `T_camera_EE`
placeholder 를 다루는 방식과 동일하게.

---

## 8. 데이터에 대한 관찰

파이프라인과 별개로, 이번 7 segment 자체에 대해 기록해둔다.

**RGB 내용이 목표 task 가 아니다.** 사무실에서 손에 든 폰으로 찍은 영상으로,
빨대 꽂힌 컵 · 노트북 · 의자가 보인다. 핸드오프 문서 §2 의
*고정 배경 · 고정 조명 · 단일 block pick-and-place* demonstration 이 아니다.
파이프라인 검증에는 충분하지만 학습 데이터로는 쓸 수 없다.

**이미지가 약 90° 회전되어 있다.** collector 를 어떻게 들었는지에 달렸지만,
robot wrist camera 는 같은 방향이 아닐 것이므로 domain gap 이 된다.
수집 자세를 고정하거나 CPU 단계에서 회전을 정규화해야 한다.

**규모가 작고 길이 편차가 크다.** 431 stored frames (43초), episode 길이
18 ~ 166 stored frames (1.8 ~ 16.6초). 목표인 60 episodes 에 비해 매우 작다.

**gripper 신호가 없다.** 상수이므로 action 10차원 중 gripper 축은 학습에서
아무 정보도 주지 않는다.

---

## 9. Stage B 진입 조건

| | 필요한 것 | 담당 |
|---|---|---|
| 1 | 목표 task 의 demonstration 수집 (§8) | 수집 |
| 2 | `T_camera_EE` calibration | 캘리브레이션 |
| 3 | marker 기반 `gripper_width_m` (meter) | CPU |
| 4 | collector / robot 카메라 `fx,fy,cx,cy` (Step 1 실험용) | 캘리브레이션 |

2·3 은 **raw 재수집이 필요 없다.** 같은 processed 데이터에 converter 를 다시
돌리면 된다.

```bash
$EDITOR configs/collector/default.yaml
#   camera_to_ee: {status: calibrated, calibration_version: "v1-...", ...}
#   gripper:      {mode: width_m, status: calibrated}
python -m omx.cli build omx_pick_raw_center_v1 --overwrite
```

---

## 10. 산출물

```
data/omx/zarr/omx_pick_raw_center_v1.zarr.zip        8.8 MB
data/omx/zarr/omx_pick_raw_center_v1.meta.json        19 KB   (contract · calibration · 에피소드별 출처)
data/omx/inspect/omx_pick_raw_center_v1/
    rgb_samples.png  rgb_augmentation_preview.png  trajectories.png  step_size.png
data/omx/train/omx_pick_raw_center_v1/2026.09.21/12.16.58/
    checkpoints/latest.ckpt                          1.3 GB
    checkpoints/epoch=0000-train_loss=1.108.ckpt     1.3 GB
    logs.json.txt  .hydra/config.yaml
```

### mirror

```
~/omx_data/processed/v1/            52 MB   5 sessions · 7 segments · 1,283 rows
```

교체·고아 7건(72 MB)이 `.superseded/` 에 남아 있었으나, 새 데이터가 검사를
전부 통과하고 원본이 CPU 에도 있으므로 2026-09-21 12:29 에 정리했다
(`123 MB → 52 MB`). 삭제 후 inspection 재실행 결과 동일하게 통과.

```bash
rm -rf ~/omx_data/processed/v1/.superseded
```

> smoke run 하나가 checkpoint 2.6 GB 를 쓴다 (`latest` + topk 1개, 각 1.3 GB).
> full training 은 `checkpoint_every: 10` · `topk.k: 20` 이므로 120 epoch 에서
> 약 15 GB 를 쓴다. `/home` 에 11 TB 여유가 있어 문제는 아니지만 예산에 넣어둔다.

---

## 11. 재현

```bash
conda activate umi
cd ~/universal_manipulation_interface

./scripts/sync_processed_from_cpu.sh -n --force-resync
./scripts/sync_processed_from_cpu.sh    --force-resync
./scripts/sync_processed_from_cpu.sh    --prune-orphans

python scripts/inspect_synced_processed.py -v
python -m omx.cli build   omx_pick_raw_center_v1 --dry-run
python -m omx.cli build   omx_pick_raw_center_v1 --overwrite
python -m omx.cli inspect omx_pick_raw_center_v1
python -m omx.cli train   omx_pick_raw_center_v1 --profile smoke

python tests/test_omx_contract.py      # 15/15
```

seed 42 고정이라 smoke training 의 loss 는 재실행해도 동일하다
(`1.1206 → 1.0947` 재현 확인).
