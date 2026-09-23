"""preflight_jitter - 정지 보드 연속 프레임의 코너 흔들림."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.session import Session
from preflight_jitter import (
    JITTER_OK_PX,
    JITTER_WARN_PX,
    MIN_FRAMES,
    analyze,
    collect_corners,
    verdict,
)

from conftest import render_checkerboard

FRAME_SIZE = (1920, 1080)


def fake_stack(n_frames: int, n_corners: int, jitter_px: float, drift_px: float = 0.0):
    """(F, N, 2) 코너 스택. 고정 격자 + 지정한 크기의 흔들림/드리프트."""
    rng = np.random.default_rng(0)
    base = np.stack(
        np.meshgrid(np.arange(9) * 60.0 + 200, np.arange(6) * 60.0 + 200), axis=-1
    ).reshape(-1, 2)[:n_corners]
    frames = []
    for i in range(n_frames):
        shift = np.array([drift_px * i / max(n_frames - 1, 1), 0.0])
        noise = rng.normal(0, jitter_px, size=base.shape) if jitter_px > 0 else 0.0
        frames.append(base + shift + noise)
    return np.stack(frames)


# --- analyze ---------------------------------------------------------------


def test_perfectly_still_has_zero_std() -> None:
    stats = analyze(fake_stack(20, 54, jitter_px=0.0))
    assert stats["std_mean"] == pytest.approx(0.0)
    assert stats["std_max"] == pytest.approx(0.0)
    assert stats["drift"] == pytest.approx(0.0)


def test_std_matches_injected_noise() -> None:
    """축별 std 0.5px 을 넣으면 코너별 크기는 sqrt(2)*0.5 근처가 된다."""
    stats = analyze(fake_stack(200, 54, jitter_px=0.5))
    assert stats["std_u_mean"] == pytest.approx(0.5, rel=0.15)
    assert stats["std_mean"] == pytest.approx(0.5 * np.sqrt(2), rel=0.15)


def test_drift_is_separated_from_jitter() -> None:
    """서서히 밀린 것과 떠는 것은 다른 문제다. 따로 잡혀야 한다."""
    stats = analyze(fake_stack(30, 54, jitter_px=0.0, drift_px=5.0))
    assert stats["drift"] == pytest.approx(5.0, rel=0.05)


# --- verdict ---------------------------------------------------------------


@pytest.mark.parametrize(
    "std_max, expect_code, expect_word",
    [
        (0.05, 0, "OK"),
        (JITTER_OK_PX - 0.01, 0, "OK"),
        (JITTER_OK_PX + 0.01, 2, "애매"),
        (JITTER_WARN_PX + 0.5, 2, "경고"),
    ],
)
def test_verdict_thresholds(std_max: float, expect_code: int, expect_word: str) -> None:
    text, code = verdict({"std_max": std_max})
    assert code == expect_code
    assert expect_word in text


def test_eis_is_named_in_the_warning() -> None:
    """경고 문구가 무엇을 의심해야 하는지 말해야 한다."""
    text, _ = verdict({"std_max": 2.0})
    assert "EIS" in text


# --- collect_corners (실제 세션 왕복) --------------------------------------


def make_session(tmp_path, spec: BoardSpec, n_frames: int, shift_px: float = 0.0) -> Session:
    """같은 보드를 조금씩 흔들어 찍은 것처럼 만든 세션."""
    session = Session.create(
        data_root=tmp_path,
        camera="s10",
        board=spec,
        resolution_requested=FRAME_SIZE,
        resolution_actual=FRAME_SIZE,
    )
    patch, _ = render_checkerboard(spec, square_px=60, margin_px=60)
    h, w = patch.shape[:2]
    for i in range(n_frames):
        frame = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), 220, dtype=np.uint8)
        x = 400 + int(round(i * shift_px))
        frame[300 : 300 + h, x : x + w] = patch
        session.add_frame(frame, detected=True, n_corners=spec.n_corners)
    return session


def test_collect_corners_round_trip(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, MIN_FRAMES + 2)
    corners, names = collect_corners(session)
    assert corners.shape == (MIN_FRAMES + 2, spec.n_corners, 2)
    assert len(names) == MIN_FRAMES + 2

    stats = analyze(corners)
    assert stats["std_max"] < JITTER_OK_PX  # 완전히 고정된 합성 장면


def test_moving_board_is_flagged(tmp_path, spec: BoardSpec) -> None:
    """프레임마다 2px 씩 민 세션은 경고가 나와야 한다."""
    session = make_session(tmp_path, spec, 10, shift_px=2.0)
    stats = analyze(collect_corners(session)[0])
    _, code = verdict(stats)
    assert code == 2
    assert stats["drift"] > JITTER_WARN_PX


def test_too_few_frames_stops(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, MIN_FRAMES - 2)
    with pytest.raises(SystemExit):
        collect_corners(session)
