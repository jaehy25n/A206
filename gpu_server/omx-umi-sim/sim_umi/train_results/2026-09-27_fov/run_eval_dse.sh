#!/usr/bin/env bash
# Deterministic sim-time evaluation (DSE), one phase per call:
#   run_eval_dse.sh <phase> <subdir>
#     smoke   -- G0 nominal episode 0 only
#     g0rep   -- G0 nominal episodes 0,1 (the reproducibility check; run twice into two subdirs)
#     g0 | g1 | g2 -- the full set for one checkpoint: nominal 5 + perturbation val18
#     g0nom   -- G0 nominal 5 only
#   <subdir>: output folder under sim_umi/eval_results/2026-09-27_dse
# Policy server on physical GPU 5 only (EMA weights, deterministic, seed 1234), as in the
# asynchronous evaluation. The plant is paused by the rollout for its whole duration and
# resumed at the end. Refuses to start while training, another rollout or a plant audit is
# running. Never overwrites an output.
set -u
ROOT=/home/j-j15a206/universal_manipulation_interface
cd $ROOT
F=sim_umi/train_results/2026-09-27_fov
E=sim_umi/eval_results/2026-09-27_dse/${2:?give an output subdir}
LOG=$F/eval_chain_dse.log
UMI=/home/j-j15a206/.conda/envs/umi/bin/python
G0=sim_umi/train_results/2026-09-27_amp_v2_definitive/checkpoints/step11400.ckpt
G1=sim_umi/train_results/2026-09-27_fov_g1_letterbox224/checkpoints/step11400.ckpt
G2=sim_umi/train_results/2026-09-27_fov_g2_rect288x176/checkpoints/step11400.ckpt
# ablation A (timing aux): the evaluator is unchanged -- its head is never evaluated
A=sim_umi/train_results/2026-09-28_g0_timing_aux_v1/checkpoints/step11400.ckpt
say(){ echo "[$(date -Iseconds)] $*" | tee -a $LOG; }
mkdir -p $E
if pgrep -f "train.py --config-name=train_diffusion_unet_timm_omx_workspace" > /dev/null; then
  say "a training process is still alive -- evaluation refused"; exit 1; fi
# python processes only: a shell whose command text merely mentions these names is not one
if pgrep -a python | grep -qE "(policy_rollout|dse_rollout|step_audit|camera_step_test)[.]py"; then
  say "another rollout or plant audit is running -- evaluation refused"; exit 1; fi
say "DSE phase $1 -> $E, git $(git rev-parse --short HEAD), batch ${DSE_BATCH:-5}; load $(cut -d' ' -f1-3 /proc/loadavg); GPUs: $(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader | sed -n '1p;6p' | tr '\n' ' ')"

run_job(){   # label ckpt mode [extra rollout args]
  local label=$1 ckpt=$2 mode=$3 extra=${4:-}
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
  # physics steps per StepSimulation call between events (DSE_BATCH, default 5): with 5
  # back-to-back steps the plant's try-published /clock occasionally drops a tick, and the
  # controller manager misses that tick too -- one step per call avoids back-to-back steps
  ( set +u; source sim_umi/ros/env_overlay.sh; python sim_umi/ros/dse_rollout.py $ARGS $extra --batch ${DSE_BATCH:-5} --out $out ) > $rlog 2>&1
  local rc=$?
  kill $spid 2>/dev/null; wait $spid 2>/dev/null
  rm -f /tmp/omx_policy.sock /tmp/omx_policy.sock.meta.json
  say "$tag: rollout exit $rc; $(grep -E 'rollouts put the ball' $rlog | head -1)"
}

# full evaluations only on code whose smoke passed every hard gate
if [ "$1" != smoke ] && [ "$1" != g0rep ]; then
  CH=$(python3 sim_umi/scripts/dse/dse_gate.py --print-hash)
  if [ ! -f sim_umi/eval_results/2026-09-27_dse/GATE_PASS_$CH.json ]; then
    say "no hard-gate pass for evaluator code $CH -- full evaluation refused"; exit 1; fi
fi
case "$1" in
  smoke) run_job G0 $G0 nominal "--only 0" ;;
  g0rep) run_job G0 $G0 nominal "--only 0,1" ;;
  g0) run_job G0 $G0 nominal; run_job G0 $G0 val18 ;;
  g0nom) run_job G0 $G0 nominal ;;
  g1nom) run_job G1 $G1 nominal ;;
  g2nom) run_job G2 $G2 nominal ;;
  g1) run_job G1 $G1 nominal; run_job G1 $G1 val18 ;;
  g2) run_job G2 $G2 nominal; run_job G2 $G2 val18 ;;
  anom) run_job A $A nominal ;;
  *) echo "usage: $0 smoke|g0rep|g0|g0nom|g1|g2|g1nom|g2nom|anom <subdir>"; exit 2 ;;
esac
say "DSE PHASE $1 COMPLETE"
