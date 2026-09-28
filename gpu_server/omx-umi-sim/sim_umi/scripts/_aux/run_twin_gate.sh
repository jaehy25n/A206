#!/usr/bin/env bash
# Twin gate: G0, A and B code paths, same seed / init / overrides as the definitive
# run, 20 optimizer steps each, one after the other on physical GPU 5, with the
# twin probe on. Nothing is saved but the probes (no checkpoints).
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
T=${TWIN_DIR:-sim_umi/train_results/2026-09-28_aux_ablations/twin}
PY=/home/j-j15a206/.conda/envs/umi/bin/python
INIT=$ROOT/sim_umi/train_results/2026-09-27_definitive/shared_init/init_state.pt
ENVV="env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=${TWIN_GPU:-5} MUJOCO_GL=egl WANDB_MODE=offline HYDRA_FULL_ERROR=1"
COMMON="task.dataset.val_ratio=0.0 training.seed=42 training.device=cuda:0 training.num_epochs=100 training.checkpoint_every=10 training.sample_every=5 training.resume=True +training.mixed_precision=fp16 +training.lr_scheduler_total_steps=11400 +training.checkpoint_at_steps=[] +training.init_state_path=$INIT task.dataset_path=$ROOT/sim_umi/data/omx_sim_train_v2.zarr.zip +training.max_opt_steps=20 +training.twin_probe_steps=20"
mkdir -p $T
for arm in g0 a b; do
  case $arm in
    g0) CN=train_diffusion_unet_timm_omx_workspace ;;
    a)  CN=train_diffusion_unet_timm_omx_timing_aux_workspace ;;
    b)  CN=train_diffusion_unet_timm_omx_oracle_tip_relation_film_workspace ;;
  esac
  D=$T/$arm
  if [ -e $D ]; then echo "$D exists -- not overwriting"; exit 1; fi
  echo "[$(date -Iseconds)] twin $arm start ($CN)"
  $ENVV $PY train.py --config-name=$CN $COMMON exp_name=twin_$arm +training.twin_probe_path=$ROOT/$D/probe hydra.run.dir=$D > $T/$arm.log 2>&1
  echo "[$(date -Iseconds)] twin $arm exit $?"
done
