"""Phase 3A regression tests: unexplained scope, polarity, tokenisation.

Each of the five unsafe answers recorded in the Phase 2 baseline has a test, in
four flavours where they apply: the correct value is available (must be
selected), a similar-but-wrong value is available (must be rejected), the
needed value is absent (REVIEW), and negated vs non-negated wording is told apart.

A REVIEW never counts as a correct answer: tests that expect an ANSWER assert the
value, tests that expect REVIEW assert status AND that no answer is carried.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import MIN_CONFIDENCE, plan_question
from formfill.web.retrieve import UNEXPLAINED_CAP, index_source, retrieve
from formfill.web.tokens import tokenize
from formfill.web.understand import understand_control

YN = [Option("yes", "Yes"), Option("no", "No")]
BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "rfi"


def ask(label, source, kind="text", section="", options=None):
    control = Control(control_id="c1", kind=kind, label=label, section=section, options=options or [])
    return plan_question(understand_control(control), index_source(source))


def assert_answer(item, value, source=None):
    assert item.status == "ANSWER", (item.reason, item.alternatives)
    assert item.answer == value
    if source:
        assert item.source == source


def assert_review(item):
    assert item.status == "REVIEW" and item.answer is None, (item.status, item.answer, item.source)


# --------------------------------------------------------------------------
# A. unexplained qualifiers  (Phase 2 unsafe answers 1, 4, 5)
# --------------------------------------------------------------------------
class TestUnexplainedQualifiers:
    def test_production_employees_is_not_the_total(self):  # unsafe #1
        assert_review(ask("Number of production employees", {"workforce": {"employees": 250}}, "number"))

    def test_production_employees_selected_when_the_source_has_it(self):
        src = {"workforce": {"employees": 250, "production_employees": 80}}
        assert_answer(ask("Number of production employees", src, "number"), 80, "workforce.production_employees")

    def test_total_question_still_prefers_the_total_when_a_subset_exists(self):
        src = {"workforce": {"employees": 250, "production_employees": 80}}
        assert_answer(ask("Number of employees", src, "number"), 250, "workforce.employees")

    def test_parent_company_name_is_not_the_company_name(self):  # unsafe #4
        assert_review(ask("Parent company name", {"company": {"name": "Acme Corp"}}))

    def test_parent_company_name_rejects_a_subsidiary(self):
        assert_review(ask("Parent company name", {"company": {"name": "Acme Corp"}, "subsidiary": {"name": "Acme Labs"}}))

    def test_parent_company_name_selected_when_present(self):
        src = {"company": {"name": "Acme Corp"}, "parent_company": {"name": "Globex"}}
        assert_answer(ask("Parent company name", src), "Globex", "parent_company.name")

    def test_website_of_parent_company_is_not_the_company_website(self):  # unsafe #5
        assert_review(ask("Website of parent company", {"company": {"website": "https://acme.example"}}, "url"))

    def test_website_of_parent_company_selected_when_present(self):
        src = {"company": {"website": "https://acme.example"}, "parent": {"website": "https://globex.example"}}
        assert_answer(ask("Website of parent company", src, "url"), "https://globex.example", "parent.website")

    def test_section_bonus_cannot_launder_an_unexplained_scope_word(self):
        # a section heading naming the parent object used to lift a penalised score back over the threshold
        item = ask("Parent company name", {"company": {"name": "Acme Corp"}}, section="Company details")
        assert_review(item)

    def test_cap_stays_below_the_answer_threshold(self):
        assert UNEXPLAINED_CAP < MIN_CONFIDENCE

    def test_review_explains_why(self):
        item = ask("Number of production employees", {"workforce": {"employees": 250}}, "number")
        assert "production" in item.reason
        assert item.alternatives and item.alternatives[0]["source"] == "workforce.employees"

    def test_scope_words_present_in_the_key_path_are_explained(self):
        src = {"subsidiary": {"employees": 80}, "company": {"employees": 250}}
        assert_answer(ask("How many employees does the subsidiary have?", src, "number"), 80, "subsidiary.employees")

    def test_mostly_unexplained_question_is_capped_even_without_a_listed_scope_word(self):
        # none of these words is in any list: the generic coverage guard must still refuse a one-word key match
        assert_review(ask("Quarterly net recurring revenue", {"finance": {"revenue": 9000000}}, "number"))


# --------------------------------------------------------------------------
# B. negation and polarity  (Phase 2 unsafe answer 2)
# --------------------------------------------------------------------------
class TestPolarity:
    def test_is_mfa_optional_does_not_read_a_required_flag_as_yes(self):  # unsafe #2
        item = ask("Is MFA optional?", {"security": {"mfa_required": True}}, "radio", options=YN)
        assert_review(item)
        assert item.answer != "yes"

    def test_is_mfa_optional_answers_from_an_optional_flag(self):
        item = ask("Is MFA optional?", {"security": {"mfa_optional": False}}, "radio", options=YN)
        assert_answer(item, "no", "security.mfa_optional")

    def test_is_mfa_required_answers_from_a_required_flag(self):
        assert_answer(ask("Is MFA required?", {"security": {"mfa_required": True}}, "radio", options=YN), "yes")

    def test_is_mfa_required_rejects_an_optional_flag(self):
        assert_review(ask("Is MFA required?", {"security": {"mfa_optional": True}}, "radio", options=YN))

    @pytest.mark.parametrize("label,key,expect_answer", [
        ("Is SSO enabled?", "sso_enabled", True),
        ("Is SSO enabled?", "sso_disabled", False),
        ("Is SSO disabled?", "sso_enabled", False),
        ("Is SSO disabled?", "sso_disabled", True),
        ("Is GDPR applicable?", "gdpr_applicable", True),
        ("Is GDPR applicable?", "gdpr_not_applicable", False),
        ("Is GDPR not applicable?", "gdpr_applicable", False),
        ("Is GDPR not applicable?", "gdpr_not_applicable", True),
        ("Do you support SSO?", "sso_supported", True),
        ("Do you support SSO?", "sso_unsupported", False),
        ("Do you not support SSO?", "sso_supported", False),
        ("Do you not support SSO?", "sso_not_supported", True),
    ])
    def test_opposite_polarity_is_never_answered(self, label, key, expect_answer):
        item = ask(label, {"x": {key: True}}, "radio", options=YN)
        if expect_answer:
            assert_answer(item, "yes")
        else:
            assert_review(item)

    def test_valid_negated_question_with_a_negated_key_is_answered(self):
        assert_answer(ask("Is MFA not enforced?", {"security": {"mfa_not_enforced": False}}, "radio", options=YN), "no")

    def test_scope_negation_without_a_matching_key_goes_to_review(self):
        assert_review(ask("Is MFA required for non-administrators?", {"security": {"mfa_required": True}}, "radio", options=YN))

    @pytest.mark.parametrize("label", ["Phone (optional)", "Phone - optional", "Phone: optional", "Optional: Phone", "Phone [optional]", "Phone *"])
    def test_optional_as_a_field_decoration_is_not_negation(self, label):
        assert_answer(ask(label, {"company": {"phone": "555-0100"}}, "tel"), "555-0100")

    def test_plain_unnegated_questions_are_unaffected(self):
        assert_answer(ask("Is SSO supported?", {"security": {"sso_supported": True}}, "radio", options=YN), "yes")


# --------------------------------------------------------------------------
# C. tokenisation
# --------------------------------------------------------------------------
class TestTokenisation:
    def test_snake_case_full_time(self):
        assert tokenize("full_time_employees") == ["fulltime", "employee"]
        assert tokenize("fullTimeEmployees") == ["fulltime", "employee"]
        assert tokenize("part_time") == ["parttime"]

    def test_full_time_question_selects_the_snake_case_key(self):
        src = {"workforce": {"employees": 250, "full_time_employees": 210, "part_time_employees": 40}}
        assert_answer(ask("Number of full-time employees", src, "number"), 210, "workforce.full_time_employees")

    def test_total_is_kept_so_a_total_leaf_is_findable(self):
        assert "total" in tokenize("customers.total")
        src = {"customers": {"total": 1800, "enterprise": 120}}
        assert_answer(ask("Total number of customers", src, "number"), 1800, "customers.total")

    def test_total_in_a_question_does_not_block_the_plain_count(self):
        src = {"company": {"employees": 250}}
        assert_answer(ask("How many employees do you have in total?", src, "number"), 250, "company.employees")

    def test_state_is_a_noun_in_a_form_label(self):
        assert tokenize("State") == ["state"]
        assert tokenize("State / Province") == ["state", "province"]
        assert_answer(ask("State", {"address": {"state": "Karnataka"}}), "Karnataka", "address.state")

    def test_state_as_an_imperative_verb_is_still_dropped(self):
        assert tokenize("Please state the number of employees") == ["employee"]
        assert tokenize("State your company name") == ["company", "name"]

    def test_optional_is_a_token(self):
        assert tokenize("Is MFA optional?") == ["mfa", "optional"]

    def test_parenthetical_acronyms_are_kept(self):
        assert tokenize("Do you support single sign-on (SSO)?") == ["support", "sso"]
        assert tokenize("Is multi-factor authentication (MFA) required for all users?") == ["mfa", "all", "user"]

    def test_parenthetical_format_hints_are_still_dropped(self):
        assert tokenize("Date of birth (DD/MM/YYYY)") == ["birth", "date"]
        assert tokenize("Phone (optional)") == ["phone"]
        assert tokenize("Email (required)") == ["email"]

    def test_spelled_out_acronyms_meet_their_short_form(self):
        assert tokenize("multi_factor_authentication") == tokenize("mfa") == ["mfa"]
        assert tokenize("Data Protection Officer") == tokenize("dpo")
        assert tokenize("single sign-on") == tokenize("sso")

    def test_plural_stemming_boundaries(self):
        assert tokenize("processes") == tokenize("process") == ["process"]
        assert tokenize("branches") == tokenize("branch")
        assert tokenize("policies") == tokenize("policy")
        assert tokenize("address") == ["address"] and tokenize("business") == tokenize("business")

    def test_demonstrated_inflections(self):
        assert tokenize("supported") == tokenize("support")
        assert tokenize("Is data encrypted at rest?") == ["data", "encryption", "rest"]
        assert tokenize("encrypted") == tokenize("encryption")

    def test_headquarters_abbreviation(self):
        assert tokenize("HQ") == tokenize("headquarters") == ["headquarter"]

    def test_leading_enumerators_are_not_content(self):
        for label in ("C.3 Do you support single sign-on (SSO)?", "3. Do you support SSO?", "C3. Do you support SSO", "1.2.1 Do you support SSO?"):
            assert understand_control(Control("c", "radio", label)).concept_tokens == ["support", "sso"], label
        # but an alphanumeric word that merely starts a label is content
        assert "q3" in understand_control(Control("c", "text", "Q3 revenue")).concept_tokens
        assert "soc" in understand_control(Control("c", "text", "SOC 2 report date")).concept_tokens


# --------------------------------------------------------------------------
# D. the Phase 2 unsafe answers, against the real benchmark sources
# --------------------------------------------------------------------------
def _bench_source(case):
    return json.loads((BENCH / case / "source.json").read_text())


@pytest.mark.parametrize("case,label,kind", [
    ("c03_qualifiers", "Number of production employees", "number"),
    ("c08_missing", "Parent company name", "text"),
    ("c08_missing", "Website of parent company", "url"),
])
def test_phase2_unsafe_answers_on_benchmark_sources_now_review(case, label, kind):
    assert_review(ask(label, _bench_source(case), kind))


def test_phase2_unsafe_mfa_optional_on_benchmark_source_is_not_answered():
    item = ask("Is MFA optional?", _bench_source("c05_boolean"), "radio", options=YN)
    assert item.answer != "yes" and item.status == "REVIEW"


@pytest.mark.xfail(strict=True, reason="Phase 2 unsafe #3 (disputed label). Needs sibling/parent scoring, which is out of scope for Phase 3A.")
def test_organization_employees_with_a_subsidiary_present_should_not_auto_answer():
    assert_review(ask("How many employees does the organization have?", _bench_source("c07_ambiguity"), "number"))


# --------------------------------------------------------------------------
# E. nothing that worked before stops working
# --------------------------------------------------------------------------
@pytest.mark.parametrize("label,kind,expected,path", [
    ("Company name", "text", "Acme Corp", "company.name"),
    ("Number of employees", "number", 250, "company.employees"),
    ("Website", "url", "https://acme.example", "company.website"),
    ("Contact email", "email", "ops@acme.example", "company.contact_email"),
    ("Legal name of the company", "text", "Acme Corporation Pvt Ltd", "company.legal_name"),
    ("Total staff headcount", "number", 250, "company.employees"),
])
def test_ordinary_questions_still_answer(label, kind, expected, path):
    src = {"company": {"name": "Acme Corp", "employees": 250, "website": "https://acme.example",
                       "contact_email": "ops@acme.example", "legal_name": "Acme Corporation Pvt Ltd"}}
    assert_answer(ask(label, src, kind), expected, path)


def test_retrieval_candidates_carry_the_reason_for_a_cap():
    cands = retrieve(understand_control(Control("c", "number", "Number of production employees")), index_source({"workforce": {"employees": 250}}))
    assert cands[0].score <= UNEXPLAINED_CAP and any("production" in f for f in cands[0].flags)


def test_self_reference_word_is_not_an_unexplained_scope():
    """Found by the demo, not the benchmark: 'your organization' must not cap a key that lacks 'company'."""
    src = {"privacy": {"gdpr_applicable": True}}
    item = ask("Does GDPR apply to your organization?", src, "radio", section="Privacy", options=YN)
    assert_answer(item, "yes", "privacy.gdpr_applicable")


def test_self_reference_does_not_make_a_sibling_entity_win():
    cands = retrieve(understand_control(Control("c", "number", "How many employees does your organization have?")),
                     index_source({"company": {"employees": 250}, "subsidiary": {"employees": 80}}))
    assert cands[0].path == "company.employees"
