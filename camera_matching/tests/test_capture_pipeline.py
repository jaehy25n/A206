"""검출 → 세션 저장 → 커버리지 누적을 붙여서 확인한다.

capture_luaz.py 에서 GUI(창, 키 입력)를 뺀 나머지 경로다. 카메라 없이도
"찍으면 무슨 일이 일어나는가"를 전부 돌려볼 수 있다. 실촬영 때 처음 터지는
것을 줄이는 것이 목적이다.
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from camcal import Coverage, Session, find_corners
from camcal.board import BoardSpec
from camcal.constants import COVERAGE_GRID

from conftest import render_checkerboard

FRAME_SIZE = (1920, 1080)  # (width, height)


def board_frame(spec: BoardSpec, at: tuple[int, int], square_px: int = 45) -> np.ndarray:
    """1920x1080 프레임 안의 지정 위치에 체커보드를 붙인 합성 촬영본.

    Args:
        at: 보드 패치의 좌상단 (x, y) 픽셀.
    """
    frame = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), 220, dtype=np.uint8)
    patch, _ = render_checkerboard(spec, square_px=square_px, margin_px=square_px)
    height, width = patch.shape[:2]
    x, y = at
    assert x + width <= FRAME_SIZE[0] and y + height <= FRAME_SIZE[1], "패치가 프레임을 넘는다"
    frame[y : y + height, x : x + width] = patch
    return frame


@pytest.fixture
def session(tmp_path, spec: BoardSpec) -> Session:
    return Session.create(
        data_root=tmp_path,
        camera="luaz",
        board=spec,
        resolution_requested=FRAME_SIZE,
        resolution_actual=FRAME_SIZE,
        capture_settings={"backend": "msmf", "measured_fps": 29.9},
    )


def test_capture_three_positions(session: Session, spec: BoardSpec) -> None:
    """서로 다른 위치의 보드 3장을 저장하면 커버리지가 그만큼 올라간다."""
    coverage = Coverage(session.resolution_actual, COVERAGE_GRID)
    # 패치는 540x405 px. 프레임 안에서 좌상 / 우상 / 좌하 쪽에 놓는다.
    positions = [(40, 30), (1300, 30), (40, 640)]

    for at in positions:
        frame = board_frame(spec, at)
        detected, corners = find_corners(frame, spec)
        assert detected, f"합성 프레임 {at} 에서 검출 실패"
        session.add_frame(frame, detected=True, n_corners=len(corners))
        coverage.add(corners)

    session.set_coverage(coverage.to_dict())
    session.close()

    assert len(session.frames) == 3
    assert session.n_detected == 3
    assert coverage.ratio() > 0.0
    assert coverage.n_frames == 3

    # 저장된 PNG 를 다시 검출해도 같은 결과가 나온다 (PNG 무손실이므로 결정적).
    reloaded = Session.open(session.path)
    for record in reloaded.frames:
        img = cv2.imread(str(reloaded.frame_path(record)), cv2.IMREAD_COLOR)
        ok, corners = find_corners(img, spec)
        assert ok and len(corners) == record.n_corners


def test_meta_records_everything_needed_for_calibration(
    session: Session, spec: BoardSpec
) -> None:
    """3단계(캘리브레이션)가 meta.json 만 보고 시작할 수 있어야 한다."""
    coverage = Coverage(session.resolution_actual, COVERAGE_GRID)
    frame = board_frame(spec, (600, 300))
    detected, corners = find_corners(frame, spec)
    session.add_frame(frame, detected=detected, n_corners=len(corners))
    coverage.add(corners)
    session.set_coverage(coverage.to_dict())
    session.close()

    meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
    assert meta["resolution_actual"] == list(FRAME_SIZE)
    assert meta["board"]["cols"] == spec.cols and meta["board"]["rows"] == spec.rows
    assert meta["board"]["square_mm"] == spec.square_mm
    assert meta["capture_settings"]["measured_fps"] == 29.9
    assert meta["coverage"]["n_frames"] == 1
    assert meta["frames"][0]["n_corners"] == spec.n_corners


def test_undetected_frame_is_not_saved_by_policy(session: Session, spec: BoardSpec) -> None:
    """촬영 도구는 검출 실패 프레임을 저장하지 않는다 (여기서는 그 조건을 재현)."""
    blank = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), 200, dtype=np.uint8)
    detected, corners = find_corners(blank, spec)
    assert detected is False and corners is None

    if detected:  # pragma: no cover - 위 단정이 깨졌을 때만
        session.add_frame(blank, True, 0)
    assert session.frames == []
