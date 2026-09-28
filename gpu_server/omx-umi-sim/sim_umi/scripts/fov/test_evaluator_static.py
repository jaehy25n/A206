"""Static tests of the evaluator changes -- no simulator, no camera, no GPU.

    python sim_umi/scripts/fov/test_evaluator_static.py --scratch <dir>

1. policy_bridge.policy_image, taken from the source file as written: G0 is
   preprocess_rgb bit for bit; G1/G2 are rgb_geometry's frames.
2. policy_server on CPU with the G0 checkpoint: the sidecar says what it
   serves, "_" keys are stripped, a request without _req_id still works, the
   answer is (1, 16, 10), and the dumped encoder input equals torchvision
   CenterCrop + Resize applied independently to what was sent.
"""
import ast
import hashlib
import io
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import textwrap
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(SIM / "src"))
import click
import cv2
import numpy as np

import rgb_geometry as G

CKPT = SIM / "train_results/2026-09-27_amp_v2_definitive/checkpoints/step11400.ckpt"
UMI = "/home/j-j15a206/.conda/envs/umi/bin/python"
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}", flush=True)


def functions_from(path, names):
    src = pathlib.Path(path).read_text()
    tree = ast.parse(src)
    ns = {"cv2": cv2, "np": np}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            exec(textwrap.dedent(ast.get_source_segment(src, n)), ns)
    return ns


@click.command()
@click.option("--scratch", required=True)
def main(scratch):
    scr = pathlib.Path(scratch)
    scr.mkdir(parents=True, exist_ok=True)
    # ---------------------------------------------------------------- 1
    ns = functions_from(SIM / "ros/policy_bridge.py", {"preprocess_rgb", "policy_image"})
    frames = np.load(sorted((SIM / "data/demos/train").glob("episode_*.npz"))[3], allow_pickle=True)["rgb"][[0, 60, 120]]
    for f in frames:
        rgb, canvas = ns["policy_image"](f, "g0_center224")
        check("G0 policy_image == preprocess_rgb (bitwise), and nothing else computed (canvas None)",
              np.array_equal(rgb, ns["preprocess_rgb"](f)) and canvas is None, str(rgb.shape))
        for name, shape in (("g1_letterbox224", (3, 224, 224)), ("g2_rect288x176", (3, 176, 288))):
            rgb, canvas = ns["policy_image"](f, name)
            check(f"{name} policy_image == rgb_geometry", rgb.shape == shape and
                  np.array_equal(rgb, G.to_chw_float(G.apply(name, f))) and np.array_equal(canvas, G.apply(name, f)),
                  str(rgb.shape))
    # ---------------------------------------------------------------- 2
    sock = "/tmp/omx_fovtest.sock"          # AF_UNIX paths are limited to 108 bytes
    dump = scr / "dump"
    log = open(scr / "server.log", "w")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "LD_LIBRARY_PATH", "ROS_DISTRO", "AMENT_PREFIX_PATH")}
    env["CUDA_VISIBLE_DEVICES"] = ""
    srv = subprocess.Popen([UMI, str(SIM / "ros/policy_server.py"), "--checkpoint", str(CKPT), "--device", "cpu",
                            "--deterministic", "--seed", "1234", "--socket-path", sock, "--dump-dir", str(dump),
                            "--dump-every", "1"], stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(240):
            if "listening on" in (scr / "server.log").read_text():
                break
            time.sleep(1)
        side = json.loads(pathlib.Path(sock + ".meta.json").read_text())
        check("sidecar: G0 geometry, EMA weights, 224x224, the checkpoint",
              side["rgb_geometry"] == "g0_center224" and side["weights"] == "ema" and side["input_hw"] == [224, 224]
              and side["checkpoint"] == str(CKPT.resolve()), json.dumps({k: side[k] for k in ("rgb_geometry", "weights", "input_hw")}))
        rgb = np.stack([ns["policy_image"](f, "g0_center224")[0] for f in frames[:2]])[None].astype(np.float32)
        low = {"robot0_eef_pos": np.zeros((1, 2, 3), np.float32),
               "robot0_eef_rot_axis_angle": np.tile(np.array([1, 0, 0, 0, 1, 0], np.float32), (1, 2, 1)),
               "robot0_eef_rot_axis_angle_wrt_start": np.tile(np.array([1, 0, 0, 0, 1, 0], np.float32), (1, 2, 1)),
               "robot0_gripper_width": np.full((1, 2, 1), 0.05, np.float32)}

        timing = {}

        def ask(extra, tag=None):
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.connect(sock)
            buf = io.BytesIO()
            np.savez(buf, camera0_rgb=rgb, **low, **extra)
            body = buf.getvalue()
            t0 = time.time()
            c.sendall(struct.pack("!I", len(body)) + body)
            n = struct.unpack("!I", c.recv(4))[0]
            data = b""
            while len(data) < n:
                data += c.recv(n - len(data))
            if tag:
                timing[tag] = (t0, time.time())
            c.close()
            return np.load(io.BytesIO(data))
        a0 = ask({}, "warm")
        a1 = ask({"_req_id": np.array([1], np.int64)}, "with_dump")
        check("answer with _req_id: (1, 16, 10), finite", a1.shape == (1, 16, 10) and np.isfinite(a1).all(), str(a1.shape))
        a2 = ask({}, "no_dump")
        for _ in range(100):
            if (dump / "req000001.npz").exists():
                break
            time.sleep(0.05)
        dump_mtime = (dump / "req000001.npz").stat().st_mtime
        check("the answer is received before the dump file exists (dump after the reply)",
              timing["with_dump"][1] <= dump_mtime,
              f"reply at +{timing['with_dump'][1] - timing['with_dump'][0]:.3f} s, dump file at "
              f"+{dump_mtime - timing['with_dump'][0]:.3f} s")
        lw = timing["with_dump"][1] - timing["with_dump"][0]
        ln = timing["no_dump"][1] - timing["no_dump"][0]
        check("a request with a dump is answered as fast as one without (within 10%)", lw <= 1.10 * ln,
              f"{lw:.3f} s vs {ln:.3f} s")
        check("answer without _req_id (old bridge): (1, 16, 10), same action", a2.shape == (1, 16, 10) and np.array_equal(a1, a2))
        d = np.load(dump / "req000001.npz")
        import torch
        import torchvision
        t = torch.from_numpy(rgb.reshape(2, 3, 224, 224))
        ref = torchvision.transforms.Resize(224, antialias=True)(torchvision.transforms.CenterCrop(212)(t)).numpy()
        check("dumped encoder input == CenterCrop(212)+Resize(224) of what was sent",
              d["encoder_input"].shape == (2, 3, 224, 224) and np.array_equal(d["encoder_input"], ref),
              f"max |d| {float(np.abs(d['encoder_input'] - ref).max()):.2e}")
        check("dump links to the sent image by sha1",
              str(d["received_rgb_sha1"]) == hashlib.sha1(np.ascontiguousarray(rgb).tobytes()).hexdigest())
        check("no dump for the request without an id", sorted(p.name for p in dump.glob("*.npz")) == ["req000001.npz"])
    finally:
        srv.terminate()
        srv.wait(timeout=30)
        log.close()
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
