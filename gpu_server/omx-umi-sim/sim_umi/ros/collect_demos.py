"""Expert demonstrations, generated on the frozen stack and filtered before they count.

    python sim_umi/ros/collect_demos.py --split train --n-episodes 20

Not one trajectory copied twenty times. Every episode draws its own object
placement, bin placement and yaw, stand-off, approach pitch, lift height and
transport arc, and only the ones the arm actually flew are kept.

What makes an episode ACCEPTED, all of it checked before the file is written:

    continuous IK      every waypoint solved from the previous q, so the arm
                       does not jump branches mid-path
    joint limits       inside the official model's ranges with margin
    collision          /check_state_validity against the real scene: table,
                       paper, bin, and the robot against itself
    velocity           no segment asking for more than joint_limits.yaml allows
    the task           the ball leaves the table, stays held, and ends in the bin

Observations are the runtime contract, unchanged: the plant's own wrist camera,
the FK of /joint_states, and a gripper width estimated from the magenta patches
through the frozen calibration. MuJoCo's true widths and poses are recorded too
but only as evaluation metadata -- they are not policy input, and the converter
does not put them in the observation keys.

The actions are whatever the expert actually executed. Because every waypoint
went through the 5-DoF projection first, the recorded EE trajectory already
lies on the manifold the arm can hold, which is the point: a policy trained on
it should not need much correction at run time.
"""
import collections
import os
import json
import math
import pathlib
import sys
import time

SIM = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import numpy as np
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from geometry_msgs.msg import Pose
from moveit_msgs.msg import RobotState
from moveit_msgs.srv import GetStateValidity
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectoryPoint

import mujoco  # noqa: E402
import scene_objects  # noqa: E402
from collector import Collector, rot_x, rot_z  # noqa: E402
from gripper_vision import TipDetectorConfig, detect_tips, mask_magenta  # noqa: E402
from scene import SceneConfig  # noqa: E402

ARM = [f"joint{i}" for i in range(1, 6)]
RECORD_HZ = 10.0
TRACE = bool(os.environ.get("DEMO_TRACE"))
DUMP = os.environ.get("DEMO_DUMP")
#: Where to write a video of each episode. Debug and review only -- the
#: overview camera is rendered from a MIRROR of the plant, never the
#: observation, which stays the wrist frame the plant itself publishes.
VIDEO = os.environ.get("DEMO_VIDEO")
#: How far apart the picture and the joint state may be and still be called
#: one observation. The joint states arrive at 100 Hz, so a few milliseconds
#: is all that should ever be needed; it is an environment knob only so the
#: skew can be measured without the gate throwing every sample away first.
SKEW_MAX = float(os.environ.get("DEMO_SKEW_MAX", "0.02"))
#: How far a picture may sit from a tick and still be that tick. The camera
#: publishes every 50.000 ms of simulation time but re-bases its period on
#: the step that is due, so the phase moves by a 2 ms control step now and
#: then; this absorbs that and nothing larger.
GRID_TOL = 0.005

#: The action chunk is 16 steps at RECORD_HZ. It is the unit the leakage rule
#: is written in: if a target is not visible at the observation, nothing in the
#: next 16 actions may depend on where that target is.
ACTION_HORIZON = 16

#: One pose every episode starts from, so the previous episode cannot reach
#: into the next one through the arm. It is not the origin: it is the first
#: pose of the scan below, chosen because the camera already covers most of
#: the workspace from there. scripts/design_search.py measured it -- a yaw
#: sweep from here, 90 degrees in 17 legs at radius 160 mm, height 260 mm,
#: nose 45 degrees down, brings 100% of ball placements and 99% of bin
#: placements into the policy's 224 square.
HOME_Q = np.array([0.728554, -0.484702, -0.429863, 1.699963, 0.0])
SCAN_RADIUS = 0.16
SCAN_Z = 0.26
SCAN_PITCH = math.radians(45.0)
SCAN_SPAN = math.radians(90.0)
SCAN_LEGS = 17

#: A geom this small in the crop is a sliver at the edge, not a sighting.
VISIBLE_MIN_PX = 12

#: Phases whose motion may not depend on where the ball is, and those whose
#: motion may not depend on where the bin is. The audit reads these.
OBJECT_FREE_PHASES = ("HOME", "SEARCH_OBJECT", "RETREAT")
BIN_FREE_PHASES = ("HOME", "SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP",
                   "LIFT", "SEARCH_BIN", "RETREAT")
#: joint_limits.yaml: max_velocity 5.0 scaled by default_velocity_scaling_factor 0.1
MAX_JOINT_VEL = 0.5


def quat_from_yaw(yaw):
    return (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))


class _Interpolated:
    """A joint state at an instant no message was delivered for."""

    __slots__ = ("name", "position")

    def __init__(self, name, position):
        self.name = name
        self.position = position


class Demos(Node):
    def __init__(self):
        super().__init__("collect_demos")
        self.cfg = SceneConfig()
        self.kin = Collector(str(SIM / "mjcf" / "collector_scene.xml"),
                             cfg=self.cfg, render=False)
        if VIDEO:
            self.kin.enable_overview(width=640, height=480)
        # Visibility is decided on a segmentation render of the mirror, which
        # is allowed to know what is what -- it decides only WHETHER a thing is
        # in the picture, never where to go. Colour would not do: the ball, the
        # fingers and the bin are all white.
        W, H = self.cfg.wrist_cam_resolution
        self._seg = mujoco.Renderer(self.kin.model, height=H, width=W)
        self._seg.enable_segmentation_rendering()
        self._crop = ((W - min(W, H)) // 2, (W - min(W, H)) // 2 + min(W, H))
        self._geoms = {}
        for name in ("object", "bin"):
            bid = mujoco.mj_name2id(self.kin.model, mujoco.mjtObj.mjOBJ_BODY, name)
            self._geoms[name] = set(range(
                self.kin.model.body_geomadr[bid],
                self.kin.model.body_geomadr[bid]
                + self.kin.model.body_geomnum[bid]))
        self.state = None
        self.frame = None
        self.frame_stamp = None
        self.frame_seen = 0.0
        self.free = None
        self.max_frame_age = 0.0
        self.js_buf = collections.deque(maxlen=400)
        self.frame_recv = 0.0
        # Keep-last-1: an old joint state or an old frame is worse than none,
        # and a deep queue is what let the image fall behind the arm.
        fresh = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                           reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(JointState, "/joint_states", self._js, fresh)
        self.create_subscription(Image, "/wrist_camera/image_raw", self._img, fresh)
        from mujoco_ros2_control_msgs.msg import FreeJointStateArray
        from mujoco_ros2_control_msgs.srv import SetFreeJointState
        self.create_subscription(
            FreeJointStateArray,
            "/free_joint_state_publisher/free_joint_states", self._free, fresh)
        self.setter = self.create_client(
            SetFreeJointState, "/mujoco_ros2_control_node/set_free_joint_state")
        self.SetFreeJointState = SetFreeJointState
        self.validity = self.create_client(GetStateValidity,
                                           "/check_state_validity")
        self.arm = ActionClient(self, FollowJointTrajectory,
                                "/arm_controller/follow_joint_trajectory")
        self.grip = ActionClient(self, GripperCommand,
                                 "/gripper_controller/gripper_cmd")
        assert self.setter.wait_for_service(timeout_sec=30), "no set_free_joint_state"
        assert self.arm.wait_for_server(timeout_sec=30), "no arm_controller"
        assert self.grip.wait_for_server(timeout_sec=30), "no gripper_controller"
        self.has_validity = self.validity.wait_for_service(timeout_sec=10)
        if self.has_validity:
            scene_objects.apply(self, self.cfg, timeout=15)
        self.tip = TipDetectorConfig()
        self.cal = json.loads(
            (SIM / "assets" / "gripper_calibration.json").read_text())["scale"]
        self.last_width = None
        self.last_detect_ok = False
        self._dumped = {}
        self._home_settled = None

    # --------------------------------------------------------------- state --
    def _js(self, m):
        self.state = m
        self.js_buf.append(
            (m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
             time.monotonic(), m))

    def state_at(self, stamp):
        """The joint state from the instant a picture was taken.

        Both are stamped on the plant's simulation clock -- the launch files
        put the controller manager, its controllers and move_group on
        use_sim_time, because the camera plugin was already there. They were
        not: the camera stamped 412.064 while the broadcaster stamped
        1790384435.445, and the only way to line those up is to assume a
        constant between the two clocks, which a wandering real-time factor,
        a stall or a reset takes away. So they are matched by their own
        stamps, with nothing assumed.

        It matters because the camera publishes at 18 Hz and the recorder
        samples at 10: the newest joint state can be nearly a tenth of a
        second ahead of the picture beside it, a whole action step. Matched,
        the nearest is a millisecond away -- they arrive at 455 Hz.
        """
        if stamp is None or not self.js_buf:
            return (self.state, float("nan"), float("nan"), float("nan"))
        ts = [t for t, _, _ in self.js_buf]
        i = int(np.argmin([abs(t - stamp) for t in ts]))
        t, recv, m = self.js_buf[i]
        if abs(t - stamp) < 1e-6:
            return (m, t - stamp, recv - self.frame_recv, t)
        # No joint state carries this picture's stamp. The subscription keeps
        # only the newest message, so at 455 Hz most of them are never
        # delivered and now and then the one that matches is among them. The
        # bracketing pair is a few milliseconds apart, so interpolate rather
        # than accept the nearest and its error.
        j = i - 1 if t > stamp else i + 1
        if 0 <= j < len(self.js_buf):
            t2, recv2, m2 = self.js_buf[j]
            lo, hi = (m, m2) if t <= t2 else (m2, m)
            t_lo, t_hi = (t, t2) if t <= t2 else (t2, t)
            if t_lo <= stamp <= t_hi and t_hi > t_lo:
                a = (stamp - t_lo) / (t_hi - t_lo)
                names = list(lo.name)
                pos = [float(p_lo) + (float(p_hi) - float(p_lo)) * a
                       for p_lo, p_hi in zip(lo.position,
                                             [dict(zip(hi.name, hi.position))[n]
                                              for n in names])]
                return (_Interpolated(names, pos), 0.0,
                        recv - self.frame_recv, stamp)
        return (m, t - stamp, recv - self.frame_recv, t)

    def _img(self, m):
        self.frame = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, 3).copy()
        self.frame_stamp = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        self.frame_seen = time.time()
        # a monotonic receipt time as well, for the audit: the difference
        # between when the two messages ARRIVED is a different quantity from
        # the difference between what they say, because it carries transport
        self.frame_recv = time.monotonic()

    def _free(self, m):
        self.free = m

    def spin(self, s):
        t0 = time.time()
        while time.time() - t0 < s:
            rclpy.spin_once(self, timeout_sec=0.005)

    def q_now(self, state=None):
        st = self.state if state is None else state
        n = list(st.name)
        return np.array([st.position[n.index(j)] for j in ARM])

    def ee_now(self, state=None):
        d = self.kin._ik
        d.qpos[:] = self.kin.data.qpos
        for a, v in zip(self.kin.arm_qadr, self.q_now(state)):
            d.qpos[a] = v
        mujoco.mj_kinematics(self.kin.model, d)
        return (d.site_xpos[self.kin.tcp_sid].copy(),
                np.asarray(d.site_xmat[self.kin.tcp_sid]).reshape(3, 3).copy())

    def width_from_camera(self):
        # Runtime behaviour on a failed detection is to hold the last width, and
        # the dataset must be built through the same path. But holding a value
        # silently is how a width frozen at "open" survived a whole grasp
        # unnoticed, so every sample records whether it was a real measurement.
        det = detect_tips(self.frame, self.tip)
        if det["pixel_gap"] is None:
            self.last_detect_ok = False
            self._dump(det, "fail")
            return self.last_width
        self.last_detect_ok = True
        self._dump(det, "ok")
        self.last_width = float(self.cal["a"] * det["pixel_gap"] + self.cal["b"])
        return self.last_width

    def _dump(self, det, tag):
        cap = 4 if tag == "ok" else 40
        if not DUMP or self._dumped.get(tag, 0) >= cap:
            return
        import cv2
        n = self._dumped.get(tag, 0)
        self._dumped[tag] = n + 1
        d = pathlib.Path(DUMP); d.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / f"{tag}_{n:02d}_rgb.png"), self.frame[..., ::-1])
        cv2.imwrite(str(d / f"{tag}_{n:02d}_mask.png"), det["mask"] * 255)
        print(f"    dump {tag}_{n:02d}  blobs={det['n_blobs']} "
              f"px={int(det['mask'].sum()) // 255 if det['mask'].max() > 1 else int(det['mask'].sum())} "
              f"gt={self.gt_width()*1000:.2f}", flush=True)

    def gt_width(self, state=None):
        st = self.state if state is None else state
        n = list(st.name)
        return float(np.interp(st.position[n.index("gripper_joint_1")],
                               self.kin._theta_tab, self.kin._width_tab))

    def mirror(self, state=None):
        """Pose the kinematics model from what the plant publishes."""
        k, d = self.kin, self.kin.data
        n = list((self.state if state is None else state).name)
        st = self.state if state is None else state
        for adr, j in zip(k.arm_qadr, ARM):
            d.qpos[adr] = st.position[n.index(j)]
        if "gripper_joint_1" in n:
            g = st.position[n.index("gripper_joint_1")]
            for jid in range(k.model.njnt):
                nm = mujoco.mj_id2name(k.model, mujoco.mjtObj.mjOBJ_JOINT, jid)
                if nm and nm.startswith("gripper_joint"):
                    d.qpos[k.model.jnt_qposadr[jid]] = g
        for name, adr in (("object", k.obj_qadr), ("bin", k.bin_qadr)):
            fp = self.free_pose(name)
            if fp is not None:
                d.qpos[adr:adr + 3] = fp[0]
                d.qpos[adr + 3:adr + 7] = fp[1]
        mujoco.mj_forward(k.model, d)

    def visible(self, name, state=None):
        """Is `name` inside the square the policy is actually handed?

        Counted on the wrist camera's segmentation, so a ball behind the
        gripper is not visible and a ball at the edge of the wide frame that
        the centre crop throws away is not visible either.
        """
        if self.state is None:
            return False
        self.mirror(state)
        self._seg.update_scene(self.kin.data, camera="wrist")
        seg = self._seg.render()[:, :, 0]
        x0, x1 = self._crop
        return int(np.isin(seg[:, x0:x1], list(self._geoms[name])).sum()) \
            >= VISIBLE_MIN_PX

    def free_pose(self, name):
        """Position and orientation of a free body, as the plant publishes it."""
        if self.free is None:
            return None
        for e in self.free.free_joints:
            p, q = e.pose.pose.position, e.pose.pose.orientation
            if e.name == name:
                return (np.array([p.x, p.y, p.z]),
                        np.array([q.w, q.x, q.y, q.z]))
        return None

    def overview(self):
        """Third person, by mirroring the plant into the kinematics model.

        The plant lives inside ros2_control and renders only the wrist camera,
        so a view of the whole arm has to be posed from what the plant
        publishes: the arm and the jaw from /joint_states, the ball and the bin
        from the free joint publisher. Nothing here reaches the observation.
        """
        self.mirror()
        k = self.kin
        k.overview["renderer"].update_scene(k.data, k.overview["camera"])
        return k.overview["renderer"].render().copy()

    def body_pose(self, name):
        if self.free is None:
            return None
        for e in self.free.free_joints:
            if e.name == name:
                p = e.pose.pose.position
                return np.array([p.x, p.y, p.z])
        return None

    # -------------------------------------------------------------- acting --
    def place_bodies(self, obj_xy, obj_z, bin_xy, bin_yaw):
        req = self.SetFreeJointState.Request()
        for name, xy, z, yaw in (("object", obj_xy, obj_z, 0.0),
                                 ("bin", bin_xy, 0.0, bin_yaw)):
            e = self.SetFreeJointState.Request().free_joints.__class__()
            from mujoco_ros2_control_msgs.msg import FreeJointState
            s = FreeJointState()
            s.name = name
            s.pose.pose.position.x = float(xy[0])
            s.pose.pose.position.y = float(xy[1])
            s.pose.pose.position.z = float(z)
            (s.pose.pose.orientation.x, s.pose.pose.orientation.y,
             s.pose.pose.orientation.z, s.pose.pose.orientation.w) = quat_from_yaw(yaw)
            req.free_joints.append(s)
        fut = self.setter.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10)
        r = fut.result()
        return (r is not None and r.success), ("" if r is None else r.message)

    def valid(self, q):
        if not self.has_validity:
            return True, "no /check_state_validity"
        req = GetStateValidity.Request()
        req.group_name = "arm"
        rs = RobotState()
        rs.joint_state.name = ARM
        rs.joint_state.position = [float(v) for v in q]
        rs.is_diff = True
        req.robot_state = rs
        fut = self.validity.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5)
        r = fut.result()
        if r is None:
            return False, "validity service timed out"
        if r.valid:
            return True, ""
        c = r.contacts[0] if r.contacts else None
        return False, (f"{c.contact_body_1}|{c.contact_body_2}" if c else "invalid")

    def send(self, qs, seconds):
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ARM
        t = 0.0
        for q, dt in zip(qs, seconds):
            t += dt
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start.sec = int(t)
            pt.time_from_start.nanosec = int((t % 1) * 1e9)
            goal.trajectory.points.append(pt)
        fut = self.arm.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5)
        h = fut.result()
        if h is None or not h.accepted:
            return False, t
        return h, t

    def go_home(self, sample_cb=None, phase_cb=None):
        """Put the arm at HOME, in joint space, every time.

        Episodes used to begin wherever the last one stopped -- measured, 19 of
        20 starts were within 0.1 mm of the previous episode's final pose, so
        the order of the set leaked into its initial states and a run of bins
        on the left gave a run of starts on the left. A rejected candidate
        moved the arm too, and left that behind for the next episode. So this
        runs after every attempt, accepted or not, and the path to it is
        checked the same way any other path is.
        """
        q0 = self.q_now()
        n = max(2, int(math.ceil(float(np.abs(HOME_Q - q0).max())
                                 / math.radians(10))))
        qs = [q0 + (HOME_Q - q0) * (k + 1) / n for k in range(n)]
        for q in qs:
            ok, why = self.valid(q)
            if not ok:
                return False, f"the way home is blocked: {why}"
        times, prev = [], q0
        for q in qs:
            times.append(max(0.20, float(np.abs(q - prev).max()) / MAX_JOINT_VEL))
            prev = q
        if phase_cb is not None:
            phase_cb()
        h, total = self.send(qs, times)
        if h is False:
            return False, "the controller refused the trajectory home"
        rf = h.get_result_async()
        t0 = time.time()
        while time.time() - t0 < total + 6.0:
            rclpy.spin_once(self, timeout_sec=0.005)
            if sample_cb is not None:
                sample_cb()
            if rf.done():
                break
        res = rf.result()
        if res is None or res.result.error_code != 0:
            return False, "the controller did not reach home"
        # Let it settle against gravity before reading the pose. The position
        # actuators run at kp 50 and hold a steady-state error -- a known
        # calibration item, and a repeatable one. What HOME has to be is the
        # same pose every time, not the commanded one, so that is the test.
        for _ in range(20):
            self.spin(0.05)
        q = self.q_now()
        if self._home_settled is None:
            self._home_settled = q.copy()
            self.get_logger().info(
                "HOME settles %.2f deg from the command; that pose is the "
                "reference for every episode"
                % math.degrees(float(np.abs(q - HOME_Q).max())))
        drift = float(np.abs(q - self._home_settled).max())
        if drift > math.radians(1.0):
            return False, (f"home is not repeatable: {math.degrees(drift):.2f} "
                           f"deg from the first homing")
        return True, ""

    def jaw(self, theta, wait=True):
        g = GripperCommand.Goal()
        g.command.position = float(theta)
        g.command.max_effort = 0.5
        fut = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5)
        h = fut.result()
        if h is not None and h.accepted and wait:
            rf = h.get_result_async()
            rclpy.spin_until_future_complete(self, rf, timeout_sec=10)
        return h


# ------------------------------------------------------------------- expert --
def write_video(rec, path, ep, fps=10.0):
    """Third person beside the picture the policy is given, at real speed.

    Recording is 10 Hz, so 10 fps plays back in the time the arm actually took.
    """
    import cv2
    W, H = 640, 480
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                         (W * 2, H))
    if not vw.isOpened():
        raise RuntimeError(f"could not open {path} for writing")

    def put(img, lines, y0=22):
        for i, t in enumerate(lines):
            for col, th in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                cv2.putText(img, t, (10, y0 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX,
                            0.52, col, th, cv2.LINE_AA)

    for k in range(len(rec["t"])):
        left = rec["over"][k][..., ::-1].copy()
        wrist = rec["rgb"][k][..., ::-1]
        wide = cv2.resize(wrist, (W, int(W * wrist.shape[0] / wrist.shape[1])),
                          interpolation=cv2.INTER_NEAREST)
        right = np.zeros((H, W, 3), np.uint8)
        y0 = (H - wide.shape[0]) // 2
        right[y0:y0 + wide.shape[0]] = wide
        put(left, [f"t {rec['t'][k]:5.1f}s",
                   f"stage {rec['stage'][k]}",
                   f"ball {ep['object_xy'][0]*1000:+.0f},{ep['object_xy'][1]*1000:+.0f} mm",
                   f"bin  {ep['bin_xy'][0]*1000:+.0f},{ep['bin_xy'][1]*1000:+.0f} mm"])
        put(right, ["what the policy sees (patches removed)",
                    f"gripper {rec['width_cam'][k]*1000:5.1f} mm"
                    f"   true {rec['width_gt'][k]*1000:5.1f} mm"],
            y0=y0 - 26 if y0 > 40 else 22)
        vw.write(np.hstack([left, right]))
    vw.release()


def sample_episode(rng, cfg, ball_r, cell=None):
    """One draw of the task. Every number here is a degree of freedom the
    policy has to cope with, not a constant it can memorise."""
    bx, by = cfg.robot_base_xy
    def draw(rmin, rmax):
        for _ in range(400):
            r = math.sqrt(rng.uniform(rmin ** 2, rmax ** 2))
            th = rng.uniform(-math.pi / 3, math.pi / 3)
            x, y = bx + r * math.sin(th), by + r * math.cos(th)
            if cfg.on_paper(x, y, 0.09) and cfg.reachable(x, y, 0.06):
                return x, y
        return None
    for _ in range(400):
        o, b = draw(0.16, 0.30), draw(0.16, 0.30)
        if o and b and math.hypot(o[0] - b[0], o[1] - b[1]) > 0.16:
            spec = {
                "object_xy": o,
                "bin_xy": b,
                "bin_yaw": float(rng.uniform(-0.6, 0.6)),
                "pitch_deg": float(rng.uniform(6.0, 16.0)),
                "standoff": float(rng.uniform(0.055, 0.090)),
                "lift": float(rng.uniform(0.10, 0.15)),
                "carry_z": float(rng.uniform(0.19, 0.23)),
                "depth": float(rng.uniform(0.060, 0.070)),
                # the frozen place releases at the rim, 120 mm, which the
                # collision scene calls valid only just; with the bin's yaw
                # drawn too, a few millimetres above it is what passes
                "release_z": float(rng.uniform(0.130, 0.155)),
                "ball_r": ball_r,
            }
            if cell is not None:
                pd, want, entry = cell
                spec.update({
                    "perturb_pitch_deg": float(pd),
                    "perturb_tool_depth_mm": float(want),
                    # Just long enough for the observation window to show an
                    # arm that is not moving. A longer stand would fill the
                    # set with chunks whose whole answer is "stay here",
                    # which is the behaviour being corrected, not the
                    # correction. Every window that starts here has the
                    # correction inside its own horizon.
                    "perturb_dwell": 3,
                    "correct_steps": int(rng.integers(4, 9)),
                    "reentry_frac": float(rng.uniform(0.30, 0.45)),
                    "entry_scale": float(entry)})
            return spec
    raise RuntimeError("could not place object and bin")


def ring_pose(cfg, az):
    """A pose on the scan arc. Reachable at every azimuth by construction --
    the radius and height are the ones the sweep was measured at."""
    bx, by = cfg.robot_base_xy
    return np.array([bx - SCAN_RADIUS * math.sin(az),
                     by + SCAN_RADIUS * math.cos(az), SCAN_Z])


def blend(label, p0, pitch0, p1, pitch1, n):
    """A straight line between two poses that are each known to be reachable.

    Paths used to hold the ball's radius and climb to the scan height, which
    the arm cannot do: 260 mm is within reach on the 160 mm arc and nowhere
    near it at 300 mm out, and the IK missed by up to 40 mm. Going between
    two poses that are each feasible keeps the ends honest.
    """
    out = []
    for k in range(1, n + 1):
        a = k / n
        out.append((f"{label}{k}", p0 + (p1 - p0) * a, None,
                    pitch0 + (pitch1 - pitch0) * a))
    return out


def arc(cfg, label, az0, az1, n):
    """Move between two points on the scan arc along the arc itself.

    A straight line between them is a chord: it cuts inside the radius, folds
    the elbow, and the limit gate refused it within one or two degrees. There
    is no reason to cross the middle -- the arc is where the poses are known
    to be reachable.
    """
    return [(f"{label}{k}", ring_pose(cfg, az0 + (az1 - az0) * k / n),
             None, SCAN_PITCH) for k in range(1, n + 1)]


def object_azimuth(cfg, xy):
    bx, by = cfg.robot_base_xy
    return math.atan2(-(xy[0] - bx), xy[1] - by)


def approach_path(kin, cfg, ep, p_now):
    """Ball-directed: from the arc, out and down onto the ball.

    Only called once the ball has been seen in the policy's own crop.
    """
    pitch = math.radians(ep["pitch_deg"])
    o, r, d = ep["object_xy"], ep["ball_r"], ep["depth"]
    az = object_azimuth(cfg, o)
    pre = kin.grasp_tcp_target(o, r + ep["standoff"], pitch, d)
    out = arc(cfg, "swing", object_azimuth(cfg, p_now[:2]), az, 4)
    out += blend("reach", ring_pose(cfg, az), SCAN_PITCH, pre, pitch, 6)
    for k in range(1, 9):
        z = r + ep["standoff"] * (1 - k / 8)
        out.append((f"descend{k}", kin.grasp_tcp_target(o, z, pitch, d),
                    None, pitch))
    return out, pitch


#: The states the closed-loop rollout visits and the demonstrations do not.
#: Measured: at pitch 25-32 degrees with the ball 0 to +10 mm along the tool's
#: own depth axis, the clean set holds 0 of 6493 frames, and between 20 and 30
#: degrees not one expert frame has the pitch changing by less than 2 deg/s --
#: it passes through, it never stands there. A rollout stands there for
#: fourteen seconds. These are the cells a corrective demonstration starts in.
PERTURB_PITCH_DEG = (20.0, 25.0, 30.0, 34.0)
#: where the ball sits along the tool's depth axis at the wrong pose, in mm,
#: against the expert funnel's -16 to -24. Positive means the arm has stopped
#: short of the fingers closing around it, which is what the rollout does.
PERTURB_TOOL_DEPTH_MM = (10.0, 3.0, -4.0, -11.0)
#: between the trained cells, for a validation split that cannot be answered
#: by remembering the training ones
PERTURB_PITCH_MID = (22.5, 27.5, 32.0)
PERTURB_TOOL_DEPTH_MID = (6.5, -0.5, -7.5)
#: three entry speeds for the three repeats of each cell, so the same
#: correction is demonstrated slow, ordinary and brisk
ENTRY_SCALES = (1.55, 1.05, 0.72)


def tool_depth_mm(kin, obj_xy, ball_r, z, pitch, depth):
    """Where the ball sits along the tool's own depth axis at that pose.

    The `depth` parameter is not this number: it is measured from a different
    origin and shifts with the height the pose is taken at, which is how a
    cell meant to put the ball at +10 mm ended up putting it at +34. So the
    cells are stated in the frame they are about, and the parameter that
    reaches them is solved for.
    """
    pos = kin.grasp_tcp_target(obj_xy, z, pitch, depth)
    q, ep_, er, oop = kin.solve_ik_planar(pos, pitch, iters=60)
    if ep_ > 0.002 or abs(er) > math.radians(3):
        return None
    d = kin._ik
    d.qpos[:] = kin.data.qpos
    for a, v in zip(kin.arm_qadr, q):
        d.qpos[a] = v
    mujoco.mj_kinematics(kin.model, d)
    p = d.site_xpos[kin.tcp_sid].copy()
    R = np.asarray(d.site_xmat[kin.tcp_sid]).reshape(3, 3)
    ball = np.array([obj_xy[0], obj_xy[1], ball_r])
    return float((R.T @ (ball - p))[1] * 1000)


def depth_for(kin, obj_xy, ball_r, z, pitch, want_mm, seed_depth):
    """The `depth` parameter that lands the ball at `want_mm`. One probe is
    enough: the two move together millimetre for millimetre."""
    got = tool_depth_mm(kin, obj_xy, ball_r, z, pitch, seed_depth)
    if got is None:
        return None
    return seed_depth + (want_mm - got) / 1000.0


def corrective_approach_path(kin, cfg, ep, p_now):
    """Arrive wrong on purpose, then re-enter the expert's own approach.

    The clean expert has its nose down before the last second and then flies
    one straight insertion -- twenty times, with the pitch changing by
    +0.16 +- 0.05 degrees across the whole move. Nothing in it says what to do
    from a pose that is sixteen degrees too steep with the ball short of the
    fingers, which is exactly where the closed-loop policy ends up and stays.

    The correction does not cut straight to the grasp. It goes to the nearest
    point of the approach the clean episodes actually fly -- the same height
    on the same descent, at the right pitch and the right insertion -- and
    from there the rest is the expert's own trajectory, unchanged. So what is
    added is a way back onto the manifold, not a second way to grasp.
    """
    pitch = math.radians(ep["pitch_deg"])
    pp = math.radians(ep["perturb_pitch_deg"])
    o, r, d = ep["object_xy"], ep["ball_r"], ep["depth"]
    az = object_azimuth(cfg, o)
    # partway down the expert's own descent: far enough in that re-entry is
    # onto a real part of the path, high enough that there is path left after
    z_re = r + ep["standoff"] * ep["reentry_frac"]
    pdep = depth_for(kin, o, r, z_re, pp, ep["perturb_tool_depth_mm"], d)
    if pdep is None:
        return None, pitch
    wrong = kin.grasp_tcp_target(o, z_re, pp, pdep)
    reentry = kin.grasp_tcp_target(o, z_re, pitch, d)
    out = arc(cfg, "swing", object_azimuth(cfg, p_now[:2]), az, 4)
    out += blend("reach", ring_pose(cfg, az), SCAN_PITCH, wrong, pp, 6)
    # pitch and insertion move together, never one then the other
    out += blend("correct", wrong, pp, reentry, pitch, ep["correct_steps"])
    for k in range(1, 9):
        z = z_re - (z_re - r) * k / 8
        out.append((f"descend{k}", kin.grasp_tcp_target(o, z, pitch, d),
                    None, pitch))
    return out, pitch


def lift_path(kin, cfg, ep):
    """Ball-directed, and what makes the bin search possible: back onto the
    arc, where the camera is high enough to see past the table edge."""
    pitch = math.radians(ep["pitch_deg"])
    o, r, d = ep["object_xy"], ep["ball_r"], ep["depth"]
    az = object_azimuth(cfg, o)
    return blend("lift", kin.grasp_tcp_target(o, r, pitch, d), pitch,
                 ring_pose(cfg, az), SCAN_PITCH, 8)


def transport_path(kin, cfg, ep, p_now):
    """Bin-directed. Only built once the bin has been seen."""
    pitch = math.radians(ep["pitch_deg"])
    b, d = ep["bin_xy"], ep["depth"]
    above = kin.grasp_tcp_target(b, ep["carry_z"], pitch, d)
    az = object_azimuth(cfg, b)
    out = arc(cfg, "carry", object_azimuth(cfg, p_now[:2]), az, 6)
    out += blend("over", ring_pose(cfg, az), SCAN_PITCH, above, pitch, 6)
    return out, pitch


def place_path(kin, ep):
    pitch = math.radians(ep["pitch_deg"])
    b, d = ep["bin_xy"], ep["depth"]
    return [("release", kin.grasp_tcp_target(b, ep["release_z"], pitch, d),
             "open", pitch)]


def retreat_path(kin, cfg, ep):
    pitch = math.radians(ep["pitch_deg"])
    b, d = ep["bin_xy"], ep["depth"]
    az = object_azimuth(cfg, b)
    return blend("retreat", kin.grasp_tcp_target(b, ep["release_z"], pitch, d),
                 pitch, ring_pose(cfg, az), SCAN_PITCH, 5)


def project_path(node, path, q_seed=None):
    """Continuous IK with the previous solution as the seed, then every gate
    that can reject the episode before a single joint moves.

    A waypoint carries its own pitch now. The expert no longer flies one
    attitude from start to finish: it looks around with the nose 45 degrees
    down and grasps with it barely tipped, and the move between the two is an
    ordinary part of the path.
    """
    kin = node.kin
    qs, notes = [], []
    q_seed = node.q_now() if q_seed is None else np.asarray(q_seed, float)
    lo, hi = kin.arm_range[:, 0], kin.arm_range[:, 1]
    for label, pos, _, pitch in path:
        for a, v in zip(kin.arm_qadr, q_seed):
            kin.data.qpos[a] = v
        q, ep, er, oop = kin.solve_ik_planar(pos, pitch, iters=60)
        if ep > 0.002 or abs(er) > math.radians(3):
            return None, f"{label}: IK missed by {ep*1000:.1f} mm"
        margin = float(np.minimum(q - lo, hi - q).min())
        if margin < math.radians(2):
            return None, f"{label}: joint within {math.degrees(margin):.1f} deg of a limit"
        ok, why = node.valid(q)
        if not ok:
            return None, f"{label}: collision {why}"
        prev = qs[-1] if qs else q_seed
        step = float(np.abs(q - prev).max())
        if step > math.radians(50):
            return None, f"{label}: {math.degrees(step):.0f} deg jump (IK branch)"
        qs.append(q)
        notes.append(label)
        q_seed = q
    return qs, notes


def timing(node, qs, q_from=None):
    """Seconds per waypoint, at the velocity limit the gates check."""
    times, prev = [], (node.q_now() if q_from is None else np.asarray(q_from, float))
    for q in qs:
        times.append(max(0.15, float(np.abs(q - prev).max()) / MAX_JOINT_VEL))
        prev = q
    return times


def scan_legs(kin, cfg, start_az):
    """The look-around, as tool poses. It knows nothing about any target.

    A yaw sweep on a fixed arc: the camera is bolted to the wrist, so turning
    the base swings its footprint across the paper. The span, the radius, the
    height and the nose angle are the ones scripts/design_search.py measured;
    the only thing that varies between episodes is where the sweep starts,
    which is where the arm already is and never where the target is.

    Azimuth here is the collector's: grasp_tcp_target reads it as
    atan2(-(x - bx), y - by), so a POSITIVE azimuth is negative x. Building
    the arc the other way round put the first leg on the mirror image of HOME
    and the base was asked for 85 degrees in one step. The far end of the arc
    is swept first, which depends on where the arm is and on nothing else.
    """
    ends = sorted((SCAN_SPAN / 2, -SCAN_SPAN / 2), key=lambda e: -abs(e - start_az))
    a = [start_az]
    step = SCAN_SPAN / (SCAN_LEGS - 1)
    for e in ends:
        n = max(2, int(round(abs(e - a[-1]) / step)) + 1)
        a += list(np.linspace(a[-1], e, n))[1:]
    bx, by = cfg.robot_base_xy
    out = []
    for i, az in enumerate(a[1:]):
        out.append((f"scan{i}",
                    np.array([bx - SCAN_RADIUS * math.sin(az),
                              by + SCAN_RADIUS * math.cos(az), SCAN_Z]),
                    None, SCAN_PITCH))
    return out


def width_gate(rec):
    """The estimate has to track while the jaw is still, and a stale value
    has to be brief.

    The same gate the zarr builder applies, moved here so an episode that
    fails it is rejected while the arm is still in front of us instead of
    days later. A frozen width fed to the policy as an observation is the
    defect this whole pipeline was rebuilt around; six of the first
    forty-eight corrective episodes tripped it, because a steeper wrist
    hides a magenta tip more often than the clean approach does.
    """
    det = np.asarray(rec["width_detected"], bool)
    e = np.abs(np.asarray(rec["width_cam"]) - np.asarray(rec["width_gt"]))
    gt = np.asarray(rec["width_gt"])
    moving = np.r_[False, np.abs(np.diff(gt)) > 1e-5]
    w = np.zeros_like(moving)
    for k in range(-2, 3):
        w |= np.roll(moving, k)
    fresh = det & ~w
    err = float(e[fresh].max()) if fresh.any() else 0.0
    held = float(1.0 - det.mean())
    run = longest = 0
    for v in det:
        run = 0 if v else run + 1
        longest = max(longest, run)
    if err > 0.002:
        return False, f"width off by {err*1000:.2f} mm with the jaw still"
    if held > 0.05:
        return False, f"{held*100:.1f}% of frames reused a stale width"
    if longest > 3:
        return False, f"{longest} frames in a row reused a stale width"
    return True, ""


def run_episode(node, ep, rng, out_dir, index):
    """Execute one demonstration and record it. Returns (accepted, reason, path).

    The expert is a closed loop over what the camera shows, not a trajectory
    computed from the answer. It starts at HOME, looks around until the ball
    is in the policy's own crop, and only then uses the ball's position to
    build an approach. After the grasp it lifts to get the camera clear, looks
    around again until the bin is in the crop, and only then carries.

    Two rules hold it to that. The look-around never consults a target: it is
    a fixed yaw sweep from wherever the arm already is. And a target-directed
    move may not begin until the target has been visible for a full action
    horizon, so that every chunk of 16 actions recorded while a target was
    invisible contains nothing that depends on where it is.
    """
    kin = node.kin
    r = ep["ball_r"]
    ok, msg = node.place_bodies(ep["object_xy"], r, ep["bin_xy"], ep["bin_yaw"])
    if not ok:
        return False, f"could not place the bodies: {msg}", None
    # The collision check has to be against the bin this episode actually has.
    if node.has_validity:
        scene_objects.apply(node, node.cfg, timeout=15,
                            bin_xy=ep["bin_xy"], bin_yaw=ep["bin_yaw"])
    node.jaw(float(kin.grip_hi))
    node.spin(0.6)

    rec = {k: [] for k in ("t", "rgb", "eef_pos", "eef_rot", "width_cam",
                           "width_gt", "ball", "stage", "width_detected",
                           "frame_age", "over", "obj_vis", "bin_vis",
                           "stamp_skew", "recv_skew", "img_stamp",
                           "js_stamp")}
    state = {"stage": "HOME", "next": 0.0, "t0": time.time(),
             "t0_img": None, "next_sim": None, "last_stamp": None,
             "obj": False, "bin": False}

    def sample():
        """One row per tick of a grid made of the pictures' own stamps.

        The recorder used to fire on a wall clock, and took whichever picture
        happened to be current. The camera publishes every 50.000 ms of
        simulation time exactly -- measured, 235 intervals with no spread --
        so a wall-clock deadline lands between frames and the row spacing came
        out anywhere from 66 to 146 ms while the dataset declared 100. The
        model reads row indices and believes each step is a tenth of a second,
        so that spacing is a lie about how far the arm moved.

        Ticking on the picture stamps instead puts every row exactly 100 ms
        apart, because 100 is two camera periods. A picture that never arrives
        leaves a real gap of 200 rather than a jittered 146.
        """
        if node.frame is None or node.state is None or node.frame_stamp is None:
            return
        if node.frame_stamp == state["last_stamp"]:
            return                                    # the same picture again
        if state["next_sim"] is None:
            state["next_sim"] = node.frame_stamp
        # Walk the grid forward in whole ticks, never re-phase it. Resetting
        # the next tick to whatever picture turned up put the grid half a step
        # out and produced 50 ms followed by 150 -- right on average and wrong
        # in every row. A picture that never arrives should cost a whole tick,
        # so the gap reads 200.
        while node.frame_stamp > state["next_sim"] + GRID_TOL:
            state["next_sim"] += 1.0 / RECORD_HZ
        if node.frame_stamp < state["next_sim"] - GRID_TOL:
            return                                    # not on a tick
        age = time.time() - node.frame_seen
        node.max_frame_age = max(node.max_frame_age, age)
        # Everything in one sample must describe one instant. The width is
        # read off this picture, so the pose has to be the pose the arm was in
        # when this picture was taken, not the pose it is in now.
        st, skew, recv_skew, js_stamp = node.state_at(node.frame_stamp)
        if st is None or not np.isfinite(skew) or abs(skew) > SKEW_MAX:
            return
        p, R = node.ee_now(st)
        w = node.width_from_camera()
        if w is None:
            return
        # The timeline is the pictures' own, not the wall clock the recorder
        # woke up on. Every other field in the row belongs to this instant.
        if state["t0_img"] is None:
            state["t0_img"] = node.frame_stamp
        now = node.frame_stamp - state["t0_img"]
        rec["t"].append(now)
        rec["rgb"].append(mask_magenta(node.frame, node.tip))
        rec["eef_pos"].append(p)
        rec["eef_rot"].append(R)
        rec["width_cam"].append(w)
        rec["width_detected"].append(node.last_detect_ok)
        rec["frame_age"].append(age)
        rec["stamp_skew"].append(skew)
        rec["recv_skew"].append(recv_skew)
        rec["img_stamp"].append(node.frame_stamp)
        rec["js_stamp"].append(js_stamp)
        rec["width_gt"].append(node.gt_width(st))
        # Visibility is recorded on every frame, not only where the expert
        # asked, because the audit has to be able to check the leakage rule at
        # every frame rather than take the expert's word for it.
        rec["obj_vis"].append(node.visible("object", st))
        rec["bin_vis"].append(node.visible("bin", st))
        if VIDEO:
            rec["over"].append(node.overview())
        b = node.body_pose("object")
        rec["ball"].append(np.full(3, np.nan) if b is None else b)
        rec["stage"].append(state["stage"])
        if TRACE:
            print(f"    {state['stage']:16s} t={now:5.2f} "
                  f"obj={'Y' if rec['obj_vis'][-1] else '.'} "
                  f"bin={'Y' if rec['bin_vis'][-1] else '.'} "
                  f"cam={w*1000:6.2f} gt={rec['width_gt'][-1]*1000:6.2f} "
                  f"skew={skew*1000:+6.1f}ms",
                  flush=True)
        state["last_stamp"] = node.frame_stamp
        # Anchor to the picture actually used, so the grid follows the camera's
        # own small phase drift (it resets its period to "now" on the step that
        # is due, so it wanders by a control step now and then) instead of
        # slowly walking away from it.
        state["next_sim"] = node.frame_stamp + 1.0 / RECORD_HZ

    def drive(qlist, tlist, phase):
        state["stage"] = phase
        h, total = node.send(qlist, tlist)
        if h is False:
            return False
        rf = h.get_result_async()
        t0 = time.time()
        while time.time() - t0 < total + 6.0:
            rclpy.spin_once(node, timeout_sec=0.005)
            sample()
            if rf.done():
                break
        res = rf.result()
        for _ in range(4):
            node.spin(0.05)
            sample()
        return res is not None and res.result.error_code == 0

    def hold(phase, n_samples):
        """Stand still and keep recording. This is what makes the leakage rule
        true rather than merely intended: after a target first appears the arm
        waits one whole action horizon before anything moves towards it, so a
        chunk recorded while the target was invisible cannot reach into a
        target-directed action."""
        state["stage"] = phase
        got = len(rec["t"])
        t0 = time.time()
        while len(rec["t"]) - got < n_samples and \
                time.time() - t0 < n_samples / RECORD_HZ + 4.0:
            rclpy.spin_once(node, timeout_sec=0.005)
            sample()

    def fly(path, phase, label, scale=1.0, slow_tail=0):
        """`scale` stretches or compresses the whole segment; `slow_tail`
        lengthens the last waypoints so the tool arrives slowly.

        The expert already decelerates into the close -- 5.33, 2.69, 1.06,
        0.44, 0.15 mm per tick over the last half second -- but always from
        the same entry speed. Varying both is how the same stop gets seen
        from several approach speeds instead of one.
        """
        qs, why = project_path(node, path)
        if qs is None:
            return False, f"{label}: {why}"
        ts = [t * scale for t in timing(node, qs)]
        for j in range(min(slow_tail, len(ts))):
            ts[-1 - j] *= 1.0 + 0.6 * (slow_tail - j)
        if not drive(qs, ts, phase):
            return False, f"{label}: the controller did not reach the segment"
        return True, ""

    def azimuth_now():
        bx, by = node.cfg.robot_base_xy
        p, _ = node.ee_now()
        return math.atan2(-(p[0] - bx), p[1] - by)

    def search(body, phase):
        """Look around until `body` is in the crop. Never consults `body`."""
        if node.visible(body):
            hold(phase, ACTION_HORIZON)
            return True, ""
        legs = scan_legs(kin, node.cfg, azimuth_now())
        for i in range(0, len(legs), 2):
            chunk = legs[i:i + 2]
            ok, why = fly(chunk, phase, f"{phase.lower()} leg {i}")
            if not ok:
                return False, why
            if node.visible(body):
                hold(phase, ACTION_HORIZON)
                return True, ""
        return False, f"{phase.lower()}: swept the whole arc and never saw the {body}"

    # ---- HOME ------------------------------------------------------------
    # Homed with nothing recorded: the transit belongs to the reset, not to
    # the demonstration, and every episode's first frame has to be the same
    # pose. The clock starts once the arm is there.
    ok, why = node.go_home()
    if not ok:
        return False, f"home: {why}", None
    state["t0"] = time.time()
    state["next"] = 0.0
    state["t0_img"] = None
    state["next_sim"] = None
    state["last_stamp"] = None
    hold("HOME", 3)

    # ---- SEARCH_OBJECT ---------------------------------------------------
    ok, why = search("object", "SEARCH_OBJECT")
    if not ok:
        return False, why, None

    # ---- APPROACH_OBJECT, GRASP -----------------------------------------
    p_now, _ = node.ee_now()
    if "perturb_pitch_deg" in ep:
        # Fly to a pose that is wrong in the two ways the rollout is wrong,
        # stand there, then correct out of it. The stage label stays
        # APPROACH_OBJECT throughout: it is an approach, and what is being
        # taught is that this is a state you approach FROM.
        path, pitch = corrective_approach_path(kin, node.cfg, ep, p_now)
        if path is None:
            return False, "the perturbed pose is not reachable", None
        cut = next(i for i, w in enumerate(path) if w[0].startswith("correct"))
        ok, why = fly(path[:cut], "APPROACH_OBJECT", "approach to the wrong pose")
        if not ok:
            return False, why, None
        # the state with no support at all: standing still, nose too steep,
        # ball short of the fingers
        hold("APPROACH_OBJECT", ep["perturb_dwell"])
        ok, why = fly(path[cut:], "APPROACH_OBJECT", "correct into the funnel",
                      scale=ep["entry_scale"], slow_tail=3)
        if not ok:
            return False, why, None
    else:
        path, pitch = approach_path(kin, node.cfg, ep, p_now)
        ok, why = fly(path, "APPROACH_OBJECT", "approach")
        if not ok:
            return False, why, None
    state["stage"] = "GRASP"
    # Asynchronous on purpose: waiting for the gripper action blocks for most
    # of a second without recording, which puts a hole in the data at the one
    # moment the policy has to learn to close, and leaves the recorder behind.
    node.jaw(0.0, wait=False)
    hold("GRASP", 12)

    # ---- LIFT ------------------------------------------------------------
    ok, why = fly(lift_path(kin, node.cfg, ep), "LIFT", "lift")
    if not ok:
        return False, why, None

    # ---- SEARCH_BIN ------------------------------------------------------
    ok, why = search("bin", "SEARCH_BIN")
    if not ok:
        return False, why, None

    # ---- TRANSPORT, in legs, re-observing between them -------------------
    p_now, _ = node.ee_now()
    path, pitch = transport_path(kin, node.cfg, ep, p_now)
    for i in range(0, len(path), 4):
        ok, why = fly(path[i:i + 4], "TRANSPORT", f"transport leg {i}")
        if not ok:
            return False, why, None

    # ---- PLACE -----------------------------------------------------------
    ok, why = fly(place_path(kin, ep)[:1], "PLACE", "place")
    if not ok:
        return False, why, None
    state["stage"] = "PLACE"
    node.jaw(float(kin.grip_hi), wait=False)
    hold("PLACE", 12)

    # ---- RETREAT ---------------------------------------------------------
    ok, why = fly(retreat_path(kin, node.cfg, ep), "RETREAT", "retreat")
    if not ok:
        return False, why, None

    # Let the ball land before judging. Without this an episode that put the
    # ball dead centre was rejected for being 'too high': the last frame caught
    # it still in the air, and the height test is what says it is in the bin.
    state["stage"] = "SETTLE"
    t0 = time.time()
    while time.time() - t0 < 2.0:
        node.spin(0.05)
        sample()
        b = node.body_pose("object")
        if b is not None and len(rec["ball"]) > 6:
            recent = np.array(rec["ball"][-6:])
            if np.all(np.isfinite(recent)) and \
               float(np.abs(recent.max(0) - recent.min(0)).max()) < 0.001:
                break

    if len(rec["t"]) < 20:
        return False, (f"only {len(rec['t'])} frames were recorded; the "
                       f"observation could not be assembled"), None
    ball = np.array(rec["ball"])
    w_gt = np.array(rec["width_gt"])
    grasped = bool(np.nanmax(w_gt) > 0.005 and
                   np.nanmax(ball[:, 2]) > r + 0.04)
    bin_xy = np.array(ep["bin_xy"])
    final = ball[-1]
    c, sn = math.cos(-ep["bin_yaw"]), math.sin(-ep["bin_yaw"])
    d = final[:2] - bin_xy
    local = np.array([c * d[0] - sn * d[1], sn * d[0] + c * d[1]])
    placed = bool(abs(local[0]) < node.cfg.bin_inner / 2
                  and abs(local[1]) < node.cfg.bin_inner / 2
                  and 0.005 < final[2] < node.cfg.bin_outer)
    if not grasped:
        return False, "the ball never left the table", None
    if not placed:
        return False, f"the ball ended {np.round(local*1000,1)} mm from the bin centre", None
    ok, why = width_gate(rec)
    if not ok:
        return False, why, None

    p = pathlib.Path(out_dir) / f"episode_{index:04d}.npz"
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        p,
        # float64: the grid is exact to the microsecond and float32
        # rounds a 30 second timeline to about two of them
        t=np.array(rec["t"], np.float64),
        rgb=np.array(rec["rgb"], np.uint8),
        eef_pos=np.array(rec["eef_pos"], np.float32),
        eef_rot=np.array(rec["eef_rot"], np.float32),
        # the policy's width: estimated from the camera, as at run time
        gripper_width=np.array(rec["width_cam"], np.float32),
        # evaluation metadata only -- the converter must not put these in obs
        eval_gripper_width_gt=np.array(rec["width_gt"], np.float32),
        eval_ball_pos=np.array(rec["ball"], np.float32),
        stage=np.array(rec["stage"]),
        # True where the width above is a fresh camera measurement rather than
        # the last one held over a failed detection
        eval_width_detected=np.array(rec["width_detected"], bool),
        eval_frame_age=np.array(rec["frame_age"], np.float32),
        # joint-state stamp minus image stamp, per sample: how far apart the
        # two halves of one observation actually were
        eval_stamp_skew=np.array(rec["stamp_skew"], np.float32),
        # the same difference measured on arrival instead of on the stamps;
        # this one carries transport latency and the two are not the same thing
        eval_recv_skew=np.array(rec["recv_skew"], np.float32),
        # the two stamps themselves, so the pairing can be audited row by row
        eval_image_stamp=np.array(rec["img_stamp"], np.float64),
        eval_joint_stamp=np.array(rec["js_stamp"], np.float64),
        # what the expert was allowed to know, frame by frame: whether the
        # thing was inside the square the policy is handed
        eval_object_visible=np.array(rec["obj_vis"], bool),
        eval_bin_visible=np.array(rec["bin_vis"], bool),
        eval_home_q=HOME_Q.astype(np.float32),
        eval_action_horizon=np.int32(ACTION_HORIZON),
        spec=json.dumps(ep))
    if VIDEO:
        vp = pathlib.Path(VIDEO)
        vp.mkdir(parents=True, exist_ok=True)
        write_video(rec, vp / f"{p.stem}.mp4", ep)
    return True, f"{len(rec['t'])} frames", p


@click.command()
@click.option("--split", type=click.Choice(["train", "val"]), default="train")
@click.option("--n-episodes", default=20, type=int)
@click.option("--seed", default=None, type=int)
@click.option("--out-dir", default=None)
@click.option("--max-tries", default=60, type=int)
@click.option("--perturb/--no-perturb", default=False,
              help="corrective episodes: start from a pose that is wrong in "
                   "pitch and insertion, stand there, then correct into the "
                   "same grasp funnel the clean set ends in")
@click.option("--intermediate/--grid", default=False,
              help="use the 3x3 cells BETWEEN the training ones, so the "
                   "validation split cannot be answered by remembering them")
@click.option("--cell-offset", default=0, type=int,
              help="rotate the cell schedule, so a validation split starts "
                   "somewhere the training split did not")
@click.option("--replay", default=None,
              help="a directory of episode_*.npz: re-run THOSE specs instead of "
                   "drawing new ones, so a video shows the episode that is in "
                   "the dataset and not a fresh one that resembles it")
def main(split, n_episodes, seed, out_dir, max_tries, perturb, intermediate,
         cell_offset, replay):
    rclpy.init()
    node = Demos()
    node.spin(2.0)
    cfg = node.cfg
    ball_r = float(cfg.object_size[0])
    # Separate seed streams, so a validation placement is one the training set
    # has not seen rather than one outside the range it was taught.
    seed = seed if seed is not None else (17 if split == "train" else 9001)
    rng = np.random.default_rng(seed)
    out = pathlib.Path(out_dir or (SIM / "data" / "demos" / split))
    click.secho(f"ball {ball_r*2000:.0f} mm   split {split}   seed {seed}   -> {out}",
                bold=True)

    saved = None
    if replay:
        saved = [json.loads(str(np.load(f, allow_pickle=True)["spec"]))
                 for f in sorted(pathlib.Path(replay).glob("episode_*.npz"))]
        saved = saved[:n_episodes]
        click.secho(f"replaying {len(saved)} saved episodes from {replay}",
                    bold=True)

    ok, why = node.go_home()
    if not ok:
        raise click.ClickException(f"could not reach HOME to begin: {why}")

    kept, tries, rows = 0, 0, []
    while kept < n_episodes and tries < max_tries:
        tries += 1
        if saved is not None:
            if not saved:
                break
            ep = saved.pop(0)
        elif perturb:
            # Walk the grid rather than draw from it, so every cell is covered
            # the same number of times and the count below is a fact about the
            # set and not about a random seed. The repeat index picks the
            # entry speed, so each cell is seen slow, ordinary and brisk, and
            # the placement is redrawn every time.
            grid = ([(pd, wd) for pd in PERTURB_PITCH_DEG
                     for wd in PERTURB_TOOL_DEPTH_MM] if not intermediate
                    else [(pd, wd) for pd in PERTURB_PITCH_MID
                          for wd in PERTURB_TOOL_DEPTH_MID])
            i = kept + cell_offset
            pd, wd = grid[i % len(grid)]
            ep = sample_episode(rng, cfg, ball_r,
                                cell=(pd, wd,
                                      ENTRY_SCALES[(i // len(grid))
                                                   % len(ENTRY_SCALES)]))
        else:
            ep = sample_episode(rng, cfg, ball_r)
        ok, why, p = run_episode(node, ep, rng, out, kept)
        # Whatever happened, put the arm and the jaw back before the next
        # attempt, so a rejected candidate cannot hand its pose on.
        node.jaw(float(node.kin.grip_hi))
        home_ok, home_why = node.go_home()
        if not home_ok:
            click.secho(f"      could not reset: {home_why}", fg="red")
        rows.append({"try": tries, "accepted": ok, "reason": why, **{
            k: (list(v) if isinstance(v, tuple) else v) for k, v in ep.items()}})
        click.secho(f"  [{tries:3d}] {'ACCEPT' if ok else 'reject'}  {why}",
                    fg="green" if ok else "yellow")
        kept += int(ok)
    (out / "collection_log.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "collection_log.json").write_text(json.dumps(
        {"split": split, "seed": seed, "ball_diameter_m": ball_r * 2,
         "accepted": kept, "tries": tries,
         "record_hz": RECORD_HZ, "max_joint_vel": MAX_JOINT_VEL,
         "max_frame_age_s": round(node.max_frame_age, 4),
         "episodes": rows}, indent=2))
    click.secho(f"\naccepted {kept}/{tries}", bold=True)
    node.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
