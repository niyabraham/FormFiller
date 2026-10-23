"""Regression tests: a company's name is not a person's name.

Found on a public vendor questionnaire: "First name" and "Last name" were answered "BluePeak Tech" from `company.name`.
`company.name` explained one of the two words ("name") and scored 0.67, above plan.MIN_CONFIDENCE, with a margin over the
runner-up wide enough to pass the ambiguity check. The same hole let "Full name", "Contact name", "Project name" and a
bare "Name" read `company.name` (0.67 - 1.0).

Two changes, neither of which touches a threshold:
  * tokens.py   -- first/given/middle/last/family/surname names are one token each, so "First name" cannot be half
                   explained by `company.name`;
  * retrieve.py -- a question that says only "name" and names no organisation cannot be settled on that word alone when
                   an organisation-name key is in the source (the candidates stay visible to the reviewer).

A REVIEW never counts as a correct answer: tests that expect REVIEW assert the status AND that no answer is carried.
"""

from __future__ import annotations

import pytest

from formfill.web.models import Control
from formfill.web.plan import MIN_CONFIDENCE, MIN_MARGIN, plan_question
from formfill.web.retrieve import UNEXPLAINED_CAP, index_source
from formfill.web.tokens import tokenize
from formfill.web.understand import understand_control

COMPANY = "BluePeak Tech"
ONLY_COMPANY = {"company": {"name": COMPANY}}
PERSON_LABELS = ["First name", "Last name", "Given name", "Family name", "Surname", "Middle name",
                 "Full name", "Contact name", "Name", "Your name", "Project name"]


def ask(label, source, section="", kind="text"):
    control = Control(control_id="c1", kind=kind, label=label, section=section)
    return plan_question(understand_control(control), index_source(source))


def assert_review(item):
    assert item.status == "REVIEW" and item.answer is None and item.source is None, (item.status, item.answer, item.source)


def assert_answer(item, value, source):
    assert item.status == "ANSWER", (item.reason, item.alternatives)
    assert (item.answer, item.source) == (value, source)


# --------------------------------------------------------------------------
# thresholds and safeguards are exactly what they were
# --------------------------------------------------------------------------
def test_thresholds_are_unchanged():
    assert MIN_CONFIDENCE == 0.6
    assert MIN_MARGIN == 0.15
    assert UNEXPLAINED_CAP < MIN_CONFIDENCE  # a capped candidate can never be auto-answered


# --------------------------------------------------------------------------
# tokenisation: name parts are one token, on the question side and the key side
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("First name", ["firstname"]), ("first_name", ["firstname"]), ("firstName", ["firstname"]),
    ("FirstName", ["firstname"]), ("Given name", ["firstname"]), ("givenName", ["firstname"]), ("Forename", ["firstname"]),
    ("Last name", ["lastname"]), ("last_name", ["lastname"]), ("lastName", ["lastname"]), ("lastname", ["lastname"]),
    ("Family name", ["lastname"]), ("family_name", ["lastname"]), ("Surname", ["lastname"]), ("surname", ["lastname"]),
    ("Middle name", ["middlename"]), ("middleName", ["middlename"]),
    ("PI first name *", ["pi", "firstname"]),
])
def test_name_parts_are_single_tokens(text, expected):
    assert tokenize(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Full name", ["full", "name"]), ("Contact name", ["contact", "name"]), ("Name", ["name"]),
    ("Company name", ["company", "name"]), ("fullName", ["full", "name"]),
])
def test_other_names_stay_two_tokens(text, expected):
    assert tokenize(text) == expected


def test_last_period_wording_is_not_a_name_part():
    # "last" is a period word elsewhere ("last financial year"); only "last name" is collapsed
    assert tokenize("Revenue last financial year") == ["revenue", "last", "financial", "year"]
    assert tokenize("First quarter revenue") == ["first", "quarter", "revenue"]


# --------------------------------------------------------------------------
# the bug: only `company.name` in the source -> a person's name is never answered with it
# --------------------------------------------------------------------------
@pytest.mark.parametrize("label", PERSON_LABELS)
def test_company_name_never_answers_a_person_name_question(label):
    assert_review(ask(label, ONLY_COMPANY))


@pytest.mark.parametrize("label", PERSON_LABELS)
def test_marked_required_and_with_asterisk_it_is_still_review(label):
    assert_review(ask(label + " *", ONLY_COMPANY))


@pytest.mark.parametrize("label", ["Full name", "Contact name", "Name", "Project name"])
def test_generic_name_questions_keep_the_company_key_visible_to_the_reviewer(label):
    item = ask(label, ONLY_COMPANY)
    assert_review(item)
    assert item.confidence <= UNEXPLAINED_CAP
    assert "company.name" in item.reason  # the candidate is shown, not hidden
    assert "names no organisation" in item.reason


@pytest.mark.parametrize("label", ["First name", "Last name", "Given name", "Family name", "Surname"])
def test_name_part_questions_have_no_company_candidate_at_all(label):
    item = ask(label, ONLY_COMPANY)
    assert_review(item)
    assert item.alternatives == []


def test_the_public_page_source_shape():
    # the keys the failing run actually had: company.name, a DPO name, a security contact email
    src = {"company": {"name": COMPANY}, "privacy": {"dpo_name": "Mira Nair"}, "security": {"contact": {"email": "s@bluepeak.example"}}}
    for label in ("First name", "Last name"):
        assert_review(ask(label, src))
    assert_answer(ask("Security contact email *", src, kind="email"), "s@bluepeak.example", "security.contact.email")


@pytest.mark.parametrize("label", ["Full name", "Contact name", "Name"])
def test_an_unrelated_dpo_name_does_not_rescue_a_generic_name_question(label):
    src = {"company": {"name": COMPANY}, "privacy": {"dpo_name": "Mira Nair"}}
    assert_review(ask(label, src))


# --------------------------------------------------------------------------
# positive matches: the right person-name key is selected, whatever the key style
# --------------------------------------------------------------------------
KEY_STYLES = {
    "snake": {"first": "first_name", "last": "last_name", "full": "full_name"},
    "camel": {"first": "firstName", "last": "lastName", "full": "fullName"},
    "pascal": {"first": "FirstName", "last": "LastName", "full": "FullName"},
}


@pytest.fixture(params=sorted(KEY_STYLES))
def contact_source(request):
    k = KEY_STYLES[request.param]
    return {"company": {"name": COMPANY},
            "contact": {k["first"]: "Mira", k["last"]: "Nair", k["full"]: "Mira Nair", "name": "M. Nair"}}


@pytest.mark.parametrize("label, value", [("First name", "Mira"), ("Given name", "Mira"), ("Forename", "Mira"),
                                           ("Last name", "Nair"), ("Family name", "Nair"), ("Surname", "Nair")])
def test_name_parts_select_the_matching_key_even_beside_company_name(contact_source, label, value):
    item = ask(label, contact_source)
    assert item.status == "ANSWER" and item.answer == value
    assert item.source.startswith("contact.")


def test_full_name_selects_the_full_name_key(contact_source):
    item = ask("Full name", contact_source)
    assert item.status == "ANSWER" and item.answer == "Mira Nair"
    assert item.source.lower().replace("_", "") == "contact.fullname"


def test_contact_name_selects_the_contact_name_key_not_the_company():
    src = {"company": {"name": COMPANY}, "contact": {"name": "Mira Nair"}}
    assert_answer(ask("Contact name", src), "Mira Nair", "contact.name")


def test_name_part_questions_do_not_read_a_full_name_or_the_other_part():
    src = {"contact": {"first_name": "Mira", "last_name": "Nair", "full_name": "Mira Nair"}}
    assert_answer(ask("Last name", src), "Nair", "contact.last_name")
    assert_answer(ask("First name", src), "Mira", "contact.first_name")


def test_list_item_name_parts_still_resolve_by_sibling_evidence():
    # Phase 3B-B behaviour is unchanged by the new tokens: the question cites a value of one list item
    src = {"directors": [{"first_name": "Mira", "last_name": "Nair", "role": "CTO"},
                         {"first_name": "Lars", "last_name": "Velden", "role": "CFO"}]}
    assert_answer(ask("First name of the CFO", src), "Lars", "directors.1.first_name")


# --------------------------------------------------------------------------
# the organisation's name is still the organisation's name
# --------------------------------------------------------------------------
@pytest.mark.parametrize("label", ["Vendor / company name *", "Company name", "Organization name", "Organisation name",
                                    "Business name", "Name of the company", "Supplier name", "Vendor name",
                                    "Entity name", "Employer name"])
def test_company_name_questions_still_read_company_name(label):
    assert_answer(ask(label, ONLY_COMPANY), COMPANY, "company.name")


def test_vendor_company_name_still_wins_beside_person_keys(contact_source):
    assert_answer(ask("Vendor / company name *", contact_source), COMPANY, "company.name")


def test_a_bare_name_under_a_company_heading_reads_company_name():
    # the form section names the organisation, so "Name" is not ambiguous there
    assert_answer(ask("Name", ONLY_COMPANY, section="Company details"), COMPANY, "company.name")


def test_legal_name_is_still_the_legal_name():
    assert_answer(ask("Legal name", {"company": {"legal_name": "BluePeak Technologies Ltd"}}),
                  "BluePeak Technologies Ltd", "company.legal_name")


# --------------------------------------------------------------------------
# ambiguity safeguards survive: a bare "Name" with two different entities' names is REVIEW, never a pick
# --------------------------------------------------------------------------
def test_bare_name_with_company_and_person_is_ambiguous():
    item = ask("Name", {"company": {"name": COMPANY}, "applicant": {"name": "Jane"}})
    assert_review(item)
    assert "ambiguous" in item.reason


def test_bare_name_does_not_fall_through_to_a_weaker_person_key(contact_source):
    # without the guard covering person keys, `contact.full_name` (0.67) would have won once `company.name` was capped
    assert_review(ask("Name", contact_source))


def test_a_lone_person_key_still_answers_a_bare_name():
    # no organisation-name key in the source: the guard has nothing to say, behaviour is as before
    assert_answer(ask("Name", {"applicant": {"name": "Jane"}}), "Jane", "applicant.name")


def test_a_company_without_any_name_key_changes_nothing_for_person_keys():
    src = {"company": {"employees": 250}, "contact": {"first_name": "Mira"}}
    assert_answer(ask("First name", src), "Mira", "contact.first_name")
