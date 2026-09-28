"""The simulator state of every demo frame, rebuilt from what the demo recorded.

ORACLE / evaluation-side only: nothing here is a policy input.

A demo row stores the TCP pose (FK of /joint_states at the image instant), the
true jaw width at that instant, the ball position and the episode spec, but not
the joint angles. The five arm joints are recovered by Gauss-Newton on the TCP
site of the same model the plant runs (collector_scene.xml), warm-started from
the previous frame (frame 0 from the recorded home q), so the solution stays on
the branch the arm actually moved along; the jaw angle by inverting the model's
own angle->width table; the bin from the spec (it is a free body placed at z 0
and never touched by the expert). The residuals are returned for every frame so
a caller can gate on them.
"""
import json
import pathlib

import mujoco
import numpy as np

SIM = pathlib.Path(__file__).resolve().parents[1]
MODEL_XML = SIM / "mjcf" / "collector_scene.xml"


class DemoState:
    def __init__(self, collector):
        self.k = collector
        m = collector.model
        self.m = m
        self.gripper_qadr = [m.jnt_qposadr[j] for j in range(m.njnt)
                             if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or "").startswith("gripper_joint")]
        self._d = mujoco.MjData(m)
        self._jp = np.zeros((3, m.nv))
        self._jr = np.zeros((3, m.nv))

    def ik(self, pos, R, q0, max_iter=50):
        m, d, k = self.m, self._d, self.k
        for a, v in zip(k.arm_qadr, q0):
            d.qpos[a] = v
        for it in range(max_iter):
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            ep = pos - d.site_xpos[k.tcp_sid]
            Rc = d.site_xmat[k.tcp_sid].reshape(3, 3)
            er = 0.5 * sum(np.cross(Rc[:, c], R[:, c]) for c in range(3))
            mujoco.mj_jacSite(m, d, self._jp, self._jr, k.tcp_sid)
            J = np.vstack([self._jp[:, k.arm_dofs], self._jr[:, k.arm_dofs]])
            dq = np.linalg.lstsq(J, np.r_[ep, er], rcond=None)[0]
            for i, a in enumerate(k.arm_qadr):
                d.qpos[a] += dq[i]
            if np.linalg.norm(dq) < 1e-10:
                break
        mujoco.mj_kinematics(m, d)
        Rc = d.site_xmat[k.tcp_sid].reshape(3, 3)
        pos_err = float(np.linalg.norm(pos - d.site_xpos[k.tcp_sid]))
        rot_err = float(np.degrees(np.arccos(np.clip((np.trace(Rc.T @ R) - 1) / 2, -1, 1))))
        return np.array([d.qpos[a] for a in k.arm_qadr]), pos_err, rot_err, it + 1

    def reconstruct(self, npz_path):
        z = np.load(npz_path, allow_pickle=True)
        spec = json.loads(str(z["spec"]))
        n = len(z["t"])
        q = z["eval_home_q"].astype(np.float64)[:5]
        Q = np.zeros((n, 5))
        res = np.zeros((n, 3))
        for i in range(n):
            q, pe, re, it = self.ik(z["eef_pos"][i].astype(np.float64), z["eef_rot"][i].astype(np.float64), q)
            Q[i], res[i] = q, (pe, re, it)
        w = z["eval_gripper_width_gt"].astype(np.float64).reshape(-1)
        theta = np.interp(w, self.k._width_tab, self.k._theta_tab)
        yaw = spec["bin_yaw"]
        bin_pose = np.array([spec["bin_xy"][0], spec["bin_xy"][1], 0.0,
                             np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])
        return {"q": Q, "ik_pos_err_m": res[:, 0], "ik_rot_err_deg": res[:, 1], "ik_iters": res[:, 2],
                "gripper_theta": theta, "ball_pos": z["eval_ball_pos"].astype(np.float64),
                "bin_pose": bin_pose, "spec": spec}

    def pose(self, d, q, theta, ball, bin_pose):
        """Put one frame's state into MjData `d` (kinematics + camera poses)."""
        k = self.k
        for a, v in zip(k.arm_qadr, q):
            d.qpos[a] = v
        for a in self.gripper_qadr:
            d.qpos[a] = theta
        if np.all(np.isfinite(ball)):
            d.qpos[k.obj_qadr:k.obj_qadr + 3] = ball
            d.qpos[k.obj_qadr + 3:k.obj_qadr + 7] = [1.0, 0.0, 0.0, 0.0]
        d.qpos[k.bin_qadr:k.bin_qadr + 7] = bin_pose
        mujoco.mj_kinematics(self.m, d)
        mujoco.mj_camlight(self.m, d)
