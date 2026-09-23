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
    F_TARGET_SCAN_MAX,
    F_TARGET_SCAN_STEP,
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
    scale_focal,
    valid_mask,
    valid_ratio,
)
from camcal.fov import fov_nominal
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


# --- f_target 탐색 (설계 ③) --------------------------------------------------


def scan_f_target(
    src: dict[str, Any],
    dst: dict[str, Any],
    step: float = F_TARGET_SCAN_STEP,
    max_scale: float = F_TARGET_SCAN_MAX,
    target_valid: float = VALID_RATIO_OK,
) -> dict[str, Any]:
    """f_target 을 step 씩 올리며 valid pixel ratio 가 기준을 넘는 **최소 배율**을 찾는다.

    설계 ③ 전용이다. 목적지가 가상 카메라라 화각을 우리가 정할 수 있고,
    좁힐수록 검은 영역이 준다.

    **최소값을 찾는 이유**: 더 올리면 valid 는 계속 좋아지지만 화각을 그만큼 버리고
    국소 확대가 커진다. 기준을 넘기는 가장 덜 좁힌 값이 손해가 가장 적다.

    두 변환(src -> target, dst -> target) **모두** 기준을 넘어야 통과로 본다.

    Returns:
        {"rows": [...], "chosen": 배율 | None, "target_valid": ...}
        rows 의 각 항목: scale, fx, hfov, valid_src, valid_dst, stretch95_src,
        stretch95_dst, ok
    """
    width, height = int(dst["resolution"][0]), int(dst["resolution"][1])
    K_src, D_src = as_array(src["K"]), as_array(src["D"])
    K_dst, D_dst = as_array(dst["K"]), as_array(dst["D"])
    K_base = as_array(dst["fov_effective"]["K_prime"])

    rows: list[dict[str, Any]] = []
    chosen: float | None = None

    scale = 1.0
    while scale <= max_scale + 1e-9:
        K_target = scale_focal(K_base, scale)
        results = []
        for K, D, size in (
            (K_src, D_src, (int(src["resolution"][0]), int(src["resolution"][1]))),
            (K_dst, D_dst, (width, height)),
        ):
            map_x, map_y = build_map_to_pinhole(K, D, K_target, width, height)
            mask = valid_mask(map_x, map_y, size[0], size[1])
            _stretch, summary = local_stretch(map_x, map_y, mask)
            results.append((valid_ratio(map_x, map_y, size[0], size[1]), summary["p95"]))

        (valid_src, p95_src), (valid_dst, p95_dst) = results
        ok = valid_src >= target_valid and valid_dst >= target_valid
        rows.append({
            "scale": round(scale, 4),
            "fx": float(K_target[0, 0]),
            "hfov": fov_nominal(K_target, width, height)[0],
            "valid_src": valid_src,
            "valid_dst": valid_dst,
            "stretch95_src": p95_src,
            "stretch95_dst": p95_dst,
            "ok": ok,
        })
        if ok and chosen is None:
            chosen = round(scale, 4)
            break
        scale += step

    return {
        "rows": rows,
        "chosen": chosen,
        "target_valid": target_valid,
        "step": step,
        "max_scale": max_scale,
        "K_base_fx": float(K_base[0, 0]),
    }


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
         f"`K_target` = {dst['camera']} 의 K' (alpha=0 유도값) x **{ctx['f_target_scale']:.2f}**, "
         f"fx = {ctx['K_target'][0][0]:.1f}, 화각 H {ctx['target_fov']['h']:.2f} / "
         f"V {ctx['target_fov']['v']:.2f} 도. `D_target` = **0**. "
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

    # --- 4-1 f_target 탐색
    scan = ctx.get("scan")
    if scan:
        add("## 4-1. f_target 탐색 (설계 ③ 전용)")
        add("")
        add(f"설계 ③ 은 목적지가 가상 카메라라 **화각을 우리가 정할 수 있다.** "
            f"`f_target` 을 {scan['step'] * 100:.0f}% 씩 올리며 valid pixel ratio 가 "
            f"{scan['target_valid'] * 100:.0f}% 를 넘는 **최소 배율**을 찾았다.")
        add("")
        add("| 배율 | fx | 화각 H (도) | valid src | valid dst | stretch 95p src | 판정 |")
        add("|---|---|---|---|---|---|---|")
        for row in scan["rows"]:
            add(f"| {row['scale']:.2f} | {row['fx']:.1f} | {row['hfov']:.2f} | "
                f"{row['valid_src'] * 100:.2f}% | {row['valid_dst'] * 100:.2f}% | "
                f"{row['stretch95_src']:.4f} | {'**통과**' if row['ok'] else '-'} |")
        add("")
        if scan["chosen"] is None:
            add(f"> **{scan['max_scale']:.2f} 배까지 올려도 valid 기준을 넘지 못했다.** "
                "화각을 그 이상 버리는 것은 의미가 없다. 재촬영이 필요하다.")
        else:
            add(f"**선택: 배율 {scan['chosen']:.2f}.** 기준을 넘기는 가장 덜 좁힌 값이다. "
                "더 올리면 valid 는 계속 좋아지지만 화각을 그만큼 버린다.")
        add("")
        add("> **valid 와 stretch 는 반대로 움직인다.** f_target 을 올리면 같은 화면을 "
            "더 좁은 각도로 채우게 되므로 국소 확대가 **커진다**. 위 표에서 배율이 "
            "오를수록 stretch 95p 가 함께 오르는 것이 그것이다. "
            "검은 영역을 줄이는 대가로 확대를 받는 거래이므로, 둘 다 만족하는 값이 "
            "없을 수 있다.")
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


def compare(
    src: dict[str, Any],
    dst: dict[str, Any],
    out_dir: Path,
    f_target_scale: float = 1.0,
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """두 설계의 지표를 모두 계산하고 히트맵을 그린다.

    Args:
        f_target_scale: 설계 ③ 의 K_target 초점거리 배율 (1.0 = dst 의 K' 그대로).
            올리면 화각이 좁아져 valid 가 오르고 stretch 가 커진다.
    """
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
    K_prime_base = as_array(dst["fov_effective"]["K_prime"])
    K_prime = scale_focal(K_prime_base, f_target_scale)  # 설계 ③ 의 K_target

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

    hfov_t, vfov_t = fov_nominal(K_prime, width, height)
    return {
        "src": src,
        "dst": dst,
        "gate": gate,
        "design3": design3,
        "design2": design2,
        "f_target_scale": f_target_scale,
        "K_target": K_prime.tolist(),
        "K_target_base_fx": float(K_prime_base[0, 0]),
        "target_fov": {"h": hfov_t, "v": vfov_t},
        "scan": scan,
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
        "--f-target-scale",
        type=float,
        default=1.0,
        help="설계 ③ 의 K_target 초점거리 배율 (1.0 = LUAZ 의 K' 그대로). "
             "올리면 화각이 좁아져 valid 가 오르고 stretch 가 커진다",
    )
    parser.add_argument(
        "--scan-f-target",
        action="store_true",
        help=f"f_target 을 {F_TARGET_SCAN_STEP * 100:.0f}%% 씩 올리며 "
             f"valid >= {VALID_RATIO_OK * 100:.0f}%% 인 최소 배율을 찾아 그 값으로 리포트를 낸다",
    )
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

    scan = None
    scale = args.f_target_scale
    if args.scan_f_target:
        print("f_target 탐색 중...")
        scan = scan_f_target(src, dst)
        for row in scan["rows"]:
            print(f"  배율 {row['scale']:.2f}  fx {row['fx']:7.1f}  H {row['hfov']:5.2f} deg  "
                  f"valid src {row['valid_src'] * 100:6.2f}%  dst {row['valid_dst'] * 100:6.2f}%  "
                  f"stretch95 src {row['stretch95_src']:.4f}"
                  + ("  <- 선택" if row["ok"] else ""))
        if scan["chosen"] is None:
            print(f"[경고] {scan['max_scale']:.2f} 배까지도 valid 기준 미달. 재촬영이 필요하다",
                  file=sys.stderr)
        else:
            scale = scan["chosen"]

    ctx = compare(src, dst, args.out_dir, f_target_scale=scale, scan=scan)
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
