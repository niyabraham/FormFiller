"""Browser layer, step 2: enter the planned answers, read them back, and
(optionally) submit. This module knows *where/how* to type; it never decides
*what* to type -- that is the AnswerPlan's job.

Controls are found by the `data-ff-id` tag written during discovery.
Read-back goes through the DOM (what the page now holds), not through
whatever the fill call returned, because a successful fill call is not the
same thing as a successful fill (the lesson of the PDF PoC's verifier).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page

from formfill.web.models import Control

_TEXTLIKE = {"text", "textarea", "email", "url", "tel", "number", "date"}

_READ_JS = """
els => {
  if (!els.length) return {found: false};
  const e = els[0]; const t = (e.type || '').toLowerCase(); const tag = e.tagName.toLowerCase();
  let value;
  if (t === 'radio') { const c = els.find(x => x.checked); value = c ? c.value : null; }
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


def fill_control(page: Page, control: Control, answer: Any, timeout_ms: int = 5000) -> None:
    """Enter one validated answer. Raises on any failure; the caller records it."""
    loc = _locator(page, control)
    kind = control.kind
    if kind in _TEXTLIKE:
        loc.fill(str(answer), timeout=timeout_ms)
    elif kind == "select":
        loc.select_option(value=answer, timeout=timeout_ms)
    elif kind == "multiselect":
        loc.select_option(value=list(answer), timeout=timeout_ms)
    elif kind == "radio":
        for member in loc.all():
            if member.get_attribute("value") == answer:
                member.check(timeout=timeout_ms)
                return
        raise ValueError(f"no radio option with value {answer!r}")
    elif kind == "checkbox":
        loc.set_checked(bool(answer), timeout=timeout_ms)
    elif kind == "checkbox_group":
        for member in loc.all():
            member.set_checked(member.get_attribute("value") in answer, timeout=timeout_ms)
    else:
        raise ValueError(f"unsupported control kind {kind!r}")


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
    try:
        page.wait_for_load_state("load", timeout=timeout_ms)
    except Exception:  # noqa: BLE001
        pass
    invalid = page.evaluate(
        "() => Array.from(document.querySelectorAll(':invalid')).map(e => e.dataset.ffId || e.name || e.id)"
    )
    info: dict = {"attempted": True, "final_url": page.url, "url_changed": page.url != before}
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
