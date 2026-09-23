"""Round-trip and projection tests for the analytic OMX-F kinematics."""

import math
import random

import numpy as np
import pytest

from omx_task_control.kinematics import (BASE_X, JOINT_NAMES, IKError, Kinematics, rpy_to_rot,
                                         wrap)


@pytest.fixture
def kin():
    return Kinematics()


def test_reach_matches_datasheet(kin):
    assert abs(kin.max_reach - 0.4032) < 1e-3


def test_zero_pose_matches_urdf_chain(kin):
    x, y, z, pitch, roll = kin.forward([0.0] * 5)
    # base(-0.01125,0,0.034) + j2 z 0.0635 + j3 (0.0415,0,0.11315) + 0.162 + 0.0287 + 0.09193
    assert abs(x - 0.31288) < 1e-5
    assert abs(y) < 1e-9
    assert abs(z - 0.21065) < 1e-5
    assert abs(pitch) < 1e-9 and abs(roll) < 1e-9


def test_fk_ik_round_trip(kin):
    """Every pose whose wrist lies in front of the joint1 axis must round trip.

    Configurations folded behind the base axis (planar radius < 0) describe the
    same TCP pose with azimuth j1+pi and mirrored pitch; the (x, y, z, pitch,
    roll) parametrisation cannot tell them apart, so they are skipped here.
    """
    random.seed(0)
    matched = failed = skipped = 0
    for _ in range(5000):
        q = [random.uniform(lo, hi) for lo, hi in zip(kin.lower[:5], kin.upper[:5])]
        pose = kin.forward(q)
        azimuth = math.atan2(pose[1], pose[0] - BASE_X)
        if abs(wrap(azimuth - q[0])) > 1e-6:
            skipped += 1          # folded behind the base axis
            continue
        ok = False
        for elbow in (True, False):
            try:
                q2 = kin.inverse(*pose, elbow_up=elbow)
            except IKError:
                continue
            pose2 = kin.forward(q2)
            if max(abs(a - b) for a, b in zip(pose[:3], pose2[:3])) < 1e-9 and \
                    abs(wrap(pose[3] - pose2[3])) < 1e-9:
                ok = True
                break
        matched += ok
        failed += not ok
    assert failed == 0, f'{failed} poses did not round trip'
    assert matched > 3000, f'only {matched} testable poses ({skipped} folded behind the base)'


def test_forward_matrix_consistent_with_projection(kin):
    q = kin.inverse(0.22, 0.05, 0.12, math.radians(30), math.radians(10))
    t = kin.forward_matrix(q)
    x, y, z, pitch, roll, drop = kin.project(t)
    assert abs(x - 0.22) < 1e-9 and abs(y - 0.05) < 1e-9 and abs(z - 0.12) < 1e-9
    assert abs(pitch - math.radians(30)) < 1e-9
    assert abs(roll - math.radians(10)) < 1e-9
    assert abs(drop) < 1e-9            # yaw was already the forced one


def test_projection_reports_discarded_yaw(kin):
    p = np.array([0.22, 0.0, 0.12])
    yaw_forced = math.atan2(p[1], p[0] - BASE_X)
    extra = math.radians(25)
    t = np.eye(4)
    t[:3, :3] = rpy_to_rot(yaw_forced + extra, math.radians(30), 0.0)
    t[:3, 3] = p
    x, y, z, pitch, roll, drop = kin.project(t)
    assert abs(drop - extra) < 1e-6
    # after projection the pose is realisable and pitch survives approximately
    q, info = kin.solve(t)
    assert q is not None, info
    assert abs(kin.forward(q)[0] - 0.22) < 1e-9


def test_solve_prefers_seed_branch(kin):
    t = kin.forward_matrix(kin.inverse(0.20, 0.0, 0.18, math.radians(45), 0.0, elbow_up=False))
    q_up, _ = kin.solve(t, q_seed=kin.inverse(0.20, 0.0, 0.18, math.radians(45), 0.0, True))
    q_dn, _ = kin.solve(t, q_seed=kin.inverse(0.20, 0.0, 0.18, math.radians(45), 0.0, False))
    assert q_up is not None and q_dn is not None
    # both branches realise the same TCP pose
    for a, b in zip(kin.forward(q_up)[:3], kin.forward(q_dn)[:3]):
        assert abs(a - b) < 1e-9


def test_unreachable_raises(kin):
    with pytest.raises(IKError):
        kin.inverse(0.9, 0.0, 0.1, 0.0, 0.0)
    q, info = kin.solve(np.eye(4) @ np.diag([1, 1, 1, 1]) + np.array([[0, 0, 0, 0.9], [0] * 4, [0] * 4, [0] * 4]))
    assert q is None and info['reason']


def test_gripper_width_mapping(kin):
    assert kin.width_to_gripper(0.0) == pytest.approx(kin.gripper_closed)
    assert kin.width_to_gripper(1.0) == pytest.approx(kin.gripper_open)
    assert kin.gripper_to_width(kin.width_to_gripper(0.37)) == pytest.approx(0.37)


def test_joint_names():
    assert JOINT_NAMES == ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
