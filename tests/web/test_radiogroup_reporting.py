"""RW-13 (REAL_WORLD_TESTING_REPORT.md section 13.2): a radio group that was filled and verified was also reported `unsupported`.

SurveyJS draws a rating as `<fieldset role="radiogroup" aria-required=...>` around visually hidden native `<input type=radio>`
elements and their labels. Discovery handles the native radios (they are a normal radio control, chosen through the label and
read back from `checked`), but the unsupported-control scan also saw the `role=radiogroup` wrapper and listed it as a "custom ARIA
radiogroup: no supported way to read or set it". That contradicted the run, and a run with an unsupported control is never FILLED.

The wrapper is not reported when the native radios inside it are the control FormFiller handles. A group built only of
`role=radio` elements (no native input), or one that mixes the two, is still reported. The wrapper's `aria-required` is carried to
the radio control, because the report used to be the only place it was visible. The fixtures are written for this project.
"""

from __future__ import annotations

import pytest

from formfill.web.discover import discover
from formfill.web.pipeline import run_form
from formfill.web.result import FieldState, field_state
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

STYLE = """<style>.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.opt{display:inline-block;border:1px solid #888;padding:4px 10px;margin-right:6px;cursor:pointer}</style>"""

SOURCE = {"company": {"size": "Medium"}}


def group(attrs='role="radiogroup" aria-labelledby="q"', options=("Small", "Medium", "Large"), disabled=(), name="size"):
    opts = "".join(
        f'<label class="opt"><input class="vh" type="radio" name="{name}" value="{o}"{" disabled" if o in disabled else ""}><span>{o}</span></label>'
        for o in options)
    return f'<fieldset {attrs}><legend class="vh"></legend><div id="q">Company size</div>{opts}</fieldset>'


def load(page, body):
    page.set_content(f"<!doctype html><html><body>{STYLE}<form onsubmit='return false'>{body}</form></body></html>")


def unsupported(result):
    return [(u["kind"], u["label"]) for u in result.unsupported]


def size_item(result):
    return next(i for i in result.items if i.plan.question == "Company size")


# ---- the reproduced report: filled and verified, and nothing unsupported ----------------------------------------------------------------


def test_a_filled_accessible_radio_group_is_not_also_reported_unsupported(page):
    load(page, group())
    result = run_form(page, SOURCE, confirm_ms=0)
    item = size_item(result)
    assert item.filled and item.verified is True and field_state(item)[0] is FieldState.VERIFIED, item.detail
    assert page.is_checked("input[value=Medium]") and not page.is_checked("input[value=Small]")
    assert unsupported(result) == []
    assert result.status == "FILLED"


def test_the_selected_state_is_read_back_from_the_real_inputs(page):
    load(page, group())
    result = run_form(page, SOURCE, confirm_ms=0)
    assert size_item(result).observed == "Medium"


def test_the_same_in_a_multi_step_walk(page):
    load(page, group())
    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    assert size_item(result).verified is True and unsupported(result) == []


def test_a_plain_native_group_with_no_wrapper_is_unchanged(page):
    load(page, group(attrs="").replace('<legend class="vh"></legend>', "<legend>Company size</legend>"))  # no role: the legend names it
    result = run_form(page, SOURCE, confirm_ms=0)
    assert size_item(result).verified is True and unsupported(result) == []


# ---- required groups ---------------------------------------------------------------------------------------------------------------------


def test_the_wrappers_aria_required_marks_the_radio_control_required(page):
    """The wrapper used to carry this alone, and only in the unsupported report; the control that is answered must carry it now."""
    load(page, group(attrs='role="radiogroup" aria-labelledby="q" aria-required="true"'))
    radios = next(c for c in discover(page).controls if c.kind == "radio")
    assert radios.required is True


def test_a_group_with_no_required_marking_is_not_required(page):
    load(page, group())
    assert next(c for c in discover(page).controls if c.kind == "radio").required is False


def test_a_native_required_attribute_still_counts(page):
    load(page, group(attrs="").replace('type="radio"', 'type="radio" required'))
    assert next(c for c in discover(page).controls if c.kind == "radio").required is True


# ---- no answer, no confidence, disabled option -------------------------------------------------------------------------------------------


def test_a_group_with_no_source_answer_goes_to_review_and_nothing_is_selected(page):
    load(page, group())
    result = run_form(page, {"company": {"founded": "1999"}}, confirm_ms=0)
    item = size_item(result)
    assert item.plan.status == "REVIEW" and not item.filled
    assert not any(page.is_checked(f"input[value={v}]") for v in ("Small", "Medium", "Large"))
    assert unsupported(result) == []  # it is a supported control with no answer, not an unsupported one


def test_a_value_that_merely_equals_an_option_is_not_enough(page):
    """A source key that does not state the question's fact must not select an option just because its value is the option's text."""
    load(page, group())
    result = run_form(page, {"office_floor": "Medium"}, confirm_ms=0)
    assert size_item(result).plan.status == "REVIEW"
    assert not any(page.is_checked(f"input[value={v}]") for v in ("Small", "Medium", "Large"))


def test_a_disabled_option_is_never_selected(page):
    load(page, group(disabled=("Medium",)))
    result = run_form(page, SOURCE, confirm_ms=0, timeout_ms=1500)
    assert not page.is_checked("input[value=Medium]")
    item = size_item(result)
    assert item.verified is not True and result.status != "FILLED"


def test_an_enabled_option_is_selected_beside_a_disabled_one(page):
    load(page, group(disabled=("Large",)))
    result = run_form(page, SOURCE, confirm_ms=0)
    assert size_item(result).verified is True and page.is_checked("input[value=Medium]")


# ---- a genuinely unsupported radio group is still reported --------------------------------------------------------------------------------

CUSTOM = ('<div role="radiogroup" aria-label="Company size"><div role="radio" aria-checked="false" tabindex="0" id="r1">Small</div>'
          '<div role="radio" aria-checked="false" tabindex="0" id="r2">Medium</div></div>')


def test_a_group_of_role_radio_elements_with_no_native_input_is_still_reported_and_untouched(page):
    load(page, CUSTOM)
    result = run_form(page, SOURCE, confirm_ms=0)
    assert unsupported(result) == [("aria_radiogroup", "Company size")]
    assert page.get_attribute("#r2", "aria-checked") == "false"
    assert result.status != "FILLED"


def test_a_group_that_mixes_native_radios_and_custom_radios_is_still_reported(page):
    mixed = group().replace("</fieldset>", '<div role="radio" aria-checked="false" tabindex="0">Other</div></fieldset>')
    load(page, mixed)
    result = run_form(page, SOURCE, confirm_ms=0)
    assert ("aria_radiogroup", "Company size") in unsupported(result)


def test_a_handled_group_and_an_unsupported_one_are_told_apart(page):
    load(page, group() + CUSTOM.replace("Company size", "Preferred region"))
    result = run_form(page, SOURCE, confirm_ms=0)
    assert unsupported(result) == [("aria_radiogroup", "Preferred region")]
    assert size_item(result).verified is True
