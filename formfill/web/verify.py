"""Field-level fill and verification: enter one planned answer, read it back with the control's own semantics, and judge
what the page holds. A value is "verified" only when a read-back of the live control matches the intended answer and the
browser reports the control valid; a fill call that did not raise is not evidence. Nothing here chooses an answer, and a
value the page rejected or changed is never silently replaced with another one.

Moved out of pipeline.py (unchanged behaviour) so the navigation state machine and the resume logic can use the same
judgement as a one-page run.
"""

from __future__ import annotations

from playwright.sync_api import Page

from formfill.web.execute import TEXTLIKE_KINDS, fill_control, framework_attached, matches, read_back
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.result import ItemResult

REENTERED = "re-entered once"  # appears in the detail of an item that was entered a second time


def reenter_after_hydration(page: Page, control: Control, item: ItemResult, obs, timeout_ms: int):
    """A text answer that is gone, on the SAME node, after a UI framework attached to that node since the answer was typed, was
    most likely overwritten by the framework taking the server-rendered input over (a value typed before hydration is lost; one
    typed after it is kept: measured on a public page, see README). Enter it once more and read it back. Only then: no framework
    evidence at fill time or none now means a real reset and is left as a failure; a second loss is also left as a failure.
    The answer re-entered is the one already planned and validated; nothing is chosen or guessed, and the report says so."""
    if (item.reentered or not item.filled or item.framework_attached_at_fill is not False
            or control.kind not in TEXTLIKE_KINDS or framework_attached(page, control) is not True):
        return obs
    try:
        fill_control(page, control, item.plan.answer, timeout_ms)
    except Exception as exc:  # noqa: BLE001 - recorded, the item stays failed
        item.detail = f"{item.detail} re-entry after the framework attached failed: {str(exc).splitlines()[0]}".strip()
        return obs
    item.reentered = True
    item.detail = (f"{item.detail} {REENTERED}: the value was cleared after a UI framework attached to this field "
                   "(it had not when the answer was first typed)").strip()
    return read_back(page, control)


def judge(page: Page, control: Control, item: ItemResult, nav: dict | None, timeout_ms: int = 5000) -> None:
    """Read the control back from the page. Unmounted controls lose their current verdict; a changed remount is a reset."""
    obs = read_back(page, control)
    if obs.found and item.plan.status == "ANSWER" and not matches(item.plan.answer, obs.value):
        obs = reenter_after_hydration(page, control, item, obs, timeout_ms)
    if nav is not None and not obs.found:
        if item.plan.status == "ANSWER":
            if item.ever_verified and "no longer in the DOM" not in item.detail:
                item.detail = (item.detail + " (verified when its step was on screen; no longer in the DOM, not re-checked)").strip()
            item.verified = None
            item.observed = None
            item.browser_valid = None
        return
    item.detail = item.detail.replace(
        "(verified when its step was on screen; no longer in the DOM, not re-checked)", ""
    ).strip()
    was_verified = item.ever_verified
    item.observed = obs.value
    item.browser_valid = obs.valid if obs.found else None
    if item.plan.status == "ANSWER":
        ok = obs.found and matches(item.plan.answer, obs.value) and obs.valid
        item.verified = ok
        if ok:
            item.ever_verified = True
        if not ok:
            mismatch = f"expected {item.plan.answer!r}, page holds {obs.value!r}"
            if mismatch not in item.detail:
                item.detail = (item.detail + f" {mismatch}").strip()
            if nav is not None and was_verified:
                label = item.plan.question
                if label not in nav["resets_detected"]:
                    nav["resets_detected"].append(label)
        if obs.found and not obs.valid:
            invalid = f"browser says invalid: {obs.message}"
            if invalid not in item.detail:
                item.detail = (item.detail + f" {invalid}").strip()
    else:
        held = obs.value not in (None, "", False, [])
        item.prefilled_warning = held
        if held:
            item.detail = f"REVIEW control already holds {obs.value!r} (page default) - not our answer"


def signature(c: Control) -> tuple:
    return (c.label, c.name, c.html_id, c.section, c.kind)


# Choice controls that are not grouped by the browser (different or missing `name`) can still be one choice to the
# application: selecting one clears another. Left alone, the earlier answer is simply lost and the report says only that
# the page "holds None". After each choice is entered, the earlier choice answers are read back so the report can say
# which fill undid which answer. Detection only: nothing is re-entered and nothing is chosen between them.
CHOICE_KINDS = {"radio", "checkbox", "checkbox_group", "select", "multiselect"}
INTERFERENCE = "overwritten by the page when"  # appears in the detail recorded on the earlier answer


def note_interference(page: Page, controls: dict[str, Control], items: dict[str, ItemResult], just_filled: str) -> None:
    item = items[just_filled]
    control = controls[just_filled]
    if not item.filled or control.kind not in CHOICE_KINDS:
        return
    for qid, earlier in items.items():
        if qid == just_filled or not earlier.filled or earlier.plan.status != "ANSWER" or INTERFERENCE in earlier.detail:
            continue
        before = controls[qid]
        if before.kind not in CHOICE_KINDS or before.frame_index != control.frame_index:
            continue
        try:
            obs = read_back(page, before)
        except Exception:  # noqa: BLE001 - the control left the page: the final read-back reports it
            obs = None
        if obs is not None and obs.found and not matches(earlier.plan.answer, obs.value):
            earlier.detail = (f"{earlier.detail} {INTERFERENCE} '{item.plan.question}' was entered (page now holds {obs.value!r}, "
                              f"expected {earlier.plan.answer!r}): the page treats these controls as one choice; a human must decide").strip()
            item.detail = f"{item.detail} entering this answer changed the earlier answer for '{earlier.plan.question}'".strip()


def fill_one(page: Page, control: Control, plan: AnswerPlanItem, timeout_ms: int, step: int | None = None) -> ItemResult:
    if plan.status != "ANSWER":
        return ItemResult(plan=plan, section=control.section, step=step)
    attached = framework_attached(page, control) if control.kind in TEXTLIKE_KINDS else None
    try:
        warnings = fill_control(page, control, plan.answer, timeout_ms) or []
    except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
        return ItemResult(plan=plan, filled=False, attempted=True, section=control.section, step=step,
                          detail=f"fill failed: {str(exc).splitlines()[0]}")
    return ItemResult(plan=plan, filled=True, attempted=True, section=control.section, step=step, detail="; ".join(warnings),
                      framework_attached_at_fill=attached)


def entered_texts(answer) -> list[str]:
    """The strings an entered answer can appear as in a request (for the network policy's answer-data check)."""
    if isinstance(answer, bool) or answer is None:
        return []
    if isinstance(answer, (list, tuple)):
        return [str(a) for a in answer if not isinstance(a, bool)]
    return [str(answer)]


# Old private names, kept for callers that imported them from pipeline.
_judge = judge
_fill_one = fill_one
_note_interference = note_interference
_signature = signature
