"""Field-of-view diagnostics: where an object lands in the picture the ViT gets.

Evaluation only. Input: boolean masks over the full camera frame (320x180),
rendered from the simulator's ground truth; they are never given to the policy.
Each mask is carried through exactly the geometry the policy's image goes
through --

    frame -> rgb_geometry canvas (G0 crop / G1 letterbox / G2 rect)
          -> the evaluation CenterCrop (policy_server --deterministic)
          -> Resize back to the encoder's H x W

-- with nearest-neighbour sampling, so a mask stays a mask, and is measured on
the encoder input: area, box, the box centre's distance to each edge of the
image content (padding excluded), and how many 16 px ViT patches it touches.
"""
import cv2
import numpy as np

import rgb_geometry as G

PATCH = 16
VISIBLE_MIN_PX = 12       # the rollout's existing visibility floor
#: the evaluation crop, as the encoder builds it from RandomCrop(ratio 0.95)
#: and policy_server turns it into a CenterCrop of the same size
EVAL_CROP = {"g0_center224": (212, 212), "g1_letterbox224": (212, 212), "g2_rect288x176": (167, 273)}


def _to_canvas(mask, name):
    g = G.GEOMETRIES[name]
    m = mask.astype(np.uint8)
    if g["kind"] == "center":
        h, w = m.shape
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        W = g["canvas_wh"][0]
        return cv2.resize(m[y0:y0 + side, x0:x0 + side], (W, W), interpolation=cv2.INTER_NEAREST)
    cw, ch = g["content_wh"]
    W, H = g["canvas_wh"]
    small = cv2.resize(m, (cw, ch), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((H, W), np.uint8)
    top, left = (H - ch) // 2, (W - cw) // 2
    out[top:top + ch, left:left + cw] = small
    return out


def eval_crop_box(name):
    """(top, left, h, w) of the evaluation CenterCrop, torchvision's rounding."""
    W, H = G.GEOMETRIES[name]["canvas_wh"]
    ch, cw = EVAL_CROP[name]
    return int(round((H - ch) / 2.0)), int(round((W - cw) / 2.0)), ch, cw


def to_encoder_input(mask, name):
    W, H = G.GEOMETRIES[name]["canvas_wh"]
    top, left, ch, cw = eval_crop_box(name)
    c = _to_canvas(mask, name)[top:top + ch, left:left + cw]
    return cv2.resize(c, (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)


def content_in_encoder_input(name):
    """(x0, y0, x1, y1) of the image content (padding excluded) on the encoder input."""
    W, H = G.GEOMETRIES[name]["canvas_wh"]
    top, left, ch, cw = eval_crop_box(name)
    x0, y0, x1, y1 = G.content_box(name)
    sx, sy = W / cw, H / ch
    return (max(0.0, (x0 - left) * sx), max(0.0, (y0 - top) * sy),
            min(float(W), (x1 - left) * sx), min(float(H), (y1 - top) * sy))


def measure(mask_enc, name):
    W, H = G.GEOMETRIES[name]["canvas_wh"]
    area = int(mask_enc.sum())
    out = {"visible": area >= VISIBLE_MIN_PX, "area_px": area}
    if area == 0:
        out.update({"bbox_xyxy": None, "bbox_wh": None, "edge_dist_px": None,
                    "patches_touched": 0, "patches_half_covered": 0})
        return out
    ys, xs = np.nonzero(mask_enc)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ax0, ay0, ax1, ay1 = content_in_encoder_input(name)
    gh, gw = H // PATCH, W // PATCH
    cov = mask_enc[:gh * PATCH, :gw * PATCH].reshape(gh, PATCH, gw, PATCH).mean(axis=(1, 3))
    out.update({"bbox_xyxy": [x0, y0, x1, y1], "bbox_wh": [x1 - x0, y1 - y0],
                "edge_dist_px": {"left": round(cx - ax0, 1), "right": round(ax1 - cx, 1),
                                 "top": round(cy - ay0, 1), "bottom": round(ay1 - cy, 1)},
                "patches_touched": int((cov > 0).sum()), "patches_half_covered": int((cov >= 0.5).sum())})
    return out


def diagnostics(masks, active):
    """masks: {"object": bool HxW, "gripper": bool HxW, "tips": bool HxW} over
    the full frame. Returns the metrics for every geometry, the active one
    first, so a run's own view and what the others would have shown sit side
    by side."""
    res = {"active": active}
    for name in [active] + [n for n in G.GEOMETRIES if n != active]:
        enc = {k: to_encoder_input(v, name) for k, v in masks.items()}
        o = measure(enc["object"], name)
        o["gripper_visible"] = bool(enc["gripper"].sum() >= VISIBLE_MIN_PX)
        o["tips_px"] = int(enc["tips"].sum()) if "tips" in enc else None
        o["object_and_gripper_visible"] = bool(o["visible"] and o["gripper_visible"])
        res[name] = o
    return res
