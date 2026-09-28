# GPU 서버 정책을 Jetson Orin 에서 돌리기까지

Stage A checkpoint 를 Jetson Orin Nano 에서 실제로 load 하고 `predict_action()`
까지 돌린 과정의 기록. **무슨 일이 있었나 / 어디서 헷갈렸나 / 그래서 알아야
하는 개념** 세 층으로 정리한다.

읽는 순서는 자유. 급하면 [Part 5](#part-5--지금-상태와-다음)만 봐도 된다.

- [Part 1 — 실행 기록](#part-1--실행-기록)
- [Part 2 — 헷갈렸던 것들](#part-2--헷갈렸던-것들)
- [Part 3 — 개념](#part-3--개념)
- [Part 4 — 측정값과 계산](#part-4--측정값과-계산)
- [Part 5 — 지금 상태와 다음](#part-5--지금-상태와-다음)

---

# Part 1 — 실행 기록

## 목표

GPU 서버(V100)에서 학습한 checkpoint 를 Jetson Orin 에서 **실제로 한 번
load 해서 `predict_action()` 까지 돌려본다.** 로봇은 안 붙인다.

확인하려는 건 두 가지다.

1. **계약이 맞는가** — GPU 서버가 낸 숫자를 Jetson 이 같은 의미로 읽는가
2. **돌아가는가** — 환경, 의존성, latency

## 1차: CPU wheel, 2677 ms

Jetson 쪽에서 `pip install torch` 로 환경을 만들고 smoke 를 돌렸다.

```
ALL SMOKE CHECKS PASSED
action shape (1,16,10)
decoder parity 0.000e+00
latency 2676.7 ms/call
torch.version.cuda = None
torch.cuda.is_available() = False
```

**전부 통과했는데 GPU 를 안 썼다.**

## 지적: "jetson 인데 gpu 쓰면 되는 거 아니야?"

맞는 지적. 그리고 **CUDA 설치가 실패한 적은 없었다.** 아무도 시도를 안 했다.

`pip install torch` 는 PyPI 에서 aarch64 용 **CPU 전용** wheel 을 준다.
Jetson 용 CUDA PyTorch 는 PyPI 에 없다 — NVIDIA 가 따로 배포한다. Jetson 은
iGPU + unified memory 라 일반 서버 ARM(sbsa) 용 CUDA wheel 도 안 맞는다.

`torch.version.cuda = None` 은 **"CUDA 를 못 찾았다"가 아니라 "이 빌드에는
CUDA 가 없다"** 는 뜻이다. 에러가 아니다. wheel 출처만 바꾸면 되는 일이었다.

## wheel 찾기 — 흔히 도는 주소가 죽어 있었다

```
https://pypi.jetson-ai-lab.dev/jp6/cu126     HTTP 410 Gone      ← 문서에 많이 나옴
https://pypi.jetson-ai-lab.io/jp6/cu126      HTTP 200           ← 현재 주소
```

devpi 라 pip 주소는 `/+simple` 까지 붙는다.

cp310 으로 올라와 있는 조합 (torch ↔ torchvision 은 **반드시 세트**):

| torch | torchvision |
|---|---|
| 2.8.0 | 0.23.0 |
| 2.9.1 | 0.24.1 |
| 2.10.0 | 0.25.0 |
| 2.11.0 | 0.26.0 |

## 걱정했던 함정: torch 2.6 의 `weights_only`

위 목록이 **전부 2.6 이상**이다. torch 2.6 부터 `torch.load` 의 `weights_only`
기본값이 `True` 로 바뀌었고, 우리는 `pickle_module=dill` 로 임의 객체를 언피클
한다. 충돌할 것처럼 보였다.

**안 걸린다.** torch 내부에서:

```python
def _default_to_weights_only(pickle_module):
    return pickle_module is None and not is_fbcode
```

`pickle_module` 을 명시하면 `weights_only` 가 `False` 로 남는다. 정확히 이런
경우를 위한 가드다.

GPU 서버에서 양 끝단(2.8.0, 2.11.0)에 checkpoint 를 실제로 올려 확인했다.
둘 다 `ALL SMOKE CHECKS PASSED`, `decoder parity 0.000e+00`. 스크립트 수정
불필요.

## `--require-cuda` 추가

smoke 스크립트에 CUDA 가 없으면 조용히 cpu 로 내려가는 fallback 이 있었다.
**CPU wheel 이어도 `ALL SMOKE CHECKS PASSED` 가 그대로 찍힌다** — 정작 확인하려던
게 실패해도 통과처럼 보인다. 1차에서 벌어진 일이 정확히 이거다.

플래그를 추가해 fallback 을 exit 1 로 바꿨다.

```
FAIL  --require-cuda, but torch.cuda.is_available() is False.
      torch.version.cuda = None
      this wheel was built without CUDA. ...
```

## CUDA smoke 성공

```
torch 2.8.0 + torchvision 0.23.0, CUDA 12.6
device Orin
ALL SMOKE CHECKS PASSED
decoder parity 0.000e+00
latency 603.98 ms/call     (재측정 603.97 — 재현성 좋음)
```

## 전력 모드 — 여기서 한 번 틀렸다

"`nvpmodel -m 0` 으로 MAXN 으로 올려라" 고 안내했는데, **그건 AGX Orin 기준**
이다. Orin Nano 는 표가 다르다.

```
0: 15W
1: 25W
2: MAXN_SUPER
```

25W 에서 `-m 0` 을 하면 **15W 로 내려간다.** 실제로 그렇게 됐고, GPU 가
612 MHz 로 떨어졌다. 기기별 모드 표는 반드시 확인하고 쓸 것:

```bash
sudo nvpmodel -p --verbose
```

MAXN_SUPER 로 올린 뒤:

```
GPU  612 MHz → 1020 MHz   (1.67×)
CPU  1497.6  → 1728 MHz   (1.15×)
```

## MAXN 재측정: 616.6 ms — 안 빨라졌다

| 모드 | latency |
|---|---|
| 25W | 603.98 / 603.97 ms |
| MAXN_SUPER + jetson_clocks | 616.6 ms |

2% 차이는 **노이즈다.** 느려진 게 아니라 같은 값이다.

빨라지지 않은 이유: **25W 에서 이미 GPU 가 1020 MHz 였다.** 15W 만 612 MHz 로
제한된다. 즉 **전력 모드로 뽑을 건 이미 다 뽑은 상태**였다.

## tegrastats 분석

추론 구간(15:55:09~15:55:15)만 뽑으면:

```
GR3D_FREQ   26% 75% 99% 99% 98% 74% 99% 86% 99% 93%
CPU core    68% 76% 59% 62% 60% 59% 58% 58% 64% 56%
온도        50~52°C            ← 스로틀링 없음
```

CPU 한 코어가 60% 에서 놀고 GPU 가 99%. **dispatch 병목이 아니다.** CPU 를 더
줘도 안 빨라진다.

RAM:

```
idle      2896 MB / 7620 MB
peak      4387 MB / 7620 MB     ← 추론 프로세스가 약 1,491 MB
종료 후   2897 MB
SWAP      56 MB 고정            ← 스와핑 없음
lfb       46x4MB → 1x4MB → 47x4MB
```

## 결론: `steps_per_inference = 7`

10 Hz 정책이고 `predict_action()` 은 16 step 을 **전부** 돌려준다. 몇 step 을
실행하고 재추론할지(k)는 로봇 층이 정한다.

```
예산 = k × 100 ms

k=6 → 600 ms   →  610 ms   초과 ✗
k=7 → 700 ms   →  610 ms   여유 13% ✓
```

**k=7 로 두면 모델 변경 없이 오늘 들어간다.**

---

# Part 2 — 헷갈렸던 것들

각 항목: *생각했던 것* → *실제* → *왜*

## "CUDA 설치가 자꾸 실패한다"

→ **실패한 적 없다.** 아무도 CUDA 를 설치하려 하지 않았다.
→ `pip install torch` 가 CPU wheel 을 준 것뿐. 설치는 정상이었고 smoke 도
  통과했다. `version.cuda = None` 은 에러가 아니라 빌드 속성이다.

## "600 ms 가 기준이다"

→ **기준이 아니다.** upstream `scripts_real/eval_real_robot.py` 의
  `--steps_per_inference` **기본값이 6** 이라서 나온 숫자다. CLI 플래그다.
→ 예산은 `k × 100 ms` 이고 k 는 우리가 정한다. 다만 k 가 크면 그만큼 **오래된
  관측으로 움직인다** — 공짜가 아니다.

## "GPU 사용률 99% 면 잘 쓰고 있는 것"

→ **아니다.** GR3D 99% 는 "샘플 구간의 99% 동안 GPU 에 실행 중인 커널이
  있었다" 는 뜻이다.
→ CUDA 코어 1024개 중 **1개만** 쓰는 커널이 쉬지 않고 돌아도 100% 로 찍힌다.
  **"논 적이 없다" 이지 "다 썼다" 가 아니다.**
→ 실제로 우리는 하한의 8~10배를 쓰고 있다 ([Part 4](#part-4--측정값과-계산)).

## "`nvpmodel -m 0` 이 MAXN"

→ **AGX Orin 만 그렇다.** Orin Nano 는 0 이 15W 다. 25W 에서 실행하면 오히려
  내려간다.
→ 교훈: 기기별 모드 표를 `nvpmodel -p --verbose` 로 확인하고 쓸 것.

## "lfb 파편화 = coalescing 문제"

→ **완전히 무관하다.** 같은 "메모리" 라는 단어를 쓸 뿐 층이 다르다.

| | lfb 파편화 | coalescing |
|---|---|---|
| 어디 | 리눅스 커널의 물리 페이지 할당자 | warp 32 스레드의 global memory 접근 패턴 |
| 언제 | 프로세스가 malloc / DMA 버퍼 잡을 때 | 커널이 도는 매 순간 |
| 증상 | allocation 실패 | 커널이 느림 |

## "SM 사용률 최적화를 해야 하는 것 아니냐"

→ **직접은 못 한다. 간접적으로는 한다.**
→ 우리가 짠 커널이 하나도 없다. conv 는 cuDNN, matmul 은 cuBLAS, elementwise 는
  PyTorch 것이다. block size / register 배치는 그걸 짠 사람이 정했다.
→ 그런데 **fusion 이 정확히 SM 효율을 올리는 방법**이다. 손잡이를 돌리는 게
  아니라 커널 구조를 바꿔서 올린다.
→ 그리고 원인이 "커널 설정이 나쁘다" 가 아니라 **"batch=1 이라 일이 적다"**
  이다. 설정으로 없는 일을 만들 수는 없다.

## "메모리 병목이면 shared memory 를 쓰면 되지 않나"

→ **재사용이 있을 때만 의미가 있다.**
→ shared memory 는 "한 번 올려서 여러 번 읽는" 구조에서 이긴다. batch=1 은
  weight 원소 하나당 곱셈 한 번이라 **재사용이 1** 이다. 캐싱할 게 없다.
→ 크기도 안 맞는다. Orin Nano 의 온칩 shared memory 는 SM 8개 × 약 100 KB =
  **800 KB**, UNet 가중치는 **342 MB**. 430배 차이.
→ 게다가 cuDNN 은 도움이 되는 shape 에서는 이미 쓰고 있다.
→ **단, 중간 텐서(activation)는 재사용이 있다.** 그걸 메모리에 안 내보내는 게
  fusion 이고, 보통 shared memory 가 아니라 **레지스터**에 머문다.

## "fusion / graphs / fp16 은 다 TensorRT 얘기고, TRT 만 잘 하면 된다"

→ **앞은 맞고 뒤는 틀리다.** TRT 가 셋 다 하는 건 맞다.
→ 그런데 **셋 다 TRT 없이도 된다. 훨씬 싸게.**

```python
policy = policy.half()                                   # fp16
policy = policy.to(memory_format=torch.channels_last)    # 레이아웃
policy.model = torch.compile(policy.model, mode="reduce-overhead")
#                             ^ fusion + CUDA graphs 를 같이
```

→ TRT 는 수일짜리다. 세 줄로 예산에 들어오면 갈 이유가 없다.
→ **"TRT 만 잘 하면 된다" 보다 "TRT 까지 안 가도 될 가능성이 높다"** 가 정확.

## "대역폭이 병목이다"

→ **지금은 아니다.** 가중치 읽기 대역폭 하한이 57 ms 인데 610 ms 가 걸린다.
  대역폭에 막혀 있다면 57 근처에서 놀아야 한다.
→ 지금 시간을 먹는 건 launch 오버헤드와 중간 텐서 왕복이다. 대역폭은 그걸 다
  닫은 **다음에** 벽으로 나타난다.

---

# Part 3 — 개념

## GEMM 과 GEMV — batch=1 이 왜 문제인가

**GEMM** = GEneral Matrix Multiply. `C = A × B`. 신경망 레이어는 거의 다 GEMM 이다.

- linear 레이어 `y = Wx` 는 그대로 GEMM
- conv 도 im2col 또는 implicit GEMM 으로 GEMM 이 된다

핵심은 **한 번 읽은 weight 를 몇 번 쓰느냐** 다.

```
X [N, K] × W [K, M] = Y [N, M]

W 의 원소 하나를  ->  N 개 행이 각각 쓴다   (재사용 N 회)
```

- **batch=64**: weight 한 장 읽어서 64개 샘플에 쓴다. 재사용 64회
- **batch=1**: weight 한 장 읽어서 1번 곱하고 버린다. 재사용 1회 → 이게 **GEMV**
  (행렬 × 벡터)

GEMV 는 **본질적으로 메모리 바운드**다. 읽어온 양에 비해 할 일이 없다.

> **주의**: batch=1 이라고 재사용이 항상 1은 아니다. 시퀀스/공간 차원이 N 역할을
> 한다. 우리 경우:
> - **UNet (conv1d, horizon 16)**: N=16 → 재사용 16회
> - **ViT (patch 196 × 2 frame)**: N=392 → 재사용 392회, 연산 바운드
>
> 그래서 UNet 은 메모리 바운드, 인코더는 연산 바운드다.

## Arithmetic intensity 와 roofline

**Arithmetic intensity (AI)** = 연산량 / 메모리 전송량 [FLOP/byte].
"1 바이트 읽어서 몇 번 계산하냐."

**Ridge point** = 장비의 연산성능 / 대역폭. 이걸 넘으면 연산 바운드, 못 넘으면
메모리 바운드다.

```
Orin Nano Super
  연산  1024 cores × 2 (FMA) × 1.02 GHz  =  2.09 TFLOPS (fp32)
  대역폭                                 ≈  102 GB/s (LPDDR5, CPU 와 공유)
  ridge point = 2090 / 102               ≈  20.5 FLOP/byte
```

우리 UNet: horizon 16 이므로 weight 4 byte 당 2 × 16 = 32 FLOP → **AI ≈ 8**.

**8 < 20.5 → 메모리 바운드.** 다만 압도적으로는 아니다 (2.5배 차이).

fp16 으로 가면 같은 연산에 바이트가 절반이라 **AI 가 2배(≈16)** 로 오른다.
ridge point 에 가까워진다 — fp16 이 대역폭에도 이득인 이유.

## GPU 계층

```
GPU
 └─ SM (Streaming Multiprocessor)          Orin Nano: 8개 (TPC 4 × 2)
     ├─ CUDA core                          SM 당 128개 → 총 1024
     ├─ 텐서 코어                          fp16/int8 행렬 연산 전용
     ├─ 레지스터                           스레드 전용, 제일 빠름
     └─ shared memory / L1                 SM 당 약 128 KB
 └─ L2 캐시                                칩 전체 공유
 └─ HBM / LPDDR                            Jetson 은 CPU 와 공유 (unified)
```

**warp** = 32개 스레드 묶음. GPU 스케줄링의 최소 단위. 한 warp 안의 32 스레드는
같은 명령을 동시에 실행한다.

메모리 속도 차이는 계층마다 자릿수가 다르다:

```
레지스터        ~1 cycle
shared memory   ~20 cycle
L2              ~200 cycle
HBM / LPDDR     ~400-600 cycle     ← 여기 안 가는 게 최적화의 전부
```

## Occupancy

SM 하나에 **동시에 올라가 있는 warp 수 / 최대 warp 수**.

높으면 좋은 이유: 어떤 warp 가 메모리를 기다리는 동안 다른 warp 를 돌려서
지연을 숨긴다(latency hiding).

낮아지는 원인:
- 커널이 레지스터를 많이 씀 → SM 에 올릴 수 있는 warp 수가 줄어듦
- shared memory 를 많이 씀 → 같은 이유
- **일 자체가 적음** ← 우리 경우

앞의 둘은 커널 작성자가 조절한다. **우리 문제는 셋째**라서 설정으로 못 고친다.

> 참고: Orin Nano 는 SM 이 8개뿐이다. V100 은 80개다. **작은 GPU 가 오히려 채우기
> 쉽다** — batch=1 저활용이 큰 GPU 보다 덜 심각하다.

## Coalescing

한 warp 의 32 스레드가 **연속된 주소**를 읽으면 메모리 트랜잭션 하나로 합쳐진다
(coalesced). 흩어진 주소를 읽으면 트랜잭션이 32개로 쪼개진다.

```
coalesced     : thread 0→addr 0,  1→4,  2→8, ...     1 트랜잭션
uncoalesced   : thread 0→addr 0,  1→512, 2→1024, ... 32 트랜잭션
```

**커널 코드의 성질이다.** 우리가 만질 수 있는 유일한 인접 개념은 **텐서 레이아웃**
이다 — NCHW 냐 NHWC 냐. 텐서 코어 conv 는 NHWC 를 원하는데 NCHW 로 들어오면
cuDNN 이 transpose 를 끼워넣거나 느린 알고리즘을 고른다.

```python
policy = policy.to(memory_format=torch.channels_last)
```

coalescing 에 해당하는 레버는 사실상 이 한 줄이 전부다.

## Kernel launch 오버헤드

커널 하나 띄우는 데 CPU 측 준비 + GPU 측 스케줄링으로 수 µs 가 든다.

```
UNet 한 번 = 커널 수백 개
16 step     = 수천 번 launch
```

커널 하나가 10 µs 걸리는데 launch 에 5 µs 가 들면 **33% 가 오버헤드**다.
batch=1 처럼 커널이 작을수록 이 비중이 커진다.

## Fusion — 어느 단에서 어떻게 제공되나

### 무엇을 하는가

```
[fusion 전]
kernel A:  HBM 에서 x 읽기 → conv       → y 를 HBM 에 쓰기
kernel B:  HBM 에서 y 읽기 → bias+GELU  → z 를 HBM 에 쓰기
kernel C:  HBM 에서 z 읽기 → scale      → w 를 HBM 에 쓰기

[fusion 후]
kernel ABC: x 읽기 → conv → bias+GELU → scale → w 쓰기
            (y, z 는 레지스터에만 있고 메모리에 안 나감)
```

**쓰기 2번 + 읽기 2번이 사라진다.**

GELU / bias / scale 같은 elementwise 연산은 **연산량이 거의 0 인데 메모리 트래픽은
100%** 다. 읽고, 더하고, 쓰고. fusion 하면 거의 공짜가 된다.

### 이득의 순서

1. **중간 텐서의 메모리 왕복 제거** ← 제일 큼
2. **launch 수 감소** — 수천 번이 수백 번으로
3. occupancy 개선 ← 제일 작음. grid 크기는 보통 출력 텐서 모양이 정하므로
   fusion 해도 병렬성 자체는 별로 안 는다. 느는 건 스레드당 일의 양

### 어느 단에서 제공되나

```
사용자 코드 (PyTorch)
      │
      ├─► torch.compile / TorchInductor          ◄── ② 그래프 컴파일러
      │      elementwise 체인을 묶어 Triton 커널 생성
      │      Triton 이 block size 를 autotune
      │
   ATen 연산자 디스패치
      │
      ├─► cuDNN / cuBLASLt                       ◄── ① 라이브러리 내장
      │      conv+bias+activation, GEMM epilogue 융합
      │      PyTorch 가 불러줘야 쓰임
      │
   CUDA 커널 (PTX / SASS)
      │
   GPU 하드웨어


  TensorRT                                       ◄── ③ 추론 런타임
      ONNX 그래프를 통째로 받아 자체 fusion +
      레이어별 tactic 을 실제로 측정해 선택 →
      PyTorch 경로를 엔진으로 대체
```

| 단 | 무엇 | 비용 | 우리가 할 일 |
|---|---|---|---|
| ① 라이브러리 | cuDNN/cuBLASLt 내장 융합 | 0 | 이미 일부 적용 중 |
| ② 그래프 컴파일러 | `torch.compile` | 한 줄 | **먼저 시도** |
| ③ 추론 런타임 | TensorRT | 수일 | 마지막 |
| ④ 수동 | 직접 커널 작성 | 수주 | **안 감** |

④ 를 안 가는 이유: 300개 레이어의 occupancy 와 레이아웃을 손으로 맞추는 건
사람이 할 일이 아니다. cuDNN 보다 느린 걸 몇 주 걸려 만들게 된다.

## CUDA graphs

**커널을 하나도 안 바꾼다.** launch 시퀀스를 한 번 녹화해서 재생한다.

```
[일반]    CPU: launch A → launch B → launch C → ...   (매번 CPU 왕복)
[graph]   CPU: replay(graph)                          (한 번)
```

16 step 루프처럼 **매번 똑같은 순서로 도는** 워크로드에 딱 맞는다.
`torch.compile(mode="reduce-overhead")` 가 내부적으로 쓴다.

제약: 그래프 안에 **CPU 동기화나 데이터 의존적 분기가 없어야** 한다. diffusers
스케줄러가 `.item()` 같은 걸 부르면 캡처가 깨진다.

## Autotuning

"SM 을 어떻게 쓸지" 를 사람이 아니라 **도구가 측정해서** 정한다.

- **TensorRT**: 레이어마다 여러 구현(tactic)을 **당신의 GPU 에서 실제로 돌려보고**
  제일 빠른 걸 고른다. Orin Nano 에서 빌드하면 Orin Nano 에 맞춰진다.
  그래서 **엔진은 장비 고유**다 — 다른 GPU 로 못 옮긴다.
- **Triton** (`torch.compile` 뒤): block size 등을 autotune 한다.

## fp16 과 텐서 코어

fp16 이 주는 것은 둘이다.

1. **바이트 절반** → 대역폭 부담 절반, AI 두 배
2. **텐서 코어** → fp32 CUDA 코어보다 행렬 연산이 몇 배 빠름

대신 **수치가 바뀐다.** 정책 품질 검증을 fp16 상태에서 다시 해야 한다.

## Jetson 특수사항

### Unified memory

별도 VRAM 이 없다. CPU 와 GPU 가 **같은 물리 RAM** 을 나눠 쓴다.

- GPU 할당도 시스템 RAM 에서 나온다
- 대역폭도 공유한다 — CPU 가 메모리를 때리면 GPU 대역폭이 줄어든다
- ROS, 카메라 버퍼, 정책이 전부 같은 7.6 GB 안에 들어가야 한다

### lfb (largest free block)

`RAM 4387/7620MB (lfb 1x4MB)` 에서 `lfb` 는 **남은 연속 블록 중 가장 큰 것**과
그 개수다. `1x4MB` = 4 MB 짜리 연속 블록이 1개 남음.

**총 여유 메모리와 다르다.** 총 3.2 GB 가 남아도 연속 덩어리가 없으면 물리적으로
연속이어야 하는 할당(V4L2 DMA 버퍼 등)이 실패한다. "메모리 남았는데 왜
allocation fail?" 의 전형적 원인.

우리 로그에서는 프로세스 종료와 함께 47개로 복구됐다 — 영구 단편화는 아니었다.

### 전력 모드

`nvpmodel` 로 전력 예산을, `jetson_clocks` 로 클럭 고정을 설정한다.

```bash
sudo nvpmodel -p --verbose    # 기기별 모드 표를 반드시 확인
sudo nvpmodel -m <MAXN 번호>
sudo jetson_clocks            # 현재 모드가 허용하는 최대치로 고정
```

- **모드 번호는 기기마다 다르다.** AGX 는 0 이 MAXN, Orin Nano 는 0 이 15W
- `jetson_clocks` 는 **현재 모드 안에서만** 최대로 올린다. 15W 에서 돌리면
  612 MHz 에 고정될 뿐이다
- **`jetson_clocks` 는 재부팅하면 풀린다.** `nvpmodel` 모드는 남는다.
  실제 배포 때 부팅 시 자동 적용을 넣지 않으면 조용히 느려진다

### tegrastats 읽는 법

```
RAM 4387/7620MB (lfb 1x4MB) SWAP 56/3810MB CPU [0%@1728,...] GR3D_FREQ 99% ...
```

| 필드 | 의미 |
|---|---|
| `RAM a/b` | 사용/전체. CPU+GPU 공유 |
| `lfb NxMMB` | 연속 블록 파편화 지표 |
| `SWAP` | 늘어나면 latency 가 무너진다 |
| `CPU [x%@f]` | 코어별 사용률@주파수 |
| `GR3D_FREQ` | **GPU 사용률** (이름과 달리 주파수 아님). "논 적 없다" 지 "다 썼다" 가 아님 |
| `tj@`, `gpu@` | 온도. 스로틀링 판단 |
| `VDD_*` | 순간/평균 전력 |

---

# Part 4 — 측정값과 계산

## 모델 크기

```
obs_encoder (CLIP ViT-B/16)   85,799,424 params   343.2 MB (fp32)
unet (Conditional 1D U-Net)   85,474,186 params   341.9 MB (fp32)
---------------------------------------------------------------
TOTAL                        171,273,772 params   685.1 MB (fp32)
```

## 하한 계산 (Orin Nano Super)

```
장비:  1024 CUDA cores @ 1.02 GHz  =  2.09 TFLOPS (fp32)
       LPDDR5                      ≈  102 GB/s (CPU 와 공유)

16 step 가중치 읽기 총량
  encoder 343 MB × 1  +  unet 342 MB × 16  =  5.81 GB
  → 대역폭 하한  5.81 GB / 102 GB/s        =    57 ms

연산량
  encoder  ViT-B/16 × 2 frame              ≈    35 GFLOP
  unet     2 × 85M × 16 pos × 16 step      ≈    44 GFLOP
  → 연산 하한  79 GFLOP / 2.09 TFLOPS      ≈    38 ms
```

**하한 약 57~70 ms. 실측 610 ms. 갭 8~10배.**

대역폭도 연산도 아니다. 그 갭이 곧 **launch 오버헤드 + 중간 텐서 왕복** 이고,
fusion / CUDA graphs 가 겨냥하는 지점이다.

> V100 에서도 같은 성질이 나온다 — 인코더 이론 2.2 ms 인데 실측 9.7 ms(4.4배).
> **batch=1 diffusion 이 원래 이렇다.** Jetson 탓이 아니다.

## 실측 latency

| 환경 | 16 step | 8 step |
|---|---|---|
| V100 (x86, CUDA, fp32) | 139~144 ms | 76.3 ms |
| GPU 서버 CPU (x86, py3.10, torch 2.8) | 327 ms | — |
| GPU 서버 CPU (torch 2.11) | 336 ms | — |
| **Jetson Orin Nano, CPU wheel** | **2677 ms** | — |
| **Jetson Orin Nano, CUDA 25W** | **604 ms** | **357 ms** |
| Jetson Orin Nano, CUDA MAXN_SUPER | 617 ms | — |

## V100 분해

```
obs_encoder (1회)                9.7 ms   ( 7%)
UNet denoise 16 step 합계      129.5 ms   (93%)   step 당 8.1 ms
-----------------------------------------------
전체                           139.3 ms
```

**93% 가 denoise 루프**이고 step 수에 거의 선형이다.

| `num_inference_steps` | V100 | 전체 대비 |
|---|---|---|
| 16 | 143.9 ms | 100% |
| 8 | 76.3 ms | 53% |
| 4 | 43.0 ms | 30% |
| 2 | 27.1 ms | 19% |
| 1 | 19.0 ms | 13% |

## 예산 산식

```
정책은 10 Hz, predict_action() 은 항상 16 step 을 전부 반환한다 (자르지 않음).
k step 을 실행하고 재추론한다면, 그 k step 이 흐르는 동안 다음 추론이 끝나야 한다.

예산 = k × 100 ms
```

| k | 예산 | 16 step (610 ms) | 8 step (357 ms) |
|---|---|---|---|
| 4 | 400 ms | ✗ | ✓ 여유 11% |
| 6 | 600 ms | ✗ (2% 초과) | ✓ 여유 41% |
| **7** | **700 ms** | **✓ 여유 13%** | ✓ |
| 8 | 800 ms | ✓ 여유 24% | ✓ |

k 를 키우면 예산은 늘지만 그만큼 **오래된 관측으로 움직인다.**

## RAM

```
idle          2896 MB / 7620 MB
peak          4387 MB / 7620 MB      추론 프로세스 약 1,491 MB
남는 여유     3,233 MB
SWAP          56 MB 고정 (스와핑 없음)
lfb           46x4MB → 1x4MB → 47x4MB (종료 후 복구)
```

여기에 **아직 안 올라온 것**: 카메라 파이프라인 버퍼, ROS Jazzy 컨테이너,
나머지 로봇 스택. 전부 같은 7.6 GB 를 나눠 쓴다.

> idle 이 2896 MB 로 높다 — 데스크톱 환경으로 보인다. **헤드리스로 돌리면
> 몇백 MB 회수된다.** 배포 단계에서 가장 값싼 절약.

---

# Part 5 — 지금 상태와 다음

## 확정된 것

- ✅ checkpoint 가 Jetson 에서 load 된다 (py3.9 로 만든 걸 py3.10 에서)
- ✅ `predict_action()` 이 돈다. `(1, 16, 10)`
- ✅ **decoder parity `0.000e+00`** — GPU 서버와 Jetson 이 같은 텐서에서 같은 EE
  좌표를 뽑는다. **계약이 맞는다**
- ✅ CUDA 로 GPU 를 실제로 쓴다 (torch 2.8.0 + cu126)
- ✅ latency 실측: 16 step 610 ms, 8 step 357 ms
- ✅ `steps_per_inference = 7` 이면 예산 안

## 확정 안 된 것

- ❌ **end-to-end 루프 latency** — 610 ms 는 **추론만**이다. 카메라 캡처 +
  JPEG 디코드 + crop/resize + ROS 왕복 + IK 가 안 재졌다. 이게 90 ms 를 넘으면
  k=7 도 모자란다
- ❌ **정책 품질** — 7 step 학습한 더미다. 출력이 무의미하다
- ❌ 실제 카메라 입력 — 저장된 reference observation **1개**로만 돌렸다
- ❌ `T_camera_EE`, gripper 가 placeholder
- ❌ ROS + 카메라를 얹은 상태의 RAM 피크

## 다음 순서

### Jetson 쪽

1. **end-to-end 루프 latency 측정** — 카메라부터 joint 명령까지. `tegrastats`
   같이 띄워서 RAM 피크와 lfb 도 같이 볼 것
2. 그 결과로 k 를 6 으로 할지 7 로 할지 확정

### 최적화 (필요해지면. 지금은 아님)

**지금 하면 안 되는 이유 셋:**

1. 최적화할 대상이 없다 — 학습된 policy 가 나오면 설정이 달라질 수 있다.
   지금 TRT 엔진을 빌드하면 그때 다시 빌드다
2. 추론이 병목인지 모른다 — 카메라+ROS 가 300 ms 면 추론을 반으로 줄여도
   예산은 그대로다
3. fp16 도 TRT 도 출력 숫자를 바꾼다 — 나중에 품질 문제가 생기면 모델 탓인지
   최적화 탓인지 분리가 안 된다

**그때가 오면 순서:**

| 순서 | 방법 | 작업량 | 비고 |
|---|---|---|---|
| 1 | `policy.half()` | 한 줄 | 대역폭 절반 + 텐서 코어 |
| 2 | `to(memory_format=channels_last)` | 한 줄 | 텐서 코어 conv 레이아웃 |
| 3 | `torch.compile(mode="reduce-overhead")` | 한 줄 | fusion + CUDA graphs. **aarch64 에서 triton 이 없거나 깨질 수 있음** |
| 4 | `num_inference_steps` 16→8 | 한 줄 | 357 ms. **출력 분포가 바뀌므로 학습된 policy 로 품질 확인 후** |
| 5 | TensorRT | 수일 | 엔진 2개(encoder, unet). 루프와 스케줄러는 Python 에 남음. ONNX export 리스크 있음 |
| — | 커스텀 CUDA 커널 | 수주 | **안 감** |

> TensorRT 로 갈 때 구조: `predict_action()` 을 통째로 못 감싼다.
> ```python
> scheduler.set_timesteps(16)
> for t in scheduler.timesteps:              # Python 루프, 16회
>     trajectory[condition_mask] = ...
>     model_output = model(trajectory, t, ...)   # ← TRT 엔진 대상
>     trajectory = scheduler.step(...).prev_sample  # diffusers, Python
> ```
> 커널 수백 개 중 대부분이 UNet 안에 있고 그게 16번 도니 효과는 크다.

### GPU 서버 쪽 (Stage B 차단 요소)

Jetson 과 무관하게 막혀 있는 것들:

- 실제 `T_camera_EE` 캘리브레이션 (현재 identity placeholder)
- marker 기반 `gripper_width_m` (현재 상수)
- 실제 카메라 intrinsics (`fx, fy, cx, cy`)
- 목표 태스크 시연 데이터

## 안전 제약 (유지)

- Stage A checkpoint 는 **INTEGRATION ONLY — NOT FOR LIVE TASK EXECUTION**.
  `live_ready: false`. **actuator 연결 금지**
- gripper parity 는 통과해도 세지 말 것 — reference 가 상수 `0.105` 라 어떤
  decoder 를 넣어도 통과한다. gripper limit / threshold 를 여기서 뽑지 말 것
- ROS Jazzy 컨테이너에 `pip install torch` 하지 말 것. 추론 환경은 분리

---

## 부록: 자주 쓰는 명령

```bash
# 전력 / 클럭
sudo nvpmodel -p --verbose        # 기기별 모드 표 (번호는 기기마다 다름!)
sudo nvpmodel -q                  # 현재 모드
sudo nvpmodel -m <MAXN 번호>
sudo jetson_clocks                # 현재 모드 안에서 최대 고정
sudo jetson_clocks --show

# 모니터링
tegrastats --interval 500

# CUDA wheel (JetPack 6.x / CUDA 12.6 / cp310)
pip install torch==2.8.0 torchvision==0.23.0 \
    --index-url https://pypi.jetson-ai-lab.io/jp6/cu126/+simple

# CUDA 가 진짜 들어왔는지 (CPU wheel 이면 여기서 죽는다)
python -c "
import torch
assert torch.version.cuda is not None, 'CPU wheel'
assert torch.cuda.is_available(),      'device 안 보임'
print(torch.version.cuda, torch.cuda.get_device_name(0))"

# smoke — --require-cuda 없으면 CPU 로 조용히 내려가서 통과한다
python scripts/smoke_predict_action.py --bundle ../jetson_handoff --require-cuda
```

## 관련 문서

- `README_JETSON_SETUP.md` — 전체 설치 절차 (§9 CUDA wheel)
- `README_JETSON_HANDOFF.md` — 번들 구조와 계약
- `README_HANDOFF_CONTRACT.md` — CPU↔GPU 데이터 계약
- `REPORT_STAGE_A_INTEGRATION.md` — Stage A 학습/검증 기록
