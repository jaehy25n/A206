"""The checkpoint, in the environment it was trained in, behind a socket.

    python sim_umi/ros/policy_server.py            # in the `umi` env

The bridge cannot import torch: ROS 2 Jazzy's binaries are built against
numpy 2 and this checkpoint's stack is torch 2.1 against numpy 1.24. Rather
than rebuild the policy on a different stack and hope the numbers match, the
policy stays where it was trained and the two talk over a unix socket. On the
real robot the policy is a separate process too.

The socket carries observations in and actions out. Nothing about the contract
lives here -- preprocessing, decoding and projection are all on the bridge
side, so there is exactly one place where the contract is written down.
"""
import io
import os
import pathlib
import socket
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import click
import dill
import hydra
import numpy as np
import torch

from diffusion_policy.workspace.base_workspace import BaseWorkspace

SOCK = "/tmp/omx_policy.sock"
HANDOFF = ROOT / "jetson_handoff"


def recv_exactly(conn, n):
    buf = b""
    while len(buf) < n:
        part = conn.recv(n - len(buf))
        if not part:
            raise ConnectionError("socket closed mid-message")
        buf += part
    return buf


@click.command()
@click.option("--checkpoint", default=str(HANDOFF / "checkpoint.ckpt"))
@click.option("--device", default="cuda:0")
@click.option("--socket-path", default=SOCK)
@click.option("--deterministic", is_flag=True,
              help="take the randomness out of the picture path: the random "
                   "crop becomes a centre crop and the colour jitter goes. "
                   "The weights are untouched; only what reaches them changes.")
@click.option("--seed", default=None, type=int,
              help="re-seed before every inference, so the same observation "
                   "gives the same action and a difference between two "
                   "actions can only come from a difference in the input")
@click.option("--dump-dir", default=None,
              help="save the exact tensor the ViT receives (after the evaluation "
                   "transform) for every --dump-every-th request, float32, lossless")
@click.option("--dump-every", default=10, type=int)
def main(checkpoint, device, socket_path, deterministic, seed, dump_dir, dump_every):
    payload = torch.load(pathlib.Path(checkpoint).open("rb"), pickle_module=dill,
                         map_location="cpu")
    cfg = payload["cfg"]
    ws: BaseWorkspace = hydra.utils.get_class(cfg._target_)(
        cfg, output_dir=str(ROOT / "sim_umi" / "outputs" / "policy_server"))
    ws.load_payload(payload, exclude_keys=None, include_keys=None)
    policy = ws.model
    weights = "raw"
    if cfg.training.use_ema and getattr(ws, "ema_model", None) is not None:
        policy, weights = ws.ema_model, "ema"
    dev = torch.device(device)
    policy.to(dev).eval()
    policy.num_inference_steps = cfg.policy.num_inference_steps
    print(f"checkpoint {checkpoint}")
    print(f"weights {weights}  device {dev}  diffusion steps "
          f"{policy.num_inference_steps}  torch {torch.__version__} "
          f"numpy {np.__version__}", flush=True)

    if os.path.exists(socket_path):
        os.unlink(socket_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path)
    srv.listen(1)
    if deterministic:
        import torchvision
        enc = policy.obs_encoder
        for key in list(enc.key_transform_map.keys()):
            was = enc.key_transform_map[key]
            kept = []
            for t in was:
                n = type(t).__name__
                if n == "RandomCrop":
                    # the same geometry, taken from the middle every time
                    kept.append(torchvision.transforms.CenterCrop(t.size))
                elif n == "ColorJitter":
                    continue
                else:
                    kept.append(t)
            enc.key_transform_map[key] = torch.nn.Sequential(*kept)
            print(f"deterministic {key}: {was} -> {enc.key_transform_map[key]}",
                  flush=True)
    if seed is not None:
        print(f"re-seeding with {seed} before every inference", flush=True)

    # What this server is serving, written next to the socket for the bridge:
    # the checkpoint, the weights, and the image geometry the checkpoint was
    # trained on (a checkpoint from before the FOV work has none: G0).
    import datetime
    import hashlib
    import json
    enc = policy.obs_encoder
    geometry = cfg.task.get("rgb_geometry", None) or "g0_center224"
    input_hw = [int(v) for v in list(cfg.task.shape_meta.obs.camera0_rgb.shape)[1:]]
    ck = pathlib.Path(checkpoint).resolve()
    side = {"checkpoint": str(ck), "checkpoint_bytes": ck.stat().st_size,
            "checkpoint_mtime": ck.stat().st_mtime, "weights": weights,
            "rgb_geometry": geometry, "input_hw": input_hw,
            "eval_transform": repr(enc.key_transform_map["camera0_rgb"]),
            "deterministic": bool(deterministic), "seed": seed, "device": str(dev),
            "pid": os.getpid(), "started": datetime.datetime.now().astimezone().isoformat()}
    pathlib.Path(socket_path + ".meta.json").write_text(json.dumps(side, indent=1))
    print(f"geometry {geometry}  input {input_hw[0]}x{input_hw[1]}  "
          f"eval transform {side['eval_transform']!r}", flush=True)
    enc_in = {}
    enc.key_transform_map["camera0_rgb"].register_forward_hook(
        lambda m, i, o: enc_in.__setitem__("x", o.detach()))
    if dump_dir:
        pathlib.Path(dump_dir).mkdir(parents=True, exist_ok=True)

    print(f"listening on {socket_path}", flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            while True:
                head = conn.recv(4)
                if not head:
                    break
                n = struct.unpack("!I", head)[0]
                obs = np.load(io.BytesIO(recv_exactly(conn, n)))
                # "_" keys are bookkeeping from the bridge, never policy input
                req = int(obs["_req_id"][0]) if "_req_id" in obs.files else None
                batch = {k: torch.from_numpy(obs[k]).to(dev) for k in obs.files
                         if not k.startswith("_")}
                try:
                    if seed is not None:
                        torch.manual_seed(seed)
                        torch.cuda.manual_seed_all(seed)
                    with torch.no_grad():
                        out = policy.predict_action(batch)
                    act = out["action_pred"].cpu().numpy().astype(np.float32)
                except Exception as e:
                    # A bad request must not take the weights down with it --
                    # loading this checkpoint costs a minute.
                    print(f"inference failed: {type(e).__name__}: {e}", flush=True)
                    for k, v in batch.items():
                        print(f"   got {k:38s} {tuple(v.shape)}", flush=True)
                    act = np.zeros((0,), np.float32)
                buf = io.BytesIO()
                np.save(buf, act)
                body = buf.getvalue()
                conn.sendall(struct.pack("!I", len(body)) + body)
                # only after the answer is on its way: the dump must never sit
                # between an observation and its action
                if (dump_dir and req is not None and act.size and "x" in enc_in
                        and (req - 1) % max(1, dump_every) == 0):
                    rgb_in = obs["camera0_rgb"]
                    np.savez_compressed(
                        pathlib.Path(dump_dir) / f"req{req:06d}.npz",
                        encoder_input=enc_in["x"].float().cpu().numpy(), req_id=req,
                        received_rgb_sha1=hashlib.sha1(np.ascontiguousarray(rgb_in).tobytes()).hexdigest(),
                        received_rgb_shape=np.array(rgb_in.shape))
        except (ConnectionError, EOFError) as e:
            print(f"client gone: {e}", flush=True)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
