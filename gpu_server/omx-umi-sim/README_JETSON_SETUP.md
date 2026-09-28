# Jetson 수령 후 작업 가이드

GPU 서버에서 받은 두 아카이브로 Jetson Orin 에서 Stage A checkpoint 를
`predict_action()` 까지 한 번 돌리는 절차.

목표는 이것 하나다.

```
reference observation → Stage A checkpoint → [1,16,10] → decoded [16,3]
```

ROS·로봇·컨트롤러는 **전혀 연결하지 않는다.**

> **INTEGRATION ONLY — NOT FOR LIVE TASK EXECUTION.**
> 이 checkpoint 는 load / shape / latency / parity 확인용이다.
> OMX actuator command 에 연결하지 않는다.

관련 문서: [contract](README_JETSON_HANDOFF.md) ·
[CPU↔GPU](README_HANDOFF_CONTRACT.md)

---

## 1. 옮길 파일 — 정확히 4개

| 파일 | 크기 | |
|---|---|---|
| `omx_jetson_handoff_0d9d30d_20260922.zip` | 620.5 MB | checkpoint + reference + 검증 스크립트 |
| `omx_jetson_handoff_0d9d30d_20260922.zip.sha256` | 106 B | 위 파일의 해시 |
| `jetson_inference_source_0d9d30d.tar.gz` | 12.5 MB | checkpoint 를 load 할 수 있는 소스 스냅샷 |
| `jetson_inference_source_0d9d30d.tar.gz.sha256` | 105 B | 위 파일의 해시 |

```
9204efd33e0ea3b1ebc0cc79ca727a2d51dd3aa716fa6a2ec567f61b0f822269  omx_jetson_handoff_0d9d30d_20260922.zip
```

> **tar.gz 의 해시는 여기 적지 않는다.** 이 문서가 그 tar.gz **안에** 들어가기
> 때문이다. tar 를 만들기 전에는 tar 의 해시를 알 수 없으므로, 안에 적힌 값은
> 구조적으로 항상 한 세대 전 값이 된다. 동봉된
> `jetson_inference_source_*.tar.gz.sha256` 을 기준으로 삼는다.

```bash
sha256sum -c jetson_inference_source_0d9d30d.tar.gz.sha256
```

`.sha256` 파일은 **아카이브 자체**의 무결성용이다. 아카이브 *안*의 파일별
체크섬(`SHA256SUMS`)은 이미 아카이브 안에 들어 있으므로 별도 전달이 필요 없다.

전송 수단은 상관없다 — scp / USB / 공유 드라이브.

### ⚠️ 이미 한 번 옮기셨다면 반드시 확인

오늘 **같은 파일명으로 여러 세대**가 만들어졌다. 커밋과 날짜가 같아 이름이
동일하지만 **내용이 다르다.**

```bash
sha256sum omx_jetson_handoff_0d9d30d_20260922.zip
```

| 해시 | 상태 |
|---|---|
| `9204efd3…` | **현재 버전. 이걸 쓴다** |
| `72228e33…` | 이전 버전 — `observation_reference.npz` 의 키 충돌 버그 있음. 폐기 |

이전 버전은 `obs_` 접두어로 observation 을 고르면 프레임 인덱스 배열
(`obs_frames`)이 딸려 들어와 추론이 `AttributeError: 'ParameterDict' object has
no attribute 'frames'` 로 죽는다. 현재 버전은 그 배열들이
`frame_index_obs` / `frame_index_action` 으로 바뀌었고 manifest 에
`observation_keys` 목록이 들어 있다.

**contract 본체**(position semantics, rot6d layout, 곱셈 순서, gripper 의미,
`action_dt_s`, `first_action_offset_s`, RGB preprocessing)는 두 버전이 같다.
그쪽으로 이미 구현했다면 그대로 유효하고, npz 키 이름만 고치면 된다.

---

## 2. 환경 — ROS 컨테이너에 torch 를 넣지 않는다

Jetson 은 PyTorch / CUDA / JetPack 이 서로 묶여 있다. ROS Jazzy (Python 3.12)
컨테이너에 `pip install torch dill` 하면 거의 확실히 뒤에서 꼬인다.
**추론 환경을 따로 만든다.**

```
Jetson
├── ROS Jazzy container          ← 손대지 않는다
│   camera / joint_states / FK / MoveIt / controller
│
└── Policy inference environment ← 이번에 만드는 것
    ├── JetPack 에 맞는 PyTorch
    ├── jetson_inference_source  (소스 스냅샷)
    ├── jetson_handoff           (checkpoint + reference)
    └── predict_action()
```

지금은 두 프로세스를 연결할 필요가 **없다.** 추론 환경에서 `[1,16,10]` 이
나오는 것까지만 하면 된다.

### PyTorch

`pip install torch` 를 쓰지 않는다. NVIDIA 가 배포하는 JetPack 대응 wheel 이나
`nvcr.io/nvidia/l4t-pytorch` / `dustynv/l4t-pytorch` 계열 이미지를 쓴다.
JetPack 버전에 맞는 것을 골라야 한다.

```bash
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

`cuda_available=False` 여도 이번 smoke 는 `--device cpu` 로 통과할 수 있다.
다만 latency 숫자는 의미가 없어진다.

### 나머지 의존성

소스 스냅샷의 `pip_freeze.txt` / `environment.json` 은 **버전 참조용이지
설치 목록이 아니다.** GPU 서버는 x86_64 + CUDA 12.1 이고 Jetson 은 ARM +
JetPack 이라 그대로 설치하면 안 된다.

**GPU 서버에서 python 3.10.12 / CPU 로 실제 재현**해서 확정한 목록이다.
snapshot 안의 `inference_requirements.txt` 가 같은 내용이다.

```bash
# 1) JetPack 대응 PyTorch 를 먼저 설치 (torch, torchvision)
# 2) 그다음
pip install -r inference_requirements.txt
```

| 패키지 | 버전 | 비고 |
|---|---|---|
| `torch` | 2.1.0 또는 2.5.1 | **JetPack 빌드로.** PyPI 에서 받지 않는다 |
| `torchvision` | torch 와 짝 | 0.16.0 / 0.20.1 둘 다 검증 |
| `huggingface_hub` | **`==0.25.2` 고정** | 아래 참고 |
| `numpy` | **`<2`** | torch 2.1.0 이 numpy 1.x ABI 로 빌드됨 |
| `timm` | 0.9.7 | |
| `diffusers` | 0.18.2 | |
| `accelerate` | 0.24.1 | `diffusers` 가 import |
| `einops` | 0.6.1 | |
| `hydra-core` | 1.2.0 | |
| `omegaconf` | 2.2.3 | |
| `dill` | 0.3.7 | checkpoint unpickle |
| `scipy` | — | 회전 변환 |
| `zarr` / `numcodecs` / `boto3` | 2.16.1 / 0.11.0 / — | upstream 이 module-level 로 import |
| `opencv-python` | — | `verify_bundle.py` 의 RGB 항목에만 필요 |

**`huggingface_hub` 를 고정해야 하는 이유** — 그냥 설치하면 최신(1.x)이 들어오고
`diffusers 0.18.2` 가 쓰는 `huggingface_hub.constants.hf_cache_home` 이 없어서
이렇게 죽는다.

```
ImportError: cannot import name 'hf_cache_home' from 'huggingface_hub.constants'
```

**필요 없다고 확인된 것**: `wandb` 와 그 스택(`sentry-sdk`, `GitPython`,
`wandb-*`), 그리고 **`av`**. 없이 돌려서 `ALL SMOKE CHECKS PASSED` 확인했다.
`av` 는 ffmpeg 를 끌고 와서 ARM 에서 특히 아픈데 불필요하다.

> smoke 스크립트는 policy 를 `cfg.policy` 에서 **직접** 만든다. `cfg._target_` 이
> 가리키는 training workspace 클래스를 거치면 그 모듈의 `import wandb` 때문에
> wandb / sentry-sdk / GitPython 이 전부 딸려온다. 직접 로드해도 동일한 네트워크
> 이고, GPU 서버에서 두 경로의 출력이 일치함을 확인했다.

### Python 버전

checkpoint 는 **python 3.9 / dill 0.3.7** 로 pickle 되어 있다. Jetson 의
**python 3.10.12 에서 정상 load 되는 것을 실제로 확인**했다 (`torch.load` OK,
`state_dicts=['ema_model']`, cfg 복원 OK). `dill` 은 `0.3.7` 로 맞추는 것을
권장한다 — 버전 차이가 크면 unpickle 이 깨질 수 있다.

---

## 3. 배치

두 아카이브를 **나란히** 푼다.

```bash
mkdir -p ~/omx_policy && cd ~/omx_policy

sha256sum -c omx_jetson_handoff_0d9d30d_20260922.zip.sha256
sha256sum -c jetson_inference_source_0d9d30d.tar.gz.sha256

unzip omx_jetson_handoff_0d9d30d_20260922.zip     # unzip 없으면:
# python3 -m zipfile -e omx_jetson_handoff_0d9d30d_20260922.zip .
tar xzf jetson_inference_source_0d9d30d.tar.gz
```

```
~/omx_policy/
├── jetson_handoff/            checkpoint.ckpt, reference, INSTALL.md, verify_bundle.py
└── jetson_inference_source/   diffusion_policy/ umi/ omx/ configs/ scripts/
```

두 디렉토리의 내부 체크섬도 확인한다.

```bash
cd jetson_handoff            && sha256sum -c SHA256SUMS && cd ..
cd jetson_inference_source   && sha256sum -c SHA256SUMS && cd ..
```

`SHA256SUMS` 의 **모든 줄**이 `OK` 여야 한다. 줄 수는 번들/스냅샷 버전마다
다르므로 특정 숫자를 기대하지 않는다 — `sha256sum -c` 가 실패를 0 건으로
보고하는지만 본다.

```bash
sha256sum -c SHA256SUMS | grep -cv ': OK'    # 0 이어야 함
```

---

## 4. 순서대로 실행

### 4.1 contract 재현 확인 (torch 불필요)

```bash
cd ~/omx_policy/jetson_handoff
python3 verify_bundle.py
```

`numpy` 만 있으면 된다. GPU repo 를 전혀 import 하지 않고 contract 문서만 보고
decoder 를 새로 구현해 대조한다.

```
ALL BUNDLE CHECKS PASSED
```

여기서 실패하면 전송이 깨진 것이지 환경 문제가 아니다.

### 4.2 checkpoint smoke (torch 필요)

```bash
cd ~/omx_policy/jetson_inference_source
python3 scripts/smoke_predict_action.py --bundle ../jetson_handoff
#   CPU 로만 돌릴 때:
python3 scripts/smoke_predict_action.py --bundle ../jetson_handoff --device cpu
```

### 기대 출력

GPU 서버(V100)에서의 결과다. Jetson 에서는 **latency 와 `vs reference action`
두 줄만 다르고 나머지 PASS 는 모두 같아야 한다** (아래 경고 참고).

```
[1] checkpoint
  PASS  checkpoint file present    685 MB
  PASS  checkpoint load            0.5 s
  PASS  ema_model in state_dicts   state_dicts=['ema_model']
  PASS  ema_model load
  PASS  ema weights applied        obs_encoder.key_model_map.camera0_rgb.patch_

[2] observation
  PASS  all declared keys present  5 keys
        camera0_rgb                            (1, 2, 3, 224, 224)  torch.float32
        robot0_eef_pos                         (1, 2, 3)  torch.float32
        robot0_eef_rot_axis_angle              (1, 2, 6)  torch.float32
        robot0_eef_rot_axis_angle_wrt_start    (1, 2, 6)  torch.float32
        robot0_gripper_width                   (1, 2, 1)  torch.float32

[3] predict_action
  PASS  output shape [1,16,10]     (1, 16, 10)
  PASS  output finite              range [-1.0000, +1.0606]
  info  matches reference_action.npy  max|d| = 0.000e+00  same

[4] decode
  PASS  EE target shape [16,3]     (16, 3)
  PASS  EE target finite           first [0.07865, 0.32149, -0.0508]
  PASS  decoder parity             max|d| = 0.000e+00  (reference action -> decode, deterministic)

[5] latency
        139.3 ms / call  (B=1, 16 denoise steps, cuda:0)

ALL SMOKE CHECKS PASSED
```

### ⚠️ `matches reference_action.npy` 는 Jetson 에서 통과하지 않을 수 있다

정책이 **자기 입력을 무작위화**하고(§5.3) diffusion 샘플링이 난수를 쓰기 때문에,
출력은 **RNG 스트림에 의존**한다. 같은 seed 라도 device 가 다르면 달라진다.
GPU 서버에서 직접 측정한 값:

```
cuda:0  vs reference_action.npy   max|d| = 0.0000
cpu     vs reference_action.npy   max|d| = 1.9963      ← 같은 머신, 같은 seed
```

즉 **이 항목은 "부동소수점 오차" 수준이 아니라 통째로 다른 샘플**이 된다.
그래서 smoke 스크립트는 이 줄을 `PASS/FAIL` 이 아니라 `info` 로만 출력한다 —
값이 커도 `ALL SMOKE CHECKS PASSED` 는 그대로 나온다.

**실제로 봐야 하는 것:**

| 항목 | 기준 |
|---|---|
| `output shape [1,16,10]` | 반드시 PASS |
| `output finite` | 반드시 PASS |
| `EE target shape [16,3]` | 반드시 PASS |
| `decoder parity` | 반드시 PASS — 저장된 reference action 을 디코드하므로 결정적이다 |
| `matches reference_action.npy` | **정보성 출력.** PASS/FAIL 로 세지 않는다 |

`decoder parity` 는 정책이 방금 낸 action 이 아니라 **저장된
`reference_action.npy` 를 디코드**해서 비교한다. 따라서 정책 출력과 무관하게
항상 `0` 이어야 하고, 그쪽이 FAIL 이면 진짜 문제다.

GPU 서버에서 CPU 로 돌린 결과 (Jetson 최악 케이스 모사):

```
info  matches reference_action.npy  max|d| = 1.996e+00  differs (expected on other hardware)
PASS  decoder parity               max|d| = 0.000e+00
ALL SMOKE CHECKS PASSED
```

---

## 5. Jetson 에서 특히 걸리는 것

### 5.1 `pretrained` — 오프라인이면 여기서 죽는다

학습 config 가 `policy.obs_encoder.pretrained: True` 라, policy 를 만들 때
`timm` 이 HuggingFace hub 에서 CLIP 가중치를 받으러 간다. 그런데 checkpoint 가
그 가중치를 **전부 덮어쓴다.** 네트워크 없는 Jetson 에서는 생성 단계에서 그냥
실패한다.

`smoke_predict_action.py` 는 이미 `pretrained=False` 로 강제한다. GPU 서버에서
`--check-pretrained` 로 **결과가 bit 동일**(max|d| = 0)함을 확인했다.

직접 코드를 짜신다면 policy 를 만들기 **전에** 반드시:

```python
cfg.policy.obs_encoder.pretrained = False
```

### 5.2 `ema_model` 을 로드해야 한다

패키지된 checkpoint 에는 `ema_model` 밖에 없다. `model` 을 로드하면 **학습되지
않은 네트워크**를 조용히 얻는다.

```python
policy = workspace.ema_model     # not workspace.model
```

### 5.3 정책이 추론 시 자기 입력을 무작위화한다

`TimmObsEncoder.forward` 가 `RandomCrop(212) + Resize(224) + ColorJitter` 를
`training` 가드 없이 적용하고, torchvision 은 `eval()` 을 보지 않는다. 같은
입력을 두 번 넣으면 출력이 다르다 (~2.0 측정).

→ **정책 출력의 bit 일치를 assert 하지 않는다.** decoder 를 맞춘다.
→ ONNX/TensorRT export 시 이 transform 을 그래프에 넣을지 명시적으로 정한다.

### 5.4 gripper reference 값은 측정값이 아니다

CPU 의 `frames.csv` 에 gripper 컬럼이 아직 없어서 상수 `0.105 m` 로 채워져
있다. `decoder_reference.npz` 의 gripper 축은 **어떤 decoder 를 넣어도 통과**
하므로 검증된 것으로 카운트하면 안 된다. gripper limit / threshold 도 이
reference 에서 뽑지 않는다.

contract 자체(절대 width, meter, delta 아님)는 정확하다.

---

## 6. 실패했을 때

| 증상 | 원인 / 조치 |
|---|---|
| `sha256sum -c` 실패 | 전송 깨짐. 재전송 |
| `AttributeError: 'ParameterDict' object has no attribute 'frames'` | 구 버전 zip. §1 의 해시 확인 |
| hub 접속 시도 후 timeout/실패 | `pretrained=False` 강제 안 됨. §5.1 |
| 출력이 이상하지만 shape 은 맞음 | `model` 을 로드했을 수 있음. §5.2 |
| `dill` unpickle 오류 | `dill==0.3.7` 로 맞춰본다 |
| `ModuleNotFoundError: diffusion_policy` | `jetson_inference_source` 디렉토리에서 실행하거나 `PYTHONPATH` 에 추가 |
| `cv2` 없음 | RGB parity 항목만 skip 된다. 나머지는 진행됨 |
| `torch.cuda.is_available() == False` | `--device cpu` 로 통과 가능. latency 는 무의미 |

---

## 7. 돌려줄 것

```
ALL SMOKE CHECKS PASSED   yes / no
action shape              기대 (1, 16, 10)
action finite             기대 True
decoder parity            기대 0.000e+00      ← 반드시 맞아야 하는 항목
decoded target shape      기대 (16, 3)
inference latency         ms/call, cpu 인지 cuda 인지
vs reference action       출력된 값 그대로 (정보성, 어떤 값이든 무방)
python / torch / torchvision 버전, JetPack 버전
```

FAIL 이 있으면 출력 전체를 보내주세요. 각 항목이 무엇과 무엇을 비교했는지
이름에 들어 있습니다.

---

## 8. Latency — 실제로 쓸 수 있는가

smoke 가 통과해도 latency 가 예산 안에 들어와야 실행에 쓸 수 있다.

### 예산

policy 는 10 Hz 이고 `predict_action()` 은 **항상 16 step 을 전부 돌려준다.**
잘라주지 않는다 — `diffusion_unet_timm_policy.py` 의 `predict_action()` 에는
`n_action_steps` 가 아예 없고, 반환 직전 shape 이 `(B, action_horizon, 10)` 로
assert 된다. 우리 config 에도 그런 키는 없다.

몇 step 을 실행하고 재추론할지는 **robot layer 가 정한다.** upstream 의 실제
로봇 루프 `scripts_real/eval_real_robot.py` 에서는 그게 `--steps_per_inference`
이고 **기본값이 6** 이다.

k step 을 실행하는 동안 다음 추론이 끝나야 하므로:

```
예산 = k × 100 ms
  k=6  ->  600 ms      (upstream eval_real_robot.py 기본값)
  k=8  ->  800 ms
  k=4  ->  400 ms
```

**k 를 정하는 것이 곧 latency 예산을 정하는 일이다.** k 를 키우면 예산은
늘지만 그만큼 오래된 관측으로 움직인다.

### 측정값

| | latency |
|---|---|
| V100 (x86, CUDA) | 139 ms |
| GPU 서버 CPU (x86, py3.10) | 410 ~ 640 ms |
| **Jetson Orin CPU wheel (aarch64)** | **2677 ms** |
| Jetson Orin + JetPack CUDA | 미측정 |

CPU wheel 2677 ms 는 **k=6 예산(600 ms)의 4.5배**다. k 를 26 까지 올려야 맞는데
16 step 밖에 없으므로 불가능하다. JetPack CUDA 빌드가 필요한 이유가 여기 있다.

> V100 에서 Orin 의 CUDA latency 를 추정하지는 않았다. 연산 성능 차가 커서
> 600 ms 를 넘길 수도 있다. **CUDA 빌드 후 다시 재보는 것이 유일한 확인 방법**이다.

### 어디를 줄일 수 있나 (V100 기준 분해)

```
obs_encoder (CLIP ViT-B/16, 2 frames, 1회)      9.7 ms   ( 7%)
UNet denoise 16 step 합계                     129.5 ms   (93%)   step 당 8.1 ms
------------------------------------------------------
전체                                          139.3 ms
```

**93% 가 denoise 루프**이고 step 수에 거의 선형이다.

| `num_inference_steps` | V100 | 전체 대비 |
|---|---|---|
| 16 (현재) | 143.9 ms | 100% |
| 8 | 76.3 ms | 53% |
| 4 | 43.0 ms | 30% |
| 2 | 27.1 ms | 19% |
| 1 | 19.0 ms | 13% |

즉 latency 가 모자라면 순서는:

1. **JetPack CUDA 빌드** — CPU wheel 대비 가장 큰 폭
2. `policy.num_inference_steps` 를 줄인다 — 8 로 하면 거의 절반. DDIM 이라
   적은 step 을 전제로 설계돼 있지만 **출력 분포가 달라지므로** 학습된 policy
   에서 성능을 확인하고 정해야 한다. Stage A checkpoint 로 판단하면 안 된다
3. FP16 / TensorRT — encoder 가 7% 뿐이라 UNet 쪽이 주 대상

> `num_inference_steps` 는 checkpoint 가 아니라 실행 시 설정이다. 바꿔도
> checkpoint 를 다시 만들 필요는 없지만, **manifest 의 `diffusion_steps` 와
> 달라지므로 실제 쓴 값을 기록해야 한다.**

---

## 9. CUDA wheel — Orin GPU 를 실제로 쓰기

smoke 가 통과했더라도 `torch.version.cuda` 가 `None` 이면 **GPU 를 전혀 안 쓰고
있는 것**이다. Orin 의 GPU 는 멀쩡히 있고, PyTorch 가 그걸 쓸 줄 모르는 상태다.

```
torch 2.5.1          설치 성공
torch.version.cuda   None          <- 이 wheel 은 CUDA 없이 빌드됨
cuda.is_available()  False
```

`None` 은 "CUDA 를 못 찾았다" 가 아니라 **"이 빌드에는 CUDA 가 없다"** 는 뜻이다.
에러가 아니다. 고장난 것도 없다. **wheel 출처만 바꾸면 된다.**

### 왜 이렇게 되나

`pip install torch` 는 PyPI 에서 aarch64 용 **CPU 전용** wheel 을 준다.
Jetson 용 CUDA PyTorch 는 **PyPI 에 없다.** Jetson 은 iGPU + unified memory 라
일반 서버 ARM(sbsa) 용 CUDA wheel 도 맞지 않는다. NVIDIA 가 따로 배포한다.

### 어디서 받나

JetPack 6.x / CUDA 12.6 용 index:

```
https://pypi.jetson-ai-lab.io/jp6/cu126
```

> 예전 안내에 나오는 `pypi.jetson-ai-lab.**dev**` 는 **죽었다** (HTTP 410).
> `.io` 를 쓸 것. 2026-09-22 기준 확인.

cp310 으로 올라와 있는 조합 (torch ↔ torchvision 은 **반드시 세트**):

| torch | torchvision |
|---|---|
| 2.8.0 | 0.23.0 |
| 2.9.1 | 0.24.1 |
| 2.10.0 | 0.25.0 |
| 2.11.0 | 0.26.0 |

**어느 것이든 된다.** GPU 서버에서 checkpoint 를 실제로 올려 양 끝단을 확인했다:

| | 결과 |
|---|---|
| torch 2.8.0 + tv 0.23.0 | ALL SMOKE CHECKS PASSED, decoder parity `0.000e+00` |
| torch 2.11.0 + tv 0.26.0 | ALL SMOKE CHECKS PASSED, decoder parity `0.000e+00` |

> torch 2.6 부터 `torch.load` 의 `weights_only` 기본값이 `True` 로 바뀌었지만
> **우리는 안 걸린다.** `pickle_module=dill` 을 명시하면 torch 가
> `weights_only` 를 `False` 로 유지한다 (`_default_to_weights_only()`).
> 확인했고, 스크립트 수정 필요 없다.

### 설치

**지금 돌아가는 CPU venv 는 건드리지 말 것.** 옆에 새로 만든다 — CUDA 쪽이
안 되면 돌아갈 곳이 있어야 한다.

```bash
cd ~/omx_policy
python3 -m venv venv_cuda
source venv_cuda/bin/activate
pip install --upgrade pip

# 1) Jetson CUDA 빌드를 먼저. torch 와 torchvision 은 세트로.
pip install torch==2.8.0 torchvision==0.23.0 \
    --index-url https://pypi.jetson-ai-lab.io/jp6/cu126/+simple

# 2) CUDA 가 진짜 들어왔는지 확인 -- 여기서 안 되면 더 가지 말 것
python -c "
import torch
print('torch        ', torch.__version__)
print('version.cuda ', torch.version.cuda)
print('is_available ', torch.cuda.is_available())
print('device       ', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')
assert torch.version.cuda is not None, 'CPU wheel -- index 를 잘못 썼다'
assert torch.cuda.is_available(),      'CUDA 빌드는 맞는데 device 가 안 보인다'
print('OK')
"

# 3) 나머지 의존성. 이 파일에는 torch 가 없어서 덮어쓰지 않는다.
pip install -r jetson_inference_source/inference_requirements.txt

# 4) torch 가 바뀌지 않았는지 재확인 (transitive 로 갈려나갔을 수 있음)
python -c "import torch;assert torch.version.cuda,'torch 가 CPU 판으로 교체됨';print('still cuda:',torch.version.cuda)"
```

`version.cuda` 는 `12.6`, `device` 는 Orin 계열 이름이 나와야 한다.

### 실행

```bash
cd ~/omx_policy/jetson_inference_source
python scripts/smoke_predict_action.py --bundle ../jetson_handoff --require-cuda
```

**`--require-cuda` 를 반드시 붙일 것.** 이게 없으면 CUDA 가 없을 때 스크립트가
조용히 cpu 로 내려가서 `ALL SMOKE CHECKS PASSED` 를 그대로 찍는다 — 통과한 것
처럼 보이지만 GPU 는 안 쓴 결과다. 이 플래그는 fallback 을 실패로 바꾼다.

출력에 이렇게 나와야 한다:

```
torch    : 2.8.0  cuda=12.6
device   : Orin
...
        <N> ms / call  (B=1, 16 denoise steps, cuda:0)
```

### 안 될 때

* `is_available()` 이 `False` 인데 `version.cuda` 는 채워져 있다
  → 빌드는 맞고 런타임이 안 보이는 것. `nvidia-smi` 또는 `tegrastats` 확인,
    `CUDA_VISIBLE_DEVICES` 가 빈 문자열로 설정돼 있지 않은지 확인.
* `libcusparseLt.so` / `libcudnn.so` 를 못 찾는다
  → JetPack 구성요소 누락. `sudo apt install nvidia-jetpack` 로 채운다.
* index 에서 받아지지 않는다
  → `+simple` 경로가 빠졌는지 확인. 이 index 는 devpi 라
    `https://pypi.jetson-ai-lab.io/jp6/cu126/+simple` 이 pip 용 주소다.
* 그래도 안 되면 CPU venv 로 돌아가면 된다. Stage A 검증은 이미 끝나 있다.

### 돌려줄 것

`--require-cuda` 로 돌린 뒤 **ms / call 한 줄**만 있으면 된다.
`torch.version.cuda` 와 `get_device_name` 도 같이.

---

## 10. 여기까지 되면

```
reference observation → Stage A checkpoint → [1,16,10] → decoded [16,3]
```

이 성공하면 이번 단계는 끝이다. 그다음에야 추론 환경과 ROS 프로세스를 연결하는
설계로 넘어간다.

`live_ready: false` 이므로 **actuator 연결은 아직 하지 않는다.** blocker 3건:

1. `T_camera_EE` 가 placeholder — EE 궤적이 물리적으로 보정되지 않음
2. gripper 가 placeholder — 상수
3. checkpoint 가 task 영상이 아닌 7 segment 로 7 step 학습된 것

---

## 11. 다음 번들이 올 때

Stage B 는 checkpoint 를 바꾸지 contract 를 바꾸지 않는다. 아래는 그대로다.

action semantics · rot6d layout · 곱셈 순서 · gripper 의미 · `action_dt_s` ·
`first_action_offset_s` · RGB preprocessing

바뀌는 것: `checkpoint_sha256`, `live_ready`, gripper 값, EE 궤적,
`rgb_preprocess.effective_hfov_deg`.

절차:

```bash
sha256sum -c *.sha256
python3 verify_bundle.py
diff <(python3 -m json.tool old/model_manifest.json) \
     <(python3 -m json.tool new/model_manifest.json)
```

위 목록의 필드만 움직였으면 checkpoint 교체가 작업의 전부다. 소스 스냅샷도
그때 다시 받는다 (`git_commit.txt` 로 대조).
