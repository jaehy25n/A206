"""프로젝트 전역 상수.

매직 넘버를 코드에 직접 쓰지 않는다. 값을 바꿀 일이 생기면 여기 한 곳만 고치고,
왜 그 값인지를 주석으로 남긴다.

좌표 이름 규약 (CLAUDE.md 3절):
    X_w  월드 좌표 (보드 평면, mm)
    X_c  카메라 좌표 (mm)
    x_n, y_n  정규 좌표 (단위 없음, Z_c 로 나눈 뒤)
    u, v  픽셀 좌표
"""

from __future__ import annotations

import cv2

# --- 코너 검출 -------------------------------------------------------------

#: findChessboardCorners 플래그.
#: ADAPTIVE_THRESH  조명 기울기가 있는 실내에서 필수.
#: NORMALIZE_IMAGE  노출이 세션마다 달라도 같은 임계값이 먹도록.
#: FAST_CHECK       보드가 없는 프레임을 빨리 버린다. 실시간 미리보기에 필요.
#: FILTER_QUADS 는 쓰지 않는다 - 기울인 보드의 원근 사각형을 걸러내 검출률을 떨어뜨린다.
FIND_CORNERS_FLAGS = (
    cv2.CALIB_CB_ADAPTIVE_THRESH
    | cv2.CALIB_CB_NORMALIZE_IMAGE
    | cv2.CALIB_CB_FAST_CHECK
)

#: cornerSubPix 탐색 창 반경 (픽셀). (11, 11) 이면 23x23 창.
#: 1920x1080 에서 한 칸이 보통 40~100 px 이므로 이웃 코너를 넘보지 않는 크기다.
SUBPIX_WINDOW = (11, 11)

#: cornerSubPix 제외 영역. (-1, -1) = 쓰지 않음.
SUBPIX_ZERO_ZONE = (-1, -1)

#: cornerSubPix 종료 조건: 30회 반복 또는 이동량 0.001 px 이하.
SUBPIX_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)


# --- 커버리지 --------------------------------------------------------------

#: 화면을 몇 등분해서 보드가 화면 구석까지 왔는지 보는가.
#: 3x3 = 9셀. 왜곡 계수 k1, k2 는 화면 가장자리 데이터가 있어야 풀린다.
COVERAGE_GRID = (3, 3)  # (cols, rows)


# --- 저장 ------------------------------------------------------------------

#: PNG 무손실. JPEG 는 코너 위치를 흔들기 때문에 쓰지 않는다.
#: 압축 레벨 1 = 빠르게. 무손실이라 화질은 레벨과 무관하다.
PNG_WRITE_PARAMS = [cv2.IMWRITE_PNG_COMPRESSION, 1]

#: 프레임 파일명. 000.png, 001.png ...
FRAME_FILENAME_FORMAT = "{index:03d}.png"

#: 세션 메타데이터 파일명.
META_FILENAME = "meta.json"

#: meta.json 스키마 버전. 필드를 바꾸면 올린다.
META_SCHEMA_VERSION = 3


# --- 촬영 도구 -------------------------------------------------------------

#: 자동 모드 기본 간격 (초). 손이 보드를 옮기고 흔들림이 멎을 시간.
AUTO_INTERVAL_SEC = 3.0

#: 미리보기 창에서 코너를 그릴 때의 원 반경 (픽셀).
OVERLAY_CORNER_RADIUS = 4


# --- 캘리브레이션 (3단계) ---------------------------------------------------

#: cv2.calibrateCamera 플래그. 0 = OpenCV 기본 모델 (k1, k2, p1, p2, k3).
#: 고정하거나 빼는 계수가 있으면 여기서 바꾸고, 바꾼 이유를 result.md 에 적는다.
#: 모델을 바꾸면 D 의 길이와 의미가 달라지므로 결과 JSON 에 D_model 로 남긴다.
CALIB_FLAGS = 0

#: 이 플래그 조합이 만들어내는 왜곡 모델 이름. intrinsics JSON 의 D_model.
CALIB_D_MODEL = "opencv_5"

#: calibrateCamera 종료 조건. 기본값보다 조금 더 조인다 (1080p 에서 몇 초 차이).
CALIB_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7)

#: 기본 학습 장수. 나머지는 홀드아웃으로 간다 (25~30장 찍어 20장 학습).
DEFAULT_N_TRAIN = 20

#: 분할 시드 기본값. 같은 시드 -> 같은 분할.
DEFAULT_SEED = 0

#: 파라미터 안정성 검사: 몇 번, 몇 장씩 뽑아 다시 추정하는가.
#: fx 가 부분집합마다 크게 흔들리면 데이터가 부족하거나 자세 다양성이 없는 것이다.
STABILITY_RUNS = 10
STABILITY_SUBSET = 15

#: 잔차 공간 분포를 볼 격자 (4x4 = 16셀). 커버리지 격자(3x3)와 다른 목적이라
#: 따로 둔다: 저쪽은 촬영 중 안내, 이쪽은 사후 오차 분석.
SPATIAL_GRID = 4

#: sanity_check 임계값.
#: fx 와 fy 는 정사각 픽셀 센서라면 1% 안에 들어온다.
SANITY_FXFY_REL_TOL = 0.01
#: 주점은 보통 화면 중심 근처다. 50 px 이상 벗어나면 크롭이나 추정 실패를 의심한다.
SANITY_PRINCIPAL_TOL_PX = 50.0

#: RMS 해석 구간 (픽셀). CLAUDE.md 6절.
#: ~0.3 정상 / 0.3~0.6 설명 안 되는 요인 있음 / 1.0 이상 구조적 문제.
RMS_GOOD_PX = 0.3
RMS_SUSPECT_PX = 0.6
RMS_BAD_PX = 1.0

#: 홀드아웃 RMS 가 학습 RMS 보다 이 배율 이상 크면 과적합을 의심한다.
HOLDOUT_RATIO_WARN = 1.5

#: 잔차 방사성(radiality) 경고 임계값 (픽셀).
#: 잔차가 방사 방향으로 일정하게 쏠려 있으면 왜곡 모델이 데이터를 못 따라간 것이다.
RADIALITY_WARN_PX = 0.1


# --- 파일 쓰기 (Windows) ----------------------------------------------------

#: meta.json 을 원자적으로 바꿔치기할 때 os.replace 재시도 횟수와 간격 (초).
#: Windows 에서는 방금 쓴 파일을 백신/검색 인덱서가 잠깐 열고 있어 os.replace 가
#: PermissionError 를 내는 일이 있다 (실제로 테스트 중 간헐 발생). 촬영 중에는
#: 프레임마다 save() 를 부르므로, 한 번의 일시적 잠금으로 세션이 죽으면 안 된다.
META_REPLACE_RETRIES = 10
META_REPLACE_DELAY_SEC = 0.05


# --- target 공간 비교 (4단계) ------------------------------------------------

#: remap 후 검은 영역 없이 유효한 픽셀 비율의 판정선.
#: 0.98 = 가장자리 2% 까지는 잘라내고 쓸 수 있다고 본다.
VALID_RATIO_OK = 0.98

#: 국소 확대(stretch) 95 퍼센타일 판정선.
#: 1.15 = 화면의 95% 지점에서 15% 이상 확대되지 않는다. 확대는 없는 정보를
#: 만들어내는 것이라 보간으로 뭉개진다.
STRETCH_P95_OK = 1.15

#: remap 맵을 만들 때의 OpenCV 맵 타입. CV_32FC1 두 장(map_x, map_y)으로 받는다
#: (CV_16SC2 는 고정소수점이라 야코비안을 재는 데 쓸 수 없다).
REMAP_MAP_TYPE = cv2.CV_32FC1

#: 야코비안/유효성 계산에서 목적지 픽셀이 원본 범위 안인지 볼 때의 여유 (픽셀).
#: remap 은 경계에서 보간에 이웃 픽셀을 쓰므로 정확히 0..W-1 이면 경계가 흐려진다.
VALID_MARGIN_PX = 0.5

#: stretch 히트맵 그림 크기(인치)와 해상도.
HEATMAP_SIZE_IN = (9.0, 5.2)
HEATMAP_DPI = 110


# --- 이상치 프레임 제거 (다중 세션 캘리브레이션) -----------------------------

#: 프레임별 재투영 RMS 가 median + k * (robust sigma) 를 넘으면 이상치로 본다.
#: robust sigma = 1.4826 * MAD. 평균/표준편차 대신 중앙값/MAD 를 쓰는 이유는
#: 이상치 자체가 평균과 표준편차를 끌고 가 버리기 때문이다.
OUTLIER_MAD_K = 3.0

#: 절대 하한. 모든 프레임이 아주 좋으면 sigma 가 0 에 가까워져서 멀쩡한 프레임까지
#: 이상치가 된다. 이 값 아래로는 잘라내지 않는다.
OUTLIER_FLOOR_PX = RMS_GOOD_PX

#: 한 번에 이 비율 넘게 버리지 않는다. 절반을 버려야 할 정도면 이상치가 아니라
#: 촬영 자체가 잘못된 것이고, 사람이 봐야 한다.
OUTLIER_MAX_DROP_RATIO = 0.30

#: 제거 후 최소 프레임 수. 이보다 적게 남으면 제거를 포기하고 경고한다.
OUTLIER_MIN_KEEP = 12


# --- f_target 탐색 (설계 ③) --------------------------------------------------

#: f_target 을 몇 %씩 올리며 찾을 것인가. valid pixel ratio 는 f_target 을 올리면
#: (화각이 좁아지면) 올라간다. 대신 국소 확대(stretch)는 같이 커진다 - 같은 화면을
#: 더 좁은 각도로 채우는 것이기 때문이다. 두 지표가 반대로 움직이므로 표로 본다.
F_TARGET_SCAN_STEP = 0.05

#: 탐색 상한. 1.6 배면 화각이 원래의 약 2/3 로 줄어든다. 그보다 더 잘라야 한다면
#: 애초에 두 카메라를 맞출 수 없다고 보는 편이 낫다.
F_TARGET_SCAN_MAX = 1.60


#: --crop 으로 잘라내고 남아야 하는 최소 넓이 비율. 이보다 작으면 조용히
#: 작은 이미지를 내놓지 않고 멈춘다.
MIN_CROP_AREA_RATIO = 0.10
