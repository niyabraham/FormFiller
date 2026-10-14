"""Generate the held-out benchmark (benchmarks/heldout/) from its authored sources.

    python tools/build_heldout.py

Inputs (committed, authored independently of the pipeline and of the development failure cards):
  benchmarks/heldout/authoring/*.py          the forms, source JSON and author's answer key
  benchmarks/heldout/reconciliation.json     pre-freeze label changes after the blind audit
Outputs per case: form.html, source.json, truth.json; plus manifest.json with the version and a content digest.
The evaluator reads only the outputs; it never imports the authoring sources.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELD = ROOT / "benchmarks" / "heldout"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(HELD / "authoring"))

from benchmark_render import render_form, truth_record

BENCHMARK_VERSION = "heldout-1.0.0"
SPLIT = "heldout"


def load_cases() -> list[dict]:
    import heldout_cases

    cases = heldout_cases.CASES
    changes = {(c["case"], c["control"]): c for c in json.loads((HELD / "reconciliation.json").read_text())["changes"]}
    seen = set()
    for case in cases:
        for q in case["qs"]:
            ch = changes.get((case["id"], q.name))
            if ch:
                assert q.expect == ch["original"]["expect"] and q.answer == ch["original"]["answer"], f"{case['id']}:{q.name} drifted"
                q.expect, q.answer, q.source = ch["reconciled"]["expect"], None, None
                q.tags = [*q.tags, "reconciled"]
                q.note += f" [RECONCILED to REVIEW before freeze: {ch['reason']}]"
                seen.add((case["id"], q.name))
    assert seen == set(changes), "reconciliation entry matched no question"
    return cases


def main(out: Path = HELD) -> None:
    cases = load_cases()
    manifest = []
    for case in cases:
        d = out / case["id"]
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        (d / "form.html").write_text(render_form(case["id"], case["qs"], submit=case.get("submit"),
                                                 dynamic_steps=case.get("dynamic_steps", set())), encoding="utf-8")
        (d / "source.json").write_text(json.dumps(case["source"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (d / "truth.json").write_text(json.dumps(truth_record(case["id"], case["description"], case["source_style"], case["qs"]),
                                                 indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest.append({"id": case["id"], "kind": "extraction", "description": case["description"], "source_style": case["source_style"]})
    scored = sum(q.expect != "ABSENT" for c in cases for q in c["qs"])
    (out / "manifest.json").write_text(json.dumps({
        "benchmark_version": BENCHMARK_VERSION, "split": SPLIT, "cases": manifest,
        "scored_questions": scored,
        "provenance": "authored by an independent agent from a spec without access to the pipeline or the development failure cards; "
                      "key cross-checked by a blind labeller; see docs/HELDOUT_EVALUATION.md",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases, {scored} scored questions -> {out}")


if __name__ == "__main__":
    main()
