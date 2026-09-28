"""Reload a definitive-run checkpoint from disk and cross-check every counter.

    python sim_umi/scripts/definitive/audit_checkpoint.py <ckpt> [--expect-init <sha>] [--out f.json]

A step-N checkpoint is supposed to be the state after exactly N applied
optimizer updates, in all of its parts. This checks that from the file itself,
not from what the training process believed it wrote: the update counter, the
per-parameter AdamW step counts, the scheduler position and the learning rate
it implies, the EMA update count, the gradient scaler, the RNG states, and the
shared initial-state checksum.
"""
import json, math, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import collections, dill, torch
from diffusers.optimization import get_cosine_schedule_with_warmup


def expected_lr(step, base, warmup=2000, total=11400):
    # the schedule the runs use, evaluated by the same library function
    opt = torch.optim.SGD([torch.zeros(1, requires_grad=True)], lr=base)
    sch = get_cosine_schedule_with_warmup(opt, warmup, total, last_epoch=-1)
    return base * sch.lr_lambdas[0](step)


def main():
    path = pathlib.Path(sys.argv[1])
    exp_init = sys.argv[sys.argv.index("--expect-init") + 1] if "--expect-init" in sys.argv else None
    m = re.search(r"step(\d+)", path.name)
    N = int(m.group(1)) if m else None
    d = torch.load(path.open("rb"), pickle_module=dill, map_location="cpu")
    fails, rec = [], {"checkpoint": str(path), "expected_opt_steps": N, "bytes": path.stat().st_size}
    sd, pk, ex = d["state_dicts"], d["pickles"], d.get("extra")
    rec["state_dicts"] = sorted(sd)
    for k in ("model", "ema_model", "optimizer"):
        if k not in sd:
            fails.append(f"missing state_dict: {k}")
    if ex is None:
        fails.append("missing extra (scheduler/scaler/EMA/RNG)")
        ex = {}
    P = {k: dill.loads(v) for k, v in pk.items() if k != "_output_dir"}
    rec["pickles"] = P
    c = ex.get("counters", {})
    ema = ex.get("ema") or {}
    sch = ex.get("lr_scheduler") or {}
    opt = sd.get("optimizer", {})
    hist = collections.Counter(int(v["step"]) for v in opt.get("state", {}).values() if "step" in v)
    lrs = [g["lr"] for g in opt.get("param_groups", [])]
    base = [g.get("initial_lr") for g in opt.get("param_groups", [])]
    rec.update({
        "opt_steps_pickle": P.get("opt_steps"), "opt_steps_extra": c.get("opt_steps"),
        "ema_update_count": ema.get("optimization_step"), "ema_decay": ema.get("decay"),
        "scheduler_last_epoch": sch.get("last_epoch"), "scheduler_step_count": sch.get("_step_count"),
        "scheduler_last_lr": sch.get("_last_lr"), "optimizer_lr": lrs, "optimizer_initial_lr": base,
        "param_step_histogram": {str(k): v for k, v in sorted(hist.items())},
        "scaler": ex.get("scaler"), "skipped_optimizer_steps": c.get("skipped_optimizer_steps"),
        "nonfinite_losses": c.get("nonfinite_losses"), "epoch": c.get("epoch"),
        "global_step": c.get("global_step"), "batch_idx_in_epoch": c.get("batch_idx_in_epoch"),
        "rng_present": sorted((ex.get("rng") or {}).keys()),
        "init_checksum": P.get("init_checksum"),
        # an ablation that adds a module is checked on the parameters it shares with G0
        "shared_init_checksum": (ex.get("provenance") or {}).get("shared_init_checksum"),
        "new_module_prefixes": (ex.get("provenance") or {}).get("new_module_prefixes") or [],
        "mixed_precision": (ex.get("provenance") or {}).get("mixed_precision"),
        "dataset_sha256": ((ex.get("provenance") or {}).get("dataset") or {}).get("sha256"),
        "val_ratio": (ex.get("provenance") or {}).get("val_ratio"),
    })
    if N is not None:
        for key in ("opt_steps_pickle", "opt_steps_extra", "ema_update_count", "scheduler_last_epoch"):
            if rec[key] != N:
                fails.append(f"{key} = {rec[key]}, expected {N}")
        if set(hist) != {N}:
            fails.append(f"optimizer param steps {dict(hist)} != {{{N}: all}}")
        if base and base[0]:
            want = [expected_lr(N, b) for b in base]
            rec["expected_lr"] = want
            for got, w in zip(lrs, want):
                if not math.isclose(got, w, rel_tol=1e-6, abs_tol=1e-12):
                    fails.append(f"optimizer lr {got} != schedule({N}) {w}")
    if rec["mixed_precision"] == "fp16":
        sc = rec["scaler"] or {}
        if not sc or not math.isfinite(float(sc.get("scale", float("nan")))) or float(sc.get("scale", 0)) <= 0:
            fails.append(f"fp16 run without a valid scaler state: {sc}")
    if rec["nonfinite_losses"]:
        fails.append(f"nonfinite_losses = {rec['nonfinite_losses']}")
    if exp_init:
        key = "shared_init_checksum" if rec["new_module_prefixes"] else "init_checksum"
        if rec[key] != exp_init:
            fails.append(f"{key} {rec[key]} != expected {exp_init}")
    for need in ("python", "numpy", "torch_cpu", "torch_cuda"):
        if need not in rec["rng_present"]:
            fails.append(f"rng state missing: {need}")
    rec["fail"], rec["pass"] = fails, not fails
    print(f"{path.name}: {'PASS' if not fails else 'FAIL'}  opt_steps {rec['opt_steps_pickle']}  "
          f"ema {rec['ema_update_count']}  sched {rec['scheduler_last_epoch']}  hist {rec['param_step_histogram']}  "
          f"lr {['%.4e' % x for x in lrs]}  scale {(rec['scaler'] or {}).get('scale')}  "
          f"skipped {rec['skipped_optimizer_steps']}  {fails if fails else ''}")
    if "--out" in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index("--out") + 1]).write_text(json.dumps(rec, indent=1, default=str))
    sys.exit(0 if not fails else 4)


if __name__ == "__main__":
    main()
