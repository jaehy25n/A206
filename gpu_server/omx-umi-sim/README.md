# OMX-UMI: Diffusion Policy for a 5-DoF OpenMANIPULATOR-X, trained and evaluated in MuJoCo

A pick-and-place policy for a 5-DoF ROBOTIS OpenMANIPULATOR-X (OMX) with a custom
pivot gripper and a wrist camera, built on top of the
[Universal Manipulation Interface](https://umi-gripper.github.io/) (UMI) codebase.
Because the policy was trained and evaluated in closed loop in simulation, the
repository covers the whole chain:

- a MuJoCo + ROS 2 plant (ros2_control, a patched camera plugin, MoveIt);
- a scripted expert that records demonstrations;
- dataset builders;
- CLIP ViT-B/16 + Diffusion U-Net training;
- a closed-loop evaluator whose timing is controlled in simulated time;
- the ablations run on top of the baseline.

The upstream UMI README is kept at [docs/upstream/UMI_README.md](docs/upstream/UMI_README.md).

> This tree is a snapshot of the local branch `omx-gpu-baseline` at commit
> `3c3d9aa`, plus the result files and external sources listed in
> [PACKAGE_CONTENTS.md](PACKAGE_CONTENTS.md). Datasets and checkpoints are not
> included: they are listed with sha256 in [manifests/](manifests/).

## What is where

| Path | Contents |
|---|---|
| `sim_umi/` | Everything simulation-side (listed in the rows below) |
| `sim_umi/mjcf/collector_scene.xml` | MuJoCo model of the arm, gripper, wrist camera, table, ball and bin. The plant loads it, and so does every mirror or renderer |
| `sim_umi/ros/` | ROS 2 side: `mujoco_bringup.launch.py` (the plant), `collect_demos.py` (scripted expert), `policy_server.py` (the model), `policy_bridge.py` / `rolling_executor.py` / `policy_rollout.py` (asynchronous closed loop), `dse_rollout.py` (timing-controlled evaluator), `dse_rollout_masks.py` (the same with oracle masks) |
| `sim_umi/src/` | Kinematics (`collector.py`), camera-based gripper width (`gripper_vision.py`), image geometries (`rgb_geometry.py`), oracle state / render / masks (`oracle_*.py`) |
| `sim_umi/scripts/` | Dataset building (`demos_to_umi_zarr.py`), audits, analysis, the FOV, DSE, label, aux and definitive toolsets |
| `sim_umi/train_results/<date>_<exp>/` | Per experiment: `JOURNAL.md` (purpose / control / result / interpretation, as it ran), design notes, runner scripts, resolved configs, training logs, checkpoint audits |
| `sim_umi/eval_results/<date>_<exp>/` | Closed-loop evaluation outputs: aggregates, tables, videos, gate markers |
| `diffusion_policy/` | UMI's Diffusion Policy with this project's changes. Four upstream files were modified: the training workspace, the base workspace, the timm obs encoder and `umi_dataset`. The added pieces are the OMX configs, the two ablation policies, the relation-FiLM encoder, the aux dataset and the twin probe |
| `omx/` | GPU-server data pipeline for real recordings (`processed_v1` to UMI zarr), the CLI, and the rectangular ViT encoder |
| `jetson_handoff/`, `README_JETSON_*.md`, `deliverables/jetson/` | Inference handoff to the Jetson robot controller |
| `external/mujoco_ros2_control/` | The patched `mujoco_ros2_control` camera plugin (source and diffs against upstream `58f465b`) with its build scripts |
| `env/`, `colab/` | Install files: `requirements-train.txt`, `environment-train.yml`, `environment-sim-ros.yml`; the Colab setup script and notebook; pip freeze / package lists of both host envs; `HOST.txt` |
| `manifests/` | sha256 and size of every dataset file and every checkpoint that is not shipped |
| `docs/` | [INDEX.md](docs/INDEX.md) (every document), [git/COMMITS.md](docs/git/COMMITS.md) (the 177 local commits) |

## Start here

- [ARCHITECTURE.md](ARCHITECTURE.md): the system, the model and the two evaluators, with diagrams.
- [RESULTS.md](RESULTS.md): every headline result in one place, with links to the evidence.
- [ENVIRONMENT.md](ENVIRONMENT.md): step-by-step environment setup (training env verified from scratch; simulator / ROS 2 and Google Colab as a guide).
- [REPRODUCIBILITY.md](REPRODUCIBILITY.md): what reproduces from this tree, what is needed beyond it, and how.
- [MEDIA.md](MEDIA.md): videos and figures.
- [docs/INDEX.md](docs/INDEX.md): journals, design documents and reports, in order.

## Results in one paragraph

On the frozen, timing-controlled canonical condition (nominal placements, 5
episodes, 2 runs each):

- **Baseline.** The G0 baseline (center-crop geometry, v2 dataset, 11 400 updates)
  lifts the ball in 8 of 10 episodes and bins it in 2 of 10.
- **FOV.** Wider-FOV inputs do worse. G1 letterbox lifts 4/10 and bins 0/10; G2
  rectangular ViT lifts 2/10 and bins 1/10.
- **Ablation A (timing aux).** A train-only time-to-close/lift/open auxiliary
  regression makes the policy close deeper, but nearly level, and lifts drop to
  5/10.
- **Ablation B (oracle relation FiLM).** Relation features between the oracle
  target and the fingertip patches, applied as a FiLM, double strict secure grasps
  and bin placements against a G0 control run on the same evaluator: 6/10 vs 3/10
  and 4/10 vs 2/10. Lifts are 6 vs 7.
- **Caveats.** Every comparison has n = 10 per arm and no significance is claimed.
  B consumes simulator ground-truth masks, so it is not a deployable policy.

See [RESULTS.md](RESULTS.md).

## License

Upstream UMI code: MIT, (c) 2023 Columbia Artificial Intelligence and Robotics Lab
([LICENSE](LICENSE)). The additions in this tree follow the repository owner's
licensing decision; no separate license has been applied yet.
