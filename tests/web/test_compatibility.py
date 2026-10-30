"""Requirement D: compatibility with common form patterns (local fixtures in tests/web/fixtures/compat; nothing external).

Each test states what is supported and what is not. Where a pattern is NOT supported, the test pins the safe outcome (nothing is
guessed, the gap is visible) rather than pretending it works. These are fixtures written for this project: they show behaviour
on these patterns, not compatibility with any named portal (docs/COMPATIBILITY.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser
COMPAT = Path(__file__).resolve().parent / "fixtures" / "compat"


def open_compat(page, name):
    page.goto((COMPAT / name).as_uri())
    return page


def by_q(result):
    return {i.plan.question: i for i in result.items}


def test_vue_style_state_bound_fields_are_filled_through_events_and_verified(page):
    source = {"company": {"legal_name": "Fictional Vendor GmbH", "country_of_registration": "Germany", "employees": 120,
                          "iso27001_certified": True}}
    result = run_form(open_compat(page, "vue_style.html"), source, confirm_ms=300)
    assert page.evaluate("() => window.__state") == {"name": "Fictional Vendor GmbH", "country": "Germany", "employees": "120", "iso": True}
    assert all(i.state.value == "verified" for i in result.items), [(i.plan.question, i.state, i.detail) for i in result.items]
    iso = by_q(result)["ISO 27001 certified"]
    assert iso.plan.method == "status_evidence"  # a certification claim, answered from a stated status


def test_unconventional_labels_are_read_and_an_unlabelled_field_is_not_guessed(page):
    source = {"company": {"website": "https://vendor.example", "headquarters_city": "Leeds", "year_founded": 2009},
              "contact": {"email": "ops@vendor.example", "phone": "+44 20 7946 0000"}}
    result = run_form(open_compat(page, "unconventional_labels.html"), source, confirm_ms=0)
    q = by_q(result)
    assert page.input_value("#web") == "https://vendor.example"  # aria-labelledby to a table header
    assert page.input_value("#email") == "ops@vendor.example"  # aria-label
    assert page.input_value("#city") == "Leeds"  # label wrapping the input
    assert page.input_value("#phone") == "+44 20 7946 0000"  # title attribute only
    # Plain text in a preceding <div> is not associated with the input, so the question reads as its name "field_7": nothing
    # in the source matches it and nothing is entered. A person sees it in the review list.
    assert page.input_value("#founded") == "" and q["field_7"].state.value == "needs_review"


def test_repeated_question_blocks_are_told_apart_by_their_section(page):
    source = {"primary_contact": {"full_name": "Ada Example", "email": "ada@vendor.example"},
              "billing_contact": {"full_name": "Bo Example", "email": "billing@vendor.example"}}
    result = run_form(open_compat(page, "repeated_blocks.html"), source, confirm_ms=0)
    assert page.input_value("#p_name") == "Ada Example" and page.input_value("#b_name") == "Bo Example"
    assert page.input_value("#p_email") == "ada@vendor.example" and page.input_value("#b_email") == "billing@vendor.example"
    assert {i.plan.source for i in result.items} == {"primary_contact.full_name", "primary_contact.email",
                                                      "billing_contact.full_name", "billing_contact.email"}
    assert result.summary()["duplicates"]  # the same wording twice is listed for the reviewer, even when answered


def test_repeated_blocks_without_a_distinguishing_source_stay_in_review(page):
    source = {"contacts": [{"full_name": "Ada Example"}, {"full_name": "Bo Example"}]}
    result = run_form(open_compat(page, "repeated_blocks.html"), source, confirm_ms=0)
    names = [i for i in result.items if i.plan.question == "Full name"]
    assert len(names) == 2 and all(i.plan.status == "REVIEW" for i in names)
    assert page.input_value("#p_name") == "" and page.input_value("#b_name") == ""


def test_dates_and_numbers_respect_the_field_constraints(page):
    source = {"insurance": {"policy_expiry_date": "2027-06-30"}, "finance": {"annual_revenue_usd_millions": 12.5},
              "company": {"employees": 120, "incorporation_date": "2009-04-01"}}
    result = run_form(open_compat(page, "dates_numbers.html"), source, confirm_ms=0)
    assert page.input_value("#expiry") == "2027-06-30" and page.input_value("#revenue") == "12.5"
    assert page.input_value("#staff") == "120"
    assert page.input_value("#founded") == "01/04/2009"  # written in the format the field shows
    assert all(i.state.value == "verified" for i in result.items)


def test_a_value_outside_the_field_constraints_is_never_forced_in(page):
    source = {"insurance": {"policy_expiry_date": "2035-01-01"}, "company": {"employees": 5000}}
    result = run_form(open_compat(page, "dates_numbers.html"), source, confirm_ms=0)
    q = by_q(result)
    assert q["Insurance policy expiry date"].plan.status == "REVIEW" and "outside the allowed range" in q["Insurance policy expiry date"].plan.reason
    assert q["Number of employees"].plan.status == "REVIEW" and "above the maximum" in q["Number of employees"].plan.reason
    assert page.input_value("#expiry") == "" and page.input_value("#staff") == ""


def test_a_form_that_renders_late_is_waited_for_and_filled(page):
    source = {"company": {"legal_name": "Fictional Vendor Ltd", "vat_number": "GB123456789"}}
    result = run_form(open_compat(page, "delayed_validation.html"), source, confirm_ms=0)
    assert page.input_value("#org") == "Fictional Vendor Ltd" and page.input_value("#vat") == "GB123456789"
    assert result.status == "FILLED"


def test_a_field_the_page_marks_invalid_after_filling_is_rejected_not_verified(page):
    source = {"company": {"legal_name": "Fictional Vendor Ltd", "vat_number": "123"}}
    result = run_form(open_compat(page, "delayed_validation.html"), source, confirm_ms=0)
    vat = by_q(result)["VAT number"]
    assert vat.filled and vat.state.value == "rejected" and vat.browser_valid is False
    assert "invalid" in vat.detail and result.status == "FAILED"
    assert result.summary()["invalid"][0]["question"] == "VAT number"


def test_a_dropdown_built_from_plain_divs_is_not_supported_and_nothing_is_guessed(page):
    source = {"company": {"legal_name": "Fictional Vendor Ltd", "industry": "Software"}}
    result = run_form(open_compat(page, "custom_div_dropdown.html"), source, confirm_ms=0)
    assert [i.plan.question for i in result.items] == ["Legal company name"]  # the div dropdown is not a control FormFiller can see
    assert page.evaluate("() => window.__industry === undefined")  # and it was never clicked
