#!/usr/bin/env bash
# (Re)launch the timing-controlled plant exactly as it ran before training
# (dse_bringup_before_training.txt): mujoco_bringup with CUDA_VISIBLE_DEVICES=5,
# MUJOCO_EGL_DEVICE_ID=5 (lands on physical GPU 0), ROS_DOMAIN_ID 77.
#   bringup.sh plain   -- env_overlay.sh + mujoco_plugins_dse.yaml         (A, the unchanged evaluator)
#   bringup.sh masks   -- env_overlay_masks.sh + mujoco_plugins_dse_masks.yaml (B and its G0 control)
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
L=sim_umi/train_results/2026-09-28_aux_ablations/bringup_$1_$(date +%H%M%S).log
if ps -eo comm= | grep -q "^ros2_control"; then echo "a plant is already running -- refusing"; exit 1; fi
case "$1" in
  plain) ENVF=sim_umi/ros/env_overlay.sh; PLUG=$ROOT/sim_umi/ros/config/mujoco_plugins_dse.yaml ;;
  masks) ENVF=sim_umi/ros/env_overlay_masks.sh; PLUG=$ROOT/sim_umi/ros/config/mujoco_plugins_dse_masks.yaml ;;
  *) echo "usage: $0 plain|masks"; exit 2 ;;
esac
( set +u; source $ENVF; export CUDA_VISIBLE_DEVICES=5 OMX_MUJOCO_PLUGINS=$PLUG; \
  setsid nohup ros2 launch sim_umi/ros/launch/mujoco_bringup.launch.py > $L 2>&1 & )
for i in $(seq 1 90); do grep -q "Joint snapshot of every capture" $L 2>/dev/null && break; sleep 2; done
grep -E "Camera trigger|Joint snapshot of every capture" $L | cut -c1-200
echo "log $L"
