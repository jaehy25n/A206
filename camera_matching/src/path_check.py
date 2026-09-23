"""웹앱 촬영본과 기본 카메라 앱 촬영본이 **같은 광학 경로**인지 확인한다.

    python src/path_check.py web.png camera_app.png

왜 필요한가: 같은 camera 0 이어도 앱마다 다른 처리를 거칠 수 있다.
브라우저가 스트림을 크롭하거나(EIS 여유분), 기본 카메라 앱이 자체 보정을 넣으면
같은 렌즈인데도 **유효 초점거리 fx 가 달라진다.** 그러면 웹앱으로 구한 K 를
기본 앱으로 찍은 사진에 쓸 수 없다. "캘리브레이션 경로 = 데이터 수집 경로"를
확인하는 것이 이 도구의 전부다.

무엇을 재는가: 두 사진에서 체커보드를 검출해 **인접 코너의 평균 간격(픽셀)** 을
구하고 그 비율을 본다. 보드와 카메라가 같은 자리에 있었다면, 간격 비율이 곧
배율(~= fx) 비율이다.

전제 (지키지 않으면 결과가 무의미하다):
    - 같은 삼각대, 같은 위치. 카메라를 옮기지 않는다
    - 보드도 같은 자리, 같은 각도
    - 두 장 사이에 zoom 을 건드리지 않는다
    - 두 사진의 해상도가 같아야 한다 (다르면 픽셀 간격을 직접 비교할 수 없다)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from camcal import BoardSpec, find_corners
from camcal.console import setup_console

#: 이 안이면 같은 경로로 본다. 검출 오차와 보드 재배치 오차를 합쳐도 이 정도다.
RATIO_OK_PCT = 1.0

#: 이 이상이면 경고. 3% 차이는 fx 로 치면 약 45 px (fx~=1500 기준) 이고,
#: 그대로 두면 remap 이 눈에 보이게 어긋난다.
RATIO_WARN_PCT = 3.0


def mean_adjacent_spacing(corners: np.ndarray, spec: BoardSpec) -> float:
    """격자에서 가로·세로 **이웃한 코너** 사이 거리의 평균 (픽셀).

    검출 결과는 행 우선 순서이므로 (rows, cols, 2) 로 접은 뒤
    행 방향 diff 와 열 방향 diff 를 각각 잰다. 원근 때문에 위치마다 간격이
    다르지만, 두 사진에서 같은 방식으로 평균 내면 비교할 수 있다.
    """
    grid = np.asarray(corners, dtype=np.float64).reshape(spec.rows, spec.cols, 2)
    horizontal = np.linalg.norm(np.diff(grid, axis=1), axis=2)  # (rows, cols-1)
    vertical = np.linalg.norm(np.diff(grid, axis=0), axis=2)    # (rows-1, cols)
    return float(np.concatenate([horizontal.ravel(), vertical.ravel()]).mean())


def load_and_measure(path: Path, spec: BoardSpec) -> tuple[float, tuple[int, int]]:
    """이미지 한 장 → (평균 인접 간격 px, (width, height))."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"[중단] 이미지를 읽지 못했다: {path}")
    ok, corners = find_corners(img, spec)
    if not ok:
        raise SystemExit(
            f"[중단] 체커보드를 찾지 못했다: {path}\n"
            f"  보드 규격이 {spec.cols}x{spec.rows} 내부 코너가 맞는지, "
            "보드 둘레에 흰 여백이 있는지 확인한다"
        )
    height, width = img.shape[:2]
    return mean_adjacent_spacing(corners, spec), (width, height)


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image_a", type=Path, help="웹앱으로 찍은 사진")
    parser.add_argument("image_b", type=Path, help="기본 카메라 앱으로 찍은 사진")
    parser.add_argument(
        "--board",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "config" / "board.yaml",
    )
    args = parser.parse_args(argv)

    spec = BoardSpec.from_yaml(args.board)
    spacing_a, size_a = load_and_measure(args.image_a, spec)
    spacing_b, size_b = load_and_measure(args.image_b, spec)

    if size_a != size_b:
        print(
            f"[중단] 해상도가 다르다: {size_a[0]}x{size_a[1]} vs {size_b[0]}x{size_b[1]}.\n"
            "  픽셀 간격을 직접 비교할 수 없다. 두 앱 모두 1920x1080 으로 찍는다"
        )
        return 2

    ratio = spacing_a / spacing_b
    diff_pct = abs(ratio - 1.0) * 100

    print()
    print(f"  해상도            {size_a[0]}x{size_a[1]} (양쪽 동일)")
    print(f"  A 웹앱   평균 간격 {spacing_a:.3f} px  ({args.image_a.name})")
    print(f"  B 기본앱 평균 간격 {spacing_b:.3f} px  ({args.image_b.name})")
    print(f"  비율 A/B          {ratio:.5f}  (차이 {diff_pct:.2f}%)")
    print()

    if diff_pct <= RATIO_OK_PCT:
        print(f"  판정: OK - 차이 {diff_pct:.2f}% <= {RATIO_OK_PCT}%. 같은 경로로 본다")
        return 0
    if diff_pct < RATIO_WARN_PCT:
        print(
            f"  판정: 애매 - 차이 {diff_pct:.2f}% ({RATIO_OK_PCT}~{RATIO_WARN_PCT}%).\n"
            "        보드/삼각대를 더 정확히 맞추고 다시 잰다. 그래도 남으면 경로가 다른 것이다"
        )
        return 2
    print(
        f"  판정: 경고 - 차이 {diff_pct:.2f}% >= {RATIO_WARN_PCT}%. **경로가 다르다.**\n"
        f"        A 가 더 {'크게' if ratio > 1 else '작게'} 찍혔다 "
        f"(크롭 또는 zoom 차이). 웹앱으로 구한 K 를 기본 앱 사진에 쓰면 안 된다.\n"
        "        캘리브레이션과 실제 데이터 수집을 같은 앱으로 통일한다"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
