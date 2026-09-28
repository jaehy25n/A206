"""The ORACLE target / EE mask renderer -- one implementation for the prep sidecar
(build_oracle_masks.py) and for the mask-capable evaluator (dse_rollout_masks.py).

MuJoCo segmentation of the wrist camera of the plant's own model
(collector_scene.xml), rendered WITHOUT multisampling so every pixel is its
centre's geom; a depth render back-projects the finger pixels into their own
finger's body frame for the fingertip band. Masks are made at 320x180 and
carried through the G0 geometry (oracle_masks.g0_mask, nearest).

    target_mask      geom object_geom
    ee_gripper_mask  every geom of bodies left_finger, right_finger
    ee_tip_mask      ee_gripper_mask pixels with finger-frame y >= TIP_Y0 (50 mm), on the
                     rounded-mm y map, so ee_finger_y_mm and ee_tip_mask agree exactly
    ee_finger_y_mm   finger-frame y (mm) of every gripper pixel, 0 elsewhere

ORACLE: simulator ground truth; never a deployment input.
"""
import os

import numpy as np

import oracle_masks as OM

TIP_Y0 = 0.050
# the finger mesh's box in its body frame (-10.1..10.1, -10.1..65.0, -21.3..21.3 mm), +3 mm
FINGER_BOX_LO = np.array([-0.0131, -0.0131, -0.0243])
FINGER_BOX_HI = np.array([0.0131, 0.068, 0.0243])
ARM = [f"joint{i}" for i in range(1, 6)]
FREE_SUFFIX = ("x", "y", "z", "qw", "qx", "qy", "qz")


class OracleRenderer:
    def __init__(self):
        os.environ.setdefault("MUJOCO_GL", "egl")
        import mujoco
        from collector import Collector
        from scene import SceneConfig
        import oracle_state
        self.mujoco = mujoco
        k = Collector(str(oracle_state.MODEL_XML), cfg=SceneConfig(), render=False)
        m = k.model
        W, H = OM.RAW_WH
        # Segmentation and depth WITHOUT multisampling: with the model's 4x MSAA the
        # colour-coded ids of two geoms meeting at an edge blend into the code of a
        # third, unrelated geom. The RGB mirror keeps the model's own setting, as the plant.
        samples = int(m.vis.quality.offsamples)
        m.vis.quality.offsamples = 0
        self.seg = mujoco.Renderer(m, height=H, width=W); self.seg.enable_segmentation_rendering()
        self.dep = mujoco.Renderer(m, height=H, width=W); self.dep.enable_depth_rendering()
        m.vis.quality.offsamples = samples
        self.rgb = mujoco.Renderer(m, height=H, width=W)

        def body_geoms(n):
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)
            return list(range(m.body_geomadr[b], m.body_geomadr[b] + m.body_geomnum[b]))
        self.k, self.m = k, m
        self.S = oracle_state.DemoState(k)
        self.d = mujoco.MjData(m)
        self.obj = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "object_geom")]
        self.lf, self.rf = body_geoms("left_finger"), body_geoms("right_finger")
        self.tips = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n) for n in ("left_tip_patch", "right_tip_patch")]
        self.lb = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "left_finger")
        self.rb = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "right_finger")
        self.cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
        self.f = 0.5 * H / np.tan(np.radians(m.cam_fovy[self.cid]) / 2)
        self.geom_t = int(mujoco.mjtObj.mjOBJ_GEOM)
        self.u = (np.arange(W) + 0.5 - W / 2) / self.f
        self.v = -(np.arange(H) + 0.5 - H / 2) / self.f

    def render(self, d):
        """Masks of the state posed in MjData d (kinematics + camera poses done)."""
        import cv2
        self.seg.update_scene(d, camera="wrist"); sg = self.seg.render()
        self.dep.update_scene(d, camera="wrist"); dp = self.dep.render()
        self.rgb.update_scene(d, camera="wrist"); im = self.rgb.render()
        ids = np.where(sg[:, :, 1] == self.geom_t, sg[:, :, 0], -1)
        tgt = np.isin(ids, self.obj)
        left, right = np.isin(ids, self.lf), np.isin(ids, self.rf)
        grip = left | right
        # surface points of the finger pixels in their own finger's frame
        cp, cR = d.cam_xpos[self.cid], d.cam_xmat[self.cid].reshape(3, 3)
        pts = np.stack([self.u[None, :] * dp, self.v[:, None] * dp, -dp], -1) @ cR.T + cp
        fy = np.zeros(grip.shape, np.float64)
        off_box = 0
        for msk, b in ((left, self.lb), (right, self.rb)):
            if msk.any():
                loc = (pts[msk] - d.xpos[b]) @ d.xmat[b].reshape(3, 3)
                fy[msk] = loc[:, 1]
                off_box += int(((loc < FINGER_BOX_LO) | (loc > FINGER_BOX_HI)).any(1).sum())
        ymap = np.where(grip, np.clip(np.round(fy * 1000), 1, 255), 0).astype(np.uint8)
        tip = grip & (ymap >= round(TIP_Y0 * 1000))          # on the stored mm, so the two agree exactly
        yout = cv2.resize(np.ascontiguousarray(ymap[:, OM.G0_X0:OM.G0_X0 + OM.G0_SIDE]), (OM.G0_OUT, OM.G0_OUT),
                          interpolation=cv2.INTER_NEAREST)
        raw = {"target_mask": tgt, "ee_gripper_mask": grip, "ee_tip_mask": tip}
        g0 = {name: OM.g0_mask(mk) for name, mk in raw.items()}
        return {"ids": ids, "pts": pts, "im": im, "raw": raw, "g0": g0, "ymap_g0": yout, "off_box": off_box}

    def pose_from_joint_state(self, js):
        """Pose the mirror from one joint snapshot of the (patched) camera plugin: hinge
        joints by name, free joints from their <name>/x..qz entries. Returns what was set."""
        mujoco, m, d, k = self.mujoco, self.m, self.d, self.k
        pos = dict(zip(list(js.name), list(js.position)))
        missing = [n for n in ARM if n not in pos]
        for a, n in zip(k.arm_qadr, ARM):
            if n in pos:
                d.qpos[a] = pos[n]
        for j in range(m.njnt):
            n = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or ""
            if n.startswith("gripper_joint") and n in pos:
                d.qpos[m.jnt_qposadr[j]] = pos[n]
            if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE:
                # the plugin names a free joint by its body (the joints are unnamed)
                n = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.jnt_bodyid[j])
                keys = [f"{n}/{s}" for s in FREE_SUFFIX]
                if all(x in pos for x in keys):
                    d.qpos[m.jnt_qposadr[j]:m.jnt_qposadr[j] + 7] = [pos[x] for x in keys]
                else:
                    missing.append(n)
        mujoco.mj_kinematics(m, d)
        mujoco.mj_camlight(m, d)
        return {"missing": missing}
