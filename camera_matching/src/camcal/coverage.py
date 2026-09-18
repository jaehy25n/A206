"""화면 커버리지 - 보드가 화면의 어느 칸까지 왔는가.

왜 필요한가: 왜곡 계수 k1, k2 는 **화면 가장자리** 데이터가 있어야 풀린다.
가운데에서만 30장을 찍으면 RMS 는 낮게 나오지만 D 는 신뢰할 수 없다.
그래서 촬영 중에 "아직 안 채운 칸"을 실시간으로 보여준다.

셀 인덱스는 (col, row), 원점은 좌상단. 픽셀 좌표 (u, v) 기준이다.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from .constants import COVERAGE_GRID

#: 3x3 격자 셀 이름. **ASCII 만 쓴다** - 이 문자열이 cv2.putText 로 미리보기
#: 창에 그려지는데, OpenCV 의 Hershey 폰트는 한글을 렌더하지 못하고 "???" 가 된다.
#: 한글 이름은 콘솔 출력용으로 CELL_LABELS_KO 에 따로 둔다.
_CELL_LABELS_3X3 = {
    (0, 0): "TL", (1, 0): "T", (2, 0): "TR",
    (0, 1): "L", (1, 1): "C", (2, 1): "R",
    (0, 2): "BL", (1, 2): "B", (2, 2): "BR",
}

#: 콘솔/문서용 한글 이름. 미리보기 창에는 쓰지 않는다.
CELL_LABELS_KO = {
    (0, 0): "좌상", (1, 0): "상", (2, 0): "우상",
    (0, 1): "좌", (1, 1): "중앙", (2, 1): "우",
    (0, 2): "좌하", (1, 2): "하", (2, 2): "우하",
}


class Coverage:
    """세션 내내 누적되는 화면 커버리지.

    Args:
        image_size: (width, height) 픽셀.
        grid: (cols, rows) 셀 개수. 기본 3x3.
    """

    def __init__(
        self,
        image_size: tuple[int, int],
        grid: tuple[int, int] = COVERAGE_GRID,
    ) -> None:
        width, height = image_size
        if width <= 0 or height <= 0:
            raise ValueError(f"image_size 는 양수여야 한다: {image_size}")
        if grid[0] <= 0 or grid[1] <= 0:
            raise ValueError(f"grid 는 양수여야 한다: {grid}")
        self.image_size = (int(width), int(height))
        self.grid = (int(grid[0]), int(grid[1]))
        #: counts[row][col] = 그 셀에 코너가 들어간 **프레임 수** (코너 수가 아니다)
        self.counts = np.zeros((self.grid[1], self.grid[0]), dtype=np.int32)
        self.n_frames = 0

    # --- 셀 매핑 ----------------------------------------------------------

    def cell_of(self, u: float, v: float) -> tuple[int, int]:
        """픽셀 (u, v) 가 속한 셀 (col, row).

        경계 규칙: 셀은 [시작, 끝) 반열림 구간이다. 즉 u = W/3 은 가운데 셀.
        u = W (이미지 밖 한 칸) 는 마지막 셀로 clamp 한다 - cornerSubPix 가
        이미지 경계를 아주 살짝 넘는 값을 내는 경우가 있어서, 거기서 예외를
        내면 정상 프레임이 버려진다.
        """
        width, height = self.image_size
        cols, rows = self.grid
        col = int(np.floor(u * cols / width))
        row = int(np.floor(v * rows / height))
        col = min(max(col, 0), cols - 1)
        row = min(max(row, 0), rows - 1)
        return (col, row)

    def cells_of_frame(self, corners: np.ndarray) -> set[tuple[int, int]]:
        """한 프레임의 코너들이 덮는 셀 집합. 누적하지 않는다."""
        pts = np.asarray(corners, dtype=np.float64).reshape(-1, 2)
        return {self.cell_of(float(u), float(v)) for u, v in pts}

    # --- 누적 -------------------------------------------------------------

    def add(self, corners: np.ndarray) -> set[tuple[int, int]]:
        """검출된 코너 한 세트를 누적한다.

        한 프레임이 같은 셀을 여러 코너로 덮어도 그 셀의 카운트는 1만 오른다.
        (한 장을 오래 들고 있다고 커버리지가 좋아지면 안 된다)

        Returns:
            이 프레임이 덮은 셀 집합.
        """
        cells = self.cells_of_frame(corners)
        for col, row in cells:
            self.counts[row, col] += 1
        self.n_frames += 1
        return cells

    # --- 조회 -------------------------------------------------------------

    @property
    def n_cells(self) -> int:
        return self.grid[0] * self.grid[1]

    def filled_cells(self) -> list[tuple[int, int]]:
        """한 번이라도 코너가 들어간 셀. (col, row) 정렬 목록."""
        return [c for c in self._all_cells() if self.counts[c[1], c[0]] > 0]

    def empty_cells(self) -> list[tuple[int, int]]:
        """아직 비어 있는 셀. 촬영 중 이 목록이 화면에 뜬다."""
        return [c for c in self._all_cells() if self.counts[c[1], c[0]] == 0]

    def ratio(self) -> float:
        """채워진 셀 비율 0.0 ~ 1.0."""
        return len(self.filled_cells()) / self.n_cells

    def _all_cells(self) -> Iterable[tuple[int, int]]:
        cols, rows = self.grid
        for row in range(rows):
            for col in range(cols):
                yield (col, row)

    def label(self, cell: tuple[int, int], korean: bool = False) -> str:
        """셀 이름. 3x3 이면 방향 약어(TL/T/TR...), 아니면 좌표.

        korean=True 는 콘솔 출력 전용이다. 미리보기 창(cv2.putText)에는
        쓰지 않는다 - OpenCV 폰트가 한글을 렌더하지 못한다.
        """
        if self.grid == (3, 3):
            return (CELL_LABELS_KO if korean else _CELL_LABELS_3X3)[cell]
        return f"({cell[0]},{cell[1]})"

    def empty_labels(self, korean: bool = False) -> list[str]:
        return [self.label(c, korean=korean) for c in self.empty_cells()]

    def to_dict(self) -> dict:
        """meta.json 에 넣을 형태."""
        return {
            "grid": list(self.grid),
            "image_size": list(self.image_size),
            "n_frames": int(self.n_frames),
            "counts": self.counts.tolist(),  # [row][col]
            "ratio": self.ratio(),
            "empty_cells": [list(c) for c in self.empty_cells()],
        }
