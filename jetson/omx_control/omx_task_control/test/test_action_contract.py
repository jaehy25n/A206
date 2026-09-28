"""The policy action contract, checked the way the GPU side states it.

gpu_server/omx-umi-sim/README_JETSON_HANDOFF.md sections 3-4: position relative
to T0 in the T0 frame, rot6d = first two ROWS, T_abs = T0 @ T_rel, gripper
absolute in metres, step k at t0 + k*dt.

The last test compares against the handoff bundle itself.  Point
OMX_HANDOFF_DIR at an unpacked jetson_handoff/ to run it:

    OMX_HANDOFF_DIR=~/omx_policy/jetson_handoff python3 -m pytest -q omx_task_control/test
"""

import os

import numpy as np
import pytest

from omx_task_control import action_format as af

RNG = np.random.default_rng(7)


def _random_rot():
    q = RNG.normal(size=4)
    q /= np.linalg.norm(q)
    return af.quat_to_mat(*q)


def _random_t(scale=0.3):
    return af.make_t(RNG.uniform(-scale, scale, 3), _random_rot())


def _gpu_rot6d_to_mat(d6):
    """umi/common/pose_util.py rot6d_to_mat, copied: rows are stacked."""
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = a1 / np.linalg.norm(a1, axis=-1, keepdims=True)
    b2 = a2 - np.sum(b1 * a2, axis=-1, keepdims=True) * b1
    b2 = b2 / np.linalg.norm(b2, axis=-1, keepdims=True)
    b3 = np.cross(b1, b2, axis=-1)
    return np.stack((b1, b2, b3), axis=-2)


def test_rot6d_is_first_two_rows():
    for _ in range(50):
        r = _random_rot()
        assert np.allclose(af.rot_to_6d(r), r[:2, :].reshape(6))
        assert np.allclose(af.rot_from_6d(af.rot_to_6d(r)), r, atol=1e-12)


def test_rot_from_6d_matches_gpu_construction():
    for _ in range(50):
        d6 = RNG.normal(size=6)          # not orthonormal: exercises Gram-Schmidt
        assert np.allclose(af.rot_from_6d(d6), _gpu_rot6d_to_mat(d6), atol=1e-12)


def test_decode_matches_contract_probes():
    t0 = _random_t()
    r0, p0 = t0[:3, :3], t0[:3, 3]
    t_abs = [_random_t() for _ in range(af.ACTION_HORIZON)]
    widths = RNG.uniform(0.0, 0.05, af.ACTION_HORIZON)

    # build the action from the contract's own formulas, independently of encode_action
    action = np.zeros((af.ACTION_HORIZON, af.ACTION_DIM))
    for k, t_k in enumerate(t_abs):
        action[k, 0:3] = r0.T @ (t_k[:3, 3] - p0)
        action[k, 3:9] = (r0.T @ t_k[:3, :3])[:2, :].reshape(6)
        action[k, 9] = widths[k]

    dec, w = af.decode_action(action, t0)
    for k, t_k in enumerate(t_abs):
        assert np.allclose(dec[k], t_k, atol=1e-12)
    assert np.allclose(w, widths)                  # absolute, untouched

    # the conventions the contract rules out would not reproduce the poses
    k = 1
    r_rel = af.rot_from_6d(action[k, 3:9])
    cols = np.stack([action[k, 3:6], action[k, 6:9]], axis=1)   # read as two columns
    assert not np.allclose(r0 @ cols[:, :2], t_abs[k][:3, :2], atol=1e-6)
    assert not np.allclose(r_rel @ r0, t_abs[k][:3, :3], atol=1e-6)   # base on the right


def test_encode_decode_roundtrip():
    t0 = _random_t()
    t_abs = [t0] + [_random_t() for _ in range(af.ACTION_HORIZON - 1)]
    action = af.encode_action(t0, t_abs, [0.03] * af.ACTION_HORIZON)
    assert np.allclose(action[0, 0:3], 0.0, atol=1e-12)                   # action[0] = T0
    assert np.allclose(action[0, 3:9], [1, 0, 0, 0, 1, 0], atol=1e-12)    # identity rot6d
    dec, _ = af.decode_action(action, t0)
    assert np.allclose(dec, np.stack(t_abs), atol=1e-12)


def test_schedule_drops_stale_prefix():
    t0, dt, n = 100.0, af.ACTION_DT_S, af.ACTION_HORIZON
    assert [k for k, _ in af.schedule(t0, dt, n, t0)] == list(range(1, n))   # step 0 always stale
    kept = af.schedule(t0, dt, n, t0 + 0.25)
    assert kept[0][0] == 3 and kept[0][1] == pytest.approx(t0 + 0.3)
    assert af.schedule(t0, dt, n, t0 + n * dt) == []


HANDOFF = os.environ.get('OMX_HANDOFF_DIR', '')


@pytest.mark.skipif(not os.path.isfile(os.path.join(HANDOFF, 'decoder_reference.npz')),
                    reason='set OMX_HANDOFF_DIR to an unpacked jetson_handoff/')
def test_decoder_parity_with_handoff_bundle():
    ref = np.load(os.path.join(HANDOFF, 'decoder_reference.npz'))
    t0 = af.make_t(ref['base_position'], ref['base_rotation_matrix'])
    for raw, pos, rot in [
            ('raw_action', 'expected_position', 'expected_rotation_matrix'),
            ('groundtruth_raw_action', 'groundtruth_expected_position', None)]:
        dec, w = af.decode_action(ref[raw].astype(np.float64), t0)
        assert np.allclose(dec[:, :3, 3], ref[pos], atol=1e-5), raw
        if rot:
            assert np.allclose(dec[:, :3, :3], ref[rot], atol=1e-5), raw
    _, w = af.decode_action(ref['raw_action'].astype(np.float64), t0)
    assert np.allclose(w, ref['expected_gripper'], atol=1e-6)
