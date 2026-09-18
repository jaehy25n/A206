"""정지 보드 연속 촬영에서 코너가 얼마나 흔들리는지 잰다 (EIS / AF 변동 확인).

    python src/preflight_jitter.py data/s10/<session_id>

왜 재는가: S10 은 전자식 손떨림 보정(EIS)이 켜져 있으면 **프레임마다 이미지를
조금씩 이동·크롭한다.** 보드도 카메라도 고정인데 코너 좌표가 움직인다면
캘리브레이션이 푸는 K, D 에 그 흔들림이 섞여 들어간다. 오토포커스가 계속
재초점을 잡아도 초점거리가 미세하게 변해 같은 증상이 나온다.

무엇을 재는가: 같은 코너(같은 인덱스)의 좌표가 프레임들 사이에서 갖는 표준편차.
정지 장면이므로 이상적으로는 0 이어야 한다.

전제: **보드와 카메라가 완전히 고정된 상태**에서 연속 촬영한 세션이어야 한다.
보드를 들고 찍은 세션에 이 도구를 쓰면 의미 없는 큰 값이 나온다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from camcal import Session, find_corners
from camcal.console import setup_console

#: 판정 임계값 (픽셀). 코너 검출 자체의 재현 오차가 0.05~0.1 px 수준이므로
#: 0.3 px 은 "검출 노이즈보다 조금 큰 정도"까지 허용하는 값이다.
JITTER_OK_PX = 0.3

#: 이 이상이면 EIS 나 AF 변동을 의심한다. 1 px 흔들림은 캘리브레이션 RMS 에
#: 그대로 더해져 0.3 px 목표를 넘겨버린다.
JITTER_WARN_PX = 1.0

#: 판정에 필요한 최소 프레임 수. 2장으로는 표준편차가 의미가 없다.
MIN_FRAMES = 5


def collect_corners(session: Session) -> tuple[np.ndarray, list[str]]:
    """세션의 검출 성공 프레임에서 코너를 모은다.

    Returns:
        (corners, filenames). corners shape (F, N, 2) - F 프레임, N 코너, (u, v).
        모든 프레임에서 코너 수가 같아야 한다 (같은 보드이므로 당연히 같아야 한다).
    """
    spec = session.board
    stack: list[np.ndarray] = []
    names: list[str] = []
    skipped: list[str] = []

    for record in session.frames:
        path = session.frame_path(record)
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise IOError(f"이미지를 읽지 못했다: {path}")
        ok, corners = find_corners(img, spec)
        if not ok:
            skipped.append(record.filename)
            continue
        stack.append(np.asarray(corners, dtype=np.float64).reshape(-1, 2))
        names.append(record.filename)

    if skipped:
        print(f"검출 실패로 제외: {len(skipped)}장 ({', '.join(skipped[:5])}…)")
    if len(stack) < MIN_FRAMES:
        raise SystemExit(
            f"[중단] 검출된 프레임이 {len(stack)}장뿐이다. 최소 {MIN_FRAMES}장 필요.\n"
            "  보드와 카메라를 고정하고 자동 모드로 20장쯤 찍은 세션을 쓴다"
        )
    return np.stack(stack), names


def analyze(corners: np.ndarray) -> dict[str, float]:
    """프레임 간 코너 흔들림.

    Args:
        corners: (F, N, 2).

    Returns:
        std_mean / std_max: 코너별 (u,v) 표준편차의 평균과 최댓값 (픽셀).
        drift: 첫 프레임과 마지막 프레임의 코너 평균 위치 차이 (픽셀).
            흔들림(jitter)과 서서히 밀리는 것(drift)을 구분하려고 따로 본다.
    """
    # 코너별 축별 표준편차 → (N, 2), 축을 합쳐 코너별 크기 (N,)
    std_per_axis = corners.std(axis=0, ddof=1)
    std_per_corner = np.linalg.norm(std_per_axis, axis=1)

    centroid_first = corners[0].mean(axis=0)
    centroid_last = corners[-1].mean(axis=0)
    drift = float(np.linalg.norm(centroid_last - centroid_first))

    return {
        "std_mean": float(std_per_corner.mean()),
        "std_max": float(std_per_corner.max()),
        "std_u_mean": float(std_per_axis[:, 0].mean()),
        "std_v_mean": float(std_per_axis[:, 1].mean()),
        "drift": drift,
    }


def verdict(stats: dict[str, float]) -> tuple[str, int]:
    """(판정 문구, 종료 코드). 0 = OK, 2 = 의심."""
    worst = stats["std_max"]
    if worst < JITTER_OK_PX:
        return (f"OK - 최대 코너 흔들림 {worst:.3f} px < {JITTER_OK_PX} px", 0)
    if worst < JITTER_WARN_PX:
        return (
            f"애매 - 최대 {worst:.3f} px ({JITTER_OK_PX}~{JITTER_WARN_PX} px). "
            "삼각대·바닥 진동을 먼저 의심한다",
            2,
        )
    return (
        f"경고 - 최대 {worst:.3f} px >= {JITTER_WARN_PX} px. "
        "EIS(손떨림 보정) 또는 AF 변동 의심. 폰 설정에서 끄고 다시 잰다",
        2,
    )


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path, help="data/<camera>/<session_id> 경로")
    args = parser.parse_args(argv)

    session = Session.open(args.session)
    print(f"세션 {session.session_id} · {session.camera} · 프레임 {len(session.frames)}장")

    corners, names = collect_corners(session)
    stats = analyze(corners)
    text, code = verdict(stats)

    print()
    print(f"  프레임 {len(names)}장, 코너 {corners.shape[1]}개")
    print(f"  코너별 표준편차   평균 {stats['std_mean']:.3f} px / 최대 {stats['std_max']:.3f} px")
    print(f"    축별 평균       u {stats['std_u_mean']:.3f} px, v {stats['std_v_mean']:.3f} px")
    print(f"  첫↔마지막 드리프트 {stats['drift']:.3f} px")
    print()
    print(f"  판정: {text}")
    print()
    if stats["drift"] > JITTER_WARN_PX and stats["std_max"] < JITTER_WARN_PX:
        print(
            "  흔들림은 작은데 드리프트가 크다 → 삼각대가 서서히 밀렸거나 "
            "촬영 중 카메라가 움직였다. EIS 문제와는 다르다."
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
