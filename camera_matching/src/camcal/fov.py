"""화각 계산. **이름 두 개만 쓴다** (README "FOV 정의").

    fov_nominal(K, W, H)              K 와 이미지 크기만으로. 왜곡 무시
    fov_effective(K, D, W, H, alpha)  왜곡을 편 뒤 alpha 로 크롭한 유효 화각

다른 이름의 FOV 함수를 만들지 않는다. 1회차에서 같은 데이터로 64.3 도와 61.0 도가
따로 나온 원인이 이 구분이 없어서였다 - 한쪽은 원본 K 로, 다른 쪽은 왜곡 보정 후
K' 로 잰 값이었는데 둘 다 그냥 "화각"이라고 불렀다.

두 값은 **다른 것이 맞다.** 어느 쪽을 쓸지는 질문에 달려 있다.
    - "센서에 들어온 빛의 각도 범위는?"           -> fov_nominal
    - "왜곡을 편 뒤 쓸 수 있는 화면은 몇 도?"      -> fov_effective
    - "LUAZ 화각이 S10 안에 들어오나?" (게이트)   -> fov_effective 끼리 비교
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def fov_nominal(K: np.ndarray, width: int, height: int) -> tuple[float, float]:
    """K 와 이미지 크기만으로 구한 화각 (도).

        HFOV = 2 * atan(W / (2 * fx))
        VFOV = 2 * atan(H / (2 * fy))

    왜곡(D)은 들어가지 않는다. 주점이 중심에서 벗어나 있어도 이 식은 그것을
    반영하지 않는다 - 대칭이라고 가정한 값이다.

    Returns:
        (hfov_deg, vfov_deg)
    """
    K = np.asarray(K, dtype=np.float64)
    fx = float(K[0, 0])
    fy = float(K[1, 1])
    if fx <= 0 or fy <= 0:
        raise ValueError(f"fx, fy 는 양수여야 한다: fx={fx}, fy={fy}")

    hfov = 2.0 * math.degrees(math.atan(width / (2.0 * fx)))
    vfov = 2.0 * math.degrees(math.atan(height / (2.0 * fy)))
    return (hfov, vfov)


def fov_effective(
    K: np.ndarray,
    D: np.ndarray,
    width: int,
    height: int,
    alpha: float = 0.0,
) -> tuple[float, float, np.ndarray]:
    """왜곡을 편 뒤 남는 유효 화각 (도)와 그때의 K'.

    getOptimalNewCameraMatrix(alpha) 가 주는 K' 로 fov_nominal 을 다시 계산한다.

    alpha 의 의미:
        0 = 검은 여백이 하나도 없게 잘라낸다 (alpha=1 보다 화각이 좁다)
        1 = 원본 픽셀을 다 남긴다 (모서리에 검은 영역이 생긴다)

    기본값 0 을 쓰는 이유: "실제로 쓸 수 있는 화면"이 궁금한 것이기 때문이다.
    검은 여백은 모델에 넣을 수 없다.

    **fov_nominal 과의 대소는 왜곡 부호에 따라 뒤집힌다** (2026-09-18 측정).
    fx=1527, 1920x1080 기준:
        배럴 k1=-0.25  -> effective 71.7 도 > nominal 64.3 도
        핀쿠션 k1=+0.25 -> effective 59.2 도 < nominal 64.3 도
    배럴 렌즈는 가장자리를 안쪽으로 눌러 담으므로, 왜곡을 펴면 nominal 이
    말하는 것보다 실제로 더 넓은 각도를 담고 있었다는 것이 드러난다.
    그래서 "LUAZ 화각이 S10 안에 들어오나" 게이트는 **양쪽 다 fov_effective 로**
    비교해야 한다. nominal 로 비교하면 배럴 렌즈의 화각을 과소평가한다.

    Returns:
        (hfov_deg, vfov_deg, K_prime)
    """
    K = np.asarray(K, dtype=np.float64)
    D = np.asarray(D, dtype=np.float64).ravel()
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha 는 0~1 이다: {alpha}")

    K_prime, _roi = cv2.getOptimalNewCameraMatrix(
        K, D, (width, height), alpha, (width, height)
    )
    K_prime = np.asarray(K_prime, dtype=np.float64)
    hfov, vfov = fov_nominal(K_prime, width, height)
    return (hfov, vfov, K_prime)


def is_degenerate_k_prime(
    K: np.ndarray, K_prime: np.ndarray, D: np.ndarray, tol: float = 1e-6
) -> bool:
    """getOptimalNewCameraMatrix 가 사실상 아무것도 하지 않은 경우인지.

    왜곡이 아주 강하면(관측: k1 = -0.40) OpenCV 가 유효 영역 계산을 포기하고
    **원본 K 를 그대로 돌려준다.** 그러면 fov_effective 가 fov_nominal 과 같은
    값이 되는데, 이것은 "왜곡이 없다"는 뜻이 아니라 "계산하지 못했다"는 뜻이다.
    값만 보면 구분되지 않으므로 여기서 잡아 경고로 올린다.
    """
    D = np.asarray(D, dtype=np.float64).ravel()
    if not np.any(np.abs(D) > 0):
        return False  # D = 0 이면 같은 것이 정상이다
    return bool(np.allclose(np.asarray(K), np.asarray(K_prime), rtol=0.0, atol=tol))
