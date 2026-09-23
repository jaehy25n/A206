"""camcal - S10 ↔ LUAZ 카메라 매칭 공통 패키지.

좌표 이름 규약 (프로젝트 전역, CLAUDE.md 3절):
    X_w      월드 좌표 (보드 평면, mm, Z_w = 0)
    X_c      카메라 좌표 (mm)
    x_n, y_n 정규 좌표 (단위 없음)
    u, v     픽셀 좌표

촬영(session, detect, coverage)과 캘리브레이션(calibrate, report, fov)이 한 패키지에
있다. calibrate / report 는 무겁고(matplotlib) 촬영 경로에서는 필요 없으므로
여기서 재수출하지 않는다 - `from camcal.calibrate import ...` 로 직접 쓴다.
"""

from .board import BoardSpec
from .coverage import Coverage
from .detect import corner_span_px, draw_corners, find_corners, to_gray
from .fov import fov_effective, fov_nominal
from .session import FrameRecord, Session, make_session_id

__all__ = [
    "BoardSpec",
    "Coverage",
    "Session",
    "FrameRecord",
    "make_session_id",
    "find_corners",
    "draw_corners",
    "corner_span_px",
    "to_gray",
    "fov_nominal",
    "fov_effective",
]
