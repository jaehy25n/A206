#!/usr/bin/env bash
# Full training of the two ablations, started together, only after a twin-gate PASS:
#   GPU 0  g0_timing_aux_v1                 (ablation A)
#   GPU 5  g0_oracle_tip_relation_film_v1   (ablation B)
# Same overrides as the definitive G0 run (run_training.sh COMMON) except the
# checkpoint list the user fixed (5986, 8000, 10000, 11400 successful updates).
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
E=sim_umi/train_results/2026-09-28_aux_ablations
PY=/home/j-j15a206/.conda/envs/umi/bin/python
INIT=$ROOT/sim_umi/train_results/2026-09-27_definitive/shared_init/init_state.pt
INIT_SHA=a4cd264fbf9439ef9d8b3fdb4dc51e3559ec82559dbeab591faa8cce06c28076
LOG=$E/training_chain.log
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
grep -q '"verdict": "PASS"' $E/gates/twin_gate_r2.json || { say "twin gate not PASS -- refusing to train"; exit 1; }
COMMON="task.dataset.val_ratio=0.0 training.seed=42 training.device=cuda:0 training.num_epochs=100 training.checkpoint_every=10 training.sample_every=5 training.resume=True +training.mixed_precision=fp16 +training.lr_scheduler_total_steps=11400 +training.checkpoint_at_steps=[5986,8000,10000,11400] +training.init_state_path=$INIT task.dataset_path=$ROOT/sim_umi/data/omx_sim_train_v2.zarr.zip +training.max_opt_steps=11400"
A_DIR=sim_umi/train_results/2026-09-28_g0_timing_aux_v1
B_DIR=sim_umi/train_results/2026-09-28_g0_oracle_tip_relation_film_v1
for d in $A_DIR $B_DIR; do [ -e $d ] && { say "$d exists -- refusing to overwrite"; exit 1; }; done
say "start, git $(git rev-parse HEAD)"
env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=0 MUJOCO_GL=egl WANDB_MODE=offline HYDRA_FULL_ERROR=1 \
  $PY train.py --config-name=train_diffusion_unet_timm_omx_timing_aux_workspace $COMMON exp_name=g0_timing_aux_v1 hydra.run.dir=$A_DIR > $E/train_g0_timing_aux_v1.log 2>&1 &
APID=$!
env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=5 MUJOCO_GL=egl WANDB_MODE=offline HYDRA_FULL_ERROR=1 \
  $PY train.py --config-name=train_diffusion_unet_timm_omx_oracle_tip_relation_film_workspace $COMMON exp_name=g0_oracle_tip_relation_film_v1 hydra.run.dir=$B_DIR > $E/train_g0_oracle_tip_relation_film_v1.log 2>&1 &
BPID=$!
say "A pid $APID (GPU 0), B pid $BPID (GPU 5)"
wait $APID; ra=$?; say "A exit $ra"
wait $BPID; rb=$?; say "B exit $rb"
for arm in A B; do
  D=$A_DIR; [ $arm = B ] && D=$B_DIR
  for t in 5986 8000 10000 11400; do
    [ -f $D/checkpoints/step$t.ckpt ] || { say "$arm step$t checkpoint missing"; continue; }
    env -u PYTHONPATH CUDA_VISIBLE_DEVICES="" $PY sim_umi/scripts/definitive/audit_checkpoint.py $D/checkpoints/step$t.ckpt --expect-init $INIT_SHA --out $D/checkpoints/step$t.audit.json >> $LOG 2>&1 && say "$arm step$t audit PASS" || say "$arm step$t audit FAIL"
  done
done
say "TRAINING CHAIN COMPLETE (A $ra, B $rb)"
