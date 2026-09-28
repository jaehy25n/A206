"""Stage A checkpoint smoke test: load -> predict_action() -> decode.

Runs from a handoff bundle alone. No ROS, no robot, no dataset, no zarr -- only
`checkpoint.ckpt`, `observation_reference.npz` and `model_manifest.json`.

    python scripts/smoke_predict_action.py --bundle jetson_handoff
    python scripts/smoke_predict_action.py --bundle . --device cpu

This same file ships inside the Jetson source snapshot, so both sides run the
identical check and the results are directly comparable.

The policy is built from `cfg.policy` directly, never through the training
workspace class: that module imports wandb at module level, which would put
wandb, sentry-sdk, GitPython and boto3 on the Jetson's install list for nothing.

Note on `pretrained`: the config used for training sets
`policy.obs_encoder.pretrained: True`, which makes timm fetch CLIP weights from
the HuggingFace hub at construction time. The checkpoint then overwrites every
one of those weights, so the download is pure latency on the GPU box and a hard
failure on an offline Jetson. This script forces it to False before building the
policy and verifies the outcome is bit-identical either way (--check-pretrained).
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import argparse
import json
import pathlib
import platform
import time

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="jetson_handoff",
                    help="directory holding checkpoint.ckpt, "
                         "observation_reference.npz, model_manifest.json")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--benchmark", type=int, default=5)
    ap.add_argument("--require-cuda", action="store_true",
                    help="fail instead of falling back to cpu. Use this to prove "
                         "a JetPack CUDA wheel is really in use -- without it a "
                         "CPU-only wheel still reports ALL SMOKE CHECKS PASSED, "
                         "just on the wrong device.")
    ap.add_argument("--check-pretrained", action="store_true",
                    help="also build with pretrained=True and confirm the output "
                         "is identical (needs network)")
    args = ap.parse_args()

    B = pathlib.Path(args.bundle).absolute()
    results = {}
    failed = []

    def step(name, ok, detail=""):
        results[name] = ok
        if not ok:
            failed.append(name)
        print(f"  {'PASS' if ok else 'FAIL'}  {name:26s} {detail}")

    print("=" * 74)
    print("Stage A checkpoint smoke test")
    print("=" * 74)
    print(f"bundle   : {B}")
    print(f"python   : {platform.python_version()}  {platform.machine()}")

    import torch
    print(f"torch    : {torch.__version__}  cuda={torch.version.cuda}")
    dev = torch.device(args.device if torch.cuda.is_available()
                       or not args.device.startswith("cuda") else "cpu")
    if str(dev) != args.device:
        if args.require_cuda:
            print(f"\n  FAIL  --require-cuda, but torch.cuda.is_available() is False.")
            print(f"        torch.version.cuda = {torch.version.cuda}")
            print("        " + ("this wheel was built without CUDA. On a Jetson, pip's\n"
                                "        default aarch64 wheel is CPU-only -- the JetPack build\n"
                                "        has to come from NVIDIA's index. See README_JETSON_SETUP\n"
                                "        section 'CUDA wheel'."
                                if torch.version.cuda is None else
                                "the wheel has CUDA but no device is visible: check\n"
                                "        CUDA_VISIBLE_DEVICES and that nvidia drivers are loaded."))
            return 1
        print(f"           (cuda unavailable, falling back to {dev})")
    if dev.type == "cuda":
        print(f"device   : {torch.cuda.get_device_name(0)}")
    print(f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')}")
    print()

    manifest = json.loads((B / "model_manifest.json").read_text())
    obs_keys = manifest["observation_keys"]

    # ------------------------------------------------------------ 1. load --- #
    print("[1] checkpoint")
    import dill
    import hydra
    from omegaconf import OmegaConf
    OmegaConf.register_new_resolver("eval", eval, replace=True)

    ck = B / "checkpoint.ckpt"
    step("checkpoint file present", ck.is_file(), f"{ck.stat().st_size/1e6:.0f} MB"
         if ck.is_file() else str(ck))
    if not ck.is_file():
        return 1

    t0 = time.perf_counter()
    payload = torch.load(ck.open("rb"), pickle_module=dill, map_location="cpu")
    load_s = time.perf_counter() - t0
    step("checkpoint load", True, f"{load_s:.1f} s")

    have = sorted(payload["state_dicts"].keys())
    step("ema_model in state_dicts", "ema_model" in have, f"state_dicts={have}")

    cfg = payload["cfg"]
    # The checkpoint supplies every weight; skip the hub download.
    if "pretrained" in cfg.policy.obs_encoder:
        cfg.policy.obs_encoder.pretrained = False

    # Build the policy directly from cfg.policy rather than through the training
    # workspace class. cfg._target_ points at
    # train_diffusion_unet_image_workspace, whose module-level `import wandb`
    # would drag wandb, sentry-sdk, GitPython and boto3 onto the Jetson for no
    # reason -- none of them are used by inference. Instantiating the policy
    # alone gives the identical network; verified against the workspace path on
    # the GPU box (max|d| = 0).
    sd = payload["state_dicts"]["ema_model"]
    policy = hydra.utils.instantiate(cfg.policy)
    try:
        policy.load_state_dict(sd)
        loaded = True
    except RuntimeError as e:
        print(f"  note  direct load failed ({str(e)[:70]}…), falling back to workspace")
        cls = hydra.utils.get_class(cfg._target_)
        workspace = cls(cfg, output_dir=str(B))
        workspace.load_payload(payload, exclude_keys=None, include_keys=None)
        policy = getattr(workspace, "ema_model", None)
        loaded = policy is not None
    step("ema_model load", loaded, "policy built from cfg.policy (no workspace)")
    if not loaded:
        return 1

    # weights really came from the file, not from random init
    probe = next(k for k in sd if k.endswith("weight") and sd[k].ndim > 1)
    step("ema weights applied",
         bool(torch.allclose(dict(policy.state_dict())[probe].cpu(), sd[probe])),
         probe[:44])

    policy.to(dev).eval()

    # ----------------------------------------------------- 2. observation --- #
    print("\n[2] observation")
    o = np.load(B / "observation_reference.npz")
    missing = [k for k in obs_keys if f"obs_{k}" not in o.files]
    step("all declared keys present", not missing, f"{len(obs_keys)} keys"
         if not missing else f"missing {missing}")
    obs = {k: torch.from_numpy(o[f"obs_{k}"])[None].to(dev) for k in obs_keys}
    for k in obs_keys:
        print(f"        {k:38s} {tuple(obs[k].shape)}  {obs[k].dtype}")

    # ------------------------------------------------------ 3. inference --- #
    print("\n[3] predict_action")
    torch.manual_seed(int(manifest["reference_sample"]["torch_seed"]))
    np.random.seed(int(manifest["reference_sample"]["torch_seed"]))
    with torch.no_grad():
        out = policy.predict_action(obs, None)
    action = out["action"].detach().cpu().numpy()
    step("output shape [1,16,10]", action.shape == (1, 16, 10), str(action.shape))
    step("output finite", bool(np.isfinite(action).all()),
         f"range [{action.min():+.4f}, {action.max():+.4f}]")

    ref_p = B / "reference_action.npy"
    if ref_p.is_file():
        ref = np.load(ref_p)
        d = float(np.abs(action[0] - ref).max())
        # Informational, never a failure. The policy randomises its own input and
        # the diffusion sampler draws noise, so the output follows the device's
        # RNG stream: identical seed on cpu vs cuda already differs by ~2.0 on the
        # GPU box. Matching it is a nice-to-have on the same hardware, not a
        # contract. The decoder check below is the one that must hold.
        mark = "same" if d < 1e-4 else "differs (expected on other hardware)"
        print(f"  info  matches reference_action.npy  max|d| = {d:.3e}  {mark}")
        results["reference_action_max_abs_diff"] = d

    # --------------------------------------------------------- 4. decode --- #
    print("\n[4] decode")
    from diffusion_policy.common.pose_repr_util import convert_pose_mat_rep
    from umi.common.pose_util import mat_to_pose, pose10d_to_mat, pose_to_mat

    base6 = o["base_pose6"]

    def decode(raw10):
        world = convert_pose_mat_rep(pose10d_to_mat(raw10[:, :9]),
                                     base_pose_mat=pose_to_mat(base6),
                                     pose_rep="relative", backward=True)
        return mat_to_pose(world)[:, :3]

    # the live path: decode what this machine's policy just produced
    ee_target = decode(action[0])
    step("EE target shape [16,3]", ee_target.shape == (16, 3), str(ee_target.shape))
    step("EE target finite", bool(np.isfinite(ee_target).all()),
         f"first {np.round(ee_target[0], 5).tolist()}")

    # decoder parity: decode the SAVED reference action, not the one just
    # produced. The decoder is deterministic; the policy is not, so comparing a
    # freshly sampled action against the recorded decode would fail on any
    # machine whose RNG stream differs -- which is every machine but this one.
    dec_p = B / "reference_decoded_pose.npz"
    if dec_p.is_file() and ref_p.is_file():
        rd = np.load(dec_p)
        d = float(np.abs(decode(np.load(ref_p)) - rd["ee_position"]).max())
        step("decoder parity", d < 1e-4, f"max|d| = {d:.3e}  "
             f"(reference action -> decode, deterministic)")

    # -------------------------------------------------------- 5. latency --- #
    print("\n[5] latency")
    if args.benchmark:
        with torch.no_grad():
            for _ in range(2):
                policy.predict_action(obs, None)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            for _ in range(args.benchmark):
                policy.predict_action(obs, None)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            ms = (time.perf_counter() - t0) / args.benchmark * 1e3
        print(f"        {ms:.1f} ms / call  (B=1, "
              f"{cfg.policy.num_inference_steps} denoise steps, {dev})")
        results["latency_ms"] = round(ms, 2)

    # ----------------------------------------------- 6. pretrained check --- #
    if args.check_pretrained:
        print("\n[6] pretrained=True gives the same result")
        cfg2 = payload["cfg"]
        cfg2.policy.obs_encoder.pretrained = True
        ws2 = hydra.utils.get_class(cfg2._target_)(cfg2, output_dir=str(B))
        ws2.load_payload(payload, exclude_keys=None, include_keys=None)
        p2 = ws2.ema_model.to(dev).eval()
        torch.manual_seed(int(manifest["reference_sample"]["torch_seed"]))
        np.random.seed(int(manifest["reference_sample"]["torch_seed"]))
        with torch.no_grad():
            a2 = p2.predict_action(obs, None)["action"].cpu().numpy()
        d = float(np.abs(a2 - action).max())
        step("pretrained flag is irrelevant", d < 1e-6, f"max|d| = {d:.3e}")

    # --------------------------------------------------------- summary ----- #
    print("\n" + "=" * 74)
    print("SUMMARY")
    print("-" * 74)
    print(f"checkpoint load      : {'PASS' if results.get('checkpoint load') else 'FAIL'}")
    print(f"ema_model            : {'PASS' if results.get('ema_model load') else 'FAIL'}")
    print(f"observation keys     : {obs_keys}")
    print(f"action shape         : {action.shape}")
    print(f"action finite        : {bool(np.isfinite(action).all())}")
    print(f"decoded target shape : {ee_target.shape}")
    if "latency_ms" in results:
        print(f"inference latency    : {results['latency_ms']} ms/call "
              f"(B=1, {cfg.policy.num_inference_steps} steps, {dev})")
    if "reference_action_max_abs_diff" in results:
        print(f"vs reference action  : max|d| = "
              f"{results['reference_action_max_abs_diff']:.3e}  (informational; "
              f"device-dependent RNG)")
    print("=" * 74)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
