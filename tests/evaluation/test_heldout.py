"""Integrity of the frozen held-out benchmark and of the two recorded runs against it."""

from __future__ import annotations

import filecmp
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELD = ROOT / "benchmarks" / "heldout"
sys.path.insert(0, str(ROOT / "tools"))

MANIFEST = json.loads((HELD / "manifest.json").read_text())
CASES = [c["id"] for c in MANIFEST["cases"]]
PHASE2 = "78d7cab4906d9d922ca1e49108281499c7be2d5c"
PHASE3A = "ee61e130951d452f106932832dfdba01ec2e1aaa"


def _get(data, path):
    for seg in path.split("."):
        data = data[int(seg)] if isinstance(data, list) else data[seg]
    return data


def test_size_and_version():
    assert MANIFEST["benchmark_version"] == "heldout-1.0.0" and MANIFEST["split"] == "heldout"
    assert len(CASES) >= 12 and MANIFEST["scored_questions"] >= 150


def test_frozen_digest_matches_files():
    import evaluate_baseline as ev

    frozen = re.search(r"digest[^:]*:\s*([0-9a-f]{16})", (HELD / "FROZEN.txt").read_text()).group(1)
    old = ev.BENCH
    ev.BENCH = HELD
    try:
        assert ev.benchmark_digest() == frozen, "held-out benchmark changed after it was frozen"
    finally:
        ev.BENCH = old


def test_no_overlap_with_development_cases():
    dev = {c["id"] for c in json.loads((ROOT / "benchmarks" / "rfi" / "manifest.json").read_text())["cases"]}
    assert not dev & set(CASES)


@pytest.mark.parametrize("case", CASES)
def test_truth_consistent_with_form_and_source(case):
    d = HELD / case
    form = (d / "form.html").read_text()
    source = json.loads((d / "source.json").read_text())
    for q in json.loads((d / "truth.json").read_text())["questions"]:
        assert f'"{q["control"]}"' in form, f"{q['control']} missing from form"
        if q["expect"] == "ANSWER":
            assert q["answer"] is not None and q["source"]
            _get(source, q["source"])
        elif q["expect"] == "REVIEW":
            assert q["answer"] is None and q["source"] is None
        else:
            assert q["when"] or q["enable_when"]
        assert q["note"], "every label is justified"


def test_generated_files_match_authoring_sources(tmp_path):
    import build_heldout

    build_heldout.main(tmp_path / "heldout")
    for p in (tmp_path / "heldout").rglob("*"):
        if p.is_file():
            assert filecmp.cmp(p, HELD / p.relative_to(tmp_path / "heldout"), shallow=False), f"stale: {p.name}"


def test_reconciliation_was_conservative():
    rec = json.loads((HELD / "reconciliation.json").read_text())
    assert rec["changes"] and all(c["original"]["expect"] == "ANSWER" and c["reconciled"]["expect"] == "REVIEW" for c in rec["changes"])


@pytest.mark.parametrize("run,commit", [("phase2", PHASE2), ("phase3a", PHASE3A)])
def test_recorded_runs_are_provenanced_and_reconcile(run, commit):
    d = json.loads((HELD / "results" / run / "baseline.json").read_text())
    assert d["run"]["evaluated_commit"] == commit and d["run"]["pipeline_dirty"] is False
    assert d["run"]["benchmark_digest"] == re.search(r"([0-9a-f]{16})", (HELD / "FROZEN.txt").read_text()).group(1)
    o = d["overall"]
    assert sum(o["confusion"].values()) == o["questions"] == MANIFEST["scored_questions"]
    assert o["auto_answered"] == o["correct_answers"] + o["unsafe_answers"] + o["fill_failed"]
