"""Pluggable readers for the EC2 *processed* episode format.

The exact on-disk layout the CPU server emits is not frozen yet, so the reader
layer is the only place that needs to change when it is.  Four shapes are
supported out of the box and auto-detected:

    npz         one ``<episode>.npz`` per episode (rgb + lowdim in one file)
    hdf5        one ``<episode>.h5`` / ``.hdf5`` per episode
    video_dir   ``<episode>/video.mp4`` + a ``.json`` / ``.csv`` / ``.npz`` sidecar
    frames_dir  ``<episode>/frames/*.png|jpg`` + a ``.json`` / ``.csv`` / ``.npz`` sidecar

Field names are resolved through ``contract.FIELD_ALIASES``; anything unusual can
be pinned explicitly with ``field_map`` in the collector config, e.g.

    field_map:
      timestamp: frame_t
      position:  [tx, ty, tz]
      rotation:  [qx, qy, qz, qw]
      gripper:   grip_norm
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from omx.data.contract import FIELD_ALIASES, ContractError, LowDimData

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v")
SIDECAR_EXTS = (".json", ".csv", ".npz", ".npy")

# column-name groups used when the lowdim sidecar is a flat table (csv / records)
_COLUMN_GROUPS: Dict[str, Sequence[Sequence[str]]] = {
    "position": (
        ("x", "y", "z"), ("px", "py", "pz"), ("tx", "ty", "tz"),
        ("pos_x", "pos_y", "pos_z"), ("position_x", "position_y", "position_z"),
        ("ee_x", "ee_y", "ee_z"), ("cam_x", "cam_y", "cam_z"),
        ("translation_x", "translation_y", "translation_z"),
    ),
    "rotation_quat": (
        ("qx", "qy", "qz", "qw"), ("quat_x", "quat_y", "quat_z", "quat_w"),
        ("rot_x", "rot_y", "rot_z", "rot_w"),
        ("orientation_x", "orientation_y", "orientation_z", "orientation_w"),
    ),
    "rotation_rotvec": (
        ("rx", "ry", "rz"), ("rotvec_x", "rotvec_y", "rotvec_z"),
        ("axis_angle_x", "axis_angle_y", "axis_angle_z"),
    ),
}


def _natural_key(p: pathlib.Path):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.name)]


def _resolve(keys: Sequence[str], logical: str,
             field_map: Optional[Dict[str, object]] = None) -> Optional[str]:
    """Find the physical key for a logical field name."""
    field_map = field_map or {}
    explicit = field_map.get(logical)
    if isinstance(explicit, str):
        if explicit not in keys:
            raise ContractError(
                f"field_map maps {logical!r} -> {explicit!r} but that key is not "
                f"present; available keys: {sorted(keys)}")
        return explicit
    lower = {str(k).lower(): k for k in keys}
    for alias in FIELD_ALIASES.get(logical, []):
        if alias.lower() in lower:
            return lower[alias.lower()]
    return None


def _columns(table: Dict[str, np.ndarray], logical: str,
             field_map: Optional[Dict[str, object]] = None
             ) -> Tuple[Optional[np.ndarray], Optional[str]]:
    """Pull a vector field out of a flat table, returning (array, rotation_format)."""
    field_map = field_map or {}
    explicit = field_map.get(logical)
    if isinstance(explicit, (list, tuple)):
        missing = [c for c in explicit if c not in table]
        if missing:
            raise ContractError(
                f"field_map maps {logical!r} -> {list(explicit)} but {missing} "
                f"are missing; available columns: {sorted(table)}")
        arr = np.stack([np.asarray(table[c], dtype=np.float64) for c in explicit], -1)
        fmt = None
        if logical == "rotation":
            fmt = {3: "rotvec", 4: "quat_xyzw", 9: "matrix"}.get(len(explicit))
        return arr, fmt

    key = _resolve(list(table), logical, field_map)
    if key is not None:
        return np.asarray(table[key], dtype=np.float64), None

    lower = {str(k).lower(): k for k in table}
    groups = ()
    if logical == "position":
        groups = (("position", g) for g in _COLUMN_GROUPS["position"])
    elif logical == "rotation":
        groups = ([("quat_xyzw", g) for g in _COLUMN_GROUPS["rotation_quat"]] +
                  [("rotvec", g) for g in _COLUMN_GROUPS["rotation_rotvec"]])
    for fmt, group in groups:
        if all(c in lower for c in group):
            arr = np.stack([np.asarray(table[lower[c]], dtype=np.float64)
                            for c in group], -1)
            return arr, (None if logical == "position" else fmt)
    return None, None


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
class EpisodeReader:
    """Base class.  Subclasses provide lowdim and rgb access separately so the
    converter can write all lowdim first (cheap) and then stream rgb in parallel."""

    format_name = "base"

    def __init__(self, path: pathlib.Path, episode_id: str,
                 rotation_format: str = "quat_xyzw",
                 field_map: Optional[Dict[str, object]] = None):
        self.path = pathlib.Path(path)
        self.episode_id = episode_id
        self.rotation_format = rotation_format
        self.field_map = field_map or {}
        self._n_frames: Optional[int] = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.episode_id} {self.path}>"

    def read_lowdim(self) -> LowDimData:
        raise NotImplementedError

    def iter_rgb(self) -> Iterator[np.ndarray]:
        raise NotImplementedError

    def n_frames(self) -> int:
        if self._n_frames is None:
            self._n_frames = self.read_lowdim().n_frames
        return self._n_frames

    def read_rgb_indices(self, indices: Sequence[int]) -> Iterator[np.ndarray]:
        """Yield only the frames at ``indices`` (ascending), in that order.

        The generic implementation streams the whole episode and picks; readers
        backed by individual files override it to touch only what is needed.
        """
        wanted = {int(i) for i in indices}
        if not wanted:
            return
        last = max(wanted)
        for i, frame in enumerate(self.iter_rgb()):
            if i in wanted:
                yield frame
            if i >= last:
                break

    def probe_rgb_shape(self) -> Tuple[int, int]:
        for frame in self.iter_rgb():
            return int(frame.shape[0]), int(frame.shape[1])
        raise ContractError(f"[{self.episode_id}] no rgb frames")

    # shared helper -------------------------------------------------------- #
    def _lowdim_from_table(self, table: Dict[str, np.ndarray], source: str) -> LowDimData:
        ts_key = _resolve(list(table), "timestamp", self.field_map)
        position, _ = _columns(table, "position", self.field_map)
        rotation, detected_fmt = _columns(table, "rotation", self.field_map)
        gripper, _ = _columns(table, "gripper", self.field_map)

        if rotation is None:
            pose_key = _resolve(list(table), "pose_matrix", self.field_map)
            if pose_key is not None:
                pose = np.asarray(table[pose_key], dtype=np.float64)
                if pose.ndim == 3 and pose.shape[-2:] == (4, 4):
                    rotation, detected_fmt = pose, "matrix4x4"
                    position = pose[:, :3, 3] if position is None else position
                elif pose.ndim == 2 and pose.shape[-1] == 7:
                    position = pose[:, :3] if position is None else position
                    rotation, detected_fmt = pose[:, 3:7], "quat_xyzw"
                elif pose.ndim == 2 and pose.shape[-1] == 6:
                    position = pose[:, :3] if position is None else position
                    rotation, detected_fmt = pose[:, 3:6], "rotvec"

        missing = [name for name, v in
                   (("timestamp", ts_key), ("position", position),
                    ("rotation", rotation), ("gripper", gripper)) if v is None]
        if missing:
            raise ContractError(
                f"[{self.episode_id}] could not resolve {missing} in {source}.\n"
                f"  available keys: {sorted(table)}\n"
                f"  fix by adding a 'field_map' entry to the collector config.")

        ts = np.asarray(table[ts_key], dtype=np.float64).reshape(-1)
        gripper = np.asarray(gripper, dtype=np.float64).reshape(-1) \
            if np.asarray(gripper).ndim <= 1 else np.asarray(gripper)[..., 0]

        fmt = detected_fmt or self.rotation_format
        if detected_fmt is None:
            rot = np.asarray(rotation)
            if rot.ndim == 3 and rot.shape[-2:] == (4, 4):
                fmt = "matrix4x4"
            elif rot.ndim == 3 and rot.shape[-2:] == (3, 3):
                fmt = "matrix"

        return LowDimData(
            timestamp=ts,
            position=np.asarray(position, dtype=np.float64),
            rotation=np.asarray(rotation, dtype=np.float64),
            gripper=gripper,
            rotation_format=fmt,
            source=f"{self.episode_id} ({source})",
        )


class NpzReader(EpisodeReader):
    format_name = "npz"

    def _table(self) -> Dict[str, np.ndarray]:
        with np.load(self.path, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}

    def read_lowdim(self) -> LowDimData:
        table = {k: v for k, v in self._table().items()}
        rgb_key = _resolve(list(table), "rgb", self.field_map)
        table.pop(rgb_key, None)
        return self._lowdim_from_table(table, str(self.path.name))

    def iter_rgb(self) -> Iterator[np.ndarray]:
        with np.load(self.path, allow_pickle=False) as z:
            rgb_key = _resolve(list(z.files), "rgb", self.field_map)
            if rgb_key is None:
                raise ContractError(
                    f"[{self.episode_id}] no rgb array in {self.path.name}; "
                    f"keys: {sorted(z.files)}")
            rgb = z[rgb_key]
            for i in range(rgb.shape[0]):
                yield np.ascontiguousarray(rgb[i])


class Hdf5Reader(EpisodeReader):
    format_name = "hdf5"

    def _open(self):
        import h5py  # imported lazily: only this reader needs it
        return h5py.File(self.path, "r")

    @staticmethod
    def _flatten(node, prefix="") -> Dict[str, object]:
        import h5py
        out = {}
        for key, value in node.items():
            name = f"{prefix}{key}"
            if isinstance(value, h5py.Group):
                out.update(Hdf5Reader._flatten(value, prefix=f"{name}/"))
            else:
                out[name] = value
                out.setdefault(key, value)
        return out

    def read_lowdim(self) -> LowDimData:
        with self._open() as f:
            flat = self._flatten(f)
            rgb_key = _resolve(list(flat), "rgb", self.field_map)
            table = {k: np.asarray(v) for k, v in flat.items() if k != rgb_key}
        return self._lowdim_from_table(table, str(self.path.name))

    def iter_rgb(self) -> Iterator[np.ndarray]:
        with self._open() as f:
            flat = self._flatten(f)
            rgb_key = _resolve(list(flat), "rgb", self.field_map)
            if rgb_key is None:
                raise ContractError(
                    f"[{self.episode_id}] no rgb dataset in {self.path.name}; "
                    f"keys: {sorted(flat)}")
            dset = flat[rgb_key]
            for i in range(dset.shape[0]):
                yield np.ascontiguousarray(dset[i])


class _SidecarMixin(EpisodeReader):
    """Lowdim comes from a json / csv / npz sidecar inside the episode directory."""

    def _sidecar_path(self) -> pathlib.Path:
        explicit = self.field_map.get("_sidecar")
        if isinstance(explicit, str):
            return self.path / explicit
        candidates = [p for p in sorted(self.path.iterdir())
                      if p.suffix.lower() in SIDECAR_EXTS]
        # prefer names that look like trajectory data over generic metadata
        def rank(p: pathlib.Path) -> int:
            n = p.stem.lower()
            if any(t in n for t in ("traj", "pose", "lowdim", "state", "data", "ee")):
                return 0
            if n in ("meta", "metadata", "info", "config"):
                return 2
            return 1
        if not candidates:
            raise ContractError(
                f"[{self.episode_id}] no lowdim sidecar (.json/.csv/.npz) in {self.path}")
        candidates.sort(key=lambda p: (rank(p), p.name))
        return candidates[0]

    def read_lowdim(self) -> LowDimData:
        p = self._sidecar_path()
        table = _load_table(p)
        return self._lowdim_from_table(table, p.name)


class VideoDirReader(_SidecarMixin):
    format_name = "video_dir"

    def _video_path(self) -> pathlib.Path:
        vids = [p for p in sorted(self.path.iterdir())
                if p.suffix.lower() in VIDEO_EXTS]
        if not vids:
            raise ContractError(f"[{self.episode_id}] no video file in {self.path}")
        if len(vids) > 1:
            raise ContractError(
                f"[{self.episode_id}] {len(vids)} video files in {self.path}; "
                f"expected exactly one (single-camera baseline): "
                f"{[v.name for v in vids]}")
        return vids[0]

    def iter_rgb(self) -> Iterator[np.ndarray]:
        import av
        with av.open(str(self._video_path())) as container:
            stream = container.streams.video[0]
            stream.thread_count = 1
            for frame in container.decode(stream):
                yield frame.to_ndarray(format="rgb24")


class FramesDirReader(_SidecarMixin):
    format_name = "frames_dir"

    def _frame_paths(self) -> List[pathlib.Path]:
        roots = [self.path / n for n in ("frames", "images", "rgb", "color")]
        roots = [r for r in roots if r.is_dir()] or [self.path]
        files: List[pathlib.Path] = []
        for r in roots:
            files.extend(p for p in r.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        files.sort(key=_natural_key)
        if not files:
            raise ContractError(f"[{self.episode_id}] no image files under {self.path}")
        return files

    def iter_rgb(self) -> Iterator[np.ndarray]:
        import cv2
        for p in self._frame_paths():
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ContractError(f"[{self.episode_id}] failed to read {p}")
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def read_rgb_indices(self, indices: Sequence[int]) -> Iterator[np.ndarray]:
        import cv2
        paths = self._frame_paths()
        for i in indices:
            bgr = cv2.imread(str(paths[int(i)]), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ContractError(f"[{self.episode_id}] failed to read {paths[int(i)]}")
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


READERS = {
    "npz": NpzReader,
    "hdf5": Hdf5Reader,
    "video_dir": VideoDirReader,
    "frames_dir": FramesDirReader,
}


# --------------------------------------------------------------------------- #
# sidecar table loading
# --------------------------------------------------------------------------- #
def _load_table(path: pathlib.Path) -> Dict[str, np.ndarray]:
    suffix = path.suffix.lower()
    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}
    if suffix == ".json":
        with open(path, "r") as f:
            raw = json.load(f)
        return _records_to_table(raw)
    if suffix == ".csv":
        with open(path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise ContractError(f"{path} is empty")
        return _records_to_table(rows)
    raise ContractError(f"unsupported sidecar format: {path}")


def _records_to_table(raw) -> Dict[str, np.ndarray]:
    """Accept arrays-of-fields, list-of-records, or {'frames': [records]}."""
    if isinstance(raw, dict):
        for container in ("frames", "records", "data", "episode", "steps"):
            if container in raw and isinstance(raw[container], list):
                table = _records_to_table(raw[container])
                # keep scalar top-level metadata reachable too
                for k, v in raw.items():
                    if k != container and not isinstance(v, (list, dict)):
                        table.setdefault(k, v)
                return table
        return {k: _to_array(v) for k, v in raw.items()}

    if isinstance(raw, list):
        if not raw:
            raise ContractError("empty record list")
        if not isinstance(raw[0], dict):
            raise ContractError(
                f"expected a list of records, got list of {type(raw[0]).__name__}")
        keys = list(raw[0].keys())
        return {k: _to_array([r.get(k) for r in raw]) for k in keys}

    raise ContractError(f"unsupported json/csv structure: {type(raw).__name__}")


def _to_array(v):
    try:
        arr = np.asarray(v, dtype=np.float64)
    except (TypeError, ValueError):
        return np.asarray(v, dtype=object)
    return arr


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #
def _classify_dir(path: pathlib.Path) -> Optional[str]:
    if not path.is_dir():
        return None
    entries = list(path.iterdir())
    has_video = any(p.suffix.lower() in VIDEO_EXTS for p in entries)
    has_sidecar = any(p.suffix.lower() in SIDECAR_EXTS for p in entries)
    frame_dirs = [p for p in entries
                  if p.is_dir() and p.name.lower() in ("frames", "images", "rgb", "color")]
    has_images = (any(p.suffix.lower() in IMAGE_EXTS for p in entries)
                  or any(any(q.suffix.lower() in IMAGE_EXTS for q in d.iterdir())
                         for d in frame_dirs))
    if has_video and has_sidecar:
        return "video_dir"
    if has_images and has_sidecar:
        return "frames_dir"
    return None


def open_episode(path, episode_id: Optional[str] = None,
                 input_format: str = "auto",
                 rotation_format: str = "quat_xyzw",
                 field_map: Optional[Dict[str, object]] = None) -> EpisodeReader:
    path = pathlib.Path(path)
    episode_id = episode_id or path.stem
    if input_format != "auto":
        if input_format not in READERS:
            raise ValueError(
                f"unknown input_format {input_format!r}; "
                f"expected 'auto' or one of {sorted(READERS)}")
        detected = input_format
    else:
        if path.is_file():
            ext = path.suffix.lower()
            detected = "npz" if ext == ".npz" else "hdf5" if ext in (".h5", ".hdf5") else None
        else:
            detected = _classify_dir(path)
        if detected is None:
            raise ContractError(
                f"could not auto-detect the processed-episode format of {path}. "
                f"Pass --input-format explicitly (one of {sorted(READERS)}).")
    return READERS[detected](path, episode_id, rotation_format=rotation_format,
                             field_map=field_map)


def discover_episodes(roots: Sequence[str], input_format: str = "auto",
                      rotation_format: str = "quat_xyzw",
                      field_map: Optional[Dict[str, object]] = None,
                      pattern: Optional[str] = None) -> List[EpisodeReader]:
    """Find every episode under one or more session roots, sorted deterministically.

    Ordering matters: handoff doc section 25 requires episode ordering to stay
    identical across A/B dataset variants, so it is a plain natural sort of the
    episode id and never depends on filesystem order.
    """
    found: List[EpisodeReader] = []
    seen = set()
    for root in roots:
        root = pathlib.Path(os.path.expanduser(root)).absolute()
        if not root.exists():
            raise FileNotFoundError(f"input path does not exist: {root}")

        candidates: List[pathlib.Path] = []
        if root.is_file():
            candidates = [root]
        elif open_episode_is_self(root, input_format):
            candidates = [root]
        else:
            for p in sorted(root.iterdir(), key=_natural_key):
                if pattern and not re.search(pattern, p.name):
                    continue
                if p.is_file() and p.suffix.lower() in (".npz", ".h5", ".hdf5"):
                    candidates.append(p)
                elif p.is_dir() and (_classify_dir(p) is not None or input_format != "auto"):
                    candidates.append(p)

        for c in candidates:
            key = str(c.resolve())
            if key in seen:
                continue
            seen.add(key)
            episode_id = f"{root.name}__{c.stem}" if root.is_dir() and c != root else c.stem
            found.append(open_episode(c, episode_id=episode_id,
                                      input_format=input_format,
                                      rotation_format=rotation_format,
                                      field_map=field_map))
    found.sort(key=lambda r: _natural_key(pathlib.Path(r.episode_id)))
    return found


def open_episode_is_self(path: pathlib.Path, input_format: str) -> bool:
    """True when ``path`` is itself one episode rather than a directory of them."""
    if input_format in ("video_dir", "frames_dir"):
        try:
            return _classify_dir(path) == input_format
        except OSError:
            return False
    return input_format == "auto" and _classify_dir(path) is not None
