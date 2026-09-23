"""TargetSpace - ②/③ 결정을 한 곳에 못 박는다.

두 사람이 각자 K_target 을 계산하면 미세하게 다른 공간이 생기고, 그 차이는
영상만 봐서는 보이지 않는다. 그래서 결정은 파일 하나에 적고 모두가 그것을 읽는다.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from camcal.fov import fov_effective, fov_nominal
from camcal.target_space import (
    DESIGN_DISTORTED,
    DESIGN_PINHOLE,
    TARGET_SPACE_FILENAME,
    TargetSpace,
)

WIDTH, HEIGHT = 1920, 1080


def make_reference(fx: float = 1639.4, k1: float = 0.275) -> dict:
    K = np.array([[fx, 0.0, 960.0], [0.0, fx * 0.995, 540.0], [0.0, 0.0, 1.0]])
    D = np.array([k1, 0.0, 0.0, 0.0, 0.0])
    hn, vn = fov_nominal(K, WIDTH, HEIGHT)
    he, ve, K_prime = fov_effective(K, D, WIDTH, HEIGHT, 0.0)
    return {
        "camera": "luaz",
        "session_id": "sess_luaz",
        "resolution": [WIDTH, HEIGHT],
        "K": K.tolist(),
        "D": D.tolist(),
        "fov_nominal": {"h": hn, "v": vn},
        "fov_effective": {"h": he, "v": ve, "K_prime": K_prime.tolist()},
    }


# --- 설계를 가르는 것은 D_target 이다 ----------------------------------------


def test_design3_has_zero_distortion() -> None:
    """③ 의 정의는 D_target = 0 이다. K_target 이 아니다."""
    target = TargetSpace.from_intrinsics(make_reference(), design=DESIGN_PINHOLE)
    assert np.all(target.D == 0)
    assert target.is_pinhole is True


def test_design2_keeps_reference_distortion() -> None:
    reference = make_reference()
    target = TargetSpace.from_intrinsics(reference, design=DESIGN_DISTORTED)

    assert np.allclose(target.D, np.asarray(reference["D"]))
    assert np.allclose(target.K, np.asarray(reference["K"]))
    assert target.is_pinhole is False


def test_design2_uses_K_not_K_prime() -> None:
    """② 는 기준 카메라 **원본** 이 target 이다. K' 를 쓰면 다른 공간이 된다."""
    reference = make_reference()
    target = TargetSpace.from_intrinsics(reference, design=DESIGN_DISTORTED)
    K_prime = np.asarray(reference["fov_effective"]["K_prime"])

    assert target.K[0, 0] == pytest.approx(reference["K"][0][0])
    assert target.K[0, 0] != pytest.approx(K_prime[0, 0])


def test_design3_scales_only_focal() -> None:
    reference = make_reference()
    K_prime = np.asarray(reference["fov_effective"]["K_prime"])
    target = TargetSpace.from_intrinsics(
        reference, design=DESIGN_PINHOLE, f_target_scale=1.10
    )

    assert target.K[0, 0] == pytest.approx(K_prime[0, 0] * 1.10)
    assert target.K[0, 2] == pytest.approx(K_prime[0, 2])  # 주점은 그대로


# --- 잘못 쓰면 멈춘다 --------------------------------------------------------


def test_design2_rejects_scaling() -> None:
    """② 에서 배율을 만지면 더 이상 'LUAZ 원본'이 아니다."""
    with pytest.raises(ValueError) as exc:
        TargetSpace.from_intrinsics(
            make_reference(), design=DESIGN_DISTORTED, f_target_scale=1.10
        )
    assert "설계 ②" in str(exc.value)


@pytest.mark.parametrize("design", [0, 1, 4, -3])
def test_unknown_design_is_refused(design: int) -> None:
    with pytest.raises(ValueError):
        TargetSpace.from_intrinsics(make_reference(), design=design)


def test_load_missing_file_explains_how_to_make_it(tmp_path) -> None:
    """없으면 조용히 기본값을 쓰지 않고, 만드는 방법을 알려주고 멈춘다."""
    with pytest.raises(FileNotFoundError) as exc:
        TargetSpace.load(tmp_path / TARGET_SPACE_FILENAME)
    assert "--design" in str(exc.value)


# --- 저장 / 복원 -------------------------------------------------------------


def test_round_trip(tmp_path) -> None:
    target = TargetSpace.from_intrinsics(
        make_reference(), design=DESIGN_PINHOLE, f_target_scale=1.10, note="테스트"
    )
    path = target.save(tmp_path / TARGET_SPACE_FILENAME)
    loaded = TargetSpace.load(path)

    assert loaded.design == target.design
    assert np.allclose(loaded.K, target.K)
    assert np.allclose(loaded.D, target.D)
    assert loaded.f_target_scale == 1.10
    assert loaded.note == "테스트"
    assert loaded.reference_camera == "luaz"


def test_saved_json_is_readable_by_a_human(tmp_path) -> None:
    """나중에 이 값을 의심할 때 열어볼 파일이다. 무엇으로 만들었는지 남아야 한다."""
    target = TargetSpace.from_intrinsics(
        make_reference(), design=DESIGN_PINHOLE, f_target_scale=1.10
    )
    path = target.save(tmp_path / TARGET_SPACE_FILENAME)
    data = json.loads(path.read_text(encoding="utf-8"))

    for key in ("design", "K_target", "D_target", "reference_camera",
                "reference_session", "f_target_scale", "resolution", "created_at"):
        assert key in data, f"{key} 가 없으면 이 공간을 재현할 수 없다"


def test_describe_mentions_the_design(tmp_path) -> None:
    target = TargetSpace.from_intrinsics(make_reference(), design=DESIGN_PINHOLE)
    assert "③" in target.describe()
    assert "D_target 0" in target.describe()
