# action.md — 실행 절차 (런북)

"무엇을 어떤 순서로 실행하는가"만 다룹니다.
측정 결과와 결정 사항은 [result.md](result.md) 에 쌓고, 도구 설명은 [README.md](README.md) 에 둡니다.

> 2026-09-18 초기화. **`legacy/` 는 참조하지 않는다** (1회차 데이터는 잘못된 데이터로 판정).
> 현재 1~5단계(LUAZ 촬영 · S10 웹앱 · 캘리브레이션 · target 공간 비교 · 변환)까지 적혀 있습니다.

---

## 실행 순서 한눈에

**직접 실행하는 파일은 `src/` 바로 아래 7개뿐이다.** 나머지(`src/camcal/`, `src/s10_server/`)는
이들이 불러 쓰는 패키지라 직접 실행하지 않는다. 표의 순서대로 내려간다.

| # | 실행 | 언제 | 산출물 | 넘어가는 조건 | 상세 |
|---|---|---|---|---|---|
| 0 | `pip install -r requirements.txt`<br>`python -m pytest` | 맨 처음 1회 | - | `229 passed` | [1장](#1-설치와-테스트-촬영-전-1회) |
| 1 | `python src/capture_luaz.py --list-devices` | LUAZ 꽂은 뒤 | - | 어느 index 가 LUAZ 인지 눈으로 확인 | [3장](#3-luaz-연결-확인) |
| 2 | `python src/capture_luaz.py` | LUAZ 촬영 | `data/luaz/<session_id>/` | 25~30장, 커버리지 빈 셀 없음 | [4장](#4-촬영) |
| 3 | `python src/run_s10_server.py` | S10 촬영 (서버는 켜 둔 채로 4~6 진행) | - | 폰 접속, 1920x1080 확인 | [6~7장](#6-서버-띄우기) |
| 4 | `python src/preflight_jitter.py data/s10/<session_id>` | **첫 세션에만.** 보드 고정하고 20장 찍은 뒤 | - | 최대 흔들림 < 0.3 px | [8-1장](#8-1-eis--af-흔들림-preflight_jitter) |
| 5 | `python src/path_check.py <웹앱 1장> <기본앱 1장>` | **첫 세션에만** | - | 차이 <= 1% | [8-2장](#8-2-촬영-경로-동일성-path_check) |
| 6 | (노트북 화면에서 본 촬영) | S10 본 촬영 | `data/s10/<session_id>/` | 25~30장, 빈 셀 없음 | [9장](#9-s10-본-촬영-2530장) |
| 7 | `python src/run_calibrate.py data/luaz/<session_id>` | LUAZ 세션이 생긴 뒤 | `results/luaz_intrinsics.json`<br>`results/reports/<session_id>.md` | 리포트 경고 해소 | [10~12장](#10-세션-하나로-k-d-구하기) |
| 8 | `python src/run_calibrate.py data/s10/<s1> data/s10/<s2>` | S10 세션이 생긴 뒤 (**여러 개면 다 넣는다**) | `results/s10_intrinsics.json` + 리포트 | 리포트 경고 해소 | [10~12장](#10-세션-하나로-k-d-구하기) |
| 9 | `python src/run_fov_compare.py results/s10_intrinsics.json results/luaz_intrinsics.json --scan-f-target` | 7, 8 이 **둘 다** 끝난 뒤 | `results/reports/fov_compare.md` + 히트맵 3장 | - (사람이 ②/③ 결정) | [14~16장](#14-두-intrinsics-로-지표-내기) |
| 10 | `python src/run_remap.py --design 3 --f-target-scale 1.10 --reference ... -o out/...` | ②/③ 를 정한 뒤 | `results/target_space.json` + 변환된 PNG | 육안 확인 | [18장](#18-영상을-공통-공간으로-옮긴다) |

두 카메라는 서로 독립이다. **1~2(LUAZ)와 3~6(S10)은 순서를 바꿔도 되고**, 7과 8도 마찬가지다.
9만 둘 다 끝나야 돌아간다.

```
capture_luaz.py ──> data/luaz/<id>/ ──> run_calibrate.py ──> results/luaz_intrinsics.json ─┐ \
                                                                                            ├─> run_fov_compare.py
run_s10_server.py ─> data/s10/<id>/ ──> run_calibrate.py ──> results/s10_intrinsics.json  ─┘ \
                          │ \
                          └─> preflight_jitter.py, path_check.py  (첫 세션 확인용, 곁가지)
```

### 지금 어디인가 (2026-09-18)

0 까지 끝났다. **다음은 1번** - LUAZ 를 USB 에 꽂고 `--list-devices` 로 index 를 확인하는 것이다.
(현재 `Web Camera` Status=Unknown 으로 LUAZ 가 인식되지 않은 상태다. [result.md](result.md) 1장)

---

## 0. 준비물

| 항목 | 내용 |
|---|---|
| 체커보드 | 9×6 **내부 코너** (= 10×7 칸). 단단한 판에 평평하게. 둘레에 흰 여백이 있어야 검출된다 |
| 자 | **보드를 바꿀 때만** 필요하다. 현재 보드는 25.0 mm 로 확정 (2장) |
| 삼각대 | 카메라 고정용. 손으로 들면 모션 블러가 코너 정밀도를 직접 깎는다 |
| 조명 | 고정. 촬영 중 밝기를 바꾸지 않는다. 보드에 반사광이 생기지 않는 각도 |
| 노트북 | Python 3.11, `pip install -r requirements.txt` |
| LUAZ WC1080 | USB 직결 |

---

## 1. 설치와 테스트 (촬영 전 1회)

```bash
pip install -r requirements.txt
python -m pytest
```

- 확인할 것: `225 passed` (2026-09-18 기준). 이 테스트는 카메라 없이 돈다
- 실패하면: 촬영을 시작하지 않는다. 검출기나 세션 저장이 깨진 채로 찍으면 전부 다시 찍어야 한다

---

## 2. 보드 규격 — **확정됨. 할 일 없음**

현재 보드는 9x6 내부 코너, 한 칸 **25.0 mm** 로 확정되어 있다 (2026-09-18).
`config/board.yaml` 이 이미 그렇게 되어 있으므로 촬영 전에 할 일이 없다.

```yaml
board:
  cols: 9
  rows: 6
  square_mm: 25.0
  square_mm_measured: true
```

### 보드를 바꿀 때만 하는 일

1. 자로 **8칸 길이**를 재고 8로 나눈다. 두세 군데를 재서 평균한다
2. `config/board.yaml` 의 `square_mm` 을 고치고 `square_mm_measured: true` 로 둔다
3. 잰 방법과 값을 [result.md](result.md) 에 적는다

- 이 값이 틀리면: `K`(fx, fy, cx, cy)는 맞지만 거리 `t` 가 전부 같은 비율로 틀어진다
- `square_mm_measured: false` 인 동안에는 촬영 도구와 서버가 시작하지 않는다
  (종료 코드 2 / HTTP 409). 시험 촬영만 `--allow-unmeasured-square`
- **보드를 바꾸면 이전 세션과 새 세션을 한 캘리브레이션에 섞을 수 없다.** 새로 다 찍는다

---

## 3. LUAZ 연결 확인

```bash
python src/capture_luaz.py --list-devices
```

- 확인할 것: 어느 index 가 LUAZ 인지 **미리보기 창을 눈으로** 본다.
  LUAZ 와 내장 카메라는 둘 다 1920×1080 을 받으므로 해상도로는 구분되지 않는다
- index 가 0 이 아니면: `--device-index N` 으로 넘기거나 `config/cameras.yaml` 을 고친다
- 하나도 안 열리면: USB 를 다시 꽂고, PowerShell 에서 확인한다

```powershell
Get-PnpDevice -Class Camera | Select-Object Status, FriendlyName
```

  `Web Camera` 의 Status 가 `Unknown` 이면 LUAZ 가 인식되지 않은 것이다 (2026-09-18 상태)

---

## 4. 촬영

```bash
python src/capture_luaz.py
```

옵션이 필요하면: `--device-index 1`, `--backend dshow`, `--auto-interval 2.5`, `--session-id 내이름`

### 키

| 키 | 동작 |
|---|---|
| `space` | 지금 프레임 저장 (**검출 성공일 때만**) |
| `a` | 자동 모드 토글 (기본 3초 간격, 검출 성공한 프레임만) |
| `q` / `ESC` | 종료. `meta.json` 최종 저장 |

### 화면 우상단 패널

```
saved: 12            지금까지 저장한 장수
coverage: 67%        3x3 셀 중 채운 비율
empty: TR, BR        아직 비어 있는 셀 (TL/T/TR/L/C/R/BL/B/BR)
board: DETECTED      현재 프레임 검출 상태
AUTO 3.0s (next 1.2s)
```

### 무엇을 찍는가 — 25~30장

- **화면 구석까지 채운다.** `empty:` 가 `none` 이 될 때까지. 왜곡 계수 `k1, k2` 는
  가장자리 데이터가 있어야 풀린다. 가운데에서만 찍으면 RMS 는 낮은데 `D` 는 못 믿는다
- **기울인다.** 좌/우/상/하로 각각 2장 이상, 25~50° 정도. 정면만 찍으면 초점거리와
  거리가 같은 방향으로 움직여 분리되지 않는다
- **거리를 바꾼다.** 가깝게(보드가 화면을 크게 채움) / 중간 / 멀게, 각각 2장 이상
- 저장할 때마다 콘솔에 `저장 003.png  코너 54  셀 [...]  커버리지 67%  빈 셀 [...]` 가 찍힌다

- 확인할 것: 종료 시 출력되는 `총 N장 저장`, `커버리지`, `빈 셀: 없음`
- 중간에 카메라가 빠지면: 프레임 30회 연속 실패 후 예외로 멈춘다. 그때까지의 프레임과
  `meta.json` 은 디스크에 남아 있다 (프레임마다 저장하므로)

---

## 5. 촬영 결과 확인

```
data/luaz/<session_id>/
├── frames/000.png ...
└── meta.json
```

```bash
python -c "import sys; sys.path.insert(0,'src'); from camcal import Session; s=Session.open(r'data/luaz/<session_id>'); print(s.n_detected, s.coverage['ratio'], s.coverage['empty_cells'])"
```

- 확인할 것: 검출 성공 20장 이상, `ratio` 1.0, `empty_cells` 비어 있음
- 부족하면: **같은 조건에서 이어 찍지 말고 새 세션으로 다시 찍는다.**
  조명이나 카메라 위치가 바뀐 프레임이 한 세션에 섞이면 그 세션 전체를 의심해야 한다

---

# S10 촬영 (2단계)

폰은 삼각대에 고정하고 **손대지 않는다.** 사용자는 체커보드를 들고 노트북 화면을 본다.
조작(촬영·자동 모드·세션 시작/종료)은 전부 노트북에서 한다.

## 6. 서버 띄우기

```bash
python src/run_s10_server.py
```

- 인증서는 `certs/` 에 **없으면 자동 생성**된다. 따로 만들 필요 없다
- 시작 시 출력되는 두 줄을 그대로 쓴다

```
  폰에서 열기   https://<노트북 LAN IP>:8443/phone
  노트북에서 열기 https://localhost:8443/laptop
```

- 확인할 것: 노트북 브라우저에서 `laptop.html` 이 열리고 "폰: 끊김" 으로 표시되는지
- `[경고] LAN IP 를 찾지 못했다` 가 뜨면: Wi-Fi 가 끊긴 것이다. 폰이 접속할 수 없다
- `[경고] 인증서 SAN 에 현재 LAN IP 가 없다` 가 뜨면: 다른 Wi-Fi 로 옮겼거나 DHCP 가
  주소를 바꾼 것이다. `certs/cert.pem`, `certs/key.pem` 을 지우고 서버를 다시 띄운다
- 폰과 노트북이 **같은 Wi-Fi** 에 있어야 한다

## 7. 폰 접속과 카메라 선택 (첫 1회)

1. 폰 Chrome 으로 `https://<LAN IP>:8443/phone` 접속
2. "연결이 비공개로 설정되어 있지 않습니다" 경고 → **고급 → 계속**
   (자체 서명 인증서라 정상이다. HTTP 로는 카메라를 아예 열 수 없다)
3. 카메라 권한 허용
4. 카메라 목록에서 **후면 메인**을 고른다. 초록 테두리가 후면으로 추정되는 것들이다
   - **초광각·망원을 고르면 화각이 달라져 세션 전체를 다시 찍어야 한다.** \
     라벨을 반드시 확인한다
   - 고른 카메라는 이 폰에 기억된다. 바꾸려면 폰 화면 아래 "카메라 선택 다시 하기"
5. 폰 화면이 `연결됨 · 1920×1080 · 노트북에서 조작한다` 한 줄이 되면 준비 끝

- 폰 화면에 빨간 에러가 크게 뜨면: 그 카메라가 1920×1080 을 못 준다는 뜻이다.
  **다른 해상도로 대신 찍지 않는다.** 다른 카메라를 고르거나 폰 설정을 확인한다
- 노트북 화면 "연결 상태" 에서 확인할 것:
  - 폰 = 연결됨, 실제 해상도 = 1920 × 1080
  - manual 제약: 적용된 항목과 미지원 항목. **미지원은 정상이다** (기기마다 다르다). \
    무엇이 지원됐는지가 meta.json 에 남는 것이 중요하다

## 8. 본 촬영 전 두 가지 확인 (첫 세션에만)

### 8-1. EIS / AF 흔들림 (preflight_jitter)

보드를 **벽에 고정**하고, 폰도 삼각대에 고정한 채 손을 떼고 찍는다.

1. 노트북에서 `세션 시작` → 간격 2초 → `자동 시작`
2. 20장쯤 모이면 `자동 정지` → `세션 종료`
3. 판정

```bash
python src/preflight_jitter.py data/s10/<session_id>
```

- OK (최대 흔들림 < 0.3 px): 다음으로
- 경고 (>= 1 px): **EIS(손떨림 보정) 또는 AF 변동 의심.** 폰 카메라 설정에서 끄고 다시 잰다
- 드리프트만 크면: 삼각대가 밀린 것이다. EIS 와는 다른 문제

### 8-2. 촬영 경로 동일성 (path_check)

같은 삼각대, 같은 보드 위치에서 **앱만 바꿔** 한 장씩 찍는다.

1. 웹앱으로 1장 (노트북에서 `즉시 촬영`)
2. 폰 기본 카메라 앱으로 1장 (16:9, 1920×1080, zoom 1.0). 폰에서 노트북으로 옮긴다
3. 비교

```bash
python src/path_check.py data/s10/<session_id>/frames/000.png camera_app.png
```

- 차이 <= 1%: 같은 경로. 웹앱으로 구한 K 를 그대로 쓸 수 있다
- 차이 >= 3%: **경로가 다르다.** 브라우저 크롭이나 zoom 차이다.
  캘리브레이션과 실제 데이터 수집을 같은 앱으로 통일해야 한다

## 9. S10 본 촬영 (25~30장)

1. 노트북에서 `세션 시작`
2. 간격 슬라이더로 3초 → `자동 시작`
3. 체커보드를 들고 움직인다. **노트북 화면만 본다**
   - 커버리지 3×3 격자가 전부 초록이 될 때까지 (빈 셀이 `없음` 이 될 때까지)
   - 기울이기 좌/우/상/하 각 2장 이상, 25~50도
   - 거리 근/중/원 각 2장 이상
   - `마지막 업로드 프레임` 이 FAIL 로 계속 뜨면 보드가 화면을 벗어났거나 \
     너무 기울었다. 검출 실패 프레임은 저장되지 않는다 (업로드 / 미검출 카운터로 확인)
4. 저장 25~30장이 되면 `자동 정지` → `세션 종료`
5. 종료 시 표시되는 session_id, 장수, 커버리지를 [result.md](result.md) 에 적는다

- 자동 모드 중 폰 연결이 끊기면: 노트북 화면의 폰 상태가 "끊김" 으로 바뀌고
  자동 모드도 꺼진다. 폰 화면을 다시 켜면 5초 안에 재연결된다
- 이미 찍은 프레임과 meta.json 은 업로드될 때마다 디스크에 저장된다

---

# 캘리브레이션 (3단계)

## 10. 세션(들)로 (K, D) 구하기

```bash
python src/run_calibrate.py data/luaz/<session_id>
python src/run_calibrate.py data/s10/<session1> data/s10/<session2> --n-train 40
```

**세션을 여러 개 주면 전부 합쳐 한 번에 추정한다.** 한 카메라를 나눠 찍었을 때 쓴다.
카메라 / 해상도 / 보드 규격이 하나라도 다르면 합치지 않고 멈춘다 (종료 코드 2).

처리 순서는 네 단계다.

1. 전체 프레임으로 **1차 추정** - 이 K 는 버린다. 목적은 프레임별 오차를 보는 것
2. **프레임별 재투영 오차** 를 낸다
3. 오차가 큰 프레임을 **이상치로 제거** (중앙값 + k*sigma, 기본 k=3)
4. 남은 프레임으로 학습/홀드아웃을 나누고 **최종 추정**

제거는 이 추정에서 빼는 것뿐이다. **PNG 도 meta.json 도 건드리지 않는다.**

산출물

```
results/<camera>_intrinsics.json          K, D, RMS, 안정성, FOV, 경고
results/reports/<session_id>.md           표 + 해석
results/reports/<session_id>_residuals.png 잔차 벡터 그림
```

- 25~30장 찍었다면 `--n-train 20` 이 기본이다. 나머지가 전부 홀드아웃이 된다.
  **합쳐서 60장이 넘으면 `--n-train` 을 올린다** (예: 63장 -> 40). 안 올리면 20장만
  학습에 쓰고 나머지 40장이 전부 홀드아웃으로 간다
- 홀드아웃이 0장이 되면 **중단한다** (종료 코드 2). `--n-train` 을 낮춘다
- 같은 세션 + 같은 `--seed` 면 항상 같은 숫자가 나온다. 결과를 diff 할 수 있다
- `--outlier-k 5` 로 덜 버리게, `--keep-all` 로 아예 안 버리게 할 수 있다
  (프레임별 오차 표는 `--keep-all` 에서도 그대로 나온다)

## 11. 콘솔 요약에서 먼저 볼 것

```
  RMS  학습 0.2140 px (정상)  홀드아웃 0.2380 px
  fx 1502.31 +-3.20   fy 1499.88 +-3.05   (부분집합 13장 x 10회)
  cx 958.12 +-4.10   cy 541.77 +-3.88
  D (opencv_5) -0.2380, 0.0712, 0.00041, -0.00022, 0.00000
  FOV  nominal H 64.97 deg / effective(alpha=0) H 71.20 deg
  경고 없음
```

| 볼 것 | 판정 |
|---|---|
| 학습 RMS | ~0.3 px 정상 / 0.3~0.6 설명 안 되는 요인 / 1.0 이상 구조적 문제 |
| 홀드아웃 / 학습 비율 | 1.5배 넘으면 경고. 과적합이거나 세션에 조건이 다른 사진이 섞였다 |
| fx, fy 의 `+-` 값 | 부분집합마다 얼마나 흔들리는가. fx 의 1% 를 넘으면 데이터가 부족하다 |
| cx, cy | 화면 중심(960, 540)에서 50 px 넘게 벗어나면 경고가 뜬다 |
| k1 부호 | 광각이면 보통 음수(배럴). 양수면 보드가 가장자리까지 안 왔을 가능성 |
| FOV 두 값 | **다른 것이 정상이다.** 배럴 렌즈는 effective 가 nominal 보다 넓다 |

**RMS 만 보고 판단하지 않는다.** 리포트의 네 항목을 같이 본다.

## 11-1. 프레임별 오차 표를 먼저 본다 (리포트 0장)

전체 RMS 하나로는 두 상황이 구분되지 않는다. **해야 할 일이 정반대다.**

| 프레임별 표가 이러면 | 뜻 | 할 일 |
|---|---|---|
| 대부분 낮은데 **몇 장만** 크다 | 그 몇 장에 사고가 있었다 (흔들림, 보드 휨, 가장자리 벗어남) | 이상치 제거가 처리한다. 그대로 진행 |
| **전부** 비슷하게 높다 | 촬영 조건 자체의 문제 | 제거로 해결되지 않는다. 다시 찍는다 |
| 특정 **세션만** 높다 | 그 판의 조명·자세·초점이 달랐다 | 그 세션을 빼고 추정하거나 다시 찍는다 |

- 중앙값을 본다. 중앙값이 0.3 px 을 넘으면 이상치 제거로는 해결되지 않는다
- 세션이 여러 개면 세션별로 나눠 본다 (프레임 이름에 세션 id 가 붙어 있다)
- `경계` 가 어떻게 나왔는지도 표에 있다 (중앙값, MAD, sigma)

> 절반 이상이 나쁘면 **이상치 판정 자체가 작동하지 않는다.** 중앙값이 나쁜 쪽으로
> 끌려가서 경계가 같이 올라가기 때문이다. 이때는 0장 제거로 나오는데, 그것이
> "문제 없음"이 아니라 "판정 불가"라는 뜻이다. 중앙값을 직접 확인한다.

## 12. 리포트에서 볼 네 가지

`results/reports/<session_id>.md` 를 연다.

1. **공간 분포** (4×4 셀별 평균 잔차) - 한쪽 셀에만 크게 몰려 있으면 전체 RMS 가 낮아도
   그 영역의 K, D 는 못 믿는다. **비어 있는 셀**이 있으면 그 영역의 왜곡은 추정된 것이
   아니라 외삽된 값이다 -> 그 자리를 채워 다시 찍는다
2. **잔차 방향성** (방사성 내적 + 잔차 벡터 PNG) - 화살표가 사방으로 흩어져 있으면 정상.
   가장자리에서 일제히 한 방향이면 왜곡 모델 부족. 한 덩어리만 같은 방향이면 그 사진
   한 장의 문제다 (흔들림, 보드 휨)
3. **파라미터 안정성** - fx 표준편차가 크면 RMS 가 낮아도 데이터가 파라미터를 결정하지
   못한 것이다 (자세가 다 비슷하거나, 장수가 부족하거나)
4. **홀드아웃 사진별 RMS** - 한 장만 유독 크면 그 사진을 의심한다. 전체가 고르게 크면
   K, D 자체가 일반화되지 않는 것이다

경고에 "안정성 검사 부분집합이 줄었다" 가 뜨면 학습 장수가 부족한 것이다. 더 찍는다.

## 13. 두 카메라 모두 끝나면

`results/luaz_intrinsics.json` 과 `results/s10_intrinsics.json` 이 모두 생기면 4단계
(FOV 비교, target 공간 결정)로 넘어간다. 그 전에 각각의 리포트 경고가 모두 해소돼야 한다.

숫자와 판단은 [result.md](result.md) 에 옮긴다.

---

# target 공간 비교 (4단계)

## 14. 두 intrinsics 로 지표 내기

3단계가 `results/luaz_intrinsics.json` 과 `results/s10_intrinsics.json` 을
모두 만든 뒤에 돌린다.

```bash
python src/run_fov_compare.py results/s10_intrinsics.json results/luaz_intrinsics.json
```

인자 순서: **변환할 카메라(src) 먼저, 기준 카메라(dst) 나중.** 보통 s10, luaz 순이다.

산출물

```
results/reports/fov_compare.md
results/reports/stretch_design3_0.png   s10  -> 가상 카메라
results/reports/stretch_design3_1.png   luaz -> 가상 카메라
results/reports/stretch_design2_0.png   s10  -> luaz 원본
```

이 도구는 **결정하지 않는다.** ②/③ 중 무엇을 쓸지는 이 숫자를 보고 사람이 정한다.

## 15. 리포트를 읽는 순서

### 15-1. 게이트부터 (2장)

`LUAZ fov_effective ⊆ S10 fov_effective` 인가.

> **게이트는 선별용이다.** H 와 V 를 축별로 비교할 뿐이라, 두 축이 다 통과해도
> 화면 **모서리**는 따로다 (대각 방향은 H 도 V 도 아니고, 왜곡 때문에 화각 경계가
> 직사각형이 아니다). 설계 ② 의 모서리 커버리지는 4장의 `valid pixel ratio` 가
> 판정한다. **게이트 통과 = ② 가능이 아니다.**

- **통과**: 여유 각도를 확인하고 4장의 valid pixel ratio 로 넘어간다.
  여유가 1도 미만이면 가장자리가 위태롭다
- **불통과**: **설계 ② 는 불가능하다.** LUAZ 가 S10 보다 넓으면 S10 에 없는 픽셀을
  요구하게 되고, 없는 픽셀은 만들 수 없다. 설계 ③ 도 `f_target` 을 올려 화각을 좁혀야 한다
  - 이 경우 먼저 의심할 것: S10 이 후면 **메인**이 맞는가 (초광각을 고르면 반대로 넓다), \
    S10 쪽에 EIS 크롭이 걸려 있지 않은가 (8-1 로 확인)

### 15-2. 두 설계의 숫자 (3, 4장)

| 보는 값 | 뜻 |
|---|---|
| valid pixel ratio | 1.0 미만이면 그만큼 검은 영역이 생긴다. 잘라내야 하고, 잘라내면 화각이 준다 |
| local stretch (면적) | 1보다 크면 확대. 없는 정보를 보간으로 채우므로 뭉개진다 |
| 같은 값의 선형 배율 | 면적의 제곱근. 판정선이 면적 기준이라 실제 체감과 다를 수 있다 |
| 히트맵의 회색 영역 | 검은 영역이 생길 자리 |
| 히트맵의 밝은 영역 | 확대가 큰 곳. 보통 가장자리다 |

### 15-3. 판정 참고 (5장)

`valid >= 98%` **이고** `stretch 95p <= 1.15` 면 "기하학적으로 적합".

- 이것은 **'가능한가'까지만**이다. '좋은 선택인가'는 변환 영상의 SSIM / edge / MTF,
  필요하면 모델 성능까지 보고 정한다
- 미달이라고 자동으로 탈락시키지 않는다. 수치를 그대로 읽는다.
  특히 stretch 는 면적 기준이라 초점거리가 7% 만 달라도 걸린다

### 15-4. 없는 것

RMS 는 이 리포트에 없다. RMS 는 `(K, D)` 추정 품질이고 target 적합성과 무관하다.
추정 품질은 3단계 리포트에서 본다.

## 16. 결정을 적는다

②/③ 중 무엇을 골랐는지, 그 근거가 리포트의 어느 숫자인지를 [result.md](result.md) 의
decision log 에 적는다. 이 결정이 5단계(변환 프로그램)의 전제가 된다.

---

# 변환 (5단계)

## 18. 영상을 공통 공간으로 옮긴다

### 18-1. 처음 한 번 - 설계와 배율을 명시한다

```bash
python src/run_remap.py data/s10/<session_id> --intrinsics results/s10_intrinsics.json --design 3 --reference results/luaz_intrinsics.json --f-target-scale 1.10 --note "2026-09-21 확정. result.md 9장" -o out/s10 --compare
```

이때 `results/target_space.json` 이 만들어진다. **이 파일이 공통 공간의 정본이다.**

- `--design` 을 주지 않고 이 파일도 없으면 **멈춘다** (종료 코드 2).
  코드가 ②/③ 를 대신 고르지 않는다
- 이미 있는데 `--design` 을 또 주면 덮어쓰면서 경고한다.
  **이전 공간으로 변환해 둔 결과물은 새 것과 섞을 수 없다**

### 18-2. 이후 - 파일을 그대로 쓴다

```bash
python src/run_remap.py data/luaz/<session_id> --intrinsics results/luaz_intrinsics.json -o out/luaz --compare
```

### 18-3. 옵션

| 옵션 | 뜻 |
|---|---|
| `--compare` | 전/후를 나란히 붙인 비교본을 `<out>/compare/` 에 같이 저장 |
| `--crop` | 검은 영역을 잘라내고 유효 영역만 남긴다 (최대 내접 사각형) |
| `--limit N` | 앞에서 N 장만 |

검은 영역은 **원본에 없는 부분**이다. 채우지 않는다. 그대로 두거나(`기본`)
잘라내거나(`--crop`) 둘 중 하나다.

### 18-4. 확인할 것

- 콘솔의 `valid pixel ratio` 가 4단계 리포트의 값과 같은지 (다르면 다른 공간을 쓴 것)
- `--compare` 로 나온 비교본을 **눈으로** 본다. 직선인 것이 직선으로 보이는지.
  `k1` 부호가 틀렸으면 반대로 휜다. 지표는 못 잡아도 눈은 잡는다
- 세션 디렉토리를 주면 **meta.json 이 아는 프레임만** 변환한다 (폴더를 glob 하지 않는다)

## 19. 두 카메라를 실시간으로 겹쳐 본다

LUAZ 를 노트북에 꽂고 서버를 띄우면, S10 웹앱 프리뷰와 나란히/겹쳐서 볼 수 있다.

```bash
python src/run_s10_server.py --with-luaz
```

```
  폰에서 열기   https://<LAN IP>:8443/phone
  노트북에서 열기 https://localhost:8443/laptop
  라이브 비교     https://localhost:8443/compare
```

`/compare` 에서:

| 모드 | 무엇을 보는가 |
|---|---|
| **블렌드** | 슬라이더로 두 화면을 섞는다. 대략의 정렬을 본다 |
| **차이** | 겹치면 검게, 어긋나면 밝게. **정렬 오차를 제일 잘 보여준다** |
| **나란히** | 각각 따로 본다 |

- `target 공간으로 변환` 체크를 끄면 원본끼리 비교한다 (변환 효과를 보려면 켜고 끈다)
- `results/target_space.json` 과 양쪽 intrinsics 가 있어야 변환이 된다.
  없으면 화면이 그 사실을 알려주고 원본만 보여준다

**주의**
- `--with-luaz` 는 촬영 도구(`capture_luaz.py`)와 **같은 카메라를 동시에 쓸 수 없다.**
  둘 중 하나만 띄운다
- S10 쪽은 320x180 프리뷰다. 정렬을 보는 용도이지 화질 비교용이 아니다
- **평면 차트만 겹친다.** 3D 장면은 시차 때문에 겹치지 않는다.
  같은 삼각대 자리에서 카메라만 바꿔 꽂아야 의미가 있다

---

## 20. 기록

- 각 단계에서 나온 수치·판단은 그 자리에서 [result.md](result.md) 에 추가한다
- 세션을 하나 찍을 때마다: session_id, 장수, 커버리지, 조명·거리 조건, 실측 `square_mm`
- 작업 후 검수는 [docs/REVIEW_PROTOCOL.md](docs/REVIEW_PROTOCOL.md) 절차를 따르고,
  결과 한 줄을 result.md 에 남긴다
