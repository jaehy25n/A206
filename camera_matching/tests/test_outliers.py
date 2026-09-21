"""프레임별 재투영 오차와 이상치 제거.

전체 RMS 하나로는 두 상황이 구분되지 않는다.

    (가) 한 장이 심하게 틀렸다      -> 그 한 장을 빼면 된다
    (나) 전부 조금씩 틀렸다         -> 촬영 조건을 다시 봐야 한다

같은 RMS 가 나와도 해야 할 일이 정반대다. 프레임별 오차가 그 구분을 만든다.
이 테스트는 (가)를 실제로 잡아내는지, 그리고 (나)에서 함부로 버리지 않는지를 본다.
"""

from __future__ import annotations

import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.calibrate import (
    calibrate,
    drop_outliers,
    outlier_threshold,
    per_frame_rms,
)
from camcal.constants import OUTLIER_FLOOR_PX, OUTLIER_MIN_KEEP
from camcal.session import Session

from synth import IMAGE_SIZE, make_corner_sets

N_IMAGES = 25


@pytest.fixture
def synth_session(tmp_path, spec: BoardSpec) -> Session:
    session = Session.create(
        data_root=tmp_path,
        camera="synth",
        board=spec,
        resolution_requested=IMAGE_SIZE,
        resolution_actual=IMAGE_SIZE,
    )
    flat = np.full((IMAGE_SIZE[1], IMAGE_SIZE[0], 3), 200, dtype=np.uint8)
    for _ in range(N_IMAGES):
        session.add_frame(flat, detected=True, n_corners=spec.n_corners)
    return session


# --- per_frame_rms ----------------------------------------------------------


def test_clean_frames_are_all_near_the_noise(synth_session: Session, spec: BoardSpec) -> None:
    corners = make_corner_sets(spec, N_IMAGES, noise_px=0.1, seed=0)
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    frame_rms = per_frame_rms(synth_session, result, corners=corners)

    assert len(frame_rms) == N_IMAGES
    values = np.array(list(frame_rms.values()))
    assert values.max() < 0.25, f"깨끗한 데이터인데 {values.max():.3f} px 짜리가 있다"


def test_one_shaken_frame_stands_out(synth_session: Session, spec: BoardSpec) -> None:
    """한 장만 코너를 3 px 흔들면 그 프레임의 RMS 만 커져야 한다."""
    corners = make_corner_sets(spec, N_IMAGES, noise_px=0.1, seed=0)
    rng = np.random.default_rng(0)
    bad = 7
    corners[bad] = (
        corners[bad] + rng.normal(0, 3.0, corners[bad].shape).astype(np.float32)
    ).astype(np.float32)

    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    frame_rms = per_frame_rms(synth_session, result, corners=corners)

    worst = max(frame_rms, key=lambda i: frame_rms[i])
    assert worst == bad, f"흔든 프레임이 {bad} 인데 최악은 {worst}"
    others = [v for i, v in frame_rms.items() if i != bad]
    assert frame_rms[bad] > max(others) * 3


def test_sum_matches_overall_rms(synth_session: Session, spec: BoardSpec) -> None:
    """프레임별 RMS 를 제곱평균하면 전체 RMS 가 나와야 한다 (정의 일관성)."""
    corners = make_corner_sets(spec, N_IMAGES, noise_px=0.1, seed=0)
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    frame_rms = per_frame_rms(synth_session, result, corners=corners)

    values = np.array(list(frame_rms.values()))
    combined = float(np.sqrt(np.mean(values**2)))  # 프레임마다 코너 수가 같다
    assert combined == pytest.approx(result.rms, rel=1e-6)


# --- outlier_threshold ------------------------------------------------------


def test_threshold_is_not_dragged_by_the_outlier() -> None:
    """이상치가 경계를 얼마나 끌어올리는지. 중앙값/MAD 는 끌려가지 않는다.

    [0.20] * 20 + [5.0] 에서:
        중앙값/MAD 기준  경계 0.300 px  (측정)
        평균/표준편차     경계 3.498 px  (측정)
    둘 다 5.0 은 잡지만, 평균 기준은 **3.5 px 짜리 프레임까지 통과시킨다.**
    이상치 하나가 자기 주변까지 정상 범위로 만들어 버리는 것이 문제다.
    """
    values = [0.20] * 20 + [5.0]
    stats = outlier_threshold(values, k=3.0)

    assert stats["median"] == pytest.approx(0.20)
    assert stats["threshold"] < 5.0, "이상치가 경계 안에 들어와 버렸다"

    mean_based = float(np.mean(values) + 3 * np.std(values))
    assert mean_based > stats["threshold"] * 5, (
        f"평균 기준 {mean_based:.3f} vs MAD 기준 {stats['threshold']:.3f} - "
        "차이가 없다면 MAD 를 쓸 이유도 없다"
    )


def test_floor_protects_a_very_clean_set() -> None:
    """전부 0.05 px 이면 sigma 가 0 에 가까워 멀쩡한 0.09 까지 이상치가 된다.

    그래서 절대 하한을 둔다.
    """
    values = [0.05] * 20 + [0.09]
    stats = outlier_threshold(values, k=3.0)
    assert stats["threshold"] == pytest.approx(OUTLIER_FLOOR_PX)


# --- drop_outliers ----------------------------------------------------------


def make_rms(n_good: int, bad: list[float], good: float = 0.20) -> dict[int, float]:
    out = {i: good + (i % 3) * 0.01 for i in range(n_good)}
    for j, value in enumerate(bad):
        out[n_good + j] = value
    return out


def test_drops_only_the_bad_ones() -> None:
    frame_rms = make_rms(20, [3.0, 1.2])
    out = drop_outliers(frame_rms)

    assert out["dropped"] == [20, 21]
    assert len(out["keep"]) == 20
    assert out["capped"] is False


def test_keeps_everything_when_all_are_good() -> None:
    out = drop_outliers(make_rms(20, []))
    assert out["dropped"] == []
    assert len(out["keep"]) == 20


def test_never_drops_more_than_the_ratio() -> None:
    """나쁜 것이 3분의 1이면 한도(30%)에 걸려 일부만 버리고 그 사실을 알린다."""
    frame_rms = make_rms(30, [2.0 + 0.1 * i for i in range(15)])
    out = drop_outliers(frame_rms, max_drop_ratio=0.30)

    assert out["capped"] is True
    assert "촬영 조건" in out["capped_reason"]
    assert len(out["dropped"]) == int(45 * 0.30)
    assert len(out["keep"]) == 45 - int(45 * 0.30)


def test_half_bad_flags_nothing_and_that_is_correct() -> None:
    """절반이 나쁘면 **아무것도 잡지 못한다.** 이것은 버그가 아니라 한계다.

    중앙값 자체가 나쁜 쪽으로 끌려가서(측정: 1.110 px) 경계가 5.157 px 로 올라간다.
    "어느 쪽이 정상인지"를 데이터만 보고는 정할 수 없기 때문이다.

    그래서 이상치 제거는 **소수의 사고를 정리하는 도구**일 뿐이고, 전체가 나쁜
    세션을 구해주지 않는다. 그 경우는 프레임별 표의 중앙값을 보고 사람이
    다시 찍어야 한다.
    """
    frame_rms = make_rms(20, [2.0 + 0.1 * i for i in range(20)])
    out = drop_outliers(frame_rms)

    assert out["dropped"] == []
    assert out["median"] > 1.0, "중앙값이 이미 나쁜 쪽으로 끌려간 상태"


def test_capped_drops_the_worst_first() -> None:
    """한도에 걸려 다 못 버릴 때는 나쁜 것부터 버린다."""
    frame_rms = make_rms(10, [9.0, 8.0, 7.0, 6.0, 5.0])
    out = drop_outliers(frame_rms, max_drop_ratio=0.20)

    assert len(out["dropped"]) == 3
    assert out["dropped"] == [10, 11, 12]  # 9.0, 8.0, 7.0


def test_min_keep_is_respected() -> None:
    frame_rms = make_rms(6, [5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    out = drop_outliers(frame_rms, max_drop_ratio=1.0, min_keep=OUTLIER_MIN_KEEP)
    assert len(out["keep"]) >= min(OUTLIER_MIN_KEEP, len(frame_rms))


def test_bigger_k_drops_less() -> None:
    frame_rms = make_rms(20, [0.9])
    strict = drop_outliers(frame_rms, k=1.0)
    loose = drop_outliers(frame_rms, k=50.0)
    assert len(strict["dropped"]) >= len(loose["dropped"])
    assert loose["dropped"] == []


def test_stats_are_reported() -> None:
    out = drop_outliers(make_rms(20, [3.0]))
    for key in ("threshold", "median", "mad", "sigma", "k"):
        assert out[key] is not None, f"{key} 가 없으면 왜 잘렸는지 설명할 수 없다"
