"""5단계 - 영상을 공통 target 공간으로 옮긴다.

    # 처음 한 번: 설계와 배율을 명시해 target 공간을 정한다
    python src/run_remap.py --design 3 --f-target-scale 1.10 \\
        --intrinsics results/s10_intrinsics.json \\
        data/s10/<session_id> -o out/s10

    # 이후: results/target_space.json 을 그대로 쓴다
    python src/run_remap.py --intrinsics results/luaz_intrinsics.json \\
        data/luaz/<session_id> -o out/luaz

입력은 이미지 파일 여러 개 또는 세션 디렉토리. 출력은 같은 이름의 PNG 무손실.

**설계는 코드가 고르지 않는다.** `results/target_space.json` 이 없으면 `--design` 을
요구하고 멈춘다. 한 번 정해지면 그 파일이 정본이고, 이후 모든 변환이 같은 공간을 쓴다.

검은 영역에 대하여 - 원본에 없는 부분은 채울 수 없다. 기본은 검은색으로 두고,
`--crop` 을 주면 유효 영역만 남기고 잘라낸다. **없는 픽셀을 만들어내지 않는다.**
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from camcal import Session
from camcal.console import setup_console
from camcal.constants import PNG_WRITE_PARAMS
from camcal.remap_metrics import (
    build_map_to_distorted,
    build_map_to_pinhole,
    crop_box,
    valid_mask,
    valid_ratio,
)
from camcal.target_space import (
    DESIGN_PINHOLE,
    DESIGNS,
    TARGET_SPACE_FILENAME,
    TargetSpace,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 전후 비교본에서 한 장의 가로 크기 (픽셀). 원본 1920 두 장을 붙이면 너무 커진다.
COMPARE_WIDTH = 900

#: remap 보간. INTER_LINEAR 가 기본값이자 가장 안전하다. INTER_CUBIC 은 가장자리에
#: 링잉을 만들고, 그 링잉이 나중에 선명도 측정을 오염시킨다.
REMAP_INTERPOLATION = cv2.INTER_LINEAR

#: 원본에 없는 자리를 채우는 색. 검은색으로 두면 나중에 "여기는 데이터가 없다"를
#: 눈으로도 코드로도 구분할 수 있다.
BORDER_VALUE = (0, 0, 0)


# --- 매핑 --------------------------------------------------------------------


def build_map(
    intrinsics: dict[str, Any], target: TargetSpace
) -> tuple[np.ndarray, np.ndarray]:
    """이 카메라를 target 공간으로 옮기는 맵.

    설계 ③ 이면 목적지에 왜곡이 없으므로 `build_map_to_pinhole`,
    ② 면 목적지가 기준 카메라의 왜곡을 그대로 가지므로 `build_map_to_distorted`.
    """
    K_src = np.asarray(intrinsics["K"], dtype=np.float64)
    D_src = np.asarray(intrinsics["D"], dtype=np.float64).ravel()
    width, height = target.size

    if target.design == DESIGN_PINHOLE:
        return build_map_to_pinhole(K_src, D_src, target.K, width, height)
    return build_map_to_distorted(K_src, D_src, target.K, target.D, width, height)


def remap_image(
    image: np.ndarray,
    map_x: np.ndarray,
    map_y: np.ndarray,
    box: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    warped = cv2.remap(
        image,
        map_x,
        map_y,
        REMAP_INTERPOLATION,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=BORDER_VALUE,
    )
    if box is None:
        return warped
    x, y, w, h = box
    return warped[y : y + h, x : x + w]


def side_by_side(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """전/후를 가로로 붙인다. 높이를 맞추고 가운데 구분선을 넣는다."""
    def fit(img: np.ndarray) -> np.ndarray:
        scale = COMPARE_WIDTH / img.shape[1]
        return cv2.resize(
            img,
            (COMPARE_WIDTH, max(int(round(img.shape[0] * scale)), 1)),
            interpolation=cv2.INTER_AREA,
        )

    a, b = fit(before), fit(after)
    height = max(a.shape[0], b.shape[0])
    canvas = np.zeros((height, COMPARE_WIDTH * 2 + 4, 3), dtype=np.uint8)
    canvas[: a.shape[0], :COMPARE_WIDTH] = a
    canvas[: b.shape[0], COMPARE_WIDTH + 4 :] = b
    canvas[:, COMPARE_WIDTH : COMPARE_WIDTH + 4] = (60, 60, 60)
    for text, x in (("BEFORE", 20), ("AFTER", COMPARE_WIDTH + 24)):
        cv2.putText(canvas, text, (x, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 4)
        cv2.putText(canvas, text, (x, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 1)
    return canvas


# --- 입력 --------------------------------------------------------------------


def collect_inputs(paths: list[Path]) -> list[Path]:
    """이미지 파일 목록. 세션 디렉토리를 주면 **meta.json 이 아는 프레임만** 쓴다.

    폴더를 glob 하지 않는 이유: 세션 폴더에 출처를 알 수 없는 PNG 가 섞여 있던
    적이 있다 (result.md 7-2). meta.json 이 정본이다.
    """
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            meta = path / "meta.json"
            if meta.exists():
                session = Session.open(path)
                out.extend(session.frame_path(f) for f in session.frames)
            else:
                out.extend(sorted(path.glob("*.png")))
        elif path.exists():
            out.append(path)
        else:
            raise SystemExit(f"[중단] 입력을 찾을 수 없다: {path}")
    if not out:
        raise SystemExit("[중단] 변환할 이미지가 없다")
    return out


# --- CLI ---------------------------------------------------------------------


def resolve_target(args: argparse.Namespace, results_dir: Path) -> TargetSpace:
    """target 공간을 읽거나, --design 이 주어졌으면 새로 정해 저장한다."""
    path = results_dir / TARGET_SPACE_FILENAME

    if args.design is None:
        target = TargetSpace.load(path)
        print(f"target 공간 (기존): {target.describe()}")
        return target

    if args.reference is None:
        raise SystemExit(
            "[중단] --design 으로 target 공간을 새로 정하려면 기준 카메라의 "
            "intrinsics 가 필요하다: --reference results/luaz_intrinsics.json"
        )
    import json

    with Path(args.reference).open("r", encoding="utf-8") as fp:
        reference = json.load(fp)

    target = TargetSpace.from_intrinsics(
        reference, design=args.design, f_target_scale=args.f_target_scale, note=args.note
    )
    if path.exists():
        existing = TargetSpace.load(path)
        print(f"[경고] target 공간을 덮어쓴다.\n  이전: {existing.describe()}\n"
              f"  새로: {target.describe()}\n"
              "  이전 공간으로 변환해 둔 결과물은 새 것과 섞을 수 없다",
              file=sys.stderr)
    target.save(path)
    print(f"target 공간 (새로 정함 -> {path}): {target.describe()}")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("inputs", type=Path, nargs="+", help="이미지 파일 또는 세션 디렉토리")
    parser.add_argument(
        "--intrinsics", type=Path, required=True, help="변환할 카메라의 intrinsics.json"
    )
    parser.add_argument("-o", "--out-dir", type=Path, required=True, help="출력 폴더")
    parser.add_argument(
        "--design",
        type=int,
        choices=DESIGNS,
        default=None,
        help="target 공간을 새로 정한다 (2=LUAZ 원본, 3=가상 카메라). "
             "생략하면 results/target_space.json 을 쓴다",
    )
    parser.add_argument(
        "--reference", type=Path, default=None, help="--design 과 함께. 기준 카메라 intrinsics"
    )
    parser.add_argument(
        "--f-target-scale", type=float, default=1.0, help="--design 3 전용. K' 에 곱할 배율"
    )
    parser.add_argument("--note", default="", help="target_space.json 에 남길 메모")
    parser.add_argument(
        "--crop", action="store_true", help="검은 영역을 잘라내고 유효 영역만 남긴다"
    )
    parser.add_argument(
        "--compare", action="store_true", help="전/후를 나란히 붙인 비교본도 저장한다"
    )
    parser.add_argument(
        "--results-dir", type=Path, default=PROJECT_ROOT / "results",
        help="target_space.json 위치 (기본 results/)",
    )
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N 장만 변환")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    import json

    with Path(args.intrinsics).open("r", encoding="utf-8") as fp:
        intrinsics = json.load(fp)

    try:
        target = resolve_target(args, Path(args.results_dir))
    except FileNotFoundError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    if tuple(intrinsics["resolution"]) != target.size:
        raise SystemExit(
            f"[중단] 해상도가 target 과 다르다: {intrinsics['camera']} "
            f"{intrinsics['resolution']} vs target {list(target.size)}"
        )

    map_x, map_y = build_map(intrinsics, target)
    width_src, height_src = (
        int(intrinsics["resolution"][0]),
        int(intrinsics["resolution"][1]),
    )
    mask = valid_mask(map_x, map_y, width_src, height_src)
    ratio = valid_ratio(map_x, map_y, width_src, height_src)

    box = None
    if args.crop:
        box = crop_box(mask)
        print(f"crop: ({box[0]}, {box[1]}) 에서 {box[2]}x{box[3]} "
              f"(원래 {target.size[0]}x{target.size[1]})")

    print(f"{intrinsics['camera']} -> target · valid pixel ratio {ratio * 100:.2f}%"
          + ("" if args.crop else f" (검은 영역 {100 - ratio * 100:.2f}%)"))

    files = collect_inputs(args.inputs)
    if args.limit:
        files = files[: args.limit]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    compare_dir = out_dir / "compare"
    if args.compare:
        compare_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for path in files:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise SystemExit(f"[중단] 이미지를 읽지 못했다: {path}")
        if (image.shape[1], image.shape[0]) != (width_src, height_src):
            raise SystemExit(
                f"[중단] 해상도가 intrinsics 와 다르다: {path} "
                f"{image.shape[1]}x{image.shape[0]} != {width_src}x{height_src}"
            )

        warped = remap_image(image, map_x, map_y, box)
        out_path = out_dir / path.name
        if not cv2.imwrite(str(out_path), warped, PNG_WRITE_PARAMS):
            raise SystemExit(f"[중단] 저장 실패: {out_path}")
        if args.compare:
            cv2.imwrite(str(compare_dir / path.name), side_by_side(image, warped))
        written += 1

    print(f"{written}장 변환 -> {out_dir}")
    if args.compare:
        print(f"비교본 -> {compare_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
