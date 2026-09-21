"""세션 하나 -> (K, D) 추정과 그 추정을 의심하기 위한 수치들.

Zhang 방법은 K, D 와 **사진마다의 R, t 를 동시에 푸는** 최적화다. R, t 는 풀어야만
하는 방해 변수이며 목적이 아니다 - 그래서 여기서 나오는 rvecs, tvecs 는 잔차를
계산하는 데만 쓰고 결과 JSON 에 저장하지 않는다.

RMS 하나로 판단하지 않기 위해 네 가지를 같이 낸다 (CLAUDE.md 6절).
    1. 공간 분포     report.spatial_error_grid
    2. 잔차 방향성   report.residual_radiality
    3. 파라미터 안정성 stability()  (여기)
    4. 홀드아웃      holdout_rms() (여기)

좌표 이름:
    X_w   보드 좌표 (mm, Z_w = 0)      <- BoardSpec.object_points()
    u, v  픽셀 좌표                    <- find_corners()
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

import cv2
import numpy as np

from .constants import (
    CALIB_CRITERIA,
    CALIB_D_MODEL,
    CALIB_FLAGS,
    DEFAULT_N_TRAIN,
    DEFAULT_SEED,
    OUTLIER_FLOOR_PX,
    OUTLIER_MAD_K,
    OUTLIER_MAX_DROP_RATIO,
    OUTLIER_MIN_KEEP,
    STABILITY_RUNS,
    STABILITY_SUBSET,
)
from .detect import find_corners
from .session import Session

#: 코너 캐시. {프레임 index: (N, 1, 2) float32}
CornerCache = dict[int, np.ndarray]


@contextmanager
def deterministic_opencv() -> Iterator[None]:
    """OpenCV 를 단일 스레드로 돌려 **비트 단위로 재현 가능한** 결과를 얻는다.

    측정 (2026-09-18, 20장 합성):
        멀티스레드(22): 같은 입력 두 번 -> fx 1497.8669530901363 / 1497.8669530890741
        단일 스레드   : 같은 입력 두 번 -> 완전히 같은 값. 시간 차이 없음 (0.04s vs 0.05s)

    차이 자체는 1e-9 상대오차로 물리적 의미가 없다. 문제는 결과 JSON 을 diff 했을 때
    같은 데이터인데 숫자가 달라 보이는 것이다. "어제와 값이 다른데 뭐가 바뀐 거지"를
    추적하는 데 드는 시간이 이 스레드 하나보다 비싸다.

    전역 상태이므로 **빠져나올 때 원래대로 돌려놓는다** (촬영 도구의 실시간 검출은
    스레드를 그대로 써야 한다).
    """
    previous = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        yield
    finally:
        cv2.setNumThreads(previous)


@dataclass
class CalibrationResult:
    """calibrateCamera 한 번의 결과.

    Attributes:
        K: 3x3 내부 파라미터.
        D: 왜곡 계수 벡터 (길이는 d_model 에 따라 다르다). **K 와 별개다.**
        rvecs, tvecs: 사진마다의 자세. 잔차 계산용이며 재사용하지 않는다.
        rms: OpenCV 가 돌려준 재투영 RMS (픽셀). sqrt(sum ||e||^2 / N).
        ids: 이 추정에 쓴 프레임 index 목록.
        d_model: 왜곡 모델 이름 (D 를 해석하려면 필요하다).
    """

    K: np.ndarray
    D: np.ndarray
    rvecs: list[np.ndarray]
    tvecs: list[np.ndarray]
    rms: float
    ids: list[int]
    d_model: str = CALIB_D_MODEL
    image_size: tuple[int, int] = (0, 0)  # (width, height)

    @property
    def fx(self) -> float:
        return float(self.K[0, 0])

    @property
    def fy(self) -> float:
        return float(self.K[1, 1])

    @property
    def cx(self) -> float:
        return float(self.K[0, 2])

    @property
    def cy(self) -> float:
        return float(self.K[1, 2])

    def params(self) -> dict[str, float]:
        """안정성 비교에 쓰는 네 값."""
        return {"fx": self.fx, "fy": self.fy, "cx": self.cx, "cy": self.cy}


# --- 코너 읽기 --------------------------------------------------------------


def detect_session_corners(session: Session, ids: list[int] | None = None) -> CornerCache:
    """세션의 PNG 를 다시 검출해 코너를 모은다.

    촬영 때 이미 검출했지만 좌표를 meta.json 에 넣지 않았다 (PNG 무손실이라
    같은 입력 -> 같은 결과다). 여기서 한 번 모아두고 이후 모든 추정이 공유한다.

    Raises:
        RuntimeError: meta.json 은 검출 성공이라고 했는데 지금 검출되지 않는 경우.
            파일이 바뀌었거나 board.yaml 과 다른 보드다. 조용히 넘기지 않는다.
    """
    spec = session.board
    wanted = set(ids) if ids is not None else None
    cache: CornerCache = {}

    for record in session.frames:
        if not record.detected:
            continue
        if wanted is not None and record.index not in wanted:
            continue
        path = session.frame_path(record)
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise IOError(f"이미지를 읽지 못했다: {path}")
        ok, corners = find_corners(img, spec)
        if not ok:
            raise RuntimeError(
                f"meta.json 은 검출 성공이라는데 지금은 검출되지 않는다: {path}. "
                f"파일이 바뀌었거나 config/board.yaml 이 세션의 보드"
                f"({spec.cols}x{spec.rows})와 다르다"
            )
        cache[record.index] = corners
    return cache


def detected_ids(session: Session) -> list[int]:
    """검출 성공으로 기록된 프레임 index (오름차순)."""
    return sorted(f.index for f in session.frames if f.detected)


# --- 분할 ------------------------------------------------------------------


def split(
    session: Session,
    n_train: int = DEFAULT_N_TRAIN,
    seed: int = DEFAULT_SEED,
    ids: list[int] | None = None,
) -> tuple[list[int], list[int]]:
    """검출 성공 프레임을 학습 / 홀드아웃으로 나눈다.

    **결정적이다**: 같은 세션 + 같은 시드 -> 항상 같은 분할. 시드는 결과 JSON 에
    기록되므로 나중에 같은 분할을 재현할 수 있다.

    Args:
        n_train: 학습에 쓸 장수. 나머지가 전부 홀드아웃이 된다.
        ids: 나눌 대상 목록. 주지 않으면 세션의 검출 성공 프레임 전부.
            이상치를 걸러낸 뒤 남은 것만 나눌 때 쓴다.

    Raises:
        ValueError: 홀드아웃이 한 장도 남지 않는 경우. 홀드아웃 없이 낸 RMS 는
            "학습 데이터를 얼마나 잘 맞췄나"일 뿐이라 조용히 진행하지 않는다.
    """
    ids = sorted(ids) if ids is not None else detected_ids(session)
    if n_train < 1:
        raise ValueError(f"n_train 은 1 이상이어야 한다: {n_train}")
    if len(ids) <= n_train:
        raise ValueError(
            f"검출 성공 {len(ids)}장으로는 학습 {n_train}장 + 홀드아웃을 만들 수 없다. "
            f"--n-train 을 {max(len(ids) - 1, 1)} 이하로 낮추거나 더 찍는다"
        )

    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(np.asarray(ids))
    train = sorted(int(i) for i in shuffled[:n_train])
    holdout = sorted(int(i) for i in shuffled[n_train:])
    return train, holdout


# --- 추정 ------------------------------------------------------------------


def calibrate(
    session: Session, ids: list[int], corners: CornerCache | None = None
) -> CalibrationResult:
    """cv2.calibrateCamera 로 K, D 를 푼다.

    Args:
        ids: 쓸 프레임 index 목록.
        corners: detect_session_corners() 결과. 없으면 여기서 읽는다.
    """
    if not ids:
        raise ValueError("빈 id 목록으로는 추정할 수 없다")
    cache = corners if corners is not None else detect_session_corners(session, ids)

    spec = session.board
    object_points = [spec.object_points() for _ in ids]
    image_points = [cache[i] for i in ids]
    image_size = session.resolution_actual  # (width, height)

    with deterministic_opencv():
        rms, K, D, rvecs, tvecs = cv2.calibrateCamera(
            object_points,
            image_points,
            image_size,
            None,
            None,
            flags=CALIB_FLAGS,
            criteria=CALIB_CRITERIA,
        )
    return CalibrationResult(
        K=np.asarray(K, dtype=np.float64),
        D=np.asarray(D, dtype=np.float64).ravel(),
        rvecs=[np.asarray(r, dtype=np.float64) for r in rvecs],
        tvecs=[np.asarray(t, dtype=np.float64) for t in tvecs],
        rms=float(rms),
        ids=list(ids),
        image_size=image_size,
    )


def reprojection_residuals(
    session: Session,
    result: CalibrationResult,
    corners: CornerCache | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """추정에 쓴 프레임들의 잔차와 그 위치.

    Returns:
        (residuals, points). 둘 다 (총코너수, 2) float64.
        residuals = 재투영 - 관측 (픽셀), points = 관측 픽셀 좌표 (u, v).

    공간 분포와 방향성 분석은 전부 이 두 배열에서 나온다.
    """
    cache = corners if corners is not None else detect_session_corners(session, result.ids)
    spec = session.board
    object_points = spec.object_points()

    all_res: list[np.ndarray] = []
    all_pts: list[np.ndarray] = []
    for k, frame_id in enumerate(result.ids):
        projected, _ = cv2.projectPoints(
            object_points, result.rvecs[k], result.tvecs[k], result.K, result.D
        )
        projected = np.asarray(projected, dtype=np.float64).reshape(-1, 2)
        observed = np.asarray(cache[frame_id], dtype=np.float64).reshape(-1, 2)
        all_res.append(projected - observed)
        all_pts.append(observed)

    return np.concatenate(all_res), np.concatenate(all_pts)


def rms_of(residuals: np.ndarray) -> float:
    """OpenCV 와 같은 정의의 RMS: sqrt(평균 ||e||^2).

    축별 RMS 가 아니라 **점별 유클리드 거리**의 RMS 다. 정의를 섞으면 sqrt(2) 배
    차이가 나면서 "왜 우리 값만 다르지"가 된다.
    """
    res = np.asarray(residuals, dtype=np.float64).reshape(-1, 2)
    return float(np.sqrt(np.mean(np.sum(res**2, axis=1))))


# --- 홀드아웃 --------------------------------------------------------------


def holdout_rms(
    session: Session,
    holdout_ids: list[int],
    K: np.ndarray,
    D: np.ndarray,
    corners: CornerCache | None = None,
) -> dict[str, Any]:
    """K, D 를 **고정**하고 홀드아웃 사진의 재투영 오차를 잰다.

    사진마다 solvePnP 로 R, t 만 새로 구한다 (K, D 는 건드리지 않는다).
    학습 RMS 는 "얼마나 잘 맞췄나"이고, 이 값은 "처음 보는 사진에도 통하나"다.
    둘이 크게 벌어지면 과적합이거나 세션 안에 조건이 다른 사진이 섞인 것이다.

    Returns:
        {"rms": 전체 RMS, "per_image": [{"id", "rms", "n_corners"}...],
         "residuals": (N,2), "points": (N,2)}
    """
    if not holdout_ids:
        raise ValueError("홀드아웃이 비어 있다")
    cache = corners if corners is not None else detect_session_corners(session, holdout_ids)

    object_points = session.board.object_points()
    per_image: list[dict[str, Any]] = []
    all_res: list[np.ndarray] = []
    all_pts: list[np.ndarray] = []

    for frame_id in holdout_ids:
        observed = np.asarray(cache[frame_id], dtype=np.float64).reshape(-1, 1, 2)
        with deterministic_opencv():
            ok, rvec, tvec = cv2.solvePnP(object_points, observed, K, D)
        if not ok:
            raise RuntimeError(
                f"홀드아웃 프레임 {frame_id} 의 자세를 풀지 못했다 (solvePnP 실패)"
            )
        projected, _ = cv2.projectPoints(object_points, rvec, tvec, K, D)
        res = np.asarray(projected, dtype=np.float64).reshape(-1, 2) - observed.reshape(-1, 2)
        all_res.append(res)
        all_pts.append(observed.reshape(-1, 2))
        per_image.append(
            {"id": int(frame_id), "rms": rms_of(res), "n_corners": int(res.shape[0])}
        )

    residuals = np.concatenate(all_res)
    return {
        "rms": rms_of(residuals),
        "per_image": per_image,
        "residuals": residuals,
        "points": np.concatenate(all_pts),
    }


# --- 파라미터 안정성 --------------------------------------------------------


def stability(
    session: Session,
    train_ids: list[int],
    K_full: np.ndarray,
    n_runs: int = STABILITY_RUNS,
    subset: int = STABILITY_SUBSET,
    seed: int = DEFAULT_SEED,
    corners: CornerCache | None = None,
) -> dict[str, dict[str, float]]:
    """학습 사진의 부분집합으로 반복 추정해 fx, fy, cx, cy 가 얼마나 흔들리는지 본다.

    RMS 가 낮아도 이 값이 크게 흔들리면 **데이터가 파라미터를 결정하지 못한 것**이다
    (자세가 다 비슷하거나, 화면 가장자리가 비어 있거나, 장수가 부족하거나).

    Args:
        K_full: 학습 전체로 구한 K. 부분집합 평균이 여기서 얼마나 벗어나는지 같이 본다.

    Returns:
        {"fx": {"mean", "std", "full", "max_dev"}, "fy": ..., "cx": ..., "cy": ...,
         "n_runs": 실제 실행 횟수, "subset": 한 번에 쓴 장수}
    """
    cache = corners if corners is not None else detect_session_corners(session, train_ids)

    # 부분집합이 학습 전체와 같으면 매번 똑같은 집합을 쓰게 되어 표준편차가 항상 0 이
    # 나온다. 그 0 은 "완벽하게 안정적"이 아니라 **"검사하지 않았다"** 는 뜻인데
    # 숫자로는 구분되지 않는다. 그래서 최소 한 장은 빼도록 강제한다.
    requested = subset
    subset = min(subset, len(train_ids) - 1)
    if subset < 3:
        raise ValueError(
            f"학습 {len(train_ids)}장으로는 안정성 검사를 할 수 없다 "
            f"(부분집합 {subset}장, 최소 3장). 학습 장수를 늘린다"
        )

    rng = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {"fx": [], "fy": [], "cx": [], "cy": []}
    for _ in range(n_runs):
        picked = sorted(
            int(i) for i in rng.choice(np.asarray(train_ids), size=subset, replace=False)
        )
        result = calibrate(session, picked, corners=cache)
        for name, value in result.params().items():
            samples[name].append(value)

    full = {
        "fx": float(K_full[0, 0]),
        "fy": float(K_full[1, 1]),
        "cx": float(K_full[0, 2]),
        "cy": float(K_full[1, 2]),
    }
    out: dict[str, Any] = {
        "n_runs": n_runs,
        "subset": subset,
        "requested_subset": requested,
    }
    for name, values in samples.items():
        arr = np.asarray(values, dtype=np.float64)
        out[name] = {
            "mean": float(arr.mean()),
            "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "full": full[name],
            "max_dev": float(np.abs(arr - full[name]).max()),
        }
    return out


# --- 프레임별 오차와 이상치 -------------------------------------------------


def per_frame_rms(
    session: Session,
    result: CalibrationResult,
    corners: CornerCache | None = None,
) -> dict[int, float]:
    """추정에 쓴 프레임 각각의 재투영 RMS (픽셀).

    전체 RMS 하나로는 "한 장이 심하게 틀렸다"와 "전부 조금씩 틀렸다"를 구분할 수
    없다. 앞쪽이면 그 한 장을 빼면 되고, 뒤쪽이면 촬영 조건을 다시 봐야 한다.
    같은 숫자인데 해야 할 일이 정반대다.

    Returns:
        {프레임 index: RMS}. 순서는 result.ids 그대로.
    """
    cache = corners if corners is not None else detect_session_corners(session, result.ids)
    object_points = session.board.object_points()

    out: dict[int, float] = {}
    for k, frame_id in enumerate(result.ids):
        projected, _ = cv2.projectPoints(
            object_points, result.rvecs[k], result.tvecs[k], result.K, result.D
        )
        projected = np.asarray(projected, dtype=np.float64).reshape(-1, 2)
        observed = np.asarray(cache[frame_id], dtype=np.float64).reshape(-1, 2)
        out[int(frame_id)] = rms_of(projected - observed)
    return out


def outlier_threshold(values: list[float], k: float = OUTLIER_MAD_K) -> dict[str, float]:
    """중앙값과 MAD 로 이상치 경계를 잡는다.

    평균과 표준편차를 쓰면 이상치가 그 둘을 끌고 가서 자기 자신을 정상으로
    만든다 (한 장이 5 px 이면 표준편차가 커져 경계가 5 px 위로 올라간다).
    중앙값과 MAD 는 그 영향을 받지 않는다.

    Returns:
        {"median", "mad", "sigma", "threshold"}. sigma = 1.4826 * MAD
        (정규분포에서 MAD 를 표준편차로 환산하는 상수).
    """
    arr = np.asarray(values, dtype=np.float64)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    sigma = 1.4826 * mad
    return {
        "median": median,
        "mad": mad,
        "sigma": sigma,
        "threshold": max(median + k * sigma, OUTLIER_FLOOR_PX),
    }


def drop_outliers(
    frame_rms: dict[int, float],
    k: float = OUTLIER_MAD_K,
    max_drop_ratio: float = OUTLIER_MAX_DROP_RATIO,
    min_keep: int = OUTLIER_MIN_KEEP,
) -> dict[str, Any]:
    """재투영 오차가 큰 프레임을 골라낸다. **실제로 지우지는 않는다.**

    안전장치 두 개를 둔다.
        - 한 번에 max_drop_ratio 넘게 버리지 않는다. 절반을 버려야 할 정도면
          이상치가 아니라 촬영 자체가 잘못된 것이고 사람이 봐야 한다
        - min_keep 장 아래로 내려가지 않는다

    안전장치에 걸려 다 버리지 못하면 **오차가 큰 것부터** 한도까지만 버리고
    그 사실을 `capped` 로 알린다 (조용히 덜 버리면 안 된다).

    Returns:
        {"keep": [...], "dropped": [...], "threshold", "median", "mad", "sigma",
         "capped": bool, "capped_reason": str | None}
    """
    ids = sorted(frame_rms)
    stats = outlier_threshold([frame_rms[i] for i in ids], k=k)
    threshold = stats["threshold"]

    over = sorted((i for i in ids if frame_rms[i] > threshold), key=lambda i: -frame_rms[i])
    allowed = min(int(len(ids) * max_drop_ratio), max(len(ids) - min_keep, 0))

    capped_reason = None
    if len(over) > allowed:
        capped_reason = (
            f"이상치 후보 {len(over)}장 중 {allowed}장만 제거했다 "
            f"(한도: 전체의 {max_drop_ratio * 100:.0f}% 이내, 최소 {min_keep}장 유지). "
            "이 정도로 많으면 개별 프레임 문제가 아니라 촬영 조건을 의심한다"
        )
        over = over[:allowed]

    dropped = set(over)
    return {
        "keep": [i for i in ids if i not in dropped],
        "dropped": sorted(dropped),
        "threshold": threshold,
        "median": stats["median"],
        "mad": stats["mad"],
        "sigma": stats["sigma"],
        "k": k,
        "capped": capped_reason is not None,
        "capped_reason": capped_reason,
    }
