"""Parameterised scripted pick-and-place in the virtual-collector scene.

`collect_scripted.py` hard-codes one trajectory: the object sits at
[0, 0.28, 0.025], every waypoint has x = 0, and `mocap_quat` is held at
identity. That makes six of the ten action dimensions and the x axis exactly
constant in the dataset -- there is nothing in those axes for a policy to learn,
and nothing to test it on.

Here the object pose is an input. Waypoints are derived from it, and the
collector yaws to meet the object, so px and the rot6d dimensions carry real
signal.

Geometry: the TCP site sits at [0, 0.18, -0.035] in the collector's frame, and
at rest its world position is exactly the object's. So to put the TCP at some
world point with some yaw:

    collector_pos = tcp_world - R_z(yaw) @ tcp_offset
"""
import dataclasses
import json
import math
import pathlib
from typing import Dict, Optional, Tuple

import json

import mujoco
import numpy as np

from gripper_vision import TipDetectorConfig, detect_tips, mask_magenta

RECORD_HZ = 30.0


@dataclasses.dataclass
class EpisodeSpec:
    """One demonstration, in the table-centre frame (see scene.py)."""
    object_xy: Tuple[float, float] = (-0.12, -0.22)
    object_yaw: float = 0.0
    object_type: str = "box"
    object_size_xy: float = 0.010                 # half-width in the jaw axis
    bin_xy: Tuple[float, float] = (0.10, -0.12)
    bin_yaw: float = 0.0
    approach_yaw: float = 0.0                     # yaw the episode starts from
    carry_z: float = 0.20                         # clears the 120 mm bin rim
    release_z: float = 0.055                      # inside the bin; the gripper
                                                  # is 92 mm across and the
                                                  # opening is 114 mm, so it can
                                                  # be lowered in and let go
    grasp_z: float = 0.010
    #: How much narrower than the object the jaw is commanded. Commanding a
    #: full close on a 50 mm block asks the fingers to travel 40 mm through it;
    #: the position actuator obliges and squirts it out sideways. A real
    #: gripper is told a width, so this one is too.
    grasp_squeeze: float = 0.006
    seed: int = 0

    def to_meta(self) -> Dict[str, object]:
        return {
            "object_type": self.object_type,
            "object_x": round(self.object_xy[0], 5),
            "object_y": round(self.object_xy[1], 5),
            "object_yaw_deg": round(math.degrees(self.object_yaw), 3),
            "bin_x": round(self.bin_xy[0], 5),
            "bin_y": round(self.bin_xy[1], 5),
            "bin_yaw_deg": round(math.degrees(self.bin_yaw), 3),
            "approach_yaw_deg": round(math.degrees(self.approach_yaw), 3),
            "seed": self.seed,
        }

    @property
    def arrangement(self) -> str:
        """Coarse label for the relative layout, for failure analysis."""
        dx = self.bin_xy[0] - self.object_xy[0]
        dy = self.bin_xy[1] - self.object_xy[1]
        lr = "bin_right" if dx > 0.05 else "bin_left" if dx < -0.05 else "bin_centre"
        nf = "bin_far" if dy > 0.05 else "bin_near" if dy < -0.05 else "bin_same"
        return f"{lr}/{nf}"


def yaw_quat(yaw: float) -> np.ndarray:
    """wxyz, MuJoCo order."""
    return np.array([math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)])


def rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class Collector:
    """Holds the model once; `run()` may be called repeatedly."""

    #: 16:9, because the collector's own camera is: metadata.json gives
    #: 1920x1080 with fx 1491.89, which is 65.5 deg across and 39.8 deg down.
    #: At 4:3 the raw frame was 51.5 deg across -- 14 deg narrower than the
    #: hardware it is imitating. The policy input is unaffected either way
    #: (a centre square at the same vertical FOV is the same square), but the
    #: raw stream is what everything else is measured on.
    def __init__(self, xml_path: str, cfg=None, width: int = 320, height: int = 180,
                 render: bool = True):
        self.cfg = cfg
        self.model = mujoco.MjModel.from_xml_path(str(xml_path))
        self.data = mujoco.MjData(self.model)
        # render=False is for callers that only want the kinematics -- FK, the
        # jaw table, the IK. The policy bridge is one: its pictures come from
        # the plant's own camera topic now, not from a second model.
        self.renderer = (mujoco.Renderer(self.model, height=height, width=width)
                         if render else None)

        def _id(t, n):
            i = mujoco.mj_name2id(self.model, t, n)
            if i < 0:
                raise RuntimeError(f"missing {n}")
            return i

        self.object_bid = _id(mujoco.mjtObj.mjOBJ_BODY, "object")
        self.bin_bid = _id(mujoco.mjtObj.mjOBJ_BODY, "bin")
        self.finger_bids = [_id(mujoco.mjtObj.mjOBJ_BODY, b)
                            for b in ("left_finger", "right_finger")]
        self.collector_bid = _id(mujoco.mjtObj.mjOBJ_BODY, "collector")
        #: Sample points on the gripper, in each geom's own frame, used for
        #: the clearance measure: every vertex of both finger MESHES plus the
        #: eight corners of every collision pad. The mesh is what the video
        #: shows, and it is wider than the seven-box pad stack, so a sweep that
        #: clears every pad can still cut a wall on screen.
        self.clearance_pts = []
        mm = self.model
        for g in range(mm.ngeom):
            if mm.geom_bodyid[g] not in self.finger_bids:
                continue
            if mm.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
                mid = mm.geom_dataid[g]
                a = mm.mesh_vertadr[mid]
                n = mm.mesh_vertnum[mid]
                self.clearance_pts.append((g, mm.mesh_vert[a:a + n].astype(float)))
            elif mm.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX:
                sx, sy, sz = mm.geom_size[g]
                self.clearance_pts.append((g, np.array(
                    [[i * sx, j * sy, k * sz]
                     for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)], float)))
        self.bin_box_gids = [g for g in range(mm.ngeom)
                             if mm.geom_bodyid[g] == self.bin_bid
                             and mm.geom_contype[g]
                             and mm.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX]
        #: Anything further than this is reported as this. Nothing is decided
        #: on a large clearance, only on a small or negative one.
        self.clearance_cap = 0.05
        self.tcp_sid = _id(mujoco.mjtObj.mjOBJ_SITE, "tcp")
        self.left_sid = _id(mujoco.mjtObj.mjOBJ_SITE, "left_inner")
        self.right_sid = _id(mujoco.mjtObj.mjOBJ_SITE, "right_inner")
        # one actuator now, on the tendon, as ros2_control requires
        self.left_act = self.right_act = _id(
            mujoco.mjtObj.mjOBJ_ACTUATOR, "gripper_joint_1")
        # Two ways to hold the gripper. With the official arm it hangs off
        # link5 and is driven through Joint1..5; without it, it is a free body
        # on a mocap weld -- the handheld collector, which is fine for looking
        # at the gripper alone and says nothing about where the elbow goes.
        self.arm_joints = [j for j in ("joint1", "joint2", "joint3",
                                       "joint4", "joint5")
                           if mujoco.mj_name2id(self.model,
                                                mujoco.mjtObj.mjOBJ_JOINT, j) >= 0]
        self.has_arm = len(self.arm_joints) == 5
        if self.has_arm:
            self.arm_jids = [_id(mujoco.mjtObj.mjOBJ_JOINT, j)
                             for j in self.arm_joints]
            self.arm_qadr = [self.model.jnt_qposadr[j] for j in self.arm_jids]
            self.arm_dofs = [self.model.jnt_dofadr[j] for j in self.arm_jids]
            self.arm_acts = [_id(mujoco.mjtObj.mjOBJ_ACTUATOR, j)
                             for j in self.arm_joints]
            self.arm_range = self.model.jnt_range[self.arm_jids].copy()
            self.mocap_id = None
            self._ik = mujoco.MjData(self.model)
            # Joint1's axis does not pass through the base point: link1 sits
            # 11.25 mm back along link0's x (urdf/omx.xml), so the arm's
            # working plane is offset by that much. Taking the base instead
            # threw link5 3-6 mm off the plane at non-zero base angles, which
            # then showed up as an IK residual that no iteration could remove.
            probe = mujoco.MjData(self.model)
            mujoco.mj_resetData(self.model, probe)
            mujoco.mj_forward(self.model, probe)
            self.arm_pivot_xy = probe.xpos[
                _id(mujoco.mjtObj.mjOBJ_BODY, "link1")][:2].copy()
        else:
            mocap_bid = _id(mujoco.mjtObj.mjOBJ_BODY, "mocap_target")
            self.mocap_id = self.model.body_mocapid[mocap_bid]

        self.tcp_offset = self.model.site_pos[self.tcp_sid].copy()
        self.grasp_offset = np.asarray(
            cfg.grasp_point_offset if cfg is not None else self.tcp_offset, float)
        lo, hi = (cfg.hinge_range if cfg is not None else (0.0, 0.47))
        self.grip_span = hi - lo
        self.grip_lo = lo
        self.grip_hi = hi
        # Measure the jaw table off the compiled model instead of deriving it.
        # On a pivot the inner faces swing and tilt together, so a closed-form
        # gap is easy to write and easy to get subtly wrong -- forward
        # kinematics at a few angles is exact by construction.
        self._theta_tab, self._width_tab = self._measure_jaw_table()
        self.bin_inner_half = ((cfg.bin_inner if cfg is not None else 0.114) / 2)
        self.bin_outer = (cfg.bin_outer if cfg is not None else 0.120)
        #: m/s for the transport segment. Slow enough that the block stays in
        #: an angled pivot jaw.
        self.carry_speed = 0.10
        #: How far back the approach starts, along the approach heading.
        self.approach_back = 0.22
        self.tip_cfg = TipDetectorConfig()
        self.gripper_scale = None
        cal = pathlib.Path(__file__).resolve().parents[1] / "assets" / "gripper_calibration.json"
        if cal.is_file():
            self.gripper_scale = json.loads(cal.read_text())["scale"]
        self.obj_qadr = self.model.jnt_qposadr[self.model.body_jntadr[self.object_bid]]
        self.bin_qadr = self.model.jnt_qposadr[self.model.body_jntadr[self.bin_bid]]
        self.col_qadr = self.model.jnt_qposadr[
            self.model.body_jntadr[self.collector_bid]]

    def enable_overview(self, width: int = 640, height: int = 480,
                        azimuth: float = 90.0, elevation: float = -30.0,
                        distance: float = 1.05,
                        lookat=(0.0, -0.18, 0.05)) -> None:
        """Also record a third-person view. Debug/demo only -- never the policy
        observation, which stays the wrist camera."""
        cam = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(cam)
        cam.azimuth, cam.elevation, cam.distance = azimuth, elevation, distance
        cam.lookat[:] = lookat
        self.overview = {"renderer": mujoco.Renderer(self.model, height=height,
                                                     width=width),
                         "camera": cam}

    def close(self) -> None:
        """Release the GL context explicitly.

        Letting the Renderer be collected raises EGL_NOT_INITIALIZED out of
        __del__ at interpreter shutdown, and that traceback lands on top of
        whatever real error killed the run -- which is exactly how long it took
        to notice a plain TypeError here once.
        """
        ov = getattr(self, "overview", None)
        if ov is not None:
            try:
                ov["renderer"].close()
            except Exception:
                pass
            self.overview = None
        r = getattr(self, "renderer", None)
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
            self.renderer = None

    # ----------------------------------------------------------------- pose --
    def mocap_for_tcp(self, tcp_world, yaw: float) -> np.ndarray:
        return np.asarray(tcp_world, float) - rot_z(yaw) @ self.tcp_offset

    def mocap_for_grasp(self, grasp_world, yaw: float) -> np.ndarray:
        """Place the CAVITY on this point, not the tool frame."""
        return np.asarray(grasp_world, float) - rot_z(yaw) @ self.grasp_offset

    # ------------------------------------------------------------------ ik --
    def solve_ik(self, tcp_pos, tcp_quat, q0=None, iters=60, damping=0.05,
                 tol_pos=1e-4, tol_rot=1e-3):
        """Damped least squares on the five arm joints.

        Returns (q, position error, orientation error). The orientation error
        is not a failure of the solver: five joints cannot place a frame in
        six dimensions. With the wrist held level the gripper's yaw IS the base
        angle, so a demonstration that also wants a free yaw is asking for a
        pose the arm does not have. The residual is returned so the caller can
        report it rather than absorb it.
        """
        m, d = self.model, self._ik
        d.qpos[:] = self.data.qpos
        d.qvel[:] = 0.0
        if q0 is not None:
            for a, v in zip(self.arm_qadr, q0):
                d.qpos[a] = v
        tgt = np.asarray(tcp_quat, float)
        jacp = np.zeros((3, m.nv))
        jacr = np.zeros((3, m.nv))
        cur = np.zeros(4)
        err_r = np.zeros(3)
        for _ in range(iters):
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            pos = d.site_xpos[self.tcp_sid]
            mujoco.mju_mat2Quat(cur, np.asarray(d.site_xmat[self.tcp_sid]).reshape(-1))
            mujoco.mju_subQuat(err_r, tgt, cur)
            err_p = np.asarray(tcp_pos, float) - pos
            if np.linalg.norm(err_p) < tol_pos and np.linalg.norm(err_r) < tol_rot:
                break
            mujoco.mj_jacSite(m, d, jacp, jacr, self.tcp_sid)
            J = np.vstack([jacp[:, self.arm_dofs], jacr[:, self.arm_dofs]])
            e = np.concatenate([err_p, err_r])
            dq = J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(6), e)
            for k, a in enumerate(self.arm_qadr):
                d.qpos[a] = float(np.clip(d.qpos[a] + dq[k],
                                          self.arm_range[k][0],
                                          self.arm_range[k][1]))
        mujoco.mj_kinematics(m, d)
        mujoco.mju_mat2Quat(cur, np.asarray(d.site_xmat[self.tcp_sid]).reshape(-1))
        mujoco.mju_subQuat(err_r, tgt, cur)
        q = np.array([d.qpos[a] for a in self.arm_qadr])
        return (q,
                float(np.linalg.norm(np.asarray(tcp_pos) - d.site_xpos[self.tcp_sid])),
                float(np.linalg.norm(err_r)))

    def solve_ik_planar(self, tcp_pos, pitch, roll=0.0, base_xy=None,
                        iters=40, damping=0.02):
        """IK that respects what the arm is, instead of fighting it.

        Joint1 turns the whole arm about the vertical, so the tool's yaw IS
        the base angle -- asking a damped least squares for an independent yaw
        just trades position away for an orientation it can never reach (it
        did: 163 mm mean position error, and every joint pinned at a limit).

        So Joint1 is set from the azimuth, joints 2-4 solve a 3x3 problem in
        the arm's own vertical plane -- two position components and the tool's
        pitch -- and Joint5 is the roll about the finger axis. Returns
        (q, in-plane position error, pitch error, out-of-plane offset). The
        last one is not solver slop: the tool frame sits 1.6 mm off the plane
        (urdf end_effector_joint y = -0.0016), so it is a real, fixed miss
        unless Joint1 is nudged, which this does.
        """
        m, d = self.model, self._ik
        bx, by = base_xy if base_xy is not None else self.arm_pivot_xy
        tcp_pos = np.asarray(tcp_pos, float)
        dx, dy = tcp_pos[0] - bx, tcp_pos[1] - by
        r = math.hypot(dx, dy)
        # the tool frame is 1.6 mm off the arm's plane; turn the base back by
        # the angle that subtends, so the TCP lands on the point asked for
        off = float(self.tcp_offset[0])
        yaw = math.atan2(-dx, dy) - math.asin(
            max(-1.0, min(1.0, off / max(r, 1e-6))))

        d.qpos[:] = self.data.qpos
        d.qvel[:] = 0.0
        d.qpos[self.arm_qadr[0]] = yaw
        d.qpos[self.arm_qadr[4]] = roll
        dofs = self.arm_dofs[1:4]
        e_r = np.array([-math.sin(yaw), math.cos(yaw), 0.0])
        e_z = np.array([0.0, 0.0, 1.0])
        n = np.cross(e_r, e_z)
        jacp = np.zeros((3, m.nv))
        jacr = np.zeros((3, m.nv))
        cur = np.zeros(4)
        err_r = np.zeros(3)
        tgt = np.zeros(4)
        mujoco.mju_mat2Quat(tgt, np.asarray(
            rot_z(yaw) @ rot_x(-pitch) @ rot_y(roll)).reshape(-1))
        for _ in range(iters):
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            dp = tcp_pos - d.site_xpos[self.tcp_sid]
            mujoco.mju_mat2Quat(cur, np.asarray(
                d.site_xmat[self.tcp_sid]).reshape(-1))
            mujoco.mju_subQuat(err_r, tgt, cur)
            e = np.array([dp @ e_r, dp @ e_z, err_r @ n])
            if np.abs(e).max() < 1e-5:
                break
            mujoco.mj_jacSite(m, d, jacp, jacr, self.tcp_sid)
            J = np.vstack([e_r @ jacp[:, dofs], e_z @ jacp[:, dofs],
                           n @ jacr[:, dofs]])
            dq = J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(3), e)
            for k, a in enumerate(self.arm_qadr[1:4]):
                d.qpos[a] = float(np.clip(d.qpos[a] + dq[k],
                                          self.arm_range[k + 1][0],
                                          self.arm_range[k + 1][1]))
        mujoco.mj_kinematics(m, d)
        dp = tcp_pos - d.site_xpos[self.tcp_sid]
        mujoco.mju_mat2Quat(cur, np.asarray(d.site_xmat[self.tcp_sid]).reshape(-1))
        mujoco.mju_subQuat(err_r, tgt, cur)
        q = np.array([d.qpos[a] for a in self.arm_qadr])
        return (q, float(math.hypot(dp @ e_r, dp @ e_z)),
                float(abs(err_r @ n)), float(dp @ n))

    #: Elbow-up, elbow-down, and a few between. A 3R planar chain has more
    #: than one solution and Newton finds whichever one it starts next to;
    #: from a single start the same target solved to 0.01 mm at one pitch and
    #: 110 mm at the next.
    IK_SEEDS = ((0.0, 0.0, 0.0), (0.6, -0.9, -0.5), (-0.6, 0.9, 0.5),
                (1.0, -1.4, 0.0), (-0.3, -0.6, 1.0), (0.3, 0.6, -1.0))

    def solve_ik_best(self, tcp_pos, pitch, roll=0.0, passes=3, **kw):
        """solve_ik_planar from several elbow configurations; keep the best.

        Then nudge the base angle by whatever is left out of plane and solve
        again. The tool's lateral offset turns with the wrist, so correcting
        it once from the nominal 1.6 mm leaves a few millimetres; two passes
        take it under a tenth.
        """
        bx, by = kw.pop("base_xy", None) or self.arm_pivot_xy
        bx, by = float(bx), float(by)
        r = max(1e-6, math.hypot(tcp_pos[0] - bx, tcp_pos[1] - by))
        shift = 0.0
        best = None
        for _ in range(passes):
            for seed in self.IK_SEEDS:
                for a, v in zip(self.arm_qadr[1:4], seed):
                    self.data.qpos[a] = v
                q, ep, er, oo = self.solve_ik_planar(
                    tcp_pos, pitch, roll,
                    base_xy=(bx + shift * (tcp_pos[1] - by) / r,
                             by - shift * (tcp_pos[0] - bx) / r), **kw)
                score = ep + 0.05 * er + abs(oo)
                if best is None or score < best[0]:
                    best = (score, q, ep, er, oo)
            shift -= best[4]
        return best[1:]

    def grasp_tcp_target(self, obj_xy, z, pitch, depth):
        """Where the TCP goes so that the point `depth` along the finger axis
        lands on (obj_xy, z), with the wrist pitched nose-down by `pitch`.

        The claw holds a tabletop object at its TIPS: measured, taking it into
        the cavity puts the claw's lower half 8-22 mm inside the table.
        """
        bx, by = (self.cfg.robot_base_xy if self.cfg is not None else (0.0, -0.34))
        yaw = math.atan2(-(obj_xy[0] - bx), obj_xy[1] - by)
        R = rot_z(yaw) @ rot_x(-pitch)
        return (np.array([obj_xy[0], obj_xy[1], z])
                + R @ (np.asarray(self.tcp_offset, float)
                       - np.array([0.0, depth, 0.0])))

    # ------------------------------------------------------------- recording --
    def _tcp_quat(self) -> np.ndarray:
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, np.asarray(self.data.site_xmat[self.tcp_sid]).reshape(-1))
        return q

    def _gripper_width(self) -> float:
        return float(np.linalg.norm(self.data.site_xpos[self.left_sid]
                                    - self.data.site_xpos[self.right_sid]))

    def _bin_clearance(self) -> float:
        """Signed distance from the gripper to the bin, in metres.

        Negative means the gripper is inside a wall. Sampled points against
        the wall boxes, done here rather than with the simulator:
        `mj_geomDistance` returns a spurious 0.0 for these box pairs (a
        measured 25 mm gap reads as 0 at isolated poses), and a contact margin
        -- the other way to read a near miss -- changes the dynamics it is
        supposed to observe, on the bin and on the fingers both.

        The magnitude saturates at the wall half-thickness (1.5 mm) once a
        point is all the way through, so read the SIGN, not the depth: a wall
        crossed is -1.5 mm whether it was crossed by a millimetre or by a hand.
        """
        d, m = self.data, self.model
        best = self.clearance_cap
        for g, pts in self.clearance_pts:
            world = d.geom_xpos[g] + pts @ np.asarray(d.geom_xmat[g]).reshape(3, 3).T
            for b in self.bin_box_gids:
                local = (world - d.geom_xpos[b]) @ np.asarray(
                    d.geom_xmat[b]).reshape(3, 3)
                over = np.abs(local) - m.geom_size[b]
                outside = np.linalg.norm(np.maximum(over, 0.0), axis=1)
                inside = np.minimum(over.max(axis=1), 0.0)
                dist = float((outside + inside).min())
                if dist < best:
                    best = dist
        return best

    def _measure_jaw_table(self, n: int = 41):
        m = self.model
        d = mujoco.MjData(m)
        adr = [m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, j)]
               for j in ("gripper_joint_1", "gripper_joint_2")]
        lo, hi = self.grip_lo, self.grip_hi
        th = np.linspace(lo, hi, n)
        w = np.empty(n)
        for i, t in enumerate(th):
            d.qpos[:] = 0.0
            for a in adr:
                d.qpos[a] = t
            mujoco.mj_forward(m, d)
            w[i] = float(np.linalg.norm(d.site_xpos[self.left_sid]
                                        - d.site_xpos[self.right_sid]))
        order = np.argsort(w)
        return th[order], w[order]

    def gap_to_alpha(self, gap: float) -> float:
        """Jaw opening in metres -> the 0..1 the segments use."""
        t = float(np.interp(gap, self._width_tab, self._theta_tab))
        t = float(np.clip(t, self.grip_lo, self.grip_hi))
        # alpha is CLOSEDNESS: 0 = fully open = the hinge at its upper limit.
        # Returning openness here instead drives every commanded width to its
        # mirror, so a 36 mm grasp closes to 14 mm and crushes straight through
        # the block -- and no actuator gain fixes that, which is what made it
        # look like a contact problem.
        return float((self.grip_hi - t) / (self.grip_hi - self.grip_lo))

    def grasp_alpha_for(self, spec: "EpisodeSpec") -> float:
        """Just close.

        The real gripper is current-based position control: it is handed a
        closed target and a current cap, and the object stops it. Computing a
        width and inverting the geometry to a joint angle is not what the
        hardware does, and every bug in this area was a sign or an offset in
        that inversion -- which could not show up as a wrong number, because
        the jaw table and the command were built from the same sites.
        """
        return 1.0

    def _set_gripper(self, alpha: float) -> None:
        alpha = float(np.clip(alpha, 0.0, 1.0))
        # alpha 0 = fully OPEN. The fingers slide outward as the joint value
        # grows, so open is the stroke's upper end and closed the lower --
        # mapping alpha straight onto [lo, hi] inverts it, and the script then
        # opens where it means to grip. Nothing lifts and nothing errors.
        # Both fingers now slide OUTWARD for a positive joint value -- the left
        # one's axis is -x -- so both actuators take the same sign. They took
        # opposite signs while the axes were both +x, and the left one silently
        # clamped to its limit after the axis flipped.
        # alpha 0 = fully OPEN. Both actuators take the same command; the
        # joint axes carry the opposite sense, standing in for the real
        # gripper's mimic (joint_2 = -joint_1 through a gear).
        v = self.grip_hi + (self.grip_lo - self.grip_hi) * alpha
        self.data.ctrl[self.left_act] = v
        self.data.ctrl[self.right_act] = v

    # ------------------------------------------------------------------ run --
    def run(self, spec: EpisodeSpec) -> Dict[str, object]:
        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)

        ox, oy = spec.object_xy
        d.qpos[self.obj_qadr:self.obj_qadr + 3] = [ox, oy, spec.grasp_z]
        d.qpos[self.obj_qadr + 3:self.obj_qadr + 7] = yaw_quat(spec.object_yaw)

        bx, by = spec.bin_xy
        d.qpos[self.bin_qadr:self.bin_qadr + 3] = [bx, by, 0.0]
        d.qpos[self.bin_qadr + 3:self.bin_qadr + 7] = yaw_quat(spec.bin_yaw)

        start = self.mocap_for_grasp([ox, oy, spec.carry_z], spec.approach_yaw)
        d.qpos[self.col_qadr:self.col_qadr + 3] = start
        d.qpos[self.col_qadr + 3:self.col_qadr + 7] = yaw_quat(spec.approach_yaw)
        mujoco.mj_forward(m, d)

        d.mocap_pos[self.mocap_id] = start
        d.mocap_quat[self.mocap_id] = yaw_quat(spec.approach_yaw)
        self._set_gripper(0.0)

        ov = getattr(self, "overview", None)
        rec = {k: [] for k in ("timestamps", "rgb", "rgb_raw", "overview",
                               "bin_contacts", "bin_penetration",
                               "bin_clearance", "tcp_pos",
                               "tcp_quat_wxyz", "gripper_width",
                               "gripper_width_gt", "object_pos")}
        state = {"next": 0.0}

        def record():
            if d.time + 1e-9 < state["next"]:
                return
            self.renderer.update_scene(d, camera="wrist")
            raw = self.renderer.render().copy()
            # The collector reads its jaw off the camera, as the real one does;
            # MuJoCo's width is kept beside it as ground truth, never as the
            # training input. The magenta is then painted out, because the real
            # OMX has none and an encoder must not learn to look for it.
            gt = self._gripper_width()
            est = gt
            if self.gripper_scale is not None:
                det = detect_tips(raw, self.tip_cfg)
                if det["pixel_gap"] is not None:
                    est = float(self.gripper_scale["a"] * det["pixel_gap"]
                                + self.gripper_scale["b"])
            rec["rgb"].append(mask_magenta(raw, self.tip_cfg))
            rec["rgb_raw"].append(raw)
            if ov is not None:
                ov["renderer"].update_scene(d, camera=ov["camera"])
                rec["overview"].append(ov["renderer"].render().copy())
            rec["timestamps"].append(d.time)
            rec["tcp_pos"].append(d.site_xpos[self.tcp_sid].copy())
            rec["tcp_quat_wxyz"].append(self._tcp_quat())
            rec["gripper_width"].append(est)
            rec["gripper_width_gt"].append(gt)
            rec["object_pos"].append(d.xpos[self.object_bid].copy())
            # Gripper against the bin: a visual arm that sweeps through a wall
            # looks like success and is not. Logged per frame so an episode can
            # be rejected on it rather than on the final position alone.
            hits, worst = 0, 0.0
            for ci in range(d.ncon):
                con = d.contact[ci]
                b1 = m.geom_bodyid[con.geom1]
                b2 = m.geom_bodyid[con.geom2]
                if (b1 in self.finger_bids and b2 == self.bin_bid) or \
                   (b2 in self.finger_bids and b1 == self.bin_bid):
                    hits += 1
                    worst = min(worst, float(con.dist))
            rec["bin_contacts"].append(hits)
            rec["bin_penetration"].append(-worst)
            rec["bin_clearance"].append(self._bin_clearance())
            state["next"] += 1.0 / RECORD_HZ

        def segment(tcp_target, yaw, duration, grip):
            p0 = d.mocap_pos[self.mocap_id].copy()
            q0 = d.mocap_quat[self.mocap_id].copy()
            g0 = (self.grip_hi - d.ctrl[self.left_act]) / self.grip_span
            p1 = self.mocap_for_grasp(tcp_target, yaw)
            q1 = yaw_quat(yaw)
            if float(q0 @ q1) < 0.0:
                q1 = -q1
            n = int(duration / m.opt.timestep)
            for i in range(n):
                a = (i + 1) / n
                d.mocap_pos[self.mocap_id] = (1 - a) * p0 + a * p1
                q = (1 - a) * q0 + a * q1
                d.mocap_quat[self.mocap_id] = q / np.linalg.norm(q)
                self._set_gripper((1 - a) * g0 + a * grip)
                mujoco.mj_step(m, d)
                record()

        gy, byaw, ayaw = spec.object_yaw, spec.bin_yaw, spec.approach_yaw
        gz, cz, rz = spec.grasp_z, spec.carry_z, spec.release_z

        # The wrist rotates twice inside the episode: to meet the block, and to
        # the bin's orientation while carrying it. Without that, rot6d is
        # constant -- the action is relative to the last observation, so yaw
        # that only differs between episodes never reaches it.
        # Start back from the block rather than directly over it. Descending
        # straight down keeps the object underneath the gripper, where a
        # shallow wrist camera never sees it -- measured 0/12 frames at every
        # pitch below 36 deg. The reference demonstrator approaches across the
        # table with the object in view, so the script does too.
        aox = ox - self.approach_back * math.sin(ayaw)
        aoy = oy - self.approach_back * math.cos(ayaw)
        segment([aox, aoy, cz], ayaw, 0.7, 0.0)   # stand off, block in view
        segment([ox, oy, cz], gy,   0.8, 0.0)     # close in and align
        segment([ox, oy, gz], gy,   0.6, 0.0)     # descend
        ga = self.grasp_alpha_for(spec)
        segment([ox, oy, gz], gy,   0.8, ga)      # close onto the block
        segment([ox, oy, cz], gy,   0.6, ga)      # lift clear of the rim
        # Constant speed rather than constant duration. A fixed 1.4 s made
        # every long carry a fast one, and a pivot jaw holds at the tips with
        # the pads at an angle -- past about 0.11 m of travel the block slid
        # out every time, while short carries succeeded. Rotation was not the
        # cause: it failed with the wrist held still too.
        dist = float(np.hypot(bx - ox, by - oy))
        segment([bx, by, cz], byaw, max(1.2, dist / self.carry_speed), ga)
        segment([bx, by, rz], byaw, 0.7, ga)      # lower INTO the bin
        segment([bx, by, rz], byaw, 0.5, 0.0)     # release
        segment([bx, by, cz], byaw, 0.7, 0.0)     # retreat
        segment([bx, by, cz], byaw, 1.0, 0.0)     # settle before judging -- the
                                                  # block is released a few cm
                                                  # above the bin floor and
                                                  # needs time to stop bouncing

        out = {
            "timestamps": np.asarray(rec["timestamps"], np.float64),
            "rgb": np.asarray(rec["rgb"], np.uint8),
            "tcp_pos": np.asarray(rec["tcp_pos"], np.float32),
            "tcp_quat_wxyz": np.asarray(rec["tcp_quat_wxyz"], np.float32),
            "gripper_width": np.asarray(rec["gripper_width"], np.float32),
            "gripper_width_gt": np.asarray(rec["gripper_width_gt"], np.float32),
            "rgb_raw": np.asarray(rec["rgb_raw"], np.uint8),
            "overview": (np.asarray(rec["overview"], np.uint8)
                         if rec["overview"] else None),
            "bin_contacts": np.asarray(rec["bin_contacts"], np.int32),
            "bin_penetration": np.asarray(rec["bin_penetration"], np.float64),
            "bin_clearance": np.asarray(rec["bin_clearance"], np.float64),
            "object_pos": np.asarray(rec["object_pos"], np.float32),
        }
        out["gripper_width_error"] = (out["gripper_width"]
                                      - out["gripper_width_gt"]).astype(np.float32)
        out.update(self._judge(spec, out))
        return out

    def _judge(self, spec: EpisodeSpec, out: Dict[str, object]) -> Dict[str, object]:
        """Lift, then inside the bin, then still there.

        Final position alone is not enough in either direction: a block shoved
        across the table ends up at the same xy, and one that bounces off the
        rim can be over the bin for a frame on its way out.
        """
        d = self.data
        final = d.xpos[self.object_bid].copy()
        bin_pos = d.xpos[self.bin_bid].copy()
        obj = out["object_pos"]
        half = self.bin_inner_half

        rel = final[:2] - bin_pos[:2]
        c, s = math.cos(-spec.bin_yaw), math.sin(-spec.bin_yaw)
        local = np.array([c * rel[0] - s * rel[1], s * rel[0] + c * rel[1]])

        max_z = float(obj[:, 2].max())
        lifted = bool(max_z > spec.grasp_z + 0.04)
        inside = bool(abs(local[0]) < half and abs(local[1]) < half
                      and 0.01 < final[2] < self.bin_outer)
        # settled: the last 10 recorded frames barely move
        tail = obj[-10:] if len(obj) >= 10 else obj
        settled = bool(np.linalg.norm(tail.max(0) - tail.min(0)) < 0.005)
        pen = float(out["bin_penetration"].max()) if len(out["bin_penetration"]) else 0.0
        touches = int((out["bin_contacts"] > 0).sum())
        clr = out["bin_clearance"]
        min_clr = float(clr.min()) if len(clr) else 1.0
        # 1 mm of contact resolution is the solver settling; deeper means the
        # arm is inside the wall, not resting on it. The same 1 mm is allowed
        # on the geometric side, where a negative clearance IS penetration.
        clean = bool(pen < 0.001 and min_clr > -0.001)
        return {"lifted": lifted, "in_bin": inside, "settled": settled,
                "bin_touch_frames": touches,
                "bin_penetration_mm": round(pen * 1000, 3),
                "bin_min_clearance_mm": round(min_clr * 1000, 3),
                "no_wall_penetration": clean,
                "success": bool(lifted and inside and settled and clean),
                "max_object_z": max_z,
                "bin_local_xy": [round(float(v), 5) for v in local],
                "final_object_pos": final}


def sample_pose_pair(rng: np.random.Generator, cfg,
                     *, min_separation: float = 0.20,
                     edge_clearance: float = 0.06,
                     r_min: float = 0.14, r_max: Optional[float] = None,
                     max_tries: int = 400):
    """Draw object and bin placements that the arm can actually work with.

    Rejection sampling rather than axis-aligned ranges, because the constraints
    are not axis-aligned: reach is a disc around the base, the paper is a
    rectangle, and the two objects must not overlap. Drawing both from the same
    region and rejecting the bad pairs is what produces the varied layouts --
    bin left of the object, right of it, nearer, further, diagonal -- instead of
    the bin always sitting straight ahead of it.
    """
    bx, by = cfg.robot_base_xy
    r_max = r_max if r_max is not None else cfg.robot_reach - 0.04

    def draw():
        for _ in range(max_tries):
            r = math.sqrt(rng.uniform(r_min ** 2, r_max ** 2))
            th = rng.uniform(-math.pi / 2.2, math.pi / 2.2)   # in front of base
            x, y = bx + r * math.sin(th), by + r * math.cos(th)
            if cfg.on_paper(x, y, edge_clearance) and cfg.reachable(x, y, 0.03):
                return x, y
        return None

    for _ in range(max_tries):
        a, b = draw(), draw()
        if a is None or b is None:
            continue
        if math.hypot(a[0] - b[0], a[1] - b[1]) >= min_separation:
            return a, b
    raise RuntimeError("could not place object and bin under the constraints; "
                       "loosen min_separation or edge_clearance")


def sample_spec(rng: np.random.Generator, seed: int, cfg,
                yaw_range_deg=(-40.0, 40.0),
                bin_yaw_range_deg=(-40.0, 40.0),
                object_type: str = "box",
                **kw) -> EpisodeSpec:
    obj_xy, bin_xy = sample_pose_pair(rng, cfg, **kw)
    return EpisodeSpec(
        object_xy=obj_xy,
        object_yaw=math.radians(float(rng.uniform(*yaw_range_deg))),
        object_type=object_type,
        bin_xy=bin_xy,
        bin_yaw=math.radians(float(rng.uniform(*bin_yaw_range_deg))),
        approach_yaw=0.0,
        seed=seed)
