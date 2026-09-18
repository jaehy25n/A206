"""테스트 공용 픽스처와 합성 체커보드 생성기.

하드웨어 없이 검출기를 검증하려면 **정답을 아는 이미지**가 필요하다.
cv2 로 직접 그린 체커보드는 코너의 참값 좌표를 알고 있으므로,
검출 성공 여부뿐 아니라 서브픽셀 정확도까지 잴 수 있다.
"""

from __future__ import annotations

import numpy as np
import pytest

from camcal.board import BoardSpec


@pytest.fixture
def spec() -> BoardSpec:
    """테스트 표준 보드. 실제 config/board.yaml 과 같은 9x6."""
    return BoardSpec(cols=9, rows=6, square_mm=25.0, square_mm_measured=True, note="test")


def render_checkerboard(
    spec: BoardSpec,
    square_px: int = 60,
    margin_px: int = 90,
) -> tuple[np.ndarray, np.ndarray]:
    """정면에서 본 체커보드 이미지와 내부 코너 참값을 만든다.

    내부 코너가 cols x rows 개가 되려면 칸은 (cols+1) x (rows+1) 개다.
    보드 둘레의 흰 여백(margin)은 findChessboardCorners 에 필수다 -
    여백 없이 이미지 가장자리에 붙으면 바깥 사각형을 인식하지 못한다.

    픽셀 좌표 규약: OpenCV 에서 정수 좌표 u=k 는 픽셀 k 의 **중심**이다.
    따라서 픽셀 k-1 과 k 사이의 경계(= 체커보드 코너)는 k - 0.5 에 있다.
    이 0.5 를 빼지 않으면 모든 코너가 (0.5, 0.5) 만큼 어긋나 보이고,
    검출기가 정확한데도 오차 sqrt(2)/2 = 0.707 px 이 일정하게 나온다.

    Returns:
        (image BGR uint8, expected_corners shape (N, 2) float64 픽셀 (u, v))
        expected_corners 는 행 우선 순서지만, 검출 결과와 순서가 같다고
        가정하지 않는다 (테스트에서 최근접 매칭으로 비교한다).
    """
    n_sq_x = spec.cols + 1
    n_sq_y = spec.rows + 1
    width = n_sq_x * square_px + 2 * margin_px
    height = n_sq_y * square_px + 2 * margin_px

    img = np.full((height, width, 3), 255, dtype=np.uint8)
    for iy in range(n_sq_y):
        for ix in range(n_sq_x):
            if (ix + iy) % 2 == 0:
                continue
            y0 = margin_px + iy * square_px
            x0 = margin_px + ix * square_px
            img[y0 : y0 + square_px, x0 : x0 + square_px] = 0

    corners = np.zeros((spec.n_corners, 2), dtype=np.float64)
    k = 0
    for row in range(spec.rows):
        for col in range(spec.cols):
            corners[k, 0] = margin_px + (col + 1) * square_px - 0.5  # u
            corners[k, 1] = margin_px + (row + 1) * square_px - 0.5  # v
            k += 1
    return img, corners


@pytest.fixture
def checkerboard(spec: BoardSpec):
    """(image, expected_corners) 쌍."""
    return render_checkerboard(spec)
