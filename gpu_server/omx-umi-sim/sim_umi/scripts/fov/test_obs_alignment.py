"""Static tests of the observation-pair fix: state_at_aligned and observe_at
on fake buffers (no simulator, no ROS graph -- the module is only imported)."""
import collections
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sim_umi/ros"), str(ROOT / "sim_umi/src")]
import numpy as np

import policy_bridge as PB
from gripper_vision import TipDetectorConfig

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


Msg = collections.namedtuple("Msg", "name position")
names = [f"joint{i}" for i in range(1, 6)] + ["gripper_joint_1"]
fake = types.SimpleNamespace()
fake.js_buf = collections.deque(maxlen=400)
fake.state = None
fake._recorder_lookup = lambda stamp: None       # no recorder: the local buffer, marked "local"
for k in range(200):                               # 455 Hz-ish, irregular
    t = 10.0 + k * 0.0022 + (0.0003 if k % 3 == 0 else 0.0)
    fake.js_buf.append((t, Msg(names, [t] * 6)))   # position = its own stamp, so interpolation is checkable
t_ex = fake.js_buf[50][0]
st, info = PB.Bridge.state_at_aligned(fake, t_ex)
check("exact stamp -> that message", info["mode"] == "exact" and st.position[0] == t_ex)
t_mid = (fake.js_buf[80][0] + fake.js_buf[81][0]) / 2
st, info = PB.Bridge.state_at_aligned(fake, t_mid)
check("between two -> linear interpolation at the stamp", info["mode"] == "interp" and abs(st.position[0] - t_mid) < 1e-12,
      f"{st.position[0]:.6f} vs {t_mid:.6f}")
st, info = PB.Bridge.state_at_aligned(fake, 10.0 + 200 * 0.0022 + 0.05)
check("outside the buffer -> nearest, flagged with its skew", info["mode"] == "nearest" and info["skew_s"] < 0,
      f"skew {info['skew_s']:.4f} s")
# frames on the camera's 20 Hz simulation grid, one missing
fake.frame_buf = collections.deque(maxlen=60)
for k in range(40):
    t = round(20.0 + 0.05 * k, 6)
    if k == 30:
        continue
    img = np.full((180, 320, 3), 100 + k, np.uint8)
    fake.frame_buf.append((t, img))
fake.js_buf = collections.deque([(round(20.0 + 0.001 * k, 6), Msg(names, [0.1] * 6)) for k in range(2000)], maxlen=4000)
fake.jaw_from_camera = lambda raw: (0.05, 10.0)
fake.tip_cfg = TipDetectorConfig()
fake.state_at_aligned = lambda s: PB.Bridge.state_at_aligned(fake, s)
fake.ee_now = lambda st: (np.zeros(3), np.eye(3))
fake.jaw_now_gt = lambda: 0.05
fake.start_pose = None
fake.rgb_geometry = "g0_center224"
fake.frame_log = {}
fake.obs_frames = lambda: list(fake.frame_buf)          # the complete buffer, as the bridge snapshots it
t_cur = round(20.0 + 0.05 * 39, 6)
o_hist = PB.Bridge.observe_at(fake, round(t_cur - 0.1, 6))
o_cur = PB.Bridge.observe_at(fake, t_cur)
check("history frame picked by stamp t-0.1 exactly", o_hist[2]["frame_exact"] and abs(o_hist[2]["image_stamp_s"] - (t_cur - 0.1)) < 1e-9
      and int(o_hist[1][0, 0, 0]) == 100 + 37, f"stamp {o_hist[2]['image_stamp_s']}")
check("current frame picked by stamp t", o_cur[2]["frame_exact"] and int(o_cur[1][0, 0, 0]) == 100 + 39)
check("pair dt = 0.100 s", abs((o_cur[2]["image_stamp_s"] - o_hist[2]["image_stamp_s"]) - 0.1) < 1e-9)
check("states aligned to each image stamp (exact or interp)", o_hist[2]["mode"] in ("exact", "interp") and o_cur[2]["mode"] in ("exact", "interp"),
      f"{o_hist[2]['mode']}, {o_cur[2]['mode']}")
miss = PB.Bridge.observe_at(fake, round(20.0 + 0.05 * 30, 6))
check("a dropped frame is not silently replaced: nearest used AND flagged", (not miss[2]["frame_exact"]) and
      abs(miss[2]["image_stamp_s"] - miss[2]["requested_stamp_s"]) > 1e-3,
      f"asked {miss[2]['requested_stamp_s']}, used {miss[2]['image_stamp_s']}")
check("G0 input from observe_at == preprocess_rgb of the masked frame",
      np.array_equal(o_cur[0]["rgb"], PB.preprocess_rgb(o_cur[1])))
# the recorder process's own lookup, on a synthetic buffer
import state_recorder as SR
SR.BUF.clear()
for k in range(500):
    t = 30.0 + k * 0.0022
    SR.BUF.append((t, names, [t] * 6))
r = SR.lookup(SR.BUF[100][0])
check("recorder: exact stamp", r["mode"] == "exact")
tm = (SR.BUF[200][0] + SR.BUF[201][0]) / 2
r = SR.lookup(tm)
check("recorder: interpolation at the stamp, bracket a few ms", r["mode"] == "interp" and abs(r["position"][0] - tm) < 1e-12
      and (r["bracket_s"][1] - r["bracket_s"][0]) < 0.003, f"bracket {1000 * (r['bracket_s'][1] - r['bracket_s'][0]):.1f} ms")
r = SR.lookup(40.0)
check("recorder: beyond the buffer -> nearest, flagged", r["mode"] == "nearest")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
