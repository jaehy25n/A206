"""Where does our gripper actually sit on ROBOTIS's arm?

    python sim_umi/scripts/check_mount.py

Prints the chain

    official link5 (wrist)  ->  custom gripper root  ->  TCP

and compares the composed offset with the one the hardware description gives:
urdf/omx_f end_effector_joint, (0.09193, -0.0016, 0) in link5. The gripper's
internals are frozen; what mounting can still move is this transform, the
camera's world pose and the TCP's world pose, so all three are printed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "sim_umi", "src"))

import click
import mujoco
import numpy as np

from scene import SceneConfig, write_scene

URDF_EE_IN_LINK5 = np.array([0.09193, -0.0016, 0.0])
URDF_HINGE_1 = np.array([0.0295, 0.0075, 0.0])
URDF_HINGE_2 = np.array([0.0295, -0.0108, 0.0])


def pose_of(m, d, kind, name):
    if kind == "body":
        i = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name)
        return d.xpos[i].copy(), np.asarray(d.xmat[i]).reshape(3, 3).copy()
    i = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, name)
    return d.site_xpos[i].copy(), np.asarray(d.site_xmat[i]).reshape(3, 3).copy()


def rel(parent, child):
    (pp, pr), (cp, cr) = parent, child
    return pr.T @ (cp - pp), pr.T @ cr


@click.command()
def main():
    cfg = SceneConfig()
    m = mujoco.MjModel.from_xml_path(str(write_scene(cfg)))
    d = mujoco.MjData(m)
    mujoco.mj_resetData(m, d)
    mujoco.mj_forward(m, d)

    link5 = pose_of(m, d, "body", "link5")
    grip = pose_of(m, d, "body", "collector")
    tcp = pose_of(m, d, "site", "tcp")
    lf = pose_of(m, d, "body", "left_finger")
    rf = pose_of(m, d, "body", "right_finger")

    p, R = rel(link5, grip)
    click.secho("link5 (official wrist)  ->  collector (custom gripper root)",
                bold=True)
    click.echo(f"   translation {np.round(p*1000, 4)} mm")
    click.echo(f"   rotation\n{np.array2string(np.round(R, 6), prefix='      ')}")
    click.echo(f"   yaw {np.degrees(np.arctan2(R[1,0], R[0,0])):+.3f} deg")

    pg, _ = rel(grip, tcp)
    click.secho("\ncollector  ->  TCP", bold=True)
    click.echo(f"   translation {np.round(pg*1000, 4)} mm  "
               f"(config tcp_offset {np.round(np.array(cfg.tcp_offset)*1000, 4)})")

    p5, _ = rel(link5, tcp)
    click.secho("\nlink5  ->  TCP  (the composed chain)", bold=True)
    click.echo(f"   composed  {np.round(p5*1000, 4)} mm")
    click.echo(f"   urdf      {np.round(URDF_EE_IN_LINK5*1000, 4)} mm")
    err = np.linalg.norm(p5 - URDF_EE_IN_LINK5) * 1000
    click.secho(f"   error     {err:.4f} mm", bold=True,
                fg="green" if err < 0.01 else "red")

    click.secho("\nlink5  ->  finger hinges  (independent check of the mount)",
                bold=True)
    for name, got, want in (("gripper_joint_1", rel(link5, lf)[0], URDF_HINGE_1),
                            ("gripper_joint_2", rel(link5, rf)[0], URDF_HINGE_2)):
        e = np.linalg.norm(got - want) * 1000
        click.secho(f"   {name}: composed {np.round(got*1000, 4)} mm  "
                    f"urdf {np.round(want*1000, 4)} mm  error {e:.4f} mm",
                    fg="green" if e < 0.01 else "red")

    cam = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
    cpos = d.cam_xpos[cam].copy()
    cmat = np.asarray(d.cam_xmat[cam]).reshape(3, 3)
    click.secho("\ncamera extrinsic -- unchanged inside the gripper, moved in "
                "the world by the mount", bold=True)
    click.echo(f"   camera in the gripper frame {np.round(grip[1].T @ (cpos - grip[0]) * 1000, 3)} mm")
    click.echo(f"   camera in the world         {np.round(cpos, 5)} m")
    click.echo(f"   TCP in the world            {np.round(tcp[0], 5)} m")
    click.echo(f"   camera look direction (world) {np.round(-cmat[:, 2], 4)}")


if __name__ == "__main__":
    main()
