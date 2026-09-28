#!/usr/bin/env bash
# FOV evaluation, one phase per call:
#   run_eval_fov.sh g0    -- G0 (definitive v2_11400) regression with the instrumented evaluator
#   run_eval_fov.sh g12   -- G1 then G2 at step 11400, only after the G0 regression passed
# Same executor, reset, placements and episode sets as the definitive evaluation. One
# policy server at a time on physical GPU 5 (EMA weights, deterministic, seed 1234); the
# simulator keeps rendering on GPU 0 as it always has. Refuses to start while any
# training process is alive. Never overwrites an output.
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
F=sim_umi/train_results/2026-09-27_fov
E=sim_umi/eval_results/2026-09-27_fov
LOG=$F/eval_chain_fov.log
UMI=/home/j-j15a206/.conda/envs/umi/bin/python
G0=sim_umi/train_results/2026-09-27_amp_v2_definitive/checkpoints/step11400.ckpt
G1=sim_umi/train_results/2026-09-27_fov_g1_letterbox224/checkpoints/step11400.ckpt
G2=sim_umi/train_results/2026-09-27_fov_g2_rect288x176/checkpoints/step11400.ckpt
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
mkdir -p $E
if pgrep -f "train.py --config-name=train_diffusion_unet_timm_omx_workspace" > /dev/null; then
  say "a training process is still alive -- evaluation refused"; exit 1
fi
say "phase $1, git $(git rev-parse --short HEAD); GPUs: $(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader | sed -n '1p;6p' | tr '\n' ' ')"

run_job(){   # label ckpt mode
  local label=$1 ckpt=$2 mode=$3
  local tag=${mode}_${label}
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
  say "$tag: server pid $spid, $(grep '^checkpoint' $slog | cut -c1-170), $(grep '^geometry' $slog | cut -c1-40)"
  if [ "$mode" = nominal ]; then
    ARGS="--episodes 5 --horizon-steps 8 --max-ticks 600"
  else
    ARGS="--from-demos v2_val --episodes 18 --start-perturbed --horizon-steps 8 --max-ticks 400"
  fi
  ( set +u; source sim_umi/ros/env_overlay.sh; python sim_umi/ros/policy_rollout.py $ARGS --out $out ) > $rlog 2>&1
  local rc=$?
  kill $spid 2>/dev/null; wait $spid 2>/dev/null
  rm -f /tmp/omx_policy.sock /tmp/omx_policy.sock.meta.json
  say "$tag: rollout exit $rc; $(grep -E 'rollouts put the ball' $rlog | head -1); geometry used: $(grep -E '^image geometry' $rlog | cut -c1-60)"
  grep -E "INFRA FAILURE|not ready" $rlog | sed "s/^/    [$tag] /" >> $LOG
}

case "$1" in
  g0)  run_job G0 $G0 nominal; run_job G0 $G0 val18 ;;
  g12) run_job G1 $G1 nominal; run_job G1 $G1 val18; run_job G2 $G2 nominal; run_job G2 $G2 val18 ;;
  *) echo "usage: $0 g0|g12"; exit 2 ;;
esac
say "PHASE $1 COMPLETE"
