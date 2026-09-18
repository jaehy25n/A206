"""run_fov_compare 전체 - 두 intrinsics.json -> 리포트.

이 리포트의 항목 이름은 README "미정 결정" 표와 일치해야 한다. 문서와 산출물이
다른 말을 쓰기 시작하면 ②/③ 를 놓고 이야기할 때 서로 다른 것을 가리키게 된다.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

import run_fov_compare
from camcal.fov import fov_effective, fov_nominal, is_degenerate_k_prime

WIDTH, HEIGHT = 1920, 1080


def make_intrinsics(camera: str, fx: float, fy: float, k1: float, k2: float = 0.0) -> dict:
    """run_calibrate 가 내는 것과 같은 모양의 intrinsics dict (합성값)."""
    K = np.array([[fx, 0.0, WIDTH / 2], [0.0, fy, HEIGHT / 2], [0.0, 0.0, 1.0]])
    D = np.array([k1, k2, 0.0, 0.0, 0.0])
    hn, vn = fov_nominal(K, WIDTH, HEIGHT)
    he, ve, K_prime = fov_effective(K, D, WIDTH, HEIGHT, 0.0)
    return {
        "camera": camera,
        "session_id": f"synthetic_{camera}",
        "resolution": [WIDTH, HEIGHT],
        "K": K.tolist(),
        "D": D.tolist(),
        "D_model": "opencv_5",
        "fov_nominal": {"h": hn, "v": vn},
        "fov_effective": {"h": he, "v": ve, "K_prime": K_prime.tolist()},
        "fov_degenerate": is_degenerate_k_prime(K, K_prime, D),
        "rms_train": 0.2137,  # 리포트에 나오면 안 되는 값
    }


def write_pair(tmp_path: Path, src: dict, dst: dict) -> tuple[Path, Path]:
    src_path = tmp_path / f"{src['camera']}_intrinsics.json"
    dst_path = tmp_path / f"{dst['camera']}_intrinsics.json"
    src_path.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    dst_path.write_text(json.dumps(dst, ensure_ascii=False), encoding="utf-8")
    return src_path, dst_path


@pytest.fixture
def wide_src() -> dict:
    """S10 역할. 더 넓게 본다 (fx 가 작다)."""
    return make_intrinsics("s10", 1380.0, 1377.0, -0.11, 0.03)


@pytest.fixture
def narrow_dst() -> dict:
    """LUAZ 역할. 더 좁게 본다 -> 게이트 통과가 기대된다."""
    return make_intrinsics("luaz", 1527.0, 1520.0, -0.24, 0.07)


def run(tmp_path, src: dict, dst: dict):
    src_path, dst_path = write_pair(tmp_path, src, dst)
    out_dir = tmp_path / "reports"
    code = run_fov_compare.main([str(src_path), str(dst_path), "--out-dir", str(out_dir)])
    return code, out_dir, (out_dir / "fov_compare.md").read_text(encoding="utf-8")


# --- 리포트 내용 ------------------------------------------------------------


def test_report_has_all_six_sections(tmp_path, wide_src, narrow_dst) -> None:
    code, out_dir, md = run(tmp_path, wide_src, narrow_dst)
    assert code == 0

    for heading in (
        "## 1. 두 카메라의 화각",
        "## 2. 게이트",
        "## 3. 설계 ③ 가상 카메라 = target",
        "## 4. 설계 ② LUAZ 원본 = target",
        "## 5. 판정 참고",
        "## 6. 이 리포트에 RMS 가 없는 이유",
    ):
        assert heading in md, f"리포트에 '{heading}' 가 없다"


def test_names_match_readme_table(tmp_path, wide_src, narrow_dst) -> None:
    """README '미정 결정' 표의 용어를 그대로 쓴다."""
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    for term in (
        "② LUAZ 원본",
        "③ 가상 카메라",
        "K_target",
        "D_target",
        "fov_nominal",
        "fov_effective",
        "valid pixel ratio",
        "local stretch",
    ):
        assert term in md, f"README 용어 '{term}' 가 리포트에 없다"


def test_rms_is_not_in_the_report(tmp_path, wide_src, narrow_dst) -> None:
    """RMS 는 target 적합성과 무관하므로 이 리포트에 숫자로 넣지 않는다.

    (왜 넣지 않는지 설명하는 6장은 있어야 한다 - 그래서 숫자만 확인한다)
    """
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    assert "0.2137" not in md, "RMS 값이 리포트에 들어갔다"
    assert "rms_train" not in md


def test_both_designs_are_measured(tmp_path, wide_src, narrow_dst) -> None:
    """어느 설계도 미리 고르지 않는다. 양쪽 숫자가 다 있어야 한다."""
    _code, out_dir, md = run(tmp_path, wide_src, narrow_dst)

    assert "s10 -> 가상 카메라 (설계 ③)" in md
    assert "luaz -> 가상 카메라 (설계 ③)" in md
    assert "s10 -> luaz 원본 (설계 ②)" in md
    assert "변환 없음" in md  # 설계 ② 의 LUAZ

    pngs = sorted(p.name for p in out_dir.glob("*.png"))
    assert pngs == ["stretch_design2_0.png", "stretch_design3_0.png", "stretch_design3_1.png"]
    for p in out_dir.glob("*.png"):
        assert p.stat().st_size > 1000


def test_decision_is_left_to_a_human(tmp_path, wide_src, narrow_dst) -> None:
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    assert "최종 결정은 사람이 한다" in md
    assert "기하학적으로" in md


# --- 게이트 ----------------------------------------------------------------


def test_gate_passes_when_dst_is_narrower(tmp_path, wide_src, narrow_dst) -> None:
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    assert "**통과.**" in md
    assert "**불통과**" not in md


def test_gate_note_is_always_present(tmp_path, wide_src, narrow_dst) -> None:
    """게이트를 통과해도 설계 ② 가 성립한다는 뜻은 아니다.

    게이트는 H, V 를 축별로 비교한다. 두 축이 다 통과해도 화면 **모서리**는 따로다
    (대각 방향은 H 도 V 도 아니고, 왜곡 때문에 화각 경계가 직사각형이 아니다).
    모서리가 실제로 채워지는지는 valid_ratio 가 답한다. 그 구분을 리포트가
    빠뜨리면 게이트 통과를 곧 ② 가능으로 읽게 된다.
    """
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    assert run_fov_compare.GATE_NOTE in md
    assert "모서리" in md and "valid_ratio" in md


def test_gate_note_is_present_even_when_gate_fails(tmp_path, capsys) -> None:
    src = make_intrinsics("s10", 1700.0, 1695.0, -0.05)
    dst = make_intrinsics("luaz", 1200.0, 1196.0, -0.20)
    _code, _out, md = run(tmp_path, src, dst)
    assert run_fov_compare.GATE_NOTE in md


def test_gate_note_sits_in_the_gate_section(tmp_path, wide_src, narrow_dst) -> None:
    """2장(게이트) 안에 있어야 한다. 다른 장으로 밀리면 읽히지 않는다."""
    _code, _out, md = run(tmp_path, wide_src, narrow_dst)
    gate_start = md.index("## 2. 게이트")
    next_section = md.index("## 3. ")
    assert gate_start < md.index(run_fov_compare.GATE_NOTE) < next_section


def test_gate_fails_when_dst_is_wider(tmp_path, capsys) -> None:
    """LUAZ 가 S10 보다 넓으면 설계 ② 는 불가능하다. 굵게 경고해야 한다."""
    src = make_intrinsics("s10", 1700.0, 1695.0, -0.05)   # 좁게 본다
    dst = make_intrinsics("luaz", 1200.0, 1196.0, -0.20)  # 넓게 본다

    code, _out, md = run(tmp_path, src, dst)
    assert code == 0  # 리포트는 만든다
    assert "**불통과**" in md
    assert "설계 ② 는 불가능하다" in md
    assert "f_target" in md
    assert "게이트 불통과" in capsys.readouterr().err


# --- 입력 검증 --------------------------------------------------------------


def test_resolution_mismatch_stops(tmp_path, wide_src, narrow_dst) -> None:
    narrow_dst["resolution"] = [1280, 720]
    src_path, dst_path = write_pair(tmp_path, wide_src, narrow_dst)
    with pytest.raises(SystemExit) as exc:
        run_fov_compare.main([str(src_path), str(dst_path), "--out-dir", str(tmp_path / "r")])
    assert "해상도가 다르다" in str(exc.value)


def test_missing_fields_stop(tmp_path, wide_src, narrow_dst) -> None:
    del narrow_dst["fov_effective"]
    src_path, dst_path = write_pair(tmp_path, wide_src, narrow_dst)
    with pytest.raises(SystemExit) as exc:
        run_fov_compare.main([str(src_path), str(dst_path), "--out-dir", str(tmp_path / "r")])
    assert "fov_effective" in str(exc.value)


def test_degenerate_k_prime_is_warned(tmp_path, wide_src) -> None:
    """K' 가 퇴화면 설계 ③ 의 K_target 자체가 못 믿을 값이다. 리포트에 알려야 한다."""
    dst = make_intrinsics("luaz", 1527.0, 1520.0, -0.40)  # 강한 배럴 -> 퇴화
    assert dst["fov_degenerate"] is True

    _code, _out, md = run(tmp_path, wide_src, dst)
    assert "getOptimalNewCameraMatrix" in md
    assert "신뢰할 수 없" in md


# --- 그림 ------------------------------------------------------------------


def test_heatmap_has_no_missing_glyphs(tmp_path, wide_src, narrow_dst) -> None:
    """matplotlib 기본 폰트에는 한글 글리프가 없다.

    한글을 넣으면 경고만 내고 PNG 는 그대로 만들어진다 - 글자가 네모(두부)로
    찍힌 그림이 조용히 나온다. 그림 안의 글자는 ASCII 만 쓴다.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run(tmp_path, wide_src, narrow_dst)

    missing = [str(w.message) for w in caught if "missing from font" in str(w.message)]
    assert not missing, f"그림에 렌더되지 않는 글자가 있다: {missing[:3]}"


def test_ascii_labels_are_ascii(tmp_path, wide_src, narrow_dst) -> None:
    ctx = run_fov_compare.compare(wide_src, narrow_dst, tmp_path)
    for key in ("design3", "design2"):
        for result in ctx[key]:
            if result.get("_skipped"):
                continue
            assert result["ascii_label"].isascii()


# --- 수치의 자기검증 --------------------------------------------------------


def test_design2_stretch_equals_focal_ratio_squared(tmp_path) -> None:
    """설계 ②(왜곡 없는 두 카메라)의 stretch 는 초점거리 비의 제곱이어야 한다.

    S10 을 LUAZ 규격으로 옮기면 면적 배율이 (fx_luaz / fx_s10)^2 이다.
    이 값이 맞으면 야코비안 계산이 맞다는 뜻이다.
    """
    src = make_intrinsics("s10", 1000.0, 1000.0, 0.0)
    dst = make_intrinsics("luaz", 1200.0, 1200.0, 0.0)

    ctx = run_fov_compare.compare(src, dst, tmp_path)
    design2 = ctx["design2"][0]
    expected = (1200.0 / 1000.0) ** 2
    assert design2["stretch"]["median"] == pytest.approx(expected, rel=0.01)
