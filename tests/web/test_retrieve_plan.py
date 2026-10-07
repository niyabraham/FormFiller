"""Question-driven retrieval + the never-guess answer policy (no browser)."""

from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source, retrieve
from formfill.web.tokens import tokenize
from formfill.web.understand import understand_control

COMPANY = {"company": {"employees": 250, "full_time": 210, "contractors": 40}}


def q(label, kind="text", section="", **kw):
    return understand_control(Control(control_id="c1", kind=kind, label=label, section=section, **kw))


def test_tokenize_normalises_both_sides_the_same_way():
    assert tokenize("Number of full-time employees?") == ["fulltime", "employee"]
    assert tokenize("company.full_time") == ["company", "fulltime"]
    assert tokenize("securityContactEmail") == ["security", "contact", "email"]
    assert tokenize("E-mail address") == ["email", "address"]


def test_full_time_question_prefers_full_time_over_total_employees():
    cands = retrieve(q("Number of full-time employees?", "number"), index_source(COMPANY))
    assert cands[0].path == "company.full_time"
    assert cands[0].score - cands[1].score >= 0.15


def test_total_employees_question_prefers_total():
    cands = retrieve(q("How many employees does your organization have?", "number"), index_source(COMPANY))
    assert cands[0].path == "company.employees"


def test_list_indices_do_not_pollute_tokens():
    leaves = index_source({"contacts": [{"email": "a@x.com"}, {"email": "b@x.com"}]})
    assert {leaf.path for leaf in leaves} == {"contacts.0.email", "contacts.1.email"}
    assert all(leaf.leaf_tokens == {"email"} for leaf in leaves)


def test_scalar_lists_are_kept_whole_for_multi_select():
    leaves = index_source({"certifications": ["ISO 27001", "SOC 2"]})
    assert leaves[0].path == "certifications" and leaves[0].value == ["ISO 27001", "SOC 2"]


# ---- policy -----------------------------------------------------------------


def test_answer_has_source_confidence_and_transformed_value():
    item = plan_question(q("Number of full-time employees", "number"), index_source(COMPANY))
    assert item.status == "ANSWER"
    assert item.source == "company.full_time" and item.answer == 210 and item.confidence >= 0.6


def test_missing_source_value_is_review_not_a_guess():
    item = plan_question(q("Do you hold SOC 2 attestation?", "radio", options=[Option("yes", "Yes")]), index_source(COMPANY))
    assert item.status == "REVIEW" and "no matching value" in item.reason and item.answer is None


def test_ambiguous_candidates_with_different_values_go_to_review():
    src = {"applicant": {"name": "Jane"}, "company": {"name": "Acme"}}
    item = plan_question(q("Name"), index_source(src))
    assert item.status == "REVIEW" and "ambiguous" in item.reason
    assert {a["source"] for a in item.alternatives} == {"applicant.name", "company.name"}


def test_section_context_resolves_the_ambiguity():
    src = {"applicant": {"name": "Jane"}, "company": {"name": "Acme"}}
    item = plan_question(q("Name", section="Company details"), index_source(src))
    assert item.status == "ANSWER" and item.answer == "Acme"


def test_equal_values_from_two_paths_are_not_a_conflict():
    src = {"company": {"email": "a@x.com"}, "billing": {"email": "a@x.com"}}
    item = plan_question(q("Email", "email"), index_source(src))
    assert item.status == "ANSWER"


def test_wrong_type_is_review():
    item = plan_question(q("Number of employees", "number"), index_source({"employees": "about two hundred"}))
    assert item.status == "REVIEW" and "not a number" in item.reason


def test_value_not_in_allowed_options_is_review():
    ctl = dict(options=[Option("IN", "India"), Option("US", "United States")])
    item = plan_question(q("Country", "select", **ctl), index_source({"country": "Atlantis"}))
    assert item.status == "REVIEW" and "allowed options" in item.reason


def test_json_boolean_maps_to_yes_no_radio():
    ctl = dict(options=[Option("yes", "Yes"), Option("no", "No")])
    item = plan_question(q("Do you hold ISO 27001 certification?", "radio", **ctl),
                         index_source({"certifications": {"iso_27001": True}}))
    assert item.status == "ANSWER" and item.answer == "yes"


def test_weak_evidence_is_review():
    item = plan_question(q("Registered office address of the parent holding company"), index_source({"address": "1 Main St"}))
    assert item.status == "REVIEW" and "too weak" in item.reason


def test_attestation_checkbox_is_never_auto_ticked_even_if_the_source_says_true():
    item = plan_question(q("I confirm the answers are accurate", "checkbox"), index_source({"answers_accurate": True}))
    assert item.status == "REVIEW" and "attestation" in item.reason
    ordinary = plan_question(q("Has SSO enabled", "checkbox"), index_source({"sso_enabled": True}))
    assert ordinary.status == "ANSWER" and ordinary.answer is True


def test_disabled_control_is_review():
    item = plan_question(q("Fax", disabled=True), index_source({"fax": "123"}))
    assert item.status == "REVIEW" and "disabled" in item.reason
