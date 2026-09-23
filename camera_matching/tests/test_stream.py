"""FrameRemapper - 다른 프로그램이 쓰는 제품. 계약을 여기서 못 박는다.

계약
    1. 맵은 만들 때 정한 **입력 크기**에만 쓴다. 다른 크기가 오면 예외
    2. 해상도가 캘리브레이션과 달라도 **종횡비가 같으면** 정확히 처리한다
    3. 종횡비가 다르면 (크롭이 들어갔다는 뜻) 거부한다
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from camcal.stream import (
    ASPECT_TOLERANCE,
    FrameRemapper,
    ResolutionMismatch,
    scale_intrinsics,
)
from camcal.target_space import TargetSpace

from test_target_space import make_reference

WIDTH, HEIGHT = 1920, 1080


def make_intrinsics(fx: float = 1600.0, k1: float = -0.1) -> dict:
    return {
        "camera": "cam",
        "resolution": [WIDTH, HEIGHT],
        "K": [[fx, 0.0, 960.0], [0.0, fx, 540.0], [0.0, 0.0, 1.0]],
        "D": [k1, 0.0, 0.0, 0.0, 0.0],
    }


def noisy(width: int = WIDTH, height: int = HEIGHT) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


@pytest.fixture
def target() -> TargetSpace:
    return TargetSpace.from_intrinsics(make_reference(), design=3, f_target_scale=1.10)


# --- 항등 ---------------------------------------------------------------------


def test_identity_passes_the_image_through() -> None:
    """카메라가 곧 target 이면 출력이 입력과 (거의) 같아야 한다."""
    K = [[1500.0, 0.0, 960.0], [0.0, 1500.0, 540.0], [0.0, 0.0, 1.0]]
    intrinsics = {"camera": "cam", "resolution": [WIDTH, HEIGHT], "K": K, "D": [0.0] * 5}
    target = TargetSpace(
        design=3, K_target=K, D_target=[0.0] * 5, reference_camera="cam",
        reference_session="s", f_target_scale=1.0, resolution=[WIDTH, HEIGHT],
        created_at="now",
    )
    remapper = FrameRemapper.build(intrinsics, target)
    image = noisy()
    out = remapper.apply(image)

    assert out.shape == image.shape
    assert np.mean(np.abs(out.astype(int) - image.astype(int))) < 1.5
    assert remapper.valid_ratio == pytest.approx(1.0, abs=0.01)


# --- 입력 크기 계약 -----------------------------------------------------------


def test_wrong_frame_size_is_refused(target: TargetSpace) -> None:
    """맵은 크기마다 따로다. 조용히 늘려 쓰면 화면이 망가진다 (result.md 11-4)."""
    remapper = FrameRemapper.build(make_intrinsics(), target)
    with pytest.raises(ResolutionMismatch) as exc:
        remapper.apply(noisy(1280, 720))
    assert "프레임 크기가 다르다" in str(exc.value)


def test_smaller_input_is_handled_exactly(target: TargetSpace) -> None:
    """절반으로 줄여 들어와도 같은 화각을 내야 한다 (단순 리사이즈는 화각을 안 바꾼다)."""
    intrinsics = make_intrinsics()
    full = FrameRemapper.build(intrinsics, target)
    half = FrameRemapper.build(intrinsics, target, input_size=(960, 540))

    assert half.input_size == (960, 540)
    assert half.output_size == full.output_size
    # 유효 비율이 거의 같아야 한다 (같은 화각을 같은 target 격자에 담으므로)
    assert half.valid_ratio == pytest.approx(full.valid_ratio, abs=0.02)


def test_different_aspect_is_refused(target: TargetSpace) -> None:
    """종횡비가 다르면 크롭이다. 크롭은 화각을 바꾸므로 K 를 고칠 수 없다."""
    with pytest.raises(ResolutionMismatch) as exc:
        FrameRemapper.build(make_intrinsics(), target, input_size=(1440, 1080))  # 4:3
    assert "종횡비" in str(exc.value)


def test_tiny_aspect_difference_is_tolerated(target: TargetSpace) -> None:
    """반올림으로 생기는 미세한 차이까지 막으면 쓸 수가 없다."""
    remapper = FrameRemapper.build(make_intrinsics(), target, input_size=(1921, 1080))
    assert remapper.input_size == (1921, 1080)


# --- scale_intrinsics ---------------------------------------------------------


def test_scale_intrinsics_preserves_fov() -> None:
    from camcal.fov import fov_nominal

    K = np.array([[1600.0, 0.0, 960.0], [0.0, 1600.0, 540.0], [0.0, 0.0, 1.0]])
    full = fov_nominal(K, WIDTH, HEIGHT)
    half = fov_nominal(scale_intrinsics(K, 0.5), WIDTH // 2, HEIGHT // 2)
    assert half[0] == pytest.approx(full[0], abs=1e-9)


# --- crop ---------------------------------------------------------------------


def test_crop_removes_the_black_border(target: TargetSpace) -> None:
    intrinsics = make_intrinsics(fx=1200.0)  # 넓게 봐서 검은 영역이 생기게
    plain = FrameRemapper.build(intrinsics, target)
    cropped = FrameRemapper.build(intrinsics, target, crop=True)

    out = cropped.apply(noisy())
    assert out.shape[1] <= plain.output_size[0]
    assert out.shape[0] <= plain.output_size[1]
    assert (out.max(axis=2) < 8).mean() < 0.01, "잘라냈는데 검은 영역이 남았다"


# --- 파일에서 만들기 -----------------------------------------------------------


def test_from_files_round_trip(tmp_path, target: TargetSpace) -> None:
    from camcal.target_space import TARGET_SPACE_FILENAME

    intrinsics_path = tmp_path / "cam_intrinsics.json"
    intrinsics_path.write_text(json.dumps(make_intrinsics()), encoding="utf-8")
    target.save(tmp_path / TARGET_SPACE_FILENAME)

    remapper = FrameRemapper.from_files(intrinsics_path)
    assert remapper.camera == "cam"
    assert remapper.design == 3
    assert remapper.apply(noisy()).shape[:2] == (HEIGHT, WIDTH)


def test_from_files_without_target_explains(tmp_path) -> None:
    intrinsics_path = tmp_path / "cam_intrinsics.json"
    intrinsics_path.write_text(json.dumps(make_intrinsics()), encoding="utf-8")
    with pytest.raises(FileNotFoundError) as exc:
        FrameRemapper.from_files(intrinsics_path)
    assert "--design" in str(exc.value)


def test_describe_is_readable(target: TargetSpace) -> None:
    remapper = FrameRemapper.build(make_intrinsics(), target)
    text = remapper.describe()
    assert "1920x1080" in text and "설계 3" in text and "유효" in text


# --- 성능 ---------------------------------------------------------------------


def test_apply_is_fast_enough_for_realtime(target: TargetSpace) -> None:
    """1080p 30fps 는 33ms 예산이다. 변환이 그 절반을 넘으면 곤란하다."""
    import time

    remapper = FrameRemapper.build(make_intrinsics(), target)
    image = noisy()
    remapper.apply(image)  # 첫 호출은 캐시 워밍

    start = time.perf_counter()
    for _ in range(10):
        remapper.apply(image)
    per_frame_ms = (time.perf_counter() - start) / 10 * 1000

    assert per_frame_ms < 16.0, f"프레임당 {per_frame_ms:.1f} ms 로 너무 느리다"
