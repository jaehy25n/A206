"""The image geometries of the FOV ablation, defined once.

The dataset builder and the runtime bridge both call these, so what a policy
is trained on and what it is shown at run time cannot drift apart.

    g0_center224     the existing contract: the central square of the frame,
                     cv2 INTER_AREA to 224x224. Identical, pixel for pixel, to
                     demos_to_umi_zarr.center_crop_resize and to the crop in
                     policy_bridge.preprocess_rgb -- those stay the production
                     G0 code and are not replaced by this.
    g1_letterbox224  the whole frame, aspect kept: 320x180 -> 224x126 content,
                     49 px of padding above and below, 224x224 canvas.
    g2_rect288x176   the whole frame, aspect kept: 320x180 -> 288x162 content,
                     7 px of padding above and below, a 288x176 canvas that a
                     16 px patch grid divides into 18 x 11 = 198 tokens.

Padding is uint8 128. The encoder applies no mean/std normalization (the image
normalizer is identity; its declared stats are mean 0.5), so the neutral value
is 0.5 gray; 127.5 cannot be stored in uint8, 128 is 0.50196, and the same 128
is used in training data and at run time.

Every array here is H x W x 3 uint8 RGB. Sizes are given as (width, height),
the order cv2 takes them in.
"""
import cv2
import numpy as np

PAD = 128

GEOMETRIES = {
    "g0_center224": {"kind": "center", "canvas_wh": (224, 224)},
    "g1_letterbox224": {"kind": "letterbox", "canvas_wh": (224, 224), "content_wh": (224, 126)},
    "g2_rect288x176": {"kind": "letterbox", "canvas_wh": (288, 176), "content_wh": (288, 162)},
}


def center_square(rgb, out=224):
    h, w = rgb.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    return cv2.resize(rgb[y0:y0 + side, x0:x0 + side], (out, out), interpolation=cv2.INTER_AREA)


def letterbox(rgb, canvas_wh, content_wh, pad=PAD):
    h, w = rgb.shape[:2]
    cw, ch = content_wh
    W, H = canvas_wh
    # the content keeps the frame's aspect exactly, or it is not full FOV
    if w * ch != h * cw:
        raise ValueError(f"content {cw}x{ch} does not keep the aspect of a {w}x{h} frame")
    if cw > W or ch > H:
        raise ValueError(f"content {cw}x{ch} does not fit the {W}x{H} canvas")
    small = cv2.resize(rgb, (cw, ch), interpolation=cv2.INTER_AREA)
    top, left = (H - ch) // 2, (W - cw) // 2
    out = np.full((H, W, 3), pad, np.uint8)
    out[top:top + ch, left:left + cw] = small
    return out


def content_box(name):
    """(x0, y0, x1, y1) of the image content inside the canvas."""
    g = GEOMETRIES[name]
    W, H = g["canvas_wh"]
    if g["kind"] == "center":
        return (0, 0, W, H)
    cw, ch = g["content_wh"]
    top, left = (H - ch) // 2, (W - cw) // 2
    return (left, top, left + cw, top + ch)


def apply(name, rgb):
    g = GEOMETRIES[name]
    if g["kind"] == "center":
        return center_square(rgb, g["canvas_wh"][0])
    return letterbox(rgb, g["canvas_wh"], g["content_wh"])


def to_chw_float(img):
    """What the policy is sent: CHW float32 in [0, 1], as preprocess_rgb does."""
    return np.moveaxis(img.astype(np.float32) / 255.0, -1, 0)


def frame_to_canvas(name, frame_wh=(320, 180)):
    """The affine map from frame pixel coordinates to canvas pixel coordinates:
    canvas = s * frame + (tx, ty). Used to place ground-truth geometry (object
    masks, boxes) in the picture the encoder receives."""
    g = GEOMETRIES[name]
    fw, fh = frame_wh
    W, H = g["canvas_wh"]
    if g["kind"] == "center":
        side = min(fw, fh)
        s = W / side
        return s, -((fw - side) // 2) * s, -((fh - side) // 2) * s
    cw, ch = g["content_wh"]
    s = cw / fw
    left, top = (W - cw) // 2, (H - ch) // 2
    return s, float(left), float(top)
