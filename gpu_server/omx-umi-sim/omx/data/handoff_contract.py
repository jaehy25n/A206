"""CPU <-> GPU handoff contract validation, shared by the inspector and the converter.

The CPU stamps a ``handoff_contract`` block into ``session_metadata.json`` and
into every segment's ``metadata.json``:

    handoff_contract:
      version                      omx_processed_v1_posefix_1
      source_hz_reference          30.0
      policy_hz_reference          10.0
      action_horizon_reference     16
      min_publish_segment_frames   48

Three of those must match the GPU config exactly -- if the CPU published for
30 Hz and the GPU decimates as if it were 60, everything downstream is silently
wrong and nothing else in the pipeline would notice.

``min_publish_segment_frames`` is deliberately NOT an equality check. It is the
CPU's publish gate; the GPU only needs it to be at least as strict as its own
sampler requirement. The CPU currently publishes at 48 source frames while the
GPU needs 46, i.e. the CPU is two frames more conservative. That is a pass, not
a mismatch.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

#: Contract versions this GPU code knows how to consume.
SUPPORTED_CONTRACT_VERSIONS: Tuple[str, ...] = (
    "omx_processed_v1_posefix_1",
)

CONTRACT_KEY = "handoff_contract"

#: Files a session may carry the contract in. The first two are the ones the GPU
#: actually consumes; the rest are cross-checked when present.
SESSION_CONTRACT_FILES = ("session_metadata.json", "validation_report.json")
SEGMENT_CONTRACT_FILES = ("metadata.json",)

_FLOAT_TOL = 1e-9


@dataclass(frozen=True)
class HandoffContract:
    version: str
    source_hz_reference: float
    policy_hz_reference: float
    action_horizon_reference: int
    min_publish_segment_frames: int

    def key(self) -> tuple:
        return (self.version, float(self.source_hz_reference),
                float(self.policy_hz_reference), int(self.action_horizon_reference),
                int(self.min_publish_segment_frames))

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def describe(self) -> str:
        return (f"{self.version} (source {self.source_hz_reference:g} Hz, "
                f"policy {self.policy_hz_reference:g} Hz, "
                f"action_horizon {self.action_horizon_reference}, "
                f"min_publish_segment_frames {self.min_publish_segment_frames})")


def parse_contract(block: Dict[str, object], source: str
                   ) -> Tuple[Optional[HandoffContract], List[str]]:
    required = ("version", "source_hz_reference", "policy_hz_reference",
                "action_horizon_reference", "min_publish_segment_frames")
    missing = [k for k in required if k not in block]
    if missing:
        return None, [f"{source}: handoff_contract is missing {missing}"]
    try:
        return HandoffContract(
            version=str(block["version"]),
            source_hz_reference=float(block["source_hz_reference"]),
            policy_hz_reference=float(block["policy_hz_reference"]),
            action_horizon_reference=int(block["action_horizon_reference"]),
            min_publish_segment_frames=int(block["min_publish_segment_frames"]),
        ), []
    except (TypeError, ValueError) as e:
        return None, [f"{source}: handoff_contract has an unparseable value ({e})"]


def read_contract_from_json(path: pathlib.Path
                            ) -> Tuple[Optional[HandoffContract], List[str]]:
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return None, [f"{path.name}: unreadable ({e})"]
    block = data.get(CONTRACT_KEY)
    if not isinstance(block, dict):
        return None, []
    return parse_contract(block, path.name)


def collect_session_contracts(session_dir: pathlib.Path, episode_dirs: List[pathlib.Path]
                              ) -> Tuple[Dict[str, HandoffContract], List[str]]:
    """Every contract a session carries, keyed by where it was found."""
    found: Dict[str, HandoffContract] = {}
    problems: List[str] = []
    for name in SESSION_CONTRACT_FILES:
        c, errs = read_contract_from_json(session_dir / name)
        problems.extend(errs)
        if c is not None:
            found[name] = c
    for ep in episode_dirs:
        for name in SEGMENT_CONTRACT_FILES:
            c, errs = read_contract_from_json(ep / name)
            problems.extend(f"{ep.name}/{e}" for e in errs)
            if c is not None:
                found[f"{ep.name}/{name}"] = c
    return found, problems


def validate_contracts(contracts: Dict[str, HandoffContract],
                       source_fps: float, policy_hz: float, action_horizon: int,
                       required_min_source_frames: int,
                       ) -> Tuple[List[str], List[str], Optional[HandoffContract]]:
    """Check a session's contracts against the GPU config.

    Returns ``(problems, notes, agreed_contract)``. ``agreed_contract`` is set
    only when every copy agrees.
    """
    problems: List[str] = []
    notes: List[str] = []

    if not contracts:
        return ([f"no {CONTRACT_KEY} found in session_metadata.json or any segment "
                 f"metadata.json. This export predates the handoff contract; "
                 f"re-run CPU preprocessing and re-sync."], notes, None)

    # --- every copy must agree ---------------------------------------------- #
    by_key: Dict[tuple, List[str]] = {}
    for where, c in contracts.items():
        by_key.setdefault(c.key(), []).append(where)
    if len(by_key) > 1:
        lines = []
        for key, wheres in by_key.items():
            lines.append(f"      {contracts[wheres[0]].describe()}\n"
                         f"        in: {', '.join(sorted(wheres))}")
        problems.append(
            "handoff_contract differs between session and segment metadata "
            "(they must be identical):\n" + "\n".join(lines))
        return problems, notes, None

    contract = next(iter(contracts.values()))
    notes.append(f"contract {contract.describe()} "
                 f"[{len(contracts)} copy/copies agree]")

    # --- version ------------------------------------------------------------ #
    if contract.version not in SUPPORTED_CONTRACT_VERSIONS:
        problems.append(
            f"handoff_contract.version={contract.version!r} is not supported by "
            f"this GPU code. Supported: {list(SUPPORTED_CONTRACT_VERSIONS)}. "
            f"Update omx/data/handoff_contract.py once the new version's meaning "
            f"is understood -- do not just add the string.")

    # --- exact matches ------------------------------------------------------- #
    for label, cpu_value, gpu_value in (
        ("source_hz_reference", contract.source_hz_reference, float(source_fps)),
        ("policy_hz_reference", contract.policy_hz_reference, float(policy_hz)),
    ):
        if abs(cpu_value - gpu_value) > _FLOAT_TOL:
            problems.append(
                f"{label}: CPU published for {cpu_value:g} Hz but the GPU config "
                f"says {gpu_value:g} Hz. These must match exactly -- a mismatch "
                f"silently changes the decimation and every downstream timing.")
    if int(contract.action_horizon_reference) != int(action_horizon):
        problems.append(
            f"action_horizon_reference: CPU published for {contract.action_horizon_reference} "
            f"but the GPU task config uses {action_horizon}. These must match exactly.")

    # --- CPU publish gate must be at least as strict as ours ----------------- #
    if contract.min_publish_segment_frames < required_min_source_frames:
        problems.append(
            f"min_publish_segment_frames={contract.min_publish_segment_frames} is "
            f"below the GPU requirement of {required_min_source_frames} source "
            f"frames (action_horizon {action_horizon} at {policy_hz:g} Hz). The CPU "
            f"may publish segments the sampler cannot draw a single sample from.")
    elif contract.min_publish_segment_frames > required_min_source_frames:
        notes.append(
            f"CPU publish gate is {contract.min_publish_segment_frames} source frames "
            f"vs the GPU requirement of {required_min_source_frames} -- the CPU is "
            f"{contract.min_publish_segment_frames - required_min_source_frames} "
            f"frame(s) more conservative, which is fine.")

    return problems, notes, (contract if not problems else contract)
