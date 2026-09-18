"""Session - 디렉토리 생성, meta.json 왕복, 데이터 무결성 가드."""

from __future__ import annotations

import json
from datetime import datetime

import cv2
import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.constants import META_SCHEMA_VERSION
from camcal.session import Session, make_session_id

RESOLUTION = (1920, 1080)


def make_frame(width: int = 1920, height: int = 1080) -> np.ndarray:
    """저장/재로드를 확인할 수 있게 값이 일정하지 않은 프레임을 만든다."""
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


@pytest.fixture
def session(tmp_path, spec: BoardSpec) -> Session:
    return Session.create(
        data_root=tmp_path,
        camera="luaz",
        board=spec,
        resolution_requested=RESOLUTION,
        resolution_actual=RESOLUTION,
        capture_settings={"backend": "msmf", "measured_fps": 31.9},
    )


# --- session_id ------------------------------------------------------------


def test_session_id_format() -> None:
    when = datetime(2026, 9, 18, 14, 30, 12)
    assert make_session_id("luaz", when) == "20260918_143012_luaz"


def test_session_dir_layout(session: Session, tmp_path) -> None:
    assert session.path == tmp_path / "luaz" / session.session_id
    assert session.frames_dir.is_dir()
    assert session.meta_path.is_file()


@pytest.mark.parametrize("camera", ["../evil", "LUAZ", "lu az", "s10/x", ""])
def test_bad_camera_name_rejected(tmp_path, spec: BoardSpec, camera: str) -> None:
    """카메라 이름은 경로 한 조각이 된다."""
    with pytest.raises(ValueError):
        Session.create(tmp_path, camera, spec, RESOLUTION, RESOLUTION)


def test_existing_session_is_not_overwritten(tmp_path, spec: BoardSpec) -> None:
    first = Session.create(
        tmp_path, "luaz", spec, RESOLUTION, RESOLUTION, session_id="fixed_id"
    )
    first.add_frame(make_frame(), detected=True, n_corners=54)
    with pytest.raises(FileExistsError):
        Session.create(tmp_path, "luaz", spec, RESOLUTION, RESOLUTION, session_id="fixed_id")
    # 기존 프레임이 그대로 남아 있다
    assert (first.frames_dir / "000.png").is_file()


# --- 프레임 추가와 왕복 ----------------------------------------------------


def test_add_frame_writes_png_losslessly(session: Session) -> None:
    frame = make_frame()
    record = session.add_frame(frame, detected=True, n_corners=54)

    saved = cv2.imread(str(session.frame_path(record)), cv2.IMREAD_COLOR)
    assert saved is not None
    assert np.array_equal(saved, frame), "PNG 저장이 무손실이 아니다"


def test_frame_filenames_are_sequential(session: Session) -> None:
    for _ in range(3):
        session.add_frame(make_frame(), detected=True, n_corners=54)
    assert [f.filename for f in session.frames] == ["000.png", "001.png", "002.png"]
    assert [f.index for f in session.frames] == [0, 1, 2]


def test_round_trip(session: Session, spec: BoardSpec) -> None:
    session.add_frame(make_frame(), detected=True, n_corners=54)
    session.add_frame(make_frame(), detected=False, n_corners=0)
    session.set_coverage({"grid": [3, 3], "ratio": 0.5})
    session.close()

    loaded = Session.open(session.path)
    assert loaded.session_id == session.session_id
    assert loaded.camera == "luaz"
    assert loaded.board == spec
    assert loaded.resolution_requested == RESOLUTION
    assert loaded.resolution_actual == RESOLUTION
    assert loaded.capture_settings["measured_fps"] == 31.9
    assert loaded.coverage == {"grid": [3, 3], "ratio": 0.5}
    assert len(loaded.frames) == 2
    assert loaded.n_detected == 1
    assert loaded.frames[0].to_dict() == session.frames[0].to_dict()


def test_meta_written_on_every_frame(session: Session) -> None:
    """촬영 중 크래시가 나도 직전까지의 프레임 기록은 디스크에 있어야 한다."""
    session.add_frame(make_frame(), detected=True, n_corners=54)
    meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
    assert meta["n_frames"] == 1
    assert meta["frames"][0]["filename"] == "000.png"
    assert meta["schema_version"] == META_SCHEMA_VERSION


def test_no_temp_file_left_behind(session: Session) -> None:
    session.add_frame(make_frame(), detected=True, n_corners=54)
    assert list(session.path.glob("*.tmp")) == []


def test_board_spec_copied_into_meta(session: Session, spec: BoardSpec) -> None:
    """나중에 board.yaml 을 고쳐도 이 세션이 어떤 보드였는지 남는다."""
    meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
    assert meta["board"]["cols"] == spec.cols
    assert meta["board"]["square_mm"] == spec.square_mm
    assert meta["board"]["square_mm_measured"] is True


# --- 무결성 가드 -----------------------------------------------------------


def test_frame_with_wrong_resolution_rejected(session: Session) -> None:
    """세션 도중 해상도가 바뀐 프레임을 섞으면 K 가 무의미해진다."""
    with pytest.raises(ValueError):
        session.add_frame(make_frame(1280, 720), detected=True, n_corners=54)
    assert session.frames == []
    assert not (session.frames_dir / "000.png").exists()


def test_open_missing_meta(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        Session.open(tmp_path / "nope")


def test_open_rejects_other_schema_version(session: Session) -> None:
    """다른 버전의 도구가 만든 세션을 조용히 읽지 않는다."""
    meta = json.loads(session.meta_path.read_text(encoding="utf-8"))
    meta["schema_version"] = META_SCHEMA_VERSION - 1
    session.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        Session.open(session.path)
