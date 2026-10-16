"""Evaluate question understanding + retrieval + answer planning on the semantic benchmark (no browser needed).

    python tools/evaluate_semantic.py --split dev
    python tools/evaluate_semantic.py --split heldout --out-dir benchmarks/semantic/results/<name>

Every question goes through the same code the pipeline uses (understand_control -> index_source -> plan_question), so the
numbers describe the shipped behaviour. Outcomes per question:

  expect = a source path:   correct (ANSWER from that path) | wrong_answer (ANSWER from another path: UNSAFE) | missed (REVIEW: safe)
  expect = "REVIEW":        correct_review (REVIEW)          | unsafe_answer (ANSWER where a person had to decide: UNSAFE)

precision = correct / auto-answered; coverage = correct / questions that had an answer in the source; unsafe = wrong_answer +
unsafe_answer. Unscored questions do not exist here: every question lands in exactly one outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control
from tools._provenance import RECIPE, _git, pipeline_source_sha256

BENCH = ROOT / "benchmarks" / "semantic"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def evaluate_question(leaves, q: dict, n: int) -> dict:
    opts = [Option(value=o, label=o) for o in q.get("options", [])]
    control = Control(control_id=f"q{n}", kind=q.get("kind", "text"), label=q["question"], section=q.get("section", ""),
                      options=opts)
    plan = plan_question(understand_control(control), leaves)
    exp = q["expect"]
    got = plan.source if plan.status == "ANSWER" else "REVIEW"
    if exp == "REVIEW":
        outcome = "correct_review" if plan.status == "REVIEW" else "unsafe_answer"
    elif plan.status == "ANSWER":
        outcome = "correct" if plan.source == exp else "wrong_answer"
    else:
        outcome = "missed"
    return {"question": q["question"], "category": q["category"], "expect": exp, "got": got, "outcome": outcome,
            "confidence": round(plan.confidence, 3), "reason": plan.reason, "evidence": plan.evidence,
            "alternatives": [{"source": a["source"], "score": a["score"]} for a in plan.alternatives[:2]]}


def summarise(rows: list[dict]) -> dict:
    c = Counter(r["outcome"] for r in rows)
    n = len(rows)
    answered = c["correct"] + c["wrong_answer"] + c["unsafe_answer"]
    answerable = c["correct"] + c["wrong_answer"] + c["missed"]
    unsafe = c["wrong_answer"] + c["unsafe_answer"]
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    return {"questions": n, "expected_answer": answerable, "expected_review": c["correct_review"] + c["unsafe_answer"],
            "auto_answered": answered, "correct": c["correct"], "unsafe": unsafe, "wrong_answer": c["wrong_answer"],
            "unsafe_answer": c["unsafe_answer"], "missed": c["missed"], "correct_review": c["correct_review"],
            "precision_pct": pct(c["correct"], answered), "coverage_pct": pct(c["correct"], answerable),
            "review_rate_pct": pct(n - answered, n), "unsafe_rate_pct": pct(unsafe, n)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "seen", "heldout"], required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--list-failures", action="store_true")
    ap.add_argument("--provider", choices=["wordnet"], help="ablation: add an optional term provider on top of the shipped layer")
    ap.add_argument("--no-semantic", action="store_true", help="ablation: switch the semantic alignment layer off")
    args = ap.parse_args()
    from dataclasses import replace

    from formfill.web import retrieve, semantic

    if args.no_semantic:
        retrieve.SEMANTIC = semantic.OFF
    if args.provider == "wordnet":
        from tools.wordnet_provider import WordNetProvider

        retrieve.SEMANTIC = replace(retrieve.SEMANTIC, provider=WordNetProvider())

    path = BENCH / f"{args.split}.json"
    doc = json.loads(path.read_text())
    rows: list[dict] = []
    for case in doc["cases"]:
        leaves = index_source(case["source"])
        for n, q in enumerate(case["questions"]):
            r = evaluate_question(leaves, q, n)
            r["case"] = case["id"]
            rows.append(r)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    head = _git(ROOT, "rev-parse", "HEAD").strip()
    report = {"benchmark": doc["benchmark"], "version": doc["version"], "file_digest": digest(path),
              "provenance": {"git_head": head, "pipeline_source_sha256": pipeline_source_sha256(ROOT), "hash_recipe": RECIPE,
                             "note": "pipeline_source_sha256 is null for a clean tree; otherwise it hashes the uncommitted formfill/ changes"},
              "overall": summarise(rows),
              "by_category": {k: summarise(v) for k, v in sorted(by_cat.items())},
              "by_case": {k: summarise(v) for k, v in sorted(by_case.items())},
              "unsafe": [r for r in rows if r["outcome"] in ("wrong_answer", "unsafe_answer")],
              "missed": [r for r in rows if r["outcome"] == "missed"], "questions": rows}
    o = report["overall"]
    print(f"[{args.split}] digest={report['file_digest']} questions={o['questions']} (answerable {o['expected_answer']}, must-review {o['expected_review']})")
    print(f"auto-answered={o['auto_answered']} correct={o['correct']} UNSAFE={o['unsafe']} "
          f"(wrong source {o['wrong_answer']}, answered a must-review {o['unsafe_answer']}) missed={o['missed']}")
    print(f"precision={o['precision_pct']}%  coverage={o['coverage_pct']}%  review_rate={o['review_rate_pct']}%  unsafe_rate={o['unsafe_rate_pct']}%")
    for k, v in report["by_category"].items():
        print(f"  {k:<18} n={v['questions']:<3} correct={v['correct']:<3} missed={v['missed']:<3} unsafe={v['unsafe']:<2} correct_review={v['correct_review']}")
    if args.list_failures:
        for r in report["unsafe"]:
            print(f"UNSAFE  [{r['case']}] {r['question']!r}: expected {r['expect']} got {r['got']} ({r['confidence']})")
        for r in report["missed"]:
            print(f"missed  [{r['case']}] {r['question']!r}: expected {r['expect']}; {r['reason']}"[:230])
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.split}.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
        print("wrote", out / f"{args.split}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
