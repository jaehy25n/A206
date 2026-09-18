"""알려진 K, D 를 되찾아오는지 - 캘리브레이션의 유일한 정답 있는 검증.

실제 촬영에는 정답이 없다. RMS 가 낮아도 K 가 틀렸을 수 있다. 그래서 정답을 아는
합성 데이터로 "우리 파이프라인이 K 를 되찾아온다"를 먼저 확인한다.

여기서 쓰는 것은 코너 좌표 수준의 합성이다 (projectPoints + 0.1px 노이즈).
검출기는 test_detect.py 가, 이미지까지 포함한 왕복은 test_run_calibrate.py 가 본다.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.calibrate import (
    calibrate,
    holdout_rms,
    reprojection_residuals,
    rms_of,
    split,
    stability,
)
from camcal.session import Session

from synth import IMAGE_SIZE, TRUE_D, TRUE_K, make_corner_sets

#: 복원 허용 오차. 0.5% 는 fx=1500 기준 7.5 px.
FX_TOLERANCE_REL = 0.005

#: 합성 장수. 실제 촬영 권장치(25~30)와 같게 둔다.
N_IMAGES = 25


@pytest.fixture
def synth_session(tmp_path, spec: BoardSpec) -> Session:
    """코너만 합성으로 쓰기 때문에 이미지 내용은 쓰이지 않는다.

    그래도 Session 을 진짜로 만드는 이유: calibrate() 가 세션에서 보드 규격과
    해상도를 읽어 오므로, 그 경로까지 같이 돌려보는 편이 낫다.
    """
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


@pytest.fixture
def corners(spec: BoardSpec):
    return make_corner_sets(spec, N_IMAGES, noise_px=0.1, seed=0)


# --- 핵심: K, D 복원 --------------------------------------------------------


def test_recovers_focal_length(synth_session: Session, corners) -> None:
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)

    rel_fx = abs(result.fx - TRUE_K[0, 0]) / TRUE_K[0, 0]
    rel_fy = abs(result.fy - TRUE_K[1, 1]) / TRUE_K[1, 1]
    assert rel_fx < FX_TOLERANCE_REL, f"fx {result.fx:.2f} vs 참값 {TRUE_K[0, 0]} ({rel_fx:.4%})"
    assert rel_fy < FX_TOLERANCE_REL, f"fy {result.fy:.2f} vs 참값 {TRUE_K[1, 1]} ({rel_fy:.4%})"


def test_recovers_principal_point(synth_session: Session, corners) -> None:
    """주점은 초점거리보다 잘 안 잡힌다. 그래도 수십 px 안에는 들어와야 한다."""
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    assert abs(result.cx - TRUE_K[0, 2]) < 20.0
    assert abs(result.cy - TRUE_K[1, 2]) < 20.0


def test_k1_sign_and_magnitude(synth_session: Session, corners) -> None:
    """배럴 왜곡(k1 < 0)을 배럴로 복원해야 한다. 부호가 뒤집히면 remap 방향이 반대가 된다."""
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    k1 = result.D[0]
    assert k1 < 0, f"k1={k1:.5f} - 참값은 {TRUE_D[0]} (배럴)"
    assert abs(k1 - TRUE_D[0]) < 0.02, f"k1={k1:.5f} vs 참값 {TRUE_D[0]}"


def test_d_model_length_is_recorded(synth_session: Session, corners) -> None:
    """D 의 길이를 모르면 나중에 계수를 해석할 수 없다."""
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    assert result.d_model == "opencv_5"
    assert result.D.size == 5


def test_rms_is_near_injected_noise(synth_session: Session, corners) -> None:
    """노이즈 0.1 px 을 넣었으면 RMS 도 그 근처여야 한다.

    훨씬 크면 모델이 데이터를 못 따라간 것이고, 훨씬 작으면 과적합이다.
    """
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    assert 0.05 < result.rms < 0.20, f"RMS {result.rms:.4f}"


def test_our_rms_matches_opencv(synth_session: Session, corners) -> None:
    """rms_of() 의 정의가 OpenCV 와 같은지. 다르면 sqrt(2) 배 차이가 난다."""
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    residuals, _points = reprojection_residuals(synth_session, result, corners=corners)
    assert rms_of(residuals) == pytest.approx(result.rms, rel=1e-6)


# --- 홀드아웃 --------------------------------------------------------------


def test_holdout_rms_close_to_train(synth_session: Session, corners) -> None:
    """같은 분포에서 나온 데이터이므로 홀드아웃이 학습과 비슷해야 한다."""
    train, holdout = split(synth_session, n_train=20, seed=0)
    result = calibrate(synth_session, train, corners=corners)
    hold = holdout_rms(synth_session, holdout, result.K, result.D, corners=corners)

    assert len(hold["per_image"]) == len(holdout)
    assert hold["rms"] < result.rms * 2.0, (
        f"홀드아웃 {hold['rms']:.4f} vs 학습 {result.rms:.4f}"
    )


def test_holdout_detects_wrong_K(synth_session: Session, corners) -> None:
    """K 를 일부러 10% 틀리게 주면 홀드아웃 RMS 가 크게 올라가야 한다.

    이게 안 오르면 홀드아웃 검사가 아무것도 검사하지 않는 것이다.
    """
    train, holdout = split(synth_session, n_train=20, seed=0)
    result = calibrate(synth_session, train, corners=corners)

    good = holdout_rms(synth_session, holdout, result.K, result.D, corners=corners)["rms"]
    K_bad = result.K.copy()
    K_bad[0, 0] *= 1.10
    bad = holdout_rms(synth_session, holdout, K_bad, result.D, corners=corners)["rms"]

    assert bad > good * 5, f"틀린 K 인데 RMS 가 {bad:.4f} (정상 {good:.4f})"


# --- 안정성 ----------------------------------------------------------------


def test_stability_is_tight_on_clean_data(synth_session: Session, corners) -> None:
    """자세가 다양하고 노이즈가 작으면 부분집합마다 fx 가 크게 흔들리면 안 된다."""
    train, _holdout = split(synth_session, n_train=20, seed=0)
    result = calibrate(synth_session, train, corners=corners)
    stab = stability(synth_session, train, result.K, seed=0, corners=corners)

    assert stab["n_runs"] == 10
    assert stab["fx"]["std"] < TRUE_K[0, 0] * 0.01, f"fx std {stab['fx']['std']:.2f}"
    assert stab["fx"]["mean"] == pytest.approx(result.fx, rel=0.01)


def test_stability_grows_with_noise(synth_session: Session, spec: BoardSpec) -> None:
    """노이즈를 20배로 키우면 fx 표준편차가 커져야 한다 (검사가 살아 있는지)."""
    train, _ = split(synth_session, n_train=20, seed=0)

    quiet = make_corner_sets(spec, N_IMAGES, noise_px=0.1, seed=1)
    noisy = make_corner_sets(spec, N_IMAGES, noise_px=2.0, seed=1)

    std_quiet = stability(
        synth_session, train, calibrate(synth_session, train, corners=quiet).K,
        seed=0, corners=quiet,
    )["fx"]["std"]
    std_noisy = stability(
        synth_session, train, calibrate(synth_session, train, corners=noisy).K,
        seed=0, corners=noisy,
    )["fx"]["std"]

    assert std_noisy > std_quiet * 2, f"quiet {std_quiet:.3f} vs noisy {std_noisy:.3f}"


def test_stability_needs_enough_images(synth_session: Session, corners) -> None:
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    with pytest.raises(ValueError):
        stability(synth_session, [0, 1], result.K, subset=2, corners=corners)


# --- 잔차 ------------------------------------------------------------------


def test_residuals_shape_and_locations(synth_session: Session, corners, spec: BoardSpec) -> None:
    result = calibrate(synth_session, list(range(N_IMAGES)), corners=corners)
    residuals, points = reprojection_residuals(synth_session, result, corners=corners)

    assert residuals.shape == (N_IMAGES * spec.n_corners, 2)
    assert points.shape == residuals.shape
    assert 0 <= points[:, 0].min() and points[:, 0].max() <= IMAGE_SIZE[0]
    assert 0 <= points[:, 1].min() and points[:, 1].max() <= IMAGE_SIZE[1]


def test_calibrate_rejects_empty_ids(synth_session: Session, corners) -> None:
    with pytest.raises(ValueError):
        calibrate(synth_session, [], corners=corners)
