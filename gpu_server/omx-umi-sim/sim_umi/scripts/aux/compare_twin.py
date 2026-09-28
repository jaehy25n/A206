"""Twin-gate verdict: G0 vs A, G0 vs B.

    python sim_umi/scripts/aux/compare_twin.py <twin dir> --out <json>

PASS requires, for every recorded step: identical sample indices, crop draws,
jitter draws, UNet timesteps, noisy-trajectory hash (-> identical diffusion noise
and input-perturbation noise), global CPU and CUDA RNG state at the step start;
at step 0: identical shared-init hash, identical L_diff bits, identical global
condition (max abs diff 0) and, for B, CLS' == CLS; every run finished without
a hard fail / non-finite loss / OOM.
"""
import json
import pathlib
import sys

import click
import torch


def load(d):
    d = pathlib.Path(d)
    rows = json.loads((d / "probe" / "twin_probe.json").read_text())
    prov = json.loads((d / "run_provenance.json").read_text())
    gc = torch.load(d / "probe" / "global_cond_step0.pt")
    return rows, prov, gc


@click.command()
@click.argument("twin_dir")
@click.option("--out", required=True)
def main(twin_dir, out):
    T = pathlib.Path(twin_dir)
    res, fails = {}, []
    runs = {k: load(T / k) for k in ("g0", "a", "b")}
    for k in ("g0", "a", "b"):
        log = (T / f"{k}.log").read_text(errors="replace")
        bad = [s for s in ("HARD FAIL", "out of memory", "CUDA error", "Traceback", "non-finite") if s in log]
        hard = (T / k / "HARD_FAIL.txt").exists()
        res[f"{k}_run_clean"] = {"ok": not bad and not hard, "problems": bad, "steps": len(runs[k][0]),
                                 "opt_steps": runs[k][0][-1]["opt_steps"],
                                 "skipped": sum(r["skipped"] for r in runs[k][0]),
                                 "shared_init_checksum": runs[k][1].get("shared_init_checksum"),
                                 "optimizer_groups": runs[k][1].get("optimizer_groups")}
    g0 = runs["g0"]
    for k in ("a", "b"):
        rows, prov, gc = runs[k]
        n = min(len(rows), len(g0[0]))
        per = {f: [] for f in ("sample_idx", "crop", "jitter", "rng_cpu_sha", "rng_cuda_sha", "timesteps", "noisy_sha")}
        for i in range(n):
            x, y = g0[0][i], rows[i]
            for f in ("sample_idx", "crop", "jitter", "rng_cpu_sha", "rng_cuda_sha"):
                per[f].append(x[f] == y[f])
            per["timesteps"].append([c["timesteps"] for c in x["unet_calls"]] == [c["timesteps"] for c in y["unet_calls"]])
            per["noisy_sha"].append([c["noisy_sha"] for c in x["unet_calls"]] == [c["noisy_sha"] for c in y["unet_calls"]])
        for f, v in per.items():
            res[f"{k}_{f}_equal_all_steps"] = {"ok": all(v) and n == 20, "steps": n, "first_mismatch": (v.index(False) if not all(v) else None)}
        res[f"{k}_shared_init_hash_equal"] = {"ok": prov.get("shared_init_checksum") == g0[1].get("shared_init_checksum")
                                             and prov.get("shared_init_checksum") is not None,
                                             "g0": g0[1].get("shared_init_checksum"), k: prov.get("shared_init_checksum")}
        res[f"{k}_step0_loss_diff_bits_equal"] = {"ok": rows[0]["loss_diff_bits"] == g0[0][0]["loss_diff_bits"],
                                                 "g0": g0[0][0]["loss_diff"], k: rows[0]["loss_diff"]}
        res[f"{k}_step0_global_cond_equal"] = {"ok": bool(torch.equal(gc, g0[2])), "max_abs_diff": float((gc - g0[2]).abs().max())}
        res[f"{k}_step0_global_cond_sha_equal"] = {"ok": rows[0]["unet_calls"][0]["global_cond_sha"] == g0[0][0]["unet_calls"][0]["global_cond_sha"]}
        res[f"{k}_later_loss_diff_differs_after_update(expected)"] = {
            "ok": True, "step1": [g0[0][1]["loss_diff"], rows[1]["loss_diff"]], "step19": [g0[0][19]["loss_diff"], rows[19]["loss_diff"]]}
    film = runs["b"][0][0].get("film") or []
    res["b_step0_cls_mod_equals_cls"] = {"ok": bool(film) and all(f["max_abs_cls_mod_minus_cls"] == 0.0 for f in film),
                                        "film_calls": film}
    film_later = [f for r in runs["b"][0][1:] for f in (r.get("film") or [])]
    res["b_film_moves_after_updates(info)"] = {"ok": True, "max_abs_cls_mod_minus_cls_by_step": [
        max((f["max_abs_cls_mod_minus_cls"] for f in (r.get("film") or [])), default=None) for r in runs["b"][0]]}
    for k, v in res.items():
        if not v["ok"]:
            fails.append(k)
    verdict = {"verdict": "PASS" if not fails else "FAIL", "fails": fails, "checks": res}
    pathlib.Path(out).write_text(json.dumps(verdict, indent=1, default=str))
    for k, v in res.items():
        print(("PASS " if v["ok"] else "FAIL ") + k, json.dumps({x: y for x, y in v.items() if x != "ok"}, default=str)[:260])
    print("VERDICT", verdict["verdict"], fails)
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
