"""체커보드 규격과 월드 좌표 X_w.

보드는 Z=0 평면 위에 있다고 둔다. 이것이 Zhang 방법의 전제이고,
그래서 object point 의 세 번째 성분은 항상 0 이다.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml


@dataclass(frozen=True)
class BoardSpec:
    """체커보드 한 장의 규격.

    Attributes:
        cols: 가로 방향 **내부 코너** 개수 (칸 수가 아니다).
        rows: 세로 방향 내부 코너 개수.
        square_mm: 한 칸의 실측 변 길이 (mm).
        square_mm_measured: 자로 실제 재서 넣은 값이면 True.
            False 인 채로 촬영하면 도구가 경고한다 - 이 값이 틀리면
            fx, fy 는 맞지만 t (거리) 전체가 같은 비율로 틀린다.
        note: 보드 설명. meta.json 에 그대로 남는다.
    """

    cols: int
    rows: int
    square_mm: float
    square_mm_measured: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if self.cols < 2 or self.rows < 2:
            raise ValueError(
                f"내부 코너 수는 각 방향 2 이상이어야 한다: cols={self.cols}, rows={self.rows}"
            )
        if self.cols == self.rows:
            # 정사각 배치는 보드의 회전 방향이 180도 모호해져서
            # 사진마다 코너 순서가 뒤집힐 수 있다. Zhang 방법에서 바로 오차로 나타난다.
            raise ValueError(
                f"cols 와 rows 가 같으면 보드 방향이 모호해진다 (cols=rows={self.cols}). "
                "비대칭 보드를 쓴다 (예: 9x6)"
            )
        if not self.square_mm > 0:
            raise ValueError(f"square_mm 은 양수여야 한다: {self.square_mm}")

    @property
    def pattern_size(self) -> tuple[int, int]:
        """OpenCV findChessboardCorners 가 받는 (cols, rows) 튜플."""
        return (self.cols, self.rows)

    @property
    def n_corners(self) -> int:
        """한 장에서 나와야 하는 내부 코너 총 개수."""
        return self.cols * self.rows

    def object_points(self) -> np.ndarray:
        """보드 좌표계에서의 코너 위치 X_w. shape (N, 3) float32, Z=0.

        순서는 OpenCV findChessboardCorners 의 출력 순서와 같다:
        행 우선 (row-major), 각 행 안에서는 x 증가 방향.

        단위는 mm. square_mm 이 실측값이면 t 도 mm 로 나온다.
        """
        grid = np.zeros((self.n_corners, 3), dtype=np.float32)
        # mgrid 가 아니라 명시적으로 쓴다. 축 순서 혼동이 여기서 제일 자주 난다.
        xs, ys = np.meshgrid(np.arange(self.cols), np.arange(self.rows))
        grid[:, 0] = xs.ravel() * self.square_mm  # X_w
        grid[:, 1] = ys.ravel() * self.square_mm  # Y_w
        # grid[:, 2] 는 0 으로 둔다 (Z_w = 0 평면)
        return grid

    def to_dict(self) -> dict[str, Any]:
        """meta.json 에 넣을 형태."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoardSpec":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BoardSpec":
        """config/board.yaml 을 읽는다. 최상위 키는 `board`."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp)
        if not isinstance(data, dict) or "board" not in data:
            raise ValueError(f"{path}: 최상위에 'board' 키가 없다")
        return cls.from_dict(data["board"])
