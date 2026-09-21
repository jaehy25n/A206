"""run_calibrate 전체 왕복 - 이미지에서 시작해 JSON 과 리포트까지.

test_calibrate_synthetic.py 는 코너 좌표부터 시작한다 (검출기를 건너뛴다).
여기서는 **실제 PNG 를 그려 세션에 저장**하고, 검출부터 리포트 렌더링까지
run_calibrate 가 하는 일을 그대로 돌린다.

호모그래피로 그리므로 이 이미지에는 렌즈 왜곡이 없다 (D = 0 인 장면).
따라서 추정된 D 도 0 근처여야 맞다. 왜곡이 있는 검증은 synthetic 쪽이 한다.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import run_calibrate
from camcal.board import BoardSpec
from camcal.calibrate import detect_session_corners
from camcal.combined import CombinedSession
from camcal.session import Session
from synth import IMAGE_SIZE, TRUE_K, default_poses, render_pose

#: 이미지를 진짜로 그리고 검출까지 하므로 장수를 줄인다 (그려도 정보량은 충분하다).
N_IMAGES = 12
N_TRAIN = 9


@pytest.fixture(scope="module")
def rendered(request):
    """(frames, spec). 모듈 단위로 한 번만 그린다 (warpPerspective x 12)."""
    spec = BoardSpec(cols=9, rows=6, square_mm=25.0, square_mm_measured=True, note="synth")
    frames = [
        render_pose(spec, rvec, tvec)
        for rvec, tvec in default_poses(spec, TRUE_K, N_IMAGES)
    ]
    return frames, spec


@pytest.fixture
def combined(session: Session) -> CombinedSession:
    """build_report 는 이제 CombinedSession 을 받는다 (세션 1개도 같은 경로)."""
    return CombinedSession.open([session.path])


@pytest.fixture
def session(tmp_path, rendered) -> Session:
    frames, spec = rendered
    s = Session.create(
        data_root=tmp_path,
        camera="synth",
        board=spec,
        resolution_requested=IMAGE_SIZE,
        resolution_actual=IMAGE_SIZE,
        capture_settings={"source": "test_render"},
    )
    for frame in frames:
        s.add_frame(frame, detected=True, n_corners=spec.n_corners)
    s.close()
    return s


# --- 검출 ------------------------------------------------------------------


def test_all_rendered_frames_detect(session: Session) -> None:
    """그린 이미지가 전부 검출돼야 이후 단계가 의미 있다."""
    corners = detect_session_corners(session)
    assert len(corners) == N_IMAGES
    for c in corners.values():
        assert c.shape == (session.board.n_corners, 1, 2)


def test_detect_raises_when_board_spec_disagrees(tmp_path, rendered) -> None:
    """meta.json 은 검출 성공이라는데 지금은 안 되는 경우 조용히 넘기지 않는다."""
    frames, _spec = rendered
    wrong = BoardSpec(cols=7, rows=5, square_mm=25.0, square_mm_measured=True)
    s = Session.create(
        data_root=tmp_path,
        camera="synth",
        board=wrong,
        resolution_requested=IMAGE_SIZE,
        resolution_actual=IMAGE_SIZE,
    )
    s.add_frame(frames[0], detected=True, n_corners=wrong.n_corners)
    with pytest.raises(RuntimeError) as exc:
        detect_session_corners(s)
    assert "board.yaml" in str(exc.value)


# --- 리포트 dict -----------------------------------------------------------


def test_build_report_recovers_K(combined: CombinedSession) -> None:
    report = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)
    K = np.asarray(report["K"])

    assert abs(K[0, 0] - TRUE_K[0, 0]) / TRUE_K[0, 0] < 0.02
    assert abs(K[1, 1] - TRUE_K[1, 1]) / TRUE_K[1, 1] < 0.02


def test_rendered_scene_has_no_distortion(combined: CombinedSession) -> None:
    """호모그래피로 그렸으니 D 가 0 근처여야 한다. 크게 나오면 렌더러가 틀린 것이다."""
    report = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)
    assert abs(report["D"][0]) < 0.02, f"k1={report['D'][0]:.4f}"


def test_report_contains_all_four_checks(combined: CombinedSession) -> None:
    """RMS 만 보지 말라는 네 항목이 전부 dict 에 들어 있어야 한다."""
    report = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)

    assert report["spatial"]["grid"] == 4                 # 1. 공간 분포
    assert "mean_dot" in report["radiality"]              # 2. 방향성
    assert set(report["stability"]) >= {"fx", "fy", "cx", "cy"}  # 3. 안정성
    assert report["rms_holdout"] is not None              # 4. 홀드아웃
    assert len(report["holdout_per_image"]) == N_IMAGES - N_TRAIN


def test_split_recorded_in_report(combined: CombinedSession) -> None:
    """시드와 분할이 기록돼야 나중에 같은 결과를 재현할 수 있다."""
    report = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=3)
    assert report["seed"] == 3
    assert len(report["train_ids"]) == N_TRAIN
    assert set(report["train_ids"]) & set(report["holdout_ids"]) == set()


def test_two_fov_values_both_present(combined: CombinedSession) -> None:
    report = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)
    assert report["fov_nominal"]["h"] > 0
    assert report["fov_effective"]["h"] > 0
    assert np.asarray(report["fov_effective"]["K_prime"]).shape == (3, 3)
    assert report["fov_degenerate"] is False


# --- CLI 전체 --------------------------------------------------------------


def test_cli_writes_json_and_report(session: Session, tmp_path, capsys) -> None:
    results = tmp_path / "results"
    code = run_calibrate.main(
        [str(session.path), "--n-train", str(N_TRAIN), "--seed", "0", "--results-dir", str(results)]
    )
    assert code == 0

    json_path = results / "synth_intrinsics.json"
    md_path = results / "reports" / f"{session.session_id}.md"
    png_path = results / "reports" / f"{session.session_id}_residuals.png"
    assert json_path.is_file() and md_path.is_file() and png_path.is_file()
    assert png_path.stat().st_size > 1000  # 빈 그림이 아니어야 한다

    data = json.loads(json_path.read_text(encoding="utf-8"))
    for key in (
        "camera", "session_id", "resolution", "K", "D", "D_model",
        "rms_train", "rms_holdout", "n_train", "n_holdout", "seed",
        "stability", "fov_nominal", "fov_effective", "warnings", "created_at",
    ):
        assert key in data, f"JSON 에 {key} 가 없다"
    assert data["D_model"] == "opencv_5"
    assert len(data["D"]) == data["D_length"]
    assert "_residuals" not in data  # 큰 배열은 JSON 에 넣지 않는다

    md = md_path.read_text(encoding="utf-8")
    for heading in ("공간 분포", "방향성", "안정성", "홀드아웃"):
        assert heading in md, f"리포트에 '{heading}' 항목이 없다"
    assert f"{session.session_id}_residuals.png" in md
    assert "RMS 는" in md  # RMS 해석 문단

    out = capsys.readouterr().out
    assert "RMS" in out and "fx" in out and "FOV" in out


def test_cli_stops_when_holdout_would_be_empty(session: Session, tmp_path, capsys) -> None:
    code = run_calibrate.main(
        [str(session.path), "--n-train", str(N_IMAGES), "--results-dir", str(tmp_path / "r")]
    )
    assert code == 2
    assert "n-train" in capsys.readouterr().err


def test_same_seed_same_numbers(combined: CombinedSession) -> None:
    """결정적이어야 한다. 같은 입력에 두 번 돌려 같은 K 가 나오는지."""
    a = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)
    b = run_calibrate.build_report(combined, n_train=N_TRAIN, seed=0)
    assert a["K"] == b["K"]
    assert a["rms_train"] == b["rms_train"]
    assert a["stability"]["fx"]["std"] == b["stability"]["fx"]["std"]
