"""Data sections of the definitive summary, generated from the artefacts.

    python sim_umi/scripts/definitive/build_tables.py > tables.md

Nothing here is typed in by hand: provenance, checkpoint and LR tables come
from run_provenance.json and the on-disk audits, results from aggregate.py's
JSON, completeness from the evaluation chain's own outputs. A primary job
that is missing or partial is shown as such and contributes nothing.
"""
import json, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
D = ROOT / "sim_umi/train_results/2026-09-27_definitive"
E = ROOT / "sim_umi/eval_results/2026-09-27_definitive"
RUNS = {"clean": ROOT / "sim_umi/train_results/2026-09-27_amp_clean_definitive",
        "v2": ROOT / "sim_umi/train_results/2026-09-27_amp_v2_definitive"}
PRIMARY = [("clean5986", "nominal"), ("v2_5986", "nominal"), ("v2_8000", "nominal"),
           ("v2_10000", "nominal"), ("v2_11400", "nominal"),
           ("clean5986", "val18"), ("v2_5986", "val18"), ("v2_11400", "val18")]
SECONDARY = [("v2_8000", "val18"), ("v2_10000", "val18"),
             ("clean5985", "nominal"), ("v2_5985", "nominal")]
EXPECTED_N = {"nominal": 5, "val18": 18}


def j(p):
    return json.load(open(p))


def completeness(agg):
    out = []
    for kind, jobs in (("primary", PRIMARY), ("secondary", SECONDARY)):
        for label, mode in jobs:
            f = E / f"{mode}_{label}.json"
            key = f"{label}_{mode}"
            if not f.exists():
                out.append((kind, label, mode, "MISSING", 0, EXPECTED_N[mode], 0))
                continue
            d = j(f)
            n_ran = len(d["episodes"])
            n_inf = len(d.get("infra_failed", []))
            R = (agg or {}).get("runs", {}).get(key)
            n_valid = R["n_episodes"] if R else None
            n_bad = len(R.get("invalid_start", [])) if R else None
            if R is None:
                st = "NOT AGGREGATED"
            elif n_valid == EXPECTED_N[mode]:
                st = "complete"
            else:
                st = "PARTIAL"
            out.append((kind, label, mode, st, n_ran, n_valid, n_bad, EXPECTED_N[mode], n_inf))
    return out


def fmt_counts(R, keys):
    n = R["n_episodes"]
    return [f"{R['counts'][k]}/{n}" for k in keys]


def main():
    agg = j(sys.argv[1]) if len(sys.argv) > 1 else None
    P = print
    P("## Provenance\n")
    sw = (D / "preflight/02_software.txt").read_text()
    P("```\n" + sw.strip() + "\n```\n")
    ds = j(D / "preflight/04_dataset.json")["checks"]
    P("| dataset | file | sha256 | segments | frames | sampler N | DataLoader len | batch | drop_last | val_ratio | held-out segs |")
    P("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in ("clean", "combined"):
        c = ds[k]
        P(f"| {k} | {pathlib.Path(c['path']).name} ({c['bytes']/1e6:.1f} MB) | `{c['sha256'][:16]}…` | {c['segments']} | "
          f"{c['raw_frames']} | {c['sampler_len']} | {c['dataloader_len']} | {c['batch_size']} | {c['drop_last']} | "
          f"{c['val_ratio']} | {c['heldout_segments']} |")
    v = ds["v2_train"]
    P(f"| v2_train (combined minus clean prefix) | — | — | {v['segments']} | {v['raw_frames']} | {v['N']} | — | — | — | — | — |\n")
    init = j(D / "shared_init/init_state.json")
    P(f"Shared initial state: `{init['checksum_excluding_normalizer'][:16]}…` (excluding the dataset-fitted normalizer); "
      f"a second seeded construction reproduces it: {init['seed_alone_reproduces']}.\n")
    P("| run | started | finished | init checksum | resumed from | AMP probe | train N | DL len | val_ratio | opt_steps at end | skipped | non-finite |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r, d in RUNS.items():
        rp = j(d / "run_provenance.json")
        P(f"| {r} | {rp['started']} | {rp.get('finished')} | `{rp['init_checksum'][:16]}…` | {rp['resumed_from']} | "
          f"autocast {rp['amp_probe']['autocast_enabled']}, {rp['amp_probe']['denoiser_output_dtype']} | {rp['train_samples']} | "
          f"{rp['dataloader_len']} | {rp['val_ratio']} | {rp.get('opt_steps_at_end')} | {rp.get('skipped_optimizer_steps')} | {rp.get('nonfinite_losses')} |")
    P("\n## Checkpoints (reloaded from disk and audited)\n")
    P("| run | step | opt_steps | EMA updates | scheduler last_epoch | AdamW step histogram | LR group0 | LR group1 | scaler scale | skipped so far | epoch | dataset passes | audit |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    N = {"clean": 6080, "v2": 21532}
    for r, d in RUNS.items():
        for a in sorted((d / "checkpoints").glob("step*.audit.json"), key=lambda p: int(re.search(r"step(\d+)", p.name).group(1))):
            x = j(a)
            P(f"| {r} | {x['expected_opt_steps']} | {x['opt_steps_pickle']} | {x['ema_update_count']} | {x['scheduler_last_epoch']} | "
              f"{x['param_step_histogram']} | {x['optimizer_lr'][0]:.4e} | {x['optimizer_lr'][1]:.4e} | {(x['scaler'] or {}).get('scale'):.0f} | "
              f"{x['skipped_optimizer_steps']} | {x['epoch']} | {x['expected_opt_steps']*64/N[r]:.1f} | {'PASS' if x['pass'] else 'FAIL'} |")
    if agg is None:
        return
    P("\n## Evaluation completeness\n")
    P("| kind | checkpoint | set | status | episodes run | valid starts (counted) | invalid starts (listed, not counted) | expected | infra-failed starts |")
    P("|---|---|---|---|---|---|---|---|---|")
    for row in completeness(agg):
        P("| " + " | ".join(str(x) for x in row) + " |")
    P("\n## Start validity (free-joint ground truth; never given to the policy)\n")
    P("| run | counted | invalid starts | infra retries | ball dev at first sample, mm (median / max) | perturbed starts settled | bodies after place, max dev mm (ball / bin) |")
    P("|---|---|---|---|---|---|---|")
    for lab, X in agg["runs"].items():
        sts = [e["start"] for e in X["episodes"] if e.get("start")]
        dv = sorted(x["ball_start_dev_mm"] for x in sts if x["ball_start_dev_mm"] is not None)
        med = dv[len(dv) // 2] if dv else None
        pert = [x for x in sts if x["perturbed"]]
        bp = [x["bodies_after_place"] for x in sts if x.get("bodies_after_place")]
        bmax = (f"{max(b['object']['dev_mm'] for b in bp):.2f} / {max(b['bin']['dev_mm'] for b in bp):.2f}"
                if bp else "not logged")
        bad = "; ".join(f"ep{x['episode']}: {x['reason']}" for x in X.get("invalid_start", [])) or "none"
        P(f"| {lab} | {X['n_episodes']} | {bad} | {X['infra_retries_total']} | "
          f"{'—' if med is None else f'{med:.2f} / {dv[-1]:.2f}'} | "
          f"{(str(sum(1 for x in pert if x['settled'])) + '/' + str(len(pert))) if pert else '—'} | {bmax} |")
    R = agg["runs"]
    keys = ["grasp_stage_reached", "lift_stage_reached", "runtime_grasped_flag", "object_lifted",
            "strict_gt_secure_grasp", "bin_success", "entered_corridor", "reached_pitch_below_20",
            "consecutive_unreachable_abort"]
    for mode, title in (("nominal", "Nominal 5 placements (HOME start, training placements)"),
                        ("val18", "Perturbation 18 (unseen intermediate cells, perturbed start)")):
        labs = [k for k in R if k.endswith("_" + mode)]
        if not labs:
            continue
        P(f"\n## {title}\n")
        P("| checkpoint | n | GRASP stage | LIFT stage | runtime grasped | ball lifted | strict GT secure | bin | corridor | pitch<20 | unreachable abort | ticks (per ep) | trap dwell s (mean) | prefix<=2 (mean) | infra retries |")
        P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for lab in labs:
            X = R[lab]
            import statistics as st
            pre = [v for v in X["valid_prefix_le2_ratio"] if v is not None]
            P(f"| {lab[:-len(mode)-1]} | {X['n_episodes']} | " + " | ".join(fmt_counts(X, keys)) +
              f" | {X['total_ticks']} | {st.mean(X['trap_dwell_s']):.2f} | {st.mean(pre):.3f} | {X['infra_retries_total']} |")
        P("\nStage ticks (mean per episode):\n")
        stages = ["SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP", "LIFT", "SEARCH_BIN", "TRANSPORT", "PLACE", "AFTER_RELEASE"]
        P("| checkpoint | " + " | ".join(stages) + " |")
        P("|---|" + "---|" * len(stages))
        for lab in labs:
            P(f"| {lab[:-len(mode)-1]} | " + " | ".join(f"{R[lab]['stage_ticks_mean'][s]:.0f}" for s in stages) + " |")
        P("\nClose geometry at the onset of closing of the first real GRASP attempt (N/A = no GRASP attempt):\n")
        P("| checkpoint | n closes | lateral mm | depth mm | vertical mm | pitch deg | EE speed mm/tick |")
        P("|---|---|---|---|---|---|---|")
        P("| expert | 20 | -0.62 [-2.26, +2.20] | -22.62 [-23.66, -15.86] | +4.30 [+0.51, +8.19] | +12.57 [+7.91, +17.40] | ~0.15 |")
        for lab in labs:
            g = R[lab]["close_geometry"]
            def f(k):
                return "N/A" if not g.get(k) else f"{g[k]['mean']:+.2f} (med {g[k]['median']:+.2f}, sd {g[k]['std']:.2f})"
            n_c = g["lateral"]["n"] if g.get("lateral") else 0
            P(f"| {lab[:-len(mode)-1]} | {n_c} | {f('lateral')} | {f('depth')} | {f('vertical')} | {f('pitch')} | {f('ee_speed_mm_per_tick')} |")
        P("\nFeasibility (runtime gate: solve_ik_best in-plane position residual > 2 mm; causes from re-solving each rejected target):\n")
        P("| checkpoint | attempted | rejected | joint limit | pitch unattainable | position unreachable, no limit | IK reproduction | asked pitch acc/rej | orientation residual acc/rej deg |")
        P("|---|---|---|---|---|---|---|---|---|")
        for lab in labs:
            fz = R[lab]["feasibility"]
            c = fz["rejection_causes"]
            def g2(a, b):
                return f"{fz[a]:.1f} / {fz[b]:.1f}" if fz[a] is not None and fz[b] is not None else "—"
            P(f"| {lab[:-len(mode)-1]} | {fz['attempted_waypoints']} | {fz['rejected_waypoints']} | {c.get('joint limit', 0)} | "
              f"{c.get('pitch unattainable at that position', 0)} | {c.get('position unreachable (no limit, pitch met)', 0)} | "
              f"{fz['recomputation_matches_logged_within_0.05mm']} | {g2('asked_pitch_deg_accepted','asked_pitch_deg_rejected')} | "
              f"{g2('orientation_residual_deg_accepted_mean','orientation_residual_deg_rejected_mean')} |")
        P("\nAbort reasons:\n")
        for lab in labs:
            P(f"- {lab}: {R[lab]['abort_reasons']}")


if __name__ == "__main__":
    main()
