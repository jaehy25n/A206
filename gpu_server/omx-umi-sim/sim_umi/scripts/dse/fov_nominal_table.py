"""G0 / G1 / G2 on the frozen timing-controlled nominal-5 condition, episode by episode.

    python sim_umi/scripts/dse/fov_nominal_table.py label=<run dir>:<L> ... --out <stem>

<run dir> holds nominal_<L>.json and aggregate_<L>_nominal.json (aggregate.py label <L>_nominal).
"""
import json
import pathlib
import sys

M = ["entered_corridor", "object_lifted", "strict_gt_secure_grasp", "bin_success", "consecutive_unreachable_abort"]
S = {"entered_corridor": "C", "object_lifted": "L", "strict_gt_secure_grasp": "S", "bin_success": "B",
     "consecutive_unreachable_abort": "a"}


def main():
    i = sys.argv.index("--out")
    out = sys.argv[i + 1]
    args = [a for a in sys.argv[1:i] + sys.argv[i + 2:]]
    runs = []
    for a in args:
        lab, rest = a.split("=", 1)
        d, L = rest.rsplit(":", 1)
        d = pathlib.Path(d)
        R = {e["episode"]: e for e in json.load(open(d / f"nominal_{L}.json"))["episodes"]}
        A = json.load(open(d / f"aggregate_{L}_nominal.json"))["runs"][f"{L}_nominal"]
        runs.append((lab, R, {e["episode"]: e for e in A["episodes"]}, A["counts"]))
    lines = ["| ep | " + " | ".join(l for l, *_ in runs) + " |", "|---|" + "---|" * len(runs)]
    for ep in range(5):
        cells = []
        for lab, R, A, _ in runs:
            e, a = R.get(ep), A.get(ep)
            if e is None:
                cells.append("-"); continue
            code = "".join(S[m] if a[m] else "." for m in M)
            cl = a.get("close")
            geo = "" if not cl else f" d{cl['depth']:.1f}/v{cl['vertical']:.1f}"
            cells.append(f"{code} {e['steps']}a{geo}{'' if e['dse']['gates']['all'] else ' GATE-FAIL'}")
        lines.append(f"| {ep} | " + " | ".join(cells) + " |")
    lines.append("| counts C/L/S/B/a | " + " | ".join("/".join(str(c[m]) for m in M) for *_, c in runs) + " |")
    txt = "\n".join(lines)
    pathlib.Path(out + ".md").write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
