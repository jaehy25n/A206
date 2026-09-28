"""Audit the Jetson handoff before telling anyone it is ready.

Answers the two questions that have to be answered every time, mechanically
instead of from memory:

    1. which artifacts changed since the Jetson last received them, i.e. exactly
       what has to be re-sent;
    2. whether the archives alone carry every piece of context needed to act on
       them -- no reliance on a chat message or on a repo-only document.

    python scripts/audit_handoff.py                 # audit + record nothing
    python scripts/audit_handoff.py --run-smoke     # also unpack clean and run
    python scripts/audit_handoff.py --mark-shipped  # record current hashes as
                                                    # what the Jetson now has

`handoff_shipped.json` is the record of what the far side actually holds. It is
only updated by --mark-shipped, so "what to re-send" is a fact, not a guess.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = pathlib.Path(ROOT_DIR)
SHIPPED = ROOT / "handoff_shipped.json"

#: Repo-only docs that quote artifact hashes or counts. They are copy-pasted to
#: the far side, so a stale value there misleads exactly like one inside an
#: archive -- but nothing packaged covers them, so they are checked separately.
UNPACKAGED_DOCS = ["HANDOFF_MESSAGE_TO_JETSON.md"]

ARTIFACTS = [
    ("bundle", "omx_jetson_handoff_*.zip"),
    ("source", "jetson_inference_source_*.tar.gz"),
    ("setup_doc", "README_JETSON_SETUP.md"),
]

#: Every fact the receiving side must be able to find inside the archives.
#: (label, regex). Searched across all packaged .md and .txt files.
REQUIRED_CONTEXT = [
    ("두 아카이브를 나란히 배치", r"나란히|side by side|omx_policy"),
    ("ROS 컨테이너에 설치 금지", r"ROS Jazzy|ros jazzy"),
    ("JetPack torch 를 먼저", r"JetPack"),
    ("huggingface_hub 핀", r"hf_cache_home"),
    ("numpy<2 핀", r"numpy<2"),
    ("pretrained=False", r"pretrained"),
    ("ema_model 을 로드", r"ema_model"),
    ("vs reference action 은 정보성", r"informational|device-dependent|device RNG|정보성"),
    ("decoder parity 가 필수 항목", r"decoder parity"),
    ("live_ready / actuator 금지", r"live_ready"),
    ("gripper reference 는 측정값 아님", r"placeholder|상수"),
    ("보고할 항목", r"send back|돌려줄"),
    ("구버전 zip 구분", r"72228e33"),
    ("inference_requirements 사용법", r"inference_requirements"),
]

#: Entry points must lead to the procedure; a reader starting anywhere must get
#: there without an out-of-band hint.
ENTRY_LINKS = [
    ("bundle INSTALL.md -> source snapshot",
     "jetson_handoff/INSTALL.md", r"inference_source|smoke_predict"),
    ("snapshot README.md -> setup doc",
     "jetson_inference_source/README.md", r"README_JETSON_SETUP"),
    ("snapshot README.md -> bundle",
     "jetson_inference_source/README.md", r"jetson_handoff"),
]


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""):
            h.update(c)
    return h.hexdigest()


def newest(pattern: str):
    hits = sorted(ROOT.glob(pattern), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def unpack(dst: pathlib.Path):
    b = newest(ARTIFACTS[0][1])
    s = newest(ARTIFACTS[1][1])
    if b:
        with zipfile.ZipFile(b) as z:
            z.extractall(dst)
    if s:
        with tarfile.open(s) as t:
            t.extractall(dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-smoke", action="store_true")
    ap.add_argument("--mark-shipped", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    problems, warnings = [], []
    print("=" * 76)
    print("Jetson handoff audit")
    print("=" * 76)

    # ------------------------------------------------- 1. what to re-send --- #
    shipped = json.loads(SHIPPED.read_text()) if SHIPPED.is_file() else {}
    current, resend = {}, []
    print("\n[1] artifacts -- what the far side has vs what is here")
    for name, pattern in ARTIFACTS:
        p = newest(pattern)
        if p is None:
            problems.append(f"missing artifact: {pattern}")
            print(f"  MISSING  {pattern}")
            continue
        h = sha256_file(p)
        current[name] = {"file": p.name, "sha256": h, "bytes": p.stat().st_size}
        was = shipped.get(name, {}).get("sha256")
        if was is None:
            state, mark = "never recorded as sent", "SEND"
        elif was == h:
            state, mark = "unchanged", "  -  "
        else:
            state, mark = f"CHANGED (had {was[:8]}…)", "SEND"
        if mark == "SEND":
            resend.append((name, p))
        print(f"  {mark}  {p.name:44s} {h[:12]}…  {state}")
        side = p.with_suffix(p.suffix + ".sha256")
        if p.suffix != ".md":
            if not side.is_file():
                problems.append(f"{p.name}: .sha256 sidecar missing")
            elif side.read_text().split()[0] != h:
                problems.append(f"{p.name}: .sha256 sidecar is stale")

    # ------------------------------------------------ 2. packaged context --- #
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="handoff_audit_"))
    try:
        unpack(tmp)
        docs = sorted(tmp.rglob("*.md")) + sorted(tmp.rglob("*.txt"))
        blob = {p: p.read_text(errors="ignore") for p in docs}

        print(f"\n[2] required context, searched across {len(docs)} packaged docs")
        for label, pat in REQUIRED_CONTEXT:
            hits = [p.name for p, t in blob.items() if re.search(pat, t, re.I)]
            if hits:
                print(f"  ok    {label:34s} {', '.join(sorted(set(hits))[:3])}")
            else:
                problems.append(f"context missing from the archives: {label}")
                print(f"  MISS  {label}")

        print("\n[3] entry points lead to the procedure")
        for label, rel, pat in ENTRY_LINKS:
            f = tmp / rel
            if not f.is_file():
                problems.append(f"entry point absent: {rel}")
                print(f"  MISS  {label:38s} (file absent)")
            elif re.search(pat, f.read_text(), re.I):
                print(f"  ok    {label}")
            else:
                warnings.append(f"entry point does not link onward: {label}")
                print(f"  warn  {label:38s} (no link; stale archive?)")

        print("\n[4] docs carry no value that goes stale")
        live = {info["sha256"] for info in current.values()}
        for rel in UNPACKAGED_DOCS:
            f = ROOT / rel
            if not f.is_file():
                continue
            text = f.read_text()
            for h in set(re.findall(r"\b[a-f0-9]{64}\b", text)):
                if h not in live:
                    problems.append(f"{rel}: quotes sha256 {h[:12]}… which is not "
                                    f"any current artifact")
                    print(f"  BAD   {rel}: stale sha256 {h[:12]}…")
            for m in re.finditer(r"\b(\d{1,4})/\1\b", text):
                warnings.append(f"{rel}: hardcoded count {m.group(0)}")
                print(f"  warn  {rel}: hardcoded count {m.group(0)}")
        for p, t in blob.items():
            for line in t.splitlines():
                if re.search(r"[a-f0-9]{64}", line) and "jetson_inference_source" in line:
                    problems.append(f"{p.name}: states this archive's own sha256")
                    print(f"  BAD   {p.name}: {line.strip()[:64]}")
        # Only a count tied to SHA256SUMS goes stale when the archive changes.
        # "15/15 passed" for a test run is a fact about that run, not a promise.
        for p, t in blob.items():
            for line in t.splitlines():
                if "SHA256SUMS" not in line:
                    continue
                m = re.search(r"\b(\d{1,4})/\1\b", line)
                if m:
                    warnings.append(f"{p.name}: checksum count hardcoded as "
                                    f"{m.group(0)}")
                    print(f"  warn  {p.name}: checksum count hardcoded as {m.group(0)}")
        for p in blob:
            for target in re.findall(r"\]\(([A-Za-z0-9_./-]+\.md)\)", blob[p]):
                if not (p.parent / target).exists():
                    problems.append(f"{p.name}: dangling link -> {target}")
                    print(f"  BAD   {p.name}: dangling link -> {target}")
        if not any(x.startswith("BAD") for x in []):
            print("  ok    no self-referential hash, no dangling link")

        # ------------------------------------------------------ 5. smoke --- #
        if args.run_smoke:
            print("\n[5] clean unpack -> verify_bundle -> smoke")
            for rel in ("jetson_handoff", "jetson_inference_source"):
                d = tmp / rel
                r = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=d,
                                   capture_output=True, text=True)
                bad = [l for l in r.stdout.splitlines() if not l.endswith(": OK")]
                n = len(r.stdout.splitlines())
                print(f"  {'ok  ' if not bad else 'BAD '} {rel}/SHA256SUMS "
                      f"{n - len(bad)}/{n}")
                if bad:
                    problems.append(f"{rel}: {len(bad)} checksum failure(s)")
            r = subprocess.run([args.python, "verify_bundle.py"],
                               cwd=tmp / "jetson_handoff", capture_output=True, text=True)
            ok = "ALL BUNDLE CHECKS PASSED" in r.stdout
            print(f"  {'ok  ' if ok else 'BAD '} verify_bundle.py")
            if not ok:
                problems.append("verify_bundle.py failed")
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="")
            r = subprocess.run(
                [args.python, "scripts/smoke_predict_action.py",
                 "--bundle", "../jetson_handoff", "--device", "cpu", "--benchmark", "1"],
                cwd=tmp / "jetson_inference_source", capture_output=True, text=True, env=env)
            ok = "ALL SMOKE CHECKS PASSED" in r.stdout
            print(f"  {'ok  ' if ok else 'BAD '} smoke_predict_action.py (cpu)")
            if not ok:
                problems.append("smoke_predict_action.py failed")
                print("        " + r.stdout.strip().splitlines()[-1][:90])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------- verdict ---- #
    print("\n" + "=" * 76)
    if resend:
        print("RE-SEND these:")
        for name, p in resend:
            side = p.with_suffix(p.suffix + ".sha256")
            print(f"  {p.name}")
            if side.is_file():
                print(f"  {side.name}")
        print("\n  unchanged, no need to re-send:")
        for name, info in current.items():
            if not any(n == name for n, _ in resend):
                print(f"  {info['file']}")
    else:
        print("nothing to re-send: every artifact matches what was last shipped")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    if problems:
        print(f"\nFAILED -- {len(problems)} problem(s):")
        for x in problems:
            print(f"  - {x}")
        return 1

    print("\nhandoff is self-sufficient: every required fact is inside the archives")
    if args.mark_shipped:
        SHIPPED.write_text(json.dumps(current, indent=2))
        print(f"\nrecorded as shipped -> {SHIPPED.name}")
    else:
        print("\n(run with --mark-shipped once the files are actually transferred)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
