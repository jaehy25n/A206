"""Coverage - 픽셀 (u, v) → 셀 매핑과 누적."""

from __future__ import annotations

import numpy as np
import pytest

from camcal.coverage import Coverage

SIZE = (1920, 1080)  # (width, height)


@pytest.fixture
def cov() -> Coverage:
    return Coverage(SIZE, (3, 3))


@pytest.mark.parametrize(
    "u, v, cell",
    [
        (0, 0, (0, 0)),             # 좌상 구석
        (639.9, 359.9, (0, 0)),     # 첫 셀의 끝 바로 앞
        (640, 360, (1, 1)),         # 경계는 다음 셀에 속한다 (반열림 구간)
        (1279.9, 719.9, (1, 1)),
        (1280, 720, (2, 2)),
        (1919, 1079, (2, 2)),       # 마지막 유효 픽셀
        (0, 1079, (0, 2)),          # 좌하
        (1919, 0, (2, 0)),          # 우상
    ],
)
def test_cell_boundaries(cov: Coverage, u: float, v: float, cell: tuple[int, int]) -> None:
    assert cov.cell_of(u, v) == cell


@pytest.mark.parametrize("u, v", [(1920, 1080), (5000, 5000), (-1, -1), (-0.3, 3.0)])
def test_out_of_range_is_clamped(cov: Coverage, u: float, v: float) -> None:
    """cornerSubPix 가 경계를 살짝 넘는 값을 줘도 정상 프레임을 버리지 않는다."""
    col, row = cov.cell_of(u, v)
    assert 0 <= col <= 2 and 0 <= row <= 2


def test_add_counts_cell_once_per_frame(cov: Coverage) -> None:
    """한 프레임이 같은 셀을 여러 코너로 덮어도 카운트는 1만 오른다."""
    corners = np.array([[10, 10], [20, 20], [30, 30]], dtype=np.float32)
    cells = cov.add(corners)
    assert cells == {(0, 0)}
    assert cov.counts[0, 0] == 1
    assert cov.n_frames == 1


def test_add_accepts_opencv_shape(cov: Coverage) -> None:
    """검출기가 주는 (N, 1, 2) 모양을 그대로 받는다."""
    corners = np.array([[[10, 10]], [[1900, 1000]]], dtype=np.float32)
    assert cov.add(corners) == {(0, 0), (2, 2)}


def test_ratio_and_empty_cells(cov: Coverage) -> None:
    assert cov.ratio() == 0.0
    assert len(cov.empty_cells()) == 9

    cov.add(np.array([[10, 10], [1900, 1000]], dtype=np.float32))
    assert cov.ratio() == pytest.approx(2 / 9)
    assert (0, 0) not in cov.empty_cells()
    assert (2, 2) not in cov.empty_cells()
    assert len(cov.empty_cells()) == 7


def test_full_coverage(cov: Coverage) -> None:
    centers = np.array(
        [[(c + 0.5) * 640, (r + 0.5) * 360] for r in range(3) for c in range(3)],
        dtype=np.float32,
    )
    cov.add(centers)
    assert cov.ratio() == 1.0
    assert cov.empty_cells() == []
    assert cov.empty_labels() == []


def test_labels_are_ascii_for_overlay(cov: Coverage) -> None:
    """미리보기 창은 cv2.putText 로 그리므로 한글이 들어가면 '???' 가 된다."""
    for label in cov.empty_labels():
        assert label.isascii()
    assert cov.label((0, 0)) == "TL"
    assert cov.label((1, 1)) == "C"
    assert cov.label((0, 0), korean=True) == "좌상"


def test_non_3x3_grid_uses_coordinates() -> None:
    cov = Coverage(SIZE, (4, 2))
    assert cov.n_cells == 8
    assert cov.label((3, 1)) == "(3,1)"
    assert cov.cell_of(1919, 1079) == (3, 1)


def test_to_dict_shape(cov: Coverage) -> None:
    cov.add(np.array([[10, 10]], dtype=np.float32))
    data = cov.to_dict()
    assert data["grid"] == [3, 3]
    assert data["image_size"] == [1920, 1080]
    assert data["n_frames"] == 1
    assert len(data["counts"]) == 3 and len(data["counts"][0]) == 3
    assert data["counts"][0][0] == 1
    assert data["ratio"] == pytest.approx(1 / 9)


@pytest.mark.parametrize("size", [(0, 1080), (1920, 0), (-1, 100)])
def test_invalid_image_size(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        Coverage(size)
