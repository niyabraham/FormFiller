"""Requirement C: the layered matcher (no browser). Each example named by the requirement has its own test.

These sources are fictional. The point of every REVIEW case is that a plausible-looking answer must NOT be entered: a mention is
not a certification, a subsidiary is not the company, two disagreeing facts are not one answer, and no evidence is no answer.
"""

from __future__ import annotations

import pytest

from formfill.web.evidence import assess_claim, status_word
from formfill.web.matching import DETERMINISTIC_ONLY, MatcherConfig, confidence_category
from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.semantic import EmbeddingSimilarity, LexicalSimilarity, rank
from formfill.web.understand import understand_control

YN = [Option("yes", "Yes"), Option("no", "No")]


def ask(question: str, source: dict, kind: str = "radio", options=None, config=None):
    opts = YN if options is None and kind in ("radio", "select") else (options or [])
    c = Control(control_id="q", kind=kind, label=question, options=opts)
    return plan_question(understand_control(c), index_source(source), config)


ACME = {
    "company": {"legal_name": "Acme Fictional Ltd",
                "subsidiaries": [{"name": "Acme Cloud GmbH", "soc2_type2_certified": True, "iso27001_certified": True}]},
    "security": {"incident_response_plan": True, "soc2_controls_mapped": True, "soc2_readiness_assessment": "completed 2025",
                 "encryption_at_rest": "AES-256", "mfa_enforced": True},
    "privacy": {"regulations_in_scope": ["GDPR", "CCPA"], "dpo_email": "dpo@acme.example"},
}


# ---- the examples named by the requirement ---------------------------------------------------------------------------------------


def test_incident_response_evidence_is_retrieved_when_the_wording_differs():
    item = ask("Do you maintain a documented incident response process?", ACME)
    # retrieved and offered to the reviewer; a similar-sounding key is not proof, so it is not entered automatically
    assert item.status == "REVIEW" and item.proposed_answer == "yes" and item.method == "semantic"
    assert item.alternatives[0]["source"] == "security.incident_response_plan"
    # and with the wording the deterministic layer understands, it is answered with full provenance
    direct = ask("Do you have a documented incident response plan?", ACME)
    assert direct.status == "ANSWER" and direct.answer == "yes" and direct.source == "security.incident_response_plan"
    assert direct.method == "deterministic" and direct.validation == "ok" and direct.confidence_category in ("high", "medium")
    assert direct.normalized_question == ["documented", "incident", "response", "plan"]


def test_soc2_is_not_answered_yes_because_the_source_mentions_soc2_controls():
    item = ask("Are you SOC 2 certified?", ACME)
    assert item.status == "REVIEW" and item.answer is None
    assert "readiness" in item.reason or "mentions" in item.reason


def test_a_subsidiarys_certification_is_not_attributed_to_the_company():
    assert ask("Is your organisation ISO 27001 certified?", ACME).status == "REVIEW"
    sub_only = {"company": {"subsidiaries": [{"name": "Acme Cloud GmbH", "iso27001_certified": True}]}}
    item = ask("Is your organisation ISO 27001 certified?", sub_only)
    assert item.status == "REVIEW" and "another entity" in item.reason
    # the subsidiary's own question may use the subsidiary's fact
    named = ask("Is your subsidiary ISO 27001 certified?", sub_only)
    assert named.status == "ANSWER" and named.answer == "yes" and named.method == "status_evidence"


def test_an_ordinary_fact_of_a_subsidiary_is_not_used_for_the_company():
    item = ask("Legal company name", {"company": {"subsidiaries": [{"legal_name": "Acme Cloud GmbH"}]}}, kind="text")
    assert item.status == "REVIEW" and "subsidiary" in item.reason


@pytest.mark.parametrize(("question", "source"), [
    ("Minimum password length", {"policies": {"password_min_length": 12}, "security": {"password_policy": {"min_length": 8}}}),
    ("Log retention period (days)", {"policies": {"retention": {"logs_days": 90}}, "security": {"log_retention_days": 180}}),
])
def test_similar_but_contradictory_policy_facts_trigger_review(question, source):
    item = ask(question, source, kind="number")
    assert item.status == "REVIEW" and item.answer is None and item.conflicts
    assert "contradicts" in item.reason or "ambiguous" in item.reason


def test_a_yes_contradicted_by_a_draft_status_triggers_review():
    source = {"security": {"incident_response_plan": True}, "governance": {"incident_response": {"status": "draft"}}}
    item = ask("Do you have a documented incident response plan?", source)
    assert item.status == "REVIEW" and item.conflicts[0]["source"] == "governance.incident_response.status"


@pytest.mark.parametrize("question", ["What is the name of your data protection officer?", "Number of employees",
                                      "Are you HIPAA compliant?", "Is your parent company SOC 2 certified?"])
def test_missing_evidence_means_abstention_not_a_guess(question):
    item = ask(question, ACME, kind="radio" if question.startswith(("Are", "Is")) else "text")
    assert item.status == "REVIEW" and item.answer is None


def test_regulatory_terminology_is_not_proof_of_compliance():
    item = ask("Are you GDPR compliant?", ACME)
    assert item.status == "REVIEW" and item.answer is None and "mentions GDPR" in item.reason


# ---- stated status answers claims, in both directions ---------------------------------------------------------------------------


@pytest.mark.parametrize(("question", "source", "answer"), [
    ("Are you SOC 2 Type II certified?", {"certifications": {"soc2_type2": {"status": "certified"}}}, "yes"),
    ("Do you have a SOC 2 Type 2 certification?", {"attestations": {"soc2": {"type": "Type 2", "status": "certified"}}}, "yes"),
    ("Are you GDPR compliant?", {"privacy": {"gdpr_compliant": True}}, "yes"),
    ("Are you compliant with HIPAA?", {"compliance": {"hipaa_compliant": False}}, "no"),
])
def test_a_stated_status_answers_a_claim(question, source, answer):
    item = ask(question, source)
    assert item.status == "ANSWER" and item.answer == answer and item.method == "status_evidence"
    assert item.confidence_category == "high" and item.source


@pytest.mark.parametrize(("source", "why"), [
    ({"certifications": {"soc2": {"type": "Type 1", "status": "certified"}}}, "different report type"),
    ({"certifications": {"soc2_type2": {"status": "in progress"}}}, "not a completed"),
    ({"a": {"soc2_type2_certified": True}, "b": {"soc2_type2": {"status": "expired"}}}, "contradicts"),
])
def test_a_status_that_is_not_a_clear_yes_stays_review(source, why):
    item = ask("Are you SOC 2 Type II certified?", source)
    assert item.status == "REVIEW" and item.answer is None
    assert why in item.reason or (why == "different report type" and "mentions" in item.reason)


def test_status_words():
    assert status_word("Certified") is True and status_word("non-compliant") is False and status_word("expired") is False
    assert status_word("in progress") == "uncertain" and status_word("Planned for Q3") == "uncertain"
    assert status_word("Fictional Vendor LLC") is None and status_word(True) is True


def test_a_claim_question_must_be_yes_no():
    c = Control(control_id="q", kind="text", label="Which SOC 2 report type do you hold?")
    assert assess_claim(understand_control(c), index_source(ACME)) is None


# ---- domain terms, kinds, layers, calibration -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("question", "source", "answer"), [
    ("Do you have a BCP?", {"security": {"business_continuity_plan": True}}, "yes"),
    ("Recovery time objective (hours)", {"security": {"disaster_recovery_rto_hours": 4}}, 4),
    ("When was your last pentest?", {"security": {"penetration_test_last_date": "2026-01-15"}}, "2026-01-15"),
    ("Is 2FA required?", {"security": {"two_factor_required": True}}, "yes"),
    ("Do you have an IR plan?", {"security": {"incident_response_plan": True}}, "yes"),
])
def test_domain_terms_and_abbreviations_meet_their_spelled_out_form(question, source, answer):
    kind = "date" if "pentest" in question else ("number" if "hours" in question else "radio")
    item = ask(question, source, kind=kind)
    assert item.status == "ANSWER" and item.answer == answer


def test_a_boolean_fact_and_a_name_are_different_facts_not_rivals():
    source = {"infosec": {"ir_plan": True, "ir_plan_owner": "CISO"}}
    assert ask("Do you have an incident response plan in place?", source).answer == "yes"
    owner = ask("Who owns the incident response plan?", source, kind="text")
    assert owner.status == "ANSWER" and owner.answer == "CISO"


def test_a_numeric_disagreement_stays_ambiguous_even_when_one_value_is_text():
    item = ask("Number of employees", {"company": {"employees": 250}, "hr": {"employees": "approx 260"}}, kind="number")
    assert item.status == "REVIEW"


def test_the_deterministic_only_configuration_is_the_previous_behaviour():
    item = ask("Do you maintain a documented incident response process?", ACME, config=DETERMINISTIC_ONLY)
    assert item.status == "REVIEW" and item.proposed_answer is None and item.method == "deterministic"


def test_a_semantic_proposal_never_becomes_an_answer_and_respects_the_threshold():
    loose = ask("How do you protect stored data?", ACME, kind="text", config=MatcherConfig(semantic_min_similarity=0.0))
    assert loose.status == "REVIEW" and loose.answer is None
    strict = ask("How do you protect stored data?", ACME, kind="text", config=MatcherConfig(semantic_min_similarity=0.99))
    assert strict.proposed_answer is None


def test_confidence_categories_follow_the_calibration():
    assert confidence_category(1.0, "deterministic") == "high"
    assert confidence_category(0.7, "deterministic") == "medium"
    assert confidence_category(0.9, "semantic") == "low" and confidence_category(0.0, "status_evidence") == "high"


def test_lexical_similarity_ranks_inflections_and_abbreviations():
    leaves = index_source({"security": {"vuln_scan_cadence": "monthly", "mfa_enforced": True, "siem_tool": "X"}})
    best = rank("How frequently are vulnerability scans run?", leaves, LexicalSimilarity())[0][0]
    assert best.path == "security.vuln_scan_cadence"
    assert rank("Do you enforce MFA?", leaves, LexicalSimilarity())[0][0].path == "security.mfa_enforced"


def test_an_embedding_backend_can_be_plugged_in_without_downloading_anything():
    class FakeModel:  # stands in for a local sentence-transformers model
        def encode(self, texts):
            return [[1.0, 0.0] if "siem" in t.lower() else [0.0, 1.0] for t in texts]

    leaves = index_source({"security": {"siem_tool": "X", "mfa_enforced": True}})
    backend = EmbeddingSimilarity(model=FakeModel())
    assert rank("Which SIEM do you run?", leaves, backend)[0][0].path == "security.siem_tool"
