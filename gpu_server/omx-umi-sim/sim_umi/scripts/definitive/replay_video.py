"""Replay one evaluated episode from its log as a video -- the episode itself,
not a re-run.

    MUJOCO_GL=egl python sim_umi/scripts/definitive/replay_video.py \
        <rollout.json> <episode> <out.mp4> [--title "..."]

Left: a fixed camera facing the robot, on the kinematics copy, posed from the
logged joints, the logged true jaw width and the logged true ball position.
Middle: a close-up that follows the tool, side-on to the arm's plane from the
side away from the bin, so insertion depth and height against the ball show.
Right: the policy's input as the bridge builds it -- wrist frame, magenta
tip patches painted out with mask_magenta(TipDetectorConfig()), centre
square, 224 px -- computed from the wrist camera RE-RENDERED at the logged
state, because the live frames were not saved. Checked against a live frame
saved at an evaluation start: the unmasked re-render matched it to 1.9/255
mean absolute difference, magenta pixels in the same places. The bin is drawn
at its placement; its pose over time is not in the log.

Overlay: time, stage, tool pitch, true jaw width, ball rise, the ball in the
tool frame against the expert's closing corridor, whether the object is in
the crop (pixels), and the plan in force: waypoints sent, or nothing
sendable and how far into the 8-plan abort count.
"""
import json
import math
import pathlib
import subprocess
import sys

import click
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(SIM / "src"), str(SIM / "scripts"), str(SIM / "scripts" / "definitive")]

import mujoco  # noqa: E402

from aggregate import EXPERT, load  # noqa: E402

FPS = 20
W, H = 480, 480


def label(img, lines, org=(8, 8), scale=0.45, line_h=17):
    """White text on a translucent dark box -- an outline drawn thicker than
    the glyphs left ghost copies after compression."""
    import cv2
    wmax = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] for t in lines) + 10
    h = line_h * len(lines) + 8
    x0, y0 = org
    x1, y1 = min(img.shape[1], x0 + wmax), min(img.shape[0], y0 + h)
    img[y0:y1, x0:x1] = (img[y0:y1, x0:x1] * 0.35).astype(img.dtype)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (x0 + 5, y0 + 4 + line_h * (i + 1) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


@click.command()
@click.argument("rollout")
@click.argument("episode", type=int)
@click.argument("out")
@click.option("--title", default="")
def main(rollout, episode, out, title):
    import cv2
    from collector import Collector
    from gripper_vision import TipDetectorConfig, mask_magenta
    from scene import SceneConfig
    d = load(rollout)
    cols = d["ee_track_columns"]
    ci = {c: i for i, c in enumerate(cols)}
    e = next(x for x in d["episodes"] if x["episode"] == episode)
    split = d.get("from_demos", "train")
    spec = json.loads(str(np.load(sorted((SIM / "data" / "demos" / split).glob("episode_*.npz"))[episode],
                                  allow_pickle=True)["spec"]))
    cfg = SceneConfig()
    k = Collector(str(SIM / "mjcf" / "collector_scene.xml"), cfg=cfg, render=False)
    m, dd = k.model, k.data
    gjs = [m.jnt_qposadr[j] for j in range(m.njnt)
           if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or "").startswith("gripper_joint")]
    yaw = float(spec["bin_yaw"])
    dd.qpos[k.bin_qadr:k.bin_qadr + 7] = [spec["bin_xy"][0], spec["bin_xy"][1], 0.0,
                                          math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    dd.qpos[k.obj_qadr + 3:k.obj_qadr + 7] = [1, 0, 0, 0]
    ball_r = float(spec["ball_r"]) * 1000

    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    # facing the robot across the workspace, so the arm does not hide the ball
    cam.azimuth, cam.elevation, cam.distance = -70.0, -32.0, 0.85
    cam.lookat[:] = (0.0, -0.22, 0.05)
    ren = mujoco.Renderer(m, height=H, width=W)
    near = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(near)
    near.elevation, near.distance = -8.0, 0.30
    lo_deg = np.degrees(k.arm_range[:, 0])
    hi_deg = np.degrees(k.arm_range[:, 1])
    pvx, pvy = k.arm_pivot_xy
    cw, ch = cfg.wrist_cam_resolution
    wren = mujoco.Renderer(m, height=ch, width=cw)
    sren = mujoco.Renderer(m, height=ch, width=cw)
    sren.enable_segmentation_rendering()
    side = min(cw, ch)
    x0 = (cw - side) // 2
    y0 = (ch - side) // 2
    tip_cfg = TipDetectorConfig()          # what policy_bridge uses
    magenta_left = 0
    obj_bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "object")
    obj_g = set(range(m.body_geomadr[obj_bid], m.body_geomadr[obj_bid] + m.body_geomnum[obj_bid]))

    tk = np.array([[np.nan if v is None else v for v in r] for r in e["ee_track"]], float)
    T = tk[:, ci["stamp_s"]]
    ev = e.get("stage_events", [])
    plans = e["trace"]
    pl_t = np.array([p["obs_t_s"] for p in plans])
    # abort count at each plan: consecutive plans with nothing sendable
    run, cnt = [], 0
    for p in plans:
        cnt = cnt + 1 if p["valid_prefix"] == 0 else 0
        run.append(cnt)
    ex_lat, ex_dep, ex_ver, ex_pit = EXPERT["lateral"], EXPERT["depth"], EXPERT["vertical"], EXPERT["pitch"]

    tmp = pathlib.Path(out).with_suffix(".raw.mp4")
    vw = None
    n = 0
    for t in np.arange(T[0], T[-1], 1.0 / FPS):
        i = int(np.searchsorted(T, t))
        i = min(i, len(T) - 1)
        row = tk[i]
        q = np.radians(row[ci["j1_deg"]:ci["j1_deg"] + 5])
        for a, v in zip(k.arm_qadr, q):
            dd.qpos[a] = v
        jaw = row[ci["jaw_gt_mm"]]
        if not np.isnan(jaw):
            th = float(np.interp(jaw / 1000.0, k._width_tab, k._theta_tab))
            for a in gjs:
                dd.qpos[a] = th
        ball = row[ci["ball_x_mm"]:ci["ball_x_mm"] + 3]
        if not np.isnan(ball).any():
            dd.qpos[k.obj_qadr:k.obj_qadr + 3] = ball / 1000.0
        mujoco.mj_forward(m, dd)
        ren.update_scene(dd, cam)
        left = ren.render().copy()
        tcp = dd.site_xpos[k.tcp_sid].copy()
        tgt = tcp if np.isnan(ball).any() else 0.5 * (tcp + ball / 1000.0)
        near.lookat[:] = tgt
        # side-on to the arm's plane, from whichever side the bin is not on
        phi = math.atan2(tcp[1] - pvy, tcp[0] - pvx)
        bxy = np.array(spec["bin_xy"])
        best = None
        for az in (phi + math.pi / 2, phi - math.pi / 2):
            cam_xy = tgt[:2] - near.distance * np.array([math.cos(az), math.sin(az)])
            dist = float(np.linalg.norm(cam_xy - bxy))
            if best is None or dist > best[0]:
                best = (dist, az)
        near.azimuth = math.degrees(best[1])
        ren.update_scene(dd, near)
        mid = ren.render().copy()
        wren.update_scene(dd, camera="wrist")
        wimg = wren.render()
        sren.update_scene(dd, camera="wrist")
        seg = sren.render()[:, :, 0]
        px = int(np.isin(seg[y0:y0 + side, x0:x0 + side], list(obj_g)).sum())
        # policy_bridge.observe: mask_magenta on the full frame, then
        # preprocess_rgb's centre square and INTER_AREA resize to 224
        masked = mask_magenta(wimg, tip_cfg)
        hsv = cv2.cvtColor(masked, cv2.COLOR_RGB2HSV)
        magenta_left = max(magenta_left, int(((hsv[..., 0] > 135) & (hsv[..., 0] < 170)
                                              & (hsv[..., 1] > 100) & (hsv[..., 2] > 80)).sum()))
        crop = masked[y0:y0 + side, x0:x0 + side]
        right = cv2.resize(cv2.resize(crop, (224, 224), interpolation=cv2.INTER_AREA),
                           (H, H), interpolation=cv2.INTER_NEAREST).copy()
        p_tcp = dd.site_xpos[k.tcp_sid].copy()
        R = np.asarray(dd.site_xmat[k.tcp_sid]).reshape(3, 3)
        off = R.T @ (ball / 1000.0 - p_tcp) * 1000 if not np.isnan(ball).any() else np.full(3, np.nan)
        pit = row[ci["pitch_deg"]]
        stage = ev[0]["stage"] if ev else "?"
        for x in ev:
            if x["t"] <= t:
                stage = x["stage"]
        j = int(np.searchsorted(pl_t, t, side="right")) - 1
        if j >= 0:
            p = plans[j]
            plan_s = (f"plan {j}: sent {p['valid_prefix']} of 8"
                      if p["valid_prefix"] > 0 else f"plan {j}: NOTHING SENDABLE  abort count {run[j]}/8")
            if p["first_unreachable_k"] is not None and p["valid_prefix"] > 0:
                plan_s += f"  (refused from k={p['first_unreachable_k']})"
        else:
            plan_s = "plan --"
        ins = (ex_dep[1] <= off[1] <= ex_dep[2] and ex_lat[1] <= off[0] <= ex_lat[2]
               and ex_ver[1] <= off[2] <= ex_ver[2] and ex_pit[1] <= pit <= ex_pit[2])
        qd = np.degrees(q)
        marg = [min(qd[j] - lo_deg[j], hi_deg[j] - qd[j]) for j in (1, 2, 3)]
        rb = (math.hypot(ball[0] / 1000 - pvx, ball[1] / 1000 - pvy) * 1000
              if not np.isnan(ball).any() else float("nan"))
        label(left, [f"{title}",
                     f"t {t - T[0]:5.1f} s   {stage}",
                     f"pitch {pit:5.1f} deg (expert close {ex_pit[0]:.1f})",
                     f"jaw {jaw:5.1f} mm (true)   ball rise {ball[2] - ball_r:6.1f} mm",
                     f"ball {rb:5.0f} mm from base (reach ~396 at table)",
                     f"j2 {qd[1]:+6.1f} ({marg[0]:4.1f} to limit)  j3 {qd[2]:+6.1f} ({marg[1]:4.1f})",
                     f"j4 {qd[3]:+6.1f} ({marg[2]:4.1f})   limits j2/j3 -120..+90, j4 +-100",
                     plan_s])
        label(mid, ["close-up, side-on to the arm",
                    f"ball in tool frame (mm): lat {off[0]:+5.1f} depth {off[1]:+5.1f} vert {off[2]:+5.1f}",
                    f"expert close:            lat {ex_lat[0]:+5.1f} depth {ex_dep[0]:+5.1f} vert {ex_ver[0]:+5.1f}",
                    "IN EXPERT CORRIDOR" if ins else "outside expert corridor"])
        label(right, ["policy input: tips masked, 224 crop (upscaled)",
                      "wrist frame re-rendered from the log",
                      f"object in crop: {px} px"])
        frame = np.hstack([left, mid, right])
        if vw is None:
            vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS,
                                 (frame.shape[1], frame.shape[0]))
        vw.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        n += 1
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "23", str(out)], check=True)
    tmp.unlink()
    click.echo(f"wrote {out} ({n} frames, {n / FPS:.1f} s); "
               f"magenta pixels left after masking, max over frames: {magenta_left}")


if __name__ == "__main__":
    main()
