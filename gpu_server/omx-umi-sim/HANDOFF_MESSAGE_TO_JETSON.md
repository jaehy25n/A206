# (Jetson 담당자에게 보낼 메시지)

아래 `---` 사이를 그대로 복사해서 전달하면 됩니다.

---

**GPU → Jetson: Stage A checkpoint smoke 요청**

파일 4개 보냈습니다. 먼저 해시부터 확인해주세요 — 오늘 같은 이름으로 여러 번
만들어져서 이전 버전이 섞였을 수 있습니다.

```bash
sha256sum -c omx_jetson_handoff_0d9d30d_20260922.zip.sha256
sha256sum -c jetson_inference_source_0d9d30d.tar.gz.sha256
```

```
9204efd33e0ea3b1ebc0cc79ca727a2d51dd3aa716fa6a2ec567f61b0f822269  omx_jetson_handoff_0d9d30d_20260922.zip
e8784e10406bc0ab43b10fbc49522e331b276254ae18a0b264b9e77c6cb6ac1b  jetson_inference_source_0d9d30d.tar.gz
```

> tar.gz 의 해시는 **동봉된 `.sha256` 파일을 기준**으로 하세요. tar 안의
> `README_JETSON_SETUP.md` 에는 일부러 적지 않았습니다 — 그 문서가 tar 안에
> 들어가므로 거기 적힌 값은 구조적으로 한 세대 전 값이 됩니다.

zip 해시가 `72228e33…` 이면 구버전입니다. 폐기하고 다시 받으세요.
(contract 자체는 같으니 이미 구현한 건 유효하고, npz 키 이름만
`obs_frames` → `frame_index_obs`, `action_frames` → `frame_index_action` 으로
고치면 됩니다.)

**전체 절차는 `README_JETSON_SETUP.md` 에 있습니다.** tar.gz 안에도 들어 있고,
따로 파일로도 보냈으니 아카이브 풀기 전에 이것부터 보셔도 됩니다.

**ROS Jazzy 컨테이너에 `pip install torch` 하지 마세요.** 추론 환경을 따로
만들고, PyTorch 는 JetPack 대응 빌드를 쓰세요.

```bash
mkdir -p ~/omx_policy && cd ~/omx_policy
python3 -m zipfile -e omx_jetson_handoff_0d9d30d_20260922.zip .   # 또는 unzip
tar xzf jetson_inference_source_0d9d30d.tar.gz

# 각 디렉토리 안의 SHA256SUMS 도 확인 — 모든 줄이 OK 여야 합니다
cd jetson_handoff          && sha256sum -c SHA256SUMS | grep -cv ': OK' && cd ..
cd jetson_inference_source && sha256sum -c SHA256SUMS | grep -cv ': OK' && cd ..
#   둘 다 0 이 나와야 합니다

# 1) contract 재현 — numpy 만 있으면 됨
cd ~/omx_policy/jetson_handoff && python3 verify_bundle.py

# 2) checkpoint smoke — torch 필요
cd ~/omx_policy/jetson_inference_source
python3 scripts/smoke_predict_action.py --bundle ../jetson_handoff
#   CUDA 안 잡히면: --device cpu
```

`ALL SMOKE CHECKS PASSED` 두 번 나오면 끝입니다.

**의존성** — snapshot 안의 `inference_requirements.txt` 를 쓰세요. GPU 서버에서
**python 3.10.12 / CPU 로 실제 재현해 확정**한 목록입니다.

```bash
# 1) JetPack 대응 PyTorch(torch, torchvision) 를 먼저 설치
# 2) 그다음
pip install -r inference_requirements.txt
```

두 개는 **반드시 고정**해야 합니다. 안 그러면 이렇게 죽습니다:

* `huggingface_hub==0.25.2` — 최신(1.x)이 들어오면
  `ImportError: cannot import name 'hf_cache_home' from 'huggingface_hub.constants'`
* `numpy<2` — torch 2.1.0 이 numpy 1.x ABI 로 빌드됨

**`wandb` 와 `av` 는 안 깔아도 됩니다** — 없이 돌려서 통과 확인했습니다.
`av` 는 ffmpeg 를 끌고 와서 ARM 에서 특히 아픈데 불필요합니다.

**헷갈릴 만한 것 3가지**

1. `vs reference action` 이 크게 나와도(예: `1.996`) **정상**입니다. 정책이
   추론 시 자기 입력을 무작위화해서 출력이 device RNG 에 의존합니다. 같은
   머신에서 cpu↔cuda 만 바꿔도 그만큼 차이납니다. 그래서 `info` 로만 찍히고
   실패로 세지 않습니다. **`decoder parity` 가 `0.000e+00` 인지**만 보세요.
2. `pretrained` 때문에 오프라인에서 HF hub 를 받으러 가다 죽을 수 있습니다.
   smoke 스크립트는 이미 막아뒀는데, 직접 코드 짜시면 policy 만들기 **전에**
   `cfg.policy.obs_encoder.pretrained = False`.
3. checkpoint 에 `ema_model` 만 들어있습니다. **`model` 을 로드하면 학습 안 된
   네트워크**를 조용히 얻습니다.

**아직 하지 마세요:** `live_ready: false` 입니다. actuator 연결 금지.
Stage A checkpoint 는 load / shape / latency / parity 확인용이고,
`T_camera_EE` 와 gripper 가 placeholder, 학습도 7 step 뿐입니다.

**gripper parity 는 통과해도 세지 마세요.** reference 값이 상수 `0.105` 라
어떤 decoder 를 넣어도 통과합니다. gripper limit / threshold 도 여기서 뽑지
마세요.

**돌려주실 것**: `ALL SMOKE CHECKS PASSED` 여부, `action shape`,
`decoder parity` 값, latency, 그리고 torch / JetPack 버전.

자세한 건 zip 안의 `INSTALL.md` 에 있습니다.

### GPU 서버 기준 결과 (비교용)

| | cuda:0 (V100) | cpu |
|---|---|---|
| action shape | `(1,16,10)` | `(1,16,10)` |
| decoder parity | `0.000e+00` | `0.000e+00` |
| vs reference action | `0.000e+00` | `1.996` |
| latency | 139.3 ms | 433 ms (py3.10) |

**torch 버전은 2.1.0 이 아니어도 됩니다.** JetPack 6.2 계열을 상정해
`torch 2.5.1 + torchvision 0.20.1` 로도 돌려서 `ALL SMOKE CHECKS PASSED`
(410 ms) 확인했습니다. py3.9 로 만든 checkpoint 가 py3.10.12 에서 정상
load 되는 것도 확인했습니다. `dill` 만 `0.3.7` 로 맞춰주세요.

---
