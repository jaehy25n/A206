"""Does the renderer's +-1-level / <= 4 px nondeterminism change what G0 does? (offline)

    /home/j-j15a206/.conda/envs/umi/bin/python sim_umi/scripts/dse/render_noise_policy_test.py \
        --frames <reset_state dir>/frames.npz --snap-json <reset_state dir>/reset_state_test.json --out <stem>

Pairs of renders of the SAME state (rep0 vs rep1 of the canonical-reset test, identical
joints) are fed to the G0 policy server with IDENTICAL low-dim input (built from the same
joint state; the camera width taken from rep 0 for both). Compared: raw action (16x10), the
decoded positions / rotations / gripper widths, and the discrete decisions downstream -- IK
reachability of every waypoint (the runtime 2 mm gate) and the jaw width change against the
3 mm send threshold. The camera width each render would give is reported separately.
"""
import io
import json
import math
import pathlib
import socket
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sim_umi/src"), str(ROOT / "sim_umi/ros"), str(ROOT)]
import click
import numpy as np

HOME_Q = [0.728554, -0.484702, -0.429863, 1.699963, 0.0]


def infer(sock, batch, rid):
    buf = io.BytesIO()
    np.savez(buf, **batch, _req_id=np.array([rid], np.int64))
    body = buf.getvalue()
    sock.sendall(struct.pack("!I", len(body)) + body)
    n = struct.unpack("!I", sock.recv(4))[0]
    data = b""
    while len(data) < n:
        data += sock.recv(n - len(data))
    return np.load(io.BytesIO(data))


@click.command()
@click.option("--frames", required=True)
@click.option("--pairs", default="0,50;25,75;100,150;125,175;250,300", help="obs pairs (tick t-0.1, tick t)")
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--out", required=True)
def main(frames, pairs, socket_path, out):
    from collector import Collector
    from scene import SceneConfig
    from gripper_vision import TipDetectorConfig, detect_tips, mask_magenta
    # policy_bridge imports rclpy (absent in this env): take its pure functions from its source
    import ast
    import cv2
    src = (ROOT / "sim_umi/ros/policy_bridge.py").read_text()
    tree = ast.parse(src)
    ns_ = {"np": np, "cv2": cv2}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("preprocess_rgb", "policy_image", "rot6d_to_mat", "decode_action"):
            exec(compile(ast.Module([node], type_ignores=[]), "policy_bridge.py", "exec"), ns_)
    decode_action, policy_image = ns_["decode_action"], ns_["policy_image"]
    import mujoco
    cfg = SceneConfig()
    kin = Collector(str(ROOT / "sim_umi/mjcf/collector_scene.xml"), cfg=cfg, render=False)
    cal = json.loads((ROOT / "sim_umi/assets/gripper_calibration.json").read_text())["scale"]
    tip = TipDetectorConfig()
    F = np.load(frames)

    def fk(q):
        d = kin._ik
        d.qpos[:] = kin.data.qpos
        for a, v in zip(kin.arm_qadr, q):
            d.qpos[a] = v
        mujoco.mj_kinematics(kin.model, d)
        return d.site_xpos[kin.tcp_sid].copy(), np.asarray(d.site_xmat[kin.tcp_sid]).reshape(3, 3).copy()

    def width(raw):
        det = detect_tips(raw, tip)
        return None if det["pixel_gap"] is None else float(cal["a"] * det["pixel_gap"] + cal["b"])

    def mat(p, R):
        T = np.eye(4); T[:3, :3], T[:3, 3] = R, p
        return T

    # the arm is at HOME and settling; the joint snapshot is identical in both reps, so FK of the
    # settled HOME is used for BOTH (identical low-dim by construction)
    p0, R0 = fk(HOME_Q)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    res, rid = [], 0
    for pr in pairs.split(";"):
        ta, tb = [int(x) for x in pr.split(",")]
        outs, widths = [], []
        for rep in (0, 1):
            raws = [F[f"rep{rep}_tick{ta}"], F[f"rep{rep}_tick{tb}"]]
            widths.append([width(r) for r in raws])
            rgb = np.stack([policy_image(mask_magenta(r, tip), "g0_center224")[0] for r in raws])
            grip = [widths[0][0] or 0.05, widths[0][1] or 0.05]        # rep 0's width for both
            T = [mat(p0, R0), mat(p0, R0)]
            Tl = np.linalg.inv(T[-1]); Ts = np.linalg.inv(T[0])
            batch = {"camera0_rgb": rgb[None],
                     "robot0_eef_pos": np.stack([(Tl @ t)[:3, 3] for t in T])[None].astype(np.float32),
                     "robot0_eef_rot_axis_angle": np.stack([(Tl @ t)[:2, :3].reshape(6) for t in T])[None].astype(np.float32),
                     "robot0_eef_rot_axis_angle_wrt_start": np.stack([(Ts @ t)[:2, :3].reshape(6) for t in T])[None].astype(np.float32),
                     "robot0_gripper_width": np.array([[g] for g in grip])[None].astype(np.float32)}
            rid += 1
            outs.append((np.asarray(infer(sock, batch, rid)), rgb))
        (a0, rgb0), (a1, rgb1) = outs
        dec = []
        for a in (a0, a1):
            rows = []
            for k in range(a.shape[1]):
                p, R, g = decode_action(a[0, k], p0, R0)
                pitch = math.asin(max(-1.0, min(1.0, -R[:, 1][2])))
                q, ep, er, oop = kin.solve_ik_best(p, pitch)
                rows.append((p, R, float(g), ep * 1000 <= 2.0))
            dec.append(rows)
        dp = max(float(np.linalg.norm(x[0] - y[0])) * 1000 for x, y in zip(*dec))
        dR = max(math.degrees(math.acos(max(-1, min(1, (np.trace(x[1].T @ y[1]) - 1) / 2)))) for x, y in zip(*dec))
        dg = max(abs(x[2] - y[2]) * 1000 for x, y in zip(*dec))
        reach_same = all(x[3] == y[3] for x, y in zip(*dec))
        r = {"pair_ticks": (ta, tb),
             "rgb_input_changed_values": int((rgb0 != rgb1).sum()),
             "rgb_input_max_abs": float(np.abs(rgb0.astype(np.float64) - rgb1.astype(np.float64)).max()),
             "raw_action_max_abs_diff": float(np.abs(a0 - a1).max()),
             "decoded_position_max_diff_mm": round(dp, 6), "decoded_rotation_max_diff_deg": round(dR, 6),
             "decoded_gripper_max_diff_mm": round(dg, 6),
             "ik_reachability_same_all_16": reach_same,
             "jaw_diff_vs_3mm_threshold": round(dg / 3.0, 6),
             "camera_width_mm_rep0_rep1": [[None if w is None else round(w * 1000, 4) for w in ws] for ws in widths]}
        res.append(r)
        print(json.dumps(r))
    pathlib.Path(out + ".json").write_text(json.dumps(res, indent=1))
    kin.close()


if __name__ == "__main__":
    main()
