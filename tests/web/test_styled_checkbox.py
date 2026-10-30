"""RW-11 (REAL_WORLD_TESTING_REPORT.md section 13.2): a checkbox drawn by its label could not be checked.

DemoQA's Hobbies checkboxes are native `<input type=checkbox>` elements that sit invisibly under their `<label>`, which draws the
box (`::before`). Discovery already finds them (they are real, visible-by-the-browser's-measure inputs); the failure was in the
interaction: `set_checked` clicks the input, the label takes the pointer, and Playwright times out ("intercepts pointer events"),
so the answer was never entered. Radios already had a label-click path (`execute._select_radio`); checkboxes did not.

The fix gives checkboxes the same path. The input is clicked as before when it can be hit; otherwise its own accessible label is
clicked (a person's click), the checked state is read back, and nothing is set through JavaScript. These tests pin the cases the
change must get right and the ones it must leave alone. The fixtures are written for this project, not copied from a site.
"""

from __future__ import annotations

import pytest

from formfill.web.discover import discover
from formfill.web.execute import fill_control, read_back
from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

STYLE = """
<style>
 .cb{position:relative;display:inline-block;margin-right:12px}
 .cb input{position:absolute;opacity:0;z-index:-1}          /* the native input is under the page: the label draws the box */
 .cb label{cursor:pointer;padding-left:24px;position:relative}
 .cb label::before{content:"";position:absolute;left:0;top:0;width:18px;height:18px;border:1px solid #666;background:#fff}
 .cb input:checked + label::before{background:#06c}
</style>
"""

COUNTERS = """
<script>
 window.changes = 0; window.submits = 0; window.linkClicks = 0;
 document.addEventListener('change', e => { if (e.target.type === 'checkbox') window.changes++; });
 document.addEventListener('submit', e => { window.submits++; e.preventDefault(); });
 document.addEventListener('click', e => { if (e.target.closest('a')) { window.linkClicks++; e.preventDefault(); } });
</script>
"""

GROUP = """
<form><fieldset><legend>Hobbies</legend>
 <div class="cb"><input id="h1" type="checkbox" name="hobby" value="1"><label for="h1">Sports</label></div>
 <div class="cb"><input id="h2" type="checkbox" name="hobby" value="2"><label for="h2">Reading</label></div>
 <div class="cb"><input id="h3" type="checkbox" name="hobby" value="3"><label for="h3">Music</label></div>
</fieldset><button type="submit">Send application</button></form>
"""


def load(page, body):
    page.set_content(f"<!doctype html><html><body>{STYLE}{body}{COUNTERS}</body></html>")


def control(page, label):
    return next(c for c in discover(page).controls if c.label == label)


def checked(page, *ids):
    return [page.is_checked(f"#{i}") for i in ids]


# ---- the failure, end to end -----------------------------------------------------------------------------------------------------------


def test_a_styled_checkbox_group_is_filled_and_verified(page):
    load(page, GROUP)
    result = run_form(page, {"hobbies": ["Sports", "Reading"]}, confirm_ms=0, timeout_ms=2000)
    item = next(i for i in result.items if i.plan.question == "Hobbies")
    assert item.filled and item.verified is True, item.detail
    assert checked(page, "h1", "h2", "h3") == [True, True, False]
    assert sorted(item.observed) == ["1", "2"]  # read back from the inputs' real checked state
    assert page.evaluate("window.submits") == 0


def test_the_discovery_side_was_never_the_problem(page):
    load(page, GROUP)
    hobbies = control(page, "Hobbies")
    assert hobbies.kind == "checkbox_group" and hobbies.visible and not hobbies.disabled
    assert [o.label for o in hobbies.options] == ["Sports", "Reading", "Music"]


# ---- single styled checkboxes: transitions ---------------------------------------------------------------------------------------------

SINGLE_FOR = '<div class="cb"><input id="n" type="checkbox"><label for="n">Subscribe to updates</label></div>'
SINGLE_WRAP = '<div class="cb"><label><input id="n" type="checkbox"><span>Subscribe to updates</span></label></div>'


@pytest.mark.parametrize("markup", [SINGLE_FOR, SINGLE_WRAP], ids=["label for=", "wrapping label"])
def test_unchecked_to_checked_and_back(page, markup):
    load(page, markup)
    box = control(page, "Subscribe to updates")
    fill_control(page, box, True, 2000)
    assert page.is_checked("#n") and read_back(page, box).value is True
    fill_control(page, box, False, 2000)
    assert not page.is_checked("#n") and read_back(page, box).value is False
    assert page.evaluate("window.changes") == 2  # one real user-style click each way


def test_an_already_checked_box_is_not_toggled(page):
    load(page, SINGLE_FOR.replace('type="checkbox"', 'type="checkbox" checked'))
    box = control(page, "Subscribe to updates")
    fill_control(page, box, True, 2000)
    assert page.is_checked("#n") and page.evaluate("window.changes") == 0  # no click at all: it already held the answer


def test_an_already_unchecked_box_is_left_alone_for_false(page):
    load(page, SINGLE_FOR)
    fill_control(page, control(page, "Subscribe to updates"), False, 2000)
    assert not page.is_checked("#n") and page.evaluate("window.changes") == 0


def test_only_the_boxes_that_must_change_are_clicked_in_a_group(page):
    load(page, GROUP.replace('id="h1" type="checkbox"', 'id="h1" type="checkbox" checked'))
    fill_control(page, control(page, "Hobbies"), ["1", "2"], 2000)
    assert checked(page, "h1", "h2", "h3") == [True, True, False]
    assert page.evaluate("window.changes") == 1  # h1 already held its value; only h2 was clicked


# ---- what must not be touched ----------------------------------------------------------------------------------------------------------


def test_a_disabled_styled_checkbox_is_not_modified(page):
    load(page, SINGLE_FOR.replace('type="checkbox"', 'type="checkbox" disabled'))
    box = control(page, "Subscribe to updates")
    with pytest.raises(ValueError, match="disabled"):
        fill_control(page, box, True, 2000)
    assert not page.is_checked("#n") and page.evaluate("window.changes") == 0


def test_a_label_that_contains_a_link_is_never_clicked(page):
    """A click on the label's centre could land on the link (terms, privacy) and navigate away. Refuse instead."""
    load(page, '<div class="cb"><input id="t" type="checkbox"><label for="t">I accept the <a href="/terms" id="tl">terms of use</a></label></div>')
    box = control(page, "I accept the terms of use")
    with pytest.raises(ValueError, match="link|button|interactive"):
        fill_control(page, box, True, 2000)
    assert not page.is_checked("#t") and page.evaluate("window.linkClicks") == 0


def test_a_checkbox_with_no_label_to_click_is_reported_not_forced(page):
    load(page, '<div style="position:relative"><input id="x" aria-label="Opt in" type="checkbox" style="position:absolute;opacity:0;z-index:-1">'
               '<div style="position:absolute;inset:0;background:#fff"></div>Opt in</div>')
    box = control(page, "Opt in")
    with pytest.raises(ValueError, match="no label"):
        fill_control(page, box, True, 2000)
    assert not page.is_checked("#x")  # never set through JavaScript


def test_a_click_that_does_not_change_the_state_is_an_error_not_a_success(page):
    load(page, SINGLE_FOR + "<script>document.getElementById('n').addEventListener('click', e => e.preventDefault());</script>")
    with pytest.raises(ValueError, match="not confirmed|did not"):
        fill_control(page, control(page, "Subscribe to updates"), True, 2000)
    assert not page.is_checked("#n")


def test_no_form_is_submitted_and_no_submit_control_is_clicked(page):
    load(page, GROUP)
    run_form(page, {"hobbies": ["Sports"]}, confirm_ms=0, timeout_ms=2000)
    assert page.evaluate("window.submits") == 0


# ---- native checkboxes keep working as before ---------------------------------------------------------------------------------------------


def test_a_plain_visible_checkbox_group_is_unchanged(page):
    page.set_content('<fieldset><legend>Hobbies</legend><label><input type="checkbox" name="h" value="1" id="a"> Sports</label>'
                     '<label><input type="checkbox" name="h" value="2" id="b"> Reading</label></fieldset>')
    result = run_form(page, {"hobbies": ["Reading"]}, confirm_ms=0)
    item = result.items[0]
    assert item.verified is True and [page.is_checked("#a"), page.is_checked("#b")] == [False, True]


def test_a_disabled_native_checkbox_still_fails_as_before(page):
    page.set_content('<label><input id="d" type="checkbox" disabled> Opt in</label>')
    box = control(page, "Opt in")
    with pytest.raises(Exception):  # noqa: B017, PT011 - the native path is Playwright's own and keeps its own error
        fill_control(page, box, True, 500)
    assert not page.is_checked("#d")


def test_a_wrapping_label_that_belongs_to_another_checkbox_is_never_clicked(page):
    """A label wrapping two inputs activates only the first. Clicking it for the second would change the wrong box, so it is refused."""
    load(page, '<div class="cb"><label><input id="a" type="checkbox"><input id="b" type="checkbox"><span>Both options</span></label></div>')
    second = next(c for c in discover(page).controls if c.html_id == "b")
    with pytest.raises(ValueError, match="no label"):
        fill_control(page, second, True, 2000)
    assert checked(page, "a", "b") == [False, False] and page.evaluate("window.changes") == 0
