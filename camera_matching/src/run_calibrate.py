"""세션 하나 -> (K, D) + 리포트.

    python src/run_calibrate.py data/luaz/<session_id>
    python src/run_calibrate.py data/s10/<session_id> --n-train 20 --seed 0

산출물
    results/<camera>_intrinsics.json    K, D, RMS, 안정성, FOV, 경고
    results/reports/<session_id>.md     표 + 잔차 벡터 그림
    results/reports/<session_id>_residuals.png

이 단계는 (K, D) 까지다. target 공간(LUAZ 원본이냐 가상 카메라냐) 결정과 remap 은
4단계다. 여기서는 어느 쪽도 가정하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from camcal import Session
from camcal.calibrate import (
    calibrate,
    detect_session_corners,
    detected_ids,
    holdout_rms,
    reprojection_residuals,
    split,
    stability,
)
from camcal.console import setup_console
from camcal.constants import CALIB_D_MODEL, DEFAULT_N_TRAIN, DEFAULT_SEED
from camcal.fov import fov_effective, fov_nominal, is_degenerate_k_prime
from camcal.report import (
    collect_warnings,
    now_iso,
    render,
    residual_radiality,
    rms_band,
    sanity_check,
    spatial_error_grid,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 산출물 위치. README 폴더 구조와 맞춘다.
RESULTS_DIRNAME = "results"
REPORTS_DIRNAME = "reports"


def build_report(
    session: Session,
    n_train: int,
    seed: int,
) -> dict[str, Any]:
    """추정과 분석을 모두 돌려 리포트 dict 를 만든다."""
    train_ids, holdout_ids = split(session, n_train=n_train, seed=seed)
    corners = detect_session_corners(session)

    result = calibrate(session, train_ids, corners=corners)
    residuals, points = reprojection_residuals(session, result, corners=corners)

    width, height = session.resolution_actual
    hold = holdout_rms(session, holdout_ids, result.K, result.D, corners=corners)
    stab = stability(
        session, train_ids, result.K, seed=seed, corners=corners
    )

    hfov_n, vfov_n = fov_nominal(result.K, width, height)
    hfov_e, vfov_e, K_prime = fov_effective(result.K, result.D, width, height, alpha=0.0)

    report: dict[str, Any] = {
        "camera": session.camera,
        "session_id": session.session_id,
        "session_path": str(session.path),
        "resolution": [width, height],
        "K": result.K.tolist(),
        "D": result.D.tolist(),
        "D_model": CALIB_D_MODEL,
        "D_length": int(result.D.size),
        "rms_train": result.rms,
        "rms_holdout": hold["rms"],
        "n_train": len(train_ids),
        "n_holdout": len(holdout_ids),
        "train_ids": train_ids,
        "holdout_ids": holdout_ids,
        "seed": seed,
        "stability": stab,
        "fov_nominal": {"h": hfov_n, "v": vfov_n},
        "fov_effective": {"h": hfov_e, "v": vfov_e, "K_prime": K_prime.tolist()},
        "fov_degenerate": is_degenerate_k_prime(result.K, K_prime, result.D),
        "spatial": spatial_error_grid(residuals, points, (width, height)),
        "radiality": residual_radiality(residuals, points, (result.cx, result.cy)),
        "holdout_per_image": hold["per_image"],
        "sanity": sanity_check(result.K, result.D, width, height),
        "board": session.board.to_dict(),
        "created_at": now_iso(),
        # 리포트 그림용. JSON 에는 넣지 않는다 (코너 수천 개짜리 배열).
        "_residuals": residuals,
        "_points": points,
    }
    report["warnings"] = collect_warnings(report)
    return report


def to_json(report: dict[str, Any]) -> dict[str, Any]:
    """JSON 으로 나갈 부분만. 밑줄로 시작하는 키는 뺀다."""
    return {k: v for k, v in report.items() if not k.startswith("_")}


def print_summary(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    """콘솔 요약 8줄. 더 자세한 것은 리포트를 본다."""
    stab = report["stability"]
    K = np.asarray(report["K"])
    warnings = report["warnings"]

    print()
    print(f"  {report['camera']} / {report['session_id']}  "
          f"학습 {report['n_train']}장 + 홀드아웃 {report['n_holdout']}장 (seed {report['seed']})")
    print(f"  RMS  학습 {report['rms_train']:.4f} px ({rms_band(report['rms_train'])})  "
          f"홀드아웃 {report['rms_holdout']:.4f} px")
    print(f"  fx {K[0, 0]:.2f} +-{stab['fx']['std']:.2f}   fy {K[1, 1]:.2f} +-{stab['fy']['std']:.2f}"
          f"   (부분집합 {stab['subset']}장 x {stab['n_runs']}회)")
    print(f"  cx {K[0, 2]:.2f} +-{stab['cx']['std']:.2f}   cy {K[1, 2]:.2f} +-{stab['cy']['std']:.2f}")
    print(f"  D ({report['D_model']}) {', '.join(f'{v:.5f}' for v in report['D'])}")
    print(f"  FOV  nominal H {report['fov_nominal']['h']:.2f} deg / "
          f"effective(alpha=0) H {report['fov_effective']['h']:.2f} deg")
    if warnings:
        print(f"  경고 {len(warnings)}건:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  경고 없음")
    print(f"  -> {json_path}")
    print(f"  -> {md_path}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path, help="data/<camera>/<session_id> 경로")
    parser.add_argument(
        "--n-train",
        type=int,
        default=DEFAULT_N_TRAIN,
        help=f"학습 장수 (기본 {DEFAULT_N_TRAIN}). 나머지는 전부 홀드아웃",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help=f"분할 시드 (기본 {DEFAULT_SEED})"
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=PROJECT_ROOT / RESULTS_DIRNAME,
        help="산출물 폴더 (기본 results/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    session = Session.open(args.session)
    n_detected = len(detected_ids(session))
    print(f"세션 {session.session_id} / {session.camera} · "
          f"프레임 {len(session.frames)}장 (검출 성공 {n_detected}장)")

    if not session.board.square_mm_measured:
        print(
            "[경고] 이 세션의 square_mm 은 실측값이 아니다. K 와 D 는 영향을 받지 않지만 "
            "거리 t 의 단위가 틀어져 있다",
            file=sys.stderr,
        )

    try:
        report = build_report(session, n_train=args.n_train, seed=args.seed)
    except ValueError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    results_dir = Path(args.results_dir)
    reports_dir = results_dir / REPORTS_DIRNAME
    results_dir.mkdir(parents=True, exist_ok=True)

    json_path = results_dir / f"{session.camera}_intrinsics.json"
    json_path.write_text(
        json.dumps(to_json(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path = render(report, reports_dir)

    print_summary(report, json_path, md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
