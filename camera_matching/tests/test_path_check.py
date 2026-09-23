"""path_check - 두 촬영 경로의 배율 비교."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.detect import find_corners
from path_check import RATIO_OK_PCT, main, mean_adjacent_spacing

from conftest import render_checkerboard


def write_board(tmp_path, spec: BoardSpec, square_px: int, name: str):
    """지정 배율의 체커보드를 1920x1080 안에 그려 PNG 로 쓴다."""
    frame = np.full((1080, 1920, 3), 220, dtype=np.uint8)
    patch, _ = render_checkerboard(spec, square_px=square_px, margin_px=30)
    h, w = patch.shape[:2]
    y = (1080 - h) // 2
    x = (1920 - w) // 2
    frame[y : y + h, x : x + w] = patch
    path = tmp_path / name
    assert cv2.imwrite(str(path), frame)
    return path


def test_spacing_equals_square_size(spec: BoardSpec) -> None:
    """정면 합성 보드에서 인접 코너 간격은 곧 칸 크기다."""
    img, _ = render_checkerboard(spec, square_px=60, margin_px=90)
    ok, corners = find_corners(img, spec)
    assert ok
    assert mean_adjacent_spacing(corners, spec) == pytest.approx(60.0, abs=0.05)


def test_identical_images_pass(tmp_path, spec: BoardSpec, capsys) -> None:
    a = write_board(tmp_path, spec, 60, "a.png")
    b = write_board(tmp_path, spec, 60, "b.png")
    code = main([str(a), str(b), "--board", str(_board_yaml(tmp_path, spec))])
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_scale_difference_is_flagged(tmp_path, spec: BoardSpec, capsys) -> None:
    """5% 크롭 차이 = 경로가 다르다. 눈으로는 잘 안 보이지만 K 는 5% 틀어진다."""
    a = write_board(tmp_path, spec, 63, "a.png")   # 5% 크게
    b = write_board(tmp_path, spec, 60, "b.png")
    code = main([str(a), str(b), "--board", str(_board_yaml(tmp_path, spec))])
    out = capsys.readouterr().out
    assert code == 2
    assert "경고" in out and "경로가 다르다" in out
    assert "5.0" in out  # 차이 %


def test_resolution_mismatch_stops(tmp_path, spec: BoardSpec, capsys) -> None:
    a = write_board(tmp_path, spec, 60, "a.png")
    img = cv2.imread(str(a))
    small = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
    b = tmp_path / "b.png"
    cv2.imwrite(str(b), small)

    code = main([str(a), str(b), "--board", str(_board_yaml(tmp_path, spec))])
    assert code == 2
    assert "해상도가 다르다" in capsys.readouterr().out


def test_missing_board_stops(tmp_path, spec: BoardSpec) -> None:
    a = write_board(tmp_path, spec, 60, "a.png")
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((1080, 1920, 3), 200, dtype=np.uint8))
    with pytest.raises(SystemExit):
        main([str(a), str(blank), "--board", str(_board_yaml(tmp_path, spec))])


def _board_yaml(tmp_path, spec: BoardSpec):
    path = tmp_path / "board.yaml"
    path.write_text(
        "board:\n"
        f"  cols: {spec.cols}\n"
        f"  rows: {spec.rows}\n"
        f"  square_mm: {spec.square_mm}\n"
        "  square_mm_measured: true\n",
        encoding="utf-8",
    )
    return path
