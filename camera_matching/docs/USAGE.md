# 카메라 영상 변환 — 사용법

S10 과 LUAZ 의 렌즈 차이를 없애고 **같은 규격의 영상**으로 바꿔 주는 모듈입니다.
학습은 S10 영상으로, 운용은 LUAZ 영상으로 하기 위한 것입니다.

---

## 필요한 것

프로젝트 폴더 `camera_matching/` 안에 이미 들어 있습니다.

```
results/luaz_intrinsics.json     LUAZ 카메라 파라미터
results/s10_intrinsics.json      S10 카메라 파라미터
results/target_space.json        공통 규격 (두 카메라가 맞춰질 기준)
```

의존성은 `numpy`, `opencv-python` 뿐입니다 (`pip install -r requirements.txt`).

---

## 코드에 붙이는 법

```python
import sys
sys.path.insert(0, r"<경로>/camera_matching/src")

from camcal.stream import FrameRemapper

# 시작할 때 한 번만
remapper = FrameRemapper.from_files(r"<경로>/camera_matching/results/luaz_intrinsics.json")

# 프레임마다
out = remapper.apply(frame)
```

S10 영상이면 `s10_intrinsics.json` 을 대신 넣습니다. **그 외에는 똑같습니다.**

| | |
|---|---|
| 입력 | 1920×1080 BGR (OpenCV 기본) |
| 출력 | 1920×1080 BGR |
| 속도 | 프레임당 **약 4~5 ms** (30 fps 예산의 15% 이하) |

---

## 바로 확인해 보기

```bash
# 웹캠을 실시간 변환해서 원본과 나란히 띄운다
python src/run_video_remap.py --camera-index 0 --intrinsics results/luaz_intrinsics.json --side-by-side

# 동영상 파일 -> 동영상 파일
python src/run_video_remap.py in.mp4 --intrinsics results/s10_intrinsics.json -o out.mp4
```

---

## 주의 세 가지

**1. 입력은 1920×1080 이어야 합니다.**
다른 크기로 들어오면 예외가 납니다 (조용히 틀리는 것보다 낫다고 판단했습니다).
다른 해상도로 쓰시려면 만들 때 크기를 알려 주세요. **종횡비가 16:9 면** 정확히 처리합니다.

```python
remapper = FrameRemapper.from_files(경로, input_size=(1280, 720))
```

**2. S10 쪽은 가장자리 1.2% 가 검은 영역입니다.**
원본에 없는 부분이라 채울 수 없습니다. 잘라내려면:

```python
remapper = FrameRemapper.from_files(경로, crop=True)   # 출력 1888×1080
```

**3. 카메라 설정이 바뀌면 다시 만들어야 합니다.**
해상도나 zoom 을 바꾸면 기존 변환이 맞지 않습니다.

---

## 지금 값의 한계 (꼭 알아 주세요)

**변환은 동작하지만 정확도가 목표에 못 미칩니다.**

| 항목 | 목표 | 현재 |
|---|---|---|
| 재투영 오차 | < 0.3 px | 0.39 ~ 0.47 px |
| S10 초점거리 | — | 촬영 회차 간 **16% 불일치** |

체커보드를 손으로 들고 찍었고 화면 가장자리까지 채우지 못한 것이 원인입니다.
재촬영하면 대부분 해소됩니다.

**실무적으로는**, 모델이 거리나 크기를 판단한다면 그 값이 한쪽으로 치우칠 수 있습니다
(최악의 경우 16%). 일단 이대로 쓰시되, **정확도가 중요한 판단에는 이 한계를 감안해
주세요.**

자로 카메라-보드 거리를 한 번만 재 주시면 1 분 안에 검증됩니다:

```bash
python src/check_align.py --camera s10 --distance-mm 400 사진.png
```

---

## 더 자세히

| 문서 | 내용 |
|---|---|
| `docs/REPORT.md` | 무엇을 왜 이렇게 만들었는지 (진행 보고) |
| `action.md` | 촬영부터 변환까지 실행 순서 |
| `result.md` | 측정값과 결정 기록 전부 |
