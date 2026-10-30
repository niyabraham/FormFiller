"""RW-10 (REAL_WORLD_TESTING_REPORT.md section 13.2): a value a react-select control really holds was marked `rejected`.

DemoQA's State / City / Subjects controls are react-select widgets. Their <input role=combobox> only holds the text being
searched for; once an option is chosen the input is emptied and the selection is drawn in a sibling element (`...-singleValue`,
or a `...-multiValue` chip). FormFiller picked the right option (the page showed it) but read back the empty search input, so the
item was `rejected` and the run `FAILED`.

The fixture below has the same structure, written for this project (it is not the real library). It has three behaviours so the
negative cases are real: `commit` records the choice, `ignore` leaves the menu open and records nothing, and `close` shuts the
menu without recording anything (an option that was only displayed, never committed).
"""

from __future__ import annotations

import pytest

from formfill.web.discover import discover
from formfill.web.execute import read_back
from formfill.web.pipeline import run_form
from formfill.web.result import FieldState, field_state

pytestmark = pytest.mark.browser

SOURCE = {"state": "NCR", "subjects": "Maths"}

WIDGET = """
<style>.menu[hidden]{display:none} .menu{border:1px solid #888} .ph{color:#888}</style>
<form onsubmit="return false">
  <label for="rs-state">State</label>
  <div class="rs" id="state-box" data-mode="%(mode)s" data-multi="0">
    <div class="ph">Select State</div>
    <input id="rs-state" role="combobox" aria-expanded="false" aria-haspopup="true" aria-autocomplete="list" type="text" value="" autocomplete="off">
    <div class="menu" role="listbox" hidden>
      <div role="option">NCR</div><div role="option">Haryana</div><div role="option">Rajasthan</div>
    </div>
  </div>
  <label for="rs-subjects">Subjects</label>
  <div class="rs" id="subjects-box" data-mode="%(mode)s" data-multi="1">
    <input id="rs-subjects" role="combobox" aria-expanded="false" aria-haspopup="true" aria-autocomplete="list" type="text" value="" autocomplete="off">
    <div class="menu" role="listbox" hidden>
      <div role="option">Maths</div><div role="option">Physics</div>
    </div>
  </div>
</form>
<script>
document.querySelectorAll('.rs').forEach(box => {
  const input = box.querySelector('input'), menu = box.querySelector('.menu'), mode = box.dataset.mode, multi = box.dataset.multi === '1';
  const filter = () => { const q = input.value.toLowerCase();
    menu.querySelectorAll('[role=option]').forEach(o => { o.hidden = !!q && !o.textContent.toLowerCase().includes(q); }); };
  const open = () => { menu.hidden = false; input.setAttribute('aria-expanded', 'true'); };
  const close = () => { menu.hidden = true; input.setAttribute('aria-expanded', 'false'); };
  input.addEventListener('input', () => { open(); filter(); });
  input.addEventListener('focus', open);
  menu.querySelectorAll('[role=option]').forEach(o => o.addEventListener('click', () => {
    if (mode === 'ignore') return;                     // the app does not react: the menu stays open, nothing is chosen
    if (mode === 'close') { input.value = ''; close(); return; }  // the menu closes and the search text is dropped: nothing was committed
    const text = mode === 'other' ? 'Haryana' : o.textContent;
    box.querySelectorAll('[class*=singleValue],[class*=multiValue]').forEach(e => e.remove());
    const shown = document.createElement('div');
    shown.className = multi ? 'css-1p3m7a8-multiValue' : 'css-1dimb5e-singleValue';
    shown.innerHTML = multi ? '<div class="css-9jq23d"></div><div class="css-xb97g8" aria-hidden="true"><svg height="14" width="14" aria-hidden="true"><path d="M0 0L14 14"></path></svg></div>' : '';
    if (multi) shown.firstChild.textContent = text; else shown.textContent = text;
    box.insertBefore(shown, input);
    const ph = box.querySelector('.ph'); if (ph) ph.remove();
    input.value = ''; close();
  }));
});
</script>
"""


def load(page, mode="commit"):
    page.set_content("<!doctype html><html><body>" + (WIDGET % {"mode": mode}) + "</body></html>")


def item(result, label):
    return next(i for i in result.items if i.plan.question.casefold() == label.casefold())


def test_a_committed_single_selection_is_read_back_and_verified(page):
    load(page)
    result = run_form(page, SOURCE, confirm_ms=0)
    state = item(result, "State")
    assert state.filled and state.verified is True, state.detail
    assert state.observed == "NCR"  # read from the control's displayed selection, not from the empty search input
    assert page.input_value("#rs-state") == ""  # the search input is empty: that is what used to be read


def test_a_committed_multi_value_chip_is_read_back_and_verified(page):
    load(page)
    result = run_form(page, SOURCE, confirm_ms=0)
    subjects = item(result, "Subjects")
    assert subjects.filled and subjects.verified is True, subjects.detail
    assert subjects.observed == "Maths"


def test_the_run_is_not_failed_when_the_page_holds_the_chosen_values(page):
    load(page)
    result = run_form(page, SOURCE, confirm_ms=0)
    assert not [i for i in result.items if i.verified is False]
    assert result.status != "FAILED"


@pytest.mark.parametrize("mode", ["close", "ignore"])
def test_a_selection_the_page_did_not_commit_stays_rejected(page, mode):
    """The option was displayed and clicked, but the control holds nothing: not accepted, and the run says so."""
    load(page, mode)
    result = run_form(page, SOURCE, confirm_ms=0, timeout_ms=1500)
    state = item(result, "State")
    assert field_state(state)[0] is FieldState.REJECTED, f"{mode}: an uncommitted option must not be accepted"
    assert result.status == "FAILED"
    assert page.query_selector("#state-box [class*=singleValue]") is None


def test_a_different_value_on_the_page_is_rejected_not_replaced(page):
    load(page, "other")  # the page commits 'Haryana' whatever was clicked
    result = run_form(page, SOURCE, confirm_ms=0)
    state = item(result, "State")
    assert state.verified is False and state.observed == "Haryana"
    assert "Haryana" in state.detail
    assert result.status == "FAILED"


def test_an_option_shown_in_the_open_list_is_not_a_held_value(page):
    """Read-back looks at what the control holds, never at the options it merely lists."""
    load(page)
    page.focus("#rs-state")  # opens the menu: 'NCR' is displayed as an option, nothing is selected
    assert page.is_visible("#state-box [role=option]")
    state = next(c for c in discover(page).controls if c.label == "State")
    obs = read_back(page, state)
    assert obs.found and obs.value in ("", None)


def test_one_widgets_selection_is_not_read_as_anothers(page):
    load(page)
    page.click("#rs-state")
    page.click("#state-box >> text=NCR")
    controls = {c.label: c for c in discover(page).controls}
    assert read_back(page, controls["State"]).value == "NCR"
    assert read_back(page, controls["Subjects"]).value in ("", None)


# ---- behaviour that must not change ----------------------------------------------------------------------------------------------------


def test_a_native_select_is_read_back_as_before(page):
    page.set_content('<label for="s">State</label><select id="s"><option value="">-</option><option value="NCR">NCR</option></select>')
    result = run_form(page, {"state": "NCR"}, confirm_ms=0)
    state = item(result, "State")
    assert state.verified is True and state.observed == "NCR"


def test_an_editable_combobox_with_no_selection_element_reads_its_own_text(page):
    """A combobox that keeps the chosen text in its own input (no separate selection element) is read from the input, as before."""
    page.set_content(
        '<label for="c">City</label><input id="c" role="combobox" aria-expanded="false" type="text">')
    city = next(c for c in discover(page).controls if c.label == "City")
    page.fill("#c", "Leeds")
    assert read_back(page, city).value == "Leeds"
