"""카메라 영상을 받아 공통 target 공간으로 바꿔 내보낸다 (5단계 실행기).

    # 웹캠을 실시간 변환해서 창에 띄운다
    python src/run_video_remap.py --camera-index 0 --intrinsics results/luaz_intrinsics.json

    # 동영상 파일 -> 동영상 파일
    python src/run_video_remap.py in.mp4 --intrinsics results/s10_intrinsics.json -o out.mp4

    # 이미지 폴더 -> 이미지 폴더
    python src/run_video_remap.py frames/ --intrinsics results/s10_intrinsics.json -o out/

이 파일은 **얇은 실행기**다. 실제 변환은 `camcal.stream.FrameRemapper` 가 한다.
다른 프로그램에 붙일 때는 이 파일을 쓰지 말고 그 클래스를 직접 import 한다.

    from camcal.stream import FrameRemapper
    remapper = FrameRemapper.from_files("results/luaz_intrinsics.json")
    out = remapper.apply(frame)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from camcal.console import setup_console
from camcal.constants import PNG_WRITE_PARAMS
from camcal.stream import FrameRemapper, ResolutionMismatch
from camcal.target_space import TARGET_SPACE_FILENAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 동영상으로 쓸 때의 코덱. mp4v 는 어디서나 열린다.
VIDEO_FOURCC = "mp4v"

#: 창에 띄울 때의 최대 가로 크기.
WINDOW_MAX_WIDTH = 1280

#: 속도를 몇 프레임마다 보고할지.
REPORT_EVERY = 60


def open_source(args: argparse.Namespace) -> tuple[cv2.VideoCapture | None, list[Path]]:
    """입력을 연다. (VideoCapture, 이미지 목록) 중 하나만 채워진다."""
    if args.camera_index is not None:
        cap = cv2.VideoCapture(args.camera_index, cv2.CAP_MSMF)
        if not cap.isOpened():
            raise SystemExit(f"[중단] 카메라를 열지 못했다: index={args.camera_index}")
        if args.width and args.height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        return cap, []

    source = args.source
    if source is None:
        raise SystemExit("[중단] 입력이 없다. 동영상/폴더를 주거나 --camera-index 를 쓴다")
    if source.is_dir():
        images = sorted(source.glob("*.png")) + sorted(source.glob("*.jpg"))
        if not images:
            raise SystemExit(f"[중단] 이미지가 없다: {source}")
        return None, images
    if not source.exists():
        raise SystemExit(f"[중단] 입력을 찾을 수 없다: {source}")
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise SystemExit(f"[중단] 동영상을 열지 못했다: {source}")
    return cap, []


def fit_window(frame):
    if frame.shape[1] <= WINDOW_MAX_WIDTH:
        return frame
    scale = WINDOW_MAX_WIDTH / frame.shape[1]
    return cv2.resize(
        frame,
        (WINDOW_MAX_WIDTH, int(round(frame.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", type=Path, nargs="?", help="동영상 파일 또는 이미지 폴더")
    parser.add_argument("--camera-index", type=int, default=None, help="웹캠 index (실시간)")
    parser.add_argument("--width", type=int, default=1920, help="웹캠에 요청할 가로")
    parser.add_argument("--height", type=int, default=1080, help="웹캠에 요청할 세로")
    parser.add_argument(
        "--intrinsics", type=Path, required=True, help="이 카메라의 intrinsics.json"
    )
    parser.add_argument(
        "--target", type=Path, default=PROJECT_ROOT / "results" / TARGET_SPACE_FILENAME
    )
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="출력 동영상 파일 또는 폴더. 없으면 창에 띄운다")
    parser.add_argument("--crop", action="store_true", help="검은 영역을 잘라낸다")
    parser.add_argument("--fps", type=float, default=None, help="출력 동영상 fps")
    parser.add_argument("--limit", type=int, default=None, help="N 프레임만 처리")
    parser.add_argument("--side-by-side", action="store_true",
                        help="창에 원본과 변환본을 나란히 띄운다")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    cap, images = open_source(args)

    # 첫 프레임을 봐야 입력 해상도를 안다. 맵은 그 크기로 한 번만 만든다.
    if cap is not None:
        ok, first = cap.read()
        if not ok or first is None:
            raise SystemExit("[중단] 첫 프레임을 읽지 못했다")
    else:
        first = cv2.imread(str(images[0]), cv2.IMREAD_COLOR)
        if first is None:
            raise SystemExit(f"[중단] 이미지를 읽지 못했다: {images[0]}")
    input_size = (first.shape[1], first.shape[0])

    try:
        remapper = FrameRemapper.from_files(
            args.intrinsics, args.target, input_size=input_size, crop=args.crop
        )
    except (FileNotFoundError, ResolutionMismatch, ValueError) as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    print(remapper.describe())
    if remapper.valid_ratio < 1.0 and not args.crop:
        print(f"  검은 영역 {100 - remapper.valid_ratio * 100:.2f}% "
              "(원본에 없는 부분이다. --crop 으로 잘라낼 수 있다)")

    writer = None
    out_dir = None
    if args.out is not None:
        if args.out.suffix.lower() in (".mp4", ".avi", ".mkv"):
            fps = args.fps or (cap.get(cv2.CAP_PROP_FPS) if cap else 30.0) or 30.0
            args.out.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(
                str(args.out), cv2.VideoWriter_fourcc(*VIDEO_FOURCC), fps,
                remapper.output_size,
            )
            if not writer.isOpened():
                raise SystemExit(f"[중단] 동영상을 쓸 수 없다: {args.out}")
            print(f"  -> {args.out} ({fps:.1f} fps)")
        else:
            out_dir = args.out
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"  -> {out_dir}")

    window = "remap (q 로 종료)"
    n = 0
    elapsed = 0.0
    frame = first
    index = 0

    try:
        while True:
            start = time.perf_counter()
            out = remapper.apply(frame)
            elapsed += time.perf_counter() - start
            n += 1

            if writer is not None:
                writer.write(out)
            elif out_dir is not None:
                name = images[index].name if images else f"{index:06d}.png"
                cv2.imwrite(str(out_dir / name), out, PNG_WRITE_PARAMS)
            else:
                shown = out
                if args.side_by_side:
                    height = max(frame.shape[0], out.shape[0])
                    pad = lambda im: cv2.copyMakeBorder(
                        im, 0, height - im.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)
                    )
                    shown = cv2.hconcat([pad(frame), pad(out)])
                cv2.imshow(window, fit_window(shown))
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break

            if n % REPORT_EVERY == 0:
                print(f"  {n}프레임  변환 평균 {elapsed / n * 1000:.2f} ms "
                      f"({n / elapsed:.0f} fps 상당)")
            if args.limit and n >= args.limit:
                break

            index += 1
            if cap is not None:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
            else:
                if index >= len(images):
                    break
                frame = cv2.imread(str(images[index]), cv2.IMREAD_COLOR)
                if frame is None:
                    break
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    if n:
        print(f"{n}프레임 처리. 변환 평균 {elapsed / n * 1000:.2f} ms "
              f"({n / elapsed:.0f} fps 상당)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
