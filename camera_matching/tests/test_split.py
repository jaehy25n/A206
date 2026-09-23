"""split - 학습/홀드아웃 분할이 결정적이고 겹치지 않는지.

분할이 실행마다 달라지면 "어제 RMS 0.28 이었는데 오늘 0.41"의 원인을 추적할 수
없다. 그래서 시드를 받고, 그 시드를 결과 JSON 에 기록한다.
"""

from __future__ import annotations

import numpy as np
import pytest

from camcal.board import BoardSpec
from camcal.calibrate import detected_ids, split
from camcal.session import Session

IMAGE_SIZE = (1920, 1080)


def make_session(tmp_path, spec: BoardSpec, n_detected: int, n_failed: int = 0) -> Session:
    """검출 성공 n_detected 장 + 실패 n_failed 장짜리 세션."""
    session = Session.create(
        data_root=tmp_path,
        camera="split",
        board=spec,
        resolution_requested=IMAGE_SIZE,
        resolution_actual=IMAGE_SIZE,
    )
    flat = np.full((IMAGE_SIZE[1], IMAGE_SIZE[0], 3), 200, dtype=np.uint8)
    for i in range(n_detected + n_failed):
        ok = i < n_detected
        session.add_frame(flat, detected=ok, n_corners=spec.n_corners if ok else 0)
    return session


def test_same_seed_same_split(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, 25)
    first = split(session, n_train=20, seed=0)
    second = split(session, n_train=20, seed=0)
    assert first == second


def test_different_seed_different_split(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, 25)
    a_train, _ = split(session, n_train=20, seed=0)
    b_train, _ = split(session, n_train=20, seed=7)
    assert a_train != b_train, "시드를 바꿨는데 분할이 같다"


def test_no_overlap_and_full_cover(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, 27)
    train, holdout = split(session, n_train=20, seed=3)

    assert set(train) & set(holdout) == set(), "학습과 홀드아웃이 겹친다"
    assert sorted(train + holdout) == detected_ids(session)
    assert len(train) == 20
    assert len(holdout) == 7


def test_ids_are_sorted(tmp_path, spec: BoardSpec) -> None:
    """리포트와 JSON 에 그대로 실리므로 읽기 좋게 정렬해 둔다."""
    session = make_session(tmp_path, spec, 25)
    train, holdout = split(session, n_train=20, seed=1)
    assert train == sorted(train)
    assert holdout == sorted(holdout)


def test_only_detected_frames_are_used(tmp_path, spec: BoardSpec) -> None:
    """검출 실패 프레임은 분할에 들어가면 안 된다 (코너가 없으니 추정에 못 쓴다)."""
    session = make_session(tmp_path, spec, 22, n_failed=5)
    train, holdout = split(session, n_train=18, seed=0)

    assert len(train) + len(holdout) == 22
    assert max(train + holdout) < 22  # 실패 프레임은 index 22~26


def test_holdout_must_not_be_empty(tmp_path, spec: BoardSpec) -> None:
    """홀드아웃이 0장이면 RMS 는 '학습을 얼마나 잘 맞췄나'일 뿐이다. 멈춘다."""
    session = make_session(tmp_path, spec, 20)
    with pytest.raises(ValueError) as exc:
        split(session, n_train=20, seed=0)
    assert "n-train" in str(exc.value)


def test_more_train_than_frames(tmp_path, spec: BoardSpec) -> None:
    session = make_session(tmp_path, spec, 10)
    with pytest.raises(ValueError):
        split(session, n_train=20, seed=0)


@pytest.mark.parametrize("n_train", [0, -1])
def test_invalid_n_train(tmp_path, spec: BoardSpec, n_train: int) -> None:
    session = make_session(tmp_path, spec, 25)
    with pytest.raises(ValueError):
        split(session, n_train=n_train, seed=0)


def test_split_is_a_permutation_not_a_prefix(tmp_path, spec: BoardSpec) -> None:
    """앞에서 20장을 자르면 촬영 순서(= 조건 변화)가 분할에 그대로 들어간다.

    홀드아웃이 마지막에 찍은 사진들뿐이면 "나중에 조명이 바뀐 것"과
    "K 가 일반화되지 않는 것"을 구분할 수 없다.
    """
    session = make_session(tmp_path, spec, 30)
    _train, holdout = split(session, n_train=20, seed=0)
    assert holdout != list(range(20, 30)), "분할이 단순 앞뒤 자르기다"
