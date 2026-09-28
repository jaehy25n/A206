#!/usr/bin/env bash
# Definitive training chain: clean AMP -> audit -> v2 AMP -> audit.
# Every gate that fails writes HARD_FAIL and stops the chain.
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
D=sim_umi/train_results/2026-09-27_definitive
PY=/home/j-j15a206/.conda/envs/umi/bin/python
INIT=$ROOT/$D/shared_init/init_state.pt
INIT_SHA=a4cd264fbf9439ef9d8b3fdb4dc51e3559ec82559dbeab591faa8cce06c28076
CLEAN_DIR=sim_umi/train_results/2026-09-27_amp_clean_definitive
V2_DIR=sim_umi/train_results/2026-09-27_amp_v2_definitive
LOG=$D/training_chain.log
ENVV="env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=5 MUJOCO_GL=egl WANDB_MODE=offline HYDRA_FULL_ERROR=1"
COMMON="--config-name=train_diffusion_unet_timm_omx_workspace task.dataset.val_ratio=0.0 training.seed=42 training.device=cuda:0 training.num_epochs=100 training.checkpoint_every=10 training.sample_every=5 training.resume=True +training.mixed_precision=fp16 +training.lr_scheduler_total_steps=11400 +training.checkpoint_at_steps=[5985,5986,8000,10000,11400] +training.init_state_path=$INIT"
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
fail(){ say "HARD FAIL: $*"; echo "$*" > $D/HARD_FAIL_training.txt; exit 1; }

say "chain start, git $(git rev-parse HEAD)"
[ -e $CLEAN_DIR ] && fail "$CLEAN_DIR already exists -- refusing to overwrite"
[ -e $V2_DIR ] && fail "$V2_DIR already exists -- refusing to overwrite"

say "CLEAN AMP: start (max_opt_steps 5986)"
$ENVV $PY train.py $COMMON task.dataset_path=$ROOT/sim_umi/data/omx_sim_train.zarr.zip exp_name=amp_clean_definitive +training.max_opt_steps=5986 hydra.run.dir=$CLEAN_DIR > $D/train_clean.log 2>&1
rc=$?; say "CLEAN AMP: exit $rc"
[ $rc -ne 0 ] && fail "clean training exited $rc (see train_clean.log)"
for t in 5985 5986; do
  $ENVV $PY sim_umi/scripts/definitive/audit_checkpoint.py $CLEAN_DIR/checkpoints/step$t.ckpt --expect-init $INIT_SHA --out $CLEAN_DIR/checkpoints/step$t.audit.json >> $LOG 2>&1 || fail "clean step$t checkpoint audit failed"
done
say "CLEAN AMP: checkpoints audited"

say "V2 AMP: start (max_opt_steps 11400)"
$ENVV $PY train.py $COMMON task.dataset_path=$ROOT/sim_umi/data/omx_sim_train_v2.zarr.zip exp_name=amp_v2_definitive +training.max_opt_steps=11400 hydra.run.dir=$V2_DIR > $D/train_v2.log 2>&1 &
V2PID=$!
# config gate: once v2 has written its resolved config, it may differ from
# clean's only in dataset path, experiment name, step budget and timestamps
for i in $(seq 1 60); do [ -s $V2_DIR/.hydra/config.yaml ] && break; sleep 5; done
diff <(sed 's/^ *//' $CLEAN_DIR/.hydra/config.yaml) <(sed 's/^ *//' $V2_DIR/.hydra/config.yaml) | grep '^[<>]' > $D/config_diff_clean_vs_v2.txt
BAD=$(grep -vE '^[<>] (exp_name: |dataset_path: |max_opt_steps: |name: [0-9]{4}\.|run_dir: |wandb_name_base: |dir: )' $D/config_diff_clean_vs_v2.txt | grep -v '^$' || true)
if [ -n "$BAD" ]; then kill $V2PID; fail "unintended config difference: $BAD"; fi
say "V2 AMP: config diff vs clean limited to intended keys ($(wc -l < $D/config_diff_clean_vs_v2.txt) lines)"
wait $V2PID; rc=$?; say "V2 AMP: exit $rc"
[ $rc -ne 0 ] && fail "v2 training exited $rc (see train_v2.log)"
for t in 5985 5986 8000 10000 11400; do
  $ENVV $PY sim_umi/scripts/definitive/audit_checkpoint.py $V2_DIR/checkpoints/step$t.ckpt --expect-init $INIT_SHA --out $V2_DIR/checkpoints/step$t.audit.json >> $LOG 2>&1 || fail "v2 step$t checkpoint audit failed"
done
say "V2 AMP: checkpoints audited"
say "TRAINING CHAIN COMPLETE"
