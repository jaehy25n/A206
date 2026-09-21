"""RMS 하나로 판단하지 않기 위한 분석과 리포트 렌더링.

RMS 가 낮다는 것은 "이 데이터에 잘 맞췄다"는 뜻일 뿐이다. 다음 네 가지가 같이
나와야 그 K, D 를 믿을지 판단할 수 있다 (CLAUDE.md 6절).

    1. 공간 분포     오차가 화면 한쪽에 몰려 있나            spatial_error_grid
    2. 잔차 방향성   잔차가 방사 방향으로 쏠려 있나          residual_radiality
    3. 파라미터 안정성 부분집합마다 fx 가 흔들리나            calibrate.stability
    4. 홀드아웃      처음 보는 사진에도 통하나               calibrate.holdout_rms

여기에 상식 범위 확인(sanity_check)을 더해 리포트로 만든다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .constants import (
    HOLDOUT_RATIO_WARN,
    RADIALITY_WARN_PX,
    RMS_BAD_PX,
    RMS_GOOD_PX,
    RMS_SUSPECT_PX,
    SANITY_FXFY_REL_TOL,
    SANITY_PRINCIPAL_TOL_PX,
    SPATIAL_GRID,
)

#: 잔차 벡터 그림에서 잔차를 몇 배로 그릴지. 0.3 px 짜리를 그대로 그리면 점으로만 보인다.
RESIDUAL_ARROW_SCALE = 200.0

#: 그림 크기 (인치)와 해상도.
FIGURE_SIZE_IN = (10.0, 5.6)
FIGURE_DPI = 110


# --- 1. 공간 분포 -----------------------------------------------------------


def spatial_error_grid(
    residuals: np.ndarray,
    points: np.ndarray,
    image_size: tuple[int, int],
    grid: int = SPATIAL_GRID,
) -> dict[str, Any]:
    """화면을 grid x grid 로 나누고 셀별 평균 잔차 크기 (픽셀).

    오차가 특정 셀에 몰려 있으면 전체 RMS 가 낮아도 그 영역의 K, D 는 못 믿는다.
    보통 가장자리 셀에 몰리는데, 그 자리에 데이터가 적거나 왜곡 모델이 부족한 것이다.

    Args:
        residuals: (N, 2) 재투영 - 관측.
        points: (N, 2) 관측 픽셀 좌표 (u, v).
        image_size: (width, height). 격자 경계는 **이미지 크기**로 나눈다.
            점들의 bounding box 로 나누면 데이터에 따라 격자가 움직여 세션끼리
            비교할 수 없게 된다.

    Returns:
        {"grid", "mean": [[...]] (셀별 평균, 데이터 없으면 None),
         "count": [[...]], "max_cell", "max_mean", "empty_cells"}
    """
    res = np.asarray(residuals, dtype=np.float64).reshape(-1, 2)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(res) != len(pts):
        raise ValueError(f"residuals 와 points 의 길이가 다르다: {len(res)} vs {len(pts)}")

    width, height = image_size
    magnitude = np.linalg.norm(res, axis=1)

    col = np.clip((pts[:, 0] * grid / width).astype(int), 0, grid - 1)
    row = np.clip((pts[:, 1] * grid / height).astype(int), 0, grid - 1)

    mean: list[list[float | None]] = []
    count: list[list[int]] = []
    best = (-1.0, None)
    empty: list[tuple[int, int]] = []
    for r in range(grid):
        mean_row: list[float | None] = []
        count_row: list[int] = []
        for c in range(grid):
            hit = (row == r) & (col == c)
            n = int(hit.sum())
            count_row.append(n)
            if n == 0:
                mean_row.append(None)
                empty.append((c, r))
                continue
            value = float(magnitude[hit].mean())
            mean_row.append(value)
            if value > best[0]:
                best = (value, (c, r))
        mean.append(mean_row)
        count.append(count_row)

    return {
        "grid": grid,
        "mean": mean,
        "count": count,
        "max_cell": list(best[1]) if best[1] is not None else None,
        "max_mean": best[0] if best[0] >= 0 else None,
        "empty_cells": [list(c) for c in empty],
    }


# --- 2. 잔차 방향성 ---------------------------------------------------------


def residual_radiality(
    residuals: np.ndarray,
    points: np.ndarray,
    principal_point: tuple[float, float],
) -> dict[str, float]:
    """잔차가 방사 방향(주점에서 바깥)으로 쏠려 있는 정도.

    각 점에서 주점으로부터의 단위 방사 벡터와 잔차의 내적을 평균한다.
    - 0 근처: 잔차가 무작위. 정상이다
    - 크게 양수/음수: 잔차가 방사 방향으로 일정하게 치우쳐 있다.
      **왜곡 모델이 데이터를 못 따라갔다는 신호** (차수를 올리거나, 가장자리
      데이터를 더 찍거나)

    주점 위에 정확히 놓인 점은 방사 방향이 정의되지 않으므로 제외한다.

    Returns:
        {"mean_dot", "abs_mean_dot", "mean_magnitude", "n_used"}
        mean_magnitude 는 잔차 크기 평균 - 내적을 해석할 때의 척도다
        (잔차 자체가 크면 내적도 커진다).
    """
    res = np.asarray(residuals, dtype=np.float64).reshape(-1, 2)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    cx, cy = principal_point

    radial = pts - np.array([cx, cy], dtype=np.float64)
    norm = np.linalg.norm(radial, axis=1)
    usable = norm > 1e-9
    unit = radial[usable] / norm[usable][:, None]

    dots = np.sum(res[usable] * unit, axis=1)
    return {
        "mean_dot": float(dots.mean()) if len(dots) else 0.0,
        "abs_mean_dot": float(np.abs(dots.mean())) if len(dots) else 0.0,
        "mean_magnitude": float(np.linalg.norm(res, axis=1).mean()),
        "n_used": int(usable.sum()),
    }


# --- 3. 상식 범위 -----------------------------------------------------------


def sanity_check(
    K: np.ndarray, D: np.ndarray, width: int, height: int
) -> list[str]:
    """K, D 가 상식 범위 안인지. 벗어난 항목의 설명 목록을 돌려준다.

    여기서 걸리는 값은 "추정이 수렴은 했는데 물리적으로 이상한" 경우다.
    RMS 는 낮은데 fx 가 fy 의 1.3 배라면 데이터가 파라미터를 결정하지 못한 것이다.
    """
    K = np.asarray(K, dtype=np.float64)
    D = np.asarray(D, dtype=np.float64).ravel()
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    warnings: list[str] = []

    rel = abs(fx - fy) / fx if fx else float("inf")
    if rel > SANITY_FXFY_REL_TOL:
        warnings.append(
            f"fx 와 fy 차이가 {rel * 100:.2f}% (기준 {SANITY_FXFY_REL_TOL * 100:.0f}%). "
            f"fx={fx:.1f}, fy={fy:.1f}. 정사각 픽셀 센서라면 1% 안에 들어와야 한다"
        )

    dx = abs(cx - width / 2.0)
    if dx > SANITY_PRINCIPAL_TOL_PX:
        warnings.append(
            f"cx 가 화면 중심에서 {dx:.1f} px 벗어났다 (기준 {SANITY_PRINCIPAL_TOL_PX:.0f} px). "
            f"cx={cx:.1f}, 중심={width / 2:.1f}. 크롭됐거나 추정이 불안정하다"
        )
    dy = abs(cy - height / 2.0)
    if dy > SANITY_PRINCIPAL_TOL_PX:
        warnings.append(
            f"cy 가 화면 중심에서 {dy:.1f} px 벗어났다 (기준 {SANITY_PRINCIPAL_TOL_PX:.0f} px). "
            f"cy={cy:.1f}, 중심={height / 2:.1f}"
        )

    if len(D) >= 1 and D[0] > 0:
        warnings.append(
            f"k1 = {D[0]:.5f} 로 양수다 (핀쿠션). 광각 렌즈는 보통 배럴(k1 < 0)이다. "
            "보드가 화면 가장자리까지 오지 않았을 때 자주 나온다"
        )

    return warnings


def rms_band(rms: float) -> str:
    """RMS 를 말로 옮긴다 (CLAUDE.md 6절의 구간)."""
    if rms < RMS_GOOD_PX:
        return "정상"
    if rms < RMS_SUSPECT_PX:
        return "설명 안 되는 요인 있음"
    if rms < RMS_BAD_PX:
        return "나쁨"
    return "구조적 문제"


def collect_warnings(report: dict[str, Any]) -> list[str]:
    """리포트 전체를 보고 경고를 모은다 (sanity + RMS + 홀드아웃 + 방사성)."""
    warnings = list(report.get("sanity", []))

    rms_train = report["rms_train"]
    if rms_train >= RMS_SUSPECT_PX:
        warnings.append(f"학습 RMS {rms_train:.3f} px - {rms_band(rms_train)}")

    rms_holdout = report.get("rms_holdout")
    if rms_holdout is not None and rms_train > 0:
        ratio = rms_holdout / rms_train
        if ratio > HOLDOUT_RATIO_WARN:
            warnings.append(
                f"홀드아웃 RMS 가 학습의 {ratio:.2f}배 "
                f"({rms_holdout:.3f} vs {rms_train:.3f} px, 기준 {HOLDOUT_RATIO_WARN}배). "
                "과적합이거나 세션 안에 조건이 다른 사진이 섞여 있다"
            )

    radiality = report.get("radiality")
    if radiality and radiality["abs_mean_dot"] > RADIALITY_WARN_PX:
        warnings.append(
            f"잔차가 방사 방향으로 평균 {radiality['mean_dot']:+.3f} px 치우쳐 있다 "
            f"(기준 {RADIALITY_WARN_PX} px). 왜곡 모델이 데이터를 못 따라갔을 수 있다"
        )

    stab = report.get("stability")
    if stab and stab.get("requested_subset", 0) > stab.get("subset", 0):
        warnings.append(
            f"안정성 검사 부분집합이 {stab['requested_subset']}장에서 {stab['subset']}장으로 "
            f"줄었다 (학습이 {report['n_train']}장뿐). 부분집합이 작을수록 표준편차가 "
            "과장되므로 값을 그대로 믿지 말고, 더 찍어서 다시 본다"
        )

    if report.get("fov_degenerate"):
        warnings.append(
            "fov_effective 가 계산되지 않았다 (getOptimalNewCameraMatrix 가 원본 K 를 "
            "그대로 반환). 왜곡이 너무 강해 유효 영역을 못 찾은 경우다. "
            "표에 적힌 effective 값은 nominal 과 같은 값일 뿐 의미가 없다"
        )

    spatial = report.get("spatial")
    if spatial and spatial.get("empty_cells"):
        warnings.append(
            f"{spatial['grid']}x{spatial['grid']} 격자 중 {len(spatial['empty_cells'])}칸에 "
            "코너가 한 개도 없다. 그 영역의 왜곡은 추정된 것이 아니라 외삽된 값이다"
        )

    return warnings


# --- 그림 ------------------------------------------------------------------


def draw_residuals(
    residuals: np.ndarray,
    points: np.ndarray,
    image_size: tuple[int, int],
    out_path: Path,
    grid: int = SPATIAL_GRID,
) -> Path:
    """잔차 벡터 그림을 PNG 로 저장한다.

    잔차를 RESIDUAL_ARROW_SCALE 배 확대해 그린다. 눈으로 볼 때 찾는 것:
        - 화살표가 사방으로 흩어져 있으면 정상
        - 가장자리에서 일제히 바깥(또는 안쪽)을 향하면 왜곡 모델 부족
        - 한 덩어리가 같은 방향이면 그 사진 한 장이 문제 (흔들림, 보드 휨)
    """
    import matplotlib

    matplotlib.use("Agg")  # 창을 띄우지 않는다 (서버/CI 에서도 돌아야 한다)
    import matplotlib.pyplot as plt

    res = np.asarray(residuals, dtype=np.float64).reshape(-1, 2)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    width, height = image_size
    magnitude = np.linalg.norm(res, axis=1)

    fig, ax = plt.subplots(figsize=FIGURE_SIZE_IN, dpi=FIGURE_DPI)
    quiver = ax.quiver(
        pts[:, 0],
        pts[:, 1],
        res[:, 0] * RESIDUAL_ARROW_SCALE,
        res[:, 1] * RESIDUAL_ARROW_SCALE,
        magnitude,
        angles="xy",
        scale_units="xy",
        scale=1.0,
        cmap="viridis",
        width=0.0025,
    )
    fig.colorbar(quiver, ax=ax, label="residual magnitude (px)")

    for i in range(1, grid):
        ax.axvline(width * i / grid, color="0.85", linewidth=0.6, zorder=0)
        ax.axhline(height * i / grid, color="0.85", linewidth=0.6, zorder=0)

    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)  # 픽셀 좌표계: v 는 아래로 증가
    ax.set_aspect("equal")
    ax.set_xlabel("u (px)")
    ax.set_ylabel("v (px)")
    ax.set_title(f"reprojection residuals (x{RESIDUAL_ARROW_SCALE:.0f})")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# --- 렌더 ------------------------------------------------------------------


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _grid_table(spatial: dict[str, Any]) -> str:
    """셀별 평균 잔차를 마크다운 표로. 괄호 안은 그 셀의 코너 수."""
    grid = spatial["grid"]
    header = "| v\\u | " + " | ".join(f"{c}" for c in range(grid)) + " |"
    sep = "|---" * (grid + 1) + "|"
    lines = [header, sep]
    for r in range(grid):
        cells = []
        for c in range(grid):
            mean = spatial["mean"][r][c]
            count = spatial["count"][r][c]
            cells.append("**비어 있음**" if mean is None else f"{mean:.3f} ({count})")
        lines.append(f"| **{r}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render(report: dict[str, Any], out_dir: Path) -> Path:
    """리포트 dict -> results/reports/<session_id>.md (+ 잔차 그림 PNG).

    리포트에는 "RMS 만 보지 말 것" 네 항목이 전부 들어간다.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session_id = report["session_id"]
    md_path = out_dir / f"{session_id}.md"

    png_name = f"{session_id}_residuals.png"
    draw_residuals(
        report["_residuals"],
        report["_points"],
        tuple(report["resolution"]),
        out_dir / png_name,
    )

    K = np.asarray(report["K"], dtype=np.float64)
    D = np.asarray(report["D"], dtype=np.float64).ravel()
    stab = report["stability"]
    spatial = report["spatial"]
    radiality = report["radiality"]
    warnings = report["warnings"]

    lines: list[str] = []
    add = lines.append

    add(f"# 캘리브레이션 리포트 - {session_id}")
    add("")
    add(f"카메라 `{report['camera']}` · 해상도 {report['resolution'][0]}x{report['resolution'][1]} · "
        f"생성 {report['created_at']}")
    add("")
    add(f"학습 {report['n_train']}장 / 홀드아웃 {report['n_holdout']}장 · 분할 시드 `{report['seed']}` "
        "(같은 시드면 같은 분할)")
    add("")

    if report.get("n_sessions", 1) > 1:
        add(f"세션 {report['n_sessions']}개를 합쳐 추정했다.")
        add("")
        for path in report.get("session_paths", []):
            add(f"- `{path}`")
        add("")

    for session_id, extra in (report.get("orphan_pngs") or {}).items():
        add(f"> **경고** `{session_id}/frames` 에 meta.json 이 모르는 PNG 가 "
            f"{len(extra)}개 있다 ({', '.join(extra[:5])}"
            f"{' ...' if len(extra) > 5 else ''}). 출처를 알 수 없어 **쓰지 않았다.** "
            "다른 세션에서 복사됐거나 저장 중 기록이 실패한 파일이다.")
        add("")

    if warnings:
        add("## 경고")
        add("")
        for w in warnings:
            add(f"- {w}")
    else:
        add("## 경고")
        add("")
        add("- 없음")
    add("")

    if report.get("frame_rms"):
        add("## 0. 프레임별 재투영 오차와 이상치 제거")
        add("")
        out = report["outliers"]
        add(f"전체 {report['n_detected']}장으로 1차 추정한 RMS 는 "
            f"**{report['rms_all_frames']:.4f} px** 이었다. 이 추정의 목적은 K 가 아니라 "
            "프레임별 오차를 보는 것이다.")
        add("")
        if out.get("skipped"):
            add("이상치 제거를 하지 않았다 (`--keep-all`). 아래 표는 참고용이다.")
        else:
            add("| 항목 | 값 |")
            add("|---|---|")
            add(f"| 중앙값 | {out['median']:.4f} px |")
            add(f"| MAD | {out['mad']:.4f} px |")
            add(f"| robust sigma (1.4826*MAD) | {out['sigma']:.4f} px |")
            add(f"| 경계 (중앙값 + {out['k']}*sigma, 최소 0.3) | **{out['threshold']:.4f} px** |")
            add(f"| 제거 / 남김 | {out['n_dropped']}장 / {out['n_kept']}장 |")
            add("")
            add("평균과 표준편차 대신 중앙값과 MAD 를 쓴다. 이상치가 평균과 표준편차를 "
                "끌고 가서 자기 자신을 정상으로 만들어 버리기 때문이다.")
        add("")
        if out.get("capped_reason"):
            add(f"> **{out['capped_reason']}**")
            add("")
        if out.get("dropped"):
            add("### 제거된 프레임")
            add("")
            add("| 프레임 | RMS (px) |")
            add("|---|---|")
            for item in out["dropped"]:
                add(f"| {item['frame']} | {item['rms']:.4f} |")
            add("")
            add("제거해도 **파일은 그대로 남는다.** meta.json 도 건드리지 않는다. "
                "이 추정에서 빼기만 한 것이다.")
            add("")

        add("### 전체 프레임 (오차 큰 순)")
        add("")
        dropped_labels = {item["frame"] for item in out.get("dropped", [])}
        add("| 프레임 | RMS (px) | 사용 |")
        add("|---|---|---|")
        for label, value in sorted(
            report["frame_rms"].items(), key=lambda kv: -kv[1]
        ):
            mark = "**제외**" if label in dropped_labels else "사용"
            add(f"| {label} | {value:.4f} | {mark} |")
        add("")

    add("## 1. 추정값")
    add("")
    add("| 항목 | 값 |")
    add("|---|---|")
    add(f"| fx, fy | {K[0, 0]:.2f}, {K[1, 1]:.2f} |")
    add(f"| cx, cy | {K[0, 2]:.2f}, {K[1, 2]:.2f} (화면 중심 "
        f"{report['resolution'][0] / 2:.1f}, {report['resolution'][1] / 2:.1f}) |")
    add(f"| D ({report['D_model']}) | {', '.join(f'{v:.6f}' for v in D)} |")
    add(f"| fov_nominal | H {report['fov_nominal']['h']:.2f} deg, "
        f"V {report['fov_nominal']['v']:.2f} deg |")
    add(f"| fov_effective (alpha=0) | H {report['fov_effective']['h']:.2f} deg, "
        f"V {report['fov_effective']['v']:.2f} deg |")
    add("")
    add("`fov_nominal` 과 `fov_effective` 는 다른 값이 정상이다. 앞은 왜곡을 무시한 값, "
        "뒤는 왜곡을 펴고 검은 여백을 잘라낸 뒤 실제로 쓸 수 있는 화각이다.")
    add("")

    add("## 2. RMS (이것만 보지 않는다)")
    add("")
    add("| 구분 | RMS (px) | 해석 |")
    add("|---|---|---|")
    add(f"| 학습 {report['n_train']}장 | {report['rms_train']:.4f} | {rms_band(report['rms_train'])} |")
    if report.get("rms_holdout") is not None:
        ratio = report["rms_holdout"] / report["rms_train"] if report["rms_train"] else float("inf")
        add(f"| 홀드아웃 {report['n_holdout']}장 | {report['rms_holdout']:.4f} | "
            f"학습 대비 {ratio:.2f}배 |")
    add("")
    add("RMS 는 **K, D 추정이 이 데이터에 잘 맞았다**는 뜻일 뿐, 그 K, D 가 좋은 target "
        "이라는 뜻이 아니다. 아래 네 항목을 같이 본다.")
    add("")

    add(f"### 2-1. 공간 분포 ({spatial['grid']}x{spatial['grid']} 셀별 평균 잔차 px, 괄호는 코너 수)")
    add("")
    add(_grid_table(spatial))
    add("")
    if spatial["max_cell"] is not None:
        add(f"최대 셀: ({spatial['max_cell'][0]}, {spatial['max_cell'][1]}) "
            f"평균 {spatial['max_mean']:.3f} px. "
            "한쪽에만 몰려 있으면 전체 RMS 가 낮아도 그 영역은 못 믿는다.")
    add("")

    add("### 2-2. 잔차 방향성 (방사성)")
    add("")
    add("| 항목 | 값 (px) |")
    add("|---|---|")
    add(f"| 방사 방향 평균 내적 | {radiality['mean_dot']:+.4f} |")
    add(f"| 잔차 크기 평균 | {radiality['mean_magnitude']:.4f} |")
    add("")
    add("0 근처면 잔차가 무작위 = 정상. 크게 치우쳐 있으면 잔차가 방사 방향으로 "
        "쏠린 것이고, 왜곡 모델이 데이터를 못 따라갔다는 신호다.")
    add("")
    add(f"![잔차 벡터]({png_name})")
    add("")
    add(f"화살표는 잔차를 {RESIDUAL_ARROW_SCALE:.0f}배 확대한 것이다. 사방으로 흩어져 있으면 정상, "
        "가장자리에서 일제히 한 방향이면 왜곡 모델 부족, 한 덩어리만 같은 방향이면 "
        "그 사진 한 장의 문제다 (흔들림, 보드 휨).")
    add("")

    add(f"### 2-3. 파라미터 안정성 (학습 {report['n_train']}장 중 {stab['subset']}장씩 "
        f"{stab['n_runs']}회 재추정)")
    add("")
    add("| 파라미터 | 전체 추정 | 부분집합 평균 | 표준편차 | 최대 편차 |")
    add("|---|---|---|---|---|")
    for name in ("fx", "fy", "cx", "cy"):
        s = stab[name]
        add(f"| {name} | {s['full']:.2f} | {s['mean']:.2f} | {s['std']:.2f} | {s['max_dev']:.2f} |")
    add("")
    add("표준편차가 크면 RMS 가 낮아도 데이터가 파라미터를 결정하지 못한 것이다 "
        "(자세가 다 비슷하거나, 화면 가장자리가 비었거나, 장수가 부족하거나).")
    add("")

    add("### 2-4. 홀드아웃 (K, D 고정, 사진마다 solvePnP 로 R, t 만)")
    add("")
    if report.get("holdout_per_image"):
        add("| 프레임 | RMS (px) | 코너 수 |")
        add("|---|---|---|")
        for item in report["holdout_per_image"]:
            add(f"| {item['id']:03d} | {item['rms']:.4f} | {item['n_corners']} |")
        add("")
        add("한 장만 유독 크면 그 사진을 의심한다 (흔들림, 보드가 화면을 벗어남). "
            "전체가 고르게 크면 K, D 자체가 일반화되지 않는 것이다.")
    else:
        add("홀드아웃 없음.")
    add("")

    add("## 3. 재현")
    add("")
    add("```bash")
    paths = " ".join(report.get("session_paths") or [report["session_path"]])
    add(f"python src/run_calibrate.py {paths} "
        f"--n-train {report['n_train']} --seed {report['seed']} "
        f"--outlier-k {report['outliers']['k']}")
    add("```")
    add("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
