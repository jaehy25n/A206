"""Reader for the EC2 CPU server's ``processed/v1`` layout.

    /srv/processed/v1/
    └─ <session_uuid>/
       └─ <episode_uuid>/
          ├─ rgb_frames/frame_%06d.jpg   <- canonical RGB stream
          ├─ frames.csv                  <- canonical frame table (timestamp + pose)
          ├─ trajectory.npz              <- T_world_camera, used for cross-checking
          ├─ accelerometer.csv / gyroscope.csv / rotation_vector.csv   (unused here)
          ├─ metadata.json
          └─ quality.json

``frames.csv`` is the single source of truth: one row per RGB frame, already
aligned by the CPU layer.  The GPU server never re-does IMU sync or ARCore
timestamp interpolation.

Pose columns are ``camera_t{x,y,z}`` + ``camera_q{x,y,z,w}`` describing
``T_world_camera(t)`` in ARCore's session-local, Y-up world frame.  No axis
remap is applied here -- see ``omx/data/pose_convert.py``.
"""
from __future__ import annotations

import csv
import json
import pathlib
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from omx.data.contract import ContractError, LowDimData
from omx.data.readers import EpisodeReader, IMAGE_EXTS, _natural_key

FRAMES_CSV = "frames.csv"
RGB_DIRNAME = "rgb_frames"
TRAJECTORY_NPZ = "trajectory.npz"

# Column-name candidates, most specific first.  The contract fixes the
# ``camera_*`` names; the rest are best-effort so a small rename upstream does
# not break the pipeline silently.
_COL = {
    "timestamp_ns": ("timestamp_ns", "timestamp_nanos", "t_ns", "frame_timestamp_ns"),
    "timestamp_s": ("timestamp", "timestamp_s", "time_s", "t", "time"),
    "frame_idx": ("frame_idx", "frame_index", "idx", "index", "frame"),
    "rgb_path": ("rgb_path", "image_path", "frame_path", "rgb", "image", "file"),
    "tx": ("camera_tx", "tx", "camera_x", "x"),
    "ty": ("camera_ty", "ty", "camera_y", "y"),
    "tz": ("camera_tz", "tz", "camera_z", "z"),
    "qx": ("camera_qx", "qx", "quat_x"),
    "qy": ("camera_qy", "qy", "quat_y"),
    "qz": ("camera_qz", "qz", "quat_z"),
    "qw": ("camera_qw", "qw", "quat_w"),
    "tracking_state": ("tracking_state", "tracking", "arcore_tracking_state", "state"),
    "pose_valid": ("pose_valid", "valid", "is_valid", "pose_ok"),
    # CPU repair bookkeeping: an interpolated row keeps its ORIGINAL
    # tracking_state, so these two are what tell a repaired row from a broken one
    "pose_interpolated": ("pose_interpolated", "interpolated", "is_interpolated",
                          "pose_is_interpolated"),
    "pose_valid_original": ("pose_valid_original", "pose_valid_orig",
                            "original_pose_valid", "pose_valid_raw"),
    # canonical: physical finger opening width in metres
    "gripper": ("gripper_width_m", "gripper_width", "gripper_m", "gripper",
                "gripper_state", "gripper_normalized", "gripper_open", "grip"),
}

_TRUE = {"1", "true", "t", "yes", "y", "ok", "valid"}
_GOOD_TRACKING = {"tracking", "normal", "ok", "good", "1", "true"}
_BLANK = {"", "none", "null", "na", "n/a", "-"}


def _parse_float_column(rows: List[Dict[str, str]], key: str) -> Tuple[np.ndarray, List[int]]:
    """Parse one csv column to float. Blank / unparseable cells become NaN.

    A blank pose cell is a *contract violation*, not a value -- so it must never
    turn into a number.  NaN propagates into the validity mask, which then
    rejects the frame (and, under the default invalid_policy=error, the whole
    build).  Substituting 0.0 here would silently teleport the end effector to
    the world origin.

    Returns (values, indices_of_unparseable_cells).
    """
    vals = np.empty(len(rows), dtype=np.float64)
    bad: List[int] = []
    for i, r in enumerate(rows):
        raw = r.get(key)
        text = "" if raw is None else str(raw).strip()
        if text.lower() in _BLANK:
            vals[i] = np.nan
            bad.append(i)
            continue
        try:
            vals[i] = float(text)
        except ValueError:
            vals[i] = np.nan
            bad.append(i)
    return vals, bad


def _summarise_bad(bad: List[int], n: int) -> str:
    head = ", ".join(str(i) for i in bad[:6])
    more = f" ... (+{len(bad) - 6} more)" if len(bad) > 6 else ""
    return f"{len(bad)}/{n} rows, at index {head}{more}"


def _pick(header: Sequence[str], logical: str,
          field_map: Optional[Dict[str, object]] = None) -> Optional[str]:
    field_map = field_map or {}
    explicit = field_map.get(logical)
    if isinstance(explicit, str):
        if explicit not in header:
            raise ContractError(
                f"field_map maps {logical!r} -> {explicit!r}, not in frames.csv header "
                f"{list(header)}")
        return explicit
    lower = {h.lower(): h for h in header}
    for cand in _COL.get(logical, ()):
        if cand in lower:
            return lower[cand]
    return None


def _as_bool(v: str) -> bool:
    return str(v).strip().lower() in _TRUE


class ProcessedV1Reader(EpisodeReader):
    """One ``<session>/<episode>/`` directory of the processed_v1 layout."""

    format_name = "processed_v1"

    def __init__(self, path, episode_id: str, rotation_format: str = "quat_xyzw",
                 field_map: Optional[Dict[str, object]] = None):
        super().__init__(path, episode_id, rotation_format="quat_xyzw",
                         field_map=field_map)
        self._rows: Optional[List[Dict[str, str]]] = None
        self._header: Optional[List[str]] = None
        #: the ancestor directory carrying READY; set by discover_processed_v1
        self.session_dir: Optional[pathlib.Path] = None

    # ------------------------------------------------------------------ #
    def _read_csv(self) -> Tuple[List[str], List[Dict[str, str]]]:
        if self._rows is None:
            csv_path = self.path / FRAMES_CSV
            if not csv_path.is_file():
                raise ContractError(f"[{self.episode_id}] missing {csv_path}")
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                self._header = list(reader.fieldnames or [])
                self._rows = list(reader)
            if not self._rows:
                raise ContractError(f"[{self.episode_id}] {csv_path} has no rows")
        return self._header, self._rows

    def read_metadata(self) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for name in ("metadata.json", "quality.json"):
            p = self.path / name
            if p.is_file():
                try:
                    with open(p, "r") as f:
                        out[p.stem] = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    out[p.stem] = {"_error": str(e)}
        return out

    # ------------------------------------------------------------------ #
    def read_lowdim(self) -> LowDimData:
        header, rows = self._read_csv()
        fm = self.field_map

        unparseable: Dict[str, str] = {}
        n = len(rows)

        c_ns = _pick(header, "timestamp_ns", fm)
        c_s = _pick(header, "timestamp_s", fm)
        if c_ns is not None:
            ts, bad = _parse_float_column(rows, c_ns)
            ts = ts * 1e-9
            ts_unit = "ns"
            ts_col = c_ns
        elif c_s is not None:
            ts, bad = _parse_float_column(rows, c_s)
            ts_unit = "s"
            ts_col = c_s
        else:
            raise ContractError(
                f"[{self.episode_id}] frames.csv has no timestamp column; "
                f"header = {header}")
        if bad:
            # A frame with no timestamp cannot be placed on the timeline at all;
            # there is no policy under which that is recoverable.
            raise ContractError(
                f"[{self.episode_id}] frames.csv column {ts_col!r} has blank or "
                f"unparseable values: {_summarise_bad(bad, n)}.\n"
                f"  This is a CPU processed_v1 contract violation. The GPU side "
                f"does not repair it -- fix the CPU output and re-sync.")

        cols = {k: _pick(header, k, fm) for k in ("tx", "ty", "tz", "qx", "qy", "qz", "qw")}
        missing = [k for k, v in cols.items() if v is None]
        if missing:
            raise ContractError(
                f"[{self.episode_id}] frames.csv missing pose columns {missing}; "
                f"header = {header}")

        pose_cols = {}
        for k in ("tx", "ty", "tz", "qx", "qy", "qz", "qw"):
            vals, bad = _parse_float_column(rows, cols[k])
            pose_cols[k] = vals
            if bad:
                unparseable[cols[k]] = _summarise_bad(bad, n)
        pos = np.stack([pose_cols[k] for k in ("tx", "ty", "tz")], axis=-1)
        quat = np.stack([pose_cols[k] for k in ("qx", "qy", "qz", "qw")], axis=-1)

        c_grip = _pick(header, "gripper", fm)
        if c_grip is not None:
            gripper, bad = _parse_float_column(rows, c_grip)
            gripper_source = f"frames.csv:{c_grip}"
            if bad:
                unparseable[c_grip] = _summarise_bad(bad, n)
        else:
            gripper = np.full(n, np.nan, dtype=np.float64)
            gripper_source = "missing"

        extra: Dict[str, np.ndarray] = {}
        c_track = _pick(header, "tracking_state", fm)
        c_valid = _pick(header, "pose_valid", fm)
        if c_track is not None:
            extra["tracking_state"] = np.array([str(r[c_track]) for r in rows], dtype=object)
        if c_valid is not None:
            extra["pose_valid"] = np.array([_as_bool(r[c_valid]) for r in rows], dtype=bool)
        for logical in ("pose_interpolated", "pose_valid_original"):
            c = _pick(header, logical, fm)
            if c is not None:
                extra[logical] = np.array([str(r[c]) for r in rows], dtype=object)

        c_idx = _pick(header, "frame_idx", fm)
        if c_idx is not None:
            fidx, bad = _parse_float_column(rows, c_idx)
            if bad:
                unparseable[c_idx] = _summarise_bad(bad, n)
            extra["frame_idx"] = np.where(np.isfinite(fidx), fidx, -1).astype(np.int64)
        c_rgb = _pick(header, "rgb_path", fm)
        if c_rgb is not None:
            extra["rgb_path"] = np.array([str(r[c_rgb]) for r in rows], dtype=object)

        extra["_timestamp_unit"] = ts_unit
        extra["_gripper_source"] = gripper_source
        extra["_csv_header"] = header
        extra["_unparseable"] = unparseable

        return LowDimData(
            timestamp=ts, position=pos, rotation=quat, gripper=gripper,
            rotation_format="quat_xyzw",
            source=f"{self.episode_id} (frames.csv, {len(rows)} rows)",
            extra=extra)

    # ------------------------------------------------------------------ #
    def frame_paths(self) -> List[pathlib.Path]:
        """RGB paths in frames.csv row order (the contract's alignment guarantee)."""
        header, rows = self._read_csv()
        c_rgb = _pick(header, "rgb_path", self.field_map)
        rgb_dir = self.path / RGB_DIRNAME

        if c_rgb is not None:
            paths = []
            for r in rows:
                raw = str(r[c_rgb]).strip()
                p = pathlib.Path(raw)
                if p.is_absolute():
                    cand = p
                else:
                    cand = self.path / raw
                    if not cand.is_file():
                        cand = rgb_dir / pathlib.Path(raw).name
                if not cand.is_file():
                    raise ContractError(
                        f"[{self.episode_id}] rgb_path {raw!r} does not resolve to a file "
                        f"(tried {self.path / raw} and {rgb_dir / pathlib.Path(raw).name})")
                paths.append(cand)
            return paths

        if not rgb_dir.is_dir():
            raise ContractError(f"[{self.episode_id}] no rgb_path column and no {rgb_dir}")
        files = sorted((p for p in rgb_dir.iterdir()
                        if p.suffix.lower() in IMAGE_EXTS), key=_natural_key)
        if len(files) != len(rows):
            raise ContractError(
                f"[{self.episode_id}] {len(files)} images in {RGB_DIRNAME}/ but "
                f"{len(rows)} rows in frames.csv -- the contract requires them to match")
        return files

    def iter_rgb(self) -> Iterator[np.ndarray]:
        import cv2
        for p in self.frame_paths():
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ContractError(f"[{self.episode_id}] failed to decode {p}")
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def read_rgb_indices(self, indices) -> Iterator[np.ndarray]:
        """Decode only the requested rows -- never the whole episode."""
        import cv2
        paths = self.frame_paths()
        for i in indices:
            p = paths[int(i)]
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ContractError(f"[{self.episode_id}] failed to decode {p}")
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def n_frames(self) -> int:
        if self._n_frames is None:
            self._n_frames = len(self._read_csv()[1])
        return self._n_frames

    # ------------------------------------------------------------------ #
    def verify_against_trajectory_npz(self, atol: float = 1e-4,
                                      T_camera_ee=None,
                                      pose_frame: str = "episode_start") -> Dict[str, object]:
        """Independently re-derive the pose chain and compare with trajectory.npz.

        ``frames.csv`` is what the GPU consumes; ``trajectory.npz`` is what the CPU
        computed. They are produced by different code paths, so agreeing to machine
        precision is real evidence that the conventions match -- quaternion order,
        units, world frame, and the episode-relative step.

        Arrays are matched BY NAME. An earlier version took the first [N,4,4] array
        it found, which is ``T_episode0_EE`` alphabetically, and then compared it
        against ``T_world_camera`` -- reporting a mismatch on healthy data.
        """
        p = self.path / TRAJECTORY_NPZ
        if not p.is_file():
            return {"checked": False, "reason": f"{TRAJECTORY_NPZ} not present"}

        import numpy as _np
        from omx.data import pose_convert as pc

        low = self.read_lowdim()
        n = low.n_frames
        T_cam = pc.build_pose_matrices(low.position, low.rotation, "quat_xyzw")
        T_ce = _np.eye(4) if T_camera_ee is None else _np.asarray(T_camera_ee,
                                                                  dtype=_np.float64)
        T_ee = T_cam @ T_ce[None, ...]
        T_rel = _np.linalg.inv(T_ee[0])[None, ...] @ T_ee

        checks: Dict[str, object] = {}
        notes: List[str] = []
        try:
            with _np.load(p, allow_pickle=False) as z:
                keys = list(z.files)

                def cmp(name, mine):
                    if name not in keys:
                        return
                    theirs = _np.asarray(z[name], dtype=_np.float64)
                    if theirs.shape != mine.shape:
                        checks[name] = {"ok": False,
                                        "reason": f"shape {theirs.shape} != {mine.shape}"}
                        return
                    d = float(_np.max(_np.abs(theirs - mine)))
                    checks[name] = {"ok": bool(d <= atol), "max_abs_diff": d}

                cmp("T_world_camera", T_cam)
                cmp("T_world_EE", T_ee)
                cmp("T_episode0_EE", T_rel)

                # The contract puts T_camera_EE application on the GPU side, so the
                # CPU's copy should be identity. A non-identity one on both sides
                # would apply the transform twice.
                if "T_camera_EE" in keys:
                    cpu_ce = _np.asarray(z["T_camera_EE"], dtype=_np.float64).reshape(4, 4)
                    d = float(_np.max(_np.abs(cpu_ce - T_ce)))
                    same = d <= atol
                    cpu_identity = bool(_np.allclose(cpu_ce, _np.eye(4), atol=1e-9))
                    gpu_identity = bool(_np.allclose(T_ce, _np.eye(4), atol=1e-9))
                    checks["T_camera_EE"] = {"ok": same or cpu_identity,
                                             "max_abs_diff": d,
                                             "cpu_identity": cpu_identity,
                                             "gpu_identity": gpu_identity}
                    if not cpu_identity and not gpu_identity and not same:
                        notes.append(
                            "trajectory.npz carries a non-identity T_camera_EE and the "
                            "collector config has a different non-identity one. The "
                            "contract applies this transform on the GPU side only; "
                            "check that it is not being applied twice.")

                # provenance columns should say the same thing in both files
                for name, col in (("pose_valid", "pose_valid"),
                                  ("pose_interpolated", "pose_interpolated"),
                                  ("pose_valid_original", "pose_valid_original")):
                    if name not in keys or col not in low.extra:
                        continue
                    from omx.data.validity import as_bool_array
                    mine_b = _np.array([bool(v) for v in
                                        as_bool_array(low.extra[col], default=False)])
                    theirs_b = _np.asarray(z[name]).astype(bool).reshape(-1)
                    if theirs_b.shape[0] != n:
                        checks[name] = {"ok": False,
                                        "reason": f"length {theirs_b.shape[0]} != {n}"}
                        continue
                    n_diff = int((mine_b != theirs_b).sum())
                    checks[name] = {"ok": n_diff == 0, "n_differing_rows": n_diff}
        except (OSError, ValueError) as e:
            return {"checked": False, "reason": f"unreadable: {e}"}

        if not checks:
            return {"checked": False,
                    "reason": f"no comparable arrays in {TRAJECTORY_NPZ}"}
        failed = {k: v for k, v in checks.items() if not v.get("ok")}
        return {"checked": True, "ok": not failed, "atol": atol,
                "checks": checks, "failed": failed, "notes": notes}


def is_processed_v1_episode(path: pathlib.Path) -> bool:
    return path.is_dir() and (path / FRAMES_CSV).is_file()


READY_MARKER = "READY"

#: Directory-name prefixes the CPU uses for episodes it threw away. They may hold
#: a complete-looking training layout, so exclude them explicitly on the GPU side
#: rather than relying on the CPU never writing frames.csv into them. Checked on
#: EVERY path component, so <session>/rejected_episode_x/<ep>/ is excluded too.
EXCLUDED_EPISODE_PREFIXES = ("rejected_episode", "failed_episode",
                             "rejected_", "failed_")


def _is_excluded(rel: pathlib.Path) -> bool:
    for part in rel.parts:
        low = part.lower()
        if low.startswith(".") or low.startswith(EXCLUDED_EPISODE_PREFIXES):
            return True
        if low in ("rejected", "failed", "quarantine", "discarded"):
            return True
    return False


def _ready_session_of(episode_dir: pathlib.Path,
                      root: pathlib.Path) -> Optional[pathlib.Path]:
    """The nearest ancestor of ``episode_dir`` (up to ``root``) carrying READY."""
    cur = episode_dir
    while True:
        if (cur / READY_MARKER).is_file():
            return cur
        if cur == root or cur.parent == cur:
            return None
        cur = cur.parent


def discover_processed_v1(roots: Sequence[str], max_depth: int = 4,
                          field_map: Optional[Dict[str, object]] = None,
                          pattern: Optional[str] = None,
                          require_ready: bool = True,
                          skipped: Optional[List[str]] = None,
                          excluded: Optional[List[str]] = None
                          ) -> List[ProcessedV1Reader]:
    """Walk ``<root>/<session>/<episode>/`` (any depth up to ``max_depth``).

    Two rules come from the CPU->GPU handoff contract:

    * dot-directories are never descended into -- ``.incoming/`` holds transfers
      still in flight, ``.logs/`` holds sync logs, ``.superseded/`` holds replaced
      copies;
    * ``rejected_episode_*`` / ``failed_episode_*`` (and bare ``rejected/``,
      ``failed/``) are excluded by name. The CPU rejects unusable episodes, and
      those directories can still contain a complete-looking layout;
    * a session is only used once it carries a ``READY`` marker, which the CPU
      side writes last, after preprocessing and validation succeed.  A session
      directory can exist while it is still being written.

    Episodes come back in a deterministic natural sort of
    ``<session>__<episode>`` so that dataset variants built for the section 25
    A/B comparison always share the same episode ordering and train/val split.
    """
    import os
    import re

    found: Dict[str, ProcessedV1Reader] = {}
    skipped = skipped if skipped is not None else []
    excluded = excluded if excluded is not None else []
    for root in roots:
        root = pathlib.Path(os.path.expanduser(str(root))).absolute()
        if not root.exists():
            raise FileNotFoundError(f"input path does not exist: {root}")

        if is_processed_v1_episode(root):
            candidates = [root]          # pointed straight at one episode
        else:
            candidates = []
            for dirpath, dirnames, filenames in os.walk(root):
                # never descend into .incoming / .logs / .superseded / any dot dir,
                # nor into anything the CPU marked as rejected or failed
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".")
                    and not d.lower().startswith(EXCLUDED_EPISODE_PREFIXES)
                    and d.lower() not in ("rejected", "failed", "quarantine", "discarded")]
                rel_depth = len(pathlib.Path(dirpath).relative_to(root).parts)
                if rel_depth > max_depth:
                    dirnames[:] = []
                    continue
                if FRAMES_CSV in filenames:
                    candidates.append(pathlib.Path(dirpath))
                    dirnames[:] = []           # an episode never nests another
            candidates.sort(key=_natural_key)

        for c in candidates:
            rel = c.relative_to(root) if c != root else pathlib.Path(c.name)
            if c != root and _is_excluded(rel):
                excluded.append("__".join(rel.parts))
                continue
            episode_id = "__".join(rel.parts) if rel.parts else c.name
            if pattern and not re.search(pattern, episode_id):
                continue
            session_dir = _ready_session_of(c, root)
            if require_ready and c != root:
                if session_dir is None:
                    skipped.append(episode_id)
                    continue
            key = str(c.resolve())
            if key in found:
                continue
            reader = ProcessedV1Reader(c, episode_id, field_map=field_map)
            reader.session_dir = session_dir or c.parent
            found[key] = reader

    readers = list(found.values())
    readers.sort(key=lambda r: _natural_key(pathlib.Path(r.episode_id)))
    return readers
