"""run_remap - 실제 영상을 공통 공간으로 옮긴다 (5단계).

가장 중요한 검사는 **항등 변환**이다. 카메라가 곧 target 이면 (K_src == K_target,
D 가 모두 0) 출력이 입력과 같아야 한다. 여기가 틀리면 나머지 변환은 전부 틀린다.
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

import run_remap
from camcal.board import BoardSpec
from camcal.session import Session
from camcal.target_space import TARGET_SPACE_FILENAME, TargetSpace

from test_target_space import make_reference

WIDTH, HEIGHT = 1920, 1080


def noisy_image() -> np.ndarray:
    """무늬가 있는 이미지. 평평한 회색이면 틀려도 같아 보인다."""
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)


def write_intrinsics(tmp_path, camera: str, K, D) -> tuple:
    from camcal.fov import fov_effective, fov_nominal

    K = np.asarray(K, dtype=np.float64)
    D = np.asarray(D, dtype=np.float64)
    hn, vn = fov_nominal(K, WIDTH, HEIGHT)
    he, ve, K_prime = fov_effective(K, D, WIDTH, HEIGHT, 0.0)
    data = {
        "camera": camera,
        "session_id": f"sess_{camera}",
        "resolution": [WIDTH, HEIGHT],
        "K": K.tolist(),
        "D": D.tolist(),
        "fov_nominal": {"h": hn, "v": vn},
        "fov_effective": {"h": he, "v": ve, "K_prime": K_prime.tolist()},
    }
    path = tmp_path / f"{camera}_intrinsics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


# --- 항등 변환 ---------------------------------------------------------------


def test_identity_remap_returns_the_same_image(tmp_path) -> None:
    """K_src == K_target, D 모두 0 -> 출력이 입력과 같아야 한다."""
    K = np.array([[1500.0, 0, 960.0], [0, 1500.0, 540.0], [0, 0, 1.0]])
    zero = np.zeros(5)
    _path, intr = write_intrinsics(tmp_path, "cam", K, zero)

    target = TargetSpace(
        design=3,
        K_target=K.tolist(),
        D_target=zero.tolist(),
        reference_camera="cam",
        reference_session="s",
        f_target_scale=1.0,
        resolution=[WIDTH, HEIGHT],
        created_at="now",
    )
    map_x, map_y = run_remap.build_map(intr, target)
    image = noisy_image()
    out = run_remap.remap_image(image, map_x, map_y)

    assert out.shape == image.shape
    # 보간 오차로 완전 동일하지는 않을 수 있으나 거의 같아야 한다
    assert np.mean(np.abs(out.astype(int) - image.astype(int))) < 1.0


def test_design_changes_the_result(tmp_path) -> None:
    """②/③ 은 다른 공간이다. 같은 입력에 같은 결과가 나오면 둘 중 하나가 무시된 것이다."""
    reference = make_reference()
    K = np.array(reference["K"])
    D = np.array([-0.1, 0.02, 0.0, 0.0, 0.0])
    _p, intr = write_intrinsics(tmp_path, "s10", K, D)

    t3 = TargetSpace.from_intrinsics(reference, design=3, f_target_scale=1.0)
    t2 = TargetSpace.from_intrinsics(reference, design=2)

    m3 = run_remap.build_map(intr, t3)
    m2 = run_remap.build_map(intr, t2)
    assert not np.allclose(m3[0], m2[0]), "②/③ 이 같은 맵을 만들었다"


# --- crop --------------------------------------------------------------------


def test_crop_box_removes_black_border() -> None:
    mask = np.zeros((100, 200), dtype=bool)
    mask[10:90, 20:180] = True
    x, y, w, h = run_remap.crop_box(mask)
    assert (x, y, w, h) == (20, 10, 160, 80)


def test_crop_box_handles_a_curved_border() -> None:
    """검은 테두리는 왜곡 때문에 곡선이다. '완전한 행'을 찾는 방식은 통하지 않는다."""
    height, width = 200, 300
    yy, xx = np.mgrid[0:height, 0:width]
    mask = ((xx - width / 2) ** 2 / (width / 2.3) ** 2
            + (yy - height / 2) ** 2 / (height / 2.3) ** 2) < 1
    assert not mask.all(axis=1).any(), "완전히 유효한 행이 있으면 이 테스트가 무의미하다"

    x, y, w, h = run_remap.crop_box(mask)
    assert w > 0 and h > 0
    assert mask[y : y + h, x : x + w].all(), "잘라낸 영역에 무효 픽셀이 남았다"


def test_crop_box_refuses_when_almost_nothing_is_left() -> None:
    """조용히 손톱만 한 이미지를 내놓지 않는다."""
    mask = np.zeros((50, 50), dtype=bool)
    mask[10, 10] = True
    with pytest.raises(ValueError) as exc:
        run_remap.crop_box(mask)
    assert "f_target" in str(exc.value)


def test_crop_box_refuses_an_empty_mask() -> None:
    with pytest.raises(ValueError) as exc:
        run_remap.crop_box(np.zeros((10, 10), dtype=bool))
    assert "유효한 픽셀이 하나도 없다" in str(exc.value)


def test_crop_shrinks_the_output(tmp_path) -> None:
    K = np.array([[1500.0, 0, 960.0], [0, 1500.0, 540.0], [0, 0, 1.0]])
    _p, intr = write_intrinsics(tmp_path, "cam", K, np.zeros(5))
    K_wide = K.copy()
    K_wide[0, 0] *= 0.8
    K_wide[1, 1] *= 0.8  # 넓은 target -> 검은 영역이 생긴다

    target = TargetSpace(
        design=3, K_target=K_wide.tolist(), D_target=[0.0] * 5,
        reference_camera="cam", reference_session="s", f_target_scale=1.0,
        resolution=[WIDTH, HEIGHT], created_at="now",
    )
    map_x, map_y = run_remap.build_map(intr, target)
    from camcal.remap_metrics import valid_mask

    mask = valid_mask(map_x, map_y, WIDTH, HEIGHT)
    box = run_remap.crop_box(mask)
    out = run_remap.remap_image(noisy_image(), map_x, map_y, box)

    assert out.shape[1] < WIDTH and out.shape[0] < HEIGHT
    assert out[:, :, :].min() >= 0  # 검은 테두리가 없어야 한다 (전부 유효)


# --- 입력 --------------------------------------------------------------------


def test_session_input_uses_meta_not_glob(tmp_path, spec: BoardSpec) -> None:
    """세션 폴더에 출처 불명 PNG 가 섞여 있어도 meta.json 이 아는 것만 쓴다."""
    session = Session.create(
        data_root=tmp_path, camera="cam", board=spec,
        resolution_requested=(WIDTH, HEIGHT), resolution_actual=(WIDTH, HEIGHT),
    )
    flat = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
    for _ in range(3):
        session.add_frame(flat, detected=True, n_corners=spec.n_corners)
    session.close()
    cv2.imwrite(str(session.frames_dir / "099.png"), flat)  # 고아 파일

    files = run_remap.collect_inputs([session.path])
    assert len(files) == 3
    assert all("099" not in f.name for f in files)


def test_missing_input_stops(tmp_path) -> None:
    with pytest.raises(SystemExit):
        run_remap.collect_inputs([tmp_path / "없는파일.png"])


# --- CLI ---------------------------------------------------------------------


def test_cli_refuses_to_pick_a_design(tmp_path, capsys) -> None:
    """target_space.json 이 없고 --design 도 없으면 **멈춘다.** 몰래 고르지 않는다."""
    K = np.array([[1500.0, 0, 960.0], [0, 1500.0, 540.0], [0, 0, 1.0]])
    intr_path, _ = write_intrinsics(tmp_path, "cam", K, np.zeros(5))
    image = tmp_path / "a.png"
    cv2.imwrite(str(image), noisy_image())

    code = run_remap.main([
        str(image), "--intrinsics", str(intr_path),
        "-o", str(tmp_path / "out"), "--results-dir", str(tmp_path / "results"),
    ])
    assert code == 2
    assert "--design" in capsys.readouterr().err


def test_cli_creates_target_space_then_reuses_it(tmp_path, capsys) -> None:
    reference = make_reference()
    ref_path = tmp_path / "luaz_intrinsics.json"
    ref_path.write_text(json.dumps(reference), encoding="utf-8")

    K = np.array(reference["K"])
    intr_path, _ = write_intrinsics(tmp_path, "s10", K, np.array([-0.1, 0, 0, 0, 0.0]))
    image = tmp_path / "a.png"
    cv2.imwrite(str(image), noisy_image())
    results = tmp_path / "results"

    # 1) 설계를 명시해 공간을 만든다
    code = run_remap.main([
        str(image), "--intrinsics", str(intr_path), "-o", str(tmp_path / "out1"),
        "--design", "3", "--reference", str(ref_path), "--f-target-scale", "1.10",
        "--results-dir", str(results),
    ])
    assert code == 0
    saved = TargetSpace.load(results / TARGET_SPACE_FILENAME)
    assert saved.design == 3 and saved.f_target_scale == 1.10
    assert (tmp_path / "out1" / "a.png").is_file()

    # 2) 두 번째부터는 그 파일을 그대로 쓴다
    code = run_remap.main([
        str(image), "--intrinsics", str(intr_path), "-o", str(tmp_path / "out2"),
        "--results-dir", str(results),
    ])
    assert code == 0
    assert "기존" in capsys.readouterr().out


def test_cli_warns_when_overwriting_target_space(tmp_path, capsys) -> None:
    """공간을 바꾸면 이전에 변환해 둔 결과물과 섞을 수 없다. 조용히 바꾸지 않는다."""
    reference = make_reference()
    ref_path = tmp_path / "luaz_intrinsics.json"
    ref_path.write_text(json.dumps(reference), encoding="utf-8")
    K = np.array(reference["K"])
    intr_path, _ = write_intrinsics(tmp_path, "s10", K, np.zeros(5))
    image = tmp_path / "a.png"
    cv2.imwrite(str(image), noisy_image())
    results = tmp_path / "results"

    common = [str(image), "--intrinsics", str(intr_path), "--reference", str(ref_path),
              "--results-dir", str(results)]
    run_remap.main(common + ["-o", str(tmp_path / "o1"), "--design", "3"])
    capsys.readouterr()
    run_remap.main(common + ["-o", str(tmp_path / "o2"), "--design", "2"])

    err = capsys.readouterr().err
    assert "덮어쓴다" in err and "섞을 수 없다" in err


def test_cli_stops_on_resolution_mismatch(tmp_path) -> None:
    reference = make_reference()
    ref_path = tmp_path / "luaz_intrinsics.json"
    ref_path.write_text(json.dumps(reference), encoding="utf-8")
    K = np.array(reference["K"])
    intr_path, data = write_intrinsics(tmp_path, "s10", K, np.zeros(5))
    data["resolution"] = [1280, 720]
    intr_path.write_text(json.dumps(data), encoding="utf-8")
    image = tmp_path / "a.png"
    cv2.imwrite(str(image), noisy_image())

    with pytest.raises(SystemExit) as exc:
        run_remap.main([
            str(image), "--intrinsics", str(intr_path), "-o", str(tmp_path / "out"),
            "--design", "3", "--reference", str(ref_path),
            "--results-dir", str(tmp_path / "results"),
        ])
    assert "해상도" in str(exc.value)
