"""Read the collector's jaw opening off its own camera, then hide the cue.

The collector has no encoder on its gripper, so its opening is estimated from
two saturated patches near the fingertips. The real OMX has no patches -- it
reads its Dynamixel -- so the patches must not survive into the image the
policy learns from, or the encoder will lean on a feature that does not exist
at deployment.

    raw wrist RGB
       |-- detect_tips()  -> two blob centroids -> pixel gap -> opening
       `-- mask_magenta() -> patches painted over with the surrounding white
                             -> policy RGB

MuJoCo knows the true width, so `estimate_width` can be scored against it
rather than trusted. See scripts/verify_gripper_vision.py.
"""
import dataclasses
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


@dataclasses.dataclass
class TipDetectorConfig:
    """HSV gate plus geometry. Every number here is a parameter on purpose."""
    # Magenta sits near hue 150 in OpenCV's 0..179 scale.
    hue_range: Tuple[int, int] = (140, 170)
    sat_min: int = 90
    val_min: int = 60
    #: Only look where the fingertips can be. Fractions of (H, W).
    roi: Tuple[float, float, float, float] = (0.35, 1.0, 0.0, 1.0)  # y0,y1,x0,x1
    #: A held ball hides most of each patch: 37 px of magenta becomes 9, split
    #: 6 and 3. At 4 the smaller one was thrown away, the detector saw a single
    #: blob and reported no gap, and the width silently held its last value --
    #: "open" -- for the whole carry. Nothing else in the scene is magenta, so
    #: the floor can be 2; what rejects noise is the geometry test below.
    min_blob_area: int = 2
    #: The two tips sit at the same height in a camera bolted to the gripper
    #: (measured: within 2 px at every jaw angle). A candidate pair further
    #: apart in y than this fraction of the image height is not the tips.
    max_tip_dy_frac: float = 0.06
    #: The fringe around a patch is anti-aliased: part magenta, part whatever
    #: is behind it. Those pixels have to go too, or the encoder can still key
    #: on them. They are NOT taken by dilating the strong mask -- that grows
    #: into anything nearby, and with a white ball held at the tips it ate 14
    #: of the ball's pixels. Instead the strong mask is grown only into pixels
    #: that are themselves magenta-ish AND connected to it: a geodesic
    #: dilation under the weak gate below. White has no chroma, so a white
    #: ball or a white finger stops the growth dead.
    weak_hue_range: Tuple[int, int] = (130, 178)
    weak_sat_min: int = 25
    #: max(R,G,B) - min(R,G,B). A white surface sits near zero here whatever
    #: its brightness, which is what keeps the ball out of the mask.
    weak_chroma_min: int = 18
    mask_grow_iters: int = 4
    #: How the hole is filled.
    #:
    #:   surface_median  the ring, minus its darker half, minus anything still
    #:                   magenta -- i.e. the FINGER around the patch -- and its
    #:                   median. The patch is glued to the fingertip, so what
    #:                   belongs in that hole is fingertip.
    #:   inpaint         Telea, per pixel from the boundary. Correct in
    #:                   principle and wrong here: the patch touches the tip's
    #:                   silhouette, so it drags background grey into the white.
    #:   ring_median     the whole ring averaged. The original, and the reason
    #:                   the repaint was visible: that ring is only ~42% finger,
    #:                   so it came out mid grey on a white tip, and pink when
    #:                   the jaw was shut.
    #:
    #: Scored against a render of the same pose with the patches switched off:
    #:                      alpha 0.00   0.35   0.70   1.00
    #:   ring_median              105.7  103.9   71.0   45.0
    #:   inpaint                   28.7   29.0   26.5   39.0
    #:   surface_median             0.00   0.80   0.00   0.68
    fill_mode: str = "surface_median"
    #: Which half of the ring counts as the finger. Anything from the 50th to
    #: the 80th percentile gives the same answer, so this is not a tuned knob.
    fill_luma_percentile: int = 60
    inpaint_radius: int = 3


def _hsv_mask(rgb: np.ndarray, cfg: TipDetectorConfig) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lo = np.array([cfg.hue_range[0], cfg.sat_min, cfg.val_min], np.uint8)
    hi = np.array([cfg.hue_range[1], 255, 255], np.uint8)
    return cv2.inRange(hsv, lo, hi)


def _roi_slice(shape, cfg: TipDetectorConfig):
    h, w = shape[:2]
    y0, y1, x0, x1 = cfg.roi
    return slice(int(y0 * h), int(y1 * h)), slice(int(x0 * w), int(x1 * w))


def detect_tips(rgb: np.ndarray,
                cfg: Optional[TipDetectorConfig] = None) -> Dict[str, object]:
    """Find the two tip patches. Returns centroids in full-image pixels."""
    cfg = cfg or TipDetectorConfig()
    ys, xs = _roi_slice(rgb.shape, cfg)
    mask = np.zeros(rgb.shape[:2], np.uint8)
    mask[ys, xs] = _hsv_mask(np.ascontiguousarray(rgb[ys, xs]), cfg)

    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    blobs = [(int(stats[i, cv2.CC_STAT_AREA]), float(cent[i][0]), float(cent[i][1]))
             for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= cfg.min_blob_area]
    blobs.sort(reverse=True)
    out: Dict[str, object] = {"n_blobs": len(blobs), "mask": mask}
    # The tips are level with each other, so the partner of the biggest blob is
    # the biggest one at its height -- not merely the second biggest anywhere.
    if blobs:
        y0 = blobs[0][2]
        tol = cfg.max_tip_dy_frac * rgb.shape[0]
        blobs = [b for b in blobs if abs(b[2] - y0) <= tol]
    if len(blobs) < 2:
        out.update(left=None, right=None, pixel_gap=None)
        return out
    two = sorted(blobs[:2], key=lambda b: b[1])          # by x
    out["left"] = (two[0][1], two[0][2])
    out["right"] = (two[1][1], two[1][2])
    out["areas"] = (two[0][0], two[1][0])
    out["pixel_gap"] = float(np.hypot(two[1][1] - two[0][1], two[1][2] - two[0][2]))
    return out


def fit_scale(pixel_gaps, true_widths) -> Dict[str, float]:
    """Least-squares width = a * pixel_gap + b over paired observations.

    The tips sit at a fixed depth in the wrist view, so the mapping is close to
    linear; fitting it beats hard-coding a focal length that is not measured.
    """
    g = np.asarray(pixel_gaps, float)
    w = np.asarray(true_widths, float)
    ok = np.isfinite(g) & np.isfinite(w)
    a, b = np.polyfit(g[ok], w[ok], 1)
    pred = a * g[ok] + b
    return {"a": float(a), "b": float(b),
            "rmse_m": float(np.sqrt(np.mean((pred - w[ok]) ** 2))),
            "max_abs_err_m": float(np.max(np.abs(pred - w[ok]))),
            "n": int(ok.sum())}


def estimate_width(rgb: np.ndarray, scale: Dict[str, float],
                   cfg: Optional[TipDetectorConfig] = None) -> Optional[float]:
    d = detect_tips(rgb, cfg)
    if d["pixel_gap"] is None:
        return None
    return float(scale["a"] * d["pixel_gap"] + scale["b"])


def _weak_magenta(rgb: np.ndarray, cfg: TipDetectorConfig) -> np.ndarray:
    """Pixels that are plausibly part of a patch's anti-aliased edge.

    Wider hue and much lower saturation than the strong gate, plus a chroma
    floor. White is colourless at every brightness, so it never qualifies --
    which is the whole point: the growth has to stop at the ball.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, _ = cv2.split(hsv)
    lo, hi = cfg.weak_hue_range
    chroma = (rgb.max(axis=2).astype(np.int16)
              - rgb.min(axis=2).astype(np.int16))
    return (((h >= lo) & (h <= hi) & (s >= cfg.weak_sat_min)
             & (chroma >= cfg.weak_chroma_min)).astype(np.uint8))


def _grow_into_fringe(rgb: np.ndarray, strong: np.ndarray,
                      cfg: TipDetectorConfig) -> np.ndarray:
    """Geodesic dilation of `strong` under the weak-magenta gate."""
    weak = _weak_magenta(rgb, cfg)
    k = np.ones((3, 3), np.uint8)
    grown = strong.copy()
    for _ in range(cfg.mask_grow_iters):
        nxt = cv2.dilate(grown, k, iterations=1) & weak
        nxt = nxt | grown
        if np.array_equal(nxt, grown):
            break
        grown = nxt
    return grown


def mask_magenta(rgb: np.ndarray, cfg: Optional[TipDetectorConfig] = None,
                 fill: Optional[Tuple[int, int, int]] = None) -> np.ndarray:
    """Paint the patches out with the gripper white around them.

    Uses the median of a ring just outside the dilated patch rather than a
    constant, so the repaint follows the local shading instead of leaving a
    flat rectangle that is just as distinctive as the magenta was.
    """
    cfg = cfg or TipDetectorConfig()
    ys, xs = _roi_slice(rgb.shape, cfg)
    m = np.zeros(rgb.shape[:2], np.uint8)
    m[ys, xs] = _hsv_mask(np.ascontiguousarray(rgb[ys, xs]), cfg)
    if not m.any():
        return rgb.copy()
    grown = _grow_into_fringe(rgb, m, cfg)
    out = rgb.copy()
    if fill is not None:
        out[grown > 0] = fill
        return out
    ring = cv2.dilate(grown, np.ones((9, 9), np.uint8), iterations=1) & ~grown
    ring = ring & ~_weak_magenta(rgb, cfg)

    if cfg.fill_mode == "surface_median":
        if ring.any():
            luma = rgb.astype(np.int32).mean(axis=2)
            thr = np.percentile(luma[ring > 0], cfg.fill_luma_percentile)
            lit = (ring > 0) & (luma >= thr)
            out[grown > 0] = np.median(rgb[lit], axis=0).astype(np.uint8)
        else:
            out[grown > 0] = (235, 235, 235)
        return out

    if cfg.fill_mode == "inpaint":
        # Per pixel, from its own neighbourhood: a hole on the finger fills
        # with finger, a hole over the background fills with background, and
        # the shading across a curved tip carries through. Telea's method
        # walks inward from the boundary, so it never invents a colour that is
        # not already next to the pixel it is filling.
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        done = cv2.inpaint(bgr, (grown > 0).astype(np.uint8),
                           cfg.inpaint_radius, cv2.INPAINT_TELEA)
        return cv2.cvtColor(done, cv2.COLOR_BGR2RGB)

    if ring.any():
        out[grown > 0] = np.median(rgb[ring > 0], axis=0).astype(np.uint8)
    else:
        out[grown > 0] = (235, 235, 235)
    return out
