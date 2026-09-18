"""두 카메라의 intrinsics 를 받아 target 공간 결정에 필요한 **숫자만** 낸다.

    python src/run_fov_compare.py results/s10_intrinsics.json results/luaz_intrinsics.json

산출물
    results/reports/fov_compare.md
    results/reports/stretch_*.png   (설계별 국소 확대 히트맵)

**결정은 하지 않는다.** README "미정 결정"의 ②/③ 중 무엇을 고를지는 이 숫자를 보고
사람이 정한다. 이 스크립트는 어느 쪽도 가정하지 않고 양쪽 지표를 모두 낸다.

RMS 는 이 리포트에 넣지 않는다. RMS 는 (K, D) 추정이 그 데이터에 잘 맞았다는 뜻이고
target 적합성과는 무관하다 (README). 추정 품질은 3단계 리포트에서 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from camcal.console import setup_console
from camcal.constants import (
    HEATMAP_DPI,
    HEATMAP_SIZE_IN,
    STRETCH_P95_OK,
    VALID_RATIO_OK,
)
from camcal.remap_metrics import (
    build_map_to_distorted,
    build_map_to_pinhole,
    containment,
    local_stretch,
    valid_mask,
    valid_ratio,
)
from camcal.report import now_iso

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_FILENAME = "fov_compare.md"

#: 게이트 장에 항상 붙는 문구. 게이트를 통과했다고 설계 ② 가 성립하는 것이 아니다.
#: 축별 각도 비교는 후보를 걸러내는 데까지이고, 실제로 모서리까지 채워지는지는
#: valid_ratio 가 판정한다.
GATE_NOTE = "게이트는 선별용. ②의 모서리 커버리지는 valid_ratio로 판정한다."


# --- 입력 ------------------------------------------------------------------


def load_intrinsics(path: Path) -> dict[str, Any]:
    """3단계가 낸 <camera>_intrinsics.json 을 읽고 필요한 필드가 있는지 확인한다."""
    with Path(path).open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    required = ("camera", "K", "D", "resolution", "fov_nominal", "fov_effective")
    missing = [k for k in required if k not in data]
    if missing:
        raise SystemExit(
            f"[중단] {path} 에 필요한 필드가 없다: {missing}. "
            "run_calibrate.py 가 만든 파일인지 확인한다"
        )
    return data


def as_array(value: Any) -> np.ndarray:
    return np.asarray(value, dtype=np.float64)


# --- 한 변환의 지표 ---------------------------------------------------------


def measure(
    label: str,
    ascii_label: str,
    map_x: np.ndarray,
    map_y: np.ndarray,
    src_size: tuple[int, int],
) -> dict[str, Any]:
    """매핑 하나에 대해 valid pixel ratio 와 local stretch 를 잰다.

    Args:
        label: 리포트(마크다운)에 쓸 이름. 한글이어도 된다.
        ascii_label: **그림에 쓸 이름. ASCII 만.** matplotlib 기본 폰트
            (DejaVu Sans)에는 한글 글리프가 없어서 한글을 넣으면 네모(두부)로
            그려진다. 경고는 나오지만 PNG 는 그대로 만들어지므로 조용히 틀린다.
    """
    width_src, height_src = src_size
    mask = valid_mask(map_x, map_y, width_src, height_src)
    stretch, summary = local_stretch(map_x, map_y, mask)
    return {
        "label": label,
        "ascii_label": ascii_label,
        "valid_ratio": valid_ratio(map_x, map_y, width_src, height_src),
        "stretch": summary,
        "_stretch_map": stretch,
        "_mask": mask,
    }


def geometrically_suitable(result: dict[str, Any]) -> bool | None:
    """valid >= 0.98 이고 stretch 95p <= 1.15 인가.

    **"기하학적으로 적합"까지만 말한다.** 실제로 좋은 선택인지는 리샘플링이 모델
    성능에 얼마나 영향을 주는지의 문제이고, 그것은 영상/모델 실험이 답한다.
    """
    p95 = result["stretch"]["p95"]
    if p95 is None:
        return None
    return bool(result["valid_ratio"] >= VALID_RATIO_OK and p95 <= STRETCH_P95_OK)


# --- 그림 ------------------------------------------------------------------


def draw_stretch_heatmap(result: dict[str, Any], out_path: Path) -> Path:
    """국소 확대 히트맵. 무효 영역(검은 영역이 될 곳)은 회색으로 비운다."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stretch = np.array(result["_stretch_map"], dtype=np.float64)
    mask = result["_mask"]
    shown = np.where(mask & np.isfinite(stretch), stretch, np.nan)

    fig, ax = plt.subplots(figsize=HEATMAP_SIZE_IN, dpi=HEATMAP_DPI)
    # 무효 영역(= 검은 영역이 생길 자리)은 회색으로 비운다.
    cmap = plt.get_cmap("magma").with_extremes(bad="0.75")

    finite = shown[np.isfinite(shown)]
    vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
    image = ax.imshow(shown, cmap=cmap, vmin=min(1.0, float(finite.min()) if finite.size else 1.0), vmax=max(vmax, 1.0))
    fig.colorbar(image, ax=ax, label="local stretch (magnification, 1 = identity)")

    # 그림 안의 글자는 ASCII 만 쓴다 (matplotlib 기본 폰트에 한글 글리프가 없다)
    title = result["ascii_label"]
    assert title.isascii(), f"그림 제목에 non-ASCII 가 들어갔다: {title!r}"
    ax.set_title(title)
    ax.set_xlabel("u (px)")
    ax.set_ylabel("v (px)")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# --- 리포트 ----------------------------------------------------------------


def fmt_fov(fov: dict[str, Any]) -> str:
    return f"H {fov['h']:.2f} / V {fov['v']:.2f}"


def metric_rows(result: dict[str, Any]) -> list[str]:
    s = result["stretch"]
    verdict = geometrically_suitable(result)
    mark = {True: "충족", False: "**미충족**", None: "계산 불가"}[verdict]
    return [
        f"| valid pixel ratio | {result['valid_ratio'] * 100:.2f}% | >= {VALID_RATIO_OK * 100:.0f}% |",
        f"| local stretch 중앙값 (면적) | {s['median']:.4f} | - |",
        f"| local stretch 95p (면적) | {s['p95']:.4f} | <= {STRETCH_P95_OK} |",
        f"| local stretch 최대 (면적) | {s['max']:.4f} (u={s['max_at'][0]}, v={s['max_at'][1]}) | - |",
        f"| local stretch 최소 (면적) | {s['min']:.4f} | - |",
        f"| 같은 값의 선형 배율 (한 변) | 중앙값 {s['linear_median']:.4f} / 95p "
        f"{s['linear_p95']:.4f} / 최대 {s['linear_max']:.4f} | - |",
        f"| 두 기준 동시 충족 | {mark} | |",
    ]


def render_report(ctx: dict[str, Any], out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = ctx["src"]
    dst = ctx["dst"]
    gate = ctx["gate"]

    lines: list[str] = []
    add = lines.append

    add("# target 공간 비교 - 숫자만")
    add("")
    add(f"생성 {ctx['created_at']}")
    add("")
    add(f"- 변환할 카메라 (src): **{src['camera']}** · {src['session_id']} · "
        f"{src['resolution'][0]}x{src['resolution'][1]}")
    add(f"- 기준 카메라 (dst):  **{dst['camera']}** · {dst['session_id']} · "
        f"{dst['resolution'][0]}x{dst['resolution'][1]}")
    add("")
    add("이 문서는 **결정하지 않는다.** README 의 미정 결정(② LUAZ 원본 vs ③ 가상 카메라)에 "
        "필요한 숫자만 낸다. 최종 결정은 사람이 한다.")
    add("")

    # --- 1
    add("## 1. 두 카메라의 화각")
    add("")
    add("| 카메라 | fov_nominal (도) | fov_effective alpha=0 (도) |")
    add("|---|---|---|")
    add(f"| {src['camera']} | {fmt_fov(src['fov_nominal'])} | {fmt_fov(src['fov_effective'])} |")
    add(f"| {dst['camera']} | {fmt_fov(dst['fov_nominal'])} | {fmt_fov(dst['fov_effective'])} |")
    add("")
    add("두 값이 다른 것이 정상이다. `fov_nominal` 은 왜곡을 무시한 값이고, "
        "`fov_effective` 는 왜곡을 편 뒤 alpha=0 으로 잘라낸 실제로 쓸 수 있는 화각이다. "
        "배럴 렌즈에서는 effective 가 nominal 보다 **넓다**.")
    add("")
    for data in (src, dst):
        if data.get("fov_degenerate"):
            add(f"> **경고** {data['camera']}: `getOptimalNewCameraMatrix` 가 원본 K 를 그대로 "
                "돌려줬다. fov_effective 와 K' 를 신뢰할 수 없고, 아래 설계 ③ 의 K_target 도 "
                "그 값에서 나온 것이다.")
            add("")

    # --- 2
    add("## 2. 게이트: LUAZ fov ⊆ S10 usable fov")
    add("")
    add(f"두 값 모두 **fov_effective** 로 비교한다 (`fov_nominal` 은 배럴 렌즈의 화각을 "
        "과소평가한다).")
    add("")
    add("| 축 | dst (기준) | src (변환할 쪽) | 여유 (src - dst) | 판정 |")
    add("|---|---|---|---|---|")
    add(f"| H | {dst['fov_effective']['h']:.2f} | {src['fov_effective']['h']:.2f} | "
        f"{gate['h_margin']:+.2f} | {'통과' if gate['h_ok'] else '**불통과**'} |")
    add(f"| V | {dst['fov_effective']['v']:.2f} | {src['fov_effective']['v']:.2f} | "
        f"{gate['v_margin']:+.2f} | {'통과' if gate['v_ok'] else '**불통과**'} |")
    add("")
    if gate["contained"]:
        add(f"**통과.** {dst['camera']} 의 화각이 {src['camera']} 안에 들어온다. "
            "두 설계 모두 기하학적으로 시도할 수 있다.")
    else:
        add(f"> **불통과.** {dst['camera']} 가 {src['camera']} 보다 넓다. "
            f"{src['camera']} 에 없는 영역을 요구하게 되므로 **설계 ② 는 불가능하다.** "
            "설계 ③ 도 `f_target` 을 올려(화각을 좁혀) 다시 봐야 한다. "
            "아무리 정확한 캘리브레이션도 없는 픽셀을 만들지 못한다.")
    add("")
    add(f"> **{GATE_NOTE}**")
    add(">")
    add("> 이 게이트는 H 와 V 를 **축별로** 비교한다. 두 축이 모두 통과해도 화면 "
        "**모서리**는 따로다 - 대각 방향은 H 도 V 도 아니고, 왜곡 때문에 화각의 "
        "경계선이 직사각형이 아니기 때문이다. 모서리가 실제로 채워지는지는 "
        f"4장의 `{src['camera']} -> {dst['camera']} 원본` valid pixel ratio 가 답한다 "
        "(모자란 만큼이 곧 검은 영역이고, 히트맵에서 회색으로 보인다).")
    add("")

    # --- 3, 4
    for key, title, note in (
        ("design3", "3. 설계 ③ 가상 카메라 = target",
         f"`K_target` = {dst['camera']} 의 K' (alpha=0 유도값), `D_target` = **0**. "
         "공통 공간에 왜곡이 없어 직선이 직선으로 남는다. 대신 배포 시 "
         f"{dst['camera']} 영상도 매 프레임 변환해야 한다."),
        ("design2", "4. 설계 ② LUAZ 원본 = target",
         f"`K_target` = {dst['camera']} 의 K, `D_target` = **{dst['camera']} 의 D**. "
         f"{dst['camera']} 영상을 전혀 건드리지 않는다 (배포 시 변환 없음). 대신 "
         f"{src['camera']} 영상에 {dst['camera']} 의 왜곡을 일부러 만들어 넣는다."),
    ):
        add(f"## {title}")
        add("")
        add(note)
        add("")
        for result in ctx[key]:
            add(f"### {result['label']}")
            add("")
            if result.get("_skipped"):
                add(result["_skipped"])
                add("")
                continue
            add("| 지표 | 값 | 기준 |")
            add("|---|---|---|")
            for row in metric_rows(result):
                add(row)
            add("")
            add(f"![{result['label']}]({result['png_name']})")
            add("")
            add("회색은 원본 밖에서 가져와야 하는 영역이다 = 검은 영역이 생길 자리. "
                "밝을수록 확대가 크고, 확대된 곳은 보간으로 뭉개진다.")
            add("")

    # --- 5
    add("## 5. 판정 참고")
    add("")
    add(f"- **기하학적으로 적합**: valid pixel ratio >= {VALID_RATIO_OK * 100:.0f}% "
        f"**이고** local stretch 95p <= {STRETCH_P95_OK}")
    add("- 그 외는 위 수치를 그대로 읽는다. 자동으로 탈락시키지 않는다")
    add("")
    add(f"> stretch 는 **면적 배율**이다 (야코비안 행렬식). 판정선 {STRETCH_P95_OK} 는 "
        f"선형으로는 {STRETCH_P95_OK ** 0.5:.3f} 배이므로, 두 카메라의 초점거리가 "
        "7% 만 달라도 그것만으로 걸린다. 표에 선형 배율을 같이 실어 두었으니 "
        "판정선을 어느 쪽에 걸지는 실측값을 보고 정한다.")
    add("")
    add("| 설계 | 변환 | 기하학적 적합 |")
    add("|---|---|---|")
    for key, name in (("design3", "③ 가상 카메라"), ("design2", "② LUAZ 원본")):
        for result in ctx[key]:
            if result.get("_skipped"):
                mark = "변환 없음"
            else:
                verdict = geometrically_suitable(result)
                mark = {True: "적합", False: "**미달**", None: "계산 불가"}[verdict]
            add(f"| {name} | {result['label']} | {mark} |")
    add("")
    add("**이 표는 결정이 아니다.** '기하학적으로 가능한가'까지만 답한다. "
        "'실제로 좋은 선택인가'는 리샘플링이 모델 성능에 얼마나 영향을 주는지의 "
        "문제이므로 변환 영상의 SSIM / edge / MTF 비교, 필요하면 모델 성능까지 "
        "보고 사람이 정한다 (README 판정 절차 3, 4).")
    add("")

    # --- 6
    add("## 6. 이 리포트에 RMS 가 없는 이유")
    add("")
    add("RMS 는 `(K, D)` 추정이 **그 데이터에 잘 맞았다**는 뜻이고, 그 카메라가 좋은 "
        "target 인지와는 무관하다. RMS 가 낮은 카메라를 target 으로 고를 이유가 없다. "
        "추정 품질은 3단계 리포트(`results/reports/<session_id>.md`)에서 본다.")
    add("")

    path = out_dir / REPORT_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- 조립 ------------------------------------------------------------------


def compare(src: dict[str, Any], dst: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """두 설계의 지표를 모두 계산하고 히트맵을 그린다."""
    src_size = (int(src["resolution"][0]), int(src["resolution"][1]))
    dst_size = (int(dst["resolution"][0]), int(dst["resolution"][1]))
    if src_size != dst_size:
        raise SystemExit(
            f"[중단] 해상도가 다르다: {src['camera']} {src_size} vs {dst['camera']} {dst_size}. "
            "양쪽 모두 1920x1080 으로 찍는 것이 확정 사항이다"
        )
    width, height = dst_size

    K_src, D_src = as_array(src["K"]), as_array(src["D"])
    K_dst, D_dst = as_array(dst["K"]), as_array(dst["D"])
    K_prime = as_array(dst["fov_effective"]["K_prime"])  # 설계 ③ 의 K_target

    # 설계 ③: K_target = dst 의 K', D_target = 0
    design3 = [
        measure(
            f"{src['camera']} -> 가상 카메라 (설계 ③)",
            f"{src['camera']} -> virtual pinhole (design 3)",
            *build_map_to_pinhole(K_src, D_src, K_prime, width, height),
            src_size,
        ),
        measure(
            f"{dst['camera']} -> 가상 카메라 (설계 ③)",
            f"{dst['camera']} -> virtual pinhole (design 3)",
            *build_map_to_pinhole(K_dst, D_dst, K_prime, width, height),
            dst_size,
        ),
    ]

    # 설계 ②: target = dst 원본 (K_dst, D_dst). dst 는 변환하지 않는다.
    design2 = [
        measure(
            f"{src['camera']} -> {dst['camera']} 원본 (설계 ②)",
            f"{src['camera']} -> {dst['camera']} original (design 2)",
            *build_map_to_distorted(K_src, D_src, K_dst, D_dst, width, height),
            src_size,
        ),
        {
            "label": f"{dst['camera']} (설계 ②)",
            "_skipped": (
                f"**변환 없음.** 설계 ② 의 target 이 {dst['camera']} 원본 그 자체이므로 "
                "valid pixel ratio = 1.0, local stretch = 1.0 이다 (계산할 것이 없다). "
                "이것이 설계 ② 의 유일한 실질적 이점이다 - 배포 경로에 remap 단계가 없다."
            ),
        },
    ]

    for key, results in (("design3", design3), ("design2", design2)):
        for i, result in enumerate(results):
            if result.get("_skipped"):
                continue
            name = f"stretch_{key}_{i}.png"
            draw_stretch_heatmap(result, Path(out_dir) / name)
            result["png_name"] = name

    gate = containment(
        (dst["fov_effective"]["h"], dst["fov_effective"]["v"]),
        (src["fov_effective"]["h"], src["fov_effective"]["v"]),
    )

    return {
        "src": src,
        "dst": dst,
        "gate": gate,
        "design3": design3,
        "design2": design2,
        "created_at": now_iso(),
    }


def print_summary(ctx: dict[str, Any], report_path: Path) -> None:
    gate = ctx["gate"]
    src, dst = ctx["src"], ctx["dst"]

    print()
    print(f"  게이트  {dst['camera']} fov_effective ⊆ {src['camera']} fov_effective ? "
          f"{'통과' if gate['contained'] else '불통과'} "
          f"(여유 H {gate['h_margin']:+.2f} / V {gate['v_margin']:+.2f} 도)")
    for key, name in (("design3", "설계 ③"), ("design2", "설계 ②")):
        for result in ctx[key]:
            if result.get("_skipped"):
                print(f"  {name}  {result['label']}: 변환 없음")
                continue
            s = result["stretch"]
            verdict = geometrically_suitable(result)
            mark = {True: "적합", False: "미달", None: "계산 불가"}[verdict]
            print(f"  {name}  {result['label']}: valid {result['valid_ratio'] * 100:.2f}% · "
                  f"stretch 95p {s['p95']:.3f} · 최대 {s['max']:.3f} -> {mark}")
    print("  (기하학적 적합 여부까지만. 최종 결정은 사람이 한다)")
    print(f"  -> {report_path}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("src", type=Path, help="변환할 카메라의 intrinsics.json (보통 s10)")
    parser.add_argument("dst", type=Path, help="기준 카메라의 intrinsics.json (보통 luaz)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "reports",
        help="리포트와 히트맵을 쓸 폴더",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    src = load_intrinsics(args.src)
    dst = load_intrinsics(args.dst)
    print(f"src {src['camera']} ({args.src})  ->  dst {dst['camera']} ({args.dst})")

    ctx = compare(src, dst, args.out_dir)
    report_path = render_report(ctx, args.out_dir)
    print_summary(ctx, report_path)

    if not ctx["gate"]["contained"]:
        print(
            "[경고] 게이트 불통과. 설계 ② 는 불가능하고 설계 ③ 도 f_target 상향이 필요하다",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
