"""The timing-controlled evaluator (dse_rollout.py) with ORACLE masks per observation frame.

    source sim_umi/ros/env_overlay_masks.sh
    python sim_umi/ros/dse_rollout_masks.py --oracle-masks send|generate-only --mask-log <jsonl> <dse_rollout args>

For ablation B and its G0 control. dse_rollout.py, policy_bridge.py and policy_server.py
are NOT modified; this file wraps two Bridge methods and then runs dse_rollout's own main:

  observe_at   after the frame and its joint snapshot of the SAME stamp are taken (exact
               mode), the mirror of the plant's model is posed from that snapshot -- arm and
               jaw joints, and object / bin from the free-joint entries the patched camera
               plugin adds to the same snapshot (joint_snapshot_free_joints) -- and the masks
               are rendered with the one oracle implementation (sim_umi/src/oracle_render.py,
               the code that built the prep sidecar). RGB frame t <-> snapshot t <-> masks t.
               The plant is paused meanwhile, so the rendering costs no simulated time.
  build_batch  adds camera0_target_mask, camera0_ee_tip_mask (uint8, 1 x T x 224 x 224) and
               camera0_target_mask_valid (1 x T) for both obs frames.
               --oracle-masks send           under those names: the policy (B) reads them
               --oracle-masks generate-only  the same arrays under "_"-prefixed names, which
                                             policy_server strips: the G0 control pays the same
                                             rendering and transfer and ignores the masks

target_mask_valid = the frame's snapshot was exact and carried both free joints. Every
frame's mask provenance goes to --mask-log (one JSON line per frame).
"""
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIM = ROOT / "sim_umi"
sys.path[:0] = [str(ROOT), str(SIM / "src"), str(SIM / "ros")]

import numpy as np

MASK_KEYS = {"target_mask": "camera0_target_mask", "ee_tip_mask": "camera0_ee_tip_mask"}
VALID_KEY = "camera0_target_mask_valid"


def _take(argv, flag):
    if flag not in argv:
        return None
    i = argv.index(flag)
    v = argv[i + 1]
    del argv[i:i + 2]
    return v


def install(mode, log_path):
    import cv2
    import policy_bridge as PB
    from oracle_render import OracleRenderer
    assert mode in ("send", "generate-only")
    state = {"R": None, "log": open(log_path, "a")}
    orig_observe_at, orig_build = PB.Bridge.observe_at, PB.Bridge.build_batch

    def observe_at(self, stamp):
        f, img, info, st = orig_observe_at(self, stamp)
        w0 = time.time()
        if state["R"] is None:
            state["R"] = OracleRenderer()
        R = state["R"]
        exact = info.get("mode") == "exact" and info.get("source") == "rgb_snapshot"
        miss = R.pose_from_joint_state(st)["missing"] if st is not None else ["no snapshot"]
        rr = R.render(R.d)
        valid = bool(exact and not miss)
        f["_oracle"] = {"target_mask": rr["g0"]["target_mask"].astype(np.uint8),
                        "ee_tip_mask": rr["g0"]["ee_tip_mask"].astype(np.uint8), "valid": valid}
        # QA against the picture the policy is given (tip patches painted out there)
        keep = ~cv2.dilate(np.isin(rr["ids"], R.tips).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        diff = np.abs(rr["im"].astype(np.int16) - img.astype(np.int16)).mean(-1)
        crop = np.zeros_like(keep); crop[:, 70:250] = True
        snap_ns = None
        if st is not None and hasattr(st, "header"):
            snap_ns = st.header.stamp.sec * 1_000_000_000 + st.header.stamp.nanosec
        rec = {"image_stamp_s": round(float(info["image_stamp_s"]), 6), "requested_stamp_s": round(float(stamp), 6),
               "snapshot_stamp_ns": snap_ns, "image_stamp_ns": int(round(float(info["image_stamp_s"]) * 1e9)),
               "state_mode": info.get("mode"), "state_source": info.get("source"), "missing": miss, "valid": valid,
               "px224": {k: int(rr["g0"][k].sum()) for k in ("target_mask", "ee_gripper_mask", "ee_tip_mask")},
               "gripper_px_off_finger_box": int(rr["off_box"]),
               "mirror_vs_image_mad_crop": round(float(diff[crop & keep].mean()), 4),
               "render_wall_s": round(time.time() - w0, 4)}
        state["log"].write(json.dumps(rec) + "\n")
        state["log"].flush()
        return f, img, info, st

    def build_batch(self, frames):
        batch = orig_build(self, frames)
        if all("_oracle" in f for f in frames):
            pre = "" if mode == "send" else "_"
            for name, key in MASK_KEYS.items():
                batch[pre + key] = np.stack([f["_oracle"][name] for f in frames])[None]
            batch[pre + VALID_KEY] = np.array([[f["_oracle"]["valid"] for f in frames]], np.uint8)
        return batch

    PB.Bridge.observe_at = observe_at
    PB.Bridge.build_batch = build_batch


if __name__ == "__main__":
    argv = sys.argv[1:]
    mode = _take(argv, "--oracle-masks")
    log_path = _take(argv, "--mask-log")
    if mode is None or log_path is None:
        sys.exit("usage: dse_rollout_masks.py --oracle-masks send|generate-only --mask-log <jsonl> <dse_rollout args>")
    install(mode, log_path)
    import dse_rollout
    sys.argv = [str(SIM / "ros" / "dse_rollout.py")] + argv
    dse_rollout.main()
