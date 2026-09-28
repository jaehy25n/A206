# Reproducibility

## What this tree reproduces exactly

- **Code.** The tree of commit `3c3d9aa` on the local branch `omx-gpu-baseline`: 177
  commits on top of upstream UMI `d095ba9`, listed in
  [docs/git/COMMITS.md](docs/git/COMMITS.md).
  - Every training run records the commit it ran from in its `run_provenance.json`:
    `63048c5` for ablations A/B, `ad87c92` / `987ebe4` for the definitive runs.
  - Every evaluation records its commit in its chain log.
- **Configs.** Resolved hydra configs (`.hydra/config.yaml`) and overrides of every
  training run are next to its journal, and the exact launch commands are in the
  runner scripts:
  - `sim_umi/train_results/2026-09-27_definitive/run_training.sh` (clean, v2 = G0);
  - `sim_umi/scripts/aux/run_twin_gate.sh`, `sim_umi/scripts/aux/run_training_ablations.sh` (A, B);
  - `sim_umi/train_results/2026-09-27_fov/run_eval_dse.sh` (timing-controlled evaluation: G0 / G1 / G2 / A);
  - `sim_umi/train_results/2026-09-28_aux_ablations/run_eval_dse_masks.sh` + `bringup.sh` (mask evaluator: G0 control / B).
- **Results.** Every aggregate, table, gate marker, audit and journal is in the tree.
  The raw rollout JSONs are in `release_assets/` (see [PACKAGE_CONTENTS.md](PACKAGE_CONTENTS.md)).

## What is needed beyond this tree

| Item | Where it was | How to get it back |
|---|---|---|
| Demonstrations, zarrs, label / mask sidecars (1.3 GB) | `sim_umi/data/` (git-ignored) | Recollect with `sim_umi/ros/collect_demos.py`, then rebuild with `sim_umi/scripts/demos_to_umi_zarr.py` and `sim_umi/scripts/labels/*`. Or copy the originals and check them against [manifests/data_sha256.txt](manifests/data_sha256.txt). The sidecar summaries (`sim_umi/data/sidecars/*.json`) are in the tree |
| Checkpoints (96 files, 246 GB) | `sim_umi/train_results/*/checkpoints/` | Retrain with the runner scripts, or copy and verify against [manifests/checkpoints_key_sha256.txt](manifests/checkpoints_key_sha256.txt). The shared initial state `init_state.pt` (685 MB) is listed there too |
| CLIP ViT-B/16 weights | Hugging Face hub (`timm/vit_base_patch16_clip_224.openai`) | Downloaded by timm on first use |
| Patched `mujoco_ros2_control` | `~/omx_overlay` (camera patch 01), `~/omx_overlay_masks` (patch 02, mask evaluator only) | [external/mujoco_ros2_control/](external/mujoco_ros2_control/): upstream `58f465b` plus patches, the full patched plugin source, and build scripts |
| Python environments | conda envs `umi` (training, py3.9, torch 2.1.0+cu121, timm 0.9.7) and `omx_ros` (ROS 2 + MuJoCo 3.3.7, py3.12) | [ENVIRONMENT.md](ENVIRONMENT.md) and [env/](env/): `requirements-train.txt` + `colab/setup_colab.sh` (verified from scratch), `environment-train.yml`, `environment-sim-ros.yml`, pip freeze + package lists, `HOST.txt` |
| W&B logs | offline (`WANDB_MODE=offline`) | Not needed: each run's `logs.json.txt` holds every step |

## Portability notes

- **Absolute paths.** Many scripts and configs contain
  `/home/j-j15a206/universal_manipulation_interface` (178 files; runner scripts,
  `run_provenance.json`, and the dataset paths in the resolved configs). Clone to that
  path, create a symlink with that name, or replace the prefix. Python modules mostly
  derive `ROOT` from `__file__`.
- **GPUs.**
  - Training and policy inference ran with `CUDA_VISIBLE_DEVICES=5`; ablation A trained
    on GPU 0.
  - The plant renders through EGL with `MUJOCO_EGL_DEVICE_ID=5`, which lands on
    physical GPU 0 on this host because EGL enumerates devices differently from CUDA.
  - Never run training and closed-loop evaluation on the same GPU at once.
- **ROS.** `ROS_DOMAIN_ID=77`. The plant is `ros2 launch sim_umi/ros/launch/mujoco_bringup.launch.py`
  with `OMX_MUJOCO_PLUGINS=sim_umi/ros/config/mujoco_plugins_dse.yaml`. The mask
  evaluator uses `mujoco_plugins_dse_masks.yaml` with `env_overlay_masks.sh`; see
  `bringup.sh`.

## Determinism: what "reproduce" means here

- **Training.** The seed, the shared initial state, the batch order, the crops, the jitter
  and the diffusion noise are identical by construction. This was proven by the twin
  gate (`sim_umi/train_results/2026-09-28_aux_ablations/gates/twin_gate_r2.json`).
  GPU backward atomics still make two identical runs differ by about 1e-5 in loss from
  the first real update, so a retrained checkpoint is not bit-identical.
- **Evaluation.**
  - The timing-controlled evaluator fixes every event to a physics tick. Renderer noise
    (+-1 grey level) is not controlled, so repeats diverge after a few plans.
  - Outcome-level agreement between two runs of one checkpoint was 5/5 (G0), 4/5
    (G0 control) and 5/5 (B) episodes.
  - Two sporadic plant-side events are known: a single-tick corrupted effort sample,
    which trips arm_continuity, and a goal that is never EXECUTING. Either one makes that
    episode infra-invalid; such episodes are reported, never dropped.

## Git history note (before pushing to GitHub)

- **The problem.** Three local commits (`e5a10d4`, `d389856`, `3c3d9aa`) contain the
  mask evaluator's raw rollout JSONs, which are 80 MB to 1.1 GB each. GitHub rejects
  files over 100 MB, so the branch cannot be pushed as is.
- **Options.**
  - Push only this cleaned tree.
  - Rewrite those commits: move the files to Git LFS or drop them from history.
  - Keep the full history local.
- **This package.** It carries slimmed copies of those JSONs: every other field is kept
  and only the mask arrays are replaced by sha1 and shape.
