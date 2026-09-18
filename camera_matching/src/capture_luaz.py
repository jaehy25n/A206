"""LUAZ WC1080 체커보드 촬영 도구.

    python src/capture_luaz.py                 # 촬영 시작
    python src/capture_luaz.py --list-devices  # 어느 index 가 LUAZ 인지 확인

키:
    space  지금 화면 프레임을 저장 (검출 성공일 때만)
    a      자동 모드 토글 (기본 3초 간격, 검출 성공한 프레임만 저장)
    q/ESC  종료 (meta.json 최종 저장)

이 도구는 캘리브레이션 계산을 하지 않는다. 찍고, 검출하고, 저장하는 데까지다.

조용히 실패하지 않게 하는 지점 세 곳:
    1. 1920x1080 을 요청하고 **첫 프레임의 실제 크기**로 확인한다. 다르면 예외로 멈춘다.
       (프로퍼티 되읽기는 MSMF 에서 못 믿는다 - result.md 2장)
    2. 보드 규격의 square_mm 이 실측값이 아니면 시작하지 않는다.
    3. 세션 도중 해상도가 바뀐 프레임은 Session.add_frame 이 거부한다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from camcal import BoardSpec, Coverage, Session, draw_corners, find_corners
from camcal.console import setup_console
from camcal.constants import AUTO_INTERVAL_SEC, COVERAGE_GRID

# --- 상수 (매직 넘버 금지) --------------------------------------------------

#: 미리보기 창의 최대 가로 픽셀. 1920 원본을 그대로 띄우면 화면을 넘는다.
#: 검출은 항상 **원본 해상도**에서 하고, 이 축소는 표시에만 쓴다.
PREVIEW_MAX_WIDTH = 1280

#: 카메라를 연 직후 버리는 프레임 수. 자동 노출/자동 화이트밸런스가 자리를 잡는 구간.
WARMUP_FRAMES = 15

#: 실측 fps 를 재는 데 쓰는 프레임 수. 프로퍼티 되읽기는 못 믿으므로 직접 잰다.
FPS_MEASURE_FRAMES = 30

#: 연속으로 프레임을 못 읽으면 포기하는 횟수. USB 가 빠졌을 때 무한 루프를 막는다.
MAX_CONSECUTIVE_READ_FAILURES = 30

#: --list-devices 가 훑어보는 index 범위.
DEVICE_SCAN_RANGE = 4

#: --list-devices 미리보기 창을 띄우는 시간 (초).
DEVICE_PREVIEW_SEC = 2.0

#: 오버레이 글자.
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.6
FONT_THICKNESS = 1
LINE_HEIGHT_PX = 24
PANEL_MARGIN_PX = 10

COLOR_OK = (0, 255, 0)
COLOR_BAD = (0, 0, 255)
COLOR_TEXT = (255, 255, 255)
COLOR_PANEL = (0, 0, 0)

#: OpenCV 백엔드 이름 → 상수.
BACKENDS = {
    "msmf": cv2.CAP_MSMF,
    "dshow": cv2.CAP_DSHOW,
    "any": cv2.CAP_ANY,
}

#: 프로젝트 루트 (이 파일의 상위의 상위). config/, data/ 를 여기서 찾는다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- 설정 읽기 --------------------------------------------------------------


def load_camera_config(path: Path, camera: str) -> dict[str, Any]:
    """config/cameras.yaml 에서 한 카메라의 설정을 읽는다."""
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    try:
        return dict(data["cameras"][camera])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path}: cameras.{camera} 항목이 없다") from exc


def decode_fourcc(value: float) -> str:
    """CAP_PROP_FOURCC 정수를 4글자로. MSMF 는 0 이나 엉뚱한 값을 주는 일이 잦다."""
    code = int(value)
    if code <= 0:
        return ""
    try:
        chars = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    except ValueError:
        return ""
    return chars if chars.isprintable() else ""


# --- 카메라 열기 ------------------------------------------------------------


class CameraOpenError(RuntimeError):
    """요청한 조건으로 카메라를 열지 못했다. 조용히 다른 조건으로 넘어가지 않는다."""


def open_camera(config: dict[str, Any]) -> tuple[cv2.VideoCapture, dict[str, Any]]:
    """카메라를 열고 요청 해상도가 실제로 나오는지 첫 프레임으로 확인한다.

    Returns:
        (cap, info). info 에는 resolution_actual, measured_fps, 읽어낸 프로퍼티가 들어간다.

    Raises:
        CameraOpenError: 열기 실패, 프레임 없음, 또는 해상도 불일치.
    """
    index = int(config["device_index"])
    width = int(config["width"])
    height = int(config["height"])
    backend_name = str(config.get("backend", "any")).lower()
    if backend_name not in BACKENDS:
        raise ValueError(f"모르는 backend: {backend_name} (가능: {sorted(BACKENDS)})")

    cap = cv2.VideoCapture(index, BACKENDS[backend_name])
    if not cap.isOpened():
        raise CameraOpenError(
            f"카메라를 열지 못했다: index={index}, backend={backend_name}. "
            "--list-devices 로 index 를 확인한다"
        )

    # FOURCC 를 해상도보다 **먼저** 설정한다. Windows 에서는 순서가 바뀌면
    # 드라이버가 앞의 설정을 무시하는 경우가 있다.
    fourcc = config.get("fourcc")
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*str(fourcc)))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if config.get("fps"):
        cap.set(cv2.CAP_PROP_FPS, float(config["fps"]))

    for _ in range(WARMUP_FRAMES):
        cap.read()

    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise CameraOpenError(
            f"카메라는 열렸지만 프레임이 오지 않는다: index={index}, backend={backend_name}"
        )

    actual = (int(frame.shape[1]), int(frame.shape[0]))
    if actual != (width, height):
        cap.release()
        raise CameraOpenError(
            f"요청 해상도와 실제가 다르다: 요청 {width}x{height}, 실제 {actual[0]}x{actual[1]}. "
            "다른 해상도로 촬영하면 K 를 비교할 수 없으므로 중단한다"
        )

    measured_fps = measure_fps(cap)
    info = {
        "backend": backend_name,
        "device_index": index,
        "resolution_requested": [width, height],
        "resolution_actual": [actual[0], actual[1]],
        "measured_fps": measured_fps,
        "properties_readback": read_properties(cap),
    }
    return cap, info


def measure_fps(cap: cv2.VideoCapture, n_frames: int = FPS_MEASURE_FRAMES) -> float | None:
    """프레임 도착 간격으로 실제 fps 를 잰다.

    CAP_PROP_FPS 되읽기는 드라이버가 공칭값을 돌려주므로 실제 대역폭을 말해주지
    않는다. 1080p 에서 실측 fps 가 5 근처면 압축 없는 포맷으로 떨어진 것이다.
    """
    start = time.perf_counter()
    got = 0
    for _ in range(n_frames):
        ok, _frame = cap.read()
        if ok:
            got += 1
    elapsed = time.perf_counter() - start
    if got < 2 or elapsed <= 0:
        return None
    return round(got / elapsed, 2)


def read_properties(cap: cv2.VideoCapture) -> dict[str, Any]:
    """읽을 수 있는 카메라 프로퍼티를 그대로 기록한다.

    **값을 믿으라는 뜻이 아니다.** MSMF 는 FOURCC 를 0 으로, EXPOSURE 를 설정과
    무관한 고정값으로 돌려주는 일이 있다 (result.md 2장).
    나중에 "그때 무엇이 읽혔는지" 비교할 수 있게 원본 그대로 남긴다.
    """
    props = {
        "frame_width": cv2.CAP_PROP_FRAME_WIDTH,
        "frame_height": cv2.CAP_PROP_FRAME_HEIGHT,
        "fps": cv2.CAP_PROP_FPS,
        "fourcc": cv2.CAP_PROP_FOURCC,
        "exposure": cv2.CAP_PROP_EXPOSURE,
        "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
        "autofocus": cv2.CAP_PROP_AUTOFOCUS,
        "focus": cv2.CAP_PROP_FOCUS,
        "auto_wb": cv2.CAP_PROP_AUTO_WB,
        "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
        "brightness": cv2.CAP_PROP_BRIGHTNESS,
        "gain": cv2.CAP_PROP_GAIN,
    }
    out: dict[str, Any] = {}
    for name, prop in props.items():
        try:
            out[name] = cap.get(prop)
        except cv2.error:
            out[name] = None
    out["fourcc_decoded"] = decode_fourcc(out.get("fourcc") or 0)
    return out


def list_devices(backend_name: str = "msmf") -> None:
    """index 0..N 을 열어보고 무엇이 붙어 있는지 미리보기로 보여준다.

    LUAZ 와 노트북 내장 카메라는 둘 다 1920x1080 을 받아주므로 해상도로는
    구분되지 않는다. 눈으로 확인하는 것이 유일한 방법이다.
    """
    backend = BACKENDS[backend_name]
    print(f"backend={backend_name}, index 0..{DEVICE_SCAN_RANGE - 1} 확인")
    for index in range(DEVICE_SCAN_RANGE):
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            print(f"  index {index}: 열리지 않음")
            cap.release()
            continue
        ok, frame = cap.read()
        if not ok or frame is None:
            print(f"  index {index}: 열렸지만 프레임 없음")
            cap.release()
            continue
        print(f"  index {index}: {frame.shape[1]}x{frame.shape[0]} - 미리보기 창 확인")
        window = f"index {index} (any key to skip)"
        deadline = time.time() + DEVICE_PREVIEW_SEC
        while time.time() < deadline:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.imshow(window, fit_preview(frame))
            if cv2.waitKey(30) != -1:
                break
        cv2.destroyWindow(window)
        cap.release()
    cv2.destroyAllWindows()


# --- 오버레이 --------------------------------------------------------------


def fit_preview(frame: np.ndarray, max_width: int = PREVIEW_MAX_WIDTH) -> np.ndarray:
    """표시용 축소. 검출에는 쓰지 않는다."""
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    return cv2.resize(
        frame, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA
    )


def draw_status_panel(canvas: np.ndarray, lines: list[tuple[str, tuple[int, int, int]]]) -> None:
    """우상단 상태 패널. lines 는 (문자열, 색) 목록. ASCII 만 쓴다(한글 렌더 불가)."""
    if not lines:
        return
    widths = [
        cv2.getTextSize(text, FONT, FONT_SCALE, FONT_THICKNESS)[0][0] for text, _ in lines
    ]
    box_w = max(widths) + 2 * PANEL_MARGIN_PX
    box_h = LINE_HEIGHT_PX * len(lines) + PANEL_MARGIN_PX
    x0 = canvas.shape[1] - box_w - PANEL_MARGIN_PX
    y0 = PANEL_MARGIN_PX

    overlay = canvas.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), COLOR_PANEL, cv2.FILLED)
    cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0, canvas)

    for i, (text, color) in enumerate(lines):
        baseline = y0 + LINE_HEIGHT_PX * (i + 1) - 6
        cv2.putText(
            canvas,
            text,
            (x0 + PANEL_MARGIN_PX, baseline),
            FONT,
            FONT_SCALE,
            color,
            FONT_THICKNESS,
            cv2.LINE_AA,
        )


def status_lines(
    session: Session,
    coverage: Coverage,
    detected: bool,
    auto_on: bool,
    auto_interval: float,
    next_auto_in: float | None,
) -> list[tuple[str, tuple[int, int, int]]]:
    """우상단에 띄울 줄들. 저장 장수 / 커버리지 / 빈 셀 / 모드."""
    empty = coverage.empty_labels()
    lines: list[tuple[str, tuple[int, int, int]]] = [
        (f"saved: {len(session.frames)}", COLOR_TEXT),
        (f"coverage: {coverage.ratio() * 100:.0f}%", COLOR_TEXT),
        (
            "empty: " + (", ".join(empty) if empty else "none"),
            COLOR_BAD if empty else COLOR_OK,
        ),
        (
            "board: DETECTED" if detected else "board: not found",
            COLOR_OK if detected else COLOR_BAD,
        ),
    ]
    if auto_on:
        remain = "" if next_auto_in is None else f" (next {max(next_auto_in, 0):.1f}s)"
        lines.append((f"AUTO {auto_interval:.1f}s{remain}", COLOR_OK))
    else:
        lines.append(("manual  [space] save [a] auto [q] quit", COLOR_TEXT))
    return lines


# --- 촬영 루프 --------------------------------------------------------------


def run_capture(
    cap: cv2.VideoCapture,
    session: Session,
    board: BoardSpec,
    auto_interval: float,
) -> None:
    """미리보기를 띄우고 키 입력에 따라 저장한다. 종료 시 meta.json 최종 저장."""
    coverage = Coverage(session.resolution_actual, COVERAGE_GRID)
    window = f"capture {session.camera} - {session.session_id}"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    auto_on = False
    last_auto_save = 0.0
    read_failures = 0

    print(f"세션: {session.path}")
    print("[space] 저장  [a] 자동 모드  [q] 종료")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                read_failures += 1
                if read_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    raise CameraOpenError(
                        f"프레임을 {read_failures}회 연속 읽지 못했다. USB 연결을 확인한다"
                    )
                continue
            read_failures = 0

            # 검출은 항상 원본 해상도에서. 축소본으로 찾으면 코너 정밀도가 떨어진다.
            detected, corners = find_corners(frame, board)

            now = time.monotonic()
            next_auto_in = (
                (last_auto_save + auto_interval) - now if auto_on and last_auto_save else None
            )

            canvas = fit_preview(draw_corners(frame, board, corners, detected))
            draw_status_panel(
                canvas,
                status_lines(session, coverage, detected, auto_on, auto_interval, next_auto_in),
            )
            cv2.imshow(window, canvas)

            key = cv2.waitKey(1) & 0xFF
            save_now = False

            if key in (ord("q"), 27):  # q or ESC
                break
            if key == ord("a"):
                auto_on = not auto_on
                last_auto_save = now if auto_on else 0.0
                print(f"자동 모드 {'ON' if auto_on else 'OFF'} ({auto_interval:.1f}s 간격)")
            elif key == ord(" "):
                if detected:
                    save_now = True
                else:
                    print("검출 실패 프레임은 저장하지 않는다")

            if auto_on and detected and (now - last_auto_save) >= auto_interval:
                save_now = True
                last_auto_save = now

            if save_now and detected and corners is not None:
                record = session.add_frame(frame, detected=True, n_corners=len(corners))
                cells = coverage.add(corners)
                session.set_coverage(coverage.to_dict())
                empty_ko = coverage.empty_labels(korean=True)
                print(
                    f"저장 {record.filename}  코너 {record.n_corners}  "
                    f"셀 {sorted(coverage.label(c) for c in cells)}  "
                    f"커버리지 {coverage.ratio() * 100:.0f}%  "
                    f"빈 셀 {empty_ko if empty_ko else '없음'}"
                )
    finally:
        cv2.destroyWindow(window)
        session.set_coverage(coverage.to_dict())
        session.close()

    empty_ko = coverage.empty_labels(korean=True)
    print()
    print(f"총 {len(session.frames)}장 저장 (검출 성공 {session.n_detected}장)")
    print(f"커버리지 {coverage.ratio() * 100:.0f}%  빈 셀: {empty_ko if empty_ko else '없음'}")
    print(f"세션: {session.path}")


# --- CLI -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LUAZ 체커보드 촬영 도구 (촬영/검출/저장까지. 캘리브레이션 없음)"
    )
    parser.add_argument(
        "--camera", default="luaz", help="config/cameras.yaml 의 카메라 키 (기본 luaz)"
    )
    parser.add_argument(
        "--config-dir", type=Path, default=PROJECT_ROOT / "config", help="board.yaml, cameras.yaml 위치"
    )
    parser.add_argument(
        "--data-root", type=Path, default=PROJECT_ROOT / "data", help="세션을 만들 data/ 경로"
    )
    parser.add_argument("--session-id", default=None, help="지정하지 않으면 YYYYMMDD_HHMMSS_<camera>")
    parser.add_argument(
        "--device-index", type=int, default=None, help="cameras.yaml 의 device_index 를 덮어쓴다"
    )
    parser.add_argument(
        "--backend", default=None, choices=sorted(BACKENDS), help="cameras.yaml 의 backend 를 덮어쓴다"
    )
    parser.add_argument(
        "--auto-interval",
        type=float,
        default=AUTO_INTERVAL_SEC,
        help=f"자동 모드 저장 간격 (초, 기본 {AUTO_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--allow-unmeasured-square",
        action="store_true",
        help="board.yaml 의 square_mm 이 실측값이 아니어도 진행한다 (시험 촬영 전용)",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="카메라 index 를 미리보기로 확인하고 끝낸다"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    if args.list_devices:
        list_devices(args.backend or "msmf")
        return 0

    board = BoardSpec.from_yaml(args.config_dir / "board.yaml")
    if not board.square_mm_measured:
        message = (
            f"board.yaml 의 square_mm={board.square_mm} 이 실측값이 아니다 "
            "(square_mm_measured: false). 이 값이 틀리면 K 는 맞지만 거리 t 가 "
            "전부 같은 비율로 틀어진다."
        )
        if not args.allow_unmeasured_square:
            print(f"[중단] {message}", file=sys.stderr)
            print(
                "  자로 재서 config/board.yaml 을 고치거나, 시험 촬영이면 "
                "--allow-unmeasured-square 를 붙인다",
                file=sys.stderr,
            )
            return 2
        print(f"[경고] {message} (--allow-unmeasured-square 로 진행)", file=sys.stderr)

    camera_config = load_camera_config(args.config_dir / "cameras.yaml", args.camera)
    if args.device_index is not None:
        camera_config["device_index"] = args.device_index
    if args.backend is not None:
        camera_config["backend"] = args.backend

    try:
        cap, info = open_camera(camera_config)
    except CameraOpenError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1

    print(
        f"카메라 open: index={info['device_index']} backend={info['backend']} "
        f"{info['resolution_actual'][0]}x{info['resolution_actual'][1]} "
        f"실측 {info['measured_fps']} fps"
    )

    try:
        session = Session.create(
            data_root=args.data_root,
            camera=args.camera,
            board=board,
            resolution_requested=tuple(info["resolution_requested"]),
            resolution_actual=tuple(info["resolution_actual"]),
            capture_settings=info,
            session_id=args.session_id,
        )
        run_capture(cap, session, board, args.auto_interval)
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
