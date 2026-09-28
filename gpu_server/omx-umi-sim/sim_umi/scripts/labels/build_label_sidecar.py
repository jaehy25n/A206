"""Metadata sidecar: row mapping, expert stages, 5-phase labels, grasp/release
timing -- for the v2 training and validation zarrs. The zarrs are not touched.

    python sim_umi/scripts/labels/build_label_sidecar.py            # train, val, val_clean
    python sim_umi/scripts/labels/build_label_sidecar.py --dry      # compute + check only

Writes, never overwriting:
    sim_umi/data/sidecars/<zarr stem>.labels.npz    arrays (row / episode / demo / sample tables)
    sim_umi/data/sidecars/<zarr stem>.labels.json   rules, checks, statistics

TRAIN-ONLY SUPERVISION. Everything here comes from the simulator's ground truth
and the scripted expert; none of it is, or may become, a policy input.

1. Mapping (read from the code, not assumed)
   demos_to_umi_zarr.py builds a zarr from one or more demo folders in sorted
   file order and CUTS every demo wherever two consecutive frames are more than
   MAX_STEP_S = 0.105 s apart (a frame that never arrived); every piece of at
   least MIN_SEGMENT = 17 frames becomes its own zarr episode, shorter pieces
   are dropped. Which folders went into which zarr is established by
   reproduction, not by name: omx_sim_train_v2 = demos/train + demos/v2_train,
   omx_sim_val_v2 = demos/v2_val ONLY, omx_sim_val (the clean-era validation
   zarr) = demos/val -- for each, the rebuilt cut reproduces meta/episode_ends
   and every row's gripper width, EE position and EE rotation bit for bit, and
   the build stops otherwise. Together the three cover all 91 source demos.
   Training samples: UmiDataset/SequenceSampler as the definitive G0 run was
   configured (its saved hydra config, val_ratio 0.0): one sample per row whose
   16-step action window fits inside its episode, obs rows {r-1, r} (the first
   row repeated at an episode start), action rows r..r+15. The sampler is
   instantiated from that config and its own index list is stored.

2. Events, once per SOURCE DEMO on the whole recording, from the width trace of
   the true jaw (eval_gripper_width_gt, sampled at the image instant) -- the rule
   of the earlier 91-demo analysis (FOV journal 23:05), reused unchanged:
     open_w  = median of the first 10 frames; hold_w = median over the expert's
               LIFT..PLACE-start stretch; mid = (open_w + hold_w) / 2
     close_start   first frame below open_w - 1 mm
     close_cross   first frame below mid
     open_cross    first frame after close_cross back above mid
     open_start    open_cross walked back along the monotonic rise (step > 0.1 mm)
                   to the frame where the opening began -- a refinement of a
                   detected crossing, not a detector: a threshold on the width
                   itself fires while carrying (the held width creeps ~0.5 mm)
   Hysteresis check: with levels lo = hold_w + (open_w-hold_w)/4 and
   hi = open_w - (open_w-hold_w)/4 the trace must make exactly one open->closed
   and one closed->open transition (no regrasp).
     object_lifted the lift-off frame of the lifted stretch that passes the
                   evaluator's strict secure-grasp test (definitive/aggregate.py:
                   ball z > r + HOLD_RISE_MM, rigid in the tool frame within
                   SECURE_STEADY_MM for >= SECURE_MIN_S while the tool travels
                   >= SECURE_MOVE_MM; constants imported from there)
     retreat_start first frame the expert labelled RETREAT
   The same close/open rule on the camera-estimated width is kept as *_cam.

3. Per row
   phase_5: 0 APPROACH [start, close_start) 1 GRASP_LIFT [close_start, object_lifted)
            2 TRANSPORT [object_lifted, open_start) 3 RELEASE [open_start, retreat_start)
            4 RETREAT_POST [retreat_start, end)
   expert_stage_10: the expert's own label, unchanged
   dt_to_<e>_s    t[event] - t[row] on the demo's image timeline, signed, unclipped
   frames_to_<e>  event frame - row frame (demo frames = zarr rows = action steps
                  inside an episode; downsample 1), signed
   <e>_is_future  frames_to_<e> > 0 (the event row itself is not future)
   <e>_within_horizon16  0 <= frames_to_<e> <= 15 AND the event row is in this
                  row's zarr episode, i.e. inside the row's 16-step action window
"""
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(ROOT), str(SIM / "scripts"), str(SIM / "scripts" / "definitive"), str(SIM / "src")]

import click
import numpy as np
import zarr

from demos_to_umi_zarr import MAX_STEP_S, MIN_SEGMENT  # noqa: E402
from aggregate import HOLD_RISE_MM, SECURE_MIN_S, SECURE_MOVE_MM, SECURE_STEADY_MM  # noqa: E402

OUT_DIR = SIM / "data" / "sidecars"
G0_RUN = SIM / "train_results" / "2026-09-27_amp_v2_definitive"
SPLITS = {
    "train": (SIM / "data/omx_sim_train_v2.zarr.zip", ("train", "v2_train")),
    "val": (SIM / "data/omx_sim_val_v2.zarr.zip", ("v2_val",)),
    "val_clean": (SIM / "data/omx_sim_val.zarr.zip", ("val",)),
}
PHASES = ("APPROACH", "GRASP_LIFT", "TRANSPORT", "RELEASE", "RETREAT_POST")
EXPERT_STAGES = ("HOME", "SEARCH_OBJECT", "APPROACH_OBJECT", "GRASP", "LIFT",
                 "SEARCH_BIN", "TRANSPORT", "PLACE", "RETREAT", "SETTLE")
EVENTS = ("close", "lift", "open", "retreat")
HORIZON = 16
CLOSE_DROP = 0.001
OPEN_WALK_STEP = 1e-4
OPEN_REF_FRAMES = 10


def width_events(w, lift0, place0):
    n = len(w)
    open_w = float(np.median(w[:OPEN_REF_FRAMES]))
    hold_w = float(np.median(w[lift0:place0]))
    mid = 0.5 * (open_w + hold_w)
    close = next((i for i in range(n) if w[i] < open_w - CLOSE_DROP), None)
    below = next((i for i in range(n) if w[i] < mid), None)
    rel = next((i for i in range(below or n, n) if w[i] > mid), None)
    open_start = None
    if rel is not None:
        k = rel
        while k > 0 and w[k - 1] < w[k] - OPEN_WALK_STEP:
            k -= 1
        open_start = k
    # hysteresis transition count
    band = 0.25 * (open_w - hold_w)
    lo, hi = hold_w + band, open_w - band
    state, downs, ups = "open", 0, 0
    for x in w:
        if state == "open" and x < lo:
            state, downs = "closed", downs + 1
        elif state == "closed" and x > hi:
            state, ups = "open", ups + 1
    return {"close": close, "close_cross": below, "open_cross": rel, "open": open_start,
            "open_w": open_w, "hold_w": hold_w, "mid": mid, "down_transitions": downs,
            "up_transitions": ups}


def secure_liftoff(t, ball, ee, R, r):
    """definitive/aggregate.py's strict secure-grasp test, per lifted stretch;
    returns the lift-off frame of the best stretch and its numbers."""
    ok = np.all(np.isfinite(ball), 1)
    offs = np.full((len(t), 3), np.nan)
    for i in np.flatnonzero(ok):
        offs[i] = R[i].T @ (ball[i] - ee[i]) * 1000.0
    lifted = ok & (ball[:, 2] * 1000.0 > r * 1000.0 + HOLD_RISE_MM)
    idx = np.flatnonzero(lifted)
    if len(idx) < 3:
        return None, {"lifted_stretches": 0}
    stretches, i0 = [], idx[0]
    while i0 < len(lifted):
        if lifted[i0]:
            j0 = i0
            while j0 + 1 < len(lifted) and lifted[j0 + 1]:
                j0 += 1
            stretches.append(np.arange(i0, j0 + 1))
            i0 = j0 + 1
        else:
            i0 += 1
    best = None
    for seg in stretches:
        O = offs[seg]
        n_ = np.arange(1, len(seg) + 1)[:, None]
        mean = np.cumsum(O, 0) / n_
        hi_ = np.maximum.accumulate(O, 0)
        lo_ = np.minimum.accumulate(O, 0)
        dev_k = np.maximum(hi_ - mean, mean - lo_).max(1)
        bad = np.where(dev_k >= SECURE_STEADY_MM)[0]
        k_end = (bad[0] - 1) if len(bad) else len(seg) - 1
        if k_end >= 1:
            rig = seg[:k_end + 1]
            cand = (float(t[rig[-1]] - t[rig[0]]), float(dev_k[k_end]),
                    float(np.linalg.norm(ee[rig[-1]] - ee[rig[0]]) * 1000.0))
        else:
            cand = (0.0, float(dev_k[0]), 0.0)
        ok_c = cand[0] >= SECURE_MIN_S and cand[1] < SECURE_STEADY_MM and cand[2] >= SECURE_MOVE_MM
        key = (ok_c, cand[2], cand[0])
        if best is None or key > best[0]:
            best = (key, cand, int(seg[0]))
    (secure, _, _), (held_t, dev, moved), start = best
    return (start if secure else None), {
        "lifted_stretches": len(stretches), "first_lifted_frame": int(idx[0]),
        "secure": bool(secure), "held_seconds": round(held_t, 3),
        "toolframe_deviation_mm": round(dev, 3), "ee_travel_mm": round(moved, 1)}


def demo_events(p):
    d = np.load(p, allow_pickle=True)
    t = d["t"].astype(np.float64)
    stage = d["stage"].astype(str)
    n = len(t)
    spec = json.loads(str(d["spec"]))
    first = {s: int(np.flatnonzero(stage == s)[0]) for s in EXPERT_STAGES if (stage == s).any()}
    problems = []
    unknown = sorted(set(stage) - set(EXPERT_STAGES))
    if unknown:
        problems.append(f"unknown expert stages {unknown}")
    if len(first) != len(EXPERT_STAGES):
        problems.append(f"expert stages missing: {sorted(set(EXPERT_STAGES) - set(first))}")
        return {"path": p, "problems": problems}
    codes = np.array([EXPERT_STAGES.index(s) for s in stage])
    if np.any(np.diff(codes) < 0):
        problems.append("expert stage order not monotone")
    w_gt = d["eval_gripper_width_gt"].astype(np.float64).reshape(-1)
    w_cam = d["gripper_width"].astype(np.float64).reshape(-1)
    gt = width_events(w_gt, first["LIFT"], first["PLACE"])
    cam = width_events(w_cam, first["LIFT"], first["PLACE"])
    lift, sec = secure_liftoff(t, d["eval_ball_pos"].astype(np.float64), d["eef_pos"].astype(np.float64),
                               d["eef_rot"].astype(np.float64), spec["ball_r"])
    ev = {"close": gt["close"], "lift": lift, "open": gt["open"], "retreat": first["RETREAT"]}
    for k, v in ev.items():
        if v is None:
            problems.append(f"{k} not found")
    if gt["down_transitions"] != 1 or gt["up_transitions"] != 1:
        problems.append(f"transitions down {gt['down_transitions']} up {gt['up_transitions']}")
    if not problems and not (0 < ev["close"] < ev["lift"] < ev["open"] < ev["retreat"] < n):
        problems.append(f"event order broken {ev} n={n}")
    return {"path": p, "n": n, "t": t, "codes": codes, "events": ev, "gt": gt, "cam": cam,
            "secure": sec, "stage_first": first, "problems": problems,
            "w_cam": w_cam, "eef_pos": d["eef_pos"], "eef_rot": d["eef_rot"]}


def segments(sources):
    """demos_to_umi_zarr's cut, in its order (identical to build_geometry_zarr.segments)."""
    out, g = [], 0
    for dname in sources:
        for p in sorted((SIM / "data/demos" / dname).glob("episode_*.npz")):
            t = np.load(p, allow_pickle=True)["t"]
            n = len(t)
            cuts = [0] + list(np.flatnonzero(np.diff(t) > MAX_STEP_S) + 1) + [n]
            for a, b in zip(cuts[:-1], cuts[1:]):
                if b - a >= MIN_SEGMENT:
                    out.append((g, str(p), dname, a, b))
                    g += b - a
    return out


def sampler_indices(zpath):
    """The training sampler's own index list, from the definitive G0 run's saved config."""
    from omegaconf import OmegaConf
    import hydra
    OmegaConf.register_new_resolver("eval", eval, replace=True)
    cfg = OmegaConf.load(G0_RUN / ".hydra" / "config.yaml")
    cfg.task.dataset.dataset_path = str(zpath)
    ds = hydra.utils.instantiate(cfg.task.dataset)
    ind = np.array([(c, s, e) for c, s, e, _ in ds.sampler.indices], dtype=np.int64)
    info = {"config": str((G0_RUN / ".hydra" / "config.yaml").relative_to(ROOT)),
            "val_ratio": float(cfg.task.dataset.val_ratio), "action_padding": bool(cfg.task.dataset.action_padding),
            "action_horizon": int(ds.key_horizon["action"]),
            "action_down_sample_steps": int(ds.key_down_sample_steps["action"]),
            "rgb_obs_horizon": int(ds.key_horizon["camera0_rgb"]),
            "lowdim_latency_steps": {k: float(v) for k, v in ds.key_latency_steps.items()},
            "n_samples": int(len(ind)), "n_val_episodes_inside_loader": int(ds.val_mask.sum())}
    return ind, info


def build(split, dry):
    zpath, sources = SPLITS[split]
    stem = zpath.name.replace(".zarr.zip", "")
    out_npz, out_json = OUT_DIR / f"{stem}.labels.npz", OUT_DIR / f"{stem}.labels.json"
    if not dry and (out_npz.exists() or out_json.exists()):
        raise click.ClickException(f"{out_npz.name} exists -- not overwriting")

    store = zarr.ZipStore(str(zpath), mode="r")
    root = zarr.group(store)
    ends = root["meta/episode_ends"][:]
    z_grip = root["data/robot0_gripper_width"][:].reshape(-1)
    z_pos = root["data/robot0_eef_pos"][:]
    z_rot = root["data/robot0_eef_rot_axis_angle"][:]
    store.close()
    N, E = int(ends[-1]), len(ends)

    segs = segments(sources)
    checks = {"episode_ends_reproduced": bool(len(segs) == E and np.array_equal(
        np.cumsum([b - a for *_, a, b in segs]), ends))}
    if not checks["episode_ends_reproduced"]:
        raise click.ClickException(f"{split}: the cut does not reproduce episode_ends")

    all_demos = [str(p) for dname in sources for p in sorted((SIM / "data/demos" / dname).glob("episode_*.npz"))]
    demos = {p: demo_events(p) for p in all_demos}
    bad = {pathlib.Path(p).relative_to(ROOT).as_posix(): e["problems"] for p, e in demos.items() if e["problems"]}
    if bad:
        raise click.ClickException(f"{split}: event problems {bad}")
    D = len(all_demos)
    did = {p: i for i, p in enumerate(all_demos)}

    from scipy.spatial.transform import Rotation
    row = {k: np.empty(N, dt) for k, dt in (
        ("zarr_row_idx", np.int32), ("zarr_episode_idx", np.int16), ("source_split", np.int8),
        ("source_demo_id", np.int16), ("source_frame_idx", np.int32), ("timestamp_s", np.float64),
        ("expert_stage_10", np.int8), ("phase_5", np.int8))}
    for e in EVENTS:
        row[f"dt_to_{e}_s"] = np.empty(N, np.float32)
        row[f"frames_to_{e}"] = np.empty(N, np.int32)
    for e in ("close", "lift", "open"):
        row[f"{e}_is_future"] = np.empty(N, bool)
        row[f"{e}_within_horizon16"] = np.empty(N, bool)
    for e in ("close", "open"):
        row[f"dt_to_{e}_cam_s"] = np.empty(N, np.float32)
    epi = {k: np.full(E, -1, np.int32) for k in (
        "source_demo_id", "source_frame_start", "source_frame_end", "zarr_row_start", "zarr_row_end",
        *[f"{e}_zarr_row" for e in EVENTS])}
    exact = {"gripper_width": True, "eef_pos": True, "eef_rot_axis_angle": True}
    for i, (g, p, dname, a, b) in enumerate(segs):
        e = demos[p]
        ev, t = e["events"], e["t"]
        k = np.arange(a, b)
        sl = slice(g, g + (b - a))
        row["zarr_row_idx"][sl] = np.arange(g, g + (b - a))
        row["zarr_episode_idx"][sl] = i
        row["source_split"][sl] = sources.index(dname)
        row["source_demo_id"][sl] = did[p]
        row["source_frame_idx"][sl] = k
        row["timestamp_s"][sl] = t[a:b]
        row["expert_stage_10"][sl] = e["codes"][a:b]
        row["phase_5"][sl] = np.searchsorted([ev["close"], ev["lift"], ev["open"], ev["retreat"]], k, side="right")
        for name in EVENTS:
            row[f"dt_to_{name}_s"][sl] = t[ev[name]] - t[a:b]
            row[f"frames_to_{name}"][sl] = ev[name] - k
        for name in ("close", "lift", "open"):
            f2 = ev[name] - k
            row[f"{name}_is_future"][sl] = f2 > 0
            row[f"{name}_within_horizon16"][sl] = (f2 >= 0) & (f2 <= HORIZON - 1) & (a <= ev[name] < b)
        for name in ("close", "open"):
            row[f"dt_to_{name}_cam_s"][sl] = t[e["cam"][name]] - t[a:b]
        epi["source_demo_id"][i], epi["source_frame_start"][i], epi["source_frame_end"][i] = did[p], a, b
        epi["zarr_row_start"][i], epi["zarr_row_end"][i] = g, g + (b - a)
        for name in EVENTS:
            epi[f"{name}_zarr_row"][i] = g + ev[name] - a if a <= ev[name] < b else -1
        exact["gripper_width"] &= bool(np.array_equal(z_grip[sl], e["w_cam"][a:b].astype(np.float32)))
        exact["eef_pos"] &= bool(np.array_equal(z_pos[sl], e["eef_pos"][a:b].astype(np.float32)))
        rv = Rotation.from_matrix(e["eef_rot"][a:b]).as_rotvec().astype(np.float32)
        exact["eef_rot_axis_angle"] &= bool(np.array_equal(z_rot[sl], rv))
    for k_, v in exact.items():
        checks[f"zarr_{k_}_equals_source_row_bitwise"] = v
    pairs = row["source_demo_id"].astype(np.int64) * 100000 + row["source_frame_idx"]
    checks["source_frame_unique_per_row"] = bool(len(np.unique(pairs)) == N)
    checks["row_count"] = N
    starts = np.r_[0, ends[:-1]]
    checks["episode_idx_matches_episode_ends"] = bool(np.array_equal(
        np.searchsorted(ends, np.arange(N), side="right"), row["zarr_episode_idx"]))
    within = [np.diff(row["timestamp_s"][s:e_]) for s, e_ in zip(starts, ends)]
    checks["timestamps_increase_within_episodes"] = bool(all(np.all(x > 0) for x in within))
    checks["max_step_within_episodes_s"] = round(float(max(x.max() for x in within)), 4)
    checks["frames_contiguous_within_episodes"] = bool(all(
        np.all(np.diff(row["source_frame_idx"][s:e_]) == 1) for s, e_ in zip(starts, ends)))
    checks["phase_monotone_within_episodes"] = bool(all(
        np.all(np.diff(row["phase_5"][s:e_]) >= 0) for s, e_ in zip(starts, ends)))
    checks["expert_stage_monotone_within_episodes"] = bool(all(
        np.all(np.diff(row["expert_stage_10"][s:e_]) >= 0) for s, e_ in zip(starts, ends)))
    for name in EVENTS:
        rr = epi[f"{name}_zarr_row"]
        checks[f"{name}_rows_have_zero_delta"] = bool(all(
            row[f"frames_to_{name}"][r] == 0 and row[f"dt_to_{name}_s"][r] == 0 for r in rr if r >= 0))
    covered = {pathlib.Path(p).relative_to(ROOT).as_posix() for _, p, *_ in segs}
    dropped_rows = sum(demos[p]["n"] for p in all_demos) - N

    sidx, sinfo = sampler_indices(zpath)
    checks["sampler_rows_inside_episodes"] = bool(np.all(
        (sidx[:, 0] >= sidx[:, 1]) & (sidx[:, 0] + HORIZON - 1 < sidx[:, 2])))
    checks["sampler_count_equals_rows_minus_15_per_episode"] = bool(len(sidx) == N - (HORIZON - 1) * E)
    is_sample = np.zeros(N, bool)
    is_sample[sidx[:, 0]] = True
    row["is_sample_current"] = is_sample
    obs_rows = np.stack([np.maximum(sidx[:, 0] - 1, sidx[:, 1]), sidx[:, 0]], 1).astype(np.int32)

    if not all(v for k_, v in checks.items() if isinstance(v, bool)):
        raise click.ClickException(f"{split}: checks failed {checks}")

    # ---------------------------------------------------------------- stats
    def ints(v):
        v = np.asarray(v)
        vals, cnt = np.unique(v, return_counts=True)
        return {"min": int(v.min()), "median": float(np.median(v)), "max": int(v.max()),
                "hist": {int(a_): int(c_) for a_, c_ in zip(vals, cnt)}}

    def secs(v):
        v = np.asarray(v, float)
        return {"mean": round(float(v.mean()), 3), "median": round(float(np.median(v)), 3),
                "min": round(float(v.min()), 3), "max": round(float(v.max()), 3)}
    L = list(demos.values())
    offsets = {
        "close_start - GRASP start (frames)": ints([e["events"]["close"] - e["stage_first"]["GRASP"] for e in L]),
        "object_lifted - GRASP start (frames)": ints([e["events"]["lift"] - e["stage_first"]["GRASP"] for e in L]),
        "object_lifted - close_start (frames)": ints([e["events"]["lift"] - e["events"]["close"] for e in L]),
        "open_start - PLACE start (frames)": ints([e["events"]["open"] - e["stage_first"]["PLACE"] for e in L]),
        "open_start - RETREAT start (frames)": ints([e["events"]["open"] - e["stage_first"]["RETREAT"] for e in L]),
        "open_start - object_lifted (frames)": ints([e["events"]["open"] - e["events"]["lift"] for e in L]),
        "object_lifted - first lifted frame (frames)": ints([e["events"]["lift"] - e["secure"]["first_lifted_frame"] for e in L]),
        "close_start camera - GT (frames)": ints([e["cam"]["close"] - e["events"]["close"] for e in L]),
        "open_start camera - GT (frames)": ints([e["cam"]["open"] - e["events"]["open"] for e in L]),
    }
    durations = {
        "close_start -> object_lifted (s)": secs([e["t"][e["events"]["lift"]] - e["t"][e["events"]["close"]] for e in L]),
        "object_lifted -> open_start (s)": secs([e["t"][e["events"]["open"]] - e["t"][e["events"]["lift"]] for e in L]),
        "open_start -> retreat_start (s)": secs([e["t"][e["events"]["retreat"]] - e["t"][e["events"]["open"]] for e in L]),
    }
    phase_rows = {PHASES[i]: int((row["phase_5"] == i).sum()) for i in range(5)}
    phase_samples = {PHASES[i]: int((row["phase_5"][is_sample] == i).sum()) for i in range(5)}
    S = is_sample
    hz = {e: {"rows": round(float(row[f"{e}_within_horizon16"].mean()), 4),
              "training_samples": round(float(row[f"{e}_within_horizon16"][S].mean()), 4),
              "training_samples_count": int(row[f"{e}_within_horizon16"][S].sum())}
          for e in ("close", "lift", "open")}
    ttd = {}
    for e in ("close", "lift", "open"):
        v = row[f"dt_to_{e}_s"][S]
        fut = v[row[f"{e}_is_future"][S]]
        ttd[e] = {"future_fraction": round(float(row[f"{e}_is_future"][S].mean()), 4),
                  "future_dt_s_percentiles_5_25_50_75_95": [round(float(x), 2) for x in np.percentile(fut, [5, 25, 50, 75, 95])],
                  "all_dt_s_min_max": [round(float(v.min()), 2), round(float(v.max()), 2)]}
    event_count = {e: sum(1 for x in L if x["events"][e] is not None) for e in EVENTS}
    stage_x_phase = {EXPERT_STAGES[s]: {PHASES[p_]: int(((row["expert_stage_10"] == s) & (row["phase_5"] == p_)).sum())
                                        for p_ in range(5) if ((row["expert_stage_10"] == s) & (row["phase_5"] == p_)).any()}
                     for s in range(10)}

    arrays = {f"row_{k_}": v for k_, v in row.items()}
    arrays.update({f"episode_{k_}": v for k_, v in epi.items()})
    arrays["sample_current_row"] = sidx[:, 0].astype(np.int32)
    arrays["sample_episode_start_row"] = sidx[:, 1].astype(np.int32)
    arrays["sample_episode_end_row"] = sidx[:, 2].astype(np.int32)
    arrays["sample_obs_rows"] = obs_rows
    arrays["demo_path"] = np.array([pathlib.Path(p).relative_to(ROOT).as_posix() for p in all_demos])
    arrays["demo_split"] = np.array([pathlib.Path(p).parent.name for p in all_demos])
    arrays["demo_n_frames"] = np.array([demos[p]["n"] for p in all_demos], np.int32)
    arrays["demo_in_zarr"] = np.array([pathlib.Path(p).relative_to(ROOT).as_posix() in covered for p in all_demos])
    for e in EVENTS:
        arrays[f"demo_{e}_start_idx"] = np.array([demos[p]["events"][e] for p in all_demos], np.int32)
    for e in ("close_cross", "open_cross"):
        arrays[f"demo_{e}_idx"] = np.array([demos[p]["gt"][e] for p in all_demos], np.int32)
    for e in ("close", "open"):
        arrays[f"demo_{e}_start_idx_cam"] = np.array([demos[p]["cam"][e] for p in all_demos], np.int32)
    arrays["demo_first_lifted_idx"] = np.array([demos[p]["secure"]["first_lifted_frame"] for p in all_demos], np.int32)
    for s in EXPERT_STAGES:
        arrays[f"demo_stage_start_{s}"] = np.array([demos[p]["stage_first"][s] for p in all_demos], np.int32)
    arrays["demo_open_w_m"] = np.array([demos[p]["gt"]["open_w"] for p in all_demos])
    arrays["demo_hold_w_m"] = np.array([demos[p]["gt"]["hold_w"] for p in all_demos])
    arrays["source_split_names"] = np.array(sources)
    arrays["phase_5_names"] = np.array(PHASES)
    arrays["expert_stage_10_names"] = np.array(EXPERT_STAGES)

    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    meta = {
        "what": "TRAIN-ONLY supervision metadata (simulator GT + scripted expert); never a policy input",
        "zarr": str(zpath.relative_to(ROOT)),
        "zarr_sha1_episode_ends_gripper": hashlib.sha1(ends.tobytes() + z_grip.tobytes()).hexdigest(),
        "sources": list(sources), "source_demos": D, "source_demos_in_zarr": len(covered),
        "zarr_episodes": E, "zarr_rows": N, "source_frames_dropped_short_pieces": int(dropped_rows),
        "demos_cut_into_pieces": int(sum(1 for p in all_demos if sum(1 for s in segs if s[1] == p) > 1)),
        "code": str(pathlib.Path(__file__).relative_to(ROOT)), "git": git,
        "sampler": sinfo, "checks": checks,
        "event_detection_count": {k_: f"{v}/{D}" for k_, v in event_count.items()},
        "event_offsets": offsets, "durations": durations,
        "secure_lift_all_demos": all(e["secure"]["secure"] for e in L),
        "rows_per_phase": phase_rows, "training_samples_per_phase": phase_samples,
        "phase_fraction_training_samples": {k_: round(v / int(S.sum()), 4) for k_, v in phase_samples.items()},
        "expert_stage_x_phase_rows": stage_x_phase,
        "horizon16_event_coverage": hz, "time_to_event_training_samples": ttd,
        "widths_mm": {"open_w": [round(float(arrays["demo_open_w_m"].min()) * 1000, 2), round(float(arrays["demo_open_w_m"].max()) * 1000, 2)],
                      "hold_w": [round(float(arrays["demo_hold_w_m"].min()) * 1000, 2), round(float(arrays["demo_hold_w_m"].max()) * 1000, 2)]},
        "arrays": {k_: [str(v.dtype), list(v.shape)] for k_, v in arrays.items()},
    }
    if not dry:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out_npz, **arrays)
        out_json.write_text(json.dumps(meta, indent=1))
        meta["npz_sha256"] = hashlib.sha256(out_npz.read_bytes()).hexdigest()
        out_json.write_text(json.dumps(meta, indent=1))
    return out_npz, meta


@click.command()
@click.option("--split", type=click.Choice(["train", "val", "val_clean", "all"]), default="all")
@click.option("--dry", is_flag=True, help="compute and check, write nothing")
def main(split, dry):
    for s in (list(SPLITS) if split == "all" else [split]):
        out, meta = build(s, dry)
        print(f"== {s}: {meta['source_demos']} demos -> {meta['zarr_episodes']} episodes, {meta['zarr_rows']} rows, "
              f"{meta['sampler']['n_samples']} samples -> {'(dry)' if dry else out.relative_to(ROOT)}")
        print(json.dumps({k: meta[k] for k in ("checks", "event_detection_count", "event_offsets", "durations",
                                                "phase_fraction_training_samples", "horizon16_event_coverage",
                                                "source_frames_dropped_short_pieces", "demos_cut_into_pieces",
                                                "secure_lift_all_demos", "widths_mm")}, indent=None)[:6000])


if __name__ == "__main__":
    main()
