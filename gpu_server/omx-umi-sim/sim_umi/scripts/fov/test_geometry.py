"""Checks on the FOV geometries before anything is trained on them.

    python sim_umi/scripts/fov/test_geometry.py --out-dir <dir>

1. G0 is frozen: the production functions (demos_to_umi_zarr.center_crop_resize,
   policy_bridge.preprocess_rgb) are taken from their source files as they
   stand -- not re-typed -- and compared with rgb_geometry on 100 real frames.
   Required: max |difference| = 0.
2. A synthetic frame with a coordinate-coded grid, four coloured corners and a
   circle goes through G1 and G2: no stretch (circle stays round), no flip, no
   H/W swap, no channel swap, no unexpected crop (the frame's edge columns and
   rows land on the content's edges).
3. Twenty real frames chosen by content (ball centred, ball near the left and
   right edges, gripper and ball, the last frame before GRASP, LIFT) are shown
   G0 | G1 | G2 side by side, and the ball's box is measured in each: in G1 and
   G2 it must stay round.
"""
import ast
import json
import pathlib
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))

import click
import cv2
import numpy as np

import rgb_geometry as G


def production_function(path, name):
    """The function exactly as written in the production file."""
    src = pathlib.Path(path).read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    code = textwrap.dedent(ast.get_source_segment(src, fn))
    ns = {"cv2": cv2, "np": np}
    exec(code, ns)
    return ns[name], code


def ball_near(img, cxy, box, thr=236, r=14):
    """The bright blob whose centre is nearest a given canvas point -- the same
    ball found in the raw frame, not whatever else is white in a wider view."""
    x0, y0, x1, y1 = box
    sub = img[y0:y1, x0:x1]
    g = cv2.cvtColor(sub, cv2.COLOR_RGB2GRAY)
    n, lab, st, cen = cv2.connectedComponentsWithStats((g >= thr).astype(np.uint8))
    best = None
    for i in range(1, n):
        d = np.hypot(cen[i][0] + x0 - cxy[0], cen[i][1] + y0 - cxy[1])
        if st[i, 4] > 20 and d < r and (best is None or d < best[0]):
            best = (d, i)
    if best is None:
        return None
    i = best[1]
    return int(st[i, 2]), int(st[i, 3]), float(cen[i][0] + x0), float(cen[i][1] + y0)


def ball_box(img, box=None, thr=236):
    """Largest bright blob that is not a fingertip (fingertips reach the bottom
    edge of the frame) -- the ball. Returns (w, h, cx, cy) or None."""
    x0, y0, x1, y1 = box or (0, 0, img.shape[1], img.shape[0])
    sub = img[y0:y1, x0:x1]
    g = cv2.cvtColor(sub, cv2.COLOR_RGB2GRAY)
    n, lab, st, cen = cv2.connectedComponentsWithStats((g >= thr).astype(np.uint8))
    c = [(st[i, 4], i) for i in range(1, n)
         if st[i, 1] + st[i, 3] < sub.shape[0] - 1 and st[i, 0] > 0 and st[i, 0] + st[i, 2] < sub.shape[1]
         and st[i, 4] > 40]
    if not c:
        return None
    _, i = max(c)
    return int(st[i, 2]), int(st[i, 3]), float(cen[i][0]), float(cen[i][1])


@click.command()
@click.option("--out-dir", required=True)
def main(out_dir):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rep = {}
    # ---------------------------------------------------------------- frames
    eps = sorted((SIM / "data/demos/train").glob("episode_*.npz")) + \
        sorted((SIM / "data/demos/v2_train").glob("episode_*.npz"))
    # the montage may also look at held-out demos: it checks the transform, not the data
    look = eps + sorted((SIM / "data/demos/val").glob("episode_*.npz")) + \
        sorted((SIM / "data/demos/v2_val").glob("episode_*.npz"))
    rng = np.random.default_rng(0)
    frames = []
    for p in rng.choice(eps, 25, replace=False):
        d = np.load(p, allow_pickle=True)
        for k in rng.choice(len(d["rgb"]), 4, replace=False):
            frames.append(d["rgb"][k])
    # ------------------------------------------------------------- 1. G0 frozen
    ccr, ccr_src = production_function(SIM / "scripts/demos_to_umi_zarr.py", "center_crop_resize")
    pre, pre_src = production_function(SIM / "ros/policy_bridge.py", "preprocess_rgb")
    d_crop = max(int(np.abs(ccr(f, (224, 224)).astype(int) - G.apply("g0_center224", f).astype(int)).max())
                 for f in frames)
    d_pre = max(float(np.abs(pre(f) - G.to_chw_float(G.apply("g0_center224", f))).max()) for f in frames)
    rep["g0_frozen"] = {"frames": len(frames), "max_abs_uint8_vs_center_crop_resize": d_crop,
                        "max_abs_float_vs_preprocess_rgb": d_pre, "pass": d_crop == 0 and d_pre == 0.0}
    print("1. G0 frozen:", rep["g0_frozen"], flush=True)

    # --------------------------------------------------------- 2. synthetic grid
    W0, H0 = 320, 180
    syn = np.zeros((H0, W0, 3), np.uint8)
    xs, ys = np.meshgrid(np.arange(W0), np.arange(H0))
    syn[..., 0] = (xs * 255 // (W0 - 1)).astype(np.uint8)          # R encodes x
    syn[..., 1] = (ys * 255 // (H0 - 1)).astype(np.uint8)          # G encodes y
    syn[..., 2] = 60
    syn[:20, :20] = (255, 0, 0)       # top-left red
    syn[:20, -20:] = (0, 255, 0)      # top-right green
    syn[-20:, :20] = (0, 0, 255)      # bottom-left blue
    syn[-20:, -20:] = (255, 255, 0)   # bottom-right yellow
    CIRCLE = (0, 200, 200)
    syn_c = syn.copy()
    cv2.circle(syn_c, (160, 90), 40, CIRCLE, -1)
    # the grid is only for looking at; nothing is judged on it
    syn_grid = syn_c.copy()
    syn_grid[((xs % 40 == 0) | (ys % 40 == 0)) & (np.abs(syn_c.astype(int) - CIRCLE).max(2) > 0)] = (255, 255, 255)
    cv2.imwrite(str(out / "synthetic_input.png"), cv2.cvtColor(syn_grid, cv2.COLOR_RGB2BGR))
    rep["synthetic"] = {}
    tiles = []
    for name in ("g1_letterbox224", "g2_rect288x176"):
        img = G.apply(name, syn_c)
        x0, y0, x1, y1 = G.content_box(name)
        H, W = img.shape[:2]
        cont = img[y0:y1, x0:x1]
        ch, cw = cont.shape[:2]
        corners = {"top-left": cont[4, 4], "top-right": cont[4, cw - 5],
                   "bottom-left": cont[ch - 5, 4], "bottom-right": cont[ch - 5, cw - 5]}
        want = {"top-left": (255, 0, 0), "top-right": (0, 255, 0), "bottom-left": (0, 0, 255),
                "bottom-right": (255, 255, 0)}
        corner_ok = all(np.abs(corners[k].astype(int) - np.array(want[k])).max() <= 12 for k in want)
        # the circle: diameter 80 px in the frame, s = cw/320 in the canvas
        m = (np.abs(cont.astype(int) - np.array(CIRCLE)).max(axis=2) <= 20)
        ys_, xs_ = np.where(m)
        cw_px, ch_px = xs_.max() - xs_.min() + 1, ys_.max() - ys_.min() + 1
        s = cw / W0
        # R should rise left to right, G top to bottom, inside the content
        r_row = cont[ch // 8, 30:cw - 30, 0].astype(int)   # above the circle, clear of the corners
        g_col = cont[30:ch - 30, cw // 5, 1].astype(int)
        mono_r = np.corrcoef(np.arange(len(r_row)), r_row)[0, 1]
        mono_g = np.corrcoef(np.arange(len(g_col)), g_col)[0, 1]
        pad_ok = bool((img[:y0] == G.PAD).all() and (img[y1:] == G.PAD).all()) if y0 > 0 else True
        # no crop: the frame's first and last columns (R = 0 and R = 255 away from
        # the corner squares) appear in the content's first and last columns
        edge_ok = cont[ch // 2, 0, 0] <= 8 and cont[ch // 2, cw - 1, 0] >= 247
        top_ok = cont[0, cw // 2 + 7, 1] <= 12 and cont[ch - 1, cw // 2 + 7, 1] >= 240
        rep["synthetic"][name] = {
            "canvas_HxW": [H, W], "content_box_x0y0x1y1": [x0, y0, x1, y1], "content_HxW": [ch, cw],
            "circle_box_px_WxH": [int(cw_px), int(ch_px)], "circle_expected_px": round(80 * s, 2),
            "circle_aspect_h_over_w": round(ch_px / cw_px, 3),
            "corners_right_colour_and_place (no flip, no swap)": bool(corner_ok),
            "R rises with x (corr)": round(float(mono_r), 4), "G rises with y (corr)": round(float(mono_g), 4),
            "padding_is_128": pad_ok, "frame_edges_reach_content_edges (no crop)": bool(edge_ok and top_ok)}
        print(f"2. synthetic {name}:", rep["synthetic"][name], flush=True)
        tiles.append(G.apply(name, syn_grid))
    g0s = G.apply("g0_center224", syn_grid)
    row = [cv2.resize(x, (int(x.shape[1] * 300 / x.shape[0]), 300), interpolation=cv2.INTER_NEAREST)
           for x in [syn_grid, g0s] + tiles]
    cv2.imwrite(str(out / "synthetic_raw_g0_g1_g2.png"), cv2.cvtColor(np.hstack(row), cv2.COLOR_RGB2BGR))

    # ------------------------------------------------------- 3. real frames
    picks = {"ball_centre": [], "ball_left_edge": [], "ball_right_edge": [], "gripper_and_ball": [],
             "last_before_grasp": [], "lift": []}
    for p in look:
        d = np.load(p, allow_pickle=True)
        st, rgb = d["stage"], d["rgb"]
        gi = np.where(st == "GRASP")[0]
        if len(gi) and len(picks["last_before_grasp"]) < 4:
            picks["last_before_grasp"].append((p.parent.name, p.stem, int(gi[0] - 1), rgb[gi[0] - 1]))
        li = np.where(st == "LIFT")[0]
        if len(li) and len(picks["lift"]) < 3:
            picks["lift"].append((p.parent.name, p.stem, int(li[len(li) // 2]), rgb[li[len(li) // 2]]))
        for k in range(0, len(rgb), 2):
            b = ball_box(rgb[k])
            if b is None or b[0] < 12:
                continue
            cx = b[2]
            key = ("ball_left_edge" if cx < 60 else "ball_right_edge" if cx > 260 else
                   "ball_centre" if abs(cx - 160) < 15 and st[k] in ("SEARCH_OBJECT", "APPROACH_OBJECT") else None)
            if key and len(picks[key]) < 4:
                picks[key].append((p.parent.name, p.stem, k, rgb[k]))
            if st[k] == "APPROACH_OBJECT" and b[3] > 110 and len(picks["gripper_and_ball"]) < 4:
                picks["gripper_and_ball"].append((p.parent.name, p.stem, k, rgb[k]))
    rows, table = [], []
    for kind, lst in picks.items():
        for split, stem, k, f in lst:
            g0, g1, g2 = (G.apply(n, f) for n in ("g0_center224", "g1_letterbox224", "g2_rect288x176"))
            rb = ball_box(f)
            b0 = b1 = b2 = None
            if rb:
                def at(name, img):
                    s_, tx, ty = G.frame_to_canvas(name)
                    return ball_near(img, (rb[2] * s_ + tx, rb[3] * s_ + ty), G.content_box(name))
                b0, b1, b2 = at("g0_center224", g0), at("g1_letterbox224", g1), at("g2_rect288x176", g2)
            table.append({"kind": kind, "src": f"{split}/{stem}#{k}",
                          "raw_ball_WxH": rb[:2] if rb else None, "g0_ball_WxH": b0[:2] if b0 else None,
                          "g1_ball_WxH": b1[:2] if b1 else None, "g2_ball_WxH": b2[:2] if b2 else None})
            H = 224
            tile = [cv2.resize(f, (int(320 * H / 180), H), interpolation=cv2.INTER_AREA), g0, g1,
                    cv2.resize(g2, (int(288 * H / 176), H), interpolation=cv2.INTER_NEAREST)]
            r = np.hstack([np.pad(t, ((0, 0), (0, 6), (0, 0)), constant_values=0) for t in tile])
            cv2.putText(r, f"{kind}  {split}/{stem}#{k}", (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
            rows.append(r)
    head = np.zeros((22, rows[0].shape[1], 3), np.uint8)
    for x, t in zip((6, 404, 634, 864), ("raw 320x180 (masked)", "G0 center 224", "G1 letterbox 224", "G2 rect 288x176 (shown at 224 high)")):
        cv2.putText(head, t, (x, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.imwrite(str(out / "montage_g0_g1_g2.png"), cv2.cvtColor(np.vstack([head] + rows), cv2.COLOR_RGB2BGR))
    rep["montage_frames"] = table
    asp = [(t["g1_ball_WxH"], t["g2_ball_WxH"]) for t in table]
    def ratio(v):
        return None if v is None else v[1] / v[0]
    r1 = [ratio(a) for a, _ in asp if a and a[0] >= 10]
    r2 = [ratio(b) for _, b in asp if b and b[0] >= 10]
    rep["ball_aspect_h_over_w"] = {"g1": [round(min(r1), 3), round(max(r1), 3)] if r1 else None,
                                   "g2": [round(min(r2), 3), round(max(r2), 3)] if r2 else None,
                                   "frames_measured": [len(r1), len(r2)], "total_frames": len(table)}
    print("3. montage:", {k: len(v) for k, v in picks.items()}, "ball h/w in G1, G2 (range):",
          rep["ball_aspect_h_over_w"], flush=True)
    (out / "test_geometry.json").write_text(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
