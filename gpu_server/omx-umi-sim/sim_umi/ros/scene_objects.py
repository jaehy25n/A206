"""Put the real environment into MoveIt's planning scene.

Without this, /check_state_validity answers about the robot and nothing else:
the world is empty, so a state that drives the claw straight through the table
comes back valid. Verified on this stack before the file existed --

    world collision objects : NONE
    check_state_validity(straight down into the table) -> valid=True

The boxes are built from SceneConfig, the same numbers the MJCF is generated
from, so the two cannot drift apart. They are expressed in link0's frame,
because that is the URDF's root: the MJCF stands the arm on the table at
robot_base_xy turned by 90 degrees, and MoveIt knows nothing about that pose.

    p_link0 = R_z(-arm_base_yaw) . (p_world - base)
"""
import math
import sys
import pathlib

import numpy as np
from geometry_msgs.msg import Pose
from moveit_msgs.msg import CollisionObject, PlanningScene
from moveit_msgs.srv import ApplyPlanningScene
from shape_msgs.msg import SolidPrimitive

SIM = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "src"))

from scene import SceneConfig  # noqa: E402

FRAME = "link0"


def to_link0(cfg, xyz):
    """A world point (the MJCF's table frame) in the URDF root's frame."""
    bx, by = cfg.robot_base_xy
    d = np.array([xyz[0] - bx, xyz[1] - by, xyz[2]], float)
    a = -cfg.arm_base_yaw
    c, s = math.cos(a), math.sin(a)
    return np.array([c * d[0] - s * d[1], s * d[0] + c * d[1], d[2]])


def box(cfg, name, centre_world, half_extents_world):
    """A world-axis-aligned box, turned into link0's frame.

    arm_base_yaw is 90 degrees, so the world x and y half-extents swap; this
    asserts that rather than assuming it, because a 45 degree base would make
    an axis-aligned box the wrong primitive entirely.
    """
    yaw = cfg.arm_base_yaw
    assert abs(abs(math.sin(yaw)) - 1.0) < 1e-9, \
        "the base yaw is not a quarter turn; these boxes would need a rotation"
    hx, hy, hz = half_extents_world
    o = CollisionObject()
    o.id = name
    o.header.frame_id = FRAME
    p = SolidPrimitive()
    p.type = SolidPrimitive.BOX
    p.dimensions = [2 * hy, 2 * hx, 2 * hz]      # swapped by the quarter turn
    pose = Pose()
    c = to_link0(cfg, centre_world)
    pose.position.x, pose.position.y, pose.position.z = (float(v) for v in c)
    pose.orientation.w = 1.0
    o.primitives.append(p)
    o.primitive_poses.append(pose)
    o.operation = CollisionObject.ADD
    return o


def environment(cfg=None, bin_xy=None, bin_yaw=0.0):
    """Table, paper and bin, as MoveIt collision objects.

    The bin moves. It was always published at cfg.bin_start_xy, so every
    episode that drew a bin somewhere else was checked against a bin that was
    not there -- an arm swinging through the real bin passed, and an arm
    nowhere near it was rejected for hitting the phantom. Pass the episode's
    bin pose and the check is against the bin the plant actually has.
    """
    cfg = cfg or SceneConfig()
    out = []
    tw, td = cfg.table_size
    th = 0.02
    # The table top is at z = 0 and the slab hangs below it. A zero-thickness
    # plane would let a link "pass" by being exactly on it.
    out.append(box(cfg, "table", (0.0, 0.0, -th), (tw / 2, td / 2, th)))
    pw, pd = cfg.paper_size
    out.append(box(cfg, "paper", (0.0, 0.0, 0.0005), (pw / 2, pd / 2, 0.0005)))

    bx, by = cfg.bin_start_xy if bin_xy is None else bin_xy
    b = cfg.bin_outer / 2
    w = cfg.bin_wall
    out.append(box(cfg, "bin_floor", (bx, by, w), (b, b, w)))
    # A turned bin cannot be an axis-aligned box, so a turned bin is covered
    # by the circle its own walls sweep: the half extent grows to the corner
    # distance. Conservative on purpose -- it can refuse a path that would
    # have squeezed past a corner, and it can never miss a wall that is there.
    grow = (b * (abs(math.cos(bin_yaw)) + abs(math.sin(bin_yaw))) - b)
    for name, dx, dy, hx, hy in (("bin_wall_yp", 0.0, b - w, b, w),
                                 ("bin_wall_ym", 0.0, -(b - w), b, w),
                                 ("bin_wall_xp", b - w, 0.0, w, b - 2 * w),
                                 ("bin_wall_xm", -(b - w), 0.0, w, b - 2 * w)):
        c, sn = math.cos(bin_yaw), math.sin(bin_yaw)
        rx, ry = c * dx - sn * dy, sn * dx + c * dy
        out.append(box(cfg, name, (bx + rx, by + ry, b + w),
                       (hx + grow, hy + grow, b - w)))
    return out


def apply(node, cfg=None, timeout=20.0, bin_xy=None, bin_yaw=0.0):
    """Push the objects through /apply_planning_scene and wait for the ack."""
    import rclpy
    cli = node.create_client(ApplyPlanningScene, "/apply_planning_scene")
    if not cli.wait_for_service(timeout_sec=timeout):
        raise RuntimeError("/apply_planning_scene never came up")
    scene = PlanningScene()
    scene.is_diff = True
    scene.world.collision_objects = environment(cfg, bin_xy, bin_yaw)
    req = ApplyPlanningScene.Request()
    req.scene = scene
    fut = cli.call_async(req)
    rclpy.spin_until_future_complete(node, fut, timeout_sec=timeout)
    r = fut.result()
    if r is None or not r.success:
        raise RuntimeError("the planning scene was not accepted")
    return [o.id for o in scene.world.collision_objects]
