#!/usr/bin/env bash
# Definitive evaluation chain, second launch: the first was stopped at 06:05 when
# the start order was found to let the arm sweep freshly placed bodies
# (fixed in a721932). Same jobs, same order, same arguments.
# one policy server at a time on GPU 5, EMA weights, deterministic
# preprocessing, seed 1234; the same final executor and placements for every
# checkpoint. A job that fails is logged and the chain moves on -- nothing is
# re-run until it succeeds.
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
D=sim_umi/train_results/2026-09-27_definitive
E=sim_umi/eval_results/2026-09-27_definitive
LOG=$D/eval_chain2.log
UMI=/home/j-j15a206/.conda/envs/umi/bin/python
CLEAN=sim_umi/train_results/2026-09-27_amp_clean_definitive/checkpoints
V2=sim_umi/train_results/2026-09-27_amp_v2_definitive/checkpoints
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
mkdir -p $E

say "rerun with the fixed start (rollout code $(git rev-parse --short HEAD)); training chain already complete and audited"
say "GPU 5 now: $(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader | sed -n '6p')"

run_job(){   # label ckpt mode
  local label=$1 ckpt=$2 mode=$3
  local slog=$E/server_${label}.log out=$E/${mode}_${label}.json rlog=$E/${mode}_${label}.log
  if [ -e $out ]; then say "$label/$mode: output exists, not overwriting"; return; fi
  if [ ! -f $ckpt ]; then say "$label/$mode: checkpoint missing: $ckpt"; return; fi
  rm -f /tmp/omx_policy.sock
  env -u PYTHONPATH -u LD_LIBRARY_PATH -u ROS_DISTRO -u AMENT_PREFIX_PATH CUDA_VISIBLE_DEVICES=5 \
    $UMI sim_umi/ros/policy_server.py --checkpoint $ckpt --device cuda:0 --deterministic --seed 1234 > $slog 2>&1 &
  local spid=$!
  for i in $(seq 1 120); do grep -q "listening on" $slog 2>/dev/null && break; sleep 3; done
  if ! grep -q "listening on" $slog; then say "$label/$mode: server did not come up"; kill $spid 2>/dev/null; return; fi
  if ! grep -q "weights ema" $slog; then say "$label/$mode: server is NOT serving EMA weights -- aborting job"; kill $spid; return; fi
  say "$label/$mode: server up (pid $spid) on $(grep '^checkpoint' $slog | cut -c1-160)"
  if [ "$mode" = nominal ]; then
    ARGS="--episodes 5 --horizon-steps 8 --max-ticks 600"
  else
    ARGS="--from-demos v2_val --episodes 18 --start-perturbed --horizon-steps 8 --max-ticks 400"
  fi
  ( set +u; source sim_umi/ros/env_overlay.sh; python sim_umi/ros/policy_rollout.py $ARGS --out $out ) > $rlog 2>&1
  local rc=$?
  kill $spid 2>/dev/null; wait $spid 2>/dev/null
  rm -f /tmp/omx_policy.sock
  say "$label/$mode: rollout exit $rc; $(grep -E 'rollouts put the ball' $rlog | head -1)"
  grep -E "INFRA FAILURE|not ready" $rlog | sed "s/^/    [$label] /" >> $LOG
}

# primary: nominal 5 for the five checkpoints, then the perturbed 18
run_job clean5986  $CLEAN/step5986.ckpt  nominal
run_job v2_5986    $V2/step5986.ckpt     nominal
run_job v2_8000    $V2/step8000.ckpt     nominal
run_job v2_10000   $V2/step10000.ckpt    nominal
run_job v2_11400   $V2/step11400.ckpt    nominal
run_job clean5986  $CLEAN/step5986.ckpt  val18
run_job v2_5986    $V2/step5986.ckpt     val18
run_job v2_11400   $V2/step11400.ckpt    val18
# then, time permitting
run_job v2_8000    $V2/step8000.ckpt     val18
run_job v2_10000   $V2/step10000.ckpt    val18
run_job clean5985  $CLEAN/step5985.ckpt  nominal
run_job v2_5985    $V2/step5985.ckpt     nominal
say "EVAL CHAIN COMPLETE"
