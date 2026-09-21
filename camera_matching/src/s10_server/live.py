"""라이브 비교 - LUAZ(USB)와 S10(웹앱)을 같은 target 공간에서 나란히 본다.

왜 필요한가: 지표(valid ratio, stretch)는 "기하학적으로 가능한가"까지만 답한다.
두 카메라를 같은 공간으로 옮겼을 때 **실제로 겹치는지**는 눈으로 봐야 알 수 있고,
그건 정지 사진을 한참 뒤에 비교하는 것보다 실시간으로 보는 편이 훨씬 빠르다.

크기를 맞추는 방법 - S10 은 웹앱이 320x180 프리뷰만 보낸다. 1920x1080 용 맵을
그대로 쓸 수 없으므로 **K 를 축소 배율만큼 줄여** 프리뷰 해상도의 맵을 따로 만든다.
    이미지를 s 배로 줄이면  fx, fy, cx, cy 가 전부 s 배가 된다.
    D 는 그대로다 (정규 좌표는 배율과 무관하다).
LUAZ 는 원본 1920x1080 을 그대로 받으므로 원본 해상도에서 변환한 뒤 축소한다
(먼저 줄이고 변환하면 정보를 두 번 버린다).
"""

from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np

from camcal.remap_metrics import build_map_to_distorted, build_map_to_pinhole
from camcal.target_space import DESIGN_PINHOLE, TargetSpace

#: 비교 화면에 띄우는 크기. S10 프리뷰(320x180)보다 키우면 없는 정보가 커 보이기만 한다.
VIEW_WIDTH = 640
VIEW_HEIGHT = 360

#: 비교 화면용 JPEG 품질. 정렬을 보는 용도라 원본 품질이 필요 없다.
VIEW_JPEG_QUALITY = 80

#: LUAZ 프레임을 연속으로 못 읽으면 포기하는 횟수.
MAX_READ_FAILURES = 10


def scale_intrinsics(K: np.ndarray, scale: float) -> np.ndarray:
    """이미지를 scale 배로 줄였을 때의 K.

    fx, fy, cx, cy 가 전부 같은 배율로 줄어든다. 마지막 행(0, 0, 1)은 그대로다.
    D 는 손대지 않는다 - 정규 좌표에서 정의되므로 이미지 크기와 무관하다.
    """
    out = np.array(K, dtype=np.float64, copy=True)
    out[0, 0] *= scale
    out[1, 1] *= scale
    out[0, 2] *= scale
    out[1, 2] *= scale
    return out


def build_view_map(
    intrinsics: dict[str, Any],
    target: TargetSpace,
    width: int,
    height: int,
    source_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """원본이 source_size 로 줄어든 상태에서 target(width x height)으로 가는 맵."""
    full_w, full_h = int(intrinsics["resolution"][0]), int(intrinsics["resolution"][1])
    src_scale = source_size[0] / full_w
    dst_scale = width / target.size[0]

    K_src = scale_intrinsics(np.asarray(intrinsics["K"], dtype=np.float64), src_scale)
    D_src = np.asarray(intrinsics["D"], dtype=np.float64).ravel()
    K_target = scale_intrinsics(target.K, dst_scale)

    if target.design == DESIGN_PINHOLE:
        return build_map_to_pinhole(K_src, D_src, K_target, width, height)
    return build_map_to_distorted(K_src, D_src, K_target, target.D, width, height)


def encode_jpeg(image: np.ndarray, quality: int = VIEW_JPEG_QUALITY) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG 인코딩 실패")
    return buf.tobytes()


def fit_view(image: np.ndarray) -> np.ndarray:
    if (image.shape[1], image.shape[0]) == (VIEW_WIDTH, VIEW_HEIGHT):
        return image
    return cv2.resize(image, (VIEW_WIDTH, VIEW_HEIGHT), interpolation=cv2.INTER_AREA)


class LuazCamera:
    """비교 화면용 LUAZ 캡처. 촬영 도구와 **동시에 쓸 수 없다** (같은 장치다).

    해상도는 촬영과 같은 규칙으로 exact 로 확인한다. 다른 해상도로 열리면
    K 가 맞지 않으므로 조용히 진행하지 않는다.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        from capture_luaz import BACKENDS, CameraOpenError, open_camera

        self._lock = threading.Lock()
        self._failures = 0
        try:
            self.cap, self.info = open_camera(config)
        except CameraOpenError as exc:
            raise RuntimeError(f"LUAZ 를 열지 못했다: {exc}") from exc
        self.resolution = (
            int(self.info["resolution_actual"][0]),
            int(self.info["resolution_actual"][1]),
        )

    def read(self) -> np.ndarray:
        """한 장 읽는다. 스레드풀에서 부른다 (blocking)."""
        with self._lock:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._failures += 1
                if self._failures >= MAX_READ_FAILURES:
                    raise RuntimeError(
                        f"LUAZ 프레임을 {self._failures}회 연속 읽지 못했다. "
                        "USB 연결을 확인한다 (촬영 도구가 같은 카메라를 쓰고 있을 수도 있다)"
                    )
                raise RuntimeError("LUAZ 프레임을 읽지 못했다 (일시적)")
            self._failures = 0
            return frame

    def release(self) -> None:
        with self._lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
