"""FOV - 이름 두 개, 값 두 개.

1회차에 같은 데이터에서 64.3 도와 61.0 도가 따로 나왔다. 두 값은 **둘 다 맞았고**,
하나는 원본 K 로, 다른 하나는 왜곡 보정 후 K' 로 잰 것이었는데 이름이 같았다.
이 테스트는 두 값이 서로 다른 것이 정상임을 고정한다.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from camcal.fov import fov_effective, fov_nominal, is_degenerate_k_prime

WIDTH, HEIGHT = 1920, 1080

#: 손계산과 대조하기 위한 검증용 값. 실측값이 아니라 테스트 상수다.
TEST_FX, TEST_FY = 1527.0, 1520.0


def make_K(fx: float, fy: float, cx: float = 960.0, cy: float = 540.0) -> np.ndarray:
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)


# --- fov_nominal -----------------------------------------------------------


def test_matches_hand_calculation() -> None:
    """손계산과 맞는지. fx=1527, W=1920 -> 64.3 도."""
    hfov, vfov = fov_nominal(make_K(TEST_FX, TEST_FY), WIDTH, HEIGHT)

    expected_h = 2 * math.degrees(math.atan(WIDTH / (2 * TEST_FX)))
    expected_v = 2 * math.degrees(math.atan(HEIGHT / (2 * TEST_FY)))
    assert hfov == pytest.approx(expected_h, abs=1e-9)
    assert vfov == pytest.approx(expected_v, abs=1e-9)
    assert hfov == pytest.approx(64.3, abs=0.05)


def test_longer_focal_means_narrower() -> None:
    narrow, _ = fov_nominal(make_K(3000.0, 3000.0), WIDTH, HEIGHT)
    wide, _ = fov_nominal(make_K(1000.0, 1000.0), WIDTH, HEIGHT)
    assert narrow < wide


def test_horizontal_wider_than_vertical_on_16_9() -> None:
    """fx == fy 인 16:9 센서라면 가로 화각이 더 넓다."""
    hfov, vfov = fov_nominal(make_K(1500.0, 1500.0), WIDTH, HEIGHT)
    assert hfov > vfov


def test_ignores_principal_point() -> None:
    """fov_nominal 은 대칭을 가정한 값이다. cx 를 옮겨도 변하지 않는다.

    이 성질을 모르고 쓰면 "주점이 치우쳤는데 왜 화각이 그대로냐"가 된다.
    """
    centered = fov_nominal(make_K(1500.0, 1500.0, cx=960.0), WIDTH, HEIGHT)
    shifted = fov_nominal(make_K(1500.0, 1500.0, cx=1100.0), WIDTH, HEIGHT)
    assert centered == shifted


@pytest.mark.parametrize("fx, fy", [(0.0, 1500.0), (-1500.0, 1500.0), (1500.0, 0.0)])
def test_rejects_nonpositive_focal(fx: float, fy: float) -> None:
    with pytest.raises(ValueError):
        fov_nominal(make_K(fx, fy), WIDTH, HEIGHT)


# --- fov_effective ---------------------------------------------------------


def test_equals_nominal_when_no_distortion() -> None:
    """D = 0 이면 펼 것이 없으므로 두 값이 같아야 한다."""
    K = make_K(TEST_FX, TEST_FY)
    zero_D = np.zeros(5, dtype=np.float64)

    nominal = fov_nominal(K, WIDTH, HEIGHT)
    h_eff, v_eff, K_prime = fov_effective(K, zero_D, WIDTH, HEIGHT, alpha=0.0)

    assert h_eff == pytest.approx(nominal[0], abs=0.5)
    assert v_eff == pytest.approx(nominal[1], abs=0.5)
    assert K_prime.shape == (3, 3)


def test_barrel_makes_effective_wider_than_nominal() -> None:
    """배럴(k1<0)에서는 effective 가 nominal 보다 **넓다**. (2026-09-18 측정)

    직관과 반대라서 고정해 둔다. 배럴 렌즈는 가장자리를 안쪽으로 눌러 담으므로,
    왜곡을 펴면 nominal 이 말하는 것보다 실제로 더 넓은 각도를 담고 있었다는
    것이 드러난다. fov_nominal 로 화각을 비교하면 배럴 렌즈를 과소평가한다.
    """
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([-0.25, 0.08, 0.0, 0.0, 0.0], dtype=np.float64)

    h_nom, _ = fov_nominal(K, WIDTH, HEIGHT)
    h_eff, _, _ = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)

    assert h_eff > h_nom, f"effective {h_eff:.2f} <= nominal {h_nom:.2f}"


def test_pincushion_makes_effective_narrower_than_nominal() -> None:
    """핀쿠션(k1>0)에서는 반대로 좁아진다. 부호에 따라 대소가 뒤집힌다."""
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([0.25, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)

    h_nom, _ = fov_nominal(K, WIDTH, HEIGHT)
    h_eff, _, _ = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)

    assert h_eff < h_nom, f"effective {h_eff:.2f} >= nominal {h_nom:.2f}"


def test_strong_distortion_degenerates_silently() -> None:
    """왜곡이 아주 강하면 OpenCV 가 원본 K 를 그대로 돌려준다.

    그 값은 "왜곡이 없다"가 아니라 "계산하지 못했다"는 뜻인데, 숫자만으로는
    구분되지 않는다. is_degenerate_k_prime 이 이것을 잡아야 한다.
    """
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([-0.40, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)

    h_nom, _ = fov_nominal(K, WIDTH, HEIGHT)
    h_eff, _, K_prime = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)

    assert h_eff == pytest.approx(h_nom, abs=1e-6)  # 구분 안 되는 값
    assert is_degenerate_k_prime(K, K_prime, D) is True


def test_zero_distortion_is_not_degenerate() -> None:
    """D=0 이면 K' == K 인 것이 정상이다. 이걸 퇴화로 잡으면 안 된다."""
    K = make_K(TEST_FX, TEST_FY)
    zero_D = np.zeros(5, dtype=np.float64)
    _h, _v, K_prime = fov_effective(K, zero_D, WIDTH, HEIGHT, alpha=0.0)
    assert is_degenerate_k_prime(K, K_prime, zero_D) is False


def test_normal_distortion_is_not_degenerate() -> None:
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([-0.25, 0.08, 0.0, 0.0, 0.0], dtype=np.float64)
    _h, _v, K_prime = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)
    assert is_degenerate_k_prime(K, K_prime, D) is False


def test_alpha_one_keeps_more_than_alpha_zero() -> None:
    """alpha=1 은 원본 픽셀을 다 남긴다 (검은 여백이 생긴다) -> 화각이 더 넓다."""
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([-0.25, 0.08, 0.0, 0.0, 0.0], dtype=np.float64)

    h_zero, _, _ = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)
    h_one, _, _ = fov_effective(K, D, WIDTH, HEIGHT, alpha=1.0)
    assert h_one > h_zero


def test_k_prime_is_returned_and_consistent() -> None:
    """K' 로 fov_nominal 을 다시 계산하면 effective 와 같아야 한다 (정의 그대로)."""
    K = make_K(TEST_FX, TEST_FY)
    D = np.array([-0.25, 0.08, 0.0, 0.0, 0.0], dtype=np.float64)

    h_eff, v_eff, K_prime = fov_effective(K, D, WIDTH, HEIGHT, alpha=0.0)
    again = fov_nominal(K_prime, WIDTH, HEIGHT)
    assert again[0] == pytest.approx(h_eff, abs=1e-9)
    assert again[1] == pytest.approx(v_eff, abs=1e-9)


@pytest.mark.parametrize("alpha", [-0.1, 1.1])
def test_alpha_range_is_checked(alpha: float) -> None:
    with pytest.raises(ValueError):
        fov_effective(make_K(1500.0, 1500.0), np.zeros(5), WIDTH, HEIGHT, alpha=alpha)
