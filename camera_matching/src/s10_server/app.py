"""S10 원격 촬영 서버.

노트북이 HTTPS 서버를 띄우고, 폰은 브라우저로 접속해 카메라만 담당한다.
**조작은 전부 노트북에서** 한다 - 사용자는 혼자이고 폰은 삼각대에 고정되어 있으며
손에는 체커보드가 들려 있다.

    노트북 브라우저 (laptop.html)  ──REST──▶  서버  ──WS 명령──▶  폰 (phone.html)
            ▲                                  ▲                      │
            └──── WS 상태/프리뷰 ──────────────┴──── PNG 업로드 ──────┘

조용히 실패하지 않는 지점:
    - 폰이 1920x1080 exact 를 못 잡으면 폰 화면에 크게 에러. 다른 해상도로 넘어가지 않는다
    - 업로드된 PNG 크기가 세션 해상도와 다르면 서버가 400 으로 거부하고 저장하지 않는다
    - 체커보드가 검출되지 않은 프레임은 저장하지 않는다 (카운트만 올린다)
    - 세션 없이 업로드하면 409. 보드 square_mm 이 실측값이 아니면 세션을 만들지 않는다
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from camcal import BoardSpec, Coverage, Session, draw_corners, find_corners
from camcal.console import setup_console
from camcal.constants import COVERAGE_GRID

from .certs import cert_san_ips, ensure_certs, lan_ip

# --- 상수 -------------------------------------------------------------------

#: 이 카메라 이름으로 세션이 만들어진다 (data/s10/<session_id>/).
CAMERA_NAME = "s10"

#: 기본 포트. 1024 아래는 관리자 권한이 필요하고, 443 은 다른 것이 쓰고 있을 수 있다.
DEFAULT_PORT = 8443

#: 자동 촬영 기본 간격 (초). 보드를 옮기고 흔들림이 멎을 시간.
DEFAULT_AUTO_INTERVAL_SEC = 3.0

#: 간격 슬라이더 범위 (초).
MIN_AUTO_INTERVAL_SEC = 1.0
MAX_AUTO_INTERVAL_SEC = 10.0

#: 노트북에 보여줄 "마지막 프레임" 오버레이 JPEG 의 가로 크기와 품질.
#: 원본 PNG 는 그대로 저장되고, 이건 화면 확인용이다.
LAST_FRAME_WIDTH = 960
LAST_FRAME_JPEG_QUALITY = 80

#: 폰이 보내는 프리뷰 규격. phone.html 과 맞춰야 한다.
PREVIEW_WIDTH = 320
PREVIEW_HEIGHT = 180
PREVIEW_FPS = 5

#: 업로드 최대 크기 (바이트). 1920x1080 PNG 는 보통 2~5MB.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


# --- 서버 상태 --------------------------------------------------------------


class ServerState:
    """세션 하나와 연결된 소켓들. 단일 사용자 전제라 락 하나로 충분하다."""

    def __init__(self, board: BoardSpec, data_root: Path, allow_unmeasured: bool) -> None:
        self.board = board
        self.data_root = Path(data_root)
        self.allow_unmeasured = allow_unmeasured

        self.session: Session | None = None
        self.coverage: Coverage | None = None
        self.lock = asyncio.Lock()

        # 폰이 보고한 실제 상태
        self.phone_connected = False
        self.phone_settings: dict[str, Any] = {}
        self.phone_manual: dict[str, Any] = {}
        self.phone_error: str | None = None
        self.phone_resolution: tuple[int, int] | None = None

        # 자동 모드 (실제 타이머는 폰이 돌린다. 여기 값은 표시와 명령용)
        self.auto_on = False
        self.auto_interval = DEFAULT_AUTO_INTERVAL_SEC

        # 카운터
        self.n_uploaded = 0
        self.n_rejected_detect = 0
        self.n_rejected_size = 0

        # 마지막 프레임 (노트북 표시용)
        self.last_overlay_jpeg: bytes | None = None
        self.last_frame_seq = 0
        self.last_result: dict[str, Any] | None = None

        self.phone_ws: WebSocket | None = None
        self.laptop_ws: set[WebSocket] = set()

    # --- 세션 ---------------------------------------------------------------

    def start_session(self, session_id: str | None = None) -> Session:
        """세션을 만든다. 폰이 실제 해상도를 보고한 뒤에만 가능하다.

        해상도를 모르는 채로 세션을 열면 나중에 어떤 크기로 찍혔는지 알 수 없다.
        """
        if not self.board.square_mm_measured and not self.allow_unmeasured:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"config/board.yaml 의 square_mm={self.board.square_mm} 이 실측값이 아니다 "
                    "(square_mm_measured: false). 자로 재서 고치거나 서버를 "
                    "--allow-unmeasured-square 로 다시 띄운다"
                ),
            )
        if self.phone_resolution is None:
            raise HTTPException(
                status_code=409,
                detail="폰이 아직 카메라를 열지 않았다. 폰에서 카메라를 선택하고 다시 시도한다",
            )
        if self.session is not None:
            raise HTTPException(
                status_code=409,
                detail=f"이미 세션이 열려 있다: {self.session.session_id}. 먼저 종료한다",
            )

        capture_settings = {
            "source": "s10_web",
            "track_settings": self.phone_settings,
            "manual_constraints": self.phone_manual,
            "preview": {"width": PREVIEW_WIDTH, "height": PREVIEW_HEIGHT, "fps": PREVIEW_FPS},
        }
        self.session = Session.create(
            data_root=self.data_root,
            camera=CAMERA_NAME,
            board=self.board,
            resolution_requested=(1920, 1080),
            resolution_actual=self.phone_resolution,
            capture_settings=capture_settings,
            session_id=session_id,
        )
        self.coverage = Coverage(self.session.resolution_actual, COVERAGE_GRID)
        self.n_uploaded = 0
        self.n_rejected_detect = 0
        self.n_rejected_size = 0
        self.last_overlay_jpeg = None
        self.last_result = None
        return self.session

    def close_session(self) -> dict[str, Any]:
        if self.session is None:
            raise HTTPException(status_code=409, detail="열린 세션이 없다")
        if self.coverage is not None:
            self.session.set_coverage(self.coverage.to_dict())
        self.session.close()
        summary = {
            "session_id": self.session.session_id,
            "path": str(self.session.path),
            "n_saved": len(self.session.frames),
            "coverage": self.coverage.to_dict() if self.coverage else None,
        }
        self.session = None
        self.coverage = None
        return summary

    # --- 상태 ---------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        session = self.session
        coverage = self.coverage
        return {
            "type": "status",
            "board": self.board.to_dict(),
            "phone": {
                "connected": self.phone_connected,
                "resolution": list(self.phone_resolution) if self.phone_resolution else None,
                "settings": self.phone_settings,
                "manual": self.phone_manual,
                "error": self.phone_error,
            },
            "session": (
                None
                if session is None
                else {
                    "session_id": session.session_id,
                    "path": str(session.path),
                    "n_saved": len(session.frames),
                    "resolution": list(session.resolution_actual),
                }
            ),
            "coverage": (
                None
                if coverage is None
                else {
                    "grid": list(coverage.grid),
                    "counts": coverage.counts.tolist(),
                    "ratio": coverage.ratio(),
                    "empty": coverage.empty_labels(),
                }
            ),
            "auto": {"on": self.auto_on, "interval": self.auto_interval},
            "counters": {
                "uploaded": self.n_uploaded,
                "rejected_detect": self.n_rejected_detect,
                "rejected_size": self.n_rejected_size,
            },
            "last": self.last_result,
            "last_frame_seq": self.last_frame_seq,
        }

    # --- 소켓 ---------------------------------------------------------------

    async def push_status(self) -> None:
        payload = json.dumps(self.status(), ensure_ascii=False)
        for ws in list(self.laptop_ws):
            try:
                await ws.send_text(payload)
            except Exception:  # 끊긴 소켓은 조용히 정리한다 (에러 자체는 정상 경로)
                self.laptop_ws.discard(ws)

    async def push_preview(self, jpeg: bytes) -> None:
        for ws in list(self.laptop_ws):
            try:
                await ws.send_bytes(jpeg)
            except Exception:
                self.laptop_ws.discard(ws)

    async def send_phone(self, message: dict[str, Any]) -> None:
        if self.phone_ws is None:
            raise HTTPException(status_code=409, detail="폰이 연결되어 있지 않다")
        await self.phone_ws.send_text(json.dumps(message, ensure_ascii=False))


# --- 프레임 처리 (CPU 작업, 스레드풀에서 돈다) -------------------------------


def process_frame(state: ServerState, png_bytes: bytes) -> dict[str, Any]:
    """PNG 디코드 → 크기 확인 → 검출 → 성공 시에만 저장.

    반환 dict 가 그대로 노트북 화면의 "마지막 결과"가 된다.
    """
    buf = np.frombuffer(png_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if frame is None:
        return {"ok": False, "reason": "PNG 디코드 실패", "saved": None}

    session = state.session
    assert session is not None and state.coverage is not None  # 호출 전에 확인한다

    height, width = frame.shape[:2]
    if (width, height) != session.resolution_actual:
        state.n_rejected_size += 1
        return {
            "ok": False,
            "reason": (
                f"해상도 불일치: 받은 {width}x{height}, 세션 "
                f"{session.resolution_actual[0]}x{session.resolution_actual[1]}"
            ),
            "saved": None,
        }

    detected, corners = find_corners(frame, state.board)
    overlay = draw_corners(frame, state.board, corners, detected)
    if overlay.shape[1] > LAST_FRAME_WIDTH:
        scale = LAST_FRAME_WIDTH / overlay.shape[1]
        overlay = cv2.resize(
            overlay,
            (LAST_FRAME_WIDTH, int(round(overlay.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok_enc, jpeg = cv2.imencode(
        ".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, LAST_FRAME_JPEG_QUALITY]
    )
    state.last_overlay_jpeg = jpeg.tobytes() if ok_enc else None
    state.last_frame_seq += 1

    if not detected:
        state.n_rejected_detect += 1
        return {"ok": False, "reason": "체커보드 미검출 (저장하지 않음)", "saved": None}

    record = session.add_frame(frame, detected=True, n_corners=len(corners))
    cells = state.coverage.add(corners)
    session.set_coverage(state.coverage.to_dict())
    return {
        "ok": True,
        "reason": None,
        "saved": record.filename,
        "n_corners": record.n_corners,
        "cells": sorted(state.coverage.label(c) for c in cells),
    }


# --- 앱 ---------------------------------------------------------------------


def create_app(state: ServerState) -> FastAPI:
    app = FastAPI(title="S10 capture server", docs_url=None, redoc_url=None)
    app.state.camcal = state
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- 페이지 ---

    @app.get("/")
    async def index() -> Response:
        return FileResponse(STATIC_DIR / "laptop.html")

    @app.get("/phone")
    async def phone_page() -> Response:
        return FileResponse(STATIC_DIR / "phone.html")

    @app.get("/laptop")
    async def laptop_page() -> Response:
        return FileResponse(STATIC_DIR / "laptop.html")

    # --- 상태 ---

    @app.get("/api/status")
    async def get_status() -> JSONResponse:
        return JSONResponse(state.status())

    @app.get("/api/last_frame.jpg")
    async def last_frame() -> Response:
        if state.last_overlay_jpeg is None:
            raise HTTPException(status_code=404, detail="아직 업로드된 프레임이 없다")
        return Response(content=state.last_overlay_jpeg, media_type="image/jpeg")

    # --- 폰이 보고하는 것 ---

    @app.post("/api/phone/settings")
    async def phone_settings(payload: dict[str, Any]) -> JSONResponse:
        """폰이 카메라를 연 직후 track.getSettings() 와 manual 제약 결과를 보낸다."""
        state.phone_settings = dict(payload.get("settings") or {})
        state.phone_manual = dict(payload.get("manual") or {})
        state.phone_error = payload.get("error")

        width = state.phone_settings.get("width")
        height = state.phone_settings.get("height")
        state.phone_resolution = (
            (int(width), int(height)) if width and height else None
        )
        await state.push_status()
        return JSONResponse({"ok": True, "resolution": state.phone_resolution})

    @app.post("/upload")
    async def upload(request: Request, frame: UploadFile | None = None) -> JSONResponse:
        """PNG 한 장. multipart 의 `frame` 필드, 또는 body 에 raw PNG.

        raw 를 받는 이유: curl 로 검증하기 쉽고, 폰이 blob 을 그대로 보낼 수 있다.
        """
        if state.session is None:
            raise HTTPException(
                status_code=409, detail="열린 세션이 없다. 노트북에서 '세션 시작'을 누른다"
            )

        data = await frame.read() if frame is not None else await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="빈 업로드")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"업로드가 너무 크다: {len(data)} bytes")

        async with state.lock:
            state.n_uploaded += 1
            result = await run_in_threadpool(process_frame, state, data)
            state.last_result = result
        await state.push_status()

        if not result["ok"]:
            # 검출 실패는 정상 경로다 (보드를 옮기는 중일 수 있다). 200 으로 돌려주되
            # 이유를 담아서 노트북에 그대로 표시한다.
            return JSONResponse(result, status_code=200)
        return JSONResponse(result)

    # --- 노트북이 누르는 것 ---

    @app.post("/api/session/start")
    async def session_start(payload: dict[str, Any] | None = None) -> JSONResponse:
        session = state.start_session((payload or {}).get("session_id"))
        await state.push_status()
        return JSONResponse(
            {"ok": True, "session_id": session.session_id, "path": str(session.path)}
        )

    @app.post("/api/session/close")
    async def session_close() -> JSONResponse:
        if state.auto_on:
            state.auto_on = False
            try:
                await state.send_phone({"type": "stop_auto"})
            except HTTPException:
                pass  # 폰이 이미 끊겼으면 세션만 닫는다
        summary = state.close_session()
        await state.push_status()
        return JSONResponse({"ok": True, **summary})

    @app.post("/api/command")
    async def command(payload: dict[str, Any]) -> JSONResponse:
        """노트북 버튼 → 폰 명령. capture_now / start_auto / stop_auto / set_interval."""
        kind = str(payload.get("type", ""))
        if kind == "capture_now":
            await state.send_phone({"type": "capture_now"})
        elif kind == "start_auto":
            state.auto_on = True
            await state.send_phone({"type": "start_auto", "interval": state.auto_interval})
        elif kind == "stop_auto":
            state.auto_on = False
            await state.send_phone({"type": "stop_auto"})
        elif kind == "set_interval":
            try:
                interval = float(payload["interval"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="interval 이 숫자가 아니다") from exc
            if not MIN_AUTO_INTERVAL_SEC <= interval <= MAX_AUTO_INTERVAL_SEC:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"interval 범위 밖: {interval} "
                        f"({MIN_AUTO_INTERVAL_SEC}~{MAX_AUTO_INTERVAL_SEC}s)"
                    ),
                )
            state.auto_interval = interval
            await state.send_phone({"type": "set_interval", "interval": interval})
        else:
            raise HTTPException(status_code=400, detail=f"모르는 명령: {kind!r}")

        await state.push_status()
        return JSONResponse({"ok": True})

    # --- WebSocket ---

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket) -> None:
        """폰 제어 채널. 서버 → 폰 명령. 폰은 ping 만 보낸다."""
        await ws.accept()
        state.phone_ws = ws
        state.phone_connected = True
        await state.push_status()
        try:
            while True:
                await ws.receive_text()  # ping. 내용은 쓰지 않는다
        except WebSocketDisconnect:
            pass
        finally:
            if state.phone_ws is ws:
                state.phone_ws = None
                state.phone_connected = False
                state.auto_on = False  # 폰이 끊기면 자동 모드도 끝난 것이다
                await state.push_status()

    @app.websocket("/ws/preview")
    async def ws_preview(ws: WebSocket) -> None:
        """폰 → 서버 프리뷰 JPEG. 노트북들에게 그대로 중계한다."""
        await ws.accept()
        try:
            while True:
                jpeg = await ws.receive_bytes()
                await state.push_preview(jpeg)
        except WebSocketDisconnect:
            pass

    @app.websocket("/ws/laptop")
    async def ws_laptop(ws: WebSocket) -> None:
        """노트북 대시보드. 텍스트 = 상태 JSON, 바이너리 = 프리뷰 JPEG."""
        await ws.accept()
        state.laptop_ws.add(ws)
        await ws.send_text(json.dumps(state.status(), ensure_ascii=False))
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state.laptop_ws.discard(ws)

    return app


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S10 원격 촬영 서버 (HTTPS)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0", help="기본 0.0.0.0 (LAN 에 노출)")
    parser.add_argument("--certs-dir", type=Path, default=PROJECT_ROOT / "certs")
    parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "config")
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument(
        "--allow-unmeasured-square",
        action="store_true",
        help="board.yaml 의 square_mm 이 실측값이 아니어도 세션을 연다 (시험 촬영 전용)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    board = BoardSpec.from_yaml(args.config_dir / "board.yaml")
    if not board.square_mm_measured and not args.allow_unmeasured_square:
        print(
            f"[경고] board.yaml 의 square_mm={board.square_mm} 이 실측값이 아니다. "
            "서버는 뜨지만 세션을 시작할 수 없다 (--allow-unmeasured-square 로 우회)",
            file=sys.stderr,
        )

    ip = lan_ip()
    cert_path, key_path = ensure_certs(args.certs_dir, ip)
    san = cert_san_ips(cert_path)
    if ip not in san:
        print(
            f"[경고] 인증서 SAN {san} 에 현재 LAN IP {ip} 가 없다. "
            f"{args.certs_dir} 의 cert.pem / key.pem 을 지우고 다시 띄우면 새로 만든다",
            file=sys.stderr,
        )
    if ip.startswith("127."):
        print("[경고] LAN IP 를 찾지 못했다. Wi-Fi 연결을 확인한다 - 폰이 접속할 수 없다", file=sys.stderr)

    state = ServerState(board, args.data_root, args.allow_unmeasured_square)
    app = create_app(state)

    print()
    print(f"  폰에서 열기   https://{ip}:{args.port}/phone")
    print(f"  노트북에서 열기 https://localhost:{args.port}/laptop")
    print()
    print("  자체 서명 인증서다. 폰 브라우저의 경고는 '고급 → 계속'으로 통과한다.")
    print()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
