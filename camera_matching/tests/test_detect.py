"""검출기 - 합성 체커보드로 성공률과 서브픽셀 정확도를 확인한다.

하드웨어 없이 검증 가능한 부분이 여기다. 실제 촬영 이미지에는 블러·노이즈·
원근이 섞이지만, 합성 이미지에서조차 틀리면 검출기 쪽 문제다.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.detect import corner_span_px, draw_corners, find_corners, to_gray

from conftest import render_checkerboard

#: 정면 합성 이미지에서 허용하는 코너 위치 오차 (픽셀).
#: 서브픽셀 보정이 동작하면 0.1 px 수준으로 들어온다. 0.5 는 넉넉한 상한이다.
MAX_CORNER_ERROR_PX = 0.5


def match_errors(detected: np.ndarray, expected: np.ndarray) -> np.ndarray:
    """검출 코너와 참값을 최근접으로 짝지어 거리 배열을 준다.

    검출 순서는 보드 방향에 따라 뒤집힐 수 있으므로 순서를 가정하지 않는다.
    """
    pts = np.asarray(detected, dtype=np.float64).reshape(-1, 2)
    dists = np.linalg.norm(pts[:, None, :] - expected[None, :, :], axis=2)
    nearest = dists.argmin(axis=1)
    assert len(set(nearest.tolist())) == len(pts), "서로 다른 코너가 같은 참값에 매칭됐다"
    return dists[np.arange(len(pts)), nearest]


def test_detects_synthetic_board(spec: BoardSpec, checkerboard) -> None:
    img, expected = checkerboard
    ok, corners = find_corners(img, spec)
    assert ok is True
    assert corners is not None
    assert corners.shape == (spec.n_corners, 1, 2)
    assert corners.dtype == np.float32


def test_subpixel_accuracy(spec: BoardSpec, checkerboard) -> None:
    img, expected = checkerboard
    ok, corners = find_corners(img, spec)
    assert ok
    errors = match_errors(corners, expected)
    assert errors.max() < MAX_CORNER_ERROR_PX, f"최대 오차 {errors.max():.3f} px"


def test_detects_grayscale_input(spec: BoardSpec, checkerboard) -> None:
    img, _ = checkerboard
    ok, corners = find_corners(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), spec)
    assert ok and corners is not None


@pytest.mark.parametrize("square_px, margin_px", [(40, 60), (60, 90), (25, 40)])
def test_detects_at_several_scales(spec: BoardSpec, square_px: int, margin_px: int) -> None:
    """보드가 화면에서 크든 작든 찾아야 근/중/원 촬영이 가능하다."""
    img, expected = render_checkerboard(spec, square_px=square_px, margin_px=margin_px)
    ok, corners = find_corners(img, spec)
    assert ok, f"square_px={square_px} 에서 검출 실패"
    assert match_errors(corners, expected).max() < MAX_CORNER_ERROR_PX


def test_detects_under_blur_and_noise(spec: BoardSpec, checkerboard) -> None:
    """실제 촬영에 가까운 열화. 여기서 실패하면 현장에서도 실패한다."""
    img, expected = checkerboard
    blurred = cv2.GaussianBlur(img, (5, 5), 1.2)
    rng = np.random.default_rng(1)
    noisy = np.clip(
        blurred.astype(np.int16) + rng.normal(0, 4, blurred.shape).astype(np.int16), 0, 255
    ).astype(np.uint8)

    ok, corners = find_corners(noisy, spec)
    assert ok
    assert match_errors(corners, expected).max() < 1.0


def test_no_board_returns_false(spec: BoardSpec) -> None:
    blank = np.full((720, 1280, 3), 200, dtype=np.uint8)
    ok, corners = find_corners(blank, spec)
    assert ok is False
    assert corners is None


def test_wrong_pattern_size_not_detected(checkerboard) -> None:
    """board.yaml 을 잘못 고치면 '찾긴 찾았는데 다른 보드'가 되면 안 된다."""
    img, _ = checkerboard
    other = BoardSpec(cols=7, rows=5, square_mm=25.0, square_mm_measured=True)
    ok, corners = find_corners(img, other)
    assert ok is False
    assert corners is None


def test_corner_span_matches_board_extent(spec: BoardSpec) -> None:
    """span 은 보드가 화면에서 차지하는 크기 = 대략의 거리 척도."""
    square_px = 60
    img, expected = render_checkerboard(spec, square_px=square_px, margin_px=90)
    ok, corners = find_corners(img, spec)
    assert ok
    span_w, span_h = corner_span_px(corners)
    assert span_w == pytest.approx((spec.cols - 1) * square_px, abs=2.0)
    assert span_h == pytest.approx((spec.rows - 1) * square_px, abs=2.0)


def test_draw_corners_does_not_modify_input(spec: BoardSpec, checkerboard) -> None:
    img, _ = checkerboard
    ok, corners = find_corners(img, spec)
    before = img.copy()
    canvas = draw_corners(img, spec, corners, ok)
    assert np.array_equal(img, before), "원본 프레임에 그렸다 - 저장본이 오염된다"
    assert not np.array_equal(canvas, img)


def test_draw_corners_on_failure_returns_copy(spec: BoardSpec) -> None:
    blank = np.full((480, 640, 3), 200, dtype=np.uint8)
    canvas = draw_corners(blank, spec, None, False)
    assert np.array_equal(canvas, blank)
    assert canvas is not blank


def test_to_gray_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError):
        to_gray(np.zeros((10, 10, 2), dtype=np.uint8))
