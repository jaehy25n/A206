"""S10 서버 - 폰 없이 검증 가능한 전부.

폰이 하는 일(getUserMedia exact, wake lock, 실제 촬영)은 여기서 확인할 수 없다.
대신 **서버가 무엇을 받아서 무엇을 저장하고 무엇을 거부하는가**를 전부 돌려본다.
합성 체커보드 PNG 를 /upload 에 넣는 것이 실제 폰 업로드와 같은 경로다.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from camcal.board import BoardSpec
from s10_server.app import ServerState, create_app

from conftest import render_checkerboard

FRAME_SIZE = (1920, 1080)  # (width, height)

PHONE_SETTINGS = {
    "settings": {"width": 1920, "height": 1080, "frameRate": 30, "deviceId": "abc"},
    "manual": {"applied": {"focusMode": "manual"}, "failed": {"whiteBalanceMode": "미지원"}},
    "error": None,
}


def board_png(spec: BoardSpec, at: tuple[int, int] = (600, 300), square_px: int = 45) -> bytes:
    """1920x1080 안에 체커보드를 그린 PNG 바이트. 폰이 보내는 것과 같은 형식."""
    frame = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), 220, dtype=np.uint8)
    patch, _ = render_checkerboard(spec, square_px=square_px, margin_px=square_px)
    height, width = patch.shape[:2]
    x, y = at
    frame[y : y + height, x : x + width] = patch
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    return buf.tobytes()


def blank_png(size: tuple[int, int] = FRAME_SIZE) -> bytes:
    frame = np.full((size[1], size[0], 3), 200, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    return buf.tobytes()


@pytest.fixture
def measured_board(spec: BoardSpec) -> BoardSpec:
    return spec  # conftest 의 spec 은 square_mm_measured=True


@pytest.fixture
def client(tmp_path, measured_board: BoardSpec):
    state = ServerState(measured_board, tmp_path, allow_unmeasured=False)
    with TestClient(create_app(state)) as c:
        c.state = state  # 테스트에서 상태를 직접 들여다보려고
        yield c


def start_session(client) -> str:
    client.post("/api/phone/settings", json=PHONE_SETTINGS)
    resp = client.post("/api/session/start", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


# --- 세션 게이트 ------------------------------------------------------------


def test_session_needs_phone_resolution(client) -> None:
    """폰이 실제 해상도를 보고하기 전에는 세션을 만들지 않는다."""
    resp = client.post("/api/session/start", json={})
    assert resp.status_code == 409
    assert "카메라" in resp.json()["detail"]


def test_session_needs_measured_square(tmp_path) -> None:
    """square_mm 이 실측값이 아니면 세션을 열지 않는다 (capture_luaz 와 같은 규칙)."""
    board = BoardSpec(9, 6, 25.0, square_mm_measured=False)
    state = ServerState(board, tmp_path, allow_unmeasured=False)
    with TestClient(create_app(state)) as client:
        client.post("/api/phone/settings", json=PHONE_SETTINGS)
        resp = client.post("/api/session/start", json={})
        assert resp.status_code == 409
        assert "square_mm" in resp.json()["detail"]


def test_allow_unmeasured_flag_opens_session(tmp_path) -> None:
    board = BoardSpec(9, 6, 25.0, square_mm_measured=False)
    state = ServerState(board, tmp_path, allow_unmeasured=True)
    with TestClient(create_app(state)) as client:
        client.post("/api/phone/settings", json=PHONE_SETTINGS)
        assert client.post("/api/session/start", json={}).status_code == 200


def test_double_session_rejected(client) -> None:
    start_session(client)
    resp = client.post("/api/session/start", json={})
    assert resp.status_code == 409
    assert "이미 세션" in resp.json()["detail"]


def test_close_without_session(client) -> None:
    assert client.post("/api/session/close").status_code == 409


# --- 업로드 ----------------------------------------------------------------


def test_upload_without_session_is_rejected(client, measured_board: BoardSpec) -> None:
    resp = client.post("/upload", content=board_png(measured_board))
    assert resp.status_code == 409
    assert "세션" in resp.json()["detail"]


def test_upload_detected_frame_is_saved(client, measured_board: BoardSpec) -> None:
    start_session(client)
    resp = client.post("/upload", content=board_png(measured_board))
    assert resp.status_code == 200
    out = resp.json()
    assert out["ok"] is True
    assert out["saved"] == "000.png"
    assert out["n_corners"] == measured_board.n_corners

    session = client.state.session
    assert (session.frames_dir / "000.png").is_file()
    assert len(session.frames) == 1

    # 저장된 PNG 는 업로드된 것과 같은 크기여야 한다 (서버가 리사이즈하지 않는다)
    saved = cv2.imread(str(session.frames_dir / "000.png"), cv2.IMREAD_COLOR)
    assert (saved.shape[1], saved.shape[0]) == FRAME_SIZE


def test_undetected_frame_is_not_saved(client) -> None:
    start_session(client)
    resp = client.post("/upload", content=blank_png())
    assert resp.status_code == 200
    out = resp.json()
    assert out["ok"] is False
    assert "미검출" in out["reason"]
    assert out["saved"] is None

    assert len(client.state.session.frames) == 0
    assert client.state.n_rejected_detect == 1
    assert client.state.n_uploaded == 1  # 카운트는 올라간다


def test_wrong_resolution_is_rejected_and_not_saved(client) -> None:
    """폰이 몰래 다른 해상도로 넘어가면 서버에서 걸린다."""
    start_session(client)
    resp = client.post("/upload", content=blank_png((1280, 720)))
    out = resp.json()
    assert out["ok"] is False
    assert "해상도 불일치" in out["reason"]
    assert len(client.state.session.frames) == 0
    assert client.state.n_rejected_size == 1


def test_empty_upload_rejected(client) -> None:
    start_session(client)
    assert client.post("/upload", content=b"").status_code == 400


def test_garbage_upload_rejected(client) -> None:
    start_session(client)
    out = client.post("/upload", content=b"not a png at all").json()
    assert out["ok"] is False
    assert "디코드" in out["reason"]


def test_multipart_upload_also_works(client, measured_board: BoardSpec) -> None:
    start_session(client)
    resp = client.post(
        "/upload", files={"frame": ("000.png", board_png(measured_board), "image/png")}
    )
    assert resp.json()["ok"] is True


def test_coverage_accumulates_across_uploads(client, measured_board: BoardSpec) -> None:
    start_session(client)
    for at in [(40, 30), (1300, 30), (40, 640)]:
        assert client.post("/upload", content=board_png(measured_board, at=at)).json()["ok"]

    status = client.get("/api/status").json()
    assert status["session"]["n_saved"] == 3
    assert status["coverage"]["ratio"] > 0
    assert sum(sum(row) for row in status["coverage"]["counts"]) >= 3


def test_close_session_writes_coverage(client, measured_board: BoardSpec) -> None:
    start_session(client)
    client.post("/upload", content=board_png(measured_board))
    path = client.state.session.path

    out = client.post("/api/session/close").json()
    assert out["ok"] is True and out["n_saved"] == 1
    assert client.state.session is None

    from camcal import Session

    reloaded = Session.open(path)
    assert reloaded.coverage is not None
    assert reloaded.coverage["n_frames"] == 1
    assert reloaded.capture_settings["source"] == "s10_web"
    assert reloaded.capture_settings["track_settings"]["width"] == 1920
    assert reloaded.capture_settings["manual_constraints"]["applied"]["focusMode"] == "manual"


# --- 상태와 명령 ------------------------------------------------------------


def test_status_reports_phone_state(client) -> None:
    before = client.get("/api/status").json()
    assert before["phone"]["connected"] is False
    assert before["session"] is None

    client.post("/api/phone/settings", json=PHONE_SETTINGS)
    after = client.get("/api/status").json()
    assert after["phone"]["resolution"] == [1920, 1080]
    assert after["phone"]["manual"]["applied"]["focusMode"] == "manual"


def test_phone_error_is_surfaced(client) -> None:
    client.post(
        "/api/phone/settings",
        json={"settings": {}, "manual": {}, "error": "1920x1080 으로 열 수 없다"},
    )
    status = client.get("/api/status").json()
    assert "1920x1080" in status["phone"]["error"]
    assert status["phone"]["resolution"] is None


def test_command_without_phone_socket(client) -> None:
    resp = client.post("/api/command", json={"type": "capture_now"})
    assert resp.status_code == 409
    assert "폰" in resp.json()["detail"]


def test_unknown_command(client) -> None:
    assert client.post("/api/command", json={"type": "explode"}).status_code == 400


@pytest.mark.parametrize("interval", [0.5, 30, "abc"])
def test_interval_out_of_range(client, interval) -> None:
    resp = client.post("/api/command", json={"type": "set_interval", "interval": interval})
    assert resp.status_code == 400


def test_last_frame_endpoint(client, measured_board: BoardSpec) -> None:
    assert client.get("/api/last_frame.jpg").status_code == 404
    start_session(client)
    client.post("/upload", content=board_png(measured_board))
    resp = client.get("/api/last_frame.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert len(resp.content) > 0


# --- WebSocket --------------------------------------------------------------


def test_phone_socket_marks_connected_and_receives_command(client) -> None:
    with client.websocket_connect("/ws/phone") as phone:
        assert client.get("/api/status").json()["phone"]["connected"] is True
        client.post("/api/command", json={"type": "start_auto"})
        assert phone.receive_json() == {"type": "start_auto", "interval": 3.0}
        assert client.get("/api/status").json()["auto"]["on"] is True

    # 폰이 끊기면 자동 모드도 꺼진 것으로 본다
    assert client.get("/api/status").json()["phone"]["connected"] is False
    assert client.get("/api/status").json()["auto"]["on"] is False


def test_laptop_socket_gets_status_on_connect(client) -> None:
    with client.websocket_connect("/ws/laptop") as laptop:
        first = laptop.receive_json()
        assert first["type"] == "status"
        assert first["session"] is None


def test_preview_is_relayed_to_laptop(client) -> None:
    with client.websocket_connect("/ws/laptop") as laptop:
        laptop.receive_json()  # 접속 직후 상태
        with client.websocket_connect("/ws/preview") as preview:
            preview.send_bytes(b"\xff\xd8fake-jpeg")
            assert laptop.receive_bytes() == b"\xff\xd8fake-jpeg"


# --- 페이지 ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/phone", "/laptop"])
def test_pages_served(client, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200
    assert "<html" in resp.text
