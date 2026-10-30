"""Evaluate answer matching on question sets that need no browser (benchmarks/semantic/*.json).

    python tools/evaluate_matching.py                              # dev and eval sets, summary on stdout
    python tools/evaluate_matching.py --set benchmarks/semantic/eval.json --out-dir output/eval_matching

Each case is one question (kind, options) asked of one fictional source. The matcher under test is whatever
`formfill.web.plan.plan_question` does in the checkout this file runs from (FORMFILL_PIPELINE_ROOT can point at another
checkout, so a baseline commit and the current code are measured with identical scoring).

Scored separately, never as one number:
  precision        correct answers / answers entered automatically
  coverage         correct answers / questions that have a correct answer
  false positives  answers entered where the expected outcome is REVIEW (unsafe) or with a wrong value
  abstentions      questions sent to REVIEW (correct ones: expected REVIEW)
  proposals        for questions that stayed REVIEW: was the proposed answer offered to the reviewer right?
The dataset file's SHA-256 is printed with every result so a number can be tied to the exact data it came from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("FORMFILL_PIPELINE_ROOT") or Path(__file__).resolve().parent.parent).resolve()
sys.path.insert(0, str(ROOT))

from formfill.web.models import Control, Option  # noqa: E402
from formfill.web.plan import plan_question  # noqa: E402
from formfill.web.retrieve import index_source  # noqa: E402
from formfill.web.understand import understand_control  # noqa: E402

DEFAULT_SETS = [Path(__file__).resolve().parent.parent / "benchmarks" / "semantic" / n for n in ("dev.json", "eval.json")]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def norm(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    s = str(v).strip().casefold()
    try:
        f = float(s.replace(",", ""))
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return s


def control_for(case: dict) -> Control:
    options = [Option(value=o.casefold(), label=o) for o in case.get("options", [])]
    return Control(control_id=case["id"], kind=case["kind"], label=case["question"], options=options, required=bool(case.get("required")))


def is_right(value: Any, case: dict, control: Control) -> bool:
    want = norm(case.get("answer"))
    got = norm(value)
    if got == want:
        return True
    return any(norm(o.value) == got and norm(o.label) == want for o in control.options)


def evaluate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for case in data["cases"]:
        control = control_for(case)
        plan = plan_question(understand_control(control), index_source(data["sources"][case["source"]]))
        expect = case["expect"]
        if plan.status == "ANSWER":
            outcome = ("correct" if is_right(plan.answer, case, control) else "wrong") if expect == "ANSWER" else "unsafe"
        else:
            outcome = "correct_abstention" if expect == "REVIEW" else "missed"
        proposal = plan.proposed_answer
        rows.append({"id": case["id"], "question": case["question"], "expect": expect, "status": plan.status, "outcome": outcome,
                     "answer": plan.answer, "proposed": proposal,
                     "proposal_right": (is_right(proposal, case, control) if (proposal is not None and expect == "ANSWER") else None),
                     "method": plan.method, "category": plan.confidence_category, "confidence": plan.confidence,
                     "source": plan.source, "reason": plan.reason, "conflicts": plan.conflicts})
    expected_answers = sum(1 for r in rows if r["expect"] == "ANSWER")
    answered = [r for r in rows if r["status"] == "ANSWER"]
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    missed = [r for r in rows if r["outcome"] == "missed"]
    summary = {
        "set": data["name"], "file": str(path.name), "sha256": sha256_of(path), "cases": len(rows),
        "expected_answers": expected_answers, "answered": len(answered), "correct": correct,
        "precision": round(correct / len(answered), 4) if answered else None,
        "coverage": round(correct / expected_answers, 4) if expected_answers else None,
        "false_positives": {"unsafe": sum(1 for r in rows if r["outcome"] == "unsafe"), "wrong_value": sum(1 for r in rows if r["outcome"] == "wrong")},
        "abstentions": {"total": sum(1 for r in rows if r["status"] == "REVIEW"),
                        "correct": sum(1 for r in rows if r["outcome"] == "correct_abstention"), "missed_answers": len(missed)},
        "proposals": {"offered": sum(1 for r in missed if r["proposed"] is not None),
                      "right": sum(1 for r in missed if r["proposal_right"]),
                      "wrong": sum(1 for r in missed if r["proposed"] is not None and r["proposal_right"] is False)},
        "by_category": {},
    }
    for r in answered:
        cat = r["category"] or "none"
        b = summary["by_category"].setdefault(cat, {"answered": 0, "correct": 0})
        b["answered"] += 1
        b["correct"] += r["outcome"] == "correct"
    return {"summary": summary, "rows": rows}


def render(results: list[dict]) -> str:
    out = ["# Matching evaluation", "", f"Code under test: `{ROOT}`", ""]
    for res in results:
        s = res["summary"]
        out += [f"## {s['set']} ({s['file']}, sha256 {s['sha256'][:16]}...)", "",
                f"- cases {s['cases']}, with a correct answer {s['expected_answers']}",
                f"- answered automatically {s['answered']}: precision {s['precision']}, coverage {s['coverage']}",
                f"- false positives: {s['false_positives']}",
                f"- abstentions: {s['abstentions']}",
                f"- proposals on abstained questions: {s['proposals']}",
                f"- by confidence category: {s['by_category']}", "",
                "| id | expect | status | outcome | answer / proposal | method | category | why |", "|---|---|---|---|---|---|---|---|"]
        for r in res["rows"]:
            shown = r["answer"] if r["status"] == "ANSWER" else (f"proposed {r['proposed']!r}" if r["proposed"] is not None else "")
            why = (r["reason"] or "").replace("|", "/")[:110]
            out.append(f"| {r['id']} | {r['expect']} | {r['status']} | {r['outcome']} | {shown} | {r['method']} | {r['category']} | {why} |")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", action="append", type=Path, help="question set (default: benchmarks/semantic/dev.json and eval.json)")
    ap.add_argument("--out-dir", type=Path, help="write matching.json and matching.md here (nothing is written otherwise)")
    args = ap.parse_args(argv)
    results = [evaluate(p) for p in (args.set or DEFAULT_SETS)]
    for res in results:
        s = res["summary"]
        print(f"{s['set']:14} precision {s['precision']} coverage {s['coverage']} answered {s['answered']}/{s['cases']} "
              f"FP {s['false_positives']} abstained {s['abstentions']} proposals {s['proposals']}")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "matching.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        (args.out_dir / "matching.md").write_text(render(results), encoding="utf-8")
        print(f"wrote {args.out_dir / 'matching.json'} and matching.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
