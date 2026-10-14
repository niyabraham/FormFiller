"""Integrity of the Phase 2 benchmark + a smoke/regression test of the harness.

The benchmark is only useful if its ground truth is internally consistent, so
these tests check the truth files themselves (not the pipeline's accuracy).
"""

from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "rfi"
sys.path.insert(0, str(ROOT / "tools"))

MANIFEST = json.loads((BENCH / "manifest.json").read_text())["cases"]


def _truth(case_id):
    return json.loads((BENCH / case_id / "truth.json").read_text())


def _get(data, path):
    for seg in path.split("."):
        data = data[int(seg)] if isinstance(data, list) else data[seg]
    return data


def test_benchmark_size_and_coverage_of_required_categories():
    tags = {t for c in MANIFEST for q in _truth(c["id"])["questions"] for t in q["tags"]}
    required = {"easy", "paraphrase", "synonym", "qualifier", "nested", "boolean_wording", "option_mapping", "missing",
                "ambiguous", "narrative", "conditional", "multistep", "validation", "label_style", "custom_widget", "realistic"}
    assert required <= tags
    assert sum(len(_truth(c["id"])["questions"]) for c in MANIFEST) >= 200


@pytest.mark.parametrize("entry", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_truth_is_consistent_with_form_and_source(entry):
    d = BENCH / entry["id"]
    form = (d / "form.html").read_text()
    source = json.loads((d / "source.json").read_text())
    for q in _truth(entry["id"])["questions"]:
        assert f'"{q["control"]}"' in form, f"{q['control']} missing from form"
        assert q["expect"] in ("ANSWER", "REVIEW", "ABSENT")
        if q["expect"] == "ANSWER":
            assert q["answer"] is not None and q["source"], f"{q['control']}: ANSWER needs answer and source"
            _get(source, q["source"])  # the path must exist in the source JSON
        if q["expect"] == "REVIEW":
            assert q["answer"] is None, f"{q['control']}: REVIEW must not carry an answer"
        if q["expect"] == "ABSENT":
            assert q["when"] or q["enable_when"], f"{q['control']}: ABSENT needs a trigger"
        if q["invalid_source"]:
            _get(source, q["invalid_source"])
    if entry["kind"] == "submission":
        assert entry["expected_outcome"] and entry["expected_status"]


def test_generated_files_are_up_to_date(tmp_path, monkeypatch):
    import build_benchmark

    monkeypatch.setattr(build_benchmark, "OUT", tmp_path / "rfi")
    build_benchmark.main()
    for p in (tmp_path / "rfi").rglob("*"):
        if p.is_file():
            committed = BENCH / p.relative_to(tmp_path / "rfi")
            assert committed.exists() and filecmp.cmp(p, committed, shallow=False), f"stale: {committed}"


@pytest.mark.browser
def test_harness_scores_the_easy_case_perfectly(browser):
    import evaluate_baseline as ev

    entry = next(c for c in MANIFEST if c["id"] == "c01_easy_exact")
    recs, _ = ev.run_case(browser, entry)
    s = ev.summarise(recs)
    assert (s["auto_answered"], s["correct_answers"], s["unsafe_answers"]) == (11, 11, 0)
    assert next(r for r in recs if r["control"] == "fax")["outcome"] == "correct_review"


@pytest.mark.browser
def test_unsafe_answers_do_not_exceed_the_recorded_baseline(browser):
    """Regression guard, not a target: later phases may change coverage, but
    must not add wrong automatic answers to this benchmark. Phase 2 recorded 5;
    Phase 3A recorded 1 (the disputed organization-employees item), so 1 is the ceiling now."""
    import evaluate_baseline as ev

    recs = []
    for entry in (c for c in MANIFEST if c["kind"] == "extraction"):
        recs.extend(ev.run_case(browser, entry)[0])
    assert ev.summarise(recs)["unsafe_answers"] <= 1


# --------------------------------------------------------------- recorded baseline
RESULTS = BENCH / "results" / "baseline.json"


def test_recorded_baseline_has_provenance_and_definitions():
    run = json.loads(RESULTS.read_text())["run"]
    for key in ("evaluated_commit", "benchmark_version", "benchmark_digest", "thresholds", "metric_definitions",
                "reproduction_command"):
        assert run[key], key
    assert set(run["thresholds"]) == {"MIN_CONFIDENCE", "MIN_MARGIN"}


def test_recorded_baseline_partitions_every_scored_question():
    o = json.loads(RESULTS.read_text())["overall"]
    c = o["confusion"]
    assert sum(c.values()) == o["questions"]
    assert o["auto_answered"] == o["correct_answers"] + o["unsafe_answers"] + o["fill_failed"]
    assert o["questions"] == o["auto_answered"] + o["review"] + o["not_surfaced"]
    assert o["precision_pct"] == round(100 * o["correct_answers"] / o["auto_answered"], 1)
    assert o["coverage_pct"] == round(100 * o["auto_answered"] / o["questions"], 1)
    assert o["review_rate_pct"] == round(100 * o["review"] / o["questions"], 1)


def test_recorded_baseline_matches_current_benchmark_files():
    import evaluate_baseline as ev

    assert json.loads(RESULTS.read_text())["run"]["benchmark_digest"] == ev.benchmark_digest(), \
        "benchmarks changed since baseline.json was recorded; re-run tools/evaluate_baseline.py"


def test_summarise_partition_on_synthetic_records():
    import evaluate_baseline as ev

    def rec(expect, decision, outcome):
        return {"expect": expect, "decision": decision, "outcome": outcome, "browser": "n/a"}

    recs = [rec("ANSWER", "ANSWER", "correct_answer"), rec("ANSWER", "ANSWER", "fill_failed"),
            rec("ANSWER", "ANSWER", "wrong_answer"), rec("REVIEW", "ANSWER", "unsafe_answer"),
            rec("ANSWER", "REVIEW", "missed_answer"), rec("REVIEW", "REVIEW", "correct_review"),
            rec("ANSWER", "NOT_ASKED", "not_asked"), rec("ABSENT", "NOT_ASKED", "correctly_unasked")]
    s = ev.summarise(recs)
    assert (s["questions"], s["auto_answered"], s["correct_answers"], s["unsafe_answers"], s["fill_failed"]) == (7, 4, 1, 2, 1)
    assert s["precision_pct"] == 25.0 and s["coverage_pct"] == round(100 * 4 / 7, 1)
