"""UmiDataset + train-only supervision / ORACLE inputs read from the prep sidecars.

Two opt-in additions, each keyed by the zarr ROW of the sample (the sampler's
indices are replay-buffer rows, i.e. zarr rows, in order):

  timing_labels_path   the labels sidecar (build_label_sidecar.py). Adds
                       batch['aux'] = {'phase': phase_5[r], 'dt': [dt_to_close,
                       dt_to_lift, dt_to_open][r]} at the CURRENT observation row
                       r -- never r-1 and never the action window. Raw seconds;
                       the policy scales them.
  oracle_mask_path     the oracle mask sidecar (build_oracle_masks.py). Adds
                       obs['camera0_target_mask'], obs['camera0_ee_tip_mask']
                       (uint8, T x 224 x 224) and obs['camera0_target_mask_valid']
                       (T,) for BOTH observation rows, sliced with exactly the RGB
                       rule of SequenceSampler (rows {r-1, r}, the first row
                       repeated at an episode start). The normaliser passes them
                       through unchanged (identity).

Neither addition draws randomness. The sidecars are checked against this zarr
(episode_ends + gripper-width fingerprint) and their sha256 is recorded.
"""
import hashlib
import json
import os
import pathlib

import numpy as np
import torch

from diffusion_policy.common.normalize_util import get_image_identity_normalizer
from diffusion_policy.dataset.umi_dataset import UmiDataset

MASK_OBS_KEYS = {"target_mask": "camera0_target_mask", "ee_tip_mask": "camera0_ee_tip_mask"}
VALID_OBS_KEY = "camera0_target_mask_valid"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class UmiAuxDataset(UmiDataset):
    def __init__(self, *args, timing_labels_path=None, oracle_mask_path=None,
                 oracle_mask_names=("target_mask", "ee_tip_mask"), expected_timing_scales_s=None, **kwargs):
        super().__init__(*args, **kwargs)
        n_rows = int(self.replay_buffer.n_steps)
        ends = self.replay_buffer.episode_ends[:]
        grip = self.replay_buffer["robot0_gripper_width"][:].reshape(-1)
        fingerprint = hashlib.sha1(np.asarray(ends).tobytes() + np.asarray(grip, np.float32).tobytes()).hexdigest()
        self.sidecar_provenance = {"zarr_fingerprint_sha1(episode_ends+gripper_width)": fingerprint}
        self.timing = None
        if timing_labels_path:
            lab = np.load(timing_labels_path)
            meta = json.loads(pathlib.Path(str(timing_labels_path).replace(".npz", ".json")).read_text())
            assert meta["zarr_sha1_episode_ends_gripper"] == fingerprint, "labels sidecar is for another zarr"
            assert len(lab["row_phase_5"]) == n_rows
            assert np.array_equal(lab["row_zarr_row_idx"], np.arange(n_rows))
            self.timing = {"phase": lab["row_phase_5"].astype(np.int64),
                           "dt": np.stack([lab["row_dt_to_close_s"], lab["row_dt_to_lift_s"],
                                           lab["row_dt_to_open_s"]], 1).astype(np.float32)}
            self.sidecar_provenance["timing_labels"] = {"path": str(timing_labels_path), "sha256": _sha256(timing_labels_path)}
            # the policy's target scales must be this training split's own P95s
            # (dt of each event over its phase, current rows of the training samples)
            rows = np.array([c for c, _, _, _ in self.sampler.indices])
            ph = self.timing["phase"][rows]
            p95 = [float(np.percentile(self.timing["dt"][rows][ph == e, e].astype(np.float64), 95)) for e in range(3)]
            self.sidecar_provenance["timing_scales_p95_s"] = {"close": p95[0], "lift": p95[1], "open": p95[2],
                                                              "samples": [int((ph == e).sum()) for e in range(3)]}
            if expected_timing_scales_s is not None:
                exp = [float(x) for x in expected_timing_scales_s]
                if any(abs(a_ - b_) > 1e-9 for a_, b_ in zip(p95, exp)):
                    raise RuntimeError(f"timing scales {exp} are not this split's P95 {p95}")
        self.mask_path, self.mask_names = None, tuple(oracle_mask_names)
        if oracle_mask_path:
            import zarr
            z = zarr.open(zarr.ZipStore(str(oracle_mask_path), mode="r"), "r")
            assert z["data/target_mask"].shape[0] == n_rows, "mask sidecar row count differs from the zarr"
            self._valid = z["data/target_mask_valid"][:].astype(bool)
            z.store.close()
            self.mask_path = str(oracle_mask_path)
            self.sidecar_provenance["oracle_masks"] = {"path": str(oracle_mask_path), "sha256": _sha256(oracle_mask_path),
                                                      "names": list(self.mask_names)}
        self._mask_store, self._mask_pid = None, None

    def _masks(self):
        # one ZipStore per process: the DataLoader forks its workers
        if self._mask_store is None or self._mask_pid != os.getpid():
            import zarr
            self._mask_store = zarr.open(zarr.ZipStore(self.mask_path, mode="r"), "r")
            self._mask_pid = os.getpid()
        return self._mask_store

    def _obs_rows(self, current_idx, start_idx):
        key = "camera0_rgb"
        h = self.key_horizon[key]
        ds = self.key_down_sample_steps[key]
        num_valid = min(h, (current_idx - start_idx) // ds + 1)
        slice_start = current_idx - (num_valid - 1) * ds
        rows = list(range(slice_start, current_idx + 1, ds))
        return [rows[0]] * (h - len(rows)) + rows

    def __getitem__(self, idx):
        torch_data = super().__getitem__(idx)
        if self.sampler.ignore_rgb_is_applied:
            return torch_data              # the normaliser pass: low-dim only
        current_idx, start_idx, _, _ = self.sampler.indices[idx]
        if self.timing is not None:
            torch_data["aux"] = {"phase": torch.tensor(self.timing["phase"][current_idx]),
                                 "dt": torch.from_numpy(self.timing["dt"][current_idx].copy())}
        if self.mask_path is not None:
            rows = self._obs_rows(current_idx, start_idx)
            z = self._masks()
            for name in self.mask_names:
                arr = np.stack([z[f"data/{name}"][r] for r in rows]).astype(np.uint8)
                torch_data["obs"][MASK_OBS_KEYS[name]] = torch.from_numpy(arr)
            torch_data["obs"][VALID_OBS_KEY] = torch.from_numpy(self._valid[rows].astype(np.uint8))
        return torch_data

    def get_normalizer(self, **kwargs):
        normalizer = super().get_normalizer(**kwargs)
        if self.mask_path is not None:
            for name in self.mask_names:
                normalizer[MASK_OBS_KEYS[name]] = get_image_identity_normalizer()
            normalizer[VALID_OBS_KEY] = get_image_identity_normalizer()
        return normalizer
