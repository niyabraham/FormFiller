"""Regression tests for two defects reproduced from a public practice form run (see README, "Bugs found and fixed").

1. A bare format hint ("YYYY-MM-DD", "dd/mm/yyyy") used as a placeholder outranked the control's own name/id as its
   label, so every date box was identified only by how to write the date. And a text box showing a date format received
   the ISO date unconverted.
2. Radios that are not grouped by the browser (different/missing `name`) but behave as one choice: the later fill undid
   the earlier answer and the report said only "page holds None".

The pages here are local, written from the symptoms; they are not copies of any public page.
"""

import pytest

from formfill.web.discover import discover
from formfill.web.models import Control
from formfill.web.pipeline import run_form
from formfill.web.validate import date_format_from_hint, is_date_format_hint, validate_answer

SOURCE = {
    "contact": {"first_name": "Asha", "date_of_birth": "1998-04-12"},
    "preferences": {"comm_email": "email", "comm_phone": "phone"},
}


# ---- pure unit tests ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("hint,fmt", [("YYYY-MM-DD", "%Y-%m-%d"), ("dd/mm/yyyy", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y"),
                                      ("DD.MM.YYYY", "%d.%m.%Y")])
def test_unambiguous_date_hints_have_a_format(hint, fmt):
    assert is_date_format_hint(hint) and date_format_from_hint(hint) == fmt


@pytest.mark.parametrize("hint", ["mm/dd/yy", "d/m/yyyy", "dd-mm/yyyy", "dd/mm"])
def test_ambiguous_date_hints_are_hints_or_not_but_never_guessed(hint):
    assert date_format_from_hint(hint) is None


@pytest.mark.parametrize("text", ["", "Enter your name", "YYYY", "HH:MM", "john@example.com", "e.g. 12/04/1998"])
def test_ordinary_placeholders_are_not_date_hints(text):
    assert not is_date_format_hint(text)


def _text(placeholder, **kw):
    return Control(control_id="c1", kind="text", label="x", placeholder=placeholder, **kw)


def test_iso_date_is_written_in_the_format_the_field_shows():
    assert validate_answer("1998-04-12", _text("dd/mm/yyyy")).value == "12/04/1998"
    assert validate_answer("1998-04-12", _text("MM/DD/YYYY")).value == "04/12/1998"
    assert validate_answer("1998-04-12", _text("YYYY-MM-DD")).value == "1998-04-12"


def test_unsupported_hint_or_non_date_value_is_rejected_not_guessed():
    assert not validate_answer("1998-04-12", _text("mm/dd/yy")).ok
    assert not validate_answer("12 April 1998", _text("dd/mm/yyyy")).ok
    assert not validate_answer("Acme", _text("dd/mm/yyyy")).ok


def test_ordinary_text_field_with_ordinary_placeholder_is_untouched():
    assert validate_answer("1998-04-12", _text("Date of birth")).value == "1998-04-12"


# ---- browser: date boxes --------------------------------------------------------------------------------------------

DATES = """<body>
<input id="forms-dob-iso" name="forms-dob-iso" type="text" placeholder="YYYY-MM-DD">
<input id="forms-dob-eu" name="forms-dob-eu" type="text" placeholder="dd/mm/yyyy">
<input id="plain" type="text" placeholder="YYYY-MM-DD"></body>"""


@pytest.mark.browser
def test_format_placeholder_does_not_replace_the_control_name_as_its_label(page):
    page.set_content(DATES)
    labels = [c.label for c in discover(page).controls]
    assert labels == ["forms-dob-iso", "forms-dob-eu", "plain"]


@pytest.mark.browser
def test_a_control_with_only_a_format_hint_keeps_it_as_a_last_resort_label(page):
    page.set_content('<body><input type="text" placeholder="dd/mm/yyyy"></body>')
    assert [c.label for c in discover(page).controls] == ["dd/mm/yyyy"]


@pytest.mark.browser
def test_date_boxes_are_filled_in_the_format_each_one_shows_and_verified(page):
    page.set_content(DATES)
    res = run_form(page, SOURCE, confirm_ms=0)
    got = {i.plan.question: (i.plan.status, i.observed, i.verified) for i in res.items}
    assert got["forms-dob-iso"] == ("ANSWER", "1998-04-12", True)
    assert got["forms-dob-eu"] == ("ANSWER", "12/04/1998", True)
    assert page.input_value("#forms-dob-eu") == "12/04/1998"


@pytest.mark.browser
def test_unlabelled_date_boxes_with_no_name_stay_in_review(page):
    page.set_content('<body><input type="text" placeholder="YYYY-MM-DD"><input type="text" placeholder="dd/mm/yyyy"></body>')
    res = run_form(page, SOURCE, confirm_ms=0)
    assert [i.plan.status for i in res.items] == ["REVIEW", "REVIEW"] and not any(i.filled for i in res.items)
    assert res.status == "NEEDS_REVIEW"


# ---- browser: radios ------------------------------------------------------------------------------------------------

GROUPED = """<body><fieldset><legend>Preferred contact method</legend>
<label><input type="radio" name="comm" value="email"> Email</label>
<label><input type="radio" name="comm" value="phone"> Phone</label></fieldset></body>"""

UNGROUPED_EXCLUSIVE = """<body>
<input id="forms-comm-email" name="forms-comm-email" type="radio" value="email">
<input id="forms-comm-phone" name="forms-comm-phone" type="radio" value="phone">
<script>const r=[...document.querySelectorAll('input[type=radio]')];
r.forEach(x=>x.addEventListener('change',()=>r.forEach(y=>{if(y!==x)y.checked=false;})));</script></body>"""

UNGROUPED_INDEPENDENT = """<body>
<input id="forms-comm-email" name="forms-comm-email" type="radio" value="email">
<input id="forms-comm-phone" name="forms-comm-phone" type="radio" value="phone"></body>"""


@pytest.mark.browser
def test_name_grouped_radios_are_one_question_with_exactly_one_selection(page):
    page.set_content(GROUPED)
    schema = discover(page)
    assert len(schema.controls) == 1 and [o.value for o in schema.controls[0].options] == ["email", "phone"]
    res = run_form(page, {"contact": {"preferred_contact_method": "phone"}}, confirm_ms=0)
    assert res.status == "FILLED" and res.items[0].observed == "phone" and res.items[0].verified is True
    assert page.is_checked("input[value=phone]") and not page.is_checked("input[value=email]")


@pytest.mark.browser
def test_independent_radio_groups_are_both_filled_and_verified(page):
    page.set_content(UNGROUPED_INDEPENDENT)
    res = run_form(page, SOURCE, confirm_ms=0)
    assert [(i.verified, i.observed) for i in res.items] == [(True, "email"), (True, "phone")]
    assert res.status == "FILLED" and not res.warnings


@pytest.mark.browser
def test_choice_undone_by_the_page_is_reported_with_its_cause_and_never_verified(page):
    page.set_content(UNGROUPED_EXCLUSIVE)
    res = run_form(page, SOURCE, confirm_ms=0)
    email, phone = res.items
    assert email.verified is False and email.observed is None  # an unchecked option is not verified
    assert "overwritten by the page when 'forms-comm-phone'" in email.detail and "human must decide" in email.detail
    assert phone.verified is True and "changed the earlier answer for 'forms-comm-email'" in phone.detail
    assert res.status == "FAILED" and any("behave as one choice" in w for w in res.warnings)
    assert page.is_checked("#forms-comm-phone") and not page.is_checked("#forms-comm-email")


@pytest.mark.browser
def test_choice_undone_by_the_page_blocks_submission(page):
    page.set_content(UNGROUPED_EXCLUSIVE)
    res = run_form(page, SOURCE, confirm_ms=0, submit=True)
    assert res.status == "FAILED" and res.submission["attempted"] is False


@pytest.mark.browser
def test_radio_with_no_resolvable_source_value_is_left_unselected_for_review(page):
    page.set_content(GROUPED)
    res = run_form(page, {"company": {"name": "Acme"}}, confirm_ms=0)
    assert res.items[0].plan.status == "REVIEW" and res.status == "NEEDS_REVIEW"
    assert not page.is_checked("input[value=phone]") and not page.is_checked("input[value=email]")


@pytest.mark.browser
def test_radio_value_not_among_the_options_is_review_not_forced(page):
    page.set_content(GROUPED)
    res = run_form(page, {"contact": {"preferred_contact_method": "carrier pigeon"}}, confirm_ms=0)
    assert res.items[0].plan.status == "REVIEW" and not page.is_checked("input[value=email]")


@pytest.mark.browser
def test_result_records_discovery_metadata_for_diagnosis(page, tmp_path):
    page.set_content(DATES)
    res = run_form(page, SOURCE, confirm_ms=0, out_dir=tmp_path)
    by_name = {c["name"]: c for c in res.controls}
    assert by_name["forms-dob-eu"]["placeholder"] == "dd/mm/yyyy" and by_name["forms-dob-eu"]["kind"] == "text"
    assert [c["control_id"] for c in res.controls] == [i.plan.question_id for i in res.items]
    import json
    assert json.loads((tmp_path / "result.json").read_text())["controls"][0]["name"] == "forms-dob-iso"
