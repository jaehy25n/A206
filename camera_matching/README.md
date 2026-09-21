# S10 ↔ LUAZ 카메라 매칭 (2회차)

Galaxy S10과 LUAZ WC1080 웹캠의 기하 특성을 측정하고, S10 영상을 LUAZ 기준으로
변환하는 파이프라인을 만든다. 최종 실사용 카메라는 **LUAZ**다.

1회차 산출물은 `legacy/`에 있다. 읽기 전용, 참조만 한다. 수치는 재측정 전까지 옮기지 않는다.

---

## 목표

```
S10 픽셀 → K_s10⁻¹ → D_s10⁻¹ → (x, y) → K_target → target 픽셀
```

이 변환 하나를 만들기 위해 필요한 것:

1. LUAZ의 `(K, D)` — 노트북 직결로 캘리브레이션
2. S10의 `(K, D)` — 노트북이 띄운 웹앱으로 원격 촬영 후 캘리브레이션
3. 두 카메라 FOV 비교 → target 공간 결정 (아래 "미정 결정")
4. 변환 프로그램

샤프니스·톤·컬러 매칭은 이 다음 단계다. 이번 회차 범위 밖.

---

## 확정 사항

| 항목 | 값 |
|---|---|
| 해상도 | 양쪽 모두 1920×1080, 16:9 |
| S10 카메라 | camera 0 (후면 메인). 브라우저에서 `deviceId`로 고정 |
| LUAZ 카메라 | camera 0, USB 직결, OpenCV `VideoCapture` |
| S10 고정 항목 | 해상도, aspect ratio, digital zoom 1.0, EIS off, focus, WB, exposure |
| 체커보드 | `config/board.yaml`에 규격. **`square_mm`는 자로 실측한 값** |
| 촬영 장수 | 카메라당 25~30장. 20장 추정, 나머지 홀드아웃 |
| FOV 정의 | 아래 한 가지만 사용 |

### FOV 정의 (통일)

두 종류를 이름으로 구분한다. 코드와 문서에서 섞어 쓰지 않는다.

- `fov_nominal` — `K`와 이미지 크기만으로 계산. 왜곡 무시
  ```
  HFOV = 2·atan(W / 2fx),   VFOV = 2·atan(H / 2fy)
  ```
- `fov_effective` — 왜곡을 편 뒤 `alpha=0`으로 크롭한 유효 화각.
  `getOptimalNewCameraMatrix`가 준 `K'`로 위 식을 다시 계산

1회차에서 같은 데이터로 64.3°와 61.0°가 따로 나온 원인이 이 구분 없음이었다.

---

## 미정 결정 — 코드가 임의로 정하지 않는다

target 공간을 무엇으로 할지는 **양쪽 `(K, D)`가 나온 뒤 데이터로 판정**한다.

| | ② LUAZ 원본 = target | ③ 가상 카메라 = target |
|---|---|---|
| `K_target` | `K_luaz` | `K_luaz` 유도값 (alpha=0) |
| `D_target` | **`D_luaz`** | **0** |
| S10 경로 | `K⁻¹ → D_s10⁻¹ → D_luaz → K_luaz` | `K⁻¹ → D_s10⁻¹ → K_target` |
| LUAZ 경로 | 그대로 | `K⁻¹ → D_luaz⁻¹ → K_target` |
| 배포 시 | 변환 없음 | LUAZ도 매 프레임 변환 |

`K_target = K_luaz`라고 해서 ②가 되는 것이 아니다. `D_target`이 0이면 ③이다.

### 판정 절차

1. **게이트**: `LUAZ fov ⊆ S10 usable fov` 인가. 아니면 ②는 불가능, ③도 `f_target` 상향 필요
2. S10→target remap 후 세 지표: **FOV overlap, valid pixel ratio, local stretch**
3. 통과 시 변환 영상의 SSIM / edge / MTF 비교
4. 필요하면 모델 성능까지

RMS가 낮다고 좋은 target이라는 뜻은 아니다. RMS는 `(K, D)` 추정 품질이고 target 적합성과 무관하다.

---

## 폴더 구조

```
second/
├── README.md               이 문서. 목표·구조·원칙
├── CLAUDE.md               Claude Code용 컨텍스트 (README의 요약 + 작업 규칙)
├── action.md               런북. 촬영·실행 절차를 순서대로
├── result.md               측정 기록. 수치와 decision log
├── config/
│   ├── board.yaml          체커보드 규격 (실측값)
│   └── cameras.yaml        카메라별 캡처 설정
├── src/
│   ├── camcal/             공통 패키지 (board, session, detect, calibrate, report, fov, remap_metrics)
│   ├── capture_luaz.py     LUAZ 촬영 도구
│   ├── s10_server/         S10 웹앱 서버 + 폰/노트북 페이지
│   ├── preflight_jitter.py EIS 확인용 (정지 보드 흔들림 측정)
│   ├── path_check.py       웹앱 vs 기본 앱 촬영 경로 동일성 확인
│   ├── run_calibrate.py    세션 → (K, D) + 품질 리포트
│   ├── run_fov_compare.py  두 카메라 비교 → ②/③ 판정 지표
│   └── run_remap.py        영상을 공통 target 공간으로 변환 (5단계)
├── tests/
├── data/<camera>/<session_id>/   frames/*.png + meta.json
├── results/                <camera>_intrinsics.json, target_space.json, reports/
├── docs/
│   ├── calibration_theory.pdf
│   └── REVIEW_PROTOCOL.md  코드 검수 방식
├── prompts/                Claude Code 위임 프롬프트 원본
└── legacy/                 1회차. 읽기 전용
```

### 문서 역할

- **README** — 왜, 무엇을. 바뀌면 프로젝트 방향이 바뀐 것
- **CLAUDE.md** — 에이전트가 매 세션 읽는 규칙. README와 충돌하면 README가 우선
- **action.md** — 어떻게. 사람이 따라 하는 절차
- **result.md** — 나온 숫자와 결정. 날짜 있는 항목만 유효

---

## 환경

- Python 3.11.9
- numpy, opencv-python, matplotlib, scipy, scikit-image, pandas, pyyaml, pytest
- S10 서버: fastapi, uvicorn (HTTPS, 자체 서명 인증서)
- 새 의존성은 `requirements.txt`에 추가하고 이유를 커밋 메시지에 남긴다

---

## 원칙

**조용히 실패하는 것들을 시끄럽게 만든다.**

- 해상도는 `exact`로 요청한다. 안 되면 실패해야 하고, 적당히 다른 해상도로 넘어가면 안 된다
- 촬영 중 매 프레임 코너 검출 결과를 즉시 표시한다
- `K` 값이 상식 범위(`fx≈fy`, `cx≈960±50`, `cy≈540±50`, 광각이면 `k1<0`)를 벗어나면 경고
- RMS 하나로 판단하지 않는다. 공간 분포·잔차 방향·파라미터 안정성·홀드아웃을 함께 본다
- 세션 메타데이터에 **실제 적용된** 캡처 설정(`track.getSettings()`)을 기록한다

**캘리브레이션 경로 = 데이터 수집 경로.**
같은 camera 0이어도 앱마다 crop이 달라 `K`가 달라질 수 있다. 첫 세션에 `path_check.py`로 확인한다.

**선명도는 remap 전 원본에서 잰다.** 리샘플링된 쪽이 보간으로 뭉개진다.

**평면 차트는 homography로 정렬되지만 3D 장면은 시차 때문에 안 된다.**
같은 삼각대 위치에서 카메라만 교체한다.

---

## 코드 검수

AI 리뷰는 지적을 끝없이 낸다. 그래서 리뷰 자체를 검증 대상으로 삼는다.
방식은 `docs/REVIEW_PROTOCOL.md`. 요지:

1. 검수 축을 나눠 병렬로 지적을 모은다
2. 지적마다 반박 에이전트를 붙인다. **기본 판정은 기각**
3. 컴파일러·테스트가 이미 잡은 것, 재현 시나리오가 없는 것은 올리지 않는다
4. 되돌리기 어려운 변경은 영향 범위 조사가 먼저다. 결론이 "바꾸지 않음"일 수 있다
5. 위임 프롬프트에 적용할 규칙을 직접 적는다. 링크만 두면 읽히지 않는다

---

## 진행 단계

| # | 단계 | 산출물 | 게이트 |
|---|---|---|---|
| 0 | 보드 실측, 촬영 조건 확정 | `config/board.yaml` | — |
| 1 | 공통 패키지 + LUAZ 촬영 도구 | `camcal/`, `capture_luaz.py` | 테스트 통과, 실촬영 1세션 |
| 2 | S10 웹앱 | `s10_server/` | 폰에서 1920×1080 확인, 원격 촬영 동작 |
| 3 | 캘리브레이션 + 리포트 | `run_calibrate.py`, `*_intrinsics.json` | 양쪽 RMS < 0.5, 홀드아웃 근접 |
| 4 | FOV 비교 + 판정 지표 | `run_fov_compare.py`, 리포트 | ②/③ 결정 |
| 5 | 변환 프로그램 | `run_remap.py`, `results/target_space.json` | 육안 확인 |

각 단계는 `prompts/`의 해당 프롬프트로 위임하고, 끝나면 `docs/REVIEW_PROTOCOL.md`로 검수한다.

**실행할 파일과 순서는 [action.md](action.md)의 "실행 순서 한눈에" 표가 정본이다.**
직접 실행하는 파일은 `src/` 바로 아래 7개뿐이다: `capture_luaz.py`, `run_s10_server.py`,
`preflight_jitter.py`, `path_check.py`, `run_calibrate.py`, `run_fov_compare.py`, `run_remap.py`.
`src/camcal/`과 `src/s10_server/`는 이들이 불러 쓰는 패키지라 직접 실행하지 않는다.
