"""Compare two evaluation runs (e.g. the frozen Phase 2 baseline vs a Phase 3 run).

    python tools/compare_runs.py BEFORE.json AFTER.json [--out comparison.md]

Reports headline metrics, the confusion-matrix delta and *every* question whose
outcome changed, with regressions (previously correct, now not) listed first.
Questions are matched by (case, control); the ground truth is read from the runs
themselves and must be identical, otherwise the comparison is refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GOOD = ("correct_answer", "correct_review", "correctly_unasked")
HEADLINE = [("auto_answered", "auto-answered"), ("correct_answers", "correct answers"), ("unsafe_answers", "unsafe answers"),
            ("fill_failed", "fill failed"), ("review", "REVIEW"), ("not_surfaced", "never asked"),
            ("precision_pct", "precision %"), ("coverage_pct", "coverage %"), ("review_rate_pct", "review rate %"),
            ("answerable_recall_pct", "answerable recall %")]


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def key(r: dict) -> str:
    return f"{r['case']}:{r['control']}"


def describe(r: dict) -> str:
    if r["decision"] == "ANSWER":
        return f"ANSWER {r['answer']!r} from {r['chosen_source']}"
    if r["decision"] == "REVIEW":
        return "REVIEW"
    return "not asked"


def describe_run(name: str, run: dict) -> str:
    return (f"- {name}: commit `{run['evaluated_commit']}` pipeline_dirty={run['pipeline_dirty']}, "
            f"benchmark v{run['benchmark_version']} `{run['benchmark_digest']}`")


def compare(before: dict, after: dict) -> str:
    b = {key(r): r for r in before["questions"]}
    a = {key(r): r for r in after["questions"]}
    assert b.keys() == a.keys(), "runs cover different questions"
    for k in b:
        for f in ("expect", "expected_answer", "expected_source", "question"):
            assert b[k][f] == a[k][f], f"ground truth differs for {k} ({f}); refusing to compare"
    ob, oa = before["overall"], after["overall"]
    out = ["# Run comparison\n",
           describe_run("before", before["run"]),
           describe_run("after ", after["run"]),
           f"- thresholds before {before['run']['thresholds']}, after {after['run']['thresholds']}\n",
           "| metric | before | after | delta |", "|---|---|---|---|"]
    for k, name in HEADLINE:
        out.append(f"| {name} | {ob[k]} | {oa[k]} | {round(oa[k] - ob[k], 1):+} |")
    out += ["", "## Confusion matrix", "", "| cell | before | after | delta |", "|---|---|---|---|"]
    for k in ob["confusion"]:
        out.append(f"| {k} | {ob['confusion'][k]} | {oa['confusion'][k]} | {oa['confusion'][k] - ob['confusion'][k]:+} |")

    changed = [k for k in b if (b[k]["outcome"], b[k]["decision"], b[k]["answer"]) != (a[k]["outcome"], a[k]["decision"], a[k]["answer"])]
    regress = [k for k in changed if b[k]["outcome"] in GOOD and a[k]["outcome"] not in GOOD]
    improve = [k for k in changed if b[k]["outcome"] not in GOOD and a[k]["outcome"] in GOOD]
    other = [k for k in changed if k not in regress and k not in improve]

    def table(title: str, keys: list[str], note: str = "") -> None:
        out.extend(["", f"## {title} ({len(keys)})", ""] + ([note, ""] if note else []))
        if not keys:
            out.append("_none_")
            return
        out.extend(["| case | question | expected | before | after |", "|---|---|---|---|---|"])
        for k in keys:
            r = b[k]
            exp = "REVIEW" if r["expect"] == "REVIEW" else repr(r["expected_answer"])
            out.append(f"| {r['case']} | {r['question']} | {exp} | {describe(b[k])} [{b[k]['outcome']}] | {describe(a[k])} [{a[k]['outcome']}] |")

    table("Regressions: previously correct, now not", regress)
    table("Improvements: previously not correct, now correct", improve)
    table("Other changed outcomes", other, "Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).")
    out.append(f"\nUnchanged outcomes: {len(b) - len(changed)} of {len(b)}.")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    text = compare(load(args.before), load(args.after))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
