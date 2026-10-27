"""Orchestration: form first, then source, then answers, then browser.

    discover -> understand -> retrieve + plan (+validate) -> fill
             -> (re-discover for conditional fields) -> read-back verify
             -> [optional] submit -> RunResult

`run_form` takes an already-open Playwright Page, so the caller owns
browser launch, navigation, sign-in and tracing; tests drive it with local
fixture pages. `run_url` is the convenience wrapper that does the launch.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from formfill.web import steps as _steps
from formfill.web.discover import discover, find_unsupported
from formfill.web.execute import (
    TEXTLIKE_KINDS,
    UNSETTLED,
    fill_control,
    framework_attached,
    matches,
    read_back,
)
from formfill.web.execute import submit as submit_form
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.plan import build_plan
from formfill.web.result import ItemResult, RunResult, overall_status
from formfill.web.retrieve import index_source
from formfill.web.understand import understand

# After the last answer is entered the run waits this long before its final read-back, so a page that wipes or replaces
# a field shortly after it was typed (an app still booting) is reported as a failure instead of "verified". This is
# detection only: nothing is re-entered, and a reset that happens later than the window is still not seen.
DEFAULT_CONFIRM_MS = 1000
MAX_CONFIRM_MS = 10000


def _wait_for_form_controls(page: Page, readiness_timeout_ms: int) -> bool:
    """Wait briefly for asynchronously rendered controls in the page or frames.

    Navigation's load event does not guarantee that a client-rendered form
    exists. This bounded wait polls actual controls, not an arbitrary sleep;
    it never clicks or submits anything. A timeout is handled as an incomplete
    run by the caller.
    """
    selector = (
        'input, select, textarea, [role="textbox"], [role="combobox"], '
        '[role="radio"], [role="checkbox"], [contenteditable="true"]'
    )
    deadline = time.monotonic() + min(max(readiness_timeout_ms, 1), 10000) / 1000
    while True:
        with contextlib.suppress(Exception):  # a frame may detach during discovery
            for frame in page.frames:
                visible = frame.locator(selector).evaluate_all(
                    """els => els.some(el => {
                        if (typeof el.checkVisibility === "function") return el.checkVisibility();
                        const style = window.getComputedStyle(el);
                        return style.display !== "none" && style.visibility !== "hidden" &&
                            !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    })"""
                )
                if visible:
                    return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            page.wait_for_timeout(min(50, max(1, int(remaining * 1000))))
        except Exception:  # noqa: BLE001 - page may have navigated or closed
            return False


def run_form(
    page: Page,
    source: Any,
    *,
    submit: bool = False,
    submit_selector: str | None = None,
    success_text: str | None = None,
    out_dir: str | Path | None = None,
    max_rounds: int = 3,
    timeout_ms: int = 5000,
    readiness_timeout_ms: int = 5000,
    confirm_ms: int = DEFAULT_CONFIRM_MS,
    policy: _steps.DiscoveryPolicy | None = None,
    acknowledge_unsupported: Iterable[str] = (),
) -> RunResult:
    """...`acknowledge_unsupported`: identifiers (the `ack_id` shown in `result.json`: html id, else name, else label, and only when unique) of OPTIONAL unsupported controls a person has
    explicitly decided to leave unfilled. With submit=True, any unsupported control not listed refuses submission; a REQUIRED
    unsupported control refuses it even when listed (it cannot be answered by this tool)."""
    if not 0 <= confirm_ms <= MAX_CONFIRM_MS:
        raise ValueError(f"confirm_ms must be between 0 and {MAX_CONFIRM_MS}, got {confirm_ms}")
    leaves = index_source(source)
    controls: dict[str, Control] = {}
    items: dict[str, ItemResult] = {}
    navigation: dict = {}
    warnings: list[str] = []

    # The ordinary one-page path has no settle gate. Wait for real controls
    # before its first discovery so JS-rendered forms are not silently missed.
    controls_ready = True
    if policy is None:
        controls_ready = _wait_for_form_controls(page, readiness_timeout_ms)
        if not controls_ready:
            warnings.append(
                "no form controls appeared before the readiness timeout; "
                "the page may still be loading or may not contain a supported form"
            )

    if policy is None:
        # Rounds handle conditional fields: answering one question can reveal more.
        for _ in range(max_rounds):
            schema = discover(page)
            new = [c for c in schema.controls if c.visible and c.control_id not in items]
            if not new:
                break
            questions = understand(new)
            for question, plan in zip(questions, build_plan(questions, leaves)):
                controls[plan.question_id] = question.control
                items[plan.question_id] = _fill_one(page, question.control, plan, timeout_ms)
                _note_interference(page, controls, items, plan.question_id)
    else:
        navigation = _run_steps(page, leaves, controls, items, policy, timeout_ms)
        if navigation.get("stop_reason") == "document_navigation":
            # The document was replaced. Controls are located by ids stamped during discovery, so a final discover and
            # read-back made while the reloaded app is still booting finds nothing and would keep the old "verified"
            # verdict. Give the new document the same bounded readiness gate as a first load before judging it.
            with contextlib.suppress(Exception):  # still navigating or closed: judged below as far as possible
                page.wait_for_load_state("load", timeout=timeout_ms)
            if not _wait_for_form_controls(page, readiness_timeout_ms):
                warnings.append(
                    "the document was replaced and no form controls reappeared before the readiness timeout; "
                    "earlier answers could not be re-checked"
                )

    if confirm_ms and any(i.filled for i in items.values()):
        with contextlib.suppress(Exception):  # page closed or navigating: the read-back below reports what it can
            page.wait_for_timeout(confirm_ms)

    schema = discover(page)
    hidden = [c for c in schema.controls if not c.visible and c.control_id not in items]
    if policy is not None:
        navigation["notes"].extend(schema.notes)

    unsupported = _assign_ack_ids(_merge_unsupported(navigation.get("unsupported", []) if policy is not None else [], find_unsupported(page)))

    # Independent read-back of everything we touched or flagged.
    for qid, item in items.items():
        _judge(page, controls[qid], item, navigation if policy is not None else None, timeout_ms)

    reentered = {q: i for q, i in items.items() if i.reentered}
    if reentered and confirm_ms:
        # the re-entered values must also survive a confirmation window of their own
        with contextlib.suppress(Exception):
            page.wait_for_timeout(confirm_ms)
        for qid, item in reentered.items():
            _judge(page, controls[qid], item, navigation if policy is not None else None, timeout_ms)

    incomplete = policy is not None and navigation.get("stop_reason") in _steps.INCOMPLETE_STOPS
    if not items:
        warnings.append(
            "no form controls were processed; this run cannot be marked FILLED and submission is disabled"
        )
    if incomplete:
        if navigation["stop_reason"] == "no_safe_next_control":
            navigation["completion"] = "unconfirmed"
            navigation["notes"].append({"kind": "completion_unconfirmed", "step": navigation.get("steps_visited"),
                                        "reason": "no recognised next-step control: this is either the last step or a Next button we do not recognise, and the page does not say which"})
            warnings.append("could not confirm the last step was reached (no recognised next-step control); the form was not submitted - review before submitting")
        else:
            navigation["completion"] = "incomplete"
            warnings.append(f"navigation stopped early ({navigation['stop_reason']}); later steps were not filled and the form was not submitted")
    if hidden:
        warnings.append(f"{len(hidden)} control(s) stayed hidden and were not asked")
    if reentered:
        warnings.append(f"{len(reentered)} answer(s) were cleared by the page after a UI framework attached to the field and were re-entered once; "
                        "see each item's detail")
    if unsupported:
        req = [u for u in unsupported if u["required"]]
        names = "; ".join(f"{u['label'] or u['html_id'] or u['tag']} ({u['kind']}{', required' if u['required'] else ''})" for u in unsupported[:8])
        warnings.append(f"{len(unsupported)} visible control(s) cannot be filled by FormFiller and were not touched ({len(req)} required): {names}"
                        + (" ..." if len(unsupported) > 8 else "") + "; a person must handle them")
    interfering = [i for i in items.values() if INTERFERENCE in i.detail]
    if interfering:
        warnings.append(f"{len(interfering)} answer(s) were undone by the page when a later choice was entered "
                        "(the controls behave as one choice); see each item's detail - a human must decide the answer")
    unsettled = [i for i in items.values() if i.detail.startswith(UNSETTLED)]
    if unsettled:
        warnings.append(f"{len(unsettled)} answer(s) were entered while the page was still changing ({UNSETTLED} after leaving the field); "
                        "questions that depend on them may not have been discovered - review before submitting")
    out = Path(out_dir) if out_dir else None
    artifacts: dict = {}
    if out:
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "filled.png"), full_page=True)
        artifacts["screenshot_filled"] = str(out / "filled.png")

    submission: dict = {}
    if submit:
        if not items:
            submission = {
                "attempted": False,
                "outcome": "SKIPPED",
                "detail": "no form controls were processed; refusing to submit an unverified page",
            }
        else:
            blockers = [i for i in items.values() if i.plan.status == "REVIEW" and i.plan.required]
            unsupported_required = [u for u in unsupported if u["required"]]
            acked = {str(a) for a in ([acknowledge_unsupported] if isinstance(acknowledge_unsupported, str) else acknowledge_unsupported)}  # a bare string is one id, not its characters
            unsupported_unacked = [u for u in unsupported if not u["required"] and (u["ack_id"] is None or u["ack_id"] not in acked)]
            # An answer blocks submission if it failed verification OR was never successfully entered (filled=False: the fill or
            # its blur-commit raised, e.g. a blur timeout on a busy page). Its text may still read back correctly, which proves
            # only what the DOM holds, not that the application recorded it; overall_status already treats it as FAILED.
            broken = [i for i in items.values() if i.plan.status == "ANSWER" and (not i.filled or i.verified is False)]
            if unsettled:
                submission = {"attempted": False, "outcome": "SKIPPED", "detail": f"{len(unsettled)} answer(s) were entered on a page that never settled"}
            elif incomplete:
                submission = {"attempted": False, "outcome": "SKIPPED",
                              "detail": (f"navigation stopped early ({navigation['stop_reason']}); the form was not completed"
                                           if navigation["completion"] == "incomplete" else
                                           "completion unconfirmed: no recognised next-step control, so the last step cannot be told from an unknown Next button")}
            elif blockers or broken or unsupported_required or unsupported_unacked:
                submission = {"attempted": False, "outcome": "SKIPPED",
                              "detail": (f"{len(blockers)} required item(s) need review, {len(broken)} answer(s) not entered or failed verification, "
                                         f"{len(unsupported_required)} required control(s) cannot be filled by FormFiller, "
                                         f"{len(unsupported_unacked)} optional unsupported control(s) lack an explicit human decision "
                                         "(pass their ack_id in acknowledge_unsupported to proceed; a control whose ack_id is null is ambiguous and cannot be acknowledged)")}
            else:
                submission = submit_form(page, submit_selector, success_text, timeout_ms)
                if out:
                    page.screenshot(path=str(out / "after_submit.png"), full_page=True)
                    artifacts["screenshot_after_submit"] = str(out / "after_submit.png")

    status = overall_status(list(items.values()), submission if submit else None)
    if unsettled and status == "FILLED":
        status = "NEEDS_REVIEW"  # an unsettled page may hide dependent questions: never "FILLED"
    if incomplete and status in ("FILLED", "SUBMITTED", "SUBMITTED_UNCONFIRMED"):
        status = "NEEDS_REVIEW"  # a walk cut short is never "FILLED"
    if unsupported and status == "FILLED":
        status = "NEEDS_REVIEW"  # a visible control we cannot fill is still open: never "FILLED"
    result = RunResult(
        url=page.url, status=status,
        items=list(items.values()), submission=submission, artifacts=artifacts, warnings=warnings, navigation=navigation,
        unsupported=unsupported,
        controls=[asdict(controls[q]) for q in items],  # what discovery saw (name, id, placeholder, options...), so a run can be diagnosed from result.json alone
    )
    result.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    if out:
        (out / "result.json").write_text(result.to_json())
        result.artifacts["result_json"] = str(out / "result.json")
    return result


def _assign_ack_ids(records: list[dict]) -> list[dict]:
    """Give each record `ack_id`: its html id, else name, else label, but only when that identifier is non-empty and belongs to
    exactly one unsupported control. An empty or shared identifier gets None: such a control can never be acknowledged by
    id, so a duplicate id cannot acknowledge the wrong control (or two at once)."""
    ids = [u.get("html_id") or u.get("name") or u.get("label") or "" for u in records]
    for u, i in zip(records, ids):
        u["ack_id"] = i if i and ids.count(i) == 1 else None
    return records


def _merge_unsupported(*groups: list[dict]) -> list[dict]:
    """Union of unsupported-control records, one per widget (a wizard control seen on an earlier step stays reported)."""
    seen: set = set()
    out: list[dict] = []
    for g in groups:
        for u in g:
            key = (u["kind"], u["label"], u["html_id"], u["name"], u["frame_index"])
            if key not in seen:
                seen.add(key)
                out.append(u)
    return out


REENTERED = "re-entered once"  # appears in the detail of an item that was entered a second time


def _reenter_after_hydration(page: Page, control: Control, item: ItemResult, obs, timeout_ms: int):
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


def _judge(page: Page, control: Control, item: ItemResult, nav: dict | None, timeout_ms: int = 5000) -> None:
    """Read the control back from the page and record what it holds. With `nav` (step navigation), a control that has
    left the DOM keeps its earlier verdict, and one that now differs from a verified answer is a reset."""
    obs = read_back(page, control)
    if obs.found and item.plan.status == "ANSWER" and not matches(item.plan.answer, obs.value):
        obs = _reenter_after_hydration(page, control, item, obs, timeout_ms)
    if nav is not None and not obs.found:
        if item.plan.status == "ANSWER" and item.verified:
            item.detail = (item.detail + " (verified when its step was on screen; no longer in the DOM, not re-checked)").strip()
        return
    was_verified = item.verified
    item.observed = obs.value
    item.browser_valid = obs.valid
    if item.plan.status == "ANSWER":
        ok = obs.found and matches(item.plan.answer, obs.value)
        item.verified = ok
        if not ok:
            item.detail = (item.detail + f" expected {item.plan.answer!r}, page holds {obs.value!r}").strip()
            if nav is not None and was_verified:
                label = item.plan.question
                if label not in nav["resets_detected"]:
                    nav["resets_detected"].append(label)
        elif not obs.valid:
            item.detail = (item.detail + f" browser says invalid: {obs.message}").strip()
    else:
        held = obs.value not in (None, "", False, [])
        item.prefilled_warning = held
        if held:
            item.detail = f"REVIEW control already holds {obs.value!r} (page default) - not our answer"


def _signature(c: Control) -> tuple:
    return (c.label, c.name, c.html_id, c.section, c.kind)


def _run_steps(page: Page, leaves, controls: dict, items: dict, policy: _steps.DiscoveryPolicy, timeout_ms: int) -> dict:
    """Walk a wizard: on each step fill what is on screen (re-discovering after every batch, because answers can reveal
    or enable more controls), verify it, then press the one allowed Next button.

    Submission safety, stated precisely:
    * Default policy (`allow_submit_type_navigation=False`): submit-type navigation controls (form-owned submit
      button/input, image input, off-page link) are refused before any click, and no commit-labelled button is ever
      pressed. The walk itself therefore presses no control that HTML marks as a form submitter. Every walk also ends
      with a stop reason that is in `INCOMPLETE_STOPS` (completion is never confirmed), so `run_form(submit=True)`
      skips the submit routine after a walk. A separate final-step policy would have to be designed before that changes.
    * `allow_submit_type_navigation` is deprecated and has no effect: a submit-type control (or an off-page link) is always
      refused before any click and the walk stops for a person, because a real submission cannot be told from an intercepted
      one until after the click. The post-click submit-event counter (`submit_event_observed`) is only a tripwire, never the
      safety argument.
    * Navigation controls are searched in the main document only, so a portal whose Next/Continue sits inside an open
      shadow root or an iframe stops safely as `no_safe_next_control` even when its fields were discovered and filled.

    Safety order matters: a page that has not settled is never filled or clicked, and a button is refused on its HTML
    metadata (form submit control, off-page link) before any click, never judged after the fact."""
    nav: dict = {"steps_visited": 0, "stop_reason": None, "notes": [], "resets_detected": [], "dialogs_seen": [],
                 "dialogs_accepted": 0, "popups_closed": 0, "step_controls": [], "settle": [],
                 "first_seen": {}, "first_ready": {}}  # control_id -> {"step", "round", "label"}: when each control was first discovered / became fillable
    events: dict = {"dialog": None, "popup": None}

    def on_dialog(d):
        events["dialog"] = f"{d.type}: {d.message}"
        nav["dialogs_seen"].append(events["dialog"])
        d.dismiss()  # never accept: accepting means agreeing to something the form's author asked a person

    def on_popup(p):
        events["popup"] = p.url
        nav["popups_closed"] += 1
        with contextlib.suppress(Exception):  # the popup may already be gone
            p.close()

    def stop(code: str, **note) -> None:
        nav["stop_reason"] = code
        if note:
            nav["notes"].append({"kind": code, **note})

    def stable(step: int, where: str) -> bool:
        """Settle; on failure record why and return False. The caller must then stop: no filling, no clicking."""
        st = _steps.settle(page, policy)
        nav["settle"].append({**st, "step": step, "where": where})
        if st.get("navigated") or not _steps.installed(page):
            stop("document_navigation", step=step, where=where,
                 reason="the document changed under us while waiting for the page to settle; its state is uncertain")
            return False
        if not st["settled"]:
            stop("page_not_settled", step=step, where=where, waited_ms=st["waited"],
                 reason=f"no quiet window of {policy.settle_quiet_ms} ms within {policy.settle_timeout_ms} ms "
                        "(still loading, polling, or constantly re-rendering); nothing was filled or clicked on an unstable page")
            return False
        return True

    page.on("dialog", on_dialog)
    page.on("popup", on_popup)
    try:
        _steps.install(page)
        answered_sigs: set = set()
        prev_visible: tuple | None = None
        for step in range(1, policy.max_steps + 1):
            nav["steps_visited"] = step
            if not stable(step, "step start"):
                break
            step_ids: list[str] = []
            halted = False
            for rnd in range(1, policy.max_rounds_per_step + 1):
                schema = discover(page)
                new = [c for c in schema.controls if c.visible and c.control_id not in items]
                for c in new:
                    nav["first_seen"].setdefault(c.control_id, {"step": step, "round": rnd, "label": c.label})
                dup = [c for c in new if _signature(c) in answered_sigs]  # same question re-rendered (Back, re-mount): not asked twice
                ready = [c for c in new if c not in dup and not c.disabled]
                if not ready:
                    break
                for c in ready:
                    nav["first_ready"].setdefault(c.control_id, {"step": step, "round": rnd, "label": c.label})
                questions = understand(ready)
                for question, plan in zip(questions, build_plan(questions, leaves)):
                    controls[plan.question_id] = question.control
                    items[plan.question_id] = _fill_one(page, question.control, plan, timeout_ms)
                    _note_interference(page, controls, items, plan.question_id)
                    answered_sigs.add(_signature(question.control))
                    step_ids.append(plan.question_id)
                if not stable(step, f"after filling round {rnd}"):
                    halted = True
                    break
            nav["step_controls"].append(step_ids)
            if halted:
                break
            for qid in step_ids:  # verify while the step is still on screen
                _judge(page, controls[qid], items[qid], nav)
            nav["unsupported"] = _merge_unsupported(nav.get("unsupported", []), find_unsupported(page))  # steps that will be left behind
            schema = discover(page)
            for c in schema.controls:
                if c.visible and c.disabled and c.control_id not in items:
                    nav["notes"].append({"kind": "control_stayed_disabled", "step": step, "control": c.label,
                                         "reason": "disabled after every other answer on the step was entered; not filled"})
            visible_now = tuple(sorted(_signature(c) for c in schema.controls if c.visible))
            if prev_visible is not None and visible_now == prev_visible:
                stop("no_change_after_next", step=step, reason="the set of visible controls did not change after pressing Next")
                break
            prev_visible = visible_now

            nb = _steps.next_button(page, policy)
            if nb["state"] == "none":
                stop("no_safe_next_control", step=step, buttons_seen=nb["seen"],
                     reason="no button on the page matches the allowed next-step labels (last step, or a label we will not press)")
                break
            if nb["state"] == "refused":
                stop("submit_type_next_refused", step=step, button=nb["detail"], buttons_seen=nb["seen"],
                     reason="the only next-step-looking button can submit the form or leave the page; refused without clicking")
                break
            if nb["state"] == "disabled":
                stop("next_disabled", step=step, button=nb["text"],
                     reason="the next-step button is disabled; required answers are probably missing (see REVIEW items)")
                break
            before_submits = _steps.submits(page)
            events["dialog"] = events["popup"] = None
            try:
                _steps.click_next(page, nb["index"], timeout_ms)
            except Exception as exc:  # noqa: BLE001
                if events["dialog"]:
                    stop("dialog_on_navigation", step=step, dialog=events["dialog"], reason="dismissed, not accepted")
                else:
                    stop("next_click_failed", step=step, detail=str(exc).splitlines()[0])
                break
            if events["dialog"]:
                stop("dialog_on_navigation", step=step, dialog=events["dialog"], reason="dismissed, not accepted")
                break
            if events["popup"]:
                stop("popup_opened", step=step, url=events["popup"], reason="closed")
                break
            if not stable(step, "after Next"):
                if nav["stop_reason"] == "document_navigation":
                    with contextlib.suppress(Exception):  # best effort: the walk stops here either way
                        page.wait_for_load_state("load", timeout=timeout_ms)
                break
            if _steps.submits(page) > before_submits:
                stop("submit_event_observed", step=step, reason="a form submit event fired during navigation")
                break
            for qid in [q for ids in nav["step_controls"] for q in ids]:  # did moving on discard earlier answers?
                _judge(page, controls[qid], items[qid], nav)
        else:
            nav["stop_reason"] = "max_steps"
    finally:
        page.remove_listener("dialog", on_dialog)
        page.remove_listener("popup", on_popup)
    return nav


# Choice controls that are not grouped by the browser (different or missing `name`) can still be one choice to the
# application: selecting one clears another. Left alone, the earlier answer is simply lost and the report says only that
# the page "holds None". After each choice is entered, the earlier choice answers are read back so the report can say
# which fill undid which answer. Detection only: nothing is re-entered and nothing is chosen between them.
_CHOICE_KINDS = {"radio", "checkbox", "checkbox_group", "select", "multiselect"}
INTERFERENCE = "overwritten by the page when"  # appears in the detail recorded on the earlier answer


def _note_interference(page: Page, controls: dict[str, Control], items: dict[str, ItemResult], just_filled: str) -> None:
    item = items[just_filled]
    control = controls[just_filled]
    if not item.filled or control.kind not in _CHOICE_KINDS:
        return
    for qid, earlier in items.items():
        if qid == just_filled or not earlier.filled or earlier.plan.status != "ANSWER" or INTERFERENCE in earlier.detail:
            continue
        before = controls[qid]
        if before.kind not in _CHOICE_KINDS or before.frame_index != control.frame_index:
            continue
        try:
            obs = read_back(page, before)
        except Exception:  # noqa: BLE001 - the control left the page: the final read-back reports it
            obs = None
        if obs is not None and obs.found and not matches(earlier.plan.answer, obs.value):
            earlier.detail = (f"{earlier.detail} {INTERFERENCE} '{item.plan.question}' was entered (page now holds {obs.value!r}, "
                              f"expected {earlier.plan.answer!r}): the page treats these controls as one choice; a human must decide").strip()
            item.detail = f"{item.detail} entering this answer changed the earlier answer for '{earlier.plan.question}'".strip()


def _fill_one(page: Page, control: Control, plan: AnswerPlanItem, timeout_ms: int) -> ItemResult:
    if plan.status != "ANSWER":
        return ItemResult(plan=plan)
    try:
        warnings = fill_control(page, control, plan.answer, timeout_ms) or []
    except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
        return ItemResult(plan=plan, filled=False, detail=f"fill failed: {str(exc).splitlines()[0]}")
    attached = framework_attached(page, control) if control.kind in TEXTLIKE_KINDS else None
    return ItemResult(plan=plan, filled=True, detail="; ".join(warnings), framework_attached_at_fill=attached)


def run_url(url: str, source_path: str | Path, *, out_dir: str | Path | None = None, trace: bool = True,
            headless: bool = True, **kwargs: Any) -> RunResult:
    """Launch Chromium, open `url`, run the pipeline, optionally save a
    Playwright trace next to the result. `FORMFILL_CHROMIUM` can point at a
    specific Chromium executable."""
    from playwright.sync_api import sync_playwright

    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=exe)
        context = browser.new_context()
        if trace and out_dir:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        try:
            page.goto(url)
            result = run_form(page, source, out_dir=out_dir, **kwargs)
        finally:
            if trace and out_dir:
                trace_path = Path(out_dir) / "trace.zip"
                context.tracing.stop(path=str(trace_path))
            browser.close()
    if trace and out_dir:
        result.artifacts["trace"] = str(Path(out_dir) / "trace.zip")
        (Path(out_dir) / "result.json").write_text(result.to_json())
    return result
