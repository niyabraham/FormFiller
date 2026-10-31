"""Browser layer, step 2: enter the planned answers, read them back, and
(optionally) submit. This module knows *where/how* to type; it never decides
*what* to type -- that is the AnswerPlan's job.

Controls are found by the `data-ff-id` tag written during discovery.
Read-back goes through the DOM (what the page now holds), not through
whatever the fill call returned, because a successful fill call is not the
same thing as a successful fill (the lesson of the PDF PoC's verifier).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from formfill.web.discover import PICKER_ROOT_JS
from formfill.web.models import Control
from formfill.web.netpolicy import redact_url

_TEXTLIKE = {"text", "textarea", "email", "url", "tel", "number", "date", "color"}

TEXTLIKE_KINDS = _TEXTLIKE

# A server-rendered page shows its inputs before the framework has taken them over. When React/Vue/Svelte later attaches to
# a node ("hydration") it may set the node's value to its own state, wiping what was typed before. These internal keys on the
# DOM node are how the framework marks that it now owns it (observed on a public page: the keys first appeared on the field at
# the moment the page's own code assigned `.value = ""`; a value entered after they existed was kept).
_FRAMEWORK_JS = "el => Object.getOwnPropertyNames(el).some(k => /^__(react|vue|svelte)/.test(k))"


def framework_attached(page: Page, control: Control) -> bool | None:
    """True/False: does a UI framework's internal bookkeeping exist on the control's node. None if it cannot be read."""
    try:
        return bool(_locator(page, control).first.evaluate(_FRAMEWORK_JS, timeout=1000))
    except Exception:  # noqa: BLE001 - the node is gone or the page is navigating
        return None


# A react-select-style combobox: its <input role=combobox> only holds the text being searched for and is emptied once an option is
# chosen; the choice is drawn in a sibling element inside the same widget (a `...singleValue` element, or one `...multiValue` chip per
# choice). That element is what the control holds. It is looked for only in the widget around the input: the search stops at the first
# ancestor that also contains another form control, so one widget's selection is never read as another's. No selection element found:
# null, and the input's own value is used, as for any other combobox (RW-10).
_READ_JS = """
els => {
  if (!els.length) return {found: false};
  const e = els[0]; const t = (e.type || '').toLowerCase(); const tag = e.tagName.toLowerCase();
  const shown = c => {
    const hits = Array.from(c.querySelectorAll('[class*="single-value" i],[class*="singlevalue" i],[class*="multi-value" i]:not([class*="remove" i]),[class*="multivalue" i]:not([class*="remove" i])'));
    return hits.filter(h => !hits.some(o => o !== h && o.contains(h))).map(h => (h.textContent || '').replace(/\\s+/g, ' ').trim()).filter(Boolean);
  };
  const chosen = () => {
    for (let c = e.parentElement, i = 0; c && i < 6; c = c.parentElement, i++) {
      if (Array.from(c.querySelectorAll('input,select,textarea,[role=combobox]')).some(x => x !== e && x.type !== 'hidden')) return null;
      const texts = shown(c);
      if (texts.length) return texts.join(', ');
    }
    return null;
  };
  const picked = e.getAttribute('role') === 'combobox' && tag === 'input' ? chosen() : null;
  let value;
  if (e.getAttribute('role') === 'combobox' && tag !== 'input' && tag !== 'select') { value = (e.textContent || '').replace(/\\s+/g, ' ').trim(); return {found: true, value, valid: true, message: ''}; }
  if (picked !== null) { value = picked; }
  else if (t === 'radio') { const c = els.find(x => x.checked); value = c ? c.value : null; }
  else if (t === 'checkbox') { value = els.length > 1 ? els.filter(x => x.checked).map(x => x.value) : e.checked; }
  else if (tag === 'select' && e.multiple) { value = Array.from(e.selectedOptions).map(o => o.value); }
  else { value = e.value; }
  return {found: true, value, valid: els.every(x => x.checkValidity()),
          message: (els.find(x => !x.checkValidity()) || {}).validationMessage || ''};
}
"""


@dataclass
class Observed:
    found: bool
    value: Any = None
    valid: bool = True
    message: str = ""


def _locator(page: Page, control: Control):
    return page.frames[control.frame_index].locator(f'[data-ff-id="{control.control_id}"]')


def fill_control(page: Page, control: Control, answer: Any, timeout_ms: int = 5000) -> list[str]:
    """Enter one validated answer. Raises on any failure; the caller records it. Returns notes for the item (normally empty):
    UNSETTLED when the page was still changing after the field was left, and a note when a date picker popup that a text entry
    left open was closed, or could not be (RW-14, _close_date_popup)."""
    loc = _locator(page, control)
    kind = control.kind
    warnings: list[str] = []
    if kind in _TEXTLIKE:
        before = _popup_state(loc) if kind == "text" else None
        loc.fill(str(answer), timeout=timeout_ms)
        warnings += _commit(page, control, loc, timeout_ms)
        if before is not None and not before["open"]:
            warnings += [w for w in _close_date_popup(page, control, loc, timeout_ms) if w not in warnings]
    elif kind == "combobox":
        _fill_combobox(page, control, loc, answer, timeout_ms)
    elif kind == "select":
        loc.select_option(value=answer, timeout=timeout_ms)
    elif kind == "multiselect":
        loc.select_option(value=list(answer), timeout=timeout_ms)
    elif kind == "radio":
        for member in loc.all():
            if member.get_attribute("value") == answer:
                _select_radio(page, control, member, timeout_ms)
                return warnings
        raise ValueError(f"no radio option with value {answer!r}")
    elif kind == "checkbox":
        _set_checkbox(member=loc, want=bool(answer), timeout_ms=timeout_ms)
    elif kind == "checkbox_group":
        for member in loc.all():
            _set_checkbox(member=member, want=member.get_attribute("value") in answer, timeout_ms=timeout_ms)
    else:
        raise ValueError(f"unsupported control kind {kind!r}")
    return warnings


# After leaving a field, wait for the DOM to be quiet for _QUIET_MS (conditional questions render in response to the
# commit). Reaching the quiet window is "settled"; hitting _SETTLE_MAX_MS first is NOT, and is reported as UNSETTLED.
# A reveal that starts later than _QUIET_MS after the blur (a slow timer, a request) is not waited for in default mode.
_QUIET_MS = 150
_SETTLE_MAX_MS = 1500
UNSETTLED = "page did not go quiet"  # prefix of the ItemResult.detail / RunResult warning recorded for an unsettled commit

_QUIET_JS = """
([quiet, maxms]) => new Promise(resolve => {
  let last = performance.now(); const t0 = last;
  const mo = new MutationObserver(() => { last = performance.now(); });
  mo.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  const tick = () => { const now = performance.now();
    if (now - last >= quiet) { mo.disconnect(); resolve({settled: true, waited: Math.round(now - t0)}); }
    else if (now - t0 >= maxms) { mo.disconnect(); resolve({settled: false, waited: Math.round(now - t0)}); }
    else setTimeout(tick, 20); };
  tick();
})
"""


def _commit(page: Page, control: Control, loc, timeout_ms: int) -> list[str]:
    """Leave the field the way a person does, so frameworks that commit on blur/change record the answer, then let
    the DOM go quiet. Blur is a real focus change, not a synthetic event; it moves focus nowhere. The DOM value
    afterwards is evidence of what the page holds, NOT proof the application recorded it. Returns [UNSETTLED ...] when
    the page never went quiet within _SETTLE_MAX_MS (dependent questions may not have rendered yet)."""
    loc.blur(timeout=timeout_ms)
    try:
        st = page.frames[control.frame_index].evaluate(_QUIET_JS, [_QUIET_MS, _SETTLE_MAX_MS])
    except Exception:  # noqa: BLE001 - a frame that navigated away: nothing left to settle
        return []
    if st.get("settled", True):
        return []
    return [f"{UNSETTLED} within {_SETTLE_MAX_MS} ms after leaving the field; questions that depend on this answer may not have appeared yet"]


# RW-14. A date entry can open a calendar popup that leaving the field does not close: react-datepicker (DemoQA) closes it on a day
# click, Escape, Tab, Enter or a click outside, not on blur, and then moves the keyboard focus into its day grid. The popup covers the
# controls under it, so a later click on them is refused. A person closes it with Escape in the field, and so does FormFiller: once, and
# only when every one of these holds, so that the key cannot close or change anything else:
#   * the widget is react-datepicker (its input sits in `react-datepicker__input-container`, its popup is `react-datepicker-popper`):
#     its Escape closes the popup without touching the chosen date (read from its shipped handlers). Escape is NOT a safe close key in
#     general: bootstrap-datepicker (Selenium's web form) clears a typed date on Escape, so every other picker is left as it is;
#   * the field is a plain <input type=text> in the page's own tree (not a search box, where Escape clears the text);
#   * no such popup (also recognised by discover.PICKER_ROOT_JS, drawn over the page) was showing before the entry, and one is after
#     the field was left;
#   * the field is not inside a dialog or a fixed-position layer, and no other dialog is open: Escape could close those instead;
#   * once the field is focused again, the focus is on the field itself, never in the popup (a key in a day grid can pick a day).
# Nothing is clicked. A popup still open afterwards is left so: a click it covers is refused and reported, never forced. The date read
# back afterwards is what the widget shows once closed, so a typed date the widget did not accept is not reported verified.
_DATE_POPUP_JS = r"""
e => {
  /*PICKER_ROOT*/
  const doc = e.ownerDocument;
  const vis = n => { const r = n.getBoundingClientRect(); if (!(r.width > 0 && r.height > 0)) return false;
    const s = getComputedStyle(n); return s.visibility !== 'hidden' && s.display !== 'none'; };
  const own = a => pickerRoot(a) === a;
  const floating = c => { for (let a = c; a && a.nodeType === 1 && own(a); a = a.parentElement) {
    const p = getComputedStyle(a).position; if (p === 'absolute' || p === 'fixed') return true; } return false; };
  const open = Array.from(doc.querySelectorAll('.react-datepicker-popper, .react-datepicker')).filter(c => vis(c) && floating(c)).length;
  let why = '';
  if (!e.closest('.react-datepicker__input-container')) why = 'the field is not a react-datepicker input';
  else if (e.tagName !== 'INPUT' || (e.type || '').toLowerCase() !== 'text' || e.readOnly || e.disabled) why = 'not a plain text input';
  else if (e.getRootNode() !== doc) why = 'the field is in a shadow root';
  else if (e.closest('dialog,[role=dialog],[role=alertdialog],[aria-modal=true]')) why = 'the field is inside a dialog';
  else {
    for (let a = e.parentElement; a && !why; a = a.parentElement) if (getComputedStyle(a).position === 'fixed') why = 'the field is inside a fixed-position layer';
    if (!why && Array.from(doc.querySelectorAll('dialog[open],[role=dialog],[role=alertdialog],[aria-modal=true]')).some(d => vis(d) && !pickerRoot(d)))
      why = 'another dialog is open';
  }
  return {open, why, focused: doc.activeElement === e};
}
""".replace("/*PICKER_ROOT*/", PICKER_ROOT_JS)
DATE_POPUP = "a date picker popup left open by this entry"  # start of every note _close_date_popup records
DATE_POPUP_CLOSED = f"{DATE_POPUP} was closed with Escape in the field"


def _popup_state(loc) -> dict | None:
    try:
        return loc.evaluate(_DATE_POPUP_JS)
    except Exception:  # noqa: BLE001 - an optional step: a field that cannot be inspected is left exactly as before
        return None


def _close_date_popup(page: Page, control: Control, loc, timeout_ms: int) -> list[str]:
    """RW-14 (see _DATE_POPUP_JS). Called after a text entry and its commit, when no popup was showing before the entry. Returns
    the notes for the item: the warnings of leaving the field again, then one note on the popup; [] when no popup is open."""
    st = _popup_state(loc)
    if not st or not st["open"]:
        return []
    if st["why"]:
        return [f"{DATE_POPUP} was not closed: {st['why']}, where Escape could close something else"]
    try:
        loc.focus(timeout=timeout_ms)
        st = _popup_state(loc)
        if not st or not st["open"]:
            return _commit(page, control, loc, timeout_ms)
        if st["why"] or not st["focused"]:
            return _commit(page, control, loc, timeout_ms) + [
                f"{DATE_POPUP} was not closed: {st['why'] or 'focusing the field moved the focus into the popup'}"]
        loc.press("Escape", timeout=timeout_ms)
        notes = _commit(page, control, loc, timeout_ms)
    except Exception as exc:  # noqa: BLE001 - the entry itself succeeded; its read-back decides, and what the popup covers fails safely
        return [f"{DATE_POPUP} was not closed: {(str(exc).splitlines() or [type(exc).__name__])[0][:160]}"]
    st = _popup_state(loc)
    if st and not st["open"]:
        return notes + [DATE_POPUP_CLOSED]
    return notes + [f"{DATE_POPUP} did not close on Escape; controls under it cannot be clicked"]


_RADIO_HIT_JS = """
e => { const r = e.getBoundingClientRect(); if (!r.width && !r.height) return false;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const t = e.getRootNode().elementFromPoint(x, y); return t === e || e.contains(t); }
"""


def _select_radio(page: Page, control: Control, member, timeout_ms: int) -> None:
    """Select one radio. A native input that is hit-testable is checked as before. A styled radio (tiny/hidden input
    under a decorator that takes the pointer) is selected through its accessible label, the visible target a person
    clicks. The result is verified by the checked state; nothing is set through JavaScript."""
    if member.evaluate(_RADIO_HIT_JS):
        member.check(timeout=timeout_ms)
        return
    label = member.evaluate_handle("e => (e.labels && e.labels[0]) || e.closest('label')").as_element()
    if label is None:
        raise ValueError("unsupported styled radio: the native input is covered and it has no label to click")
    label.click(timeout=timeout_ms)
    if not member.is_checked():
        raise ValueError("styled radio: clicking its label did not select it (selection not confirmed)")


# A label that holds something a click could activate other than its own checkbox (a link to the terms, a button): a click on the
# label's centre could land on it and navigate or act. Such a label is never clicked.
_LABEL_ACTIVE_JS = "l => !!l.querySelector('a[href],button,select,textarea,summary,[role=button],[role=link],input:not([type=checkbox])')"


def _set_checkbox(member, want: bool, timeout_ms: int) -> None:
    """Set one checkbox to `want`. One that already holds it is not touched. A native input that can be hit is set as before. A styled
    checkbox (the input sits under a label that draws the box, so a click on the input is intercepted) is set through its accessible
    label, the visible target a person clicks, exactly as `_select_radio` does for radios. The checked state is read back and a click
    that did not produce it is an error; nothing is set through JavaScript, a disabled box is never changed, and a label that holds a
    link or button is never clicked (RW-11)."""
    if member.is_checked() == want:
        return
    if member.evaluate(_RADIO_HIT_JS):
        member.set_checked(want, timeout=timeout_ms)
        return
    if member.is_disabled():
        raise ValueError("styled checkbox is disabled: not changed")
    # Only a label whose own control is this input: a label wrapping several inputs activates the first one, not this one.
    label = member.evaluate_handle("e => { const l = (e.labels && e.labels[0]) || e.closest('label'); return l && l.control === e ? l : null; }").as_element()
    if label is None:
        raise ValueError("unsupported styled checkbox: the native input is covered and it has no label of its own to click")
    if label.evaluate(_LABEL_ACTIVE_JS):
        raise ValueError("unsupported styled checkbox: its label holds a link or button that a click could activate instead")
    label.click(timeout=timeout_ms)
    if member.is_checked() != want:
        raise ValueError("styled checkbox: clicking its label did not change it (selection not confirmed)")


_OPEN_TIMEOUT_MS = 1500

# What would receive a click at the centre of the combobox? Returns {ok, target, reason}. A click is allowed only when
# the target is the combobox itself or a plain wrapper that belongs to it (contains it, or sits in its immediate container
# that holds no other control). Anything that could navigate, submit or act on something else (button, link, tab, other
# input/select/textarea, or a wrapper that also holds other controls) is refused; the keyboard path is used instead.
_CLICK_TARGET_JS = """
e => {
  const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const t = e.getRootNode().elementFromPoint(x, y);
  const name = n => n ? `<${n.tagName.toLowerCase()}${n.getAttribute('role') ? ' role=' + n.getAttribute('role') : ''}${n.type ? ' type=' + n.type : ''}> ` +
    ((n.textContent || n.value || '').replace(/\\s+/g, ' ').trim().slice(0, 30)) : 'nothing';
  if (!t) return {ok: false, target: 'nothing', reason: 'nothing is drawn at the click point'};
  if (t === e) return {ok: true, target: name(t)};
  const CONTROLS = 'button,a[href],summary,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[tabindex]';
  const risky = t.closest(CONTROLS);
  if (risky && risky !== e && !risky.contains(e)) return {ok: false, target: name(risky), reason: 'the click point is covered by another control'};
  const BAD = ['BODY', 'HTML', 'FORM', 'MAIN', 'FIELDSET', 'SECTION'];
  const owns = c => c && !BAD.includes(c.tagName) && Array.from(c.querySelectorAll(CONTROLS)).every(x => x === e || e.contains(x));
  if (t.contains(e) && owns(t)) return {ok: true, target: name(t)};
  const box = e.parentElement;
  if (box && box.contains(t) && owns(box)) return {ok: true, target: name(t)};
  return {ok: false, target: name(t), reason: 'the click point is covered by an element that is not part of this combobox'};
}
"""


def _open_readonly_combobox(page: Page, control: Control, loc, frame, timeout_ms: int):
    """A readonly combobox cannot be typed into. Open it the way a person does: click where it is drawn (a wrapper
    usually sits over the input, so click the point rather than the element) but ONLY after checking what would receive
    the click (_CLICK_TARGET_JS); if that is another control, or cannot be identified as part of this combobox, nothing
    is clicked and the keyboard path (focus + ArrowDown) is used instead. Returns the visible listbox; raises a clear
    'unsupported' error if no safe interaction opens one."""
    wait = min(timeout_ms, _OPEN_TIMEOUT_MS)
    listbox = frame.locator("[role=listbox]:visible").first
    loc.scroll_into_view_if_needed(timeout=timeout_ms)
    box = loc.bounding_box()
    refused = ""
    if box and box["width"] and box["height"]:
        hit = loc.evaluate(_CLICK_TARGET_JS)
        if hit["ok"]:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            try:
                listbox.wait_for(state="visible", timeout=wait)
                return listbox
            except PlaywrightTimeout:
                pass
        else:
            refused = f"; click refused: {hit['reason']} ({hit['target']})"
    loc.focus(timeout=timeout_ms)
    page.keyboard.press("ArrowDown")
    try:
        listbox.wait_for(state="visible", timeout=wait)
        return listbox
    except PlaywrightTimeout:
        raise ValueError("unsupported readonly combobox: it cannot be typed into and no safe interaction opened its option list "
                         f"(ArrowDown tried{refused})") from None


def _fill_combobox(page: Page, control: Control, loc, answer: Any, timeout_ms: int) -> None:
    """ARIA combobox: open it (type into it, if it is an editable input), pick the option whose text equals the answer,
    and require the popup to close. Typing alone is not an answer: the app commits on selection."""
    frame = page.frames[control.frame_index]
    is_input = loc.evaluate("e => e.tagName === 'INPUT'")
    readonly = bool(loc.evaluate("e => e.readOnly === true || e.getAttribute('aria-readonly') === 'true'")) if is_input else False
    if readonly:
        listbox = _open_readonly_combobox(page, control, loc, frame, timeout_ms)
    elif is_input:
        loc.fill(str(answer), timeout=timeout_ms)
    else:
        loc.click(timeout=timeout_ms)
    if not readonly:
        listbox = frame.locator("[role=listbox]:visible").first
        try:
            listbox.wait_for(state="visible", timeout=min(timeout_ms, 1500))
        except PlaywrightTimeout:
            if is_input:
                return  # free-text combobox with no popup: the typed text stays, read-back decides
            raise ValueError("combobox opened no listbox") from None
    want = str(answer).strip().casefold()
    options = listbox.locator("[role=option]")
    for i in range(options.count()):
        opt = options.nth(i)
        if opt.inner_text().strip().casefold() == want:
            opt.click(timeout=timeout_ms)
            break
    else:
        raise ValueError(f"no option {answer!r} in the combobox list")
    if loc.get_attribute("aria-expanded") == "true":
        raise ValueError("combobox list still open after selecting: selection not confirmed")
    if readonly and (loc.input_value() or "").strip().casefold() != want:
        raise ValueError(f"readonly combobox shows {loc.input_value()!r} after selecting {answer!r}: selection not confirmed")


def read_back(page: Page, control: Control) -> Observed:
    data = _locator(page, control).evaluate_all(_READ_JS)
    return Observed(data["found"], data.get("value"), data.get("valid", True), data.get("message", ""))


def matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, list) or isinstance(observed, list):
        return sorted(map(str, expected or [])) == sorted(map(str, observed or []))
    if isinstance(expected, bool) or isinstance(observed, bool):
        return expected is observed
    return str(expected) == str(observed)


def submit(page: Page, submit_selector: str | None = None, success_text: str | None = None,
           timeout_ms: int = 5000) -> dict:
    """Click submit and report what happened. Outcomes:
    CONFIRMED (success text seen), UNCONFIRMED (clicked, nothing to confirm
    with), BLOCKED_BY_VALIDATION (browser refused: lists the invalid
    controls), NO_SUBMIT_CONTROL, ERROR."""
    loc = page.locator(submit_selector) if submit_selector else page.locator("button[type=submit], input[type=submit]")
    if loc.count() == 0:
        return {"attempted": False, "outcome": "NO_SUBMIT_CONTROL"}
    before = page.url
    try:
        loc.first.click(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - any click failure is reported, not raised
        return {"attempted": True, "outcome": "ERROR", "detail": str(exc).splitlines()[0]}
    with contextlib.suppress(Exception):  # a page that never reaches "load" is judged by what is on screen below
        page.wait_for_load_state("load", timeout=timeout_ms)
    invalid = page.evaluate(
        "() => Array.from(document.querySelectorAll(':invalid')).map(e => e.dataset.ffId || e.name || e.id)"
    )
    info: dict = {"attempted": True, "final_url": redact_url(page.url), "url_changed": page.url != before}
    if invalid and page.url == before and not success_text:
        return {**info, "outcome": "BLOCKED_BY_VALIDATION", "invalid_controls": invalid}
    if success_text:
        try:
            el = page.get_by_text(success_text).first
            el.wait_for(timeout=timeout_ms)
            return {**info, "outcome": "CONFIRMED", "confirmation_text": el.inner_text()[:300]}
        except Exception:  # noqa: BLE001
            if invalid:
                return {**info, "outcome": "BLOCKED_BY_VALIDATION", "invalid_controls": invalid}
            return {**info, "outcome": "UNCONFIRMED", "detail": f"text {success_text!r} not found"}
    return {**info, "outcome": "UNCONFIRMED", "detail": "no success text configured"}
