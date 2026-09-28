"""RGB preprocessing modes (handoff doc sections 11, 14, 26).

Only the image changes between modes.  Pose, gripper, episode boundaries and the
train/val split are byte-identical across variants, which is what makes the
A/B comparison in section 25 fair.

    center_crop          16:9 -> central square -> out_res           (baseline v1)
    letterbox            16:9 -> full width, pad top/bottom          (keeps HFOV)
    matched_center_crop  undistort + reproject onto the robot wrist camera's
                         virtual pinhole, then square crop           (domain matching)
    stretch              plain resize, aspect ignored                (control)

Mode implementations are pure functions of a single frame so the converter can
run them in a thread pool.
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

ASPECT_TOL = 0.02

RGB_MODES = ("center_crop", "letterbox", "matched_center_crop", "stretch",
             "fit_rect")


# --------------------------------------------------------------------------- #
# intrinsics
# --------------------------------------------------------------------------- #
@dataclass
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    dist_coeffs: np.ndarray = field(default_factory=lambda: np.zeros(5))
    model: str = "pinhole"          # 'pinhole' | 'fisheye'
    name: str = ""

    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx],
                         [0.0, self.fy, self.cy],
                         [0.0, 0.0, 1.0]], dtype=np.float64)

    @property
    def hfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan((self.width / 2.0) / self.fx))

    @property
    def vfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan((self.height / 2.0) / self.fy))

    def square_crop_fov_deg(self) -> float:
        """HFOV left after cropping the central square out of this image."""
        side = min(self.width, self.height)
        f = self.fx if self.width <= self.height else self.fy
        return math.degrees(2.0 * math.atan((side / 2.0) / f))

    def aspect_matches(self, width: int, height: int, tol: float = 0.02) -> bool:
        return abs((self.width / self.height) - (width / height)) <= tol

    def scaled(self, width: int, height: int) -> "CameraIntrinsics":
        sx, sy = width / self.width, height / self.height
        return CameraIntrinsics(
            width=width, height=height,
            fx=self.fx * sx, fy=self.fy * sy,
            cx=self.cx * sx, cy=self.cy * sy,
            dist_coeffs=self.dist_coeffs.copy(), model=self.model, name=self.name)

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "model": self.model,
                "width": self.width, "height": self.height,
                "fx": self.fx, "fy": self.fy, "cx": self.cx, "cy": self.cy,
                "dist_coeffs": [float(v) for v in np.ravel(self.dist_coeffs)],
                "hfov_deg": round(self.hfov_deg, 4),
                "vfov_deg": round(self.vfov_deg, 4)}

    @staticmethod
    def from_dict(d: Dict[str, object], name: str = "") -> "CameraIntrinsics":
        """Accepts either full intrinsics or just an FOV.

        Minimal form, for when only the datasheet FOV is known:
            {"image_width": 1920, "image_height": 1080, "hfov_deg": 63.0}
        Full form:
            {"image_width":..., "image_height":..., "fx":..., "fy":...,
             "cx":..., "cy":..., "dist_coeffs":[...], "model":"pinhole"}
        The UMI GoPro ``*_intrinsics_*.json`` layout (``final_reproj_error`` /
        ``intrinsics`` block) is also accepted.
        """
        d = dict(d)
        if "intrinsics" in d and isinstance(d["intrinsics"], dict):
            # UMI / OpenSfM style
            inner = d["intrinsics"]
            w = int(d.get("image_width") or d.get("width"))
            h = int(d.get("image_height") or d.get("height"))
            fl = float(inner.get("focal_length", inner.get("focal", 0.0)))
            ar = float(inner.get("aspect_ratio", 1.0))
            px = float(inner.get("principal_point_x", 0.0))
            py = float(inner.get("principal_point_y", 0.0))
            fx = fl * w
            fy = fl * ar * w
            cx = w * (0.5 + px)
            cy = h * (0.5 + py)
            dist = np.array([inner.get(k, 0.0) for k in
                             ("radial_distortion_1", "radial_distortion_2",
                              "tangential_distortion_1", "tangential_distortion_2")],
                            dtype=np.float64)
            model = "fisheye" if "fisheye" in str(d.get("camera_model", "")).lower() else "pinhole"
            if model == "fisheye":
                dist = np.array([inner.get(k, 0.0) for k in
                                 ("radial_distortion_1", "radial_distortion_2",
                                  "radial_distortion_3", "radial_distortion_4")],
                                dtype=np.float64)
            return CameraIntrinsics(w, h, fx, fy, cx, cy, dist, model, name or str(d.get("camera_model", "")))

        w = int(d.get("image_width", d.get("width", 0)))
        h = int(d.get("image_height", d.get("height", 0)))
        if not (w and h):
            raise ValueError(f"intrinsics {name!r}: image_width/image_height are required")

        if "fx" in d:
            fx = float(d["fx"])
            fy = float(d.get("fy", fx))
            cx = float(d.get("cx", w / 2.0))
            cy = float(d.get("cy", h / 2.0))
        elif "hfov_deg" in d or "fov_deg" in d:
            hfov = float(d.get("hfov_deg", d.get("fov_deg")))
            fx = (w / 2.0) / math.tan(math.radians(hfov) / 2.0)
            fy = float(d["fy"]) if "fy" in d else fx
            cx, cy = w / 2.0, h / 2.0
        elif "vfov_deg" in d:
            vfov = float(d["vfov_deg"])
            fy = (h / 2.0) / math.tan(math.radians(vfov) / 2.0)
            fx = fy
            cx, cy = w / 2.0, h / 2.0
        else:
            raise ValueError(
                f"intrinsics {name!r}: need either 'fx' or 'hfov_deg'/'vfov_deg'")

        dist = np.asarray(d.get("dist_coeffs", d.get("distortion", [0, 0, 0, 0, 0])),
                          dtype=np.float64)
        model = str(d.get("model", "pinhole")).lower()
        return CameraIntrinsics(w, h, fx, fy, cx, cy, dist, model, name)

    @staticmethod
    def load(spec, name: str = "") -> "CameraIntrinsics":
        if isinstance(spec, CameraIntrinsics):
            return spec
        if isinstance(spec, (str, pathlib.Path)):
            with open(pathlib.Path(spec).expanduser(), "r") as f:
                spec = json.load(f)
        return CameraIntrinsics.from_dict(spec, name=name)


class PinholeRectConverter:
    """Re-render an image through a different (virtual) pinhole camera.

    The rectilinear analogue of UMI's ``FisheyeRectConverter``: it undistorts the
    source camera and reprojects onto a target camera with a chosen FOV, so that
    collector frames and robot wrist-camera frames end up in the same virtual
    camera -- the whole point of the section 25 matching experiment.
    """

    def __init__(self, src: CameraIntrinsics, out_res: Tuple[int, int],
                 out_fov_deg: float, fov_axis: str = "horizontal"):
        ow, oh = int(out_res[0]), int(out_res[1])
        if fov_axis == "horizontal":
            out_f = (ow / 2.0) / math.tan(math.radians(out_fov_deg) / 2.0)
        elif fov_axis == "vertical":
            out_f = (oh / 2.0) / math.tan(math.radians(out_fov_deg) / 2.0)
        else:
            raise ValueError(f"fov_axis must be 'horizontal' or 'vertical', got {fov_axis!r}")

        out_K = np.array([[out_f, 0.0, ow / 2.0],
                          [0.0, out_f, oh / 2.0],
                          [0.0, 0.0, 1.0]], dtype=np.float64)

        if src.model == "fisheye":
            D = np.asarray(src.dist_coeffs, dtype=np.float64).reshape(-1)[:4]
            map1, map2 = cv2.fisheye.initUndistortRectifyMap(
                src.K, D.reshape(4, 1), np.eye(3), out_K, (ow, oh), cv2.CV_16SC2)
        else:
            D = np.asarray(src.dist_coeffs, dtype=np.float64).reshape(-1)
            map1, map2 = cv2.initUndistortRectifyMap(
                src.K, D, np.eye(3), out_K, (ow, oh), cv2.CV_16SC2)

        self.map1, self.map2 = map1, map2
        self.src, self.out_K, self.out_res = src, out_K, (ow, oh)
        self.out_fov_deg, self.fov_axis = out_fov_deg, fov_axis

    def forward(self, img: np.ndarray) -> np.ndarray:
        return cv2.remap(img, self.map1, self.map2,
                         interpolation=cv2.INTER_AREA,
                         borderMode=cv2.BORDER_CONSTANT)

    def describe(self) -> Dict[str, object]:
        return {"out_res": list(self.out_res),
                "out_fov_deg": self.out_fov_deg,
                "fov_axis": self.fov_axis,
                "out_K": [[float(v) for v in row] for row in self.out_K],
                "source": self.src.to_dict()}


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #
@dataclass
class RgbPreprocessor:
    """Stateless-per-frame image transform, built once per dataset build."""

    mode: str
    out_res: Tuple[int, int]
    in_res: Tuple[int, int]
    pad_value: int = 0
    _rect: Optional[PinholeRectConverter] = None
    _info: Dict[str, object] = field(default_factory=dict)

    def __call__(self, img: np.ndarray) -> np.ndarray:
        if img.ndim != 3 or img.shape[2] != 3:
            raise ValueError(f"expected HxWx3 RGB frame, got shape {img.shape}")
        ih, iw = img.shape[:2]
        if (iw, ih) != self.in_res:
            raise ValueError(
                f"frame resolution {(iw, ih)} does not match the resolution this "
                f"preprocessor was built for {self.in_res}; episodes with mixed "
                f"resolutions must be converted separately")
        ow, oh = self.out_res

        if self.mode == "center_crop":
            side = min(iw, ih)
            x0, y0 = (iw - side) // 2, (ih - side) // 2
            crop = img[y0:y0 + side, x0:x0 + side]
            return cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_AREA)

        if self.mode == "stretch":
            return cv2.resize(img, (ow, oh), interpolation=cv2.INTER_AREA)

        if self.mode == "letterbox":
            scale = min(ow / iw, oh / ih)
            nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
            resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            out = np.full((oh, ow, 3), self.pad_value, dtype=img.dtype)
            y0, x0 = (oh - nh) // 2, (ow - nw) // 2
            out[y0:y0 + nh, x0:x0 + nw] = resized
            return out

        if self.mode == "fit_rect":
            # Crop the SOURCE to the output aspect ratio, then resize.  Unlike
            # letterbox this pads nothing, so every output pixel carries image.
            # With a 4:3 source and a wide output the crop takes it off the top
            # and bottom: full horizontal FOV is kept, vertical is spent.
            tgt, src = ow / oh, iw / ih
            if src > tgt:
                nw = int(round(ih * tgt)); x0 = (iw - nw) // 2
                crop = img[:, x0:x0 + nw]
            else:
                nh = int(round(iw / tgt)); y0 = (ih - nh) // 2
                crop = img[y0:y0 + nh, :]
            return cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_AREA)

        if self.mode == "matched_center_crop":
            return self._rect.forward(img)

        raise ValueError(f"unknown rgb mode {self.mode!r}; expected one of {RGB_MODES}")

    def describe(self) -> Dict[str, object]:
        info = {"mode": self.mode,
                "in_res": list(self.in_res),
                "out_res": list(self.out_res)}
        info.update(self._info)
        if self._rect is not None:
            info["rectification"] = self._rect.describe()
        return info


def build_preprocessor(mode: str, in_res: Tuple[int, int],
                       out_res: Tuple[int, int] = (224, 224),
                       pad_value: int = 0,
                       collector_intrinsics=None,
                       robot_intrinsics=None,
                       matched_fov_deg: Optional[float] = None,
                       matched_fov_axis: str = "horizontal",
                       source_aspect: Optional[float] = None,
                       allow_aspect_mismatch: bool = False,
                       warnings: Optional[list] = None) -> RgbPreprocessor:
    if mode not in RGB_MODES:
        raise ValueError(f"unknown rgb mode {mode!r}; expected one of {RGB_MODES}")
    warnings = warnings if warnings is not None else []

    # An experiment designed around one source aspect ratio still RUNS on
    # another -- center_crop takes min(w, h) whatever it is -- it just stops
    # testing what it was written to test. On 16:9 a central square throws away
    # 43.75% of the width (63.5 -> ~38 deg HFOV); on 4:3 it throws away 25%
    # (63.5 -> ~49.8 deg). The build silently becomes a different experiment,
    # and the numbers in the experiment's own notes stop being true. Refuse.
    if source_aspect is not None:
        actual = in_res[0] / in_res[1]
        if abs(actual - source_aspect) > ASPECT_TOL:
            msg = (f"source aspect {actual:.4f} ({in_res[0]}x{in_res[1]}) does not "
                   f"match the {source_aspect:.4f} this experiment declares. "
                   f"rgb_mode={mode!r} would still run, but the FOV figures in the "
                   f"experiment notes assume {source_aspect:.4f} and would be wrong. "
                   f"Either feed frames at the declared aspect, or set "
                   f"source_aspect=None on the variant, or pass "
                   f"allow_aspect_mismatch=True to build anyway (the zarr is then "
                   f"stamped source_aspect_mismatch=true).")
            if not allow_aspect_mismatch:
                raise ValueError(msg)
            warnings.append(msg)

    # Rescaling intrinsics across a different aspect ratio stretches fx and fy by
    # different factors, which is meaningless for a real lens. Catch the case
    # where the configured calibration resolution does not match the actual data.
    aspect_ok = True
    if collector_intrinsics is not None:
        _src = CameraIntrinsics.load(collector_intrinsics, "collector")
        aspect_ok = _src.aspect_matches(*in_res)
        if not aspect_ok:
            msg = (f"camera.collector_intrinsics is calibrated for "
                   f"{_src.width}x{_src.height} (aspect {_src.width/_src.height:.3f}) "
                   f"but the frames are {in_res[0]}x{in_res[1]} "
                   f"(aspect {in_res[0]/in_res[1]:.3f}).")
            if mode == "matched_center_crop":
                raise ValueError(
                    msg + " For matched_center_crop this makes the reprojection "
                    "geometrically wrong. Update the intrinsics to the resolution "
                    "the collector actually records at.")
            warnings.append(
                msg + " Reported FOV numbers would be meaningless, so they are "
                "omitted. The crop/resize itself is unaffected.")

    pre = RgbPreprocessor(mode=mode, out_res=tuple(out_res), in_res=tuple(in_res),
                          pad_value=pad_value)

    if mode == "center_crop":
        iw, ih = in_res
        side = min(iw, ih)
        pre._info["crop_box_xywh"] = [(iw - side) // 2, (ih - side) // 2, side, side]
        if collector_intrinsics is not None and aspect_ok:
            src = CameraIntrinsics.load(collector_intrinsics, "collector").scaled(iw, ih)
            pre._info["effective_hfov_deg"] = round(src.square_crop_fov_deg(), 3)
            pre._info["source_hfov_deg"] = round(src.hfov_deg, 3)

    elif mode == "letterbox":
        iw, ih = in_res
        ow, oh = out_res
        scale = min(ow / iw, oh / ih)
        nh = int(round(ih * scale))
        pre._info["content_rows"] = [(oh - nh) // 2, (oh - nh) // 2 + nh]
        pre._info["pad_value"] = pad_value
        pre._info["content_fraction"] = round(nh / oh, 4)
        if collector_intrinsics is not None and aspect_ok:
            src = CameraIntrinsics.load(collector_intrinsics, "collector").scaled(iw, ih)
            pre._info["effective_hfov_deg"] = round(src.hfov_deg, 3)

    elif mode == "matched_center_crop":
        if collector_intrinsics is None:
            raise ValueError(
                "rgb mode 'matched_center_crop' needs camera.collector_intrinsics "
                "in the collector config (fx/fy/cx/cy, or just hfov_deg).")
        src = CameraIntrinsics.load(collector_intrinsics, "collector").scaled(*in_res)
        fov = matched_fov_deg
        if fov is None:
            if robot_intrinsics is None:
                raise ValueError(
                    "rgb mode 'matched_center_crop' needs either camera.matched_fov_deg "
                    "or camera.robot_intrinsics to derive the target FOV from.")
            tgt = CameraIntrinsics.load(robot_intrinsics, "robot")
            fov = tgt.square_crop_fov_deg()
            pre._info["matched_fov_source"] = "robot_intrinsics.square_crop_fov_deg"
            pre._info["robot_intrinsics"] = tgt.to_dict()
        else:
            pre._info["matched_fov_source"] = "camera.matched_fov_deg"
        pre._rect = PinholeRectConverter(src, out_res, float(fov), matched_fov_axis)
        pre._info["effective_hfov_deg"] = round(float(fov), 3)

    elif mode == "fit_rect":
        iw, ih = in_res
        ow, oh = out_res
        if ow == oh:
            raise ValueError(
                "fit_rect with a square out_res is just center_crop; give a "
                "rectangular out_res (e.g. (224, 128)) or use center_crop")
        for n, v in (("width", ow), ("height", oh)):
            if v % 16:
                raise ValueError(
                    f"fit_rect out_res {n}={v} is not a multiple of 16; a ViT "
                    f"patch grid needs both sides divisible by the patch size")
        tgt, src = ow / oh, iw / ih
        kept = min(1.0, tgt / src) if src > tgt else 1.0
        pre._info["kept_horizontal_fraction"] = round(kept, 4)
        pre._info["kept_vertical_fraction"] = round(min(1.0, src / tgt), 4)
        pre._info["note"] = (
            "no padding; source cropped to the output aspect ratio. Needs a "
            "rectangular ViT (omx.model.RectTimmObsEncoder) -- the tensor shape "
            "is not 224x224.")

    elif mode == "stretch":
        pre._info["note"] = "aspect ratio is not preserved; control condition only"

    return pre
