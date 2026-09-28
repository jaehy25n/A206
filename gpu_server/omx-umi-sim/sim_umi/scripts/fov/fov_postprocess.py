"""FOV diagnostics after the rollout, never during it.

    MUJOCO_GL=egl python sim_umi/scripts/fov/fov_postprocess.py <rollout.json> [...]

For every plan, the ground truth at the moment of its last observation frame
is taken from the log -- arm joints, true jaw width and ball position from
ee_track (nearest stamp), the bin's pose from the plan's own bin_gt record --
posed on the kinematics copy, and the wrist camera's segmentation is rendered:
object, finger bodies, tip patches. fov_diag carries those masks through the
exact geometry the run's policy used and every other one. The result is written
back into the plan's obs record as "fov", in a new file <rollout>.fov.json; the
rollout file itself is not modified.

Run only when no evaluation is running: rendering competes for the GPU the
policy server infers on.
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(SIM / "src"), str(SIM / "scripts" / "definitive")]
import click
import mujoco
import numpy as np

import fov_diag
from aggregate import load


@click.command()
@click.argument("rollouts", nargs=-1, required=True)
def main(rollouts):
    from collector import Collector
    from scene import SceneConfig
    cfg = SceneConfig()
    k = Collector(str(SIM / "mjcf" / "collector_scene.xml"), cfg=cfg, render=False)
    m, d = k.model, k.data
    cw, ch = cfg.wrist_cam_resolution
    ren = mujoco.Renderer(m, height=ch, width=cw)
    ren.enable_segmentation_rendering()
    gj = [m.jnt_qposadr[j] for j in range(m.njnt)
          if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or "").startswith("gripper_joint")]

    def body_geoms(names):
        ids = set()
        for n in names:
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)
            ids |= set(range(m.body_geomadr[b], m.body_geomadr[b] + m.body_geomnum[b]))
        return ids
    groups = {"object": body_geoms(["object"]), "gripper": body_geoms(["left_finger", "right_finger"]),
              "tips": {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n) for n in ("left_tip_patch", "right_tip_patch")}}
    for f in rollouts:
        R = load(f)
        geometry = R.get("rgb_geometry") or "g0_center224"
        cols = R["ee_track_columns"]
        ci = {c: i for i, c in enumerate(cols)}
        n_done = 0
        for e in R["episodes"]:
            tk = np.array([[np.nan if v is None else v for v in r] for r in e["ee_track"]], float)
            T = tk[:, ci["stamp_s"]]
            for pl in e["trace"]:
                o = pl.get("obs") or {}
                fr = o.get("frames") or []
                t = fr[-1]["image_stamp_s"] if fr else pl["obs_t_s"]
                i = int(np.argmin(np.abs(T - t)))
                row = tk[i]
                for a, v in zip(k.arm_qadr, np.radians(row[ci["j1_deg"]:ci["j1_deg"] + 5])):
                    d.qpos[a] = v
                jaw = row[ci["jaw_gt_mm"]]
                if not np.isnan(jaw):
                    th = float(np.interp(jaw / 1000.0, k._width_tab, k._theta_tab))
                    for a in gj:
                        d.qpos[a] = th
                ball = row[ci["ball_x_mm"]:ci["ball_x_mm"] + 3]
                if not np.isnan(ball).any():
                    d.qpos[k.obj_qadr:k.obj_qadr + 3] = ball / 1000.0
                bg = o.get("bin_gt")
                if bg:
                    x, y, z, w = bg["quat_xyzw"]
                    d.qpos[k.bin_qadr:k.bin_qadr + 7] = [*(np.array(bg["xyz_mm"]) / 1000.0), w, x, y, z]
                mujoco.mj_forward(m, d)
                ren.update_scene(d, camera="wrist")
                seg = ren.render()
                ids, is_geom = seg[:, :, 0], seg[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
                masks = {g: np.isin(ids, list(v)) & is_geom for g, v in groups.items()}
                o["fov"] = fov_diag.diagnostics(masks, geometry)
                o["fov"]["state_dt_s"] = round(float(T[i] - t), 4)
                o["fov"]["bin_pose_logged"] = bool(bg)
                pl["obs"] = o
                n_done += 1
        out = pathlib.Path(str(f).replace(".json.gz", ".json").replace(".json", ".fov.json"))
        out.write_text(json.dumps(R))
        print(f"{f}: {n_done} plans -> {out}", flush=True)
    ren.close()


if __name__ == "__main__":
    main()
