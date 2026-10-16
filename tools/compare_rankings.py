"""Compare candidate ranking between two evaluation runs (top candidate and runner-up per question).

    python tools/compare_rankings.py BEFORE.json AFTER.json [--out rankings.md]

Complements compare_runs.py (which reports outcomes): this reports *why* an outcome changed, i.e. which
questions have a different top candidate, a different runner-up, or a changed score, and what the decision
became. Questions are matched by (case, control); runs on different ground truth are refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def key(r: dict) -> str:
    return f"{r['case']}:{r['control']}"


def cell(c: dict | None) -> str:
    return "-" if not c else f"{c['path']} ({c['score']:.2f})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    a, b = (json.loads(p.read_text()) for p in (args.before, args.after))
    if a["run"]["benchmark_digest"] != b["run"]["benchmark_digest"]:
        raise SystemExit("refusing: the two runs used different benchmark content")
    qa = {key(r): r for r in a["questions"]}
    qb = {key(r): r for r in b["questions"]}

    top_changed, runner_changed, score_changed = [], [], []
    for k, ra in qa.items():
        rb = qb[k]
        ta, tb, ua, ub = ra.get("top"), rb.get("top"), ra.get("runner_up"), rb.get("runner_up")
        if (ta or {}).get("path") != (tb or {}).get("path"):
            top_changed.append((k, ra, rb))
        elif (ua or {}).get("path") != (ub or {}).get("path"):
            runner_changed.append((k, ra, rb))
        elif (ta and tb and abs(ta["score"] - tb["score"]) > 1e-9) or (ua and ub and abs(ua["score"] - ub["score"]) > 1e-9):
            score_changed.append((k, ra, rb))

    def rows(items) -> list[str]:
        out = ["| question | top before | top after | runner-up before | runner-up after | decision | outcome |", "|---|---|---|---|---|---|---|"]
        for k, ra, rb in items:
            out.append(f"| {k.split(':')[0][:4]} {ra['question'][:46]} | {cell(ra.get('top'))} | {cell(rb.get('top'))} | "
                       f"{cell(ra.get('runner_up'))} | {cell(rb.get('runner_up'))} | {ra['decision']} -> {rb['decision']} | "
                       f"{ra['outcome']} -> {rb['outcome']} |")
        return out

    lines = [
        "# Candidate-ranking comparison",
        f"- before: `{a['run']['evaluated_commit']}` dirty={a['run']['pipeline_dirty']}",
        f"- after : `{b['run']['evaluated_commit']}` dirty={b['run']['pipeline_dirty']}",
        (f"- questions compared: {len(qa)}; top candidate changed: {len(top_changed)}; same top, different runner-up: {len(runner_changed)}; "
         f"same top and runner-up, score changed: {len(score_changed)}; unchanged: {len(qa) - len(top_changed) - len(runner_changed) - len(score_changed)}"),
        "", "## Top candidate changed", *rows(top_changed),
        "", "## Same top candidate, different runner-up", *rows(runner_changed),
        "", "## Same candidates, changed scores", *rows(score_changed), "",
    ]
    text = "\n".join(lines)
    if args.out:
        args.out.write_text(text)
    print("\n".join(lines[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
