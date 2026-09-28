"""Static tests of fov_diag (no simulator, no rendering): synthetic masks."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim_umi/src"))
import cv2
import numpy as np
import torch
import torchvision

import fov_diag as F
import rgb_geometry as G

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def disc(cx, cy, r):
    m = np.zeros((180, 320), np.uint8)
    cv2.circle(m, (cx, cy), r, 1, -1)
    return m.astype(bool)


def image_pipeline_bbox(mask, name):
    """The same disc as an IMAGE through the real policy path: rgb_geometry,
    then torchvision CenterCrop and Resize(antialias) as the server does."""
    img = np.repeat((mask * 255).astype(np.uint8)[..., None], 3, axis=2)
    canvas = G.apply(name, img)
    if G.GEOMETRIES[name]["kind"] != "center":
        x0, y0, x1, y1 = G.content_box(name)
        canvas[:y0] = 0; canvas[y1:] = 0
    t = torch.from_numpy(canvas).permute(2, 0, 1).float()[None] / 255
    W, H = G.GEOMETRIES[name]["canvas_wh"]
    t = torchvision.transforms.CenterCrop(F.EVAL_CROP[name])(t)
    t = torchvision.transforms.Resize((H, W), antialias=True)(t)
    m = t[0, 0].numpy() > 0.5
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


expect_r = {"g0_center224": 20 * 224 / 180 * 224 / 212, "g1_letterbox224": 20 * 0.7 * 224 / 212,
            "g2_rect288x176": 20 * 0.9 * 288 / 273}
d = F.diagnostics({"object": disc(160, 90, 20), "gripper": disc(160, 175, 8), "tips": np.zeros((180, 320), bool)},
                  "g1_letterbox224")
check("active geometry listed first", list(d)[:2] == ["active", "g1_letterbox224"])
for name, r in expect_r.items():
    m = d[name]
    w, h = m["bbox_wh"]
    check(f"{name}: centred disc diameter", abs(w - 2 * r) <= 2.5 and abs(h - 2 * r) <= 2.5,
          f"box {w}x{h}, expected ~{2 * r:.1f}")
    ref = image_pipeline_bbox(disc(160, 90, 20), name)
    check(f"{name}: mask mapping agrees with the real image path", ref is not None and
          max(abs(a - b) for a, b in zip(ref, m["bbox_xyxy"])) <= 2, f"mask {m['bbox_xyxy']} image {ref}")
e = d["g1_letterbox224"]["edge_dist_px"]
check("G1 edge distances exclude the padding (content 45.4..178.6 high)",
      abs(e["top"] - 66.6) < 2 and abs(e["bottom"] - 66.6) < 2 and abs(e["left"] - 112) < 2, str(e))
left = F.diagnostics({"object": disc(30, 90, 15), "gripper": np.zeros((180, 320), bool),
                      "tips": np.zeros((180, 320), bool)}, "g0_center224")
check("ball in the left third: invisible to G0, visible to G1 and G2",
      (not left["g0_center224"]["visible"]) and left["g1_letterbox224"]["visible"] and left["g2_rect288x176"]["visible"],
      f"areas G0 {left['g0_center224']['area_px']} G1 {left['g1_letterbox224']['area_px']} G2 {left['g2_rect288x176']['area_px']}")
for name in G.GEOMETRIES:
    ref = image_pipeline_bbox(disc(30, 90, 15), name)
    m = left[name]
    same = (ref is None and m["bbox_xyxy"] is None) or (ref is not None and m["bbox_xyxy"] is not None and
                                                        max(abs(a - b) for a, b in zip(ref, m["bbox_xyxy"])) <= 2)
    check(f"{name}: edge disc mapping agrees with the real image path", same, f"mask {m['bbox_xyxy']} image {ref}")
big = F.diagnostics({"object": disc(160, 90, 40), "gripper": np.zeros((180, 320), bool), "tips": np.zeros((180, 320), bool)},
                    "g2_rect288x176")
check("patch counts grow with the object", big["g2_rect288x176"]["patches_touched"] > d["g2_rect288x176"]["patches_touched"],
      f"{d['g2_rect288x176']['patches_touched']} -> {big['g2_rect288x176']['patches_touched']}")
check("object+gripper flag", d["g1_letterbox224"]["object_and_gripper_visible"] is True)
print("eval crop boxes:", {n: F.eval_crop_box(n) for n in G.GEOMETRIES})
print("content on encoder input:", {n: tuple(round(v, 1) for v in F.content_in_encoder_input(n)) for n in G.GEOMETRIES})
sys.exit(0 if ok else 1)
