"""실시간 프레임 변환 - 카메라 영상이 들어오면 공통 target 공간으로 바꿔 돌려준다.

이 파일이 5단계의 **제품**이다. 다른 코드는 이것만 쓰면 된다.

    from camcal.stream import FrameRemapper

    remapper = FrameRemapper.from_files("results/s10_intrinsics.json")
    while True:
        ok, frame = cap.read()
        out = remapper.apply(frame)      # 이게 전부다

맵은 **한 번만** 만든다. 프레임마다 다시 만들면 1080p 에서 수십 ms 씩 든다.
그래서 해상도가 바뀌면 맵을 다시 만들어야 하는데, 그건 카메라가 바뀐 것이므로
조용히 다시 만들지 않고 알린다.

해상도가 캘리브레이션과 다를 때
    종횡비가 같으면      K 를 배율만큼 줄여 쓴다. 단순 리사이즈는 화각을 바꾸지
                        않으므로 이것은 **정확한** 처리다
    종횡비가 다르면      **거부한다.** 크롭이 들어갔다는 뜻이고, 크롭은 화각을
                        바꾸므로 K 를 어떻게 고쳐야 하는지 알 수 없다
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .remap_metrics import (
    build_map_to_distorted,
    build_map_to_pinhole,
    crop_box,
    valid_mask,
    valid_ratio,
)
from .target_space import DESIGN_PINHOLE, TARGET_SPACE_FILENAME, TargetSpace

#: 종횡비가 이만큼 안에서 같으면 단순 리사이즈로 본다.
ASPECT_TOLERANCE = 0.01

#: 원본에 없는 자리를 채우는 색. 검은색으로 두면 "여기는 데이터가 없다" 가 보인다.
BORDER_VALUE = (0, 0, 0)

#: 실시간 경로의 보간. INTER_LINEAR 가 기본이자 가장 빠르고 안전하다.
INTERPOLATION = cv2.INTER_LINEAR


class ResolutionMismatch(ValueError):
    """들어온 프레임 크기를 이 intrinsics 로 처리할 수 없다."""


def scale_intrinsics(K: np.ndarray, scale: float) -> np.ndarray:
    """이미지를 scale 배로 리사이즈했을 때의 K (fx, fy, cx, cy 가 같이 줄어든다)."""
    out = np.array(K, dtype=np.float64, copy=True)
    out[0, 0] *= scale
    out[1, 1] *= scale
    out[0, 2] *= scale
    out[1, 2] *= scale
    return out


@dataclass
class FrameRemapper:
    """한 카메라의 프레임을 공통 target 공간으로 옮긴다.

    Attributes:
        camera: 카메라 이름 (로그용).
        input_size: 받아들이는 프레임 크기 (width, height).
        output_size: 내보내는 프레임 크기.
        valid_ratio: 출력에서 원본 데이터가 있는 픽셀 비율. 1.0 미만이면
            그만큼 검은 영역이다.
        crop_box: --crop 을 쓴 경우 (x, y, w, h). 아니면 None.
    """

    camera: str
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    valid_ratio: float
    design: int
    _map1: np.ndarray
    _map2: np.ndarray
    _crop: tuple[int, int, int, int] | None = None

    # --- 만들기 -----------------------------------------------------------

    @classmethod
    def from_files(
        cls,
        intrinsics_path: str | Path,
        target_path: str | Path | None = None,
        input_size: tuple[int, int] | None = None,
        crop: bool = False,
    ) -> "FrameRemapper":
        """intrinsics.json + target_space.json 으로 만든다.

        Args:
            target_path: 없으면 intrinsics 와 같은 폴더의 target_space.json.
            input_size: 실제로 들어올 프레임 크기. 생략하면 캘리브레이션 해상도.
            crop: 검은 영역을 잘라내고 유효 영역만 내보낸다.
        """
        intrinsics_path = Path(intrinsics_path)
        with intrinsics_path.open("r", encoding="utf-8") as fp:
            intrinsics = json.load(fp)
        target = TargetSpace.load(
            target_path or intrinsics_path.parent / TARGET_SPACE_FILENAME
        )
        return cls.build(intrinsics, target, input_size=input_size, crop=crop)

    @classmethod
    def build(
        cls,
        intrinsics: dict[str, Any],
        target: TargetSpace,
        input_size: tuple[int, int] | None = None,
        crop: bool = False,
    ) -> "FrameRemapper":
        full = (int(intrinsics["resolution"][0]), int(intrinsics["resolution"][1]))
        size = input_size or full
        K = np.asarray(intrinsics["K"], dtype=np.float64)
        D = np.asarray(intrinsics["D"], dtype=np.float64).ravel()

        if size != full:
            K = scale_intrinsics(K, _resize_scale(full, size, intrinsics.get("camera", "?")))

        width, height = target.size
        if target.design == DESIGN_PINHOLE:
            map_x, map_y = build_map_to_pinhole(K, D, target.K, width, height)
        else:
            map_x, map_y = build_map_to_distorted(K, D, target.K, target.D, width, height)

        mask = valid_mask(map_x, map_y, size[0], size[1])
        ratio = valid_ratio(map_x, map_y, size[0], size[1])

        box = None
        output_size = (width, height)
        if crop:
            box = crop_box(mask)
            output_size = (box[2], box[3])

        # 고정소수점 맵으로 바꾼다. remap 이 두 배쯤 빨라지고 정밀도 손실은
        # 1/32 픽셀이라 영상에서는 보이지 않는다.
        map1, map2 = cv2.convertMaps(map_x, map_y, cv2.CV_16SC2)

        return cls(
            camera=str(intrinsics.get("camera", "?")),
            input_size=size,
            output_size=output_size,
            valid_ratio=ratio,
            design=target.design,
            _map1=map1,
            _map2=map2,
            _crop=box,
        )

    # --- 쓰기 -------------------------------------------------------------

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """프레임 한 장을 target 공간으로 옮긴다.

        Raises:
            ResolutionMismatch: 프레임 크기가 만들 때와 다를 때. 맵은 크기마다
                따로이므로 조용히 늘려 쓰면 화면이 망가진다 (result.md 11-4).
        """
        size = (frame.shape[1], frame.shape[0])
        if size != self.input_size:
            raise ResolutionMismatch(
                f"프레임 크기가 다르다: {size} != {self.input_size}. "
                "카메라 설정이 바뀌었으면 FrameRemapper 를 다시 만든다"
            )
        out = cv2.remap(
            frame,
            self._map1,
            self._map2,
            INTERPOLATION,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=BORDER_VALUE,
        )
        if self._crop is None:
            return out
        x, y, w, h = self._crop
        return out[y : y + h, x : x + w]

    def describe(self) -> str:
        crop = f" crop {self._crop[2]}x{self._crop[3]}" if self._crop else ""
        return (
            f"{self.camera}: {self.input_size[0]}x{self.input_size[1]} -> "
            f"{self.output_size[0]}x{self.output_size[1]} (설계 {self.design}, "
            f"유효 {self.valid_ratio * 100:.2f}%){crop}"
        )


# --- 내부 --------------------------------------------------------------------


def _resize_scale(full: tuple[int, int], size: tuple[int, int], camera: str) -> float:
    """리사이즈 배율. 종횡비가 다르면 거부한다."""
    aspect_full = full[0] / full[1]
    aspect_now = size[0] / size[1]
    if abs(aspect_now - aspect_full) > ASPECT_TOLERANCE:
        raise ResolutionMismatch(
            f"{camera}: 종횡비가 다르다 (캘리브레이션 {full[0]}x{full[1]}, "
            f"입력 {size[0]}x{size[1]}). 단순 리사이즈가 아니라 크롭이 들어간 것이고, "
            "크롭은 화각을 바꾸므로 K 를 고칠 방법이 없다. 같은 종횡비로 받는다"
        )
    return size[0] / full[0]


