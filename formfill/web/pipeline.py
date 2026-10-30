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
import functools
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from formfill.web import steps as _steps
from formfill.web.artifacts import restrict, scrub_trace, secure_dir, write_text_atomic
from formfill.web.discover import discover, find_unsupported
from formfill.web.execute import UNSETTLED
from formfill.web.execute import submit as submit_form
from formfill.web.guard import (  # noqa: F401 - re-exported: callers and tests import these from pipeline
    _NETWORK_GUARDS,
    _activate_wizard_network_guard,
    _context_was_offline,
    _place_websocket_route,
    _request_record,
    _websocket_route_entry,
    release_wizard_network_guard,
)
from formfill.web.matching import MatcherConfig
from formfill.web.models import AnswerPlanItem, Control, Question
from formfill.web.navigation import WizardWalker, _merge_unsupported
from formfill.web.netpolicy import NetworkPolicy, redact_url
from formfill.web.plan import ATTESTATION_REASON_PREFIX, build_plan
from formfill.web.progress import ProgressWriter, Reconciler, ResumeConflict, check_target, load_progress
from formfill.web.report import write_audit_report
from formfill.web.result import ItemResult, RunResult, overall_status
from formfill.web.retrieve import index_source
from formfill.web.understand import understand
from formfill.web.verify import (  # noqa: F401 - re-exported names
    INTERFERENCE,
    REENTERED,
    _fill_one,
    _judge,
    _note_interference,
    _signature,
)

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


def _report_active_guard(run):
    """An exception that escapes `run_form` after the guard started leaves it active on purpose (the page's state is
    unknown, so nothing is let out). Say so on the exception, so it is not a silent state: the context stays offline until
    `release_wizard_network_guard(page)`."""
    @functools.wraps(run)
    def wrapper(*args, **kwargs):
        try:
            return run(*args, **kwargs)
        except BaseException as exc:
            with contextlib.suppress(Exception):
                page = args[0] if args else kwargs["page"]
                state = _NETWORK_GUARDS.get(page.context)
                if state is not None and state["active"]:
                    exc.add_note("FormFiller: the wizard network guard is still active on this browser context (requests are "
                                 "blocked and the context is offline). The walk did not finish and returned no result; call "
                                 "release_wizard_network_guard(page) after reviewing the page, or close the context.")
            raise
    return wrapper


@_report_active_guard
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
    network_policy: NetworkPolicy | None = None,
    checkpoint: Callable[[dict, dict, dict, str], None] | None = None,
    planner: Callable[[list[Question], list], list[AnswerPlanItem]] | None = None,
    progress_path: str | Path | None = None,
    resume: bool = False,
    progress_max_age_hours: float | None = 72.0,
    redact_report: bool = False,
    matcher: MatcherConfig | None = None,
) -> RunResult:
    """...`acknowledge_unsupported`: identifiers (the `ack_id` shown in `result.json`: html id, else name, else label, and only when unique) of OPTIONAL unsupported controls a person has
    explicitly decided to leave unfilled. With submit=True, any unsupported control not listed refuses submission; a REQUIRED
    unsupported control refuses it even when listed (it cannot be answered by this tool).

    `policy`: walks a multi-step form. For the whole walk, and after `run_form` returns, the page's browser context is
    blocked from sending on the channels `_activate_wizard_network_guard` lists; a walk is never complete, so `submit=True` is skipped after it. The
    block ends only when the context closes or `release_wizard_network_guard(page)` is called after a person has reviewed
    the result. Create the context with `service_workers="block"` (`run_url` does); other tabs in that context are blocked too.

    `network_policy` (walks only): explicit allow rules for a portal that must reach its server between steps (see
    formfill/web/netpolicy.py). Default: block everything. `checkpoint(nav, items, controls, event)` is called after each
    verified step and each transition (formfill/web/progress.py uses it to persist resumable state). `planner(questions,
    leaves)` replaces `build_plan` (formfill/web/review.py uses it to apply a person's decisions); it must return one plan
    per question, in order.

    `progress_path`: write a resumable progress file there after every verified step (formfill/web/progress.py). With
    `resume=True` an existing file is loaded and validated first (corrupt, incompatible, stale or other-origin files are
    refused), and controls it already answered are re-verified on the page instead of being entered again. Without
    `resume`, an existing file is refused rather than overwritten. With `out_dir`, an audit report (audit_report.md;
    `redact_report=True` hides the answers) is written next to result.json, owner-only where the OS supports it.

    `matcher` configures the answer-matching layers (formfill/web/matching.py); default: deterministic + evidence checks +
    semantic proposals, no LLM."""
    if not 0 <= confirm_ms <= MAX_CONFIRM_MS:
        raise ValueError(f"confirm_ms must be between 0 and {MAX_CONFIRM_MS}, got {confirm_ms}")
    writer: ProgressWriter | None = None
    reconciler: Reconciler | None = None
    resume_notes: list[str] = []
    if progress_path is not None:
        progress_path = Path(progress_path)
        if resume:
            saved = load_progress(progress_path, max_age_hours=progress_max_age_hours)  # raises ProgressError: nothing touched yet
            resume_notes = check_target(saved, page.url)
            reconciler = Reconciler(saved)
            writer = ProgressWriter(progress_path, page.url, resumed_from=saved["run_id"], previous_fields=saved["fields"])
        elif progress_path.exists():
            raise ValueError(f"progress file {progress_path} already exists: pass resume=True to continue that run, or remove it")
        else:
            writer = ProgressWriter(progress_path, page.url)
    elif resume:
        raise ValueError("resume=True needs progress_path")

    def on_checkpoint(nav: dict, items_: dict, controls_: dict, event: str) -> None:
        if writer is not None:
            writer(nav, items_, controls_, event)
        if checkpoint is not None:
            checkpoint(nav, items_, controls_, event)

    leaves = index_source(source)
    plan_questions = (lambda qs: planner(qs, leaves)) if planner is not None else (lambda qs: build_plan(qs, leaves, matcher))
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
            if reconciler is not None:  # resuming a one-page form: re-verify what the saved run entered instead of entering it again
                fresh = []
                for c in new:
                    try:
                        restored = reconciler(page, c, None)
                    except ResumeConflict as exc:
                        warnings.append(f"resume: {exc}; the control was left for a person")
                        restored = ItemResult(plan=AnswerPlanItem(question_id=c.control_id, question=c.label, field_type=c.kind,
                                                                  required=c.required, status="REVIEW",
                                                                  reason=f"resume ambiguous: {exc}"), section=c.section)
                    if restored is None:
                        fresh.append(c)
                    else:
                        controls[c.control_id], items[c.control_id] = c, restored
                new = fresh
                if not new:
                    continue
            questions = understand(new)
            for question, plan in zip(questions, plan_questions(questions), strict=True):
                controls[plan.question_id] = question.control
                items[plan.question_id] = _fill_one(page, question.control, plan, timeout_ms)
                _note_interference(page, controls, items, plan.question_id)
    else:
        navigation = _run_steps(page, leaves, controls, items, policy, timeout_ms, network=network_policy,
                                checkpoint=on_checkpoint if (writer is not None or checkpoint is not None) else None,
                                planner=plan_questions, reconcile=reconciler)
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

    blocked = (navigation.get("blocked_requests") or []) if policy is not None else []
    incomplete = policy is not None and (navigation.get("stop_reason") in _steps.INCOMPLETE_STOPS or bool(blocked))  # a blocked request is never "complete"
    if blocked:
        first = blocked[0]
        warnings.append(f"{len(blocked)} network request(s) from the page were blocked and not sent (first: {first['method']} "
                        f"{first['url'] or first['resource_type']}); the browser stays blocked until release_wizard_network_guard(page) "
                        "is called after review")
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
        secure_dir(out)
        page.screenshot(path=str(out / "filled.png"), full_page=True)
        restrict(out / "filled.png")
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
            blockers = [
                i for i in items.values()
                if i.plan.status == "REVIEW" and (
                    i.plan.required or (i.plan.reason or "").startswith(ATTESTATION_REASON_PREFIX)
                )
            ]
            unsupported_required = [u for u in unsupported if u["required"]]
            acked = {str(a) for a in ([acknowledge_unsupported] if isinstance(acknowledge_unsupported, str) else acknowledge_unsupported)}  # a bare string is one id, not its characters
            unsupported_unacked = [u for u in unsupported if not u["required"] and (u["ack_id"] is None or u["ack_id"] not in acked)]
            # An answer blocks submission if verification failed, is not current, or it was never successfully entered.
            # DOM read-back is not proof that the application recorded the value.
            broken = [i for i in items.values() if i.plan.status == "ANSWER" and (not i.filled or i.verified is not True)]
            if unsettled:
                submission = {"attempted": False, "outcome": "SKIPPED", "detail": f"{len(unsettled)} answer(s) were entered on a page that never settled"}
            elif incomplete:
                submission = {"attempted": False, "outcome": "SKIPPED",
                              "detail": (f"navigation stopped early ({navigation['stop_reason']}); the form was not completed"
                                           if navigation["completion"] == "incomplete" else
                                           "completion unconfirmed: no recognised next-step control, so the last step cannot be told from an unknown Next button")}
            elif blockers or broken or unsupported_required or unsupported_unacked:
                submission = {"attempted": False, "outcome": "SKIPPED",
                              "detail": (f"{len(blockers)} item(s) require human review, {len(broken)} answer(s) not entered or failed verification, "
                                         f"{len(unsupported_required)} required control(s) cannot be filled by FormFiller, "
                                         f"{len(unsupported_unacked)} optional unsupported control(s) lack an explicit human decision "
                                         "(pass their ack_id in acknowledge_unsupported to proceed; a control whose ack_id is null is ambiguous and cannot be acknowledged)")}
            else:
                submission = submit_form(page, submit_selector, success_text, timeout_ms)
                if out:
                    page.screenshot(path=str(out / "after_submit.png"), full_page=True)
                    restrict(out / "after_submit.png")
                    artifacts["screenshot_after_submit"] = str(out / "after_submit.png")

    status = overall_status(list(items.values()), submission if submit else None)
    if unsettled and status == "FILLED":
        status = "NEEDS_REVIEW"  # an unsettled page may hide dependent questions: never "FILLED"
    if incomplete and status in ("FILLED", "SUBMITTED", "SUBMITTED_UNCONFIRMED"):
        status = "NEEDS_REVIEW"  # a walk cut short is never "FILLED"
    if unsupported and status == "FILLED":
        status = "NEEDS_REVIEW"  # a visible control we cannot fill is still open: never "FILLED"
    result = RunResult(
        url=redact_url(page.url), status=status,
        items=list(items.values()), submission=submission, artifacts=artifacts, warnings=warnings, navigation=navigation,
        unsupported=unsupported,
        controls=[asdict(controls[q]) for q in items],  # what discovery saw (name, id, placeholder, options...), so a run can be diagnosed from result.json alone
    )
    result.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    if resume_notes or reconciler is not None:
        result.warnings.extend(f"resume: {n}" for n in resume_notes)
        if reconciler is not None:
            target = navigation if policy is not None else result.navigation
            target["resume"] = {"from_run": writer.resumed_from if writer else None, "log": reconciler.log,
                                "carried_over": [f["question"] for f in writer.carried_over(controls)] if writer else []}
    if writer is not None:
        writer(navigation if policy is not None else {}, items, controls, "finished")
        result.artifacts["progress"] = str(writer.path)
    if out:
        write_text_atomic(out / "result.json", result.to_json())
        result.artifacts["result_json"] = str(out / "result.json")
        write_audit_report(result, out / "audit_report.md", redact_values=redact_report)
        result.artifacts["audit_report"] = str(out / "audit_report.md")
    return result


def _assign_ack_ids(records: list[dict]) -> list[dict]:
    """Give each record `ack_id`: its html id, else name, else label, but only when that identifier is non-empty and belongs to
    exactly one unsupported control. An empty or shared identifier gets None: such a control can never be acknowledged by
    id, so a duplicate id cannot acknowledge the wrong control (or two at once)."""
    ids = [u.get("html_id") or u.get("name") or u.get("label") or "" for u in records]
    for u, i in zip(records, ids, strict=True):
        u["ack_id"] = i if i and ids.count(i) == 1 else None
    return records


def _run_steps(page: Page, leaves, controls: dict, items: dict, policy: _steps.DiscoveryPolicy, timeout_ms: int,
               network: NetworkPolicy | None = None, checkpoint=None, planner=None, reconcile=None) -> dict:
    """Walk a wizard with the navigation state machine (formfill/web/navigation.py) and return its record.

    Submission safety, stated precisely:
    * A persistent browser-context guard (formfill/web/guard.py) blocks the context's HTTP(S) requests and WebSocket
      connections during and after the walk and keeps the context offline for what routing cannot see. With an explicit
      `network` policy, requests matching its allow rules are relayed by FormFiller (the browser itself stays offline) and
      recorded; nothing else is let out. It remains active until the context closes or `release_wizard_network_guard(page)`.
    * Submit-type navigation controls are refused before any click unless an explicit form-navigation rule covers that form,
      commit-labelled buttons are never pressed, and a capturing listener on `document` cancels submit events. Every walk
      ends incomplete or unconfirmed, so `run_form(submit=True)` skips its own submit routine.
    * A required question that is not verified stops the walk before Next (unless the policy says otherwise)."""
    plan = planner if planner is not None else (lambda qs: build_plan(qs, leaves))
    walker = WizardWalker(page, plan, controls, items, policy, timeout_ms, network=network, checkpoint=checkpoint, reconcile=reconcile)
    return walker.run()


def run_url(url: str, source_path: str | Path, *, out_dir: str | Path | None = None, trace: bool = False,
            headless: bool = True, **kwargs: Any) -> RunResult:
    """Launch Chromium, open `url`, run the pipeline. `FORMFILL_CHROMIUM` can point at a specific Chromium executable.

    `trace=True` (with `out_dir`) also saves a Playwright trace, trace.zip. Off by default since this version (it was on):
    a trace holds the page's content, every response body and the answers entered, and Playwright records the portal's
    session cookies in it. Cookie and authorization values are removed from the saved trace (`artifacts.scrub_trace`)."""
    from playwright.sync_api import sync_playwright

    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=exe)
        context = browser.new_context(service_workers="block")
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
        scrub_trace(Path(out_dir) / "trace.zip")  # rewrites the file owner-only (POSIX)
        result.artifacts["trace"] = str(Path(out_dir) / "trace.zip")
        write_text_atomic(Path(out_dir) / "result.json", result.to_json())
    return result
