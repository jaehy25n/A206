"""target 공간 후보를 **숫자로 비교**하기 위한 지표. 결정은 하지 않는다.

README "미정 결정" 표의 두 설계를 각각 매핑으로 만들고, 세 지표를 잰다.

    설계 ② LUAZ 원본 = target   K_target = K_luaz,        D_target = D_luaz
    설계 ③ 가상 카메라 = target  K_target = K_luaz 유도값,  D_target = 0

    (CLAUDE.md 5절의 A/B 와 대응: A = ③, B = ②. 문서마다 이름이 달라 혼동이
     생기므로 여기서는 README 의 번호만 쓴다.)

세 지표 (README 판정 절차 2번)
    FOV overlap        containment()
    valid pixel ratio  valid_ratio()
    local stretch      local_stretch()

매핑의 방향에 대하여 - 여기서 만드는 map_x, map_y 는 전부 **목적지 -> 원본** 이다.
cv2.remap 이 그 방향을 요구하기 때문이다 (목적지 픽셀마다 "원본 어디서 가져올까"를
본다). 사람이 생각하는 방향(원본 -> 목적지)과 반대이므로, 이 파일 밖에서는
"역방향"이라는 말을 쓰지 않는다 - 라이브러리가 처리하는 구현 세부다.

좌표 이름:
    u, v        픽셀 좌표
    x_n, y_n    정규 좌표 (단위 없는 방향. 두 카메라가 공유하는 공통 언어)
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .constants import REMAP_MAP_TYPE, VALID_MARGIN_PX


# --- 매핑 만들기 ------------------------------------------------------------


def build_map_to_pinhole(
    K_src: np.ndarray,
    D_src: np.ndarray,
    K_target: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """**설계 ③ (가상 카메라 = target)** 용 매핑.

    목적지는 왜곡이 없는 핀홀 공간이다 (D_target = 0). 즉 목적지에서는 직선이
    직선으로 남는다.

        목적지 픽셀 --[K_target^-1]--> (x_n, y_n) --[D_src 적용]--> --[K_src]--> 원본 픽셀

    Args:
        K_src, D_src: 변환할 카메라의 (K, D).
        K_target: 목적지 핀홀 카메라의 K. 보통 LUAZ 의 K' (alpha=0).
        width, height: 목적지 이미지 크기.

    Returns:
        (map_x, map_y) 각각 (height, width) float32. 목적지 픽셀 -> 원본 픽셀 좌표.
    """
    K_src = np.asarray(K_src, dtype=np.float64)
    D_src = np.asarray(D_src, dtype=np.float64).ravel()
    K_target = np.asarray(K_target, dtype=np.float64)

    map_x, map_y = cv2.initUndistortRectifyMap(
        K_src,
        D_src,
        np.eye(3, dtype=np.float64),  # R = I. 두 카메라를 같은 자세로 본다
        K_target,
        (int(width), int(height)),
        REMAP_MAP_TYPE,
    )
    return np.asarray(map_x, dtype=np.float32), np.asarray(map_y, dtype=np.float32)


def build_map_to_distorted(
    K_src: np.ndarray,
    D_src: np.ndarray,
    K_dst: np.ndarray,
    D_dst: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """**설계 ② (LUAZ 원본 = target)** 용 매핑.

    목적지가 왜곡을 그대로 가진 공간이다 (D_target = D_dst != 0). LUAZ 영상을
    전혀 건드리지 않는 대신, S10 영상에 LUAZ 의 왜곡을 **일부러 만들어 넣는다.**

        목적지 픽셀 --[undistortPoints(K_dst, D_dst)]--> (x_n, y_n)
                    --[projectPoints(rvec=0, tvec=0, K_src, D_src)]--> 원본 픽셀

    가운데 (x_n, y_n) 은 단위 없는 방향이고, 두 카메라가 공유하는 공통 언어다.
    rvec = tvec = 0 인 이유: 같은 방향을 다른 카메라의 픽셀로 옮기는 것뿐이고,
    자세 차이는 여기서 다루지 않기 때문이다 (같은 삼각대 전제).

    Args:
        K_src, D_src: 변환할 카메라 (S10).
        K_dst, D_dst: 목적지 카메라 (LUAZ 원본). **D_dst 를 0 으로 넣으면 설계 ③ 이
            되어 버린다** - 그 경우는 build_map_to_pinhole 을 쓴다.
        width, height: 목적지 이미지 크기.

    Returns:
        (map_x, map_y) 각각 (height, width) float32.
    """
    K_src = np.asarray(K_src, dtype=np.float64)
    D_src = np.asarray(D_src, dtype=np.float64).ravel()
    K_dst = np.asarray(K_dst, dtype=np.float64)
    D_dst = np.asarray(D_dst, dtype=np.float64).ravel()

    width, height = int(width), int(height)
    grid_u, grid_v = np.meshgrid(
        np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64)
    )
    dst_pixels = np.stack([grid_u.ravel(), grid_v.ravel()], axis=1).reshape(-1, 1, 2)

    # 목적지 픽셀 -> 정규 좌표 (목적지 카메라의 왜곡을 푼다)
    normalized = cv2.undistortPoints(dst_pixels, K_dst, D_dst)
    normalized = np.asarray(normalized, dtype=np.float64).reshape(-1, 2)

    # 정규 좌표를 3차원 방향으로 올린 뒤(Z=1) 원본 카메라로 투영
    directions = np.concatenate(
        [normalized, np.ones((normalized.shape[0], 1), dtype=np.float64)], axis=1
    )
    zero = np.zeros((3, 1), dtype=np.float64)
    projected, _ = cv2.projectPoints(directions, zero, zero, K_src, D_src)
    projected = np.asarray(projected, dtype=np.float64).reshape(height, width, 2)

    return (
        projected[:, :, 0].astype(np.float32),
        projected[:, :, 1].astype(np.float32),
    )


# --- 지표 1: valid pixel ratio ----------------------------------------------


def valid_mask(
    map_x: np.ndarray,
    map_y: np.ndarray,
    width_src: int,
    height_src: int,
    margin: float = VALID_MARGIN_PX,
) -> np.ndarray:
    """목적지 픽셀이 원본 이미지 안에서 값을 가져올 수 있는지 (bool 배열).

    margin 을 두는 이유: remap 은 경계에서 보간에 이웃 픽셀을 쓰므로, 정확히
    0 이나 W-1 에 걸친 픽셀은 반쪽짜리 값이 된다.

    NaN/Inf 도 무효로 친다 (왜곡 모델이 발산하는 영역에서 나온다).
    """
    finite = np.isfinite(map_x) & np.isfinite(map_y)
    inside = (
        (map_x >= margin)
        & (map_x <= (width_src - 1) - margin)
        & (map_y >= margin)
        & (map_y <= (height_src - 1) - margin)
    )
    return finite & inside


def valid_ratio(
    map_x: np.ndarray,
    map_y: np.ndarray,
    width_src: int,
    height_src: int,
    margin: float = VALID_MARGIN_PX,
) -> float:
    """원본 범위 안에 떨어지는 목적지 픽셀 비율 (0.0 ~ 1.0).

    1.0 보다 작다는 것은 그만큼 **검은 영역**이 생긴다는 뜻이다.
    검은 영역은 모델 입력으로 쓸 수 없으므로 잘라내야 하고, 잘라내면 화각이 준다.
    """
    mask = valid_mask(map_x, map_y, width_src, height_src, margin)
    return float(mask.mean())


# --- 지표 2: local stretch --------------------------------------------------


def local_stretch(
    map_x: np.ndarray,
    map_y: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """위치별 국소 배율 (확대 배수).

    유한차분으로 야코비안 J = d(원본 픽셀) / d(목적지 픽셀) 를 구하고 그 행렬식의
    절댓값 |det J| 를 낸다. |det J| 는 "목적지 1 픽셀이 원본 몇 픽셀에서 오는가"다.

    반환하는 **stretch = 1 / |det J|** 는 그 역수, 즉 "원본 1 픽셀이 목적지에서
    몇 픽셀로 늘어나는가" = 확대 배수다.

        stretch > 1  확대. 없는 정보를 보간으로 채운다 -> 뭉개진다
        stretch = 1  등배
        stretch < 1  축소. 정보를 버리지만 흐려지지는 않는다

    역수를 쓰는 이유: 우리가 걱정하는 것은 "가장자리 과도 확대"이고, 그것이 큰
    값으로 나와야 상한(95 퍼센타일 <= 1.15)으로 걸러진다. |det J| 그대로면 확대가
    1 보다 **작은** 값으로 나와 상한에 걸리지 않는다. 두 값을 모두 요약에 넣는다.

    **stretch 는 면적 배율이다** (야코비안 행렬식이므로). 한 변의 배율(선형)은
    그 제곱근이고, 요약에 linear_* 로 같이 담는다. 판정선을 어느 쪽에 걸지는
    해석이 갈리는 지점이라 두 값을 모두 보여준다 - 면적 1.15 는 선형으로 1.072 라
    카메라 초점거리가 7% 만 달라도 걸린다.

    Args:
        mask: 유효 픽셀 마스크. 무효 영역의 야코비안은 의미가 없으므로 통계에서 뺀다.

    Returns:
        (stretch 배열 (H, W) float64, 요약 dict)
        요약: median, p95, max, max_at (u, v), min, p05,
              linear_median, linear_p95, linear_max,
              det_median, det_p05, n_used
    """
    map_x = np.asarray(map_x, dtype=np.float64)
    map_y = np.asarray(map_y, dtype=np.float64)

    # np.gradient 는 축 순서대로 (d/dv, d/du) 를 준다 (행 = v, 열 = u)
    dx_dv, dx_du = np.gradient(map_x)
    dy_dv, dy_du = np.gradient(map_y)

    det = np.abs(dx_du * dy_dv - dx_dv * dy_du)
    with np.errstate(divide="ignore", invalid="ignore"):
        stretch = np.where(det > 0, 1.0 / det, np.inf)

    if mask is None:
        mask = np.isfinite(stretch)
    usable = mask & np.isfinite(stretch)
    values = stretch[usable]

    if values.size == 0:
        return stretch, {
            "median": None, "p95": None, "max": None, "max_at": None,
            "min": None, "p05": None,
            "linear_median": None, "linear_p95": None, "linear_max": None,
            "det_median": None, "det_p05": None,
            "n_used": 0,
        }

    masked = np.where(usable, stretch, -np.inf)
    flat_at = int(np.argmax(masked))
    max_v, max_u = np.unravel_index(flat_at, stretch.shape)
    det_values = det[usable]

    median = float(np.median(values))
    p95 = float(np.percentile(values, 95))
    maximum = float(values.max())
    summary = {
        "median": median,
        "p95": p95,
        "max": maximum,
        "max_at": [int(max_u), int(max_v)],  # (u, v)
        "min": float(values.min()),
        "p05": float(np.percentile(values, 5)),
        # 한 변의 배율 = 면적 배율의 제곱근
        "linear_median": float(np.sqrt(median)),
        "linear_p95": float(np.sqrt(p95)),
        "linear_max": float(np.sqrt(maximum)),
        "det_median": float(np.median(det_values)),
        "det_p05": float(np.percentile(det_values, 5)),
        "n_used": int(values.size),
    }
    return stretch, summary


# --- 지표 3: FOV 포함 관계 --------------------------------------------------


def containment(
    fov_a: tuple[float, float], fov_b: tuple[float, float]
) -> dict[str, Any]:
    """화각 a 가 b 안에 들어오는가 (a subset of b).

    필수 선행 조건 (README): `LUAZ fov ⊆ S10 usable fov`.
    LUAZ 가 S10 보다 넓으면 S10 에 없는 영역을 요구하게 되어 **불가능하다.**
    아무리 정확한 캘리브레이션도 없는 픽셀을 만들지 못한다.

    Args:
        fov_a, fov_b: (hfov_deg, vfov_deg). 같은 종류끼리 비교해야 한다
            (둘 다 fov_effective 로 - fov_nominal 은 배럴 렌즈의 화각을 과소평가한다).

    Returns:
        {"contained": bool, "h_margin": float, "v_margin": float,
         "h_ok": bool, "v_ok": bool}
        margin 은 b - a (도). **양수면 여유**, 음수면 그만큼 모자란다.
    """
    h_a, v_a = float(fov_a[0]), float(fov_a[1])
    h_b, v_b = float(fov_b[0]), float(fov_b[1])
    h_margin = h_b - h_a
    v_margin = v_b - v_a
    return {
        "contained": bool(h_margin >= 0.0 and v_margin >= 0.0),
        "h_margin": h_margin,
        "v_margin": v_margin,
        "h_ok": bool(h_margin >= 0.0),
        "v_ok": bool(v_margin >= 0.0),
    }


# --- f_target 조정 (설계 ③) --------------------------------------------------


def scale_focal(K_target: np.ndarray, scale: float) -> np.ndarray:
    """K_target 의 fx, fy 만 배율을 곱한다 (주점은 고정).

    설계 ③ 에서 목적지 화각을 좁히는 손잡이다. fx 를 키우면 화각이 좁아지고,
    좁아진 만큼 목적지 픽셀이 전부 원본 안에서 값을 가져오게 되어
    **valid pixel ratio 가 올라간다** (검은 영역이 준다).

    공짜는 아니다. 같은 화면을 더 좁은 각도로 채우는 것이므로 **국소 확대가 커진다.**
    두 지표가 반대로 움직이니 하나만 보고 정하면 안 된다.

    주점(cx, cy)을 그대로 두는 이유: 이 연산은 "주점을 중심으로 한 줌" 이어야 한다.
    주점까지 옮기면 화각을 좁히는 것이 아니라 다른 카메라가 된다.
    """
    if scale <= 0:
        raise ValueError(f"배율은 양수여야 한다: {scale}")
    out = np.array(K_target, dtype=np.float64, copy=True)
    out[0, 0] *= scale
    out[1, 1] *= scale
    return out
