"""세션 하나 또는 여럿 -> (K, D) + 리포트.

    python src/run_calibrate.py data/luaz/<session_id>
    python src/run_calibrate.py data/s10/session1 data/s10/session2 --n-train 40

여러 세션을 주면 **전부 합쳐 한 번에** 추정한다 (한 카메라를 나눠 찍은 경우).
카메라 / 해상도 / 보드 규격이 하나라도 다르면 합치지 않고 멈춘다.

처리 순서
    1) 전체 프레임으로 1차 추정
    2) **프레임별 재투영 오차**를 낸다
    3) 오차가 큰 프레임을 이상치로 제거 (중앙값 + k*MAD, 안전장치 있음)
    4) 남은 프레임으로 학습/홀드아웃을 나누고 **최종 추정**

전체 RMS 하나로는 "한 장이 심하게 틀렸다"와 "전부 조금씩 틀렸다"를 구분할 수 없다.
2)가 그 구분을 만들고, 3)은 앞쪽 경우만 정리한다.

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

from camcal.calibrate import (
    calibrate,
    detect_session_corners,
    detected_ids,
    drop_outliers,
    holdout_rms,
    per_frame_rms,
    reprojection_residuals,
    split,
    stability,
)
from camcal.combined import CombinedSession, SessionMismatch
from camcal.console import setup_console
from camcal.constants import (
    CALIB_D_MODEL,
    DEFAULT_N_TRAIN,
    DEFAULT_SEED,
    OUTLIER_MAD_K,
)
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
    session: CombinedSession,
    n_train: int,
    seed: int,
    outlier_k: float = OUTLIER_MAD_K,
    remove_outliers: bool = True,
) -> dict[str, Any]:
    """1차 추정 -> 프레임별 오차 -> 이상치 제거 -> 최종 추정 -> 분석."""
    corners = detect_session_corners(session)
    all_ids = detected_ids(session)

    # 1) 전체로 한 번 추정한다. 이 추정의 목적은 K 가 아니라 **프레임별 오차**다.
    #    (여기서 나온 K 는 이상치가 섞여 있으므로 최종값으로 쓰지 않는다)
    first = calibrate(session, all_ids, corners=corners)
    frame_rms = per_frame_rms(session, first, corners=corners)

    # 2) 이상치 판정
    if remove_outliers:
        outliers = drop_outliers(frame_rms, k=outlier_k)
    else:
        outliers = {
            "keep": list(all_ids),
            "dropped": [],
            "threshold": None,
            "median": None,
            "mad": None,
            "sigma": None,
            "k": outlier_k,
            "capped": False,
            "capped_reason": None,
            "skipped": True,
        }
    kept_ids = outliers["keep"]

    # 3) 남은 프레임으로 학습/홀드아웃을 나누고 최종 추정
    train_ids, holdout_ids = split(session, n_train=n_train, seed=seed, ids=kept_ids)
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
        "session_paths": session.session_paths,
        "n_sessions": len(session.sessions),
        "orphan_pngs": session.orphan_pngs,
        "resolution": [width, height],
        "n_frames_total": len(session.frames),
        "n_detected": len(all_ids),
        "rms_all_frames": first.rms,
        "frame_rms": {session.label_of(i): frame_rms[i] for i in sorted(frame_rms)},
        "outliers": {
            **{k: v for k, v in outliers.items() if k not in ("keep", "dropped")},
            "dropped": [
                {"frame": session.label_of(i), "rms": frame_rms[i]}
                for i in outliers["dropped"]
            ],
            "n_kept": len(kept_ids),
            "n_dropped": len(outliers["dropped"]),
        },
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

    out = report["outliers"]
    print()
    print(f"  {report['camera']} / 세션 {report['n_sessions']}개 / "
          f"검출 {report['n_detected']}장")
    print(f"  1차(전체 {report['n_detected']}장) RMS {report['rms_all_frames']:.4f} px"
          + ("  -> 이상치 제거 안 함" if out.get("skipped") else
             f"  -> 이상치 {out['n_dropped']}장 제거 (경계 {out['threshold']:.4f} px)"))
    print(f"  학습 {report['n_train']}장 + 홀드아웃 {report['n_holdout']}장 "
          f"(남은 {out['n_kept']}장 중, seed {report['seed']})")
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
    parser.add_argument(
        "sessions",
        type=Path,
        nargs="+",
        help="data/<camera>/<session_id> 경로. 여러 개면 합쳐서 한 번에 추정한다",
    )
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
        "--outlier-k",
        type=float,
        default=OUTLIER_MAD_K,
        help=f"이상치 경계 = 중앙값 + k*sigma (기본 {OUTLIER_MAD_K}). 클수록 덜 버린다",
    )
    parser.add_argument(
        "--keep-all",
        action="store_true",
        help="이상치를 제거하지 않는다. 프레임별 오차는 그대로 출력한다",
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

    try:
        session = CombinedSession.open(args.sessions)
    except (SessionMismatch, ValueError) as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    n_detected = len(detected_ids(session))
    print(f"{session.camera} · 세션 {len(session.sessions)}개 · "
          f"프레임 {len(session.frames)}장 (검출 성공 {n_detected}장)")
    for one in session.sessions:
        print(f"  - {one.session_id}: {len(one.frames)}장 (검출 {one.n_detected}장)")

    for session_id, extra in session.orphan_pngs.items():
        print(
            f"[경고] {session_id}/frames 에 meta.json 이 모르는 PNG 가 {len(extra)}개 있다 "
            f"({', '.join(extra[:3])}{' ...' if len(extra) > 3 else ''}). "
            "출처를 알 수 없으므로 캘리브레이션에 쓰지 않는다",
            file=sys.stderr,
        )

    if not session.board.square_mm_measured:
        print(
            "[경고] 이 세션의 square_mm 은 실측값이 아니다. K 와 D 는 영향을 받지 않지만 "
            "거리 t 의 단위가 틀어져 있다",
            file=sys.stderr,
        )

    try:
        report = build_report(
            session,
            n_train=args.n_train,
            seed=args.seed,
            outlier_k=args.outlier_k,
            remove_outliers=not args.keep_all,
        )
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
