"""체커보드 코너 검출.

촬영 중에는 한 프레임당 검출을 **한 번만** 한다. 미리보기에서 성공한 프레임을
그대로 저장하므로, 화면에서 본 코너와 저장된 PNG 의 코너는 같다.
(저장은 PNG 무손실이라 이후 캘리브레이션 단계에서 다시 검출해도 같은 입력 -> 같은 결과다.
그래서 코너 좌표 자체는 meta.json 에 넣지 않고, 검출 여부와 코너 수만 기록한다.)

반환하는 코너는 shape (N, 1, 2) float32, 픽셀 좌표 (u, v) 로 **정규화해서** 준다.
findChessboardCorners 의 출력 모양은 OpenCV 버전에 따라 다르다
(4.x 는 (N,1,2), 5.0 은 (N,2)). 아래 단계들이 버전에 따라 갈리지 않도록
여기서 한 번 맞춰 둔다. calibrateCamera 는 (N,1,2) 를 그대로 받는다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .board import BoardSpec
from .constants import (
    FIND_CORNERS_FLAGS,
    OVERLAY_CORNER_RADIUS,
    SUBPIX_CRITERIA,
    SUBPIX_WINDOW,
    SUBPIX_ZERO_ZONE,
)


def to_gray(img: np.ndarray) -> np.ndarray:
    """BGR 이든 흑백이든 단채널로 맞춘다. 그 외 채널 수는 예외."""
    if img.ndim == 2:
        return img
    if img.ndim == 3 and img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    raise ValueError(f"지원하지 않는 이미지 형태: shape={img.shape}")


def find_corners(
    img: np.ndarray, spec: BoardSpec
) -> tuple[bool, np.ndarray | None]:
    """체커보드 내부 코너를 찾는다.

    Args:
        img: BGR 또는 흑백 프레임.
        spec: 보드 규격. spec.pattern_size 로 찾는다.

    Returns:
        (ok, corners). ok 가 True 면 corners 는 shape (N, 1, 2) float32,
        N == spec.n_corners 가 보장된다. 실패면 (False, None).

    검출된 코너 수가 규격과 다르면 **성공으로 치지 않는다.** OpenCV 는
    패턴 전체를 찾았을 때만 True 를 주지만, 여기서 한 번 더 확인해서
    규격 불일치(board.yaml 을 잘못 고친 경우)가 조용히 지나가지 않게 한다.
    """
    gray = to_gray(img)
    ok, corners = cv2.findChessboardCorners(
        gray, spec.pattern_size, flags=FIND_CORNERS_FLAGS
    )
    if not ok or corners is None:
        return (False, None)

    corners = np.asarray(corners, dtype=np.float32).reshape(-1, 1, 2)
    if corners.shape[0] != spec.n_corners:
        raise RuntimeError(
            f"검출 코너 수가 보드 규격과 다르다: {corners.shape[0]} != {spec.n_corners} "
            f"(spec={spec.pattern_size}). config/board.yaml 의 cols/rows 를 확인한다"
        )

    refined = cv2.cornerSubPix(
        gray,
        corners,
        SUBPIX_WINDOW,
        SUBPIX_ZERO_ZONE,
        SUBPIX_CRITERIA,
    )
    return (True, np.asarray(refined, dtype=np.float32).reshape(-1, 1, 2))


def draw_corners(
    img: np.ndarray, spec: BoardSpec, corners: np.ndarray | None, ok: bool
) -> np.ndarray:
    """미리보기용 오버레이. 원본을 복사해서 그린다.

    검출 성공이면 OpenCV 기본 색 선(코너 순서가 보인다)을,
    실패면 아무것도 그리지 않는다.
    """
    canvas = img.copy()
    if ok and corners is not None:
        cv2.drawChessboardCorners(canvas, spec.pattern_size, corners, ok)
    return canvas


def corner_span_px(corners: np.ndarray) -> tuple[float, float]:
    """코너 바운딩 박스 크기 (width, height) 픽셀.

    보드가 화면에서 얼마나 큰지 = 대략 얼마나 가까운지의 척도다.
    거리 다양성(근/중/원)을 눈으로 확인할 때 쓴다.
    """
    pts = np.asarray(corners, dtype=np.float64).reshape(-1, 2)
    span = pts.max(axis=0) - pts.min(axis=0)
    return (float(span[0]), float(span[1]))


#: 오버레이 코너 반경을 쓰는 쪽(capture 도구)이 import 하기 쉽게 재수출.
__all__ = [
    "to_gray",
    "find_corners",
    "draw_corners",
    "corner_span_px",
    "OVERLAY_CORNER_RADIUS",
]
