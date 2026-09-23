"""CombinedSession - 세션 여러 개를 하나로 합쳐 추정할 때의 규칙.

합치기는 편의 기능이 아니라 위험한 연산이다. 조건이 다른 사진을 한 추정에 넣으면
RMS 는 그럭저럭 나오면서 K 만 조용히 틀린다. 그래서 무엇을 합쳐도 되고 무엇을
합치면 안 되는지를 여기서 못 박는다.
"""

from __future__ import annotations

import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.calibrate import detected_ids
from camcal.combined import CombinedSession, SessionMismatch
from camcal.session import Session

SIZE = (1920, 1080)


def make_session(
    tmp_path,
    spec: BoardSpec,
    session_id: str,
    n_frames: int,
    camera: str = "s10",
    size: tuple[int, int] = SIZE,
    n_failed: int = 0,
) -> Session:
    s = Session.create(
        data_root=tmp_path,
        camera=camera,
        board=spec,
        resolution_requested=size,
        resolution_actual=size,
        session_id=session_id,
    )
    flat = np.full((size[1], size[0], 3), 200, dtype=np.uint8)
    for i in range(n_frames + n_failed):
        ok = i < n_frames
        s.add_frame(flat, detected=ok, n_corners=spec.n_corners if ok else 0)
    s.close()
    return s


# --- 합치기 -----------------------------------------------------------------


def test_frames_get_global_indices(tmp_path, spec: BoardSpec) -> None:
    """두 세션 모두 000 부터 시작한다. 합치면 전역 번호를 새로 매겨야 한다."""
    a = make_session(tmp_path, spec, "sess_a", 40)
    b = make_session(tmp_path, spec, "sess_b", 23)

    combined = CombinedSession.open([a.path, b.path])
    assert len(combined.frames) == 63
    assert [f.index for f in combined.frames] == list(range(63))
    assert detected_ids(combined) == list(range(63))


def test_origin_and_label_point_back(tmp_path, spec: BoardSpec) -> None:
    """전역 번호에서 원래 세션/번호로 되돌아갈 수 있어야 한다.

    못 돌아가면 리포트에서 '42번이 이상하다'를 보고도 어느 파일인지 알 수 없다.
    """
    a = make_session(tmp_path, spec, "sess_a", 40)
    b = make_session(tmp_path, spec, "sess_b", 23)
    combined = CombinedSession.open([a.path, b.path])

    assert combined.origin_of(0) == ("sess_a", 0)
    assert combined.origin_of(39) == ("sess_a", 39)
    assert combined.origin_of(40) == ("sess_b", 0)
    assert combined.origin_of(62) == ("sess_b", 22)

    assert combined.label_of(40) == "sess_b/000"
    assert combined.frame_path(combined.frames[40]) == b.frames_dir / "000.png"


def test_single_session_label_is_short(tmp_path, spec: BoardSpec) -> None:
    """세션이 하나면 세션 이름을 붙이지 않는다 (리포트가 지저분해진다)."""
    a = make_session(tmp_path, spec, "sess_a", 5)
    combined = CombinedSession.open([a.path])
    assert combined.label_of(3) == "003"
    assert combined.session_id == "sess_a"


def test_failed_frames_are_carried_but_not_detected(tmp_path, spec: BoardSpec) -> None:
    a = make_session(tmp_path, spec, "sess_a", 10, n_failed=3)
    b = make_session(tmp_path, spec, "sess_b", 5)
    combined = CombinedSession.open([a.path, b.path])

    assert len(combined.frames) == 18
    assert len(detected_ids(combined)) == 15


def test_capture_settings_kept_per_session(tmp_path, spec: BoardSpec) -> None:
    """합쳐도 어느 세션이 어떤 조건이었는지는 남아야 한다."""
    a = make_session(tmp_path, spec, "sess_a", 3)
    b = make_session(tmp_path, spec, "sess_b", 3)
    a.set_capture_settings({"note": "첫판"})
    b.set_capture_settings({"note": "둘째판"})

    combined = CombinedSession.open([a.path, b.path])
    assert combined.capture_settings["sess_a"]["note"] == "첫판"
    assert combined.capture_settings["sess_b"]["note"] == "둘째판"


# --- 합치면 안 되는 것 ------------------------------------------------------


def test_different_camera_is_refused(tmp_path, spec: BoardSpec) -> None:
    a = make_session(tmp_path, spec, "sess_a", 5, camera="s10")
    b = make_session(tmp_path, spec, "sess_b", 5, camera="luaz")
    with pytest.raises(SessionMismatch) as exc:
        CombinedSession.open([a.path, b.path])
    assert "카메라가 다르다" in str(exc.value)


def test_different_resolution_is_refused(tmp_path, spec: BoardSpec) -> None:
    a = make_session(tmp_path, spec, "sess_a", 5)
    b = make_session(tmp_path, spec, "sess_b", 5, size=(1280, 720))
    with pytest.raises(SessionMismatch) as exc:
        CombinedSession.open([a.path, b.path])
    assert "해상도가 다르다" in str(exc.value)


def test_different_board_is_refused(tmp_path, spec: BoardSpec) -> None:
    """square_mm 이 다르면 거리 t 의 단위가 섞인다."""
    other = BoardSpec(cols=9, rows=6, square_mm=30.0, square_mm_measured=True)
    a = make_session(tmp_path, spec, "sess_a", 5)
    b = make_session(tmp_path, other, "sess_b", 5)
    with pytest.raises(SessionMismatch) as exc:
        CombinedSession.open([a.path, b.path])
    assert "보드 규격이 다르다" in str(exc.value)


def test_same_session_twice_is_refused(tmp_path, spec: BoardSpec) -> None:
    """같은 사진을 두 번 넣으면 그 사진의 가중치만 두 배가 된다."""
    a = make_session(tmp_path, spec, "sess_a", 5)
    with pytest.raises(ValueError) as exc:
        CombinedSession.open([a.path, a.path])
    assert "두 번" in str(exc.value)


def test_empty_list_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        CombinedSession.open([])


# --- 고아 PNG ---------------------------------------------------------------


def test_orphan_pngs_are_reported_not_used(tmp_path, spec: BoardSpec) -> None:
    """meta.json 이 모르는 PNG 가 frames/ 에 있으면 알려야 한다.

    실제로 겪은 상황: 세션 폴더에 다른 시각에 찍힌 PNG 16 장이 섞여 있었고
    meta.json 은 23 장만 알고 있었다. 폴더를 glob 하는 코드였다면 출처를 모르는
    16 장이 조용히 추정에 들어갔을 것이다.
    """
    a = make_session(tmp_path, spec, "sess_a", 5)
    import cv2

    stray = np.full((SIZE[1], SIZE[0], 3), 100, dtype=np.uint8)
    cv2.imwrite(str(a.frames_dir / "099.png"), stray)
    cv2.imwrite(str(a.frames_dir / "100.png"), stray)

    combined = CombinedSession.open([a.path])
    assert combined.orphan_pngs["sess_a"] == ["099.png", "100.png"]
    # 쓰이지는 않는다 - meta 에 적힌 5장 그대로
    assert len(combined.frames) == 5


def test_no_orphans_when_clean(tmp_path, spec: BoardSpec) -> None:
    a = make_session(tmp_path, spec, "sess_a", 5)
    combined = CombinedSession.open([a.path])
    assert combined.orphan_pngs == {}


def test_session_paths_are_all_listed(tmp_path, spec: BoardSpec) -> None:
    """재현 명령을 리포트에 적으려면 경로가 전부 있어야 한다."""
    a = make_session(tmp_path, spec, "sess_a", 3)
    b = make_session(tmp_path, spec, "sess_b", 3)
    combined = CombinedSession.open([a.path, b.path])
    assert combined.session_paths == [str(a.path), str(b.path)]
    assert combined.session_id == "sess_a+1"
