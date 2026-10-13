"""Orchestration: form first, then source, then answers, then browser.

    discover -> understand -> retrieve + plan (+validate) -> fill
             -> (re-discover for conditional fields) -> read-back verify
             -> [optional] submit -> RunResult

`run_form` takes an already-open Playwright Page, so the caller owns
browser launch, navigation, sign-in and tracing; tests drive it with local
fixture pages. `run_url` is the convenience wrapper that does the launch.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from formfill.web import steps as _steps
from formfill.web.discover import discover
from formfill.web.execute import fill_control, matches, read_back
from formfill.web.execute import submit as submit_form
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.plan import build_plan
from formfill.web.result import ItemResult, RunResult, overall_status
from formfill.web.retrieve import index_source
from formfill.web.understand import understand


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
    policy: _steps.DiscoveryPolicy | None = None,
) -> RunResult:
    leaves = index_source(source)
    controls: dict[str, Control] = {}
    items: dict[str, ItemResult] = {}
    navigation: dict = {}

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
    else:
        navigation = _run_steps(page, leaves, controls, items, policy, timeout_ms)

    schema = discover(page)
    hidden = [c for c in schema.controls if not c.visible and c.control_id not in items]
    if policy is not None:
        navigation["notes"].extend(schema.notes)

    # Independent read-back of everything we touched or flagged.
    for qid, item in items.items():
        _judge(page, controls[qid], item, navigation if policy is not None else None)

    incomplete = policy is not None and navigation.get("stop_reason") in _steps.INCOMPLETE_STOPS
    warnings = []
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
    out = Path(out_dir) if out_dir else None
    artifacts: dict = {}
    if out:
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "filled.png"), full_page=True)
        artifacts["screenshot_filled"] = str(out / "filled.png")

    submission: dict = {}
    if submit:
        blockers = [i for i in items.values() if i.plan.status == "REVIEW" and i.plan.required]
        broken = [i for i in items.values() if i.plan.status == "ANSWER" and i.verified is False]
        if incomplete:
            submission = {"attempted": False, "outcome": "SKIPPED",
                          "detail": (f"navigation stopped early ({navigation['stop_reason']}); the form was not completed"
                                       if navigation["completion"] == "incomplete" else
                                       "completion unconfirmed: no recognised next-step control, so the last step cannot be told from an unknown Next button")}
        elif blockers or broken:
            submission = {"attempted": False, "outcome": "SKIPPED",
                          "detail": f"{len(blockers)} required item(s) need review, {len(broken)} failed verification"}
        else:
            submission = submit_form(page, submit_selector, success_text, timeout_ms)
            if out:
                page.screenshot(path=str(out / "after_submit.png"), full_page=True)
                artifacts["screenshot_after_submit"] = str(out / "after_submit.png")

    status = overall_status(list(items.values()), submission if submit else None)
    if incomplete and status in ("FILLED", "SUBMITTED", "SUBMITTED_UNCONFIRMED"):
        status = "NEEDS_REVIEW"  # a walk cut short is never "FILLED"
    result = RunResult(
        url=page.url, status=status,
        items=list(items.values()), submission=submission, artifacts=artifacts, warnings=warnings, navigation=navigation,
    )
    result.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    if out:
        (out / "result.json").write_text(result.to_json())
        result.artifacts["result_json"] = str(out / "result.json")
    return result


def _judge(page: Page, control: Control, item: ItemResult, nav: dict | None) -> None:
    """Read the control back from the page and record what it holds. With `nav` (step navigation), a control that has
    left the DOM keeps its earlier verdict, and one that now differs from a verified answer is a reset."""
    obs = read_back(page, control)
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
    * Explicit opt-in (`allow_submit_type_navigation=True`): the walk may click a submit-type control labelled like a
      Next button. That is risky: if the portal does not intercept the click, the click IS a real submission. The
      post-click submit-event counter (`submit_event_observed`) is only a second line of defence; it runs after the click,
      sees DOM `submit` events in the main document only, and cannot detect script-driven submissions (fetch/XHR posts,
      `form.submit()`, submissions from an iframe). Do not read any of this as "every submission is prevented".
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
        try:
            p.close()
        except Exception:  # noqa: BLE001
            pass

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
                    try:
                        page.wait_for_load_state("load", timeout=timeout_ms)
                    except Exception:  # noqa: BLE001
                        pass
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


def _fill_one(page: Page, control: Control, plan: AnswerPlanItem, timeout_ms: int) -> ItemResult:
    if plan.status != "ANSWER":
        return ItemResult(plan=plan)
    try:
        fill_control(page, control, plan.answer, timeout_ms)
    except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
        return ItemResult(plan=plan, filled=False, detail=f"fill failed: {str(exc).splitlines()[0]}")
    return ItemResult(plan=plan, filled=True)


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
