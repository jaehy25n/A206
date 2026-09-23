"""라이브 비교의 좌표 규약.

여기서 한 번 틀렸다 (2026-09-21): 맵을 **원본 해상도** 기준으로 만들어 놓고
축소본에 적용했다. 그러면 좌표가 이미지 밖으로 나가 내용이 좌상단 1/3 에 뭉치고
나머지가 검게 된다. 지표로는 안 보이고 화면을 봐야 보인다.

규약: `build_view_map(source_size=S)` 가 만든 맵은 **크기가 S 인 이미지**에만 쓴다.
"""

from __future__ import annotations

import numpy as np
import pytest

from s10_server.live import VIEW_HEIGHT, VIEW_WIDTH, build_view_map, scale_intrinsics
from camcal.target_space import TargetSpace

from test_target_space import make_reference

FULL = (1920, 1080)
PREVIEW = (320, 180)


def make_intrinsics(fx: float = 1600.0, k1: float = -0.1) -> dict:
    K = np.array([[fx, 0.0, 960.0], [0.0, fx, 540.0], [0.0, 0.0, 1.0]])
    return {
        "camera": "cam",
        "resolution": list(FULL),
        "K": K.tolist(),
        "D": [k1, 0.0, 0.0, 0.0, 0.0],
    }


@pytest.fixture
def target() -> TargetSpace:
    return TargetSpace.from_intrinsics(make_reference(), design=3, f_target_scale=1.10)


# --- scale_intrinsics --------------------------------------------------------


def test_scale_intrinsics_scales_all_four() -> None:
    """이미지를 s 배로 줄이면 fx, fy, cx, cy 가 전부 s 배가 된다."""
    K = np.array([[1600.0, 0.0, 960.0], [0.0, 1590.0, 540.0], [0.0, 0.0, 1.0]])
    out = scale_intrinsics(K, 1 / 6)

    assert out[0, 0] == pytest.approx(1600.0 / 6)
    assert out[1, 1] == pytest.approx(1590.0 / 6)
    assert out[0, 2] == pytest.approx(960.0 / 6)
    assert out[1, 2] == pytest.approx(540.0 / 6)
    assert out[2, 2] == 1.0
    assert K[0, 0] == 1600.0, "원본이 바뀌었다"


def test_scaling_preserves_field_of_view() -> None:
    """축소는 화각을 바꾸지 않는다. 바뀌면 K 를 잘못 줄인 것이다."""
    from camcal.fov import fov_nominal

    K = np.array([[1600.0, 0.0, 960.0], [0.0, 1600.0, 540.0], [0.0, 0.0, 1.0]])
    full = fov_nominal(K, FULL[0], FULL[1])
    small = fov_nominal(scale_intrinsics(K, 1 / 6), PREVIEW[0], PREVIEW[1])

    assert small[0] == pytest.approx(full[0], abs=1e-9)
    assert small[1] == pytest.approx(full[1], abs=1e-9)


# --- build_view_map: 좌표가 어느 공간에 있는가 --------------------------------


def test_map_coordinates_live_in_the_source_size(target: TargetSpace) -> None:
    """맵이 내놓는 좌표는 **source_size** 안에 있어야 한다.

    이 규약이 깨진 채로 축소본에 적용해 화면이 망가졌던 적이 있다.
    """
    map_x, map_y = build_view_map(make_intrinsics(), target, VIEW_WIDTH, VIEW_HEIGHT, FULL)
    assert map_x.shape == (VIEW_HEIGHT, VIEW_WIDTH)

    inside = (map_x > 0) & (map_x < FULL[0]) & (map_y > 0) & (map_y < FULL[1])
    assert inside.mean() > 0.9, "원본 해상도 좌표가 아니다"
    assert map_x[inside].max() > FULL[0] * 0.5, "좌표가 너무 작다 (축소 스케일이 섞였다)"


def test_preview_map_uses_preview_coordinates(target: TargetSpace) -> None:
    map_x, map_y = build_view_map(
        make_intrinsics(), target, VIEW_WIDTH, VIEW_HEIGHT, PREVIEW
    )
    inside = (map_x > 0) & (map_x < PREVIEW[0]) & (map_y > 0) & (map_y < PREVIEW[1])
    assert inside.mean() > 0.9
    assert map_x[inside].max() < PREVIEW[0], "프리뷰 크기를 넘는 좌표가 나왔다"


def test_full_and_preview_maps_agree_after_scaling(target: TargetSpace) -> None:
    """같은 장면이므로 두 맵은 배율만 다르고 가리키는 곳은 같아야 한다."""
    intrinsics = make_intrinsics()
    full_x, full_y = build_view_map(intrinsics, target, VIEW_WIDTH, VIEW_HEIGHT, FULL)
    prev_x, prev_y = build_view_map(intrinsics, target, VIEW_WIDTH, VIEW_HEIGHT, PREVIEW)

    scale = PREVIEW[0] / FULL[0]
    ok = np.isfinite(full_x) & np.isfinite(prev_x)
    assert np.allclose(full_x[ok] * scale, prev_x[ok], atol=0.5)
    assert np.allclose(full_y[ok] * scale, prev_y[ok], atol=0.5)


def test_remapping_the_wrong_size_leaves_black(target: TargetSpace) -> None:
    """규약을 어기면 어떻게 망가지는지 고정해 둔다 (실제로 겪은 증상)."""
    import cv2

    intrinsics = make_intrinsics()
    map_x, map_y = build_view_map(intrinsics, target, VIEW_WIDTH, VIEW_HEIGHT, FULL)

    rng = np.random.default_rng(0)
    full = rng.integers(40, 255, size=(FULL[1], FULL[0], 3), dtype=np.uint8)
    shrunk = cv2.resize(full, (VIEW_WIDTH, VIEW_HEIGHT))

    right = cv2.remap(full, map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    wrong = cv2.remap(shrunk, map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    black_right = (right.max(axis=2) < 8).mean()
    black_wrong = (wrong.max(axis=2) < 8).mean()
    assert black_right < 0.05, "맞게 썼는데도 검은 영역이 크다"
    assert black_wrong > 0.5, "틀리게 써도 멀쩡하면 이 테스트가 무의미하다"
