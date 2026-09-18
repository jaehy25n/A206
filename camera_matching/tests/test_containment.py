"""containment - FOV 포함 관계의 경계값.

이 판정 하나가 설계 ② 의 가능/불가능을 가른다 (README 판정 절차 1번의 게이트).
LUAZ 가 S10 보다 넓으면 S10 에 없는 픽셀을 요구하게 되어 불가능하다.
경계에서 어느 쪽으로 떨어지는지를 여기서 못 박는다.
"""

from __future__ import annotations

import pytest

from camcal.remap_metrics import containment


# --- 경계 ------------------------------------------------------------------


def test_exactly_equal_is_contained() -> None:
    """딱 같은 화각은 '들어온다'로 본다 (여유 0).

    실제로는 여유 0 이면 가장자리 한 줄이 위태롭다. 그래서 판정은 True 로 주되
    margin 값 0.0 을 그대로 보여주고, 해석은 리포트를 읽는 사람이 한다.
    """
    out = containment((64.0, 38.0), (64.0, 38.0))
    assert out["contained"] is True
    assert out["h_margin"] == 0.0
    assert out["v_margin"] == 0.0


def test_just_wider_is_not_contained() -> None:
    out = containment((64.001, 38.0), (64.0, 38.0))
    assert out["contained"] is False
    assert out["h_ok"] is False
    assert out["h_margin"] < 0


def test_just_narrower_is_contained() -> None:
    out = containment((63.999, 37.999), (64.0, 38.0))
    assert out["contained"] is True


# --- 축이 따로 논다 ---------------------------------------------------------


@pytest.mark.parametrize(
    "fov_a, fov_b, contained, h_ok, v_ok",
    [
        ((60.0, 40.0), (65.0, 38.0), False, True, False),   # 세로만 넘침
        ((70.0, 35.0), (65.0, 38.0), False, False, True),   # 가로만 넘침
        ((70.0, 40.0), (65.0, 38.0), False, False, False),  # 둘 다 넘침
        ((60.0, 35.0), (65.0, 38.0), True, True, True),     # 둘 다 여유
    ],
)
def test_each_axis_is_judged_separately(
    fov_a, fov_b, contained: bool, h_ok: bool, v_ok: bool
) -> None:
    """가로는 들어오는데 세로가 넘치는 경우가 실제로 있다 (종횡비가 미묘히 달라서).

    한 축만 봐서 통과시키면 그 축은 검은 띠가 생긴다.
    """
    out = containment(fov_a, fov_b)
    assert out["contained"] is contained
    assert out["h_ok"] is h_ok
    assert out["v_ok"] is v_ok


def test_contained_requires_both_axes() -> None:
    out = containment((60.0, 40.0), (65.0, 38.0))
    assert out["h_ok"] is True and out["v_ok"] is False
    assert out["contained"] is False, "한 축만 통과했는데 전체 통과로 봤다"


# --- 여유 값 ---------------------------------------------------------------


def test_margin_sign_convention() -> None:
    """margin = b - a. **양수면 여유**, 음수면 그만큼 모자란다."""
    roomy = containment((60.0, 35.0), (65.0, 38.0))
    assert roomy["h_margin"] == pytest.approx(5.0)
    assert roomy["v_margin"] == pytest.approx(3.0)

    short = containment((65.0, 38.0), (60.0, 35.0))
    assert short["h_margin"] == pytest.approx(-5.0)
    assert short["v_margin"] == pytest.approx(-3.0)


def test_not_symmetric() -> None:
    """a ⊆ b 와 b ⊆ a 는 다르다. 인자 순서를 바꾸면 결과가 뒤집힌다."""
    forward = containment((60.0, 35.0), (65.0, 38.0))
    backward = containment((65.0, 38.0), (60.0, 35.0))
    assert forward["contained"] is True
    assert backward["contained"] is False


def test_accepts_lists_and_ints() -> None:
    """JSON 에서 읽어온 값(list, int)을 그대로 넣어도 동작해야 한다."""
    out = containment([60, 35], (65.0, 38.0))
    assert out["contained"] is True
    assert isinstance(out["h_margin"], float)
