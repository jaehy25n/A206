"""fx 가 실제로 맞는지 **자로 잰 거리**로 검증한다.

    # 자로 잰 거리를 주면 fx 를 검증한다 (이게 본 용도)
    python src/check_align.py --camera s10 --distance-mm 400 사진.png

    # 거리 없이 두 장을 비교 (구현 일관성만 본다, 아래 주의 참고)
    python src/check_align.py luaz.png s10.png

**왜 자가 필요한가.** 체커보드 사진만으로는 fx 의 절대값을 검증할 수 없다.
`solvePnP` 가 거리 Z 를 구할 때 쓰는 K 가 바로 검증하려는 그 K 라서, fx 가 16%
틀려 있으면 Z 도 16% 틀리게 나오고 둘이 상쇄된다. 겉보기 크기와 거리가 **언제나**
일치해 보이므로 아무것도 걸러지지 않는다 (2026-09-21 에 이 함정을 한 번 밟았다).

순환을 끊는 것은 **바깥에서 온 숫자** 하나뿐이다. 카메라 앞면에서 보드까지를 자로
재면 끝난다.

    fx_실측 = s_원본 * Z_실측 / square_mm

이 값이 캘리브레이션의 fx 와 맞으면 그 fx 를 믿을 수 있다. 지금 S10 은 세션에 따라
fx 가 1578 / 1835 로 16% 갈리는데 (result.md 10-2), 이 검사 한 번이면 어느 쪽인지
또는 둘 다 틀렸는지 알 수 있다.

**재는 법**
    1. 보드를 평평한 곳에 고정하고 카메라를 정면으로 둔다 (기울면 오차가 커진다)
    2. 카메라 **렌즈 앞면**에서 보드 면까지를 자로 잰다. mm 로
    3. 그 자세 그대로 한 장 찍는다
    4. 이 도구에 사진과 잰 값을 준다
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from camcal import BoardSpec, find_corners
from camcal.console import setup_console
from camcal.target_space import TARGET_SPACE_FILENAME, TargetSpace

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 라이브 프레임을 받아올 기본 서버.
DEFAULT_SERVER = "https://localhost:8443"

#: 겉보기 비율과 거리 비율이 이만큼 안에서 맞으면 "거리로 설명된다" 로 본다.
#: 라이브 프리뷰는 320x180 이라 코너 정밀도가 낮다. 그 노이즈가 이 정도다.
RATIO_TOLERANCE_PCT = 8.0


def fetch(url: str) -> np.ndarray:
    ctx = ssl._create_unverified_context()
    raw = urllib.request.urlopen(url, context=ctx, timeout=10).read()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"[중단] 이미지를 디코드하지 못했다: {url}")
    return image


def mean_spacing(corners: np.ndarray, spec: BoardSpec) -> float:
    """격자에서 이웃 코너 사이 거리의 평균 (픽셀)."""
    grid = np.asarray(corners, dtype=np.float64).reshape(spec.rows, spec.cols, 2)
    horizontal = np.linalg.norm(np.diff(grid, axis=1), axis=2)
    vertical = np.linalg.norm(np.diff(grid, axis=0), axis=2)
    return float(np.concatenate([horizontal.ravel(), vertical.ravel()]).mean())


def measure(
    image: np.ndarray,
    intrinsics: dict[str, Any],
    target: TargetSpace,
    spec: BoardSpec,
    label: str,
) -> dict[str, Any]:
    """한 장에서 보드를 찾아 거리와 target 공간 칸 간격을 잰다.

    이미지가 원본 해상도가 아니면 K 를 그 배율만큼 줄여 쓴다
    (라이브 화면은 축소본이다).
    """
    ok, corners = find_corners(image, spec)
    if not ok:
        raise SystemExit(
            f"[중단] {label} 에서 체커보드를 찾지 못했다. "
            "보드가 화면 안에 다 들어오고 흐리지 않아야 한다"
        )

    full_w = int(intrinsics["resolution"][0])
    scale = image.shape[1] / full_w
    K = np.asarray(intrinsics["K"], dtype=np.float64).copy()
    K[0, 0] *= scale
    K[1, 1] *= scale
    K[0, 2] *= scale
    K[1, 2] *= scale
    D = np.asarray(intrinsics["D"], dtype=np.float64).ravel()

    ok_pnp, _rvec, tvec = cv2.solvePnP(spec.object_points(), corners.reshape(-1, 1, 2), K, D)
    if not ok_pnp:
        raise SystemExit(f"[중단] {label} 의 자세를 풀지 못했다 (solvePnP 실패)")
    distance = float(np.asarray(tvec).ravel()[2])

    # target 공간으로 옮긴 코너 (해상도 배율은 빼고 각도만 보려고 원본 K_target 을 쓴다)
    undistorted = cv2.undistortPoints(corners.reshape(-1, 1, 2), K, D, P=target.K)

    return {
        "label": label,
        "spacing_view": mean_spacing(corners, spec),
        "spacing_target": mean_spacing(undistorted, spec),
        "distance_mm": distance,
        "image_size": (image.shape[1], image.shape[0]),
        "scale": scale,
    }


def verdict(a: dict[str, Any], b: dict[str, Any], fx_target: float, square_mm: float) -> int:
    """겉보기 비율이 거리 비율로 설명되는가. 0 = 설명됨, 2 = 설명 안 됨."""
    size_ratio = a["spacing_target"] / b["spacing_target"]
    distance_ratio = b["distance_mm"] / a["distance_mm"]  # 가까울수록 크게 보인다
    gap = (size_ratio / distance_ratio - 1.0) * 100

    print()
    print(f"  {'':10s} {'보드까지 거리':>12s} {'칸 간격(target)':>16s} {'s*Z/25':>10s}")
    for m in (a, b):
        implied = m["spacing_target"] * m["distance_mm"] / square_mm
        print(f"  {m['label']:10s} {m['distance_mm']:9.0f} mm {m['spacing_target']:14.2f} px "
              f"{implied:10.1f}")
    print(f"  {'':10s} {'':12s} {'':16s} {'(fx_target ' + f'{fx_target:.0f})':>10s}")
    print()
    print(f"  겉보기 크기 비율  {a['label']}/{b['label']} = {size_ratio:.3f}")
    print(f"  거리 비율        {b['label']}/{a['label']} = {distance_ratio:.3f}")
    print(f"  어긋남           {gap:+.2f}%   (기준 +-{RATIO_TOLERANCE_PCT:.0f}%)")
    print()

    print("  ** 이 비교로는 fx 가 맞는지 알 수 없다. **")
    print("     solvePnP 가 쓰는 K 가 검증 대상인 그 K 라서, fx 가 틀려도 거리가 같이")
    print("     틀리며 상쇄된다. 위 어긋남은 보드 기울기와 코너 노이즈일 뿐이다.")
    print("     fx 를 검증하려면 --distance-mm 로 자로 잰 거리를 준다.")
    if abs(gap) <= RATIO_TOLERANCE_PCT:
        print()
        print("     (구현 일관성은 확인됐다: 겉보기와 거리가 서로 맞는다)")
        return 0
    print()
    print(f"     어긋남이 {gap:+.1f}% 로 크다. 보드가 두 사진에서 많이 다르게 기울어")
    print("     있거나, 코너 검출이 흔들린 것이다. 더 정면으로 다시 찍는다")
    return 2


def verify_fx(
    image: np.ndarray,
    intrinsics: dict[str, Any],
    spec: BoardSpec,
    distance_mm: float,
    label: str,
) -> int:
    """자로 잰 거리로 fx 를 검증한다. **순환이 아닌 유일한 검사.**

        fx_실측 = s_원본 * Z_실측 / square_mm

    s 는 원본 픽셀에서의 칸 간격이고, Z 는 바깥에서 온 값이다.
    """
    ok, corners = find_corners(image, spec)
    if not ok:
        print(f"[중단] {label} 에서 체커보드를 찾지 못했다", file=sys.stderr)
        return 2

    full_w = int(intrinsics["resolution"][0])
    scale = image.shape[1] / full_w
    spacing = mean_spacing(corners, spec) / scale  # 원본 해상도 기준으로 환산
    fx_measured = spacing * distance_mm / spec.square_mm
    fx_calibrated = float(np.asarray(intrinsics["K"])[0, 0])
    gap = (fx_measured / fx_calibrated - 1.0) * 100

    # 보드가 기울면 칸 간격이 cos 만큼 줄어 fx 가 작게 나온다. 기울기를 재서 알린다.
    # (자세 추정은 fx 오차에 둔감하다 - 거리와 달리 각도는 잘 안 흔들린다)
    K = np.asarray(intrinsics["K"], dtype=np.float64).copy()
    K[0, 0] *= scale; K[1, 1] *= scale; K[0, 2] *= scale; K[1, 2] *= scale
    D = np.asarray(intrinsics["D"], dtype=np.float64).ravel()
    _ok, rvec, _tvec = cv2.solvePnP(spec.object_points(), corners.reshape(-1, 1, 2), K, D)
    R, _ = cv2.Rodrigues(rvec)
    tilt_deg = float(np.degrees(np.arccos(np.clip(abs(R[2, 2]), -1.0, 1.0))))

    print()
    print(f"  {label}  (자로 잰 거리 {distance_mm:.0f} mm)")
    print(f"    보드 기울기            {tilt_deg:.1f} deg", end="")
    if tilt_deg > 15:
        shrink = (1 - np.cos(np.radians(tilt_deg))) * 100
        print(f"   **너무 기울었다.** 칸 간격이 약 {shrink:.0f}% 줄어 보여")
        print("                           fx 가 그만큼 작게 나온다. 정면으로 다시 찍는다")
    else:
        print("   (정면에 가깝다)")
    print(f"    칸 간격 (원본 픽셀)   {spacing:.2f} px")
    print(f"    fx 실측  = {spacing:.2f} x {distance_mm:.0f} / {spec.square_mm} "
          f"= **{fx_measured:.1f}**")
    print(f"    fx 캘리브레이션        {fx_calibrated:.1f}")
    print(f"    차이                  {gap:+.2f}%")
    print()
    if abs(gap) <= 5.0:
        print("  판정: **fx 를 믿을 수 있다.** 실측과 5% 안에서 맞는다")
        return 0
    print(f"  판정: **fx 가 {gap:+.1f}% 어긋난다.** 캘리브레이션 값을 그대로 쓰면")
    print(f"        거리·크기 판단이 그만큼 계통 편향된다")
    print("        - 보드가 정면이었는지, 자를 렌즈 앞면부터 쟀는지 먼저 확인한다")
    print("        - 그래도 남으면 그 세션의 fx 가 틀린 것이다")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("images", nargs="*", type=Path, help="luaz 사진, s10 사진 (2장)")
    parser.add_argument(
        "--live", action="store_true", help=f"돌고 있는 서버({DEFAULT_SERVER})에서 한 장씩 받아온다"
    )
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument(
        "--distance-mm", type=float, default=None,
        help="자로 잰 카메라-보드 거리 (mm). 주면 fx 를 검증한다",
    )
    parser.add_argument(
        "--camera", choices=("luaz", "s10"), default=None,
        help="--distance-mm 과 함께. 어느 카메라의 사진인가",
    )
    parser.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "config")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    spec = BoardSpec.from_yaml(args.config_dir / "board.yaml")
    try:
        target = TargetSpace.load(args.results_dir / TARGET_SPACE_FILENAME)
    except FileNotFoundError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    intrinsics = {}
    for camera in ("luaz", "s10"):
        path = args.results_dir / f"{camera}_intrinsics.json"
        if not path.exists():
            print(f"[중단] {path} 가 없다", file=sys.stderr)
            return 2
        with path.open("r", encoding="utf-8") as fp:
            intrinsics[camera] = json.load(fp)

    if args.distance_mm is not None:
        if args.camera is None or len(args.images) != 1:
            print("[중단] --distance-mm 은 --camera 와 사진 한 장이 필요하다",
                  file=sys.stderr)
            return 2
        image = cv2.imread(str(args.images[0]), cv2.IMREAD_COLOR)
        if image is None:
            print(f"[중단] 사진을 읽지 못했다: {args.images[0]}", file=sys.stderr)
            return 2
        return verify_fx(image, intrinsics[args.camera], spec, args.distance_mm, args.camera)

    if args.live:
        print(f"라이브 프레임을 받는다: {args.server}")
        images = {
            "luaz": fetch(f"{args.server}/api/live/luaz.jpg?remap=0"),
            "s10": fetch(f"{args.server}/api/live/s10.jpg?remap=0"),
        }
    else:
        if len(args.images) != 2:
            print("[중단] 사진 2장(luaz, s10)을 주거나 --live 를 쓴다", file=sys.stderr)
            return 2
        images = {
            "luaz": cv2.imread(str(args.images[0]), cv2.IMREAD_COLOR),
            "s10": cv2.imread(str(args.images[1]), cv2.IMREAD_COLOR),
        }
        for name, img in images.items():
            if img is None:
                print(f"[중단] {name} 사진을 읽지 못했다", file=sys.stderr)
                return 2

    print(f"target: {target.describe()}")
    for name, img in images.items():
        print(f"  {name}: {img.shape[1]}x{img.shape[0]}")

    a = measure(images["luaz"], intrinsics["luaz"], target, spec, "luaz")
    b = measure(images["s10"], intrinsics["s10"], target, spec, "s10")
    return verdict(a, b, float(target.K[0, 0]), spec.square_mm)


if __name__ == "__main__":
    raise SystemExit(main())
