from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
XML_PATH = ROOT / "mjcf" / "collector_scene.xml"
OUT_DIR = ROOT / "data"

OUT_DIR.mkdir(parents=True, exist_ok=True)


model = mujoco.MjModel.from_xml_path(str(XML_PATH))
data = mujoco.MjData(model)


def get_id(obj_type, name):
    idx = mujoco.mj_name2id(model, obj_type, name)
    if idx < 0:
        raise RuntimeError(f"Cannot find {name}")
    return idx


collector_body_id = get_id(mujoco.mjtObj.mjOBJ_BODY, "collector")
object_body_id = get_id(mujoco.mjtObj.mjOBJ_BODY, "object")

tcp_site_id = get_id(mujoco.mjtObj.mjOBJ_SITE, "tcp")
left_site_id = get_id(mujoco.mjtObj.mjOBJ_SITE, "left_inner")
right_site_id = get_id(mujoco.mjtObj.mjOBJ_SITE, "right_inner")

mocap_body_id = get_id(mujoco.mjtObj.mjOBJ_BODY, "mocap_target")
mocap_id = model.body_mocapid[mocap_body_id]

left_act_id = get_id(mujoco.mjtObj.mjOBJ_ACTUATOR, "left_act")
right_act_id = get_id(mujoco.mjtObj.mjOBJ_ACTUATOR, "right_act")


renderer = mujoco.Renderer(
    model,
    height=240,
    width=320
)


# -----------------------------------
# Logging
# -----------------------------------

timestamps = []
rgb_frames = []
tcp_positions = []
tcp_quaternions = []
gripper_widths = []
object_positions = []

record_hz = 30.0
next_record_time = 0.0


def get_tcp_quaternion():
    mat = np.asarray(data.site_xmat[tcp_site_id]).reshape(3, 3)

    quat = np.zeros(4, dtype=np.float64)

    mujoco.mju_mat2Quat(
        quat,
        mat.reshape(-1)
    )

    return quat


def get_gripper_width():
    left = data.site_xpos[left_site_id]
    right = data.site_xpos[right_site_id]

    return float(np.linalg.norm(left - right))


def record_if_needed():
    global next_record_time

    if data.time + 1e-9 < next_record_time:
        return

    renderer.update_scene(
        data,
        camera="wrist"
    )

    rgb = renderer.render().copy()

    timestamps.append(data.time)
    rgb_frames.append(rgb)

    tcp_positions.append(
        data.site_xpos[tcp_site_id].copy()
    )

    tcp_quaternions.append(
        get_tcp_quaternion()
    )

    gripper_widths.append(
        get_gripper_width()
    )

    object_positions.append(
        data.xpos[object_body_id].copy()
    )

    next_record_time += 1.0 / record_hz


def set_gripper(alpha):
    """
    alpha:
        0.0 = fully open
        1.0 = closed
    """

    alpha = np.clip(alpha, 0.0, 1.0)

    data.ctrl[left_act_id] = 0.030 * alpha
    data.ctrl[right_act_id] = -0.030 * alpha


def run_segment(
    target_pos,
    duration,
    target_grip
):
    start_pos = data.mocap_pos[mocap_id].copy()

    current_left = data.ctrl[left_act_id]
    start_grip = current_left / 0.030 if 0.030 > 0 else 0.0

    n_steps = int(duration / model.opt.timestep)

    for i in range(n_steps):

        a = (i + 1) / n_steps

        pos = (
            (1.0 - a) * start_pos
            + a * np.asarray(target_pos)
        )

        grip = (
            (1.0 - a) * start_grip
            + a * target_grip
        )

        data.mocap_pos[mocap_id] = pos
        data.mocap_quat[mocap_id] = [1, 0, 0, 0]

        set_gripper(grip)

        mujoco.mj_step(model, data)

        record_if_needed()


# -----------------------------------
# Initialize
# -----------------------------------

mujoco.mj_forward(model, data)

data.mocap_pos[mocap_id] = np.array(
    [0.0, 0.10, 0.06]
)

data.mocap_quat[mocap_id] = np.array(
    [1.0, 0.0, 0.0, 0.0]
)

set_gripper(0.0)


# -----------------------------------
# Scripted Pick & Place
# -----------------------------------

print("Initial object:", data.xpos[object_body_id].copy())


# settle
run_segment(
    [0.0, 0.10, 0.06],
    duration=0.8,
    target_grip=0.0
)

# close around object
run_segment(
    [0.0, 0.10, 0.06],
    duration=1.0,
    target_grip=1.0
)

# lift
run_segment(
    [0.0, 0.10, 0.16],
    duration=1.0,
    target_grip=1.0
)

# move to target
run_segment(
    [0.0, 0.37, 0.16],
    duration=1.5,
    target_grip=1.0
)

# lower
run_segment(
    [0.0, 0.37, 0.06],
    duration=1.0,
    target_grip=1.0
)

# release
run_segment(
    [0.0, 0.37, 0.06],
    duration=0.8,
    target_grip=0.0
)

# retreat
run_segment(
    [0.0, 0.37, 0.15],
    duration=0.8,
    target_grip=0.0
)


# -----------------------------------
# Save episode
# -----------------------------------

timestamps_np = np.asarray(timestamps, dtype=np.float64)
rgb_np = np.asarray(rgb_frames, dtype=np.uint8)
tcp_pos_np = np.asarray(tcp_positions, dtype=np.float32)
tcp_quat_np = np.asarray(tcp_quaternions, dtype=np.float32)
gripper_np = np.asarray(gripper_widths, dtype=np.float32)
object_pos_np = np.asarray(object_positions, dtype=np.float32)


out_path = OUT_DIR / "episode_0000.npz"

np.savez_compressed(
    out_path,
    timestamps=timestamps_np,
    rgb=rgb_np,
    tcp_pos=tcp_pos_np,
    tcp_quat_wxyz=tcp_quat_np,
    gripper_width=gripper_np,
    object_pos=object_pos_np,
)


final_object = data.xpos[object_body_id].copy()

print()
print("Final object:", final_object)
print("Frames:", len(timestamps_np))
print("RGB:", rgb_np.shape)
print("TCP:", tcp_pos_np.shape)
print("Gripper:", gripper_np.shape)
print("Saved:", out_path)

success = final_object[1] > 0.45

print()
print("PICK-PLACE SUCCESS:", success)


renderer.close()
