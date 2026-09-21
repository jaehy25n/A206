"""세션 여러 개를 하나처럼 보는 뷰.

한 카메라를 두 번에 나눠 찍는 일이 실제로 생긴다 (배터리, 자리 옮김, 중간 확인).
그 둘을 합쳐 한 번에 캘리브레이션하려면 프레임을 통째로 모아야 하는데, 세션마다
프레임 index 가 0 부터 다시 시작하므로 그대로 섞으면 어느 사진인지 알 수 없게 된다.

여기서 만드는 `CombinedSession` 은 **전역 index 를 새로 매기고** `Session` 과 같은
모양(`board`, `resolution_actual`, `frames`, `frame_path`)을 제공한다. 그래서
`calibrate.py` 의 함수들은 고칠 것 없이 그대로 쓴다.

합치기 전에 반드시 확인하는 것 (다르면 합칠 수 없다):
    - 카메라 이름     다른 카메라의 사진을 섞으면 K 가 무의미하다
    - 실제 해상도     다르면 픽셀 좌표의 의미가 다르다
    - 보드 규격       square_mm 이 다르면 거리 t 의 단위가 섞인다

그리고 **meta.json 에 없는 PNG** 가 frames/ 에 있으면 경고한다. 그런 파일은 출처를
알 수 없고 (다른 세션에서 복사됐을 수 있다), 조용히 섞이면 추적이 불가능해진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .board import BoardSpec
from .session import FrameRecord, Session


class SessionMismatch(ValueError):
    """합칠 수 없는 세션들. 조용히 섞지 않는다."""


@dataclass
class CombinedSession:
    """`Session` 처럼 동작하는, 여러 세션의 합집합.

    Attributes:
        sessions: 합친 원본 세션들 (입력 순서 그대로).
        frames: 전역 index 로 다시 매긴 프레임 기록. filename 은
            `<session_id>/<원래 파일명>` 이라 리포트에서 어느 세션인지 보인다.
        orphan_pngs: meta.json 에 없는데 frames/ 에 있던 PNG. {session_id: [파일명]}
    """

    sessions: list[Session]
    camera: str
    board: BoardSpec
    resolution_actual: tuple[int, int]
    frames: list[FrameRecord]
    orphan_pngs: dict[str, list[str]] = field(default_factory=dict)
    #: 전역 index -> 실제 파일 경로
    _paths: dict[int, Path] = field(default_factory=dict, repr=False)
    #: 전역 index -> (session_id, 원래 index)
    _origin: dict[int, tuple[str, int]] = field(default_factory=dict, repr=False)

    # --- Session 흉내 -----------------------------------------------------

    @property
    def session_id(self) -> str:
        """리포트 파일 이름이 된다. 한 개면 그대로, 여러 개면 묶음 이름."""
        if len(self.sessions) == 1:
            return self.sessions[0].session_id
        return f"{self.sessions[0].session_id}+{len(self.sessions) - 1}"

    @property
    def path(self) -> Path:
        """대표 경로. 여러 개일 때는 첫 세션 (재현 명령은 리포트에 전부 적는다)."""
        return self.sessions[0].path

    @property
    def session_paths(self) -> list[str]:
        return [str(s.path) for s in self.sessions]

    @property
    def resolution_requested(self) -> tuple[int, int]:
        return self.sessions[0].resolution_requested

    @property
    def capture_settings(self) -> dict[str, Any]:
        """세션별 캡처 설정을 session_id 로 묶어 그대로 남긴다."""
        return {s.session_id: s.capture_settings for s in self.sessions}

    @property
    def n_detected(self) -> int:
        return sum(1 for f in self.frames if f.detected)

    def frame_path(self, record: FrameRecord) -> Path:
        return self._paths[record.index]

    def origin_of(self, index: int) -> tuple[str, int]:
        """전역 index -> (session_id, 세션 안에서의 원래 index)."""
        return self._origin[index]

    def label_of(self, index: int) -> str:
        """리포트에 쓰는 사람용 이름. 세션이 하나면 짧게."""
        session_id, local = self._origin[index]
        if len(self.sessions) == 1:
            return f"{local:03d}"
        return f"{session_id}/{local:03d}"

    # --- 만들기 -----------------------------------------------------------

    @classmethod
    def open(cls, paths: list[str | Path]) -> "CombinedSession":
        """세션 디렉토리 여러 개를 읽어 합친다.

        Raises:
            SessionMismatch: 카메라 / 해상도 / 보드 규격이 서로 다를 때.
            ValueError: 같은 세션을 두 번 넣었을 때.
        """
        if not paths:
            raise ValueError("세션 경로가 하나도 없다")

        sessions = [Session.open(p) for p in paths]
        _check_compatible(sessions)

        seen: set[str] = set()
        for s in sessions:
            if s.session_id in seen:
                raise ValueError(f"같은 세션을 두 번 넣었다: {s.session_id}")
            seen.add(s.session_id)

        frames: list[FrameRecord] = []
        paths_by_index: dict[int, Path] = {}
        origin: dict[int, tuple[str, int]] = {}
        orphans: dict[str, list[str]] = {}

        for session in sessions:
            extra = _orphan_pngs(session)
            if extra:
                orphans[session.session_id] = extra
            for record in session.frames:
                index = len(frames)
                frames.append(
                    FrameRecord(
                        index=index,
                        filename=f"{session.session_id}/{record.filename}",
                        detected=record.detected,
                        n_corners=record.n_corners,
                        timestamp=record.timestamp,
                    )
                )
                paths_by_index[index] = session.frame_path(record)
                origin[index] = (session.session_id, record.index)

        first = sessions[0]
        return cls(
            sessions=sessions,
            camera=first.camera,
            board=first.board,
            resolution_actual=first.resolution_actual,
            frames=frames,
            orphan_pngs=orphans,
            _paths=paths_by_index,
            _origin=origin,
        )


# --- 검사 -------------------------------------------------------------------


def _check_compatible(sessions: list[Session]) -> None:
    """합쳐도 되는 세션들인지. 하나라도 어긋나면 멈춘다."""
    first = sessions[0]
    for other in sessions[1:]:
        if other.camera != first.camera:
            raise SessionMismatch(
                f"카메라가 다르다: {first.session_id}={first.camera} vs "
                f"{other.session_id}={other.camera}. 다른 카메라의 사진을 섞으면 "
                "K 가 무의미해진다"
            )
        if other.resolution_actual != first.resolution_actual:
            raise SessionMismatch(
                f"해상도가 다르다: {first.session_id}={first.resolution_actual} vs "
                f"{other.session_id}={other.resolution_actual}. 픽셀 좌표의 의미가 다르다"
            )
        if other.board != first.board:
            raise SessionMismatch(
                f"보드 규격이 다르다: {first.session_id}={first.board.cols}x"
                f"{first.board.rows}@{first.board.square_mm}mm vs "
                f"{other.session_id}={other.board.cols}x{other.board.rows}@"
                f"{other.board.square_mm}mm. 보드를 바꿨으면 세션을 섞을 수 없다"
            )


def _orphan_pngs(session: Session) -> list[str]:
    """frames/ 에 있지만 meta.json 이 모르는 PNG.

    출처를 알 수 없는 파일이다 (다른 세션에서 복사됐거나, 저장 도중 meta 기록이
    실패했거나). 캘리브레이션에 **쓰지 않는다** - meta 에 적힌 것만 쓴다 -
    하지만 있다는 사실은 알려야 한다. 조용히 두면 나중에 누가 폴더를 glob 해서
    섞어 버린다.
    """
    if not session.frames_dir.is_dir():
        return []
    recorded = {f.filename for f in session.frames}
    on_disk = sorted(p.name for p in session.frames_dir.glob("*.png"))
    return [name for name in on_disk if name not in recorded]
