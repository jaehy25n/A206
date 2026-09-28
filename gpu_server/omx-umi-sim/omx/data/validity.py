"""Single source of truth for "is this frame usable?".

Both the strict inspector (``scripts/inspect_synced_processed.py``) and the
converter (``omx/data/build.py``) import from here, so a dataset can never
inspect PASS and then build FAIL, or the reverse.

Effective validity (CPU->GPU handoff contract, GPU-1):

    numeric_pose_valid = position finite
                         and quaternion finite
                         and quaternion norm within tolerance

    tracking_ok        = tracking_state in usable states
                         or pose_interpolated is True

    effective_valid    = pose_valid and numeric_pose_valid and tracking_ok

The ``pose_interpolated`` clause is what makes CPU-side gap interpolation work:
an interpolated row keeps its ORIGINAL ``tracking_state`` (PAUSED / MISSING) for
provenance, so judging on ``tracking_state`` alone would reject exactly the rows
the CPU just repaired.

    PAUSED + pose_interpolated=false  -> FAIL
    PAUSED + pose_interpolated=true + numerically valid pose -> PASS
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

#: tracking_state values that count as a direct, trusted ARCore measurement.
USABLE_TRACKING_STATES: Sequence[str] = (
    "tracking", "normal", "ok", "good", "true", "1")

QUAT_NORM_TOL = 1e-2

_TRUE_TOKENS = {"1", "true", "t", "yes", "y", "ok", "valid"}
_FALSE_TOKENS = {"0", "false", "f", "no", "n", "invalid"}


def as_bool_array(values, default: Optional[bool] = None) -> Optional[np.ndarray]:
    """Parse a column of truthy strings/numbers. Unknown tokens -> ``default``."""
    if values is None:
        return None
    arr = np.asarray(values)
    out = np.empty(arr.shape[0], dtype=object)
    for i, v in enumerate(arr):
        if isinstance(v, (bool, np.bool_)):
            out[i] = bool(v)
            continue
        if isinstance(v, (int, float, np.integer, np.floating)):
            out[i] = bool(v) if np.isfinite(v) else default
            continue
        text = str(v).strip().lower()
        if text in _TRUE_TOKENS:
            out[i] = True
        elif text in _FALSE_TOKENS:
            out[i] = False
        else:
            out[i] = default
    return out


def _to_mask(obj_arr: Optional[np.ndarray], when_missing: bool) -> np.ndarray:
    """object array of True/False/None -> bool mask, None becoming ``when_missing``."""
    if obj_arr is None:
        raise ValueError("cannot build a mask from None")
    return np.array([when_missing if v is None else bool(v) for v in obj_arr], dtype=bool)


@dataclass
class ValidityResult:
    effective_valid: np.ndarray            # [N] bool -- the only mask callers should use
    numeric_pose_valid: np.ndarray         # [N] bool
    tracking_ok: np.ndarray                # [N] bool
    pose_valid: np.ndarray                 # [N] bool
    interpolated: np.ndarray               # [N] bool
    counts: Dict[str, int] = field(default_factory=dict)
    detail: Dict[str, object] = field(default_factory=dict)

    @property
    def n_invalid(self) -> int:
        return int((~self.effective_valid).sum())

    def summary_lines(self) -> List[str]:
        out = []
        for k, v in self.counts.items():
            if v:
                extra = self.detail.get(k)
                out.append(f"{k}={v}" + (f" ({extra})" if extra else ""))
        return out


def _rows(mask: np.ndarray, limit: int = 6) -> str:
    idx = np.flatnonzero(mask).tolist()
    head = ", ".join(str(i) for i in idx[:limit])
    more = f" ... (+{len(idx) - limit} more)" if len(idx) > limit else ""
    return f"rows {head}{more}"


def compute_effective_pose_validity(
    position: np.ndarray,
    rotation: np.ndarray,
    rotation_format: str,
    pose_valid=None,
    tracking_state=None,
    pose_interpolated=None,
    usable_tracking_states: Sequence[str] = USABLE_TRACKING_STATES,
    quat_norm_tol: float = QUAT_NORM_TOL,
    use_pose_valid: bool = True,
    use_tracking_state: bool = True,
) -> ValidityResult:
    """Apply the contract above. Columns that are absent are treated as passing.

    A missing column is not silently forgiven for *numeric* validity: NaN, which
    is what the reader produces for a blank cell, always fails.
    """
    n = int(np.asarray(position).shape[0])
    counts: Dict[str, int] = {}
    detail: Dict[str, object] = {}

    # ---- numeric ---------------------------------------------------------- #
    pos = np.asarray(position, dtype=np.float64)
    rot = np.asarray(rotation, dtype=np.float64).reshape(n, -1)
    pos_finite = np.all(np.isfinite(pos), axis=-1)
    rot_finite = np.all(np.isfinite(rot), axis=-1)

    quat_ok = np.ones(n, dtype=bool)
    if rotation_format in ("quat_xyzw", "quat_wxyz"):
        norms = np.full(n, np.nan)
        norms[rot_finite] = np.linalg.norm(rot[rot_finite], axis=-1)
        quat_ok = np.isfinite(norms) & (np.abs(norms - 1.0) <= quat_norm_tol)
        quat_ok |= ~rot_finite          # non-finite already counted by rot_finite

    numeric = pos_finite & rot_finite & quat_ok
    if not np.all(pos_finite):
        counts["non_finite_position"] = int((~pos_finite).sum())
        detail["non_finite_position"] = _rows(~pos_finite)
    if not np.all(rot_finite):
        counts["non_finite_rotation"] = int((~rot_finite).sum())
        detail["non_finite_rotation"] = _rows(~rot_finite)
    bad_norm = rot_finite & ~quat_ok
    if np.any(bad_norm):
        counts["quaternion_norm"] = int(bad_norm.sum())
        detail["quaternion_norm"] = _rows(bad_norm)

    # ---- interpolation flag ----------------------------------------------- #
    interp_obj = as_bool_array(pose_interpolated, default=False)
    interp = (_to_mask(interp_obj, when_missing=False) if interp_obj is not None
              else np.zeros(n, dtype=bool))
    if np.any(interp):
        counts["interpolated_by_cpu"] = int(interp.sum())

    # ---- pose_valid -------------------------------------------------------- #
    if use_pose_valid and pose_valid is not None:
        pv_obj = as_bool_array(pose_valid, default=True)
        pv = _to_mask(pv_obj, when_missing=True)
        unknown = np.array([v is None for v in pv_obj], dtype=bool)
        if np.any(unknown):
            counts["pose_valid_unparseable"] = int(unknown.sum())
            detail["pose_valid_unparseable"] = _rows(unknown)
    else:
        pv = np.ones(n, dtype=bool)
    if not np.all(pv):
        counts["pose_valid_false"] = int((~pv).sum())
        detail["pose_valid_false"] = _rows(~pv)

    # ---- tracking ---------------------------------------------------------- #
    if use_tracking_state and tracking_state is not None:
        good = {str(s).strip().lower() for s in usable_tracking_states}
        ts = np.array([str(s).strip().lower() for s in np.asarray(tracking_state)])
        direct = np.isin(ts, list(good))
        # An interpolated row keeps its original tracking_state on purpose.
        tracking_ok = direct | interp
        not_direct = ~direct
        if np.any(not_direct & ~interp):
            bad = not_direct & ~interp
            counts["tracking_bad_not_interpolated"] = int(bad.sum())
            detail["tracking_bad_not_interpolated"] = (
                f"{_rows(bad)}; values seen: "
                f"{sorted(set(ts[bad].tolist()))[:5]}")
        if np.any(not_direct & interp):
            counts["tracking_bad_but_interpolated"] = int((not_direct & interp).sum())
    else:
        tracking_ok = np.ones(n, dtype=bool)

    effective = pv & numeric & tracking_ok
    counts["effective_invalid"] = int((~effective).sum())
    return ValidityResult(effective_valid=effective, numeric_pose_valid=numeric,
                          tracking_ok=tracking_ok, pose_valid=pv,
                          interpolated=interp, counts=counts, detail=detail)


def check_pose_provenance(pose_valid=None, pose_valid_original=None,
                          pose_interpolated=None, tracking_state=None,
                          usable_tracking_states: Sequence[str] = USABLE_TRACKING_STATES
                          ) -> List[str]:
    """Consistency of the CPU's repair bookkeeping (GPU-3).

    Expected combinations:

        direct ARCore measurement   pose_valid_original=true,  pose_interpolated=false
        CPU interpolation           pose_valid_original=false, pose_interpolated=true,
                                    pose_valid=true, tracking_state kept as-is

    Anything else means the CPU's provenance columns disagree with each other,
    which makes the dataset untraceable even when the numbers look fine.
    """
    problems: List[str] = []
    if pose_interpolated is None and pose_valid_original is None:
        return problems

    interp_obj = as_bool_array(pose_interpolated, default=False)
    orig_obj = as_bool_array(pose_valid_original, default=None)
    pv_obj = as_bool_array(pose_valid, default=None)
    n = len(interp_obj) if interp_obj is not None else len(orig_obj)

    interp = (_to_mask(interp_obj, False) if interp_obj is not None
              else np.zeros(n, dtype=bool))

    if orig_obj is not None:
        known = np.array([v is not None for v in orig_obj], dtype=bool)
        orig = _to_mask(orig_obj, when_missing=False)
        # interpolated rows should be the ones the original measurement lacked
        odd = interp & known & orig
        if np.any(odd):
            problems.append(
                f"{int(odd.sum())} row(s) have pose_interpolated=true together with "
                f"pose_valid_original=true ({_rows(odd)}). Interpolation should only "
                f"replace rows whose original measurement was invalid.")
        if pv_obj is not None:
            pv = _to_mask(pv_obj, when_missing=False)
            invented = pv & known & ~orig & ~interp
            if np.any(invented):
                problems.append(
                    f"{int(invented.sum())} row(s) have pose_valid=true but "
                    f"pose_valid_original=false and pose_interpolated=false "
                    f"({_rows(invented)}). Where did the validity come from?")

    if pv_obj is not None:
        pv = _to_mask(pv_obj, when_missing=True)
        contradiction = interp & ~pv
        if np.any(contradiction):
            problems.append(
                f"{int(contradiction.sum())} row(s) have pose_interpolated=true but "
                f"pose_valid=false ({_rows(contradiction)}). An interpolated pose "
                f"that is still marked invalid should have been rejected, not written.")

    if tracking_state is not None and np.any(interp):
        good = {str(s).strip().lower() for s in usable_tracking_states}
        ts = np.array([str(s).strip().lower() for s in np.asarray(tracking_state)])
        rewritten = interp & np.isin(ts, list(good))
        if np.any(rewritten):
            problems.append(
                f"{int(rewritten.sum())} interpolated row(s) carry a healthy "
                f"tracking_state ({_rows(rewritten)}). The contract keeps the "
                f"ORIGINAL tracking_state on interpolated rows so the repair stays "
                f"visible; overwriting it loses that provenance.")
    return problems
