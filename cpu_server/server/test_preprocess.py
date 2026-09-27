import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

import preprocess


RAW_SESSIONS = Path("/srv/sessions")
USABLE_SESSION = RAW_SESSIONS / "2804e7e7-2553-4f28-8941-87619ae7312c"
UNTRACKED_SESSION = RAW_SESSIONS / "e096668c-6393-43c9-9a21-91a18b6e3b74"


class TransformTests(unittest.TestCase):
    def test_pose_transform_inverse_and_relative_action(self):
        start = preprocess.pose_to_transform((1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0))
        end = preprocess.pose_to_transform((2.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0))
        identity = preprocess.matrix_multiply(start, preprocess.invert_rigid_transform(start))
        for row in range(4):
            for column in range(4):
                self.assertAlmostEqual(identity[row][column], 1.0 if row == column else 0.0)
        actions, pairs = preprocess.relative_transform_actions([start, end], [True, True])
        self.assertEqual(pairs, [(0, 1)])
        self.assertAlmostEqual(actions[0][0][3], 1.0)

    def test_action_generation_does_not_bridge_invalid_pose(self):
        poses = [
            preprocess.pose_to_transform((float(index), 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
            for index in range(3)
        ]
        actions, pairs = preprocess.relative_transform_actions(poses, [True, False, True])
        self.assertEqual(actions, [])
        self.assertEqual(pairs, [])

    def test_paused_quality_uses_mutable_configured_thresholds(self):
        metrics = {
            "total_frame_count": 10,
            "valid_pose_count": 10,
            "tracking_ratio": 1.0,
            "max_paused_duration_ms": 0.0,
            "num_paused_segments": 0,
        }
        thresholds = dict(preprocess.QUALITY_DEFAULTS)
        self.assertEqual(preprocess._classify_quality(metrics, thresholds)[0], "VALID")
        thresholds["valid_min_tracking_ratio"] = 1.0
        thresholds["valid_max_paused_duration_ms"] = -1.0
        self.assertEqual(preprocess._classify_quality(metrics, thresholds)[0], "DEGRADED")


class NpzTests(unittest.TestCase):
    def test_archive_contains_numpy_v1_arrays(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trajectory.npz"
            preprocess._write_npz(path, {
                "timestamp_ns": ("<i8", (2,), [10, 20]),
                "pose_valid": ("|b1", (2,), [True, False]),
            })
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                content = archive.read("timestamp_ns.npy")
                self.assertEqual(content[:8], b"\x93NUMPY\x01\x00")
                header_len = int.from_bytes(content[8:10], "little")
                header = content[10:10 + header_len].decode("latin1")
                self.assertIn("'shape': (2,)", header)
                self.assertEqual(len(content) - 10 - header_len, 16)


class SlicingTests(unittest.TestCase):
    def test_episode_slice_reports_source_edges_and_unencoded_csv_tail(self):
        frames = [
            {"timestamp_ns": 10, "timestamp_source": "SENSOR_TIMESTAMP"},
            {"timestamp_ns": 20, "timestamp_source": "SENSOR_TIMESTAMP"},
            {"timestamp_ns": 30, "timestamp_source": "SENSOR_TIMESTAMP"},
            {"timestamp_ns": 40, "timestamp_source": "SENSOR_TIMESTAMP"},
        ]
        episode = {"start_timestamp_ns": 15, "end_timestamp_ns": 35}
        selected, trimmed_start, trimmed_end, unencoded = preprocess._episode_frames(
            episode, frames, common_count=2, first_valid_ts=10
        )
        self.assertEqual([row["timestamp_ns"] for row in selected], [20])
        self.assertEqual((trimmed_start, trimmed_end, unencoded), (1, 0, 1))


def _config(**overrides):
    config = preprocess._load_config(Path("/nonexistent-preprocess-config"))
    for block, values in overrides.items():
        config[block].update(values)
    return config


def _row(index, valid, interval_ns=33_000_000, tx=0.0):
    """One episode row at a fixed 30 Hz cadence."""
    return {
        "frame_idx": index,
        "episode_frame_idx": index,
        "timestamp_ns": 1_000 + index * interval_ns,
        "timestamp_source": "SENSOR_TIMESTAMP",
        "rgb_frame_index": index,
        "tracking_state": "TRACKING" if valid else "PAUSED",
        "camera_tx": tx if valid else None,
        "camera_ty": 0.0 if valid else None,
        "camera_tz": 0.0 if valid else None,
        "camera_qx": 0.0 if valid else None,
        "camera_qy": 0.0 if valid else None,
        "camera_qz": 0.0 if valid else None,
        "camera_qw": 1.0 if valid else None,
        "pose_valid": valid,
        "pose_valid_original": valid,
        "pose_interpolated": False,
        "tracking_failure_reason": "NONE",
        "rgb_path": None,
    }


def _rows(pattern, **kwargs):
    return [_row(index, char == "V", tx=float(index), **kwargs) for index, char in enumerate(pattern)]


class QuaternionTests(unittest.TestCase):
    def test_slerp_halfway_is_half_the_rotation(self):
        half = math.sqrt(0.5)
        result = preprocess.quaternion_slerp((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, half, half), 0.5)
        expected = (0.0, 0.0, math.sin(math.pi / 8), math.cos(math.pi / 8))
        for actual, target in zip(result, expected):
            self.assertAlmostEqual(actual, target, places=9)

    def test_slerp_takes_the_shortest_arc_through_a_negated_quaternion(self):
        half = math.sqrt(0.5)
        result = preprocess.quaternion_slerp((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, -half, -half), 0.5)
        expected = (0.0, 0.0, math.sin(math.pi / 8), math.cos(math.pi / 8))
        for actual, target in zip(result, expected):
            self.assertAlmostEqual(actual, target, places=9)

    def test_slerp_result_is_a_unit_quaternion(self):
        result = preprocess.quaternion_slerp((0.1, 0.2, 0.3, 0.9), (-0.4, 0.1, 0.2, 0.8), 0.37)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in result)), 1.0, places=12)


class PoseValidityTests(unittest.TestCase):
    def _pose(self, **overrides):
        pose = {
            "tx": "1.0", "ty": "2.0", "tz": "3.0",
            "qx": "0.0", "qy": "0.0", "qz": "0.0", "qw": "1.0",
            "tracking_state": "TRACKING", "tracking_failure_reason": "NONE",
        }
        pose.update(overrides)
        return pose

    def _rows_for(self, pose):
        frames = [{"timestamp_ns": 10, "timestamp_source": "SENSOR_TIMESTAMP", "rgb_frame_index": 0}]
        validity = _config()["pose_validity"]
        return preprocess._make_episode_rows(frames, {10: pose}, validity)

    def test_paused_row_with_a_filled_in_dummy_pose_is_not_valid(self):
        # Real uploads write a unit-norm placeholder pose on PAUSED rows.
        row = self._rows_for(self._pose(
            tx="0.0", ty="0.0", tz="0.0",
            qx="-2.9802322E-8", qy="-2.9802322E-8", qz="-0.7071067", qw="0.7071067",
            tracking_state="PAUSED",
        ))[0]
        self.assertFalse(row["pose_valid"])
        self.assertIsNone(row["camera_tx"])

    def test_tracking_flag_without_usable_numbers_is_not_valid(self):
        row = self._rows_for(self._pose(tx=""))[0]
        self.assertFalse(row["pose_valid"])
        self.assertEqual(row["tracking_failure_reason"], "INVALID_TRACKING_POSE")

    def test_quaternion_norm_outside_tolerance_is_not_valid(self):
        row = self._rows_for(self._pose(qw="1.5"))[0]
        self.assertFalse(row["pose_valid"])
        self.assertEqual(row["tracking_failure_reason"], "INVALID_TRACKING_POSE")

    def test_missing_pose_row_is_reported_as_missing(self):
        frames = [{"timestamp_ns": 10, "timestamp_source": "SENSOR_TIMESTAMP", "rgb_frame_index": 0}]
        row = preprocess._make_episode_rows(frames, {}, _config()["pose_validity"])[0]
        self.assertEqual((row["tracking_state"], row["tracking_failure_reason"]), ("MISSING", "MISSING_POSE"))
        self.assertFalse(row["pose_valid"])


class PublishGateConfigTests(unittest.TestCase):
    def _load(self, **trajectory_quality):
        config = json.loads(Path("preprocess_v1_config.json").read_text())
        config["trajectory_quality"].update(trajectory_quality)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps(config))
            return preprocess._load_config(path)

    def test_checked_in_gate_matches_the_reference_policy_contract(self):
        trajectory = self._load()["trajectory_quality"]
        self.assertEqual(trajectory["min_publish_segment_frames"], 48)
        self.assertEqual(trajectory["implied_min_publish_segment_frames"], 48)

    def test_a_gate_below_the_policy_contract_is_refused(self):
        with self.assertRaises(preprocess.PreprocessError) as caught:
            self._load(min_publish_segment_frames=20)
        self.assertIn("below the 48 source frames", str(caught.exception))

    def test_a_longer_action_horizon_raises_the_required_gate(self):
        with self.assertRaises(preprocess.PreprocessError) as caught:
            self._load(action_horizon_reference=32)
        self.assertIn("below the 96 source frames", str(caught.exception))


class RepairTests(unittest.TestCase):
    def test_leading_and_trailing_invalid_frames_are_trimmed(self):
        rows = _rows("xxxx" + "V" * 80 + "xx")
        segments, stats, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        self.assertEqual(len(segments), 1)
        self.assertEqual((stats["trimmed_start_frames"], stats["trimmed_end_frames"]), (4, 2))
        self.assertEqual([row["episode_frame_idx"] for row in segments[0][1]][:2], [4, 5])
        self.assertEqual(len(segments[0][1]), 80)

    def test_short_dropout_is_interpolated_and_stays_traceable(self):
        rows = _rows("V" * 40 + "x" + "V" * 40)
        segments, stats, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        self.assertEqual((stats["interpolated_pose_frames"], stats["split_count"]), (1, 0))
        repaired = segments[0][1][40]
        self.assertTrue(repaired["pose_valid"])
        self.assertTrue(repaired["pose_interpolated"])
        self.assertFalse(repaired["pose_valid_original"])
        self.assertEqual(repaired["tracking_state"], "PAUSED")
        # Translation runs 0,1,2,... so the filled frame must land on its index.
        self.assertAlmostEqual(repaired["camera_tx"], 40.0, places=9)
        self.assertAlmostEqual(repaired["camera_qw"], 1.0, places=12)

    def test_dropout_longer_than_the_threshold_splits_instead_of_bridging(self):
        rows = _rows("V" * 60 + "x" * 36 + "V" * 60)
        segments, stats, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        self.assertEqual(stats["split_count"], 1)
        self.assertEqual(stats["interpolated_pose_frames"], 0)
        self.assertEqual(stats["dropped_gap_frames"], 36)
        self.assertEqual([index for index, _ in segments], [0, 1])
        self.assertEqual([len(rows) for _, rows in segments], [60, 60])
        self.assertTrue(all(row["pose_valid"] for _, part in segments for row in part))

    def test_a_frame_count_gap_within_the_limit_still_splits_when_it_spans_too_long(self):
        rows = _rows("V" * 60 + "x" + "V" * 60)
        for row in rows[61:]:
            row["timestamp_ns"] += 2_000_000_000
        segments, stats, _ = preprocess._repair_episode_rows(rows, _config())
        self.assertEqual((stats["split_count"], stats["interpolated_pose_frames"]), (1, 0))
        self.assertEqual([len(part) for _, part in segments], [60, 60])

    def test_segments_too_short_to_train_on_are_dropped_not_published(self):
        rows = _rows("V" * 60 + "x" * 36 + "V" * 5)
        segments, stats, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        self.assertEqual(stats["dropped_short_segment_count"], 1)
        self.assertEqual(stats["output_segment_count"], 1)
        self.assertEqual([index for index, _ in segments], [0])

    def test_episode_without_any_valid_pose_is_rejected(self):
        segments, stats, reject = preprocess._repair_episode_rows(_rows("x" * 200), _config())
        self.assertEqual(reject, "NO_VALID_TRACKING_POSE")
        self.assertEqual(segments, [])
        self.assertEqual(stats["valid_pose_count_before_repair"], 0)

    def test_episode_whose_segments_are_all_too_short_is_rejected(self):
        segments, _, reject = preprocess._repair_episode_rows(_rows("xxVVVxx"), _config())
        self.assertEqual(reject, "ALL_SEGMENTS_BELOW_MIN_PUBLISH_LENGTH")
        self.assertEqual(segments, [])

    def test_publish_gate_is_the_configured_source_frame_count(self):
        gate = _config()["trajectory_quality"]["min_publish_segment_frames"]
        self.assertEqual(gate, 48)
        short, _, reject = preprocess._repair_episode_rows(_rows("V" * (gate - 1)), _config())
        self.assertEqual((short, reject), ([], "ALL_SEGMENTS_BELOW_MIN_PUBLISH_LENGTH"))
        exact, _, reject = preprocess._repair_episode_rows(_rows("V" * gate), _config())
        self.assertIsNone(reject)
        self.assertEqual([len(part) for _, part in exact], [gate])

    def test_a_split_fragment_below_the_gate_is_never_published(self):
        rows = _rows("V" * 60 + "x" * 36 + "V" * 20)
        segments, stats, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        self.assertEqual(stats["dropped_short_segment_count"], 1)
        self.assertEqual([len(part) for _, part in segments], [60])

    def test_published_segments_never_contain_an_unusable_pose(self):
        rows = _rows("xxV" + "V" * 50 + "x" + "V" * 50 + "x" * 40 + "V" * 60 + "xx")
        segments, _, reject = preprocess._repair_episode_rows(rows, _config())
        self.assertIsNone(reject)
        for _, part in segments:
            self.assertTrue(all(row["pose_valid"] for row in part))
            self.assertTrue(all(row["camera_tx"] is not None for row in part))


class HandoffContractTests(unittest.TestCase):
    def test_contract_mirrors_the_configured_reference_values(self):
        config = _config()
        contract = preprocess._handoff_contract(config)
        self.assertEqual(contract, {
            "version": preprocess.HANDOFF_CONTRACT_VERSION,
            "source_hz_reference": 30.0,
            "policy_hz_reference": 10.0,
            "action_horizon_reference": 16,
            "min_publish_segment_frames": 48,
        })
        trajectory = config["trajectory_quality"]
        for key in ("source_hz_reference", "policy_hz_reference",
                    "action_horizon_reference", "min_publish_segment_frames"):
            self.assertEqual(contract[key], trajectory[key], key)

    def test_contract_follows_the_config_so_a_mismatch_is_visible_downstream(self):
        contract = preprocess._handoff_contract(
            _config(trajectory_quality={"action_horizon_reference": 32,
                                        "min_publish_segment_frames": 96})
        )
        self.assertEqual(contract["action_horizon_reference"], 32)
        self.assertEqual(contract["min_publish_segment_frames"], 96)


class ReadyContractTests(unittest.TestCase):
    def test_ready_is_refused_before_output_is_published(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(preprocess.PreprocessError):
                preprocess._publish_ready(Path(temp_dir))
            self.assertFalse((Path(temp_dir) / "READY").exists())

    def _record_publish_order(self, session_dir, output_root):
        """Run one session, capturing what was on disk at each publish step."""
        events = []
        real_commit, real_ready = preprocess._commit_directory, preprocess._publish_ready

        def commit(stage, destination, force):
            events.append(("commit", sorted(path.name for path in stage.iterdir())))
            real_commit(stage, destination, force)

        def ready(final_dir):
            events.append(("ready", sorted(path.name for path in final_dir.iterdir())))
            real_ready(final_dir)

        preprocess._commit_directory, preprocess._publish_ready = commit, ready
        try:
            result = preprocess.preprocess_session(session_dir, output_root, _config())
        finally:
            preprocess._commit_directory, preprocess._publish_ready = real_commit, real_ready
        return result, events

    @unittest.skipUnless(USABLE_SESSION.is_dir(), "raw session fixture not available")
    def test_ready_is_written_last_and_only_after_everything_is_published(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            result, events = self._record_publish_order(USABLE_SESSION, output_root)
            self.assertTrue(result["ready"])
            self.assertEqual([name for name, _ in events], ["commit", "ready"])
            staged, published = events[0][1], events[1][1]
            # Nothing may claim READY before the directory is committed, and the
            # committed directory must be complete when READY is written.
            self.assertNotIn("READY", staged)
            self.assertNotIn("READY", published)
            self.assertIn("session_metadata.json", published)
            self.assertTrue(any(name.startswith("episode_") for name in published))
            session_dir = output_root / USABLE_SESSION.name
            self.assertTrue((session_dir / "READY").is_file())
            expected = preprocess._handoff_contract(_config())
            session_metadata = json.loads((session_dir / "session_metadata.json").read_text())
            self.assertEqual(session_metadata["handoff_contract"], expected)
            for episode_dir in session_dir.glob("episode_*"):
                for name in ("frames.csv", "trajectory.npz", "metadata.json", "quality.json"):
                    self.assertTrue((episode_dir / name).is_file(), f"{episode_dir.name}/{name}")
                # A segment stays self-describing even if it is moved on its own.
                metadata = json.loads((episode_dir / "metadata.json").read_text())
                self.assertEqual(metadata["handoff_contract"], expected)

    @unittest.skipUnless(UNTRACKED_SESSION.is_dir(), "raw session fixture not available")
    def test_a_session_without_a_usable_segment_gets_no_ready_and_no_episode_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            result, events = self._record_publish_order(UNTRACKED_SESSION, output_root)
            self.assertFalse(result["ready"])
            self.assertEqual(result["processing_status"], "REJECTED")
            self.assertEqual([name for name, _ in events], ["commit"])
            session_dir = output_root / UNTRACKED_SESSION.name
            self.assertFalse((session_dir / "READY").exists())
            self.assertEqual(list(session_dir.glob("episode_*")), [])
            rejected = list(session_dir.glob("rejected_episode_*"))
            self.assertEqual(len(rejected), 1)
            # Diagnostics only: nothing that could be mistaken for training input.
            self.assertEqual(
                sorted(path.name for path in rejected[0].iterdir()),
                ["metadata.json", "quality.json"],
            )
            quality = json.loads((rejected[0] / "quality.json").read_text())
            self.assertEqual(quality["reject_reason"], "NO_VALID_TRACKING_POSE")
            self.assertFalse(quality["training_usable"])
            session_metadata = json.loads((session_dir / "session_metadata.json").read_text())
            self.assertEqual(session_metadata["handoff_contract"], preprocess._handoff_contract(_config()))


if __name__ == "__main__":
    unittest.main()
