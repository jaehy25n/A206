"""Does /check_state_validity actually see the table and the bin?

    python sim_umi/ros/check_collision_scene.py

Publishes the environment, then asks MoveIt about poses whose answers are
known in advance. A checker that says yes to everything passes no test at all,
so every negative here is a configuration MuJoCo independently reports as
colliding, and the two have to agree.

  positive  stand-off over the ball, and the grasp pose itself
  negative  the same grasp driven 60 mm below the table
            an arm link folded onto the table
            the claw pushed through the bin's floor
            a genuine self-collision, found by searching MuJoCo's contacts
"""
import math
import pathlib
import sys

import numpy as np
import rclpy
from moveit_msgs.msg import RobotState
from moveit_msgs.srv import GetPlanningScene, GetStateValidity
from moveit_msgs.msg import PlanningSceneComponents

SIM = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "src"))
sys.path.insert(0, str(SIM / "ros"))

import mujoco  # noqa: E402
from collector import Collector  # noqa: E402
from scene import SceneConfig  # noqa: E402
import scene_objects  # noqa: E402

ARM = [f"joint{i}" for i in range(1, 6)]
SRDF_ALLOWED = {frozenset(p) for p in (
    ("link0", "link1"), ("link1", "link2"), ("link2", "link3"),
    ("link2", "link4"), ("link3", "link4"), ("link4", "link5"),
    ("link5", "left_finger"), ("link5", "right_finger"),
    ("left_finger", "right_finger"), ("link5", "collector"),
    ("collector", "left_finger"), ("collector", "right_finger"))}
ROBOT = {"link0", "link1", "link2", "link3", "link4", "link5",
         "collector", "left_finger", "right_finger"}


def mujoco_verdict(col, q):
    """What MuJoCo says about the same configuration: (self, environment)."""
    m, d = col.model, col.data
    mujoco.mj_resetData(m, d)
    for a, v in zip(col.arm_qadr, q):
        d.qpos[a] = v
    col._set_gripper(0.0)
    mujoco.mj_forward(m, d)
    selfc, envc = 0, 0
    for i in range(d.ncon):
        c = d.contact[i]
        b1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[c.geom1])
        b2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[c.geom2])
        if b1 in ROBOT and b2 in ROBOT:
            if frozenset((b1, b2)) not in SRDF_ALLOWED:
                selfc += 1
        elif b1 in ROBOT or b2 in ROBOT:
            g1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom1)
            g2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, c.geom2)
            if any(n in (g1, g2) for n in ("desk", "black_paper")) or \
               "bin" in (b1 if b1 not in ROBOT else b2):
                envc += 1
    return selfc, envc


def find_self_collision(col):
    """Search MuJoCo for a configuration where two non-adjacent links touch."""
    rng = np.random.default_rng(3)
    lo, hi = col.arm_range[:, 0], col.arm_range[:, 1]
    lo = np.maximum(lo, -2.5)
    hi = np.minimum(hi, 2.5)
    for _ in range(4000):
        q = rng.uniform(lo, hi)
        s, _ = mujoco_verdict(col, q)
        if s:
            return q
    return None


def main():
    cfg = SceneConfig()
    col = Collector(str(SIM / "mjcf" / "collector_scene.xml"), cfg=cfg)
    rclpy.init()
    n = rclpy.create_node("collision_scene_check")

    ids = scene_objects.apply(n, cfg)
    print(f"published {len(ids)} collision objects: {', '.join(ids)}")

    ps = n.create_client(GetPlanningScene, "/get_planning_scene")
    ps.wait_for_service(timeout_sec=20)
    req = GetPlanningScene.Request()
    req.components.components = (PlanningSceneComponents.WORLD_OBJECT_NAMES
                                 | PlanningSceneComponents.WORLD_OBJECT_GEOMETRY)
    f = ps.call_async(req)
    rclpy.spin_until_future_complete(n, f, timeout_sec=10)
    got = [o.id for o in f.result().scene.world.collision_objects]
    print(f"scene now holds     : {got or 'NONE'}")

    v = n.create_client(GetStateValidity, "/check_state_validity")
    v.wait_for_service(timeout_sec=20)

    def ask(q):
        r = GetStateValidity.Request()
        r.group_name = "arm"
        rs = RobotState()
        rs.joint_state.name = ARM
        rs.joint_state.position = [float(x) for x in q]
        rs.is_diff = True
        r.robot_state = rs
        fut = v.call_async(r)
        rclpy.spin_until_future_complete(n, fut, timeout_sec=10)
        res = fut.result()
        return bool(res.valid), [c.contact_body_1 + "|" + c.contact_body_2
                                 for c in res.contacts[:3]]

    ox, oy = cfg.object_start_xy
    oz = float(cfg.object_size[2])
    pitch = math.radians(10.0)
    cases = []
    q_pre, _, _, _ = col.solve_ik_best(
        col.grasp_tcp_target((ox, oy), oz + 0.07, pitch, 0.065), pitch)
    q_grasp, _, _, _ = col.solve_ik_best(
        col.grasp_tcp_target((ox, oy), oz, pitch, 0.065), pitch)
    cases.append(("stand-off over the ball", q_pre, True))
    cases.append(("the grasp pose itself", q_grasp, True))

    q_under, e, _, _ = col.solve_ik_best(
        col.grasp_tcp_target((ox, oy), oz - 0.06, pitch, 0.065), pitch)
    cases.append(("driven 60 mm below the table", q_under, False))

    bx, by = cfg.bin_start_xy
    q_bin, e2, _, _ = col.solve_ik_best(
        col.grasp_tcp_target((bx, by), -0.02, pitch, 0.065), pitch)
    cases.append(("pushed through the bin floor", q_bin, False))

    q_fold = np.array([0.0, 1.45, -0.2, -1.2, 0.0])
    cases.append(("folded onto the table", q_fold, False))

    q_self = find_self_collision(col)
    if q_self is not None:
        cases.append(("a self-collision MuJoCo found", q_self, False))
    else:
        print("no self-collision configuration found to test with")

    print(f"\n{'case':34s} {'MoveIt':>8s} {'want':>6s} {'MuJoCo self/env':>16s}  result")
    ok = True
    for name, q, want in cases:
        valid, contacts = ask(q)
        s, e = mujoco_verdict(col, q)
        good = (valid == want)
        ok &= good
        print(f"{name:34s} {str(valid):>8s} {str(want):>6s} "
              f"{s:>8d}/{e:<7d}  {'PASS' if good else 'FAIL'}"
              + (f"   {contacts[0]}" if contacts and not valid else ""))
    col.close()
    print("\n" + ("all checks pass" if ok else "SOME CHECKS FAILED"))
    rclpy.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
