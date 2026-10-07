"""Browser integration tests against local fixture pages (no network).

Pattern borrowed from MiniWoB++/WebArena: small, controllable pages and a
programmatic success check on the resulting DOM state.
"""

import json

import pytest

from formfill.web.discover import discover
from formfill.web.execute import read_back, submit
from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

BASIC_SOURCE = {
    "company": {"name": "Acme Corp", "full_time": 210, "employees": 250, "website_url": "https://acme.example",
                "country": "India", "founded": "2009-03-14"},
    "security": {"contact": {"email": "sec@acme.example"}},
    "certifications": {"iso_27001": True},
}


def by_label(schema):
    return {c.label: c for c in schema.controls}


# ---- discovery ---------------------------------------------------------------


def test_discovery_captures_labels_constraints_and_options(open_fixture):
    schema = discover(open_fixture("rfi_basic.html"))
    c = by_label(schema)
    org = c["Organization name *"]
    assert (org.kind, org.required, org.maxlength, org.section) == ("text", True, 20, "Company details")
    ft = c["Number of full-time employees"]
    assert (ft.kind, ft.min, ft.help_text) == ("number", "0", "Whole numbers only")
    assert c["Security contact email"].kind == "email"  # wrapping <label>
    assert c["Website"].kind == "url"  # aria-labelledby
    country = c["Country"]
    assert [o.value for o in country.options] == ["IN", "US"]  # placeholder option excluded
    iso = c["Do you hold ISO 27001 certification?"]  # fieldset legend
    assert iso.kind == "radio" and [o.label for o in iso.options] == ["Yes", "No"]
    assert c["I confirm the answers are accurate"].kind == "checkbox"
    assert c["Describe your incident response process"].kind == "textarea"
    assert c["Describe your incident response process"].section == "Controls"
    assert len({x.control_id for x in schema.controls}) == len(schema.controls)


def test_rediscovery_keeps_ids(open_fixture):
    page = open_fixture("rfi_basic.html")
    first = [c.control_id for c in discover(page).controls]
    assert first == [c.control_id for c in discover(page).controls]


def test_checkbox_group_multiselect_and_iframe(open_fixture):
    page = open_fixture("rfi_widgets.html")
    page.wait_for_selector("iframe")
    page.frame_locator("#fr").locator("#fe").wait_for()
    c = by_label(discover(page))
    assert c["Certifications held"].kind == "checkbox_group" and len(c["Certifications held"].options) == 3
    assert c["Operating regions"].kind == "multiselect"
    assert c["Frame email"].frame_index == 1  # found inside the iframe


# ---- end to end --------------------------------------------------------------


def test_end_to_end_fills_answers_and_flags_the_rest(open_fixture, tmp_path):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, out_dir=tmp_path)
    got = {i.plan.question: i for i in result.items}

    assert got["Organization name"].plan.status == "ANSWER"
    assert page.input_value("#org") == "Acme Corp"
    assert page.input_value("#ft") == "210" and got["Number of full-time employees"].plan.source == "company.full_time"
    assert page.input_value("[name=sec_email]") == "sec@acme.example"
    assert page.input_value("#web") == "https://acme.example"
    assert page.input_value("#founded") == "2009-03-14"
    assert page.input_value("#country") == "IN"
    assert page.is_checked("input[name=iso][value=yes]")
    # no source value -> untouched and flagged
    assert got["Describe your incident response process"].plan.status == "REVIEW"
    assert page.input_value("#ir") == ""
    assert not page.is_checked("input[name=agree]")

    assert all(i.verified for i in result.items if i.plan.status == "ANSWER")
    assert result.status == "NEEDS_REVIEW"
    data = json.loads((tmp_path / "result.json").read_text())
    assert data["status"] == "NEEDS_REVIEW" and len(data["review_items"]) == 2
    assert (tmp_path / "filled.png").stat().st_size > 0


def test_submit_blocked_while_required_items_need_review(open_fixture):
    page = open_fixture("rfi_basic.html")
    src = {k: v for k, v in BASIC_SOURCE.items() if k != "security"}  # required email now unresolved
    result = run_form(page, src, submit=True, success_text="Thank you")
    assert result.submission["outcome"] == "SKIPPED" and result.status == "NEEDS_REVIEW"
    assert page.locator("#done").is_hidden()  # nothing was sent


def test_submit_confirmed_when_all_required_answered(open_fixture):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, submit=True, success_text="Thank you, your response was received")
    assert result.submission["outcome"] == "CONFIRMED"
    assert result.status == "SUBMITTED" and len(result.review_items) == 2  # optional blanks stay visible in the result


def test_submit_unconfirmed_when_no_confirmation_text_appears(open_fixture):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, submit=True, success_text="Never appears", out_dir=None)
    assert result.submission["outcome"] == "UNCONFIRMED" and result.status == "SUBMITTED_UNCONFIRMED"


def test_browser_validation_blocks_submission_and_is_reported(open_fixture):
    page = open_fixture("rfi_strict.html")
    page.fill("#code", "BAD")  # violates the pattern; the browser must refuse to submit
    outcome = submit(page, "button[type=submit]", success_text="Registration accepted", timeout_ms=800)
    assert outcome["outcome"] == "BLOCKED_BY_VALIDATION" and outcome["invalid_controls"]
    assert page.locator("#ok").is_hidden()
    page.fill("#code", "ABC-1234")
    assert submit(page, "button[type=submit]", success_text="Registration accepted")["outcome"] == "CONFIRMED"


# ---- widgets, conditional fields, defaults -----------------------------------


def test_multi_value_controls(open_fixture):
    page = open_fixture("rfi_widgets.html")
    src = {"certifications": ["ISO 27001", "PCI DSS"], "operating_regions": ["APAC", "Americas"]}
    result = run_form(page, src)
    got = {i.plan.question: i for i in result.items}
    assert got["Certifications held"].verified and got["Operating regions"].verified
    assert page.is_checked("input[value=iso27001]") and not page.is_checked("input[value=soc2]")
    assert page.eval_on_selector("#regions", "e => Array.from(e.selectedOptions).map(o => o.value)") == ["apac", "amer"]


def test_iframe_control_is_filled(open_fixture):
    page = open_fixture("rfi_widgets.html")
    page.frame_locator("#fr").locator("#fe").wait_for()
    result = run_form(page, {"frame_email": "f@x.com"})
    item = next(i for i in result.items if i.plan.question == "Frame email")
    assert item.verified and page.frame_locator("#fr").locator("#fe").input_value() == "f@x.com"


def test_template_default_on_unresolved_control_is_flagged_not_trusted(open_fixture):
    page = open_fixture("rfi_widgets.html")
    result = run_form(page, {})
    tier = next(i for i in result.items if i.plan.question == "Preselected by the template")
    assert tier.plan.status == "REVIEW" and tier.prefilled_warning and tier.observed == "gold"


def test_pattern_violation_in_source_goes_to_review_before_touching_the_page(open_fixture):
    page = open_fixture("rfi_widgets.html")
    result = run_form(page, {"registration_code": "abc-12"})
    item = next(i for i in result.items if i.plan.question == "Registration code")
    assert item.plan.status == "REVIEW" and page.input_value("#code") == ""


def test_conditional_field_appears_after_its_trigger_is_answered(open_fixture):
    page = open_fixture("rfi_conditional.html")
    result = run_form(page, {"gdpr_applies": True, "dpo_name": "A. Rao"})
    got = {i.plan.question: i for i in result.items}
    assert got["DPO name"].verified and page.input_value("#dpo") == "A. Rao"
    assert got["Fax number"].plan.status == "REVIEW" and "disabled" in got["Fax number"].plan.reason
    assert any("stayed hidden" in w for w in result.warnings)  # "Never shown question"


def test_conditional_field_never_revealed_when_trigger_unanswered(open_fixture):
    page = open_fixture("rfi_conditional.html")
    result = run_form(page, {"dpo_name": "A. Rao"})
    assert all(i.plan.question != "DPO name" for i in result.items)
    assert page.input_value("#dpo") == ""


def test_field_vanishing_mid_run_is_a_recorded_failure_not_a_crash(open_fixture):
    page = open_fixture("rfi_basic.html")
    page.evaluate("document.getElementById('web').remove()")  # simulate dynamic page change
    result = run_form(page, BASIC_SOURCE)
    assert all(i.plan.question != "Website" for i in result.items)  # simply not in the form any more
    page2 = open_fixture("rfi_basic.html")
    # remove the element *after* discovery, before fill: patch discover to delay removal
    from formfill.web import pipeline

    real = pipeline.fill_control

    def sabotage(pg, control, answer, timeout_ms=5000):
        if control.label == "Website":
            pg.evaluate("document.getElementById('web').remove()")
        return real(pg, control, answer, 800)

    pipeline.fill_control = sabotage
    try:
        result = run_form(page2, BASIC_SOURCE, timeout_ms=800)
    finally:
        pipeline.fill_control = real
    web = next(i for i in result.items if i.plan.question == "Website")
    assert web.filled is False and "fill failed" in web.detail and result.status == "FAILED"


def test_read_back_reports_what_the_page_actually_holds(open_fixture):
    page = open_fixture("rfi_basic.html")
    ctl = next(c for c in discover(page).controls if c.label == "Number of full-time employees")
    page.fill("#ft", "-5")  # violates min=0
    obs = read_back(page, ctl)
    assert obs.value == "-5" and obs.valid is False
