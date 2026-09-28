# Environment setup guide

The project uses two Python environments. They are separate because ROS 2 Jazzy needs
Python 3.12, while the training stack (torch 2.1.0) needs Python 3.9 to 3.11.

| env | used for | Python | on the training host |
|---|---|---|---|
| **train** (`umi`) | dataset building, training, the policy server, offline analysis, oracle mask rendering, unit tests / twin gate | 3.9 | `~/.conda/envs/umi` |
| **sim** (`omx_ros`) | the MuJoCo + ROS 2 plant, the scripted expert, both closed-loop evaluators | 3.12 | `~/.conda/envs/omx_ros` |

The host itself: Ubuntu 22.04, 8x Tesla V100-PCIE-32GB, driver 570.211
([env/HOST.txt](env/HOST.txt)).

## Verification status (2026-09-28, on the training host)

| Step | Status |
|---|---|
| §1 train env from scratch via `colab/setup_colab.sh` (micromamba, Python 3.9 + `env/requirements-train.txt`) | **verified** |
| In that fresh env: `sim_umi/scripts/aux/unit_tests.py` | **22/22 PASS** |
| In that fresh env: 20-step G0 training smoke on GPU | **step-0 loss bit-identical** to the original env (1.1018394231796265), and sample order / crops / jitter / RNG / diffusion noise identical at all 20 steps |
| In that fresh env: `oracle_render_regression.py` (EGL) | **PASS**: 1078 rows bit-identical to the frozen sidecar |
| §2 `env/environment-train.yml` (conda route) | written from the host env, not re-solved from scratch. `umi_working_env.yml` is the host's exact export |
| §3 sim env + overlay | **guide only**. Written from the host env and its build scripts, not rebuilt from scratch |
| §4 Google Colab | the §1 script is exactly what Colab runs, but it was **not run on Colab itself**. The ROS 2 plant is not expected to run there |

## 1. Training env (verified)

The same steps work on any Linux x86-64 machine with an NVIDIA driver that supports
CUDA 12.1.

```bash
# get the code: this package, or upstream UMI + this tree
unzip omx_umi_github_*.zip && cd omx-umi-sim
#   or, starting from upstream:
#   git clone https://github.com/real-stanford/universal_manipulation_interface.git
#   cd universal_manipulation_interface && git checkout d095ba9   # the base this project forked from
#   cp -r /path/to/omx-umi-sim/. .                                # this project's tree on top (same layout)

bash colab/setup_colab.sh       # micromamba -> ./.mamba/envs/omx: python 3.9, av 10.0 + gym 0.21 from conda-forge,
                                # then pip install -r env/requirements-train.txt (torch 2.1.0+cu121 ...)
source colab/activate.sh        # PATH, MUJOCO_GL=egl, PYTHONNOUSERSITE=1
python -c "import torch; print(torch.cuda.is_available())"
```

Pitfalls this procedure already handles, all found while verifying it:

- **`av==10.0.0`.** There is no pip wheel for Python 3.9, and building the sdist needs
  FFmpeg development headers. It is installed from conda-forge instead.
- **`gym==0.21.0`.** Its `setup.py` is rejected by current setuptools, so it is
  installed from conda-forge.
- **`huggingface_hub`.** It must stay at 0.25.2: diffusers 0.18.2 imports
  `cached_download`, which was removed in 0.26.
- **`imagecodecs==2023.9.18`.** It is needed for the zarrs' JPEG-XL image codec. The
  setup script prints `jpegxl True` when it works.
- **Python 3.12 and later.** torch 2.1.0 has no wheels there. This is why the script
  creates its own Python 3.9 instead of using the system Python.

The upstream UMI extras (ur-rtde, spnav, robosuite, free-mujoco-py) are not installed.
They are only for the real UR5 / Franka robots, and nothing in this project imports them.

## 2. Training env, conda route (the host's way)

```bash
mamba env create -f env/environment-train.yml   # readable spec, pinned to the host's versions
# or, byte-for-byte the host (build strings included):
mamba env create -f umi_working_env.yml
conda activate umi
```

This is how upstream UMI builds its env (`conda_environment.yaml`), with this project's
additions: wandb 0.22.3, huggingface-hub 0.25.2 and mujoco 3.3.7. Since 2025 the pytorch
conda channel no longer receives new builds. The old 2.1.0 builds are still there, but
if the solve fails, use §1.

## 3. Simulator env + patched `mujoco_ros2_control` (guide)

```bash
# 3.1 ROS 2 Jazzy + MoveIt + ros2_control from RoboStack, Python 3.12
micromamba create -f env/environment-sim-ros.yml && micromamba activate omx_ros

# 3.2 the overlay: mujoco_ros2_control at upstream 58f465b + this project's camera patch
mkdir -p ~/omx_overlay/src && cd ~/omx_overlay/src
git clone https://github.com/ros-controls/mujoco_ros2_control.git && cd mujoco_ros2_control
git checkout 58f465b1b4634a6f366e71919189574f5d95c1e8
git apply /path/to/omx-umi-sim/external/mujoco_ros2_control/patches/01_camera_sim_state_trigger_and_joint_snapshot.diff
cd ~/omx_overlay && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    --packages-select mujoco_ros2_control_plugins mujoco_ros2_control
#   (the exact commands used: external/mujoco_ros2_control/build/build_overlay.sh)

# 3.3 only for the mask-capable evaluator (ablation B and its control): the plugin with
#     the free-joint snapshot, built into a SEPARATE overlay so the plain evaluator is untouched
mkdir -p ~/omx_overlay_masks/src && cp -r /path/to/omx-umi-sim/external/mujoco_ros2_control/mujoco_ros2_control_plugins_patched \
    ~/omx_overlay_masks/src/mujoco_ros2_control_plugins
source ~/omx_overlay/install/setup.bash && cd ~/omx_overlay_masks && colcon build --symlink-install \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF --packages-select mujoco_ros2_control_plugins
#   (external/mujoco_ros2_control/build/build_overlay_masks.sh)

# 3.4 run the plant
source sim_umi/ros/env_overlay.sh      # or env_overlay_masks.sh for the mask evaluator
CUDA_VISIBLE_DEVICES=5 OMX_MUJOCO_PLUGINS=$PWD/sim_umi/ros/config/mujoco_plugins_dse.yaml \
    ros2 launch sim_umi/ros/launch/mujoco_bringup.launch.py
#   or: bash sim_umi/train_results/2026-09-28_aux_ablations/bringup.sh plain|masks
```

Things this guide cannot guarantee, and what to check:

- **Hard-coded paths.** `sim_umi/ros/env_overlay.sh`, `sim_umi/ros/description/omx_f_mujoco.urdf`
  (`<mujoco_model>`) and the runner scripts contain `/home/j-j15a206/...`. Clone to that
  path, create a symlink with that name, or edit those paths.
- **EGL device.** `MUJOCO_EGL_DEVICE_ID` indexes EGL devices, not CUDA devices; on the
  host, `5` rendered on physical GPU 0. Check with `nvidia-smi` which GPU the plant
  lands on.
- **Isolation and GPU sharing.** Use a `ROS_DOMAIN_ID` of your own (the host used 77).
  Never run training and a closed-loop evaluation on the same GPU.
- **Controller cycle.** If the logs show a controller cycle skipped on `/clock` ticks
  that are 1 ns short, that is the known behaviour of mujoco_ros2_control 0.1.2. The
  DSE records it (see `DSE_DESIGN.md`).
- **Evaluator hard gate.** A new install must pass the evaluator's hard gate before its
  results count:
  `bash sim_umi/train_results/2026-09-27_fov/run_eval_dse.sh smoke <subdir>`, then
  `python3 sim_umi/scripts/dse/dse_gate.py <json> --mark`. For the mask evaluator the
  equivalents are `run_eval_dse_masks.sh msmoke_g0 / msmoke_b` and `dse_mask_gate.py`.

## 4. Google Colab

```python
# in a Colab cell, GPU runtime
!unzip -q /content/drive/MyDrive/omx_umi_github_*.zip -d /content
%cd /content/omx-umi-sim
!bash colab/setup_colab.sh
```

Or open [colab/omx_umi_colab.ipynb](colab/omx_umi_colab.ipynb).

What runs on Colab:

| Works (same code path as verified above) | Does not |
|---|---|
| Building zarrs from demos (`demos_to_umi_zarr.py`) and the label / oracle-mask sidecars (EGL rendering on the Colab GPU) | The MuJoCo + ROS 2 plant, the scripted expert and both closed-loop evaluators. They need the RoboStack ROS 2 Jazzy stack, a colcon-built C++ overlay and long-lived ROS processes. That is not practical on Colab and has not been tried |
| Training every config (G0, A, B, G1, G2); unit tests and the twin gate | Real-robot / Jetson paths |
| Offline analysis of the logged rollouts (`aggregate.py`, tables, repeat comparisons) | |

Colab specifics:

- **Data.** Datasets and checkpoints are not in the package. Put `sim_umi/data/` (1.3 GB)
  and any checkpoints on Drive and copy them in. Check them against
  `manifests/*_sha256.txt`.
- **GPU.** Colab exposes one GPU, `cuda:0`: use `CUDA_VISIBLE_DEVICES=0` where the
  scripts say 5. Batch 64 with fp16 used about 13 GB on a V100, which should fit a 16 GB
  T4 (not measured). A T4 is slower than a V100: the host needed about 80 min for
  11 400 updates.
- **Paths.** Configs and runner scripts use `/home/j-j15a206/universal_manipulation_interface`.
  Run `!mkdir -p /home/j-j15a206 && ln -s /content/omx-umi-sim /home/j-j15a206/universal_manipulation_interface`,
  or pass `task.dataset_path=...` and `training.init_state_path=...` explicitly.
- **W&B.** Set `WANDB_MODE=offline`, as all the reported runs did.
