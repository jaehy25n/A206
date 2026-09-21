"""공통 target 공간의 정의와 저장.

4단계에서 사람이 ②/③ 중 하나를 고르고 `f_target` 배율을 정한다. 그 결정은 이후
**모든 변환이 같은 공간을 쓰도록** 한 곳에 적어 두어야 한다. 두 사람이 각자
`K_target` 을 계산하면 미세하게 다른 공간이 생기고, 그 차이는 영상만 봐서는
보이지 않는다.

    results/target_space.json    이 결정의 유일한 정본

이 파일은 **코드가 알아서 만들지 않는다.** `run_remap.py --design {2|3}` 로 사람이
한 번 명시해야 생긴다 (README "미정 결정 - 코드가 임의로 정하지 않는다").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .remap_metrics import scale_focal

#: 산출물 파일 이름.
TARGET_SPACE_FILENAME = "target_space.json"

#: README 의 설계 번호. 2 = LUAZ 원본, 3 = 가상 카메라.
DESIGN_DISTORTED = 2
DESIGN_PINHOLE = 3
DESIGNS = (DESIGN_DISTORTED, DESIGN_PINHOLE)

DESIGN_NAMES = {
    DESIGN_DISTORTED: "② LUAZ 원본 = target",
    DESIGN_PINHOLE: "③ 가상 카메라 = target",
}


@dataclass
class TargetSpace:
    """두 카메라가 공유하는 목적지 공간.

    Attributes:
        design: 2 또는 3 (README 번호).
        K_target: 3x3. 설계 ③ 이면 기준 카메라 K' x 배율, ② 면 기준 카메라 K.
        D_target: 설계 ③ 이면 전부 0, ② 면 기준 카메라의 D.
            **이 값이 0 이냐 아니냐가 ②/③ 를 가른다** (K_target 이 아니다).
        reference_camera: 기준이 된 카메라 이름 (보통 luaz).
        f_target_scale: 설계 ③ 에서 K' 에 곱한 배율. ② 에서는 1.0 고정.
        resolution: (width, height). 목적지 이미지 크기.
    """

    design: int
    K_target: list[list[float]]
    D_target: list[float]
    reference_camera: str
    reference_session: str
    f_target_scale: float
    resolution: list[int]
    created_at: str
    note: str = ""

    # --- 만들기 -----------------------------------------------------------

    @classmethod
    def from_intrinsics(
        cls,
        reference: dict[str, Any],
        design: int,
        f_target_scale: float = 1.0,
        note: str = "",
    ) -> "TargetSpace":
        """기준 카메라의 intrinsics 에서 target 공간을 만든다.

        Args:
            reference: 기준 카메라(보통 LUAZ)의 intrinsics dict.
            design: 2 또는 3. **기본값을 두지 않는다** - 코드가 대신 고르면 안 된다.
            f_target_scale: 설계 ③ 전용. 올리면 화각이 좁아져 검은 영역이 준다.
        """
        if design not in DESIGNS:
            raise ValueError(f"design 은 2 또는 3 이다: {design}")

        width, height = int(reference["resolution"][0]), int(reference["resolution"][1])
        if design == DESIGN_PINHOLE:
            K_base = np.asarray(reference["fov_effective"]["K_prime"], dtype=np.float64)
            K_target = scale_focal(K_base, f_target_scale)
            D_target = np.zeros(5, dtype=np.float64)
        else:
            if f_target_scale != 1.0:
                raise ValueError(
                    "설계 ② 는 기준 카메라 원본을 그대로 target 으로 쓴다. "
                    f"f_target_scale 을 바꿀 수 없다 (받은 값 {f_target_scale})"
                )
            K_target = np.asarray(reference["K"], dtype=np.float64)
            D_target = np.asarray(reference["D"], dtype=np.float64).ravel()

        return cls(
            design=design,
            K_target=K_target.tolist(),
            D_target=D_target.tolist(),
            reference_camera=str(reference["camera"]),
            reference_session=str(reference.get("session_id", "")),
            f_target_scale=float(f_target_scale),
            resolution=[width, height],
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            note=note,
        )

    # --- 읽기 / 쓰기 ------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "TargetSpace":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"target 공간이 정해지지 않았다: {path}\n"
                "  run_remap.py --design 3 --f-target-scale 1.10 ... 처럼 "
                "설계를 한 번 명시하면 만들어진다"
            )
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            json.dump(asdict(self), fp, ensure_ascii=False, indent=2)
        return path

    # --- 조회 -------------------------------------------------------------

    @property
    def K(self) -> np.ndarray:
        return np.asarray(self.K_target, dtype=np.float64)

    @property
    def D(self) -> np.ndarray:
        return np.asarray(self.D_target, dtype=np.float64)

    @property
    def size(self) -> tuple[int, int]:
        return (int(self.resolution[0]), int(self.resolution[1]))

    @property
    def name(self) -> str:
        return DESIGN_NAMES[self.design]

    @property
    def is_pinhole(self) -> bool:
        """D_target 이 전부 0 인가. **이것이 ③ 의 정의다.**"""
        return not bool(np.any(np.abs(self.D) > 0))

    def describe(self) -> str:
        K = self.K
        return (
            f"{self.name} · 기준 {self.reference_camera}"
            f"({self.reference_session}) · fx {K[0, 0]:.1f} cx {K[0, 2]:.1f} "
            f"· 배율 {self.f_target_scale:.2f} · D_target "
            + ("0" if self.is_pinhole else "기준 카메라 D")
        )
