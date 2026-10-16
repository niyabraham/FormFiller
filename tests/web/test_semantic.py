"""Semantic retrieval layer (formfill/web/semantic.py): what it must find, and what it must never find.

Pure-Python (no browser). The benchmark gates at the bottom run tools/evaluate_semantic.py over benchmarks/semantic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from formfill.web import retrieve, semantic
from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control

ROOT = Path(__file__).resolve().parents[2]
SRC = {"company_name": "ABC Technologies", "employee_count": 150, "industry": "Information Technology",
       "services": ["AI Solutions", "Software Development"], "information_security_policy": True}


def ask(text, source=SRC, kind="text", options=()):
    c = Control(control_id="c", kind=kind, label=text, options=[Option(o, o) for o in options])
    return plan_question(understand_control(c), index_source(source))


@pytest.mark.parametrize("q", [
    "How many employees does your company have?",
    "What is your company's workforce size?",
    "Give the number of people working in the company.",
    "What is the current employee headcount?",
    "How many staff work for you?",
    "Size of your workforce",
])
def test_paraphrases_of_employee_count_retrieve_150(q):
    item = ask(q, kind="number")
    assert item.status == "ANSWER" and item.source == "employee_count" and item.answer == 150, (q, item.reason)


@pytest.mark.parametrize("q", [
    "What will your headcount be next year?",          # future
    "How many full-time employees do you have?",       # population
    "How many employees does your subsidiary have?",   # other entity
    "How many employees did you have in 2019?",        # historical
    "Number of female employees",                       # population
    "How many employees work in the engineering department?",
])
def test_employee_count_is_not_reused_for_other_populations(q):
    item = ask(q, kind="number")
    assert item.status == "REVIEW", (q, item.source)


@pytest.mark.parametrize("q", ["Does your company have ISO 27001 certification?", "Do you hold ISO 9001 certification?"])
def test_security_mention_does_not_answer_certification(q):
    item = ask(q, SRC | {"iso_13485_certified": True}, kind="radio", options=["Yes", "No"])
    assert item.status == "REVIEW"


def test_distinct_standard_numbers_do_not_match():
    src = {"iso_13485_certified": True}
    assert ask("Are you ISO 13485 certified?", src, "radio", ["Yes", "No"]).status == "ANSWER"
    assert ask("Are you ISO 9001 certified?", src, "radio", ["Yes", "No"]).status == "REVIEW"
    assert ask("Do you have a SOC 2 report?", {"security": {"soc2": {"type": "II"}}}).status == "REVIEW"  # a report type is not a yes/no


@pytest.mark.parametrize("q,expect", [
    ("Which sector does your business operate in?", "industry"),
    ("Turnover (USD)", "revenue_usd"),
    ("Switchboard telephone number", "phone"),
    ("Company web address", "website"),
])
def test_lexicon_synonyms(q, expect):
    src = {"industry": "IT", "revenue_usd": 5, "phone": "+44 1", "website": "https://a.example", "company_name": "X"}
    item = ask(q, src, kind="number" if "USD" in q else "text")
    assert item.status == "ANSWER" and item.source == expect, (q, item.reason)


def test_soft_matches_are_recorded_as_evidence_and_score_below_exact():
    exact = ask("Industry", {"industry": "IT"})
    soft = ask("Sector", {"industry": "IT"})
    assert exact.confidence == 1.0
    assert soft.status == "ANSWER" and soft.confidence < exact.confidence
    assert any("sector" in e and "industry" in e for e in soft.evidence)


def test_initialism_alignment_is_general_not_a_list_entry():
    src = {"carrier": {"eld": {"enabled": True}}}
    item = ask("Do your vehicles use electronic logging devices?", src, "radio", ["Yes", "No"])
    assert item.status == "ANSWER" and item.source == "carrier.eld.enabled"
    assert any("spells 'eld'" in e for e in item.evidence)
    # the same words with a different initialism do not match
    assert ask("Do your vehicles use electronic data capture?", src, "radio", ["Yes", "No"]).status == "REVIEW"


def test_tense_variants_are_not_equated():
    """'Opening date' (planned or in progress) is not `opened` (done)."""
    assert not semantic.same_stem("opening", "opened")
    assert semantic.same_stem("certification", "certified") and semantic.same_stem("incorporated", "incorporation")


def test_measure_word_never_dilutes_the_explained_fraction():
    """'Number of seasonal workers' must not reach `employees.total` just because 'total' is a measure word."""
    src = {"people": {"employees": {"total": 320}}}
    assert ask("Number of seasonal workers", src, "number").status == "REVIEW"
    assert ask("Total number of employees", src, "number").status == "ANSWER"


@pytest.mark.parametrize("word", ["lapsed", "expired", "revoked", "suspended"])
def test_status_negation_is_polarity(word):
    item = ask(f"Is your ISO 14001 certification {word}?", {"compliance": {"iso_14001": False}}, "radio", ["Yes", "No"])
    assert item.status == "REVIEW"


def test_ambiguity_looks_at_every_close_rival_not_only_the_runner_up():
    src = {"a": {"name": "Elena"}, "b": {"name": "Elena"}, "c": {"name": "David"}}
    item = ask("Name", src)
    assert item.status == "REVIEW" and "ambiguous" in item.reason


def test_same_value_rivals_are_not_ambiguous():
    assert ask("Name", {"a": {"name": "Elena"}, "b": {"name": "Elena"}}).status == "ANSWER"


def test_semantic_layer_can_be_switched_off_for_ablation(monkeypatch):
    monkeypatch.setattr(retrieve, "SEMANTIC", semantic.OFF)
    assert ask("Which sector does your business operate in?").status == "REVIEW"
    monkeypatch.setattr(retrieve, "SEMANTIC", semantic.DEFAULT)
    assert ask("Which sector does your business operate in?").status == "ANSWER"


def test_lexicon_is_a_closed_reviewable_file():
    lex = json.loads(semantic.LEXICON_PATH.read_text())
    assert lex["version"] == 1 and len(lex["synonym_groups"]) <= 20 and len(lex["phrases"]) <= 12
    flat = [w for g in lex["synonym_groups"] for w in g]
    assert len(flat) == len(set(flat)), "a word may belong to one group only"
    for lookalike in [("incorporation", "found"), ("mailing", "email"), ("employer", "employee"), ("subcontractor", "subprocessor")]:
        assert not semantic._same_group(*lookalike), lookalike  # look-alikes with different meanings stay apart


# ---- benchmark gates ------------------------------------------------------------------------------------------------------
sys.path.insert(0, str(ROOT))
from tools import evaluate_semantic as ev


def _run(split):
    doc = json.loads((ROOT / "benchmarks" / "semantic" / f"{split}.json").read_text())
    rows = []
    for case in doc["cases"]:
        leaves = index_source(case["source"])
        for n, q in enumerate(case["questions"]):
            rows.append(ev.evaluate_question(leaves, q, n))
    return ev.summarise(rows), rows


def test_dev_benchmark_has_no_unsafe_answers_and_keeps_its_coverage():
    s, rows = _run("dev")
    assert s["unsafe"] == 0, [r for r in rows if r["outcome"] in ("wrong_answer", "unsafe_answer")]
    assert s["precision_pct"] == 100.0 and s["correct"] >= 57


def test_seen_benchmark_does_not_regress():
    s, _ = _run("seen")
    assert s["unsafe"] <= 2 and s["correct"] >= 48  # 2 known: 'Name of your bankers' (wrong source) and 'How many employees' (conflict)


def test_heldout_v2_does_not_regress_from_its_recorded_first_run():
    """First-run record is in benchmarks/semantic/results/heldout_v2_first_run. The two remaining unsafe answers are documented in
    PROJECT_COMPLETION.md (a label defect on 'City', and a subset-population miss on 'regulatory inspections')."""
    s, rows = _run("heldout")
    assert s["unsafe"] <= 2 and s["correct"] >= 50
    unsafe = {r["question"] for r in rows if r["outcome"] in ("wrong_answer", "unsafe_answer")}
    assert unsafe <= {"City", "How many regulatory inspections have you passed?"}


def test_every_scored_question_lands_in_exactly_one_outcome():
    for split in ("dev", "seen", "heldout"):
        s, rows = _run(split)
        assert s["correct"] + s["wrong_answer"] + s["unsafe_answer"] + s["missed"] + s["correct_review"] == len(rows)


# ---- crossed modifiers in counting questions (final stabilization) ------------------------------------------------------
def _plan(label, source):
    from formfill.web.models import Control
    from formfill.web.plan import plan_question
    from formfill.web.retrieve import index_source
    from formfill.web.understand import understand_control
    return plan_question(understand_control(Control(control_id="c1", kind="number", label=label)), index_source(source))


def test_broader_count_question_does_not_take_a_narrower_populations_number():
    item = _plan("How many regulatory inspections have you passed?", {"quality": {"gcp_inspections_passed": 12}})
    assert item.status == "REVIEW" and item.answer is None


def test_the_narrower_question_still_gets_its_own_number():
    item = _plan("How many GCP inspections have you passed?", {"quality": {"gcp_inspections_passed": 12}})
    assert item.status == "ANSWER" and item.answer == 12


def test_spelled_out_number_equals_its_digit_in_the_key():
    item = _plan("How many projects have you completed in the last five years?", {"projects": {"completed_last_5_years": 31}})
    assert item.status == "ANSWER" and item.answer == 31
