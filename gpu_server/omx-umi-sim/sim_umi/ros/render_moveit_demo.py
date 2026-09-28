"""Turn the recorded /joint_states into video.

    python sim_umi/ros/render_moveit_demo.py

mujoco_ros2_control 0.0.3 has no camera plugin, so the pictures are made here:
the SAME MJCF is loaded, the arm and jaw are driven to the joint positions the
live run reported, and physics carries the object and the bin. The joint
numbers are measurements from the run, not a re-plan -- what is re-simulated is
only what the object did in response to them.

Writes outputs/moveit_demo.mp4 (overview beside the wrist camera) and
outputs/moveit_demo.png.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim_umi" / "src"))

import click
import cv2
import mujoco
import numpy as np

SIM = ROOT / "sim_umi"
ARM = [f"joint{i}" for i in range(1, 6)]


@click.command()
@click.option("--rec", default=str(SIM / "outputs" / "moveit_demo.npz"))
@click.option("--fps", default=20, type=int)
@click.option("--name", default="moveit_demo")
def main(rec, fps, name):
    d = np.load(rec, allow_pickle=True)
    t, names, q = d["t"], [str(x) for x in d["names"]], d["q"]
    # the pick recording labels its stages differently from the first demo
    if "marks" in d:
        marks = [(int(s.split(":")[0]), ":".join(s.split(":")[1:])) for s in d["marks"]]
    else:
        marks = []
    m = mujoco.MjModel.from_xml_path(str(SIM / "mjcf" / "collector_scene.xml"))
    data = mujoco.MjData(m)
    mujoco.mj_resetData(m, data)

    idx = {j: names.index(j) for j in ARM if j in names}
    jaw_i = names.index("gripper_joint_1") if "gripper_joint_1" in names else None
    acts = {j: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_ACTUATOR, j) for j in ARM}
    jaw_a = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_ACTUATOR, "gripper_joint_1")
    obj = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "object")

    rend = mujoco.Renderer(m, height=480, width=640)
    wrist = mujoco.Renderer(m, height=360, width=480)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.azimuth, cam.elevation, cam.distance = 125.0, -22.0, 1.05
    cam.lookat[:] = (-0.02, -0.20, 0.10)

    label_at = {i: l for i, l in marks}
    current = ""
    frames = []
    step_dt = m.opt.timestep
    for k in range(1, len(t)):
        if k in label_at:
            current = label_at[k]
        for j in ARM:
            data.ctrl[acts[j]] = float(q[k][idx[j]])
        if jaw_i is not None:
            data.ctrl[jaw_a] = float(q[k][jaw_i])
        n = max(1, int(round((t[k] - t[k - 1]) / step_dt)))
        for _ in range(min(n, 60)):
            mujoco.mj_step(m, data)
        if k % max(1, int(len(t) / (fps * t[-1]))) :
            continue
        rend.update_scene(data, cam)
        left = rend.render().copy()
        wrist.update_scene(data, camera="wrist")
        right = wrist.render().copy()
        pane = np.zeros((480, 640 + 480, 3), np.uint8)
        pane[:, :640] = left
        pane[:360, 640:] = right
        jaw_mm = float(np.linalg.norm(
            data.site_xpos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "left_inner")]
            - data.site_xpos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "right_inner")])) * 1000
        lines = [f"MoveIt -> arm_controller -> ros2_control -> MuJoCo   t={t[k]:5.1f}s",
                 f"{current}",
                 f"jaw {jaw_mm:5.1f} mm    object z {data.xpos[obj][2]*1000:5.1f} mm"]
        for i, s in enumerate(lines):
            for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                cv2.putText(pane, s, (10, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, col, th, cv2.LINE_AA)
        for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
            cv2.putText(pane, "camera0_rgb (wrist)", (650, 380),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, th, cv2.LINE_AA)
        frames.append(pane)
    rend.close()
    wrist.close()

    out = SIM / "outputs" / f"{name}.mp4"
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    vw.release()
    strip = np.concatenate([frames[len(frames) * i // 6] for i in (1, 2, 3, 4, 5)],
                           axis=0)
    cv2.imwrite(str(SIM / "outputs" / f"{name}.png"),
                cv2.cvtColor(strip, cv2.COLOR_RGB2BGR))
    click.echo(f"{len(frames)} frames -> {out}")


if __name__ == "__main__":
    main()
