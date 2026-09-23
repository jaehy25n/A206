"""BoardSpec - 월드 좌표 X_w 생성과 규격 검증."""

from __future__ import annotations

import numpy as np
import pytest

from camcal.board import BoardSpec

PROJECT_BOARD_YAML = "config/board.yaml"


def test_object_points_count_and_shape(spec: BoardSpec) -> None:
    pts = spec.object_points()
    assert pts.shape == (spec.cols * spec.rows, 3)
    assert pts.dtype == np.float32
    assert spec.n_corners == 54


def test_object_points_are_planar(spec: BoardSpec) -> None:
    """Z_w = 0 평면. Zhang 방법의 전제이고, 깨지면 호모그래피가 성립하지 않는다."""
    pts = spec.object_points()
    assert np.all(pts[:, 2] == 0.0)


def test_object_points_spacing_is_square_mm(spec: BoardSpec) -> None:
    pts = spec.object_points().reshape(spec.rows, spec.cols, 3)
    dx = np.diff(pts[:, :, 0], axis=1)
    dy = np.diff(pts[:, :, 1], axis=0)
    assert np.allclose(dx, spec.square_mm)
    assert np.allclose(dy, spec.square_mm)


def test_object_points_row_major_order(spec: BoardSpec) -> None:
    """OpenCV 검출 순서(행 우선, 행 안에서 x 증가)와 같아야 대응이 맞는다."""
    pts = spec.object_points()
    assert pts[0].tolist() == [0.0, 0.0, 0.0]
    assert pts[1].tolist() == [spec.square_mm, 0.0, 0.0]
    assert pts[spec.cols].tolist() == [0.0, spec.square_mm, 0.0]


def test_pattern_size_is_cols_rows(spec: BoardSpec) -> None:
    assert spec.pattern_size == (spec.cols, spec.rows)


def test_square_scaling(spec: BoardSpec) -> None:
    """square_mm 은 X_w 전체에 곱해지는 배율이다 (t 의 단위를 정한다)."""
    doubled = BoardSpec(spec.cols, spec.rows, spec.square_mm * 2, True)
    assert np.allclose(doubled.object_points(), spec.object_points() * 2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cols": 1, "rows": 6, "square_mm": 25.0},   # 코너가 너무 적다
        {"cols": 9, "rows": 1, "square_mm": 25.0},
        {"cols": 6, "rows": 6, "square_mm": 25.0},   # 정사각 배치 = 방향 모호
        {"cols": 9, "rows": 6, "square_mm": 0.0},    # 크기 없음
        {"cols": 9, "rows": 6, "square_mm": -25.0},
    ],
)
def test_invalid_specs_raise(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        BoardSpec(**kwargs)


def test_dict_round_trip(spec: BoardSpec) -> None:
    assert BoardSpec.from_dict(spec.to_dict()) == spec


def test_from_dict_ignores_unknown_keys(spec: BoardSpec) -> None:
    """옛 meta.json 에 없던 필드가 생겨도 읽기가 깨지지 않는다."""
    data = spec.to_dict() | {"unknown_field": 1}
    assert BoardSpec.from_dict(data) == spec


def test_project_board_yaml_loads() -> None:
    """실제 config/board.yaml 이 읽히고 9x6 / 25.0mm 인지 확인한다.

    보드를 바꾸면 이 테스트가 먼저 깨진다. 그것이 목적이다 - 보드 교체는
    이전 세션과 새 세션을 섞을 수 없게 만드는 변경이므로 조용히 지나가면 안 된다.
    """
    board = BoardSpec.from_yaml(PROJECT_BOARD_YAML)
    assert board.pattern_size == (9, 6)
    assert board.square_mm == 25.0


def test_project_board_square_is_confirmed() -> None:
    """square_mm_measured 가 false 면 촬영 도구가 시작하지 않는다 (종료 코드 2).

    2026-09-18 사용자가 25.0 mm 를 보장해 true 로 두었다. 보드를 바꾸면
    다시 재고 false 로 되돌린다.
    """
    board = BoardSpec.from_yaml(PROJECT_BOARD_YAML)
    assert board.square_mm_measured is True


def test_from_yaml_requires_board_key(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("cols: 9\n", encoding="utf-8")
    with pytest.raises(ValueError):
        BoardSpec.from_yaml(path)
