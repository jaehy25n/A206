"""remap_metrics - 두 설계의 매핑과 세 지표.

가장 중요한 검사는 **항등 사상**이다. K_src == K_dst, D 가 모두 0 이면 아무것도
변환하지 않는 것이고, 그때 map 은 격자 그대로, valid = 1, stretch = 1 이어야 한다.
여기가 틀리면 나머지 숫자는 전부 의미가 없다.
"""

from __future__ import annotations

import numpy as np
import pytest

from camcal.remap_metrics import (
    build_map_to_distorted,
    build_map_to_pinhole,
    containment,
    local_stretch,
    valid_mask,
    valid_ratio,
)

WIDTH, HEIGHT = 640, 360  # 작게 잡아 테스트를 빠르게 (지표는 크기와 무관하다)

K = np.array([[500.0, 0.0, 320.0], [0.0, 498.0, 180.0], [0.0, 0.0, 1.0]], dtype=np.float64)
ZERO_D = np.zeros(5, dtype=np.float64)
BARREL_D = np.array([-0.25, 0.06, 0.0, 0.0, 0.0], dtype=np.float64)


def identity_grid():
    grid_u, grid_v = np.meshgrid(
        np.arange(WIDTH, dtype=np.float64), np.arange(HEIGHT, dtype=np.float64)
    )
    return grid_u, grid_v


# --- 항등 사상 --------------------------------------------------------------


def test_pinhole_map_is_identity_when_nothing_changes() -> None:
    """설계 ③: K_src == K_target, D_src = 0 -> 맵이 격자 그대로."""
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K, WIDTH, HEIGHT)
    grid_u, grid_v = identity_grid()

    assert map_x.shape == (HEIGHT, WIDTH)
    assert np.allclose(map_x, grid_u, atol=1e-3)
    assert np.allclose(map_y, grid_v, atol=1e-3)


def test_distorted_map_is_identity_when_nothing_changes() -> None:
    """설계 ②: K_src == K_dst, D 가 양쪽 모두 0 -> 맵이 격자 그대로."""
    map_x, map_y = build_map_to_distorted(K, ZERO_D, K, ZERO_D, WIDTH, HEIGHT)
    grid_u, grid_v = identity_grid()

    assert np.allclose(map_x, grid_u, atol=1e-3)
    assert np.allclose(map_y, grid_v, atol=1e-3)


def test_two_designs_agree_when_target_has_no_distortion() -> None:
    """D_dst = 0 이면 설계 ② 함수도 결국 ③ 과 같은 맵을 만든다.

    (그래서 D_target 이 0 이면 K_target = K_luaz 여도 ③ 이다 - README 의 경고)
    """
    a_x, a_y = build_map_to_pinhole(K, BARREL_D, K, WIDTH, HEIGHT)
    b_x, b_y = build_map_to_distorted(K, BARREL_D, K, ZERO_D, WIDTH, HEIGHT)

    assert np.allclose(a_x, b_x, atol=1e-2)
    assert np.allclose(a_y, b_y, atol=1e-2)


def test_identity_gives_valid_one_and_stretch_one() -> None:
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K, WIDTH, HEIGHT)

    assert valid_ratio(map_x, map_y, WIDTH, HEIGHT) == pytest.approx(1.0, abs=0.01)

    mask = valid_mask(map_x, map_y, WIDTH, HEIGHT)
    stretch, summary = local_stretch(map_x, map_y, mask)
    assert summary["median"] == pytest.approx(1.0, abs=1e-6)
    assert summary["p95"] == pytest.approx(1.0, abs=1e-6)
    assert summary["max"] == pytest.approx(1.0, abs=1e-6)
    assert summary["det_median"] == pytest.approx(1.0, abs=1e-6)


# --- valid_ratio ------------------------------------------------------------


def test_valid_ratio_drops_when_target_is_wider() -> None:
    """목적지 초점거리를 낮추면(더 넓게 보면) 원본에 없는 영역이 생긴다."""
    K_wide = K.copy()
    K_wide[0, 0] *= 0.6
    K_wide[1, 1] *= 0.6
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K_wide, WIDTH, HEIGHT)
    assert valid_ratio(map_x, map_y, WIDTH, HEIGHT) < 0.8


def test_valid_ratio_is_one_when_target_is_narrower() -> None:
    """목적지를 더 좁게 잡으면 전부 원본 안에서 가져올 수 있다."""
    K_narrow = K.copy()
    K_narrow[0, 0] *= 1.4
    K_narrow[1, 1] *= 1.4
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K_narrow, WIDTH, HEIGHT)
    assert valid_ratio(map_x, map_y, WIDTH, HEIGHT) == pytest.approx(1.0, abs=1e-6)


def test_nan_is_invalid() -> None:
    map_x = np.full((4, 4), 2.0, dtype=np.float32)
    map_y = np.full((4, 4), 2.0, dtype=np.float32)
    map_x[0, 0] = np.nan
    assert valid_ratio(map_x, map_y, 10, 10) == pytest.approx(15 / 16)


def test_margin_excludes_border() -> None:
    """경계에 정확히 걸친 픽셀은 보간이 반쪽이므로 무효로 센다."""
    map_x = np.array([[0.0, 5.0]], dtype=np.float32)
    map_y = np.array([[5.0, 5.0]], dtype=np.float32)
    assert valid_ratio(map_x, map_y, 10, 10) == pytest.approx(0.5)
    assert valid_ratio(map_x, map_y, 10, 10, margin=0.0) == pytest.approx(1.0)


# --- local_stretch ----------------------------------------------------------


def test_uniform_scale_gives_that_stretch() -> None:
    """목적지 초점거리를 2배로 하면 목적지가 2배 확대된 그림이 된다 -> stretch 2."""
    K_zoom = K.copy()
    K_zoom[0, 0] *= 2.0
    K_zoom[1, 1] *= 2.0
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K_zoom, WIDTH, HEIGHT)
    _stretch, summary = local_stretch(map_x, map_y)

    assert summary["median"] == pytest.approx(4.0, rel=0.02)  # 면적비 = 2 x 2
    assert summary["det_median"] == pytest.approx(0.25, rel=0.02)


def test_barrel_stretches_the_edges_more_than_center() -> None:
    """배럴 왜곡을 펴면 가장자리가 더 늘어난다. 최대 지점도 가장자리여야 한다."""
    map_x, map_y = build_map_to_pinhole(K, BARREL_D, K, WIDTH, HEIGHT)
    mask = valid_mask(map_x, map_y, WIDTH, HEIGHT)
    stretch, summary = local_stretch(map_x, map_y, mask)

    center = stretch[HEIGHT // 2, WIDTH // 2]
    assert summary["max"] > center
    u, v = summary["max_at"]
    near_edge = (
        u < WIDTH * 0.2 or u > WIDTH * 0.8 or v < HEIGHT * 0.2 or v > HEIGHT * 0.8
    )
    assert near_edge, f"최대 stretch 가 가장자리가 아니다: (u,v)=({u},{v})"


def test_stretch_and_det_are_reciprocal() -> None:
    map_x, map_y = build_map_to_pinhole(K, BARREL_D, K, WIDTH, HEIGHT)
    _stretch, summary = local_stretch(map_x, map_y)
    assert summary["median"] * summary["det_median"] == pytest.approx(1.0, rel=0.02)


def test_empty_mask_returns_none_summary() -> None:
    map_x, map_y = build_map_to_pinhole(K, ZERO_D, K, WIDTH, HEIGHT)
    _stretch, summary = local_stretch(map_x, map_y, np.zeros_like(map_x, dtype=bool))
    assert summary["n_used"] == 0
    assert summary["median"] is None


# --- containment ------------------------------------------------------------


def test_contained_with_margin() -> None:
    out = containment((60.0, 35.0), (65.0, 38.0))
    assert out["contained"] is True
    assert out["h_margin"] == pytest.approx(5.0)
    assert out["v_margin"] == pytest.approx(3.0)


def test_not_contained_when_wider() -> None:
    out = containment((70.0, 35.0), (65.0, 38.0))
    assert out["contained"] is False
    assert out["h_ok"] is False
    assert out["v_ok"] is True
    assert out["h_margin"] == pytest.approx(-5.0)


# --- f_target 조정 (설계 ③) --------------------------------------------------


def test_scale_focal_touches_only_fx_fy() -> None:
    """주점을 옮기면 화각을 좁히는 것이 아니라 다른 카메라가 된다."""
    from camcal.remap_metrics import scale_focal

    scaled = scale_focal(K, 1.10)
    assert scaled[0, 0] == pytest.approx(K[0, 0] * 1.10)
    assert scaled[1, 1] == pytest.approx(K[1, 1] * 1.10)
    assert scaled[0, 2] == K[0, 2]
    assert scaled[1, 2] == K[1, 2]
    assert K[0, 0] == 500.0, "원본이 바뀌었다 (복사하지 않았다)"


@pytest.mark.parametrize("scale", [0.0, -1.0])
def test_scale_focal_rejects_nonpositive(scale: float) -> None:
    from camcal.remap_metrics import scale_focal

    with pytest.raises(ValueError):
        scale_focal(K, scale)


def test_raising_f_target_raises_valid_and_stretch_together() -> None:
    """f_target 을 올리면 valid 는 오르고 stretch 도 **같이** 오른다.

    둘이 반대로 움직인다는 것이 이 손잡이의 핵심 성질이다. 검은 영역을 줄이는
    대가로 확대를 받는 거래이므로, 하나만 보고 올리면 안 된다.
    (2026-09-21 실측에서도 배율 1.00 -> 1.10 에 valid 93.59% -> 98.77%,
    stretch 95p 1.2346 -> 1.4955 로 같이 올랐다)
    """
    from camcal.remap_metrics import scale_focal

    K_wide = K.copy()
    K_wide[0, 0] *= 0.7
    K_wide[1, 1] *= 0.7  # 원본보다 넓은 target -> 검은 영역이 생긴다

    valids, stretches = [], []
    for scale in (1.0, 1.2, 1.4):
        K_target = scale_focal(K_wide, scale)
        map_x, map_y = build_map_to_pinhole(K, BARREL_D, K_target, WIDTH, HEIGHT)
        mask = valid_mask(map_x, map_y, WIDTH, HEIGHT)
        _s, summary = local_stretch(map_x, map_y, mask)
        valids.append(valid_ratio(map_x, map_y, WIDTH, HEIGHT))
        stretches.append(summary["p95"])

    assert valids[0] < valids[1] <= valids[2], f"valid 가 올라가지 않았다: {valids}"
    assert stretches[0] < stretches[1] < stretches[2], f"stretch 가 같이 오르지 않았다: {stretches}"
