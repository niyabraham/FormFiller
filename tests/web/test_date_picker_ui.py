"""RW-12 (REAL_WORLD_TESTING_REPORT.md section 13.2): a date picker's own controls were listed as questions.

DemoQA's date field opens a calendar popup when FormFiller types into it. The popup holds a month `<select>`, a year `<select>`, a
heading ("March 1990"), navigation buttons and a day grid. After the date was entered the popup stayed open, so the next discovery
round listed its two selects as questionnaire questions (left in review, labelled by their generated ids), and the heading "March
1990" became the section of every field below it.

Discovery now treats a month/year select, or a numeric year/hour/minute box, as picker UI when it sits inside a calendar popup, and
ignores headings inside a calendar popup when working out a field's section. A calendar popup is an ancestor that names itself as
one (a class such as `datepicker` / `calendar` / `flatpickr`, or `role=dialog|application|grid` with a date/calendar label) and that
holds no other kind of input: a text field in the same box means it is a form, not a popup. Buttons and day cells were never
questions, so nothing broader is excluded: a labelled "Birth month" or "Year of birth" select, an "Age" box, a native date input and
a text date input outside a popup are still asked. The fixtures are written for this project.
"""

from __future__ import annotations

import pytest

from formfill.web.discover import discover
from formfill.web.pipeline import run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

MONTHS = "".join(f'<option value="{i}">{m}</option>' for i, m in enumerate(
    "January February March April May June July August September October November December".split()))
YEARS = "".join(f'<option value="{y}">{y}</option>' for y in range(1990, 2031))
DAYS = "".join(f'<div role="option" class="day">{d}</div>' for d in range(1, 32))

# react-datepicker's real structure (captured from DemoQA with the popup open), reduced
REACT_POPUP = f"""
<div class="react-datepicker-popper"><div class="react-datepicker" aria-label="Choose Date" role="dialog" aria-modal="true">
  <button type="button" class="react-datepicker__navigation" aria-label="Previous Month">Previous Month</button>
  <button type="button" class="react-datepicker__navigation" aria-label="Next Month">Next Month</button>
  <div class="react-datepicker__month-container"><div class="react-datepicker__header">
    <h2 class="react-datepicker__current-month">March 1990</h2>
    <div class="react-datepicker__header__dropdown"><select id="pick-month" class="react-datepicker__month-select">{MONTHS}</select>
    <select id="pick-year" class="react-datepicker__year-select">{YEARS}</select></div></div>
  <div class="react-datepicker__month" role="listbox">{DAYS}</div></div></div></div>
"""

# the same popup, known to the page only by its ARIA role and label (no recognisable class)
ARIA_POPUP = f"""
<div class="pop" role="dialog" aria-label="Choose date"><h2>March 1990</h2><select id="pick-month">{MONTHS}</select>
<select id="pick-year">{YEARS}</select><button type="button">Next</button></div>
"""

FLATPICKR_POPUP = f"""
<div class="flatpickr-calendar open"><div class="flatpickr-months"><select id="pick-month" class="flatpickr-monthDropdown-months">{MONTHS}</select>
<div class="numInputWrapper"><input id="pick-year" class="numInput cur-year" type="number" value="1990"></div></div>
<div class="flatpickr-time"><input id="pick-hour" class="numInput flatpickr-hour" type="number" value="12"></div></div>
"""

JQUERY_POPUP = f"""
<div id="ui-datepicker-div" class="ui-datepicker ui-widget"><div class="ui-datepicker-header"><div class="ui-datepicker-title">
<select id="pick-month" class="ui-datepicker-month">{MONTHS}</select><select id="pick-year" class="ui-datepicker-year">{YEARS}</select></div></div></div>
"""

POPUPS = {"react-datepicker": REACT_POPUP, "ARIA dialog only": ARIA_POPUP, "flatpickr": FLATPICKR_POPUP, "jQuery UI": JQUERY_POPUP}

QUESTIONNAIRE = """
<h1>Student registration</h1>
<label>Full name <input id="name"></label>
<label>Date of birth <input id="dob" type="text" placeholder="DD MMM YYYY"></label>
{popup}
<label>Email <input id="email" type="email"></label>
"""

SOURCE = {"full_name": "Jordan Example", "date_of_birth": "1990-03-15", "email": "jordan@example.test"}


def load(page, popup="", extra=""):
    page.set_content("<!doctype html><html><body>" + QUESTIONNAIRE.format(popup=popup) + extra + "</body></html>")


def asked(page):
    return [c.html_id for c in discover(page).controls if c.visible]


# ---- the popup's controls are not questions ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(POPUPS))
def test_an_open_date_picker_popup_adds_no_questions(page, name):
    load(page, POPUPS[name])
    assert asked(page) == ["name", "dob", "email"], name


def test_a_closed_picker_changes_nothing(page):
    load(page)
    assert asked(page) == ["name", "dob", "email"]


@pytest.mark.parametrize("name", list(POPUPS))
def test_the_popup_heading_is_not_the_section_of_the_fields_below_it(page, name):
    load(page, POPUPS[name])
    email = next(c for c in discover(page).controls if c.html_id == "email")
    assert email.section == "Student registration", f"{name}: section was {email.section!r}"


@pytest.mark.parametrize("name", list(POPUPS))
def test_a_run_with_the_popup_open_fills_only_the_real_fields(page, name):
    load(page, POPUPS[name])
    before = page.evaluate("() => Array.from(document.querySelectorAll('#pick-month, #pick-year')).map(e => e.value)")
    result = run_form(page, SOURCE, confirm_ms=0)
    assert sorted(i.plan.question for i in result.items) == ["Date of birth", "Email", "Full name"], name
    assert page.input_value("#email") == "jordan@example.test"
    after = page.evaluate("() => Array.from(document.querySelectorAll('#pick-month, #pick-year')).map(e => e.value)")
    assert after == before  # the picker's own selects were never touched
    assert result.unsupported == []


def test_the_same_holds_in_a_multi_step_walk(page):
    load(page, REACT_POPUP)
    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    assert sorted(i.plan.question for i in result.items) == ["Date of birth", "Email", "Full name"]


# ---- legitimate date questions and neighbours are kept ----------------------------------------------------------------------------------


def test_native_and_text_date_inputs_are_questions(page):
    page.set_content('<label>Start date <input id="a" type="date"></label><label>End date (DD/MM/YYYY) <input id="b" type="text" placeholder="DD/MM/YYYY"></label>')
    kinds = {c.html_id: c.kind for c in discover(page).controls if c.visible}
    assert kinds == {"a": "date", "b": "text"}


def test_labelled_month_year_and_age_questions_beside_an_open_picker_are_still_asked(page):
    extra = (f'<label>Birth month <select id="q-month">{MONTHS}</select></label>'
             f'<label>Year of birth <select id="q-year">{YEARS}</select></label>'
             '<label>Age <input id="q-age" type="number"></label>')
    load(page, REACT_POPUP, extra)
    assert asked(page) == ["name", "dob", "email", "q-month", "q-year", "q-age"]


def test_month_and_year_selects_that_are_plain_questions_are_asked(page):
    page.set_content(f'<label>Birth month <select id="m">{MONTHS}</select></label><label>Year of birth <select id="y">{YEARS}</select></label>')
    assert asked(page) == ["m", "y"]


def test_a_calendar_named_form_with_other_fields_is_not_mistaken_for_a_popup(page):
    """`calendar` in a class name must not hide a questionnaire: this box also holds a text field, so it is a form, not a popup."""
    page.set_content(f'<div class="calendar-booking"><label>Your name <input id="who"></label>'
                     f'<label>Preferred month <select id="m">{MONTHS}</select></label></div>')
    assert asked(page) == ["who", "m"]


def test_a_dialog_that_is_not_a_calendar_keeps_its_fields(page):
    page.set_content(f'<div role="dialog" aria-label="Contact details"><label>Preferred month <select id="m">{MONTHS}</select></label></div>')
    assert asked(page) == ["m"]


def test_a_custom_listbox_that_is_not_part_of_a_picker_is_still_reported(page):
    """The day grid of a picker is not reported, but the same role elsewhere still is: nothing broader was excluded."""
    load(page, REACT_POPUP, '<div role="listbox" aria-label="Pick a plan"><div role="option">Basic</div></div>')
    kinds = [(u["kind"], u["label"]) for u in run_form(page, SOURCE, confirm_ms=0).unsupported]
    assert kinds == [("aria_listbox", "Pick a plan")]
