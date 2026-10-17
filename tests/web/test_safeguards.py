"""Safeguards added after held-out v3: entity qualifiers, composite populations, modality (no browser).

Each rule is a word CLASS or a path SHAPE, never a field name or a benchmark question. These tests use sources and wording
that do not appear in `heldout_v3` (which stays frozen); the development fixtures are `benchmarks/semantic/dev_defects.json`.
"""

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control

YN = [Option("Yes", "Yes"), Option("No", "No")]


def plan(label, source, kind="text", yn=False):
    c = Control(control_id="c1", kind="radio" if yn else kind, label=label, options=YN if yn else [])
    return plan_question(understand_control(c), index_source(source))


def answered(item, source=None):
    return item.status == "ANSWER" and (source is None or item.source == source)


# ---- entity qualifiers --------------------------------------------------------------------------------------------------
GROUP = {"parent_company": {"employees": 9000, "name": "Aster Group plc"}, "subsidiary": {"employees": 90, "name": "Aster Parts Ltd"}}


@pytest.mark.parametrize("label,kind", [("How many employees does the company have?", "number"), ("Number of people employed by the business", "number"),
                                        ("Name of the company", "text"), ("Company name", "text")])
def test_generic_question_is_not_answered_from_a_parent_or_a_subsidiary(label, kind):
    assert plan(label, GROUP, kind).status == "REVIEW"


@pytest.mark.parametrize("label,kind,source", [("How many staff does the parent company have?", "number", "parent_company.employees"),
                                               ("Subsidiary headcount", "number", "subsidiary.employees"),
                                               ("Name of the subsidiary", "text", "subsidiary.name")])
def test_a_question_that_names_the_entity_is_answered(label, kind, source):
    assert answered(plan(label, GROUP, kind), source)


def test_a_key_under_the_company_itself_still_answers_a_generic_question():
    src = {"company": {"employees": 300, "name": "Tarn Ltd"}}
    assert answered(plan("How many employees does the business have?", src, "number"), "company.employees")
    assert answered(plan("Name of the firm", src), "company.name")


def test_a_sole_entity_qualified_key_never_answers_a_generic_question():
    assert plan("How many employees does the company have?", {"parent_company": {"employees": 9000}}, "number").status == "REVIEW"
    assert plan("Company country", {"subsidiary": {"country": "UK"}}).status == "REVIEW"


def test_the_plain_key_and_an_entity_key_that_disagree_stay_ambiguous():
    src = {"org": {"founded": 2005}, "parent": {"founded": 1987}}
    item = plan("Year founded", src, "number")
    assert item.status == "REVIEW" and "ambiguous" in item.reason


def test_the_plain_key_and_an_entity_key_that_agree_are_not_a_conflict():
    assert plan("Year founded", {"org": {"founded": 2005}, "parent": {"founded": 2005}}, "number").status == "ANSWER"


def test_an_entity_noun_segment_is_recognised_by_shape_not_by_a_word_list():
    src = {"group": {"holding_company": {"name": "Brack Holdings"}, "acquired_company": {"name": "Brack Foods"}}}
    assert plan("Name of the company", src).status == "REVIEW"
    assert answered(plan("Name of the acquired company", src), "group.acquired_company.name")


def test_a_noun_first_segment_is_not_an_entity_segment():
    assert answered(plan("Company name", {"company_details": {"name": "Tarn Ltd"}}), "company_details.name")


def test_an_entity_rival_that_explains_less_does_not_veto_a_better_answer():
    src = {"group": {"holding_company": {"name": "Brack Holdings"}, "operating_company": {"name": "Brack Foods"}}}
    assert answered(plan("Name of the operating company", src), "group.operating_company.name")


# ---- composite populations ----------------------------------------------------------------------------------------------
STAFF = {"people": {"seasonal_staff": 120, "permanent_staff": 800, "contractors": 60}}


@pytest.mark.parametrize("label", ["Total staff including seasonal workers", "Number of employees excluding contractors",
                                   "Combined headcount of permanent and seasonal staff", "How many staff in total, inclusive of contractors?"])
def test_a_composite_question_is_not_answered_from_one_component(label):
    assert plan(label, STAFF, "number").status == "REVIEW"


@pytest.mark.parametrize("label,source", [("Number of seasonal staff", "people.seasonal_staff"), ("How many permanent staff do you have?", "people.permanent_staff"),
                                          ("How many contractors?", "people.contractors")])
def test_the_component_question_itself_is_answered(label, source):
    assert answered(plan(label, STAFF, "number"), source)


def test_a_key_that_carries_the_composite_wording_may_answer():
    src = {"workforce": {"total_including_contractors": 960, "employees_only": 900}}
    assert answered(plan("Total workforce including contractors", src, "number"), "workforce.total_including_contractors")


# ---- modality ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label", ["Are your accounts audited?", "Have your financial statements been audited?", "Was an audit carried out?"])
def test_a_requirement_key_does_not_answer_a_question_about_what_happened(label):
    assert plan(label, {"compliance": {"audit_required": False}}, yn=True).status == "REVIEW"


def test_the_requirement_question_reads_the_requirement_key():
    assert answered(plan("Is an audit required?", {"compliance": {"audit_required": False}}, yn=True), "compliance.audit_required")


def test_a_soft_obligation_verb_can_read_a_requirement_key_and_a_plain_key():
    assert answered(plan("Do you enforce MFA?", {"security": {"mfa_required": True}}, yn=True), "security.mfa_required")
    assert answered(plan("Is MFA enforced for your staff?", {"security": {"mfaForStaff": True}}, yn=True), "security.mfaForStaff")


def test_a_question_that_says_required_can_read_a_key_that_says_enforced():
    src = {"security": {"mfa": {"enforced_for_all_users": False}}}
    assert answered(plan("Is multi-factor authentication required for all users?", src, yn=True), "security.mfa.enforced_for_all_users")


def test_a_question_that_insists_on_a_requirement_needs_a_key_that_says_so():
    assert plan("Is induction mandatory?", {"training": {"induction_completed": True}}, yn=True).status == "REVIEW"
    assert answered(plan("Is induction mandatory?", {"training": {"induction_mandatory": True}}, yn=True), "training.induction_mandatory")


@pytest.mark.parametrize("label,source", [("When is your next audit planned?", "security.audit_planned"), ("When was your last audit?", "security.last_audit")])
def test_planned_and_past_dates_are_not_swapped(label, source):
    src = {"security": {"audit_planned": "2027-03-01", "last_audit": "2026-01-10"}}
    assert answered(plan(label, src, "date"), source)


def test_a_planned_date_does_not_answer_a_question_about_the_past():
    assert plan("When was your last audit?", {"security": {"audit_planned": "2027-03-01"}}, "date").status == "REVIEW"


def test_requested_and_held_amounts_are_not_swapped():
    src = {"insurance": {"cover_requested_gbp": 5000000, "cover_held_gbp": 2000000}}
    assert plan("Insurance cover amount", src, "number").status == "REVIEW"


def test_a_decoration_is_not_a_modality():
    assert answered(plan("Company name (required)", {"company": {"name": "Tarn Ltd"}}), "company.name")
