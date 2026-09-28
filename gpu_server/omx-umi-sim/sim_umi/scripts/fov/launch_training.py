"""Launch G1 (physical GPU 0) and G2 (physical GPU 5) side by side.

    python sim_umi/scripts/fov/launch_training.py --mode smoke|production

The override list is config_diff.overrides_for(), the one the config audit
checked -- G0's own list plus the allowed geometry keys -- with only the step
budget, checkpoint list and fingerprint count changed for a smoke run. Each
run gets a fresh directory (refused if it exists: nothing is resumed and
nothing is overwritten). After launch, nvidia-smi must show each training PID
on its intended physical GPU, or both runs are stopped.
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import click

from config_diff import overrides_for

FOV = ROOT / "sim_umi/train_results/2026-09-27_fov"
PY = "/home/j-j15a206/.conda/envs/umi/bin/python"
RUNS = {"G1": {"gpu": 0, "geometry": "g1_letterbox224"}, "G2": {"gpu": 5, "geometry": "g2_rect288x176"}}


def gpu_of_pid():
    idx = dict(l.split(", ") for l in subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid,index", "--format=csv,noheader"], text=True).strip().splitlines())
    out = {}
    for l in subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
                                      "--format=csv,noheader"], text=True).strip().splitlines():
        if l.strip():
            u, pid, mem = [x.strip() for x in l.split(",")]
            out.setdefault(int(pid), []).append((int(idx[u]), mem))
    return out


def descendants(pid):
    try:
        kids = subprocess.check_output(["pgrep", "-P", str(pid)], text=True).split()
    except subprocess.CalledProcessError:
        return []
    out = []
    for k in kids:
        out += [int(k)] + descendants(int(k))
    return out


@click.command()
@click.option("--mode", type=click.Choice(["smoke", "production"]), required=True)
@click.option("--smoke-steps", default=100)
@click.option("--smoke-tag", default="smoke", help="directory for a smoke run; a rerun takes a new one")
def main(mode, smoke_steps, smoke_tag):
    launched = {}
    git = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name, r in RUNS.items():
        g = r["geometry"]
        run_dir = (FOV / smoke_tag / name.lower()) if mode == "smoke" else (ROOT / f"sim_umi/train_results/2026-09-27_fov_{g}")
        if run_dir.exists():
            raise SystemExit(f"{run_dir} exists -- refusing (fresh runs only)")
        ov = overrides_for(name)
        if mode == "smoke":
            ov = [o for o in ov if not o.startswith(("+training.max_opt_steps=", "+training.checkpoint_at_steps=",
                                                     "+training.log_batch_fingerprints=", "exp_name="))]
            ov += [f"+training.max_opt_steps={smoke_steps}", f"+training.checkpoint_at_steps=[{smoke_steps}]",
                   f"+training.log_batch_fingerprints={smoke_steps}", f"exp_name=fov_smoke_{g}"]
        ov.append(f"hydra.run.dir={run_dir}")
        cmd = [PY, "train.py", "--config-name=train_diffusion_unet_timm_omx_workspace"] + ov
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "LD_LIBRARY_PATH", "ROS_DISTRO", "AMENT_PREFIX_PATH")}
        env.update({"CUDA_VISIBLE_DEVICES": str(r["gpu"]), "MUJOCO_GL": "egl", "WANDB_MODE": "offline",
                    "HYDRA_FULL_ERROR": "1"})
        log = FOV / f"train_{name}_{smoke_tag if mode == 'smoke' else mode}.log"
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        launched[name] = {"pid": proc.pid, "gpu_intended": r["gpu"], "run_dir": str(run_dir), "log": str(log),
                          "cmd": cmd, "cuda_visible_devices": env["CUDA_VISIBLE_DEVICES"], "git": git,
                          "started": datetime.datetime.now().astimezone().isoformat()}
        print(f"{name}: pid {proc.pid} -> physical GPU {r['gpu']}, {run_dir}", flush=True)
    # every training process (and its dataloader workers, which hold no CUDA
    # context) must sit on its intended physical GPU
    deadline = time.time() + 600
    verified = {}
    while time.time() < deadline and len(verified) < len(launched):
        time.sleep(15)
        seen = gpu_of_pid()
        for name, L in launched.items():
            pids = [L["pid"]] + descendants(L["pid"])
            gpus = sorted({gi for p in pids for gi, _ in seen.get(p, [])})
            if gpus:
                verified[name] = {"pids_on_gpu": {p: seen[p] for p in pids if p in seen}, "physical_gpus": gpus}
        for name, L in launched.items():
            if subprocess.run(["kill", "-0", str(L["pid"])], capture_output=True).returncode != 0 and name not in verified:
                raise SystemExit(f"{name} exited before reaching the GPU -- see {L['log']}")
    bad = [n for n in launched if verified.get(n, {}).get("physical_gpus") != [launched[n]["gpu_intended"]]]
    rec = {"mode": mode, "launched": launched, "gpu_check": verified,
           "checked": datetime.datetime.now().astimezone().isoformat(), "pass": not bad}
    (FOV / f"launch_{smoke_tag if mode == 'smoke' else mode}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps(verified, indent=1, default=str), flush=True)
    if bad:
        for L in launched.values():
            subprocess.run(["kill", "--", f"-{os.getpgid(L['pid'])}"], capture_output=True)
        raise SystemExit(f"WRONG GPU for {bad} -- both runs stopped")
    print("GPU check PASS", flush=True)


if __name__ == "__main__":
    main()
