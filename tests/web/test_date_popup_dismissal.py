"""RW-14 (REAL_WORLD_TESTING_REPORT.md section 15): a date picker popup left open by a date entry covered the controls below it.

On DemoQA, typing the date opens react-datepicker's calendar popup, and leaving the field does not close it: the library's own blur
handler only resets the typed text, and the popup closes on a day click, Escape, Tab, Enter or a click outside (read from the
page's shipped code). Once the field is left, the library moves the keyboard focus into the day grid. The popup covered the Hobbies
checkboxes, so their label clicks were refused and both answers failed (safely: nothing was clicked through it).

A person closes the popup with Escape. FormFiller now does the same, once, but only for react-datepicker, whose Escape was read from
its shipped code and seen to keep the chosen date: Escape is not a safe close key in general (bootstrap-datepicker, on Selenium's web
form, clears a typed date on Escape), so every other picker is left exactly as before. The key is pressed only for a popup that this
entry opened and that is still open after the field was left, and only when it cannot close something else: the field must be a plain
text input, not inside a dialog or a fixed-position layer, with no other dialog open, and the keyboard focus must be on the field
itself when the key is pressed (a key in the day grid can pick another day). Nothing is clicked. A popup that does not close is left
open, and what it covers fails safely as before. The date that is then read back is what the widget shows after closing: a typed date
the widget did not accept is not reported verified.

The page below is a small model written for this project; it copies the behaviour seen in DemoQA's react-datepicker and in Selenium's
bootstrap-datepicker (it is neither library). The real pages were checked separately (report section 15).
"""

from __future__ import annotations

import json

import pytest

from formfill.web.discover import discover
from formfill.web.execute import fill_control
from formfill.web.pipeline import run_form
from formfill.web.result import FieldState, field_state
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

STYLE = """
<style>
 body{font:14px sans-serif;margin:20px} .row{margin:0 0 14px 0} .dob{position:relative;display:inline-block}
 .pop{position:absolute;width:260px;height:230px;background:#fff;border:1px solid #888;z-index:1;overflow:hidden}
 .day{display:inline-block;width:30px;height:24px;text-align:center}
 .cb{position:relative;display:inline-block;margin-right:12px}
 .cb input{position:absolute;opacity:0;z-index:-1}
 .cb label{cursor:pointer;padding-left:24px;position:relative}
 .cb label::before{content:"";position:absolute;left:0;top:0;width:18px;height:18px;border:1px solid #666;background:#fff}
 .cb input:checked + label::before{background:#06c}
</style>
"""

FORM = """
<form id="f">
 <div class="row"><label for="name">Full name</label> <input id="name" type="text"></div>
 <div class="row"><label for="dob">Date of birth</label><br><div class="dob" id="dob-wrap"><div class="{wrap}"><input id="dob" type="text" value="01 Jan 2026"></div></div></div>
 <fieldset class="row"><legend>Hobbies</legend>
  <div class="cb"><input id="h1" type="checkbox" name="hobby" value="1"><label for="h1">Sports</label></div>
  <div class="cb"><input id="h2" type="checkbox" name="hobby" value="2"><label for="h2">Reading</label></div>
  <div class="cb"><input id="h3" type="checkbox" name="hobby" value="3"><label for="h3">Music</label></div>
 </fieldset>
 <button type="submit" id="send">Submit</button>
</form>
"""

# the popup's own markup, per library family; only its outer element is what FormFiller recognises (discover.PICKER_ROOT_JS)
FLAVOURS = {
    # family: (popup markup, where the popup is attached, the wrapper the library puts around its input)
    "react-datepicker": ('<div class="pop react-datepicker-popper"><div class="react-datepicker" role="dialog" aria-label="Choose Date" aria-modal="true">'
                         '<h2 class="react-datepicker__current-month">March 1990</h2><div class="react-datepicker__month" role="listbox">{days}</div></div></div>', "wrap",
                         "react-datepicker__input-container"),
    "flatpickr": ('<div class="pop flatpickr-calendar open"><div class="flatpickr-days">{days}</div></div>', "body", "box"),
    "jQuery UI": ('<div class="pop ui-datepicker ui-widget" id="ui-datepicker-div"><div class="ui-datepicker-title">March 1990</div>{days}</div>', "body", "box"),
    "bootstrap-datepicker": ('<div class="pop datepicker datepicker-dropdown dropdown-menu"><div class="datepicker-days">{days}</div></div>', "body", "box"),
    "ARIA dialog only": ('<div class="pop" role="dialog" aria-label="Choose date"><h2>March 1990</h2><div role="grid">{days}</div></div>', "wrap", "box"),
}

# The widget, modelled on what react-datepicker does on DemoQA: open on focus; a typed date it can read ("dd MMM yyyy") is committed at
# once; leaving the field does NOT close the popup, and with the field left the day grid takes the keyboard focus; Escape in the field
# closes it and redraws the field from the committed date (Tab and an outside click also close it). A key pressed in the day grid
# changes the date (as Enter / the arrow keys do in the real one). OPT switches the variations the tests need.
WIDGET = r"""
<script>
const OPT = __OPT__, MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const S = window.S = {open: false, selected: '2026-01-01', opened: 0, closedBy: [], keys: [], submits: 0, changes: 0, dayClicks: 0, sendClicks: 0};
const input = document.getElementById('dob'), wrap = document.getElementById('dob-wrap');
const fmt = iso => { const [y, m, d] = iso.split('-'); return `${d} ${MONTHS[+m - 1]} ${y}`; };
const parse = s => { const m = /^(\d{2}) ([A-Z][a-z]{2}) (\d{4})$/.exec(s.trim()); const i = m ? MONTHS.indexOf(m[2]) : -1; return i < 0 ? null : `${m[3]}-${String(i + 1).padStart(2, '0')}-${m[1]}`; };
const firstDay = () => document.querySelector('.pop .day');
function open() {
  if (S.open) return; S.open = true; S.opened++;
  let days = ''; for (let d = 1; d <= 31; d++) days += `<div class="day" tabindex="-1" role="gridcell">${d}</div>`;
  const holder = document.createElement('div'); holder.innerHTML = OPT.markup.replace('{days}', days); const pop = holder.firstElementChild;
  if (OPT.host === 'body') { const r = input.getBoundingClientRect(); pop.style.left = (r.left + scrollX) + 'px'; pop.style.top = (r.bottom + scrollY + 2) + 'px'; document.body.appendChild(pop); }
  else { pop.style.left = '0'; pop.style.top = (input.offsetHeight + 2) + 'px'; wrap.appendChild(pop); }
  pop.addEventListener('click', e => { if (e.target.closest('.day')) S.dayClicks++; });
  pop.addEventListener('keydown', e => { if (e.key === 'Escape') close('escape in the day grid'); else S.selected = '1999-09-09'; });
}
function close(by) { if (!S.open) return; S.open = false; S.closedBy.push(by); const p = document.querySelector('.pop'); if (p) p.remove(); input.value = fmt(S.selected); }
input.addEventListener('focus', () => { const was = S.open; open(); if (OPT.focusIntoGrid && was) firstDay().focus(); });
input.addEventListener('input', () => { const iso = parse(input.value); if (iso) S.selected = iso; });
input.addEventListener('keydown', e => {
  if (!S.open) return;
  if (e.key === 'Escape' && OPT.escapeClears) { S.open = false; S.closedBy.push('escape'); document.querySelector('.pop').remove(); input.value = ''; }
  else if (e.key === 'Escape' && !OPT.ignoreEscape) { e.preventDefault(); input.blur(); close('escape'); }
  else if (e.key === 'Tab') close('tab');
});
input.addEventListener('blur', () => {
  if (OPT.closeOnBlur) return close('blur');
  setTimeout(() => { if (S.open && document.activeElement === document.body) firstDay().focus(); }, 0);
});
document.addEventListener('mousedown', e => { if (S.open && !e.target.closest('.pop') && e.target !== input) close('click outside'); });
document.addEventListener('keydown', e => S.keys.push(e.key), true);
document.addEventListener('submit', e => { S.submits++; e.preventDefault(); });
document.addEventListener('change', e => { if (e.target.type === 'checkbox') S.changes++; });
document.getElementById('send').addEventListener('click', () => S.sendClicks++);
if (OPT.openOnLoad) open();
</script>
"""

SOURCE = {"date_of_birth": "15 Mar 1990", "hobbies": ["Sports", "Reading"]}


def form(flavour="react-datepicker"):
    return FORM.replace("{wrap}", FLAVOURS[flavour][2])


def widget(flavour="react-datepicker", **opt):
    markup, host, _ = FLAVOURS[flavour]
    return WIDGET.replace("__OPT__", json.dumps({"markup": markup, "host": host, **opt}))


def load(page, flavour="react-datepicker", around=("", ""), extra="", **opt):
    page.set_content(f"<!doctype html><html><body>{STYLE}{around[0]}{form(flavour)}{around[1]}{extra}{widget(flavour, **opt)}</body></html>")


def state(page):
    return page.evaluate("() => ({...window.S, popupInPage: !!document.querySelector('.pop'), field: document.getElementById('dob').value,"
                         " boxes: ['h1', 'h2', 'h3'].map(i => document.getElementById(i).checked)})")


def item(result, question):
    return next(i for i in result.items if i.plan.question == question)


def assert_nothing_final(st):
    assert st["submits"] == 0 and st["sendClicks"] == 0 and st["dayClicks"] == 0


def run(page, source=SOURCE, **kw):
    return run_form(page, source, confirm_ms=0, timeout_ms=2000, **kw)


# ---- the failure, as it was ------------------------------------------------------------------------------------------------------------


def test_the_model_reproduces_rw14_leaving_the_field_does_not_close_the_popup(page):
    load(page)
    page.fill("#dob", "15 Mar 1990")
    page.locator("#dob").blur()
    page.wait_for_timeout(50)
    st = state(page)
    assert st["open"] and st["popupInPage"] and st["selected"] == "1990-03-15"
    covered = page.evaluate("""() => { const l = document.querySelector('label[for=h1]'); const r = l.getBoundingClientRect();
                                       return !!document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('.pop'); }""")
    assert covered, "the popup must cover the Sports label, as on DemoQA"
    assert page.evaluate("() => !!document.activeElement.closest('.pop')"), "with the field left, the focus is in the day grid"


# ---- the fix -------------------------------------------------------------------------------------------------------------------------


def test_the_popup_left_open_by_the_date_entry_is_closed_and_the_boxes_below_are_set(page):
    load(page)
    result = run(page)
    st = state(page)
    date, hobbies = item(result, "Date of birth"), item(result, "Hobbies")
    assert not st["open"] and not st["popupInPage"] and st["closedBy"] == ["escape"]
    assert date.verified is True and date.observed == "15 Mar 1990", date.detail
    assert st["selected"] == "1990-03-15" and st["field"] == "15 Mar 1990"  # the date the widget holds is the one entered
    assert hobbies.verified is True and sorted(hobbies.observed) == ["1", "2"], hobbies.detail
    assert st["boxes"] == [True, True, False] and st["changes"] == 2  # Music untouched; one click per box that had to change
    assert st["keys"] == ["Escape"]  # one key, nothing else
    assert_nothing_final(st)
    assert result.status != "FAILED"


OTHER_FAMILIES = [f for f in FLAVOURS if f != "react-datepicker"]


@pytest.mark.parametrize("flavour", OTHER_FAMILIES)
def test_other_picker_families_get_no_key_and_keep_the_typed_date(page, flavour):
    """Escape is the close key only where it was verified. Here the bootstrap-datepicker model empties the field on Escape, as the real
    library did on Selenium's web form: no key may be pressed, so the date stays as typed and the covered boxes fail safely, as before."""
    load(page, flavour, escapeClears=(flavour == "bootstrap-datepicker"))
    result = run(page)
    st = state(page)
    assert st["keys"] == [] and st["open"], flavour
    assert st["field"] == "15 Mar 1990" and item(result, "Date of birth").verified is True
    assert "date picker" not in item(result, "Date of birth").detail
    assert item(result, "Hobbies").filled is False and st["boxes"] == [False, False, False]
    assert_nothing_final(st)


def test_the_bootstrap_model_really_clears_on_escape(page):
    """The counterexample is real in the model: one Escape in its field empties the typed date (so the test above means something)."""
    load(page, "bootstrap-datepicker", escapeClears=True)
    page.fill("#dob", "15 Mar 1990")
    page.locator("#dob").press("Escape")
    assert state(page)["field"] == ""


def test_the_close_is_recorded_on_the_date_item(page):
    load(page)
    date = item(run(page), "Date of birth")
    assert "date picker popup" in date.detail and "Escape" in date.detail
    assert field_state(date)[0] is FieldState.VERIFIED


def test_the_same_in_a_guarded_walk(page):
    load(page)
    result = run(page, policy=DiscoveryPolicy())
    st = state(page)
    assert item(result, "Date of birth").verified is True and item(result, "Hobbies").verified is True
    assert st["keys"] == ["Escape"] and not st["open"]
    assert_nothing_final(st)


def test_fill_control_returns_the_note_and_the_field_keeps_the_entered_date(page):
    load(page)
    dob = next(c for c in discover(page).controls if c.html_id == "dob")
    notes = fill_control(page, dob, "15 Mar 1990", 2000)
    st = state(page)
    assert any("closed with Escape" in n for n in notes) and not st["open"]
    assert st["field"] == "15 Mar 1990" and st["selected"] == "1990-03-15"
    assert page.evaluate("() => document.activeElement !== document.getElementById('dob')")  # the field is left, as after any entry


def test_a_typed_date_the_widget_did_not_accept_is_not_reported_verified(page):
    """The widget reads "dd MMM yyyy" only. "1990-03-15" stays as typed while the popup is open; when it closes, the widget shows the date
    it actually holds. Before RW-14 the raw text was read back and reported verified; now the mismatch is reported."""
    load(page)
    result = run(page, {"date_of_birth": "1990-03-15", "hobbies": ["Sports"]})
    date, st = item(result, "Date of birth"), state(page)
    assert st["selected"] == "2026-01-01" and st["field"] == "01 Jan 2026"
    assert date.verified is False and field_state(date)[0] is FieldState.REJECTED
    assert "page holds '01 Jan 2026'" in date.detail
    assert item(result, "Hobbies").verified is True  # the popup is closed either way: the box below is reachable


# ---- when no key may be pressed ----------------------------------------------------------------------------------------------------------

CLOSE_ON_ESCAPE = "<script>document.addEventListener('keydown', e => { if (e.key === 'Escape') { const d = document.getElementById('outer'); if (d) d.remove(); } });</script>"


@pytest.mark.parametrize("around", [
    ('<div id="outer" role="dialog" aria-modal="true" aria-label="Registration">', "</div>"),
    ('<div id="outer" style="position:fixed;inset:0;overflow:auto;background:#fff;padding:20px">', "</div>"),
], ids=["form in a modal dialog", "form in a fixed-position layer"])
def test_no_key_is_pressed_when_escape_could_close_the_form_itself(page, around):
    load(page, around=around, extra=CLOSE_ON_ESCAPE)
    result = run(page)
    st = state(page)
    assert "Escape" not in st["keys"] and page.locator("#outer").count() == 1  # the form's container is still there
    assert st["open"]  # left as it was
    hobbies = item(result, "Hobbies")
    assert hobbies.filled is False and field_state(hobbies)[0] is FieldState.REJECTED  # the covered boxes fail safely, as before
    assert st["boxes"] == [False, False, False] and st["changes"] == 0
    assert_nothing_final(st)


def test_no_key_is_pressed_in_a_native_modal_dialog(page):
    page.set_content("<!doctype html><html><body>" + STYLE + '<dialog id="outer">' + form() + "</dialog>" + widget()
                     + "<script>document.getElementById('outer').showModal();</script></body></html>")
    run(page)
    st = state(page)
    assert "Escape" not in st["keys"] and page.evaluate("() => document.getElementById('outer').open")


def test_no_key_is_pressed_while_another_dialog_is_open(page):
    other = '<div id="outer" role="dialog" aria-label="Cookie preferences" style="position:fixed;right:0;bottom:0;width:200px">Cookies?</div>'
    load(page, extra=other + CLOSE_ON_ESCAPE)
    run(page)
    st = state(page)
    assert "Escape" not in st["keys"] and page.locator("#outer").count() == 1 and st["open"]


def test_a_popup_that_ignores_escape_gets_one_key_and_is_then_left_alone(page):
    load(page, ignoreEscape=True)
    result = run(page)
    st = state(page)
    assert st["keys"] == ["Escape"] and st["open"]  # tried once, never repeated, nothing clicked
    assert "did not close" in item(result, "Date of birth").detail
    assert item(result, "Hobbies").filled is False and st["boxes"] == [False, False, False]
    assert st["selected"] == "1990-03-15"
    assert_nothing_final(st)


def test_no_key_is_pressed_when_the_focus_would_land_in_the_popup(page):
    """A widget that moves the focus into its day grid when the field is focused again: a key there could pick a day."""
    load(page, focusIntoGrid=True)
    result = run(page)
    st = state(page)
    assert st["keys"] == [] and st["open"] and st["selected"] == "1990-03-15"
    assert "not closed" in item(result, "Date of birth").detail
    assert item(result, "Hobbies").filled is False
    assert_nothing_final(st)


def test_a_popup_that_closes_when_the_field_is_left_needs_no_key(page):
    load(page, closeOnBlur=True)
    result = run(page)
    st = state(page)
    assert st["keys"] == [] and st["closedBy"] == ["blur"]
    assert item(result, "Date of birth").verified is True and item(result, "Hobbies").verified is True
    assert "date picker" not in item(result, "Date of birth").detail


def test_a_popup_that_was_open_before_the_entry_is_not_this_entrys_to_close(page):
    load(page, openOnLoad=True)
    run(page)
    assert "Escape" not in state(page)["keys"]


def test_a_text_entry_that_opens_no_popup_gets_no_key(page):
    load(page)
    result = run(page, {"full_name": "Jordan Example", "hobbies": ["Sports"]})
    st = state(page)
    assert item(result, "Full name").verified is True and item(result, "Hobbies").verified is True
    assert st["keys"] == [] and st["opened"] == 0
    assert "date picker" not in item(result, "Full name").detail


def test_a_calendar_that_is_part_of_the_page_neither_blocks_the_close_nor_is_closed(page):
    """An inline calendar drawn in the page (not floating over it) is not a popup: it is not counted as one already open, and stays."""
    load(page, extra='<div id="inline" class="calendar-inline" style="border:1px solid #ccc;width:200px;height:80px">October 2026</div>')
    result = run(page)
    st = state(page)
    assert st["keys"] == ["Escape"] and not st["open"] and page.locator("#inline").count() == 1
    assert item(result, "Hobbies").verified is True
