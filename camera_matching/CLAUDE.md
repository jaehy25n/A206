# S10 ↔ LUAZ 카메라 매칭

Galaxy S10과 LUAZ WC1080 웹캠의 영상을 서로 비교 가능하게 만드는 프로젝트.
최종 실사용 카메라는 **LUAZ**다.

---

## 1. 목표

두 카메라의 차이를 측정하고 보정한다. 차이는 두 종류로 나뉜다.

| 구분 | 내용 | 기준 카메라 |
|---|---|---|
| Geometry | FOV, K, 렌즈 왜곡 | LUAZ |
| Appearance | 밝기, WB, 색, 감마, 선명도 | S10 |

즉 S10의 geometry를 LUAZ에 맞추고, LUAZ의 appearance를 S10에 맞추는 방향이다.

---

## 2. 환경

- **해상도: 양쪽 모두 1920×1080, 16:9. S10은 camera 0(후면 메인), LUAZ는 camera 0**
- Python 3.11.9, JupyterLab
- numpy, opencv-python, matplotlib, scipy, scikit-image, pandas
- LUAZ: USB 직결, 실시간 캡처 가능
- S10: 실시간 제어 불가. **촬영 후 파일 전달** 방식
  - 향후 로컬 웹서버 + 브라우저 업로드 방식 고려 중

---

## 3. 카메라 모델 (확정)

투영은 네 단계다. 이 순서를 코드 주석과 변수명에 일관되게 쓴다.

```
X_w  --[R|t]-->  X_c  --/Z_c-->  (x,y)  --distort(D)-->  (x',y')  --K-->  (u,v)
     외부 6개           미지수 0        왜곡 4개                  내부 4개
```

- `K` = 3x3 행렬, 성분은 `fx, fy, cx, cy`
- `D` = 길이 4~5 벡터 `(k1, k2, p1, p2[, k3])`. **행렬이 아니라 다항식 계수**
- `R, t` = 사진마다 다름. K, D를 추정하기 위한 동반 미지수이며 **재사용하지 않는다**
- 카메라 하나를 기술하려면 항상 `(K, D)` 쌍이 필요하다. K 단독으로는 부족

### 핵심 변환식

한 카메라의 픽셀을 다른 카메라 규격으로 옮기는 정방향 흐름:

```
p_src --[K_src^-1]--> (x_d, y_d) --[D_src^-1]--> (x, y) --[K_target]--> p_target
```

- `K^-1` : 픽셀 → 왜곡된 정규 좌표
- `D^-1` : 왜곡 제거 (`cv2.undistortPoints`, 반복 수치해)
- 가운데 `(x, y)`는 **단위 없는 방향**. 두 카메라가 공유하는 공통 언어
- `D_target = 0`인 경우 마지막에 distort 단계가 없다

> 구현은 `cv2.initUndistortRectifyMap` + `cv2.remap`을 쓴다.
> 내부적으로는 목적지→원본 역방향으로 계산하지만 그건 라이브러리가 처리한다.
> 코드에서 직접 다룰 일은 없으므로 설명이나 변수명에 역방향 개념을 끌어들이지 말 것.

---

## 4. 측정된 값

**2회차 재측정 전. 아래는 1회차 참고값이며 `result.md`에 옮기지 않는다.**
정본은 `legacy/docs/result.md`.

### LUAZ WC1080 (1회차)

```json
{
  "camera": "LUAZ_WC1080",
  "resolution": [1920, 1080],
  "fx": 1527,
  "fy": 1520,
  "cx": 960,
  "cy": 540,
  "hfov": 64.3,
  "vfov": 38.9,
  "rms": 0.36
}
```

### S10

- 2회차에서 웹앱으로 처음부터 촬영. 16:9만 사용 (4:3 폐기)

### FOV 정의 (확정)

두 이름만 쓴다. 다른 이름의 FOV 함수를 만들지 않는다.

- `fov_nominal` — `K`와 W, H만으로. `2·atan(W/2fx)`, `2·atan(H/2fy)`
- `fov_effective` — `getOptimalNewCameraMatrix(alpha=0)`의 `K'`로 다시 계산

1회차에서 64.3°와 61.0°가 같은 데이터에서 나온 원인이 이 구분 없음이었다.

---

## 5. 미정 사항 — 임의로 정하지 말 것

### 결정 A/B: target 공간을 무엇으로 할 것인가

| | 설계 A: 가상 카메라 | 설계 B: LUAZ 원본 |
|---|---|---|
| `K_target` | `K_LUAZ` 유도값 | `K_LUAZ` |
| `D_target` | **0** | **`D_LUAZ`** |
| LUAZ 영상 | 왜곡 보정됨, 크롭 발생 | **손대지 않음** |
| S10 경로 | `K^-1 → D_s10^-1 → K_target` | `K^-1 → D_s10^-1 → D_luaz → K_luaz` |
| 공통 공간 | 직선이 직선 | 왜곡이 남음 |

**`K_target = K_LUAZ`로 두는 것만으로는 B가 되지 않는다.** `D_target`이 0이면 여전히 A다.

일반적인 canonical normalization 관점에서는 A가 더 깔끔하다. 공통 공간에 왜곡이 없어
이후 처리가 단순하고, 새 카메라가 합류하기도 쉽다. B의 장점은 LUAZ 영상을 전혀
건드리지 않는다는 것이다.

현재는 확정 아님. 이 결정이 필요한 코드를 작성할 때는 **멈추고 물어볼 것.**
양쪽 다 지원하는 구조로 짜는 것도 허용.

### 판정은 두 단계로 나뉜다

| 질문 | 판정 수단 |
|---|---|
| 기하학적으로 **가능한가** | 캘리브레이션 결과로 판정 가능 |
| 실제로 **좋은 선택인가** | 영상·모델 실험 필요 |

캘리브레이션은 앞의 질문까지만 답한다. 뒤의 질문은 resampling degradation이
모델 성능에 얼마나 영향을 주는지의 문제이므로 실험해야 한다.

### 필수 선행 조건

```
LUAZ FOV  ⊆  S10 usable FOV
```

LUAZ가 S10보다 넓으면 S10에 없는 영역을 요구하게 되므로 **불가능하다.**
아무리 정확한 캘리브레이션도 없는 픽셀을 만들지 못한다.
반대로 LUAZ가 좁으면 S10을 crop해서 맞출 수 있어 안전하다.

현재 LUAZ는 HFOV 64.3°, VFOV 38.9°. S10 메인은 이보다 넓을 것으로 예상되지만
`grid169` 역산으로 **반드시 확인한다.**

### 뽑아야 하는 세 지표

S10을 LUAZ target으로 remap한 뒤 측정한다.

1. **FOV overlap** — 두 화각의 포함 관계와 여유분
2. **valid pixel ratio** — 검은 영역 없이 유효한 픽셀 비율
3. **local scale / stretch** — 위치별 국소 배율. 가장자리 과도 확대 확인

판정 예시:

```
합격:   valid 99%,  stretch 작음,  black border 거의 없음
불합격: valid 82%,  가장자리 심한 확대,  큰 black border
```

보조 지표로 calibration RMS와 distortion magnitude를 함께 본다.
다만 **RMS가 낮다고 LUAZ가 좋은 canonical이라는 뜻은 아니다.**
RMS는 `K, D` 추정이 잘 맞았다는 뜻일 뿐, target 적합성과 무관하다.

또한 LUAZ 가장자리 왜곡이 크다면, B를 택할 경우 S10에 그 왜곡을 일부러
만들어 넣어야 한다. 공통 공간으로서는 좋은 기준이 아닐 수 있다.

### B를 택할 때의 실질적 이점

```
Training:   S10 → LUAZ space → model
Inference:  LUAZ → model
```

배포 시 실제 영상을 변환하지 않아도 된다. 운영 경로에 remap 단계가 없다는 것은
지연과 화질 양쪽에서 이점이다. 대신 S10 학습 데이터가 리샘플링을 겪는다.

### 최종 판정 순서

1. S10 calibration 완료 → `K, D` 확보
2. FOV 포함 관계 확인 (불통과면 B 폐기, A도 `f_target` 상향 필요)
3. 세 지표 측정
4. 통과 시 S10→LUAZ 변환 영상의 SSIM / edge / MTF 비교
5. 필요하면 모델 성능까지 보고 결정

### 기타 미정

- 어떤 보정까지 실제로 필요한지 (프로젝트 측에서 "calibration 불필요" 의견이 나온 상태)
- 색 보정 방식 (matrix vs LUT)
- sharpness matching 방법

---

## 6. 작업 규칙

### 측정 관련

- **선명도·해상력은 remap 전 원본에서 측정한다.** remap의 보간이 리샘플링된 쪽을
  뭉개므로, 정렬된 영상으로 비교하면 결과가 왜곡된다
- 색·밝기·감마·WB는 remap 후 정렬된 영상에서 패치 대응으로 측정
- 평면 차트(체커보드, Grid, ColorChecker)는 homography로 정렬되지만
  **3D 장면은 parallax 때문에 정렬되지 않는다.** 물리적으로 같은 삼각대 위치에서
  카메라만 교체해 촬영하는 것이 전제

### 캘리브레이션 품질 기준

- RMS 0.1~0.3 px: 정상 / 0.3~0.6: 설명 안 되는 요인 있음 / 1.0 이상: 구조적 문제
- **RMS만 보지 말 것.** 다음 세 가지를 함께 확인하는 코드를 포함한다
  1. 오차의 공간 분포 (격자별 평균)
  2. 잔차 벡터의 방향성 (무작위여야 정상)
  3. 파라미터 안정성 (사진 부분집합으로 반복 실행 시 fx 변동)
- 홀드아웃 검증: 25~30장 찍어 20장으로 추정, 나머지로 검증.
  검증용 사진의 R, t는 `solvePnP`로 구한다 (K, D는 고정)

### K 값 상식 확인

- `fx` vs `fy`: 1% 이내
- `cx` ≈ 960 ± 50, `cy` ≈ 540 ± 50
- `k1`: 광각이면 음수 (배럴)

이 범위를 벗어나면 경고를 출력한다.

### 촬영 조건

S10은 다음을 반드시 고정: 카메라 모듈, 해상도, aspect ratio, digital zoom,
focus, WB, exposure, stabilization/crop.

---

## 7. 코드 규약

### 디렉토리

README.md의 폴더 구조가 정본. 요약:

```
config/board.yaml, cameras.yaml
src/camcal/            공통 패키지
src/capture_luaz.py    LUAZ 촬영
src/s10_server/        S10 웹앱
src/run_calibrate.py, run_fov_compare.py
data/<camera>/<session_id>/frames/*.png + meta.json
results/<camera>_intrinsics.json, reports/
legacy/                읽기 전용. import 금지
```

### 산출물 포맷

intrinsic JSON은 4절의 LUAZ 예시 스키마를 따른다.
`dist` 필드로 D를 추가하고, 촬영 조건과 날짜를 함께 기록한다.

### 스타일

- 매직 넘버 금지. 체커보드 규격(`square_mm`, 코너 수)은 설정으로 분리
- 좌표계 변수명은 3절의 이름을 그대로 쓴다 (`X_w`, `X_c`, `x_n`, `u`, `v`)
- 왜곡 관련 함수명에 방향을 명시한다 (`undistort_points`, `apply_distortion`)
- 새 의존성 추가 전에 확인할 것
- 세션 프레임은 PNG 무손실. 해상도는 `exact`로 요청하고 실패 시 예외

### 검수

작업이 끝나면 `docs/REVIEW_PROTOCOL.md`의 수집·반박 절차를 거친다.
지적은 재현 시나리오가 있어야 하고, 반박의 기본 판정은 기각이다.

---

## 8. 현재 상태

### 완료

- 1회차 산출물 `legacy/`로 이관
- 카메라 모델 이론 정리 (`docs/calibration_theory.pdf`)
- 해상도·카메라·FOV 정의 확정
- 단계별 위임 프롬프트 (`prompts/PROMPTS.md`)

### 다음 (prompts/PROMPTS.md 단계 순서)

1. 공통 패키지 + LUAZ 촬영 도구
2. S10 웹앱 (원격 제어, 자동 촬영, 실시간 검출)
3. 캘리브레이션 + 품질 리포트 → 양쪽 `(K, D)`
4. FOV 비교 → `LUAZ ⊆ S10` 게이트 → 판정 지표 → 설계 A/B 결정
5. 변환 프로그램 (다음 회차)
