"""Run the same rollout three times and find the first thing that differs.

    python sim_umi/ros/audit_determinism.py --repeats 3 --max-ticks 60

Two rollouts of the same checkpoint on the same placement gave different
answers, and until that is understood no comparison between checkpoints means
much. There are two quite different explanations and this separates them.

If the policy's input is identical and its raw output is not, the inference is
not deterministic. If the raw output is identical too and the arm still ends up
somewhere else, then the difference is downstream -- the projection, the IK
seed, the controller or the simulator.

So every replan records both sides: a hash of the exact observation sent over
the socket, a hash of the exact array that came back, and then what was made of
it -- the projected joints, what the IK reported, the first action executed and
the joint angles it actually reached. The runs are compared field by field and
the first tick where any of them parts company is reported, with everything
that still agreed up to that point.
"""
import hashlib
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import click
import numpy as np
import rclpy

from policy_bridge import decode_action
from policy_rollout import PRE_HOME_Q, Rollout

FIELDS = ["rgb_sha", "lowdim_sha", "pred_sha", "pred_first", "proj_q",
          "ik_pos_err_mm", "exec_first_mm", "q_after"]


def sha(x):
    return hashlib.sha1(np.ascontiguousarray(x).tobytes()).hexdigest()[:12]


@click.command()
@click.option("--socket-path", default="/tmp/omx_policy.sock")
@click.option("--from-demos", default="train")
@click.option("--episode", default=0, type=int, help="which placement")
@click.option("--repeats", default=3, type=int)
@click.option("--max-ticks", default=60, type=int)
@click.option("--exec-steps", default=4, type=int)
@click.option("--scramble/--no-scramble", default=True,
              help="drive somewhere different before each reset, so the reset "
                   "is asked to remove a history that really is different")
@click.option("--reset", type=click.Choice(["protocol", "plain"]),
              default="protocol")
@click.option("--out", default=None)
@click.option("--dump-first", default=None,
              help="write the first observation of each run out in full, so "
                   "the difference between them can be measured rather than "
                   "hashed")
def main(socket_path, from_demos, episode, repeats, max_ticks, exec_steps,
         scramble, reset, out, dump_first):
    rclpy.init()
    b = Rollout(socket_path)
    b.spin(1.5)
    dt = b.meta["action_dt_s"]
    horizon = b.meta["action_horizon"]
    p = sorted((SIM / "data" / "demos" / from_demos).glob("episode_*.npz"))[episode]
    ep = json.loads(str(np.load(p, allow_pickle=True)["spec"]))
    r = float(ep["ball_r"])
    click.secho(f"placement from {p.name}: ball "
                f"{np.round(np.array(ep['object_xy'])*1000, 1)}, bin "
                f"{np.round(np.array(ep['bin_xy'])*1000, 1)} mm", bold=True)

    runs = []
    for run in range(repeats):
        if not b.place(ep["object_xy"], r, ep["bin_xy"], ep["bin_yaw"]):
            raise click.ClickException("could not place the bodies")
        if scramble:
            # a different starting history for every run: the same reset has
            # to wash all three of them out
            target = PRE_HOME_Q + np.radians([(-25, 10, -8, 12, 0),
                                              (30, -12, 9, -14, 0),
                                              (-5, 18, -15, 6, 0)][run % 3])
            qs, times = b.leg(b.q_now(), target)
            b.send_arm(qs, times)
            b.settled(timeout=4.0)
        if reset == "protocol":
            ok, info = b.deterministic_reset()
            if not ok:
                raise click.ClickException(f"reset failed: {info}")
            click.echo(f"  run {run} reset: PRE_HOME settled in "
                       f"{info['pre_home']['seconds']}s, HOME in "
                       f"{info['home']['seconds']}s "
                       f"(bands q {info['home']['q_band_deg']:.4f} deg, "
                       f"ee {info['home']['ee_band_mm']:.4f} mm)")
        elif not b.go_home():
            raise click.ClickException("could not reach HOME")
        b.start_pose = None
        b.last_width = None
        b.spin(0.5)
        p0, R0 = b.ee_now()
        start = {
            "q_deg": np.degrees(b.q_now()).round(4).tolist(),
            "ee_mm": (p0 * 1000).round(4).tolist(),
            "ee_R": np.asarray(R0).round(6).reshape(-1).tolist(),
            "object_mm": (np.asarray(b.body_xyz("object")) * 1000).round(3).tolist(),
            "bin_mm": (np.asarray(b.body_xyz("bin")) * 1000).round(3).tolist(),
            "jaw_gt_mm": round(b.jaw_now_gt() * 1000, 4),
            "sim_time_s": round(float(b.frame_stamp), 4),
        }
        rows, steps = [], 0
        while steps < max_ticks:
            frames = []
            try:
                for k in range(b.meta["obs_horizon"]):
                    f, _ = b.observe()
                    frames.append(f)
                    if k + 1 < b.meta["obs_horizon"]:
                        b.spin(dt)
            except RuntimeError as e:
                rows.append({"tick": steps, "note": str(e)})
                break
            act, batch = b.infer(frames)
            if dump_first and steps == 0:
                d = pathlib.Path(dump_first)
                d.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(
                    d / f"run{run}.npz",
                    **{k: np.asarray(v) for k, v in batch.items()},
                    raw_action=np.asarray(act, np.float32),
                    q=b.q_now(), jaw_gt=np.float64(b.jaw_now_gt()),
                    frame_stamp=np.float64(b.frame_stamp))
            pb, Rb = b.ee_now()
            low = np.concatenate([np.asarray(batch[k]).ravel() for k in sorted(batch)
                                  if k != "camera0_rgb"])
            qs, times, widths, ik_err = [], [], [], None
            for k in range(min(exec_steps, horizon)):
                p_cmd, R_cmd, g_cmd = decode_action(act[0, k], pb, Rb)
                q, p_got, R_got, err = b.project_5dof(p_cmd, R_cmd)
                if ik_err is None:
                    ik_err = round(err["pos_err_mm"], 6)
                if err["pos_err_mm"] > 2.0:
                    break
                qs.append(q)
                widths.append(float(np.clip(g_cmd, b.kin._width_tab.min(),
                                            b.kin._width_tab.max())))
                times.append(dt)
            row = {
                "tick": steps,
                "sim_time_s": round(float(b.frame_stamp), 4),
                "rgb_sha": sha(np.asarray(batch["camera0_rgb"], np.float32)),
                "lowdim_sha": sha(low.astype(np.float64).round(9)),
                "pred_sha": sha(np.asarray(act, np.float32)),
                "pred_first": np.asarray(act[0, 0], np.float64).round(8).tolist(),
                "proj_q": (np.degrees(qs[0]).round(6).tolist() if qs else None),
                "ik_pos_err_mm": ik_err,
                "exec_first_mm": None,
                "q_after": None,
            }
            if qs:
                b.jaw_async(widths[-1])
                ok = b.send_arm(qs, times)
                steps += len(qs)
                row["exec_first_mm"] = (np.asarray(
                    decode_action(act[0, 0], pb, Rb)[0]) * 1000).round(4).tolist()
                row["q_after"] = np.degrees(b.q_now()).round(4).tolist()
                row["controller_ok"] = bool(ok)
            else:
                b.spin(dt)
            rows.append(row)
        runs.append({"start": start, "rows": rows})
        click.echo(f"  run {run}: {len(rows)} replans, {steps} ticks executed")

    # ------------------------------------------------------------- compare --
    click.secho("\nthe state each run started from", bold=True)
    keys = list(runs[0]["start"].keys())
    for k in keys:
        vals = [json.dumps(rn["start"][k]) for rn in runs]
        same = len(set(vals)) == 1
        click.secho(f"  {k:12s} {'identical' if same else 'DIFFERS'}"
                    + ("" if same else "  " + " | ".join(v[:48] for v in vals)),
                    fg=None if same else "red")

    click.secho("\nfirst replan at which each field parts company", bold=True)
    n = min(len(rn["rows"]) for rn in runs)
    first_bad = None
    for f in FIELDS:
        where = None
        for i in range(n):
            vals = [json.dumps(rn["rows"][i].get(f)) for rn in runs]
            if len(set(vals)) > 1:
                where = i
                break
        click.secho(f"  {f:15s} " + ("identical in all " + str(n) + " replans"
                                     if where is None else f"differs from replan {where}"),
                    fg="green" if where is None else "yellow")
        if where is not None and (first_bad is None or where < first_bad[1]):
            first_bad = (f, where)

    click.secho("\nverdict", bold=True)
    if first_bad is None:
        click.secho(f"  the three runs are identical over {n} replans", fg="green")
    else:
        f, i = first_bad
        order = FIELDS.index(f)
        click.echo(f"  the first thing to differ is {f}, at replan {i}")
        for g in FIELDS[:order]:
            click.echo(f"    {g} was still identical there")
        if f in ("rgb_sha", "lowdim_sha"):
            click.secho("  the policy was handed different observations, so the "
                        "difference is upstream of inference: the plant did not "
                        "repeat itself", fg="yellow")
        elif f == "pred_sha" or f == "pred_first":
            click.secho("  identical input, different output: inference is not "
                        "deterministic", fg="red")
        else:
            click.secho("  identical input and identical raw output: the "
                        "difference is downstream -- projection, IK, controller "
                        "or the simulator", fg="yellow")
        for rn in runs:
            row = rn["rows"][i]
            click.echo(f"    run: rgb {row.get('rgb_sha')}  lowdim "
                       f"{row.get('lowdim_sha')}  pred {row.get('pred_sha')}  "
                       f"ik {row.get('ik_pos_err_mm')}")
    if out:
        pathlib.Path(out).write_text(json.dumps(runs, indent=1))
        click.echo(f"\nwrote {out}")
    b.kin.close()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
