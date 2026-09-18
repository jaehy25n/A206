"""합성 촬영 장면 생성기 (테스트 전용).

알려진 K, D 와 알려진 자세로 체커보드를 투영해 **정답을 아는 데이터**를 만든다.
캘리브레이션이 그 K, D 를 되찾아오는지 보는 것이 목적이다.

두 가지 수준을 제공한다.
    make_corner_sets()  코너 좌표만 (projectPoints). 왜곡 D 를 그대로 쓸 수 있다
    render_pose()       실제 이미지 (warpPerspective). 검출기까지 포함해 확인하지만
                        평면 호모그래피라 **왜곡은 넣을 수 없다** (D = 0 인 장면)
"""

from __future__ import annotations

import cv2
import numpy as np

from camcal.board import BoardSpec

from conftest import render_checkerboard

#: 합성 장면의 기준 카메라. fx 와 fy 를 일부러 조금 다르게 둬서
#: "fx 와 fy 를 같다고 가정하고 짠 코드"가 있으면 드러나게 한다.
TRUE_K = np.array(
    [
        [1500.0, 0.0, 958.0],
        [0.0, 1494.0, 543.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

#: 광각 렌즈다운 배럴 왜곡 (k1 < 0).
TRUE_D = np.array([-0.2400, 0.0700, 0.0008, -0.0005, 0.0000], dtype=np.float64)

IMAGE_SIZE = (1920, 1080)  # (width, height)


def rodrigues(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    """오일러 각(도) -> rvec (3,1). 자세 다양성을 만들기 위한 편의 함수."""
    rx, ry, rz = np.radians([rx_deg, ry_deg, rz_deg])
    Rx = np.array([[1, 0, 0], [0, np.cos(rx), -np.sin(rx)], [0, np.sin(rx), np.cos(rx)]])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0], [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0], [np.sin(rz), np.cos(rz), 0], [0, 0, 1]])
    rvec, _ = cv2.Rodrigues(Rz @ Ry @ Rx)
    return rvec


def tvec_placing_center(
    spec: BoardSpec,
    rvec: np.ndarray,
    K: np.ndarray,
    target_uv: tuple[float, float],
    distance_mm: float,
) -> np.ndarray:
    """보드 중심이 화면의 target_uv 에, 카메라에서 distance_mm 에 오도록 하는 tvec.

    X_c = (u - cx) * Z_c / fx,  Y_c = (v - cy) * Z_c / fy  를 뒤집어 쓴 것이다.
    (왜곡은 무시하고 대략 그 자리에 놓기만 하면 된다 - 정확한 위치는 상관없고
    보드가 화면 안에 골고루 흩어지는 것이 목적이다)
    """
    obj = spec.object_points().astype(np.float64)
    center = obj.mean(axis=0)
    R, _ = cv2.Rodrigues(rvec)

    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    u, v = target_uv
    cam_point = np.array(
        [(u - cx) * distance_mm / fx, (v - cy) * distance_mm / fy, distance_mm],
        dtype=np.float64,
    )
    return (cam_point - R @ center).reshape(3, 1)


def default_poses(spec: BoardSpec, K: np.ndarray, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """화면 전체를 덮고 기울기와 거리가 다양한 자세 n 개.

    실제 촬영에서 하라고 action.md 에 적어둔 것과 같은 구성이다:
    구석까지 채우고, 좌우상하로 기울이고, 거리를 바꾼다.
    """
    width, height = IMAGE_SIZE
    spots = [
        (width * 0.25, height * 0.25),
        (width * 0.75, height * 0.25),
        (width * 0.50, height * 0.50),
        (width * 0.25, height * 0.75),
        (width * 0.75, height * 0.75),
    ]
    tilts = [(0, 0, 0), (28, 0, 8), (-25, 0, -6), (0, 30, 10), (0, -27, -12)]
    distances = [520.0, 700.0, 900.0]

    poses: list[tuple[np.ndarray, np.ndarray]] = []
    i = 0
    while len(poses) < n:
        spot = spots[i % len(spots)]
        tilt = tilts[(i // len(spots)) % len(tilts)]
        dist = distances[(i // (len(spots) * 2)) % len(distances)]
        rvec = rodrigues(*tilt)
        tvec = tvec_placing_center(spec, rvec, K, spot, dist)
        poses.append((rvec, tvec))
        i += 1
    return poses


def make_corner_sets(
    spec: BoardSpec,
    n_images: int,
    K: np.ndarray = TRUE_K,
    D: np.ndarray = TRUE_D,
    noise_px: float = 0.1,
    seed: int = 0,
) -> dict[int, np.ndarray]:
    """알려진 K, D 로 코너를 투영해 만든 {index: (N,1,2) float32}.

    noise_px 는 검출 노이즈를 흉내낸 가우시안 표준편차다. 0.1 px 은 실제
    cornerSubPix 가 좋은 조건에서 내는 수준.

    화면 밖으로 나가는 자세는 만들지 않는다 (assert 로 확인).
    """
    rng = np.random.default_rng(seed)
    obj = spec.object_points()
    width, height = IMAGE_SIZE
    out: dict[int, np.ndarray] = {}

    for i, (rvec, tvec) in enumerate(default_poses(spec, K, n_images)):
        projected, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
        pts = np.asarray(projected, dtype=np.float64).reshape(-1, 2)
        if noise_px > 0:
            pts = pts + rng.normal(0.0, noise_px, size=pts.shape)
        assert pts[:, 0].min() > 0 and pts[:, 0].max() < width, f"자세 {i} 가 화면 밖 (u)"
        assert pts[:, 1].min() > 0 and pts[:, 1].max() < height, f"자세 {i} 가 화면 밖 (v)"
        out[i] = pts.astype(np.float32).reshape(-1, 1, 2)
    return out


def render_pose(
    spec: BoardSpec,
    rvec: np.ndarray,
    tvec: np.ndarray,
    K: np.ndarray = TRUE_K,
    square_px: int = 60,
    margin_px: int = 60,
) -> np.ndarray:
    """한 자세의 체커보드를 실제 이미지로 그린다 (왜곡 없음, D = 0).

    보드 평면 -> 이미지 평면은 호모그래피 H = K [r1 r2 t] 이고, 보드 mm 좌표와
    패치 픽셀 좌표 사이도 단순 배율이므로 둘을 합쳐 warpPerspective 한 번에 끝난다.

    **왜곡은 넣을 수 없다** (호모그래피는 직선을 직선으로 보낸다). 그래서 이 이미지로
    추정한 D 는 0 근처여야 맞다. 왜곡이 있는 검증은 make_corner_sets 를 쓴다.
    """
    patch, _ = render_checkerboard(spec, square_px=square_px, margin_px=margin_px)

    # 보드 mm -> 패치 픽셀 (render_checkerboard 의 코너 배치와 같은 규칙)
    scale = square_px / spec.square_mm
    offset = margin_px + square_px - 0.5
    A = np.array(
        [[scale, 0.0, offset], [0.0, scale, offset], [0.0, 0.0, 1.0]], dtype=np.float64
    )

    R, _ = cv2.Rodrigues(rvec)
    P = np.column_stack([R[:, 0], R[:, 1], tvec.reshape(3)])
    H = K @ P @ np.linalg.inv(A)

    return cv2.warpPerspective(
        patch,
        H,
        IMAGE_SIZE,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(235, 235, 235),
    )
