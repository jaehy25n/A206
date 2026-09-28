"""Snapshot the exact working tree needed to load a handoff checkpoint.

Not `git archive`: the OMX work is additive and part of it is untracked, so an
archive built from the index would silently drop files the checkpoint needs. This
copies the real working tree and records the git state alongside it, so the
Jetson gets what actually ran rather than what happens to be committed.

    python scripts/make_jetson_source_snapshot.py

Excluded: datasets, zarr, W&B, training outputs, checkpoints, the handoff bundle
itself (the Jetson already has it), .git, caches.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tarfile
import time

ROOT = pathlib.Path(ROOT_DIR)

#: Everything the inference path can reach, plus the configs and scripts that
#: describe the contract. `diffusion_policy` and `umi` are what actually load;
#: `omx` and `configs` carry the preprocessing/collector contract.
INCLUDE_DIRS = ["diffusion_policy", "umi", "omx", "configs"]

#: Only the scripts that are useful without a dataset or a robot.
INCLUDE_SCRIPTS = [
    "smoke_predict_action.py",
    "offline_infer_omx.py",
    "make_jetson_handoff.py",
]

#: Docs the snapshot's own README and INSTALL.md link to. A dangling link in an
#: archive that travels to another machine cannot be followed, so anything
#: referenced has to travel with it.
INCLUDE_FILES = [
    "README_JETSON_SETUP.md",
    "README_JETSON_HANDOFF.md",
    "README_HANDOFF_CONTRACT.md",
    "README_GPU_VALIDATION.md",
    "README_CPU_GPU_SYNC.md",
    "README_GPU_WORKFLOW.md",
    "REPORT_STAGE_A_INTEGRATION.md",
]

#: Pruned anywhere in the tree.
EXCLUDE_NAMES = {"__pycache__", ".git", ".ipynb_checkpoints", ".pytest_cache"}

#: Pruned only at the repo root. Name-matching these anywhere would also drop
#: `omx/data/`, which is a source package, not a dataset directory.
EXCLUDE_TOPLEVEL = {"data", "data_local", "data_workspace", "wandb", "outputs",
                    "jetson_handoff", "jetson_inference_source"}
EXCLUDE_SUFFIXES = (".ckpt", ".pth", ".pt", ".zarr", ".zip", ".mp4", ".npz.zip",
                    ".pyc", ".so", ".pem")

VERSION_PACKAGES = ["torch", "torchvision", "timm", "diffusers", "accelerate",
                    "hydra-core", "omegaconf", "dill", "numpy", "scipy",
                    "opencv-python", "zarr", "numcodecs", "imagecodecs",
                    "einops", "huggingface-hub", "safetensors", "filelock",
                    "threadpoolctl"]


def git(*a) -> str:
    try:
        return subprocess.check_output(("git",) + a, cwd=ROOT,
                                       stderr=subprocess.DEVNULL).decode()
    except (subprocess.CalledProcessError, OSError):
        return ""


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""):
            h.update(c)
    return h.hexdigest()


def copy_tree(src: pathlib.Path, dst: pathlib.Path) -> int:
    n = 0
    for p in src.rglob("*"):
        rel_root = p.relative_to(ROOT).parts
        if any(part in EXCLUDE_NAMES for part in rel_root):
            continue
        if rel_root and rel_root[0] in EXCLUDE_TOPLEVEL:
            continue
        if p.is_dir():
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        rel = p.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        n += 1
    return n


def versions() -> dict:
    import importlib.metadata as md
    out = {}
    for name in VERSION_PACKAGES:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out-dir", default="jetson_inference_source")
    ap.add_argument("--tag", default=None,
                    help="archive name suffix. Default: the commit the handoff "
                         "bundle was generated at, falling back to HEAD.")
    ap.add_argument("--bundle", default="jetson_handoff")
    args = ap.parse_args()

    head = git("rev-parse", "HEAD").strip()
    head_short = git("rev-parse", "--short", "HEAD").strip()
    status = git("status", "--porcelain")
    dirty = bool(status.strip())

    bundle_commit = None
    bmf = pathlib.Path(args.bundle) / "model_manifest.json"
    if bmf.is_file():
        bundle_commit = json.loads(bmf.read_text())["repo"]["commit"]
    tag = args.tag or (bundle_commit[:7] if bundle_commit else head_short)

    out = (ROOT / args.out_dir).absolute()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("=" * 74)
    print("Jetson inference source snapshot")
    print("=" * 74)
    print(f"HEAD          : {head}")
    print(f"bundle commit : {bundle_commit}")
    print(f"dirty         : {dirty}")
    print(f"out           : {out}\n")

    total = 0
    for d in INCLUDE_DIRS:
        src = ROOT / d
        if not src.is_dir():
            print(f"  skip {d}/ (absent)")
            continue
        n = copy_tree(src, out / d)
        total += n
        print(f"  {n:5d} files  {d}/")

    (out / "scripts").mkdir(exist_ok=True)
    for s in INCLUDE_SCRIPTS:
        p = ROOT / "scripts" / s
        if p.is_file():
            shutil.copy2(p, out / "scripts" / s)
            total += 1
            print(f"      1 file   scripts/{s}")
    for f in INCLUDE_FILES:
        p = ROOT / f
        if p.is_file():
            shutil.copy2(p, out / f)
            total += 1
            print(f"      1 file   {f}")

    # ------------------------------------------------------- git state ----- #
    diff_range = ""
    if bundle_commit and bundle_commit != head:
        names = git("diff", "--name-only", f"{bundle_commit}..{head}").split()
        diff_range = (f"\ncommits between the bundle and HEAD touch these files:\n"
                      + "".join(f"  {n}\n" for n in names))
    (out / "git_commit.txt").write_text(
        f"HEAD          {head}\n"
        f"HEAD (short)  {head_short}\n"
        f"branch        {git('rev-parse', '--abbrev-ref', 'HEAD').strip()}\n"
        f"bundle commit {bundle_commit}\n"
        f"dirty         {dirty}\n"
        f"snapshot utc  {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"{diff_range}\n"
        f"Last commits:\n{git('log', '--oneline', '-8')}")
    (out / "git_status.txt").write_text(status or "(clean)\n")
    (out / "working_tree.patch").write_text(git("diff", "--binary"))

    # ----------------------------------------------------- environment ----- #
    import platform
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": versions(),
    }
    try:
        import torch
        env["torch_cuda"] = torch.version.cuda
        env["torch_cudnn"] = torch.backends.cudnn.version()
    except Exception:
        pass
    (out / "environment.json").write_text(json.dumps(env, indent=2))
    (out / "pip_freeze.txt").write_text(
        subprocess.run([sys.executable, "-m", "pip", "freeze"],
                       capture_output=True, text=True).stdout)

    write_readme(out, head, head_short, bundle_commit, dirty, env, tag)
    write_requirements(out)

    # --------------------------------------- self-referential hashes ------- #
    # A packaged doc cannot carry this archive's own hash: the archive does not
    # exist yet when the doc is copied in, so any value there is one generation
    # stale. Catch it rather than shipping a number that contradicts the
    # .sha256 sidecar.
    stale = []
    for md in sorted(out.rglob("*.md")):
        text = md.read_text()
        for line in text.splitlines():
            if re.search(r"[a-f0-9]{64}", line) and "jetson_inference_source" in line:
                stale.append(f"{md.relative_to(out)}: {line.strip()[:78]}")
    if stale:
        print("\n  ! a packaged doc states this archive's own sha256 "
              "(always stale -- remove it):")
        for x in stale:
            print(f"      {x}")

    # ------------------------------------------- doc link integrity -------- #
    dangling = []
    for md in sorted(out.rglob("*.md")):
        for target in re.findall(r"\]\(([A-Za-z0-9_./-]+\.md)\)", md.read_text()):
            if not (md.parent / target).exists() and not (out / target).exists():
                dangling.append(f"{md.relative_to(out)} -> {target}")
    if dangling:
        print("\n  ! dangling doc links (referenced but not packaged):")
        for d in dangling:
            print(f"      {d}")
    else:
        print("\n  doc links: all referenced .md files are packaged")

    # ------------------------------------------------------- checksums ----- #
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            lines.append(f"{sha256_file(p)}  {p.relative_to(out)}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    # --------------------------------------------------------- archive ----- #
    tar_path = ROOT / f"jetson_inference_source_{tag}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(out, arcname=out.name)
    tar_sha = sha256_file(tar_path)
    (ROOT / f"jetson_inference_source_{tag}.tar.gz.sha256").write_text(
        f"{tar_sha}  {tar_path.name}\n")

    print(f"\n  {total} source files + metadata")
    print(f"\narchive : {tar_path}  ({tar_path.stat().st_size/1e6:.1f} MB)")
    print(f"sha256  : {tar_sha}")
    print(f"dir     : {out}")
    return 0


def write_requirements(out: pathlib.Path) -> None:
    """The set actually needed for inference, measured by blocking imports.

    NOT a `pip install -r` target on the Jetson: torch and torchvision must come
    from the JetPack-matched build, never from PyPI. Install those first, then
    the rest.
    """
    (out / "inference_requirements.txt").write_text("""# Inference-only dependency set for the Stage A handoff checkpoint.
#
# Verified on python 3.10.12 / CPU by running scripts/smoke_predict_action.py to
# ALL SMOKE CHECKS PASSED, and by blocking each import to confirm it is really
# needed. Do NOT `pip install -r` this file wholesale on a Jetson: torch and
# torchvision must come from the JetPack-matched build.
#
# Verified against two torch versions, so the JetPack build does not have to
# match the training one:
#   torch 2.1.0 + torchvision 0.16.0   (what the checkpoint was trained with)
#   torch 2.5.1 + torchvision 0.20.1   (JetPack 6.x era)
# Both load the checkpoint and reach ALL SMOKE CHECKS PASSED. Nothing below
# conflicts with either.
#
#   1. install the JetPack PyTorch build (torch, torchvision) first
#   2. then:  pip install -r inference_requirements.txt
#
# NOT needed, confirmed by running without them:
#   wandb  (and sentry-sdk, GitPython, wandb-*)   av
# The smoke script builds the policy from cfg.policy directly instead of through
# the training workspace class, which is what keeps wandb off this list.

# --- pinned: diffusers 0.18.2 calls huggingface_hub.constants.hf_cache_home,
# --- which was removed in newer hub releases. An unpinned install breaks with
# --- "cannot import name 'hf_cache_home'".
huggingface_hub==0.25.2

# --- pinned: torch 2.1.0 is built against the numpy 1.x ABI.
numpy<2

timm==0.9.7
diffusers==0.18.2
accelerate==0.24.1
einops==0.6.1
hydra-core==1.2.0
omegaconf==2.2.3
dill==0.3.7
scipy

# imported at module level by upstream code, not used by inference itself
zarr==2.16.1
numcodecs==0.11.0
boto3

# optional: only the RGB parity section of verify_bundle.py needs it
opencv-python
""")


def write_readme(out, head, head_short, bundle_commit, dirty, env, tag) -> None:
    pkg = env["packages"]
    rows = "\n".join(f"| `{k}` | {v or '-'} |" for k, v in pkg.items())
    (out / "README.md").write_text(f"""# UMI/OMX inference source snapshot

The exact working tree that loads the Stage A handoff checkpoint, so the Jetson
does not have to guess which revision of the public UMI repo matches.

> **Start with [`README_JETSON_SETUP.md`](README_JETSON_SETUP.md)**, packaged
> beside this file. It is the full receiving procedure end to end -- which
> archives go where, how to build the inference environment, what to run in what
> order, how to read the output, and what to send back. This README only covers
> the snapshot itself.

**Do not `git clone` public UMI instead.** The OMX work is additive and part of
it was untracked at snapshot time; a clone would be missing it. This is a copy of
the real working tree, not `git archive`.

| | |
|---|---|
| HEAD | `{head}` (`{head_short}`) |
| bundle commit | `{bundle_commit}` |
| working tree dirty | {dirty} |
| snapshot tag | `{tag}` |

`git_commit.txt`, `git_status.txt` and `working_tree.patch` record the git state
exactly; `working_tree.patch` is `git diff --binary` against HEAD.

## Contents

```
diffusion_policy/   policy, dataset, common, model, workspace, codecs
umi/                pose utilities (pose_util, cv_util)
omx/                OMX adapter: config, data contract, rgb preprocessing
configs/            collector calibration / conventions
scripts/            smoke_predict_action.py, offline_infer_omx.py,
                    make_jetson_handoff.py
```

Only `diffusion_policy` and `umi` are imported by the inference path (25 modules
measured). `omx` and `configs` carry the preprocessing and collector contract and
are needed to rebuild a bundle or re-derive the RGB pipeline.

Not included: datasets, zarr, W&B, training outputs, checkpoints. The checkpoint
already ships in the handoff bundle.

## Running the smoke test

```bash
# with the handoff bundle unpacked next to this snapshot
python scripts/smoke_predict_action.py --bundle ../jetson_handoff
python scripts/smoke_predict_action.py --bundle ../jetson_handoff --device cpu
```

It loads `checkpoint.ckpt`, applies `ema_model`, feeds the 5-key reference
observation, runs `predict_action()` and decodes to `[16,3]` EE targets. No ROS,
no robot, no dataset.

### What to send back

```
ALL SMOKE CHECKS PASSED   yes / no
action shape              expect (1, 16, 10)
action finite             expect True
decoder parity            expect 0.000e+00      <- the one that must hold
decoded target shape      expect (16, 3)
inference latency         ms/call, and whether it ran on cpu or cuda
vs reference action       whatever it printed (informational, any value is fine)
python / torch / torchvision versions, JetPack version
```

If anything FAILs, send the whole output: every check names what it compared.

### Two things that matter on an offline Jetson

1. **`pretrained` must be forced to False.** The training config sets
   `policy.obs_encoder.pretrained: True`, so building the policy makes `timm`
   fetch CLIP weights from the HuggingFace hub. The checkpoint then overwrites
   every one of them. `smoke_predict_action.py` already forces it off, and
   verified on the GPU box that the output is bit-identical either way
   (`--check-pretrained`, max|d| = 0). Without this an offline Jetson fails at
   construction.
2. **Load `ema_model`, not `model`.** The packaged checkpoint contains only the
   EMA weights; `model` would be an untrained network.

## Installing the environment

`inference_requirements.txt` in this directory is the set actually needed, measured
by blocking each import and re-running the smoke test to `ALL SMOKE CHECKS PASSED`
on **python 3.10.12 / CPU**.

```bash
# 1. install the JetPack-matched PyTorch build first (torch, torchvision).
#    Never take these from PyPI on a Jetson.
# 2. then:
pip install -r inference_requirements.txt
```

Two pins are not optional:

| pin | what breaks without it |
|---|---|
| `huggingface_hub==0.25.2` | `diffusers 0.18.2` calls `huggingface_hub.constants.hf_cache_home`, removed in newer hub releases: `ImportError: cannot import name 'hf_cache_home'` |
| `numpy<2` | `torch 2.1.0` is built against the numpy 1.x ABI |

**Not needed**, confirmed by running without them: `wandb` and its stack
(`sentry-sdk`, `GitPython`, `wandb-*`), and **`av`**. `av` pulls ffmpeg, which is
the painful one on ARM.

> That is only true because `smoke_predict_action.py` builds the policy from
> `cfg.policy` directly. Going through the training workspace class that
> `cfg._target_` names would import wandb at module level and drag the whole
> stack in. If you write your own loader, instantiate `cfg.policy`, do not
> instantiate the workspace.

### Python and torch versions

The checkpoint is dill-pickled from **python 3.9 / dill 0.3.7 / torch 2.1.0**.
Verified on the GPU box that it loads and runs unchanged under:

| | result |
|---|---|
| python 3.10.12, torch 2.1.0 CPU | ALL SMOKE CHECKS PASSED, 433 ms/call |
| python 3.10.12, torch **2.5.1** CPU | ALL SMOKE CHECKS PASSED, 410 ms/call |

So the JetPack PyTorch does **not** have to be 2.1.0. Keep `dill` at `0.3.7`
though; a large version gap there can break the unpickle.

### Reference versions from the GPU box

Provenance, not an install list. The GPU server is x86_64 + CUDA 12.1.

| package | version |
|---|---|
| python | {env["python"]} |
{rows}

platform: `{env["platform"]}`

`pip_freeze.txt` and `environment.json` hold the full training environment.

## Verify after transfer

```bash
tar xzf jetson_inference_source_{tag}.tar.gz
cd jetson_inference_source
sha256sum -c SHA256SUMS
```
""")


if __name__ == "__main__":
    sys.exit(main())
