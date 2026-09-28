#!/usr/bin/env bash
# Mask-capable timing-controlled evaluation (ablation B and its G0 control), one phase per call:
#   run_eval_dse_masks.sh <phase> <subdir>
#     msmoke_g0  G0, nominal episode 0, masks generated and sent under "_" names (ignored)
#     msmoke_b   B,  nominal episode 0, masks sent to the policy
#     g0mask     G0 control, nominal 5, masks generated, ignored by the policy
#     bmask      B,  nominal 5, masks used
#   <subdir>: output folder under sim_umi/eval_results/2026-09-28_dse_masks
# Same frozen canonical condition as the G0/G1/G2 comparison: timing-controlled DSE, 0.6 s
# cadence (steps_per_inference 6), one physics step per call (DSE_BATCH 1), L_v 0.216 s,
# policy server on GPU 5 (EMA, deterministic, seed 1234). The plant must run the mask
# variant (env_overlay_masks.sh + OMX_MUJOCO_PLUGINS=mujoco_plugins_dse_masks.yaml).
# Full phases only on code whose smokes passed dse_mask_gate.py. Never overwrites an output.
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
F=sim_umi/train_results/2026-09-28_aux_ablations
E=sim_umi/eval_results/2026-09-28_dse_masks/${2:?give an output subdir}
LOG=$F/eval_chain_dse_masks.log
UMI=/home/j-j15a206/.conda/envs/umi/bin/python
G0=sim_umi/train_results/2026-09-27_amp_v2_definitive/checkpoints/step11400.ckpt
B=sim_umi/train_results/2026-09-28_g0_oracle_tip_relation_film_v1/checkpoints/step11400.ckpt
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
mkdir -p $E
if pgrep -af "train.py --config-name" | grep -q python; then say "a training process is alive -- evaluation refused"; exit 1; fi
if pgrep -a python | grep -qE "(policy_rollout|dse_rollout|dse_rollout_masks|step_audit|camera_step_test)[.]py"; then
  say "another rollout or plant audit is running -- evaluation refused"; exit 1; fi
NODE=$(ps -eo pid=,comm= | awk '$2 ~ /^ros2_control/ {print $1; exit}')
PLUG=$(tr '\0' '\n' < /proc/$NODE/environ 2>/dev/null | grep '^OMX_MUJOCO_PLUGINS=' | cut -d= -f2)
case "$PLUG" in *mujoco_plugins_dse_masks.yaml) ;; *) say "plant is not the mask variant ($PLUG) -- refused"; exit 1 ;; esac
say "DSE-MASK phase $1 -> $E, git $(git rev-parse --short HEAD), mask code $(python3 sim_umi/scripts/aux/dse_mask_gate.py --print-hash), batch ${DSE_BATCH:-1}, plant plugins $PLUG; GPUs: $(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader | sed -n '1p;6p' | tr '\n' ' ')"

run_job(){   # label ckpt masks_mode [extra rollout args]
  local label=$1 ckpt=$2 mm=$3 extra=${4:-}
  local tag=nominal_${label}
  local slog=$E/server_${tag}.log out=$E/${tag}.json rlog=$E/${tag}.log dump=$E/${tag}_encoder_input
  if [ -e $out ]; then say "$tag: output exists, not overwriting"; return; fi
  if [ ! -f $ckpt ]; then say "$tag: checkpoint missing: $ckpt"; return; fi
  rm -f /tmp/omx_policy.sock /tmp/omx_policy.sock.meta.json
  env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=5 \
    $UMI sim_umi/ros/policy_server.py --checkpoint $ckpt --device cuda:0 --deterministic --seed 1234 \
    --dump-dir $dump --dump-every 10 > $slog 2>&1 &
  local spid=$!
  for i in $(seq 1 120); do grep -q "listening on" $slog 2>/dev/null && break; sleep 3; done
  if ! grep -q "listening on" $slog; then say "$tag: server did not come up"; kill $spid 2>/dev/null; return; fi
  if ! grep -q "weights ema" $slog; then say "$tag: server is NOT serving EMA weights -- job aborted"; kill $spid; return; fi
  say "$tag: server pid $spid, masks $mm, $(grep '^checkpoint' $slog | cut -c1-170)"
  ARGS="--episodes 5 --horizon-steps 8 --max-ticks 600"
  ( set +u; source sim_umi/ros/env_overlay_masks.sh; python sim_umi/ros/dse_rollout_masks.py --oracle-masks $mm --mask-log $E/${tag}.masks.jsonl $ARGS $extra --batch ${DSE_BATCH:-1} --out $out ) > $rlog 2>&1
  local rc=$?
  kill $spid 2>/dev/null; wait $spid 2>/dev/null
  rm -f /tmp/omx_policy.sock /tmp/omx_policy.sock.meta.json
  say "$tag: rollout exit $rc; $(grep -E 'rollouts put the ball' $rlog | head -1)"
}

case "$1" in msmoke_g0|msmoke_b) ;; *)
  CH=$(python3 sim_umi/scripts/aux/dse_mask_gate.py --print-hash)
  if [ ! -f sim_umi/eval_results/2026-09-28_dse_masks/GATE_PASS_MASKS_$CH.json ]; then
    say "no mask hard-gate pass for code $CH -- full evaluation refused"; exit 1; fi ;;
esac
case "$1" in
  msmoke_g0) run_job G0 $G0 generate-only "--only 0" ;;
  msmoke_b)  run_job B $B send "--only 0" ;;
  g0mask)    run_job G0 $G0 generate-only ;;
  bmask)     run_job B $B send ;;
  *) echo "usage: $0 msmoke_g0|msmoke_b|g0mask|bmask <subdir>"; exit 2 ;;
esac
say "DSE-MASK PHASE $1 COMPLETE"
