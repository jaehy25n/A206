"""One closed loop: MuJoCo observation -> the trained checkpoint -> MuJoCo.

    python sim_umi/ros/policy_bridge.py --cycles 1

This connects, it does not improve. No scripted motion is mixed into the
policy's output, no ground truth from the simulator reaches the policy, and
nothing about the handoff contract is reinterpreted -- every rule below is
quoted from jetson_handoff/model_manifest.json, which was written from the
training code itself:

    rot6d               first two ROWS of R_rel, row-major
    rotation recovery   R_abs = R_base @ R_rel     (left-multiply)
    position recovery   p_abs = R_base @ p_rel + p_base
    base pose           the LAST observation frame
    gripper             absolute width in metres, untransformed
    rgb                 RGB, centre square, cv2.INTER_AREA -> 224, /255 -> [0,1], CHW
    action_dt_s         0.1        first_action_offset_s  0.0

The one thing that is NOT bit-identical to the Jetson path is the colour
conversion: that contract starts from cv2.imread, which hands back BGR and has
to be converted. MuJoCo renders RGB already, so the correct equivalent of
"convert to RGB" here is to do nothing, and doing the cvtColor anyway would
swap the channels the policy was trained on.
"""
import math
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import collections
import io
import socket
import struct

import click
import cv2
import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from scipy.spatial.transform import Rotation
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectoryPoint

import mujoco  # noqa: E402
import scene_objects  # noqa: E402
from collector import Collector  # noqa: E402
from scene import SceneConfig  # noqa: E402

ARM = [f"joint{i}" for i in range(1, 6)]
HANDOFF = ROOT / "jetson_handoff"


# ----------------------------------------------------------------- contract --
def preprocess_rgb(rgb: np.ndarray, out: int = 224) -> np.ndarray:
    """The manifest's rgb_preprocess, in order, on an already-RGB frame."""
    h, w = rgb.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    crop = rgb[y0:y0 + side, x0:x0 + side]
    small = cv2.resize(crop, (out, out), interpolation=cv2.INTER_AREA)
    return np.moveaxis(small.astype(np.float32) / 255.0, -1, 0)


def policy_image(masked, geometry="g0_center224"):
    """The picture the policy is sent, for the geometry its checkpoint was
    trained with. G0 is preprocess_rgb itself, untouched; G1/G2 come from
    rgb_geometry, the same module their training frames were built with.
    Returns (CHW float32 in [0, 1], the uint8 canvas it was made from)."""
    if geometry == "g0_center224":
        # exactly the definitive path, nothing computed besides it; the canvas
        # is rgb_geometry.apply(masked), reproducible after the fact
        return preprocess_rgb(masked), None
    import rgb_geometry
    canvas = rgb_geometry.apply(geometry, masked)
    return rgb_geometry.to_chw_float(canvas), canvas


class _AlignedState:
    """A joint state at an instant no message was delivered for."""
    __slots__ = ("name", "position")

    def __init__(self, name, position):
        self.name = name
        self.position = position


def rot6d_to_mat(six: np.ndarray) -> np.ndarray:
    """Gram-Schmidt on the first two ROWS. Third row is their cross product."""
    a1, a2 = np.asarray(six[:3], float), np.asarray(six[3:6], float)
    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - (b1 @ a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    return np.stack([b1, b2, np.cross(b1, b2)], axis=0)


def decode_action(a10: np.ndarray, base_pos: np.ndarray, base_rot: np.ndarray):
    """One action row -> absolute (position, rotation, gripper width)."""
    R_rel = rot6d_to_mat(a10[3:9])
    R_abs = base_rot @ R_rel                      # left-multiply, per contract
    p_abs = base_rot @ np.asarray(a10[:3], float) + base_pos
    return p_abs, R_abs, float(a10[9])


# ------------------------------------------------------------------ runtime --
class Bridge(Node):
    """Observation from ros2_control + MuJoCo, action back to the same place."""

    def __init__(self, sock_path):
        super().__init__("policy_bridge")
        self.cfg = SceneConfig()
        # A second copy of the model, used ONLY for kinematics: FK of the
        # measured joint angles, the jaw table, and the IK projection. It is
        # never read for object or contact state -- that would be the ground
        # truth this is forbidden to feed the policy.
        self.kin = Collector(str(SIM / "mjcf" / "collector_scene.xml"),
                             cfg=self.cfg, render=False)
        self.state = None
        self.frame = None
        self.frame_stamp = None
        self.js_buf = collections.deque(maxlen=400)
        # every camera frame of the last few seconds, by its simulation stamp:
        # an observation pair is picked from here by stamp, not by when a
        # wall-clock wait happened to end
        self.frame_buf = collections.deque(maxlen=60)
        # Joint states for OBSERVATION ALIGNMENT come from a separate process
        # (state_recorder.py) that keeps every message: this loop stops
        # handling callbacks for ~200 ms while it projects a plan, and a
        # buffering thread here would slow the loop itself (GIL). Nothing on
        # the action side reads the recorder.
        self._rec = None
        # Keep only the newest of each. A deep queue here is what let the
        # collector pair a stale picture with a fresh joint state and read the
        # gripper as open through an entire grasp; the width in this loop is
        # read off the same picture, so it would freeze the same way.
        fresh = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                           reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(JointState, "/joint_states", self._state, fresh)
        self.create_subscription(Image, "/wrist_camera/image_raw", self._image, fresh)
        self.arm = ActionClient(self, FollowJointTrajectory,
                                "/arm_controller/follow_joint_trajectory")
        self.grip = ActionClient(self, GripperCommand,
                                 "/gripper_controller/gripper_cmd")
        assert self.arm.wait_for_server(timeout_sec=30), "no arm_controller"
        assert self.grip.wait_for_server(timeout_sec=30), "no gripper_controller"
        # The environment goes into MoveIt's scene when move_group is up, so
        # a projected action can be checked before it is executed. The loop
        # does not depend on it: the projection and the IK are ours.
        try:
            scene_objects.apply(self, self.cfg, timeout=8.0)
            self.scene_ok = True
        except RuntimeError as e:
            self.scene_ok = False
            print(f"   (no planning scene: {e})")
        self.policy, self.meta = self._load(sock_path)
        self.start_pose = None
        # The width the policy sees is ESTIMATED FROM THE CAMERA, the way the
        # collector got it -- not read off the joint. The training data has no
        # encoder in it, and the simulator's own jaw width is privileged
        # information: it is kept, but only to score the estimate against.
        import json as _json
        from gripper_vision import TipDetectorConfig
        cal = SIM / "assets" / "gripper_calibration.json"
        if not cal.is_file():
            raise RuntimeError("no gripper_calibration.json; run "
                               "scripts/fit_gripper_vision.py --freeze")
        self.cal = _json.loads(cal.read_text())["scale"]
        self.tip_cfg = TipDetectorConfig()
        self.last_width = None
        self.width_misses = 0

    def _load(self, sock_path):
        """The manifest here, the weights in the other process."""
        import json
        meta = json.loads((HANDOFF / "model_manifest.json").read_text())
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(sock_path)
        # The server writes what it loaded next to its socket: the checkpoint,
        # the weights and the image geometry that checkpoint was trained on.
        # No sidecar means a server from before the FOV work: G0.
        side = pathlib.Path(sock_path + ".meta.json")
        self.server_meta = json.loads(side.read_text()) if side.is_file() else None
        self.rgb_geometry = (self.server_meta or {}).get("rgb_geometry", "g0_center224")
        self.frame_log = {}          # image stamp -> (masked frame, canvas), per episode
        self.req_id = 0
        return None, meta

    # ------------------------------------------------------------- sensing --
    def state_at(self, stamp):
        """The joint state from the instant a picture was taken.

        The same alignment the collector records with. Both are stamped on
        the plant's simulation clock, so they are matched by their own stamps
        and nothing is assumed between two clocks. Taking the newest joint
        state instead would put the arm in the observation ahead of the arm in
        the picture -- the camera publishes at 18 Hz -- and the policy was not
        trained on that.
        """
        if stamp is None or not self.js_buf:
            return self.state
        i = int(np.argmin([abs(t - stamp) for t, _ in self.js_buf]))
        return self.js_buf[i][1]

    def state_at_aligned(self, stamp):
        """The joint state AT a picture's stamp, the way the collector built
        its training rows (collect_demos.Demos.state_at): the message with that
        exact stamp, else linear interpolation between the two that bracket
        it. state_at above takes the nearest message instead -- up to a few ms
        of arm motion off the picture, which the training data never had.
        Returns (state, info); info["mode"] is exact | interp | nearest, and
        "nearest" is a fallback that is recorded, never hidden."""
        r = self._recorder_lookup(stamp) if stamp is not None else None
        if r is not None and r.get("mode") in ("exact", "interp", "nearest"):
            info = {k: r[k] for k in ("mode", "state_stamp_s", "skew_s") if k in r}
            info["source"] = "recorder"
            if "bracket_s" in r:
                info["bracket_s"] = r["bracket_s"]
            return _AlignedState(r["names"], r["position"]), info
        buf = list(self.js_buf)
        if stamp is None or not buf:
            return self.state, {"mode": "none", "state_stamp_s": None, "skew_s": None, "source": "local"}
        i = int(np.argmin([abs(t - stamp) for t, _ in buf]))
        t, m = buf[i]
        if abs(t - stamp) < 1e-6:
            return m, {"mode": "exact", "state_stamp_s": t, "skew_s": 0.0, "source": "local"}
        j = i - 1 if t > stamp else i + 1
        if 0 <= j < len(buf):
            t2, m2 = buf[j]
            lo, hi, t_lo, t_hi = (m, m2, t, t2) if t <= t2 else (m2, m, t2, t)
            if t_lo <= stamp <= t_hi and t_hi > t_lo:
                a = (stamp - t_lo) / (t_hi - t_lo)
                names = list(lo.name)
                hp = dict(zip(hi.name, hi.position))
                pos = [float(pv) + (float(hp[n]) - float(pv)) * a for n, pv in zip(names, lo.position)]
                return _AlignedState(names, pos), {"mode": "interp", "state_stamp_s": stamp, "skew_s": 0.0,
                                                    "bracket_s": [t_lo, t_hi],
                                                    "bracket_rel_ms": [round((t_lo - stamp) * 1000, 2), round((t_hi - stamp) * 1000, 2)],
                                                    "js_within_50ms": sum(1 for tt, _ in buf if abs(tt - stamp) < 0.05),
                                                    "js_buf_span_s": [round(buf[0][0] - stamp, 3), round(buf[-1][0] - stamp, 3)],
                                                    "js_buf_len": len(buf), "source": "local"}
        return m, {"mode": "nearest", "state_stamp_s": t, "skew_s": t - stamp, "source": "local"}

    def obs_frames(self):
        """A snapshot of the image buffer the observation pair is picked from."""
        return list(self.frame_buf)

    def _recorder_lookup(self, stamp):
        """The joint state at `stamp` from state_recorder.py, or None when no
        recorder is running (then the local buffer is used, and says so)."""
        import json as _json
        import os as _os
        if self._rec is None:
            path = _os.environ.get("OMX_STATE_RECORDER", "/tmp/omx_state_recorder.sock")
            if not _os.path.exists(path):
                self._rec = False
            else:
                c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                c.connect(path)
                self._rec = c.makefile("rwb")
        if self._rec is False:
            return None
        self._rec.write((_json.dumps({"stamp": float(stamp)}) + "\n").encode())
        self._rec.flush()
        return _json.loads(self._rec.readline())

    def observe_at(self, stamp):
        """observe(), for the frame with a given simulation stamp and the joint
        state aligned to that same stamp. If no buffered frame carries the
        stamp, the nearest one is used and the plan is marked, not silently
        mended."""
        from gripper_vision import mask_magenta
        fbuf = self.obs_frames()
        hit = next(((t, f) for t, f in reversed(fbuf) if abs(t - stamp) < 1e-4), None)
        if hit is not None:
            (used, raw), exact = hit, True
        else:
            used, raw = min(fbuf, key=lambda x: abs(x[0] - stamp))
            exact = False
        width, pixel_gap = self.jaw_from_camera(raw)
        if width is None:
            raise RuntimeError("the tips were not visible in the first frame, "
                               "so there is no camera-derived width to use")
        img = mask_magenta(raw, self.tip_cfg)
        st, sinfo = self.state_at_aligned(used)
        p, R = self.ee_now(st)
        if self.start_pose is None:
            self.start_pose = (p.copy(), R.copy())
        rgb, canvas = policy_image(img, getattr(self, "rgb_geometry", "g0_center224"))
        if getattr(self, "frame_log", None) is not None and used not in self.frame_log:
            self.frame_log[used] = (img, canvas)
        info = {"image_stamp_s": used, "requested_stamp_s": stamp, "frame_exact": exact, **sinfo}
        return ({"rgb": rgb, "pos": p, "rot": R, "grip": np.float32(width),
                 "_gt_width": self.jaw_now_gt(), "_pixel_gap": pixel_gap}, img, info, st)

    def _state(self, msg):
        self.state = msg
        self.js_buf.append(
            (msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, msg))

    def _image(self, msg):
        if msg.encoding != "rgb8":
            raise RuntimeError(f"expected rgb8 from the camera, got {msg.encoding}")
        self.frame = np.frombuffer(msg.data, np.uint8).reshape(
            msg.height, msg.width, 3).copy()
        self.frame_stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        if getattr(self, "frame_buf", None) is not None:
            self.frame_buf.append((self.frame_stamp, self.frame))

    def spin(self, seconds):
        t0 = time.time()
        while time.time() - t0 < seconds:
            rclpy.spin_once(self, timeout_sec=0.01)

    def q_now(self, state=None):
        st = self.state if state is None else state
        n = list(st.name)
        return np.array([st.position[n.index(j)] for j in ARM])

    def jaw_now_gt(self):
        """The simulator's jaw width, through the measured jaw table.

        GROUND TRUTH. Used to score the camera estimate and for nothing else --
        it never reaches the policy.
        """
        n = list(self.state.name)
        q = self.state.position[n.index("gripper_joint_1")]
        return float(np.interp(q, self.kin._theta_tab, self.kin._width_tab))

    def jaw_from_camera(self, raw):
        """What the collector measures: the pixel gap between the two patches,
        through the frozen calibration."""
        from gripper_vision import detect_tips
        det = detect_tips(raw, self.tip_cfg)
        if det["pixel_gap"] is None:
            self.width_misses += 1
            return self.last_width, None
        w = float(self.cal["a"] * det["pixel_gap"] + self.cal["b"])
        self.last_width = w
        return w, float(det["pixel_gap"])

    def width_sample(self):
        """The camera's width right now, and whether it is a measurement.

        Separate from jaw_from_camera on purpose: this is sampled at the
        camera's own rate to judge whether the jaw has settled, and it must
        not touch last_width or width_misses, which belong to the observation
        path. A frame the detector could not read returns (None, False) and
        is not a width at all -- it must not be counted as a steady one.
        """
        from gripper_vision import detect_tips
        if self.frame is None:
            return None, False
        det = detect_tips(self.frame, self.tip_cfg)
        if det["pixel_gap"] is None:
            return None, False
        return float(self.cal["a"] * det["pixel_gap"] + self.cal["b"]), True

    def ee_now(self, state=None):
        """FK of the measured joint angles -> (position, rotation)."""
        d = self.kin._ik
        d.qpos[:] = self.kin.data.qpos
        for a, v in zip(self.kin.arm_qadr, self.q_now(state)):
            d.qpos[a] = v
        mujoco.mj_kinematics(self.kin.model, d)
        p = d.site_xpos[self.kin.tcp_sid].copy()
        R = np.asarray(d.site_xmat[self.kin.tcp_sid]).reshape(3, 3).copy()
        return p, R

    def observe(self):
        """One raw frame. The policy's keys are built later, in build_batch,
        because they are all relative to the LAST frame of the window."""
        from gripper_vision import mask_magenta
        raw = self.camera_frame()
        width, pixel_gap = self.jaw_from_camera(raw)
        if width is None:
            # Nothing to fall back on yet. Using the simulator's width here
            # would be exactly the leak this is written to avoid, so say so.
            raise RuntimeError("the tips were not visible in the first frame, "
                               "so there is no camera-derived width to use")
        img = mask_magenta(raw, self.tip_cfg)
        p, R = self.ee_now(self.state_at(self.frame_stamp))
        if self.start_pose is None:
            self.start_pose = (p.copy(), R.copy())
        rgb, canvas = policy_image(img, getattr(self, "rgb_geometry", "g0_center224"))
        if getattr(self, "frame_log", None) is not None and self.frame_stamp not in self.frame_log:
            self.frame_log[self.frame_stamp] = (img, canvas)
        return {"rgb": rgb, "pos": p, "rot": R,
                "grip": np.float32(width),
                "_gt_width": self.jaw_now_gt(), "_pixel_gap": pixel_gap}, img

    def build_batch(self, frames):
        """The five observation keys, exactly as umi_dataset builds them.

        Both pose keys are RELATIVE, not absolute: the dataset takes
        inv(T[-1]) @ T[k] and writes the translation into robot0_eef_pos and
        the first two rows of the rotation into robot0_eef_rot_axis_angle --
        which therefore holds rot6d, not an axis-angle, despite the name.
        _wrt_start is the same construction against the episode's first pose.
        """
        def mat(p, R):
            T = np.eye(4)
            T[:3, :3], T[:3, 3] = R, p
            return T

        T = [mat(f["pos"], f["rot"]) for f in frames]
        T_last_inv = np.linalg.inv(T[-1])
        sp, sR = self.start_pose
        T_start_inv = np.linalg.inv(mat(sp, sR))
        pos, rot6, wrt = [], [], []
        for Tk in T:
            rel = T_last_inv @ Tk
            pos.append(rel[:3, 3])
            rot6.append(rel[:2, :3].reshape(6))         # first two ROWS
            wrt.append((T_start_inv @ Tk)[:2, :3].reshape(6))
        return {
            # only the five keys the policy declares; _gt_width and _pixel_gap
            # stay out of the batch on purpose
            "camera0_rgb": np.stack([f["rgb"] for f in frames])[None],
            "robot0_eef_pos": np.stack(pos)[None].astype(np.float32),
            "robot0_eef_rot_axis_angle": np.stack(rot6)[None].astype(np.float32),
            "robot0_eef_rot_axis_angle_wrt_start":
                np.stack(wrt)[None].astype(np.float32),
            "robot0_gripper_width":
                np.array([[f["grip"]] for f in frames])[None].astype(np.float32),
        }

    def camera_frame(self):
        """The plant's own camera, unmasked.

        mujoco_ros2_control's CameraPlugin renders from the same mjModel and
        mjData the controllers act on, so the ball, the contacts and anything
        else that moves are in the picture without a second simulation to keep
        in step. Before the overlay build this was a mirror posed from
        /joint_states, and the ball in it never moved from where the MJCF put
        it -- fine for one cycle, useless for a rollout.

        Returned RAW, because the width has to be read off the patches before
        they are painted out.
        """
        if self.frame is None:
            raise RuntimeError("no image on /wrist_camera/image_raw")
        return self.frame

    # ------------------------------------------------------------- acting --
    def infer(self, obs_frames, req_id=None):
        """obs_horizon frames -> (1, 16, 10), computed by the policy process."""
        batch = self.build_batch(obs_frames)
        buf = io.BytesIO()
        if req_id is None:
            self.req_id = getattr(self, "req_id", 0) + 1
            req_id = self.req_id
        # "_" keys never reach the policy: the server strips them
        np.savez(buf, **batch, _req_id=np.array([req_id], np.int64))
        body = buf.getvalue()
        t_send = time.time()
        self.sock.sendall(struct.pack("!I", len(body)) + body)
        head = self.sock.recv(4)
        if len(head) < 4:
            raise RuntimeError("the policy process closed the connection")
        n = struct.unpack("!I", head)[0]
        data = b""
        while len(data) < n:
            data += self.sock.recv(n - len(data))
        if not hasattr(self, "req_timing"):
            self.req_timing = {}
        self.req_timing[req_id] = {"send_wall": t_send, "recv_wall": time.time()}
        return np.load(io.BytesIO(data)), batch

    def project_5dof(self, p_abs, R_abs):
        """The arm cannot hold an arbitrary frame; give it the nearest one.

        Five joints spend three on position and leave a two-dimensional set of
        orientations, and the direction missing from it is the tool's own +z.
        So the yaw is whatever the base angle makes it and only the pitch is
        ours to ask for. The pitch asked for is the one in the policy's own
        rotation, read off its tool y axis.
        """
        fwd = R_abs[:, 1]                       # the finger axis
        pitch = float(math.asin(max(-1.0, min(1.0, -fwd[2]))))
        q, ep, er, oop = self.kin.solve_ik_best(p_abs, pitch)
        d = self.kin._ik
        for a, v in zip(self.kin.arm_qadr, q):
            d.qpos[a] = v
        mujoco.mj_kinematics(self.kin.model, d)
        p_got = d.site_xpos[self.kin.tcp_sid].copy()
        R_got = np.asarray(d.site_xmat[self.kin.tcp_sid]).reshape(3, 3).copy()
        return q, p_got, R_got, dict(pos_err_mm=ep * 1000,
                                     pitch_err_deg=math.degrees(er),
                                     out_of_plane_mm=oop * 1000,
                                     asked_pitch_deg=math.degrees(pitch))

    def execute(self, q, gripper_width, seconds=0.5):
        traj = FollowJointTrajectory.Goal()
        traj.trajectory.joint_names = ARM
        pt = JointTrajectoryPoint()
        pt.positions = [float(v) for v in q]
        pt.time_from_start.sec = int(seconds)
        pt.time_from_start.nanosec = int((seconds % 1) * 1e9)
        traj.trajectory.points.append(pt)
        fa = self.arm.send_goal_async(traj)
        rclpy.spin_until_future_complete(self, fa, timeout_sec=5.0)
        h = fa.result()
        ok = False
        if h is not None and h.accepted:
            rf = h.get_result_async()
            rclpy.spin_until_future_complete(self, rf, timeout_sec=seconds + 10)
            ok = rf.result() is not None and rf.result().result.error_code == 0
        # the gripper command is the policy's own tenth number, a width in
        # metres, turned into the joint angle that opens the jaw that far
        theta = float(np.interp(gripper_width, self.kin._width_tab,
                                self.kin._theta_tab))
        g = GripperCommand.Goal()
        g.command.position = theta
        g.command.max_effort = 0.5
        fg = self.grip.send_goal_async(g)
        rclpy.spin_until_future_complete(self, fg, timeout_sec=5.0)
        hg = fg.result()
        if hg is not None and hg.accepted:
            rg = hg.get_result_async()
            rclpy.spin_until_future_complete(self, rg, timeout_sec=10)
        return ok, theta


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--cycles", default=1, type=int)
def main(socket_path, cycles):
    rclpy.init()
    b = Bridge(socket_path)
    b.spin(1.5)
    man = b.meta
    click.secho("\n1. checkpoint", bold=True)
    click.echo(f"   {man['checkpoint']}")
    click.echo(f"   epoch {man['checkpoint_epoch']}  global_step "
               f"{man['checkpoint_global_step']}  weights {man['checkpoint_weights']}")
    click.echo(f"   obs_horizon {man['obs_horizon']}  action_horizon "
               f"{man['action_horizon']}  action_dim {man['action_dim']}  "
               f"diffusion steps {man['diffusion_steps']}")
    click.secho("   INTEGRATION ONLY: this is the smoke checkpoint "
                "(1 epoch, 7 steps). It is not expected to do the task.",
                fg="yellow")

    dt = man["action_dt_s"]
    for cycle in range(cycles):
        click.secho(f"\n=== cycle {cycle} ===", bold=True)
        frames = []
        for i in range(man["obs_horizon"]):
            f, img = b.observe()
            frames.append(f)
            if i == 0:
                click.secho("2. one RGB frame through the contract", bold=True)
                click.echo(f"   raw        {img.shape} {img.dtype} "
                           f"[{img.min()}, {img.max()}]")
                r = f["rgb"]
                click.echo(f"   preprocessed {r.shape} {r.dtype} "
                           f"[{r.min():.3f}, {r.max():.3f}]  (CHW, [0,1])")
            if i + 1 < man["obs_horizon"]:
                b.spin(dt)
        click.secho("3. state vector  (relative to the last frame, "
                    "rot6d = first two rows)", bold=True)
        f = frames[-1]
        click.echo(f"   gripper width   detected (camera) "
                   f"{float(f['grip'])*1000:7.3f} mm"
                   + (f"   [pixel gap {f['_pixel_gap']:.1f}]"
                      if f["_pixel_gap"] is not None else "   [tips not seen]"))
        click.echo(f"                   GT (jaw table)    "
                   f"{f['_gt_width']*1000:7.3f} mm   "
                   f"error {(float(f['grip'])-f['_gt_width'])*1000:+.3f} mm")
        shown = b.build_batch(frames)
        for k in ("robot0_eef_pos", "robot0_eef_rot_axis_angle",
                  "robot0_eef_rot_axis_angle_wrt_start", "robot0_gripper_width"):
            click.echo(f"   {k:36s} {tuple(shown[k].shape)}  last = "
                       f"{np.round(shown[k][0, -1], 5)}")
        same = abs(float(shown["robot0_gripper_width"][0, -1, 0])
                   - float(f["grip"])) < 1e-9
        click.secho(f"   policy input width == detected: {same}",
                    fg="green" if same else "red")

        act, batch = b.infer(frames)
        click.secho("4. policy output", bold=True)
        click.echo(f"   action_pred {act.shape}   "
                   f"pos [{act[0,:,:3].min():+.4f}, {act[0,:,:3].max():+.4f}]  "
                   f"rot6d [{act[0,:,3:9].min():+.4f}, {act[0,:,3:9].max():+.4f}]  "
                   f"grip [{act[0,:,9].min():+.4f}, {act[0,:,9].max():+.4f}]")

        p0, R0 = b.ee_now()
        p_cmd, R_cmd, g_cmd = decode_action(act[0, 0], p0, R0)
        click.secho("5. first action decoded  (R_abs = R_base @ R_rel)", bold=True)
        click.echo(f"   base pose      p {np.round(p0*1000,2)} mm")
        click.echo(f"   commanded      p {np.round(p_cmd*1000,2)} mm   "
                   f"move {np.linalg.norm(p_cmd-p0)*1000:.2f} mm")
        click.echo(f"   commanded jaw  {g_cmd*1000:.2f} mm")

        jaw_lo, jaw_hi = float(b.kin._width_tab.min()), float(b.kin._width_tab.max())
        g_exec = float(np.clip(g_cmd, jaw_lo, jaw_hi))
        q, p_got, R_got, err = b.project_5dof(p_cmd, R_cmd)
        dp = (p_got - p_cmd) * 1000
        dang = math.degrees(np.arccos(np.clip(
            (np.trace(R_cmd.T @ R_got) - 1) / 2, -1, 1)))
        click.secho("6. 5DoF projection  (policy asked | arm can hold)", bold=True)
        click.echo(f"   position   moved by {np.linalg.norm(dp):.3f} mm  {np.round(dp,3)}")
        click.echo(f"   rotation   turned by {dang:.3f} deg "
                   f"(asked pitch {err['asked_pitch_deg']:+.2f})")
        click.echo(f"   ik         pos err {err['pos_err_mm']:.4f} mm, pitch err "
                   f"{err['pitch_err_deg']:.4f} deg, off-plane "
                   f"{err['out_of_plane_mm']:.4f} mm")
        ok_ik = err["pos_err_mm"] < 1.0
        click.secho(f"   IK {'solved' if ok_ik else 'FAILED'}",
                    fg="green" if ok_ik else "red")

        # Rule: what the policy asked for and what is actually sent are both on
        # the record, and an action the arm cannot reach is NOT sent. A failed
        # IK means the solver stopped at its closest approach, and executing
        # that is executing a pose nobody chose.
        click.secho("   policy asked   vs   what would be executed", bold=True)
        click.echo(f"     position  {np.round(p_cmd*1000,2)}  ->  "
                   f"{np.round(p_got*1000,2)} mm")
        click.echo(f"     jaw       {g_cmd*1000:+.2f}  ->  {g_exec*1000:+.2f} mm"
                   + ("   CLAMPED to the jaw's range" if abs(g_exec-g_cmd) > 1e-9
                      else ""))
        if not ok_ik:
            click.secho("7. NOT executed: the projection could not reach the "
                        "policy's target, so there is nothing faithful to send",
                        fg="red", bold=True)
            ok, theta = False, float("nan")
        else:
            ok, theta = b.execute(q, g_exec)
            click.secho("7. executed through ros2_control", bold=True)
            click.echo(f"   arm_controller {'reached' if ok else 'FAILED'}   "
                       f"gripper commanded {math.degrees(theta):.2f} deg "
                       f"({g_exec*1000:.1f} mm)")

        b.spin(0.3)
        p1, _ = b.ee_now()
        click.secho("8. next observation", bold=True)
        click.echo(f"   EE now     {np.round(p1*1000,2)} mm   "
                   f"moved {np.linalg.norm(p1-p0)*1000:.2f} mm since the base pose")
        w_cam, _ = b.jaw_from_camera(b.camera_frame())
        click.echo(f"   jaw now    {w_cam*1000:.2f} mm from the camera, "
                   f"{b.jaw_now_gt()*1000:.2f} mm ground truth")
        click.secho("   loop closed", fg="green")

    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
