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
import warnings as _warnings
import weakref
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
from formfill.web.plan import ATTESTATION_REASON_PREFIX, build_plan
from formfill.web.result import ItemResult, RunResult, overall_status
from formfill.web.retrieve import index_source
from formfill.web.sharedworkers import SharedWorkerFence, install_fence
from formfill.web.understand import understand

# After the last answer is entered the run waits this long before its final read-back, so a page that wipes or replaces
# a field shortly after it was typed (an app still booting) is reported as a failure instead of "verified". This is
# detection only: nothing is re-entered, and a reset that happens later than the window is still not seen.
DEFAULT_CONFIRM_MS = 1000
MAX_CONFIRM_MS = 10000
_NETWORK_GUARDS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


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
) -> RunResult:
    """...`acknowledge_unsupported`: identifiers (the `ack_id` shown in `result.json`: html id, else name, else label, and only when unique) of OPTIONAL unsupported controls a person has
    explicitly decided to leave unfilled. With submit=True, any unsupported control not listed refuses submission; a REQUIRED
    unsupported control refuses it even when listed (it cannot be answered by this tool).

    `policy`: walks a multi-step form. For the whole walk, and after `run_form` returns, the page's browser context is
    blocked from sending on the channels `_activate_wizard_network_guard` lists; a walk is never complete, so `submit=True` is skipped after it. The
    block ends only when the context closes or `release_wizard_network_guard(page)` is called after a person has reviewed
    the result. Create the context with `service_workers="block"` (`run_url` does); other tabs in that context are blocked too."""
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
    """Read the control back from the page. Unmounted controls lose their current verdict; a changed remount is a reset."""
    obs = read_back(page, control)
    if obs.found and item.plan.status == "ANSWER" and not matches(item.plan.answer, obs.value):
        obs = _reenter_after_hydration(page, control, item, obs, timeout_ms)
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


def _signature(c: Control) -> tuple:
    return (c.label, c.name, c.html_id, c.section, c.kind)


def release_wizard_network_guard(page: Page) -> None:
    """Allow network traffic again for this context after an explicit human review. This is the only way the guard ends
    (besides closing the context). It stops blocking and puts the context back to the connectivity it had when the guard
    started: online, or offline if the caller had already emulated that (Playwright cannot report it, so it is inferred; see
    `_context_was_offline`). Call it before navigating on, and only once a person has decided it is safe. Calling it again, or
    on a context with no active guard, does nothing, so it never overrides what the caller has set since."""
    context = page.context
    state = _NETWORK_GUARDS.get(context)
    if state is None or not state["active"]:
        return
    state["active"] = False
    state["blocked_requests"] = None
    state["fence"].release()
    if not state["prior_offline"]:
        with contextlib.suppress(Exception):  # the context may already be closed
            context.set_offline(False)
    state["ws_parked"] = _place_websocket_route(context, state["ws_route"], first=False)
    if not state["ws_parked"]:
        _warnings.warn(
            "FormFiller could not move its WebSocket route behind yours; WebSocket routes registered on this context before "
            "the first guarded walk stay shadowed (their sockets connect to the real server). Register them again, or use a "
            "fresh context for walks.", RuntimeWarning, stacklevel=2)


def _context_was_offline(page: Page) -> bool:
    """Whether the caller had this context offline before the guard. Playwright has no getter for `set_offline`, so ask the
    page. A page that reports itself offline is either emulated offline or on a host that really has no network; a fresh
    context in the same browser tells those apart without any network traffic. When the browser cannot be asked (a
    persistent context) an offline page is taken to be the caller's own setting, the cautious reading."""
    if page.evaluate("() => navigator.onLine"):
        return False
    browser = page.context.browser
    if browser is None:
        return True
    probe = browser.new_context()
    try:
        return bool(probe.new_page().evaluate("() => navigator.onLine"))  # online here means this context's offline is emulated
    finally:
        probe.close()


def _websocket_route_entry(context, handler):
    """The client's own record of the WebSocket route just registered for `handler` (the sync API wraps handlers, so it is
    found by what the wrapper closes over), or None when the client does not keep one in the expected place."""
    try:
        for entry in context._impl_obj._web_socket_routes:
            if any(cell.cell_contents is handler for cell in entry.handler.__closure__ or ()):
                return entry
    except Exception:  # noqa: BLE001 - another Playwright version
        pass
    return None


def _place_websocket_route(context, entry, *, first: bool) -> bool:
    """Playwright has no way to remove a WebSocket route, and the first matching one wins, so where the guard's sits decides
    whether it shadows the caller's mocks: in front while the guard is active (so nothing a caller registered earlier can
    answer), behind everyone's once released (so their mocks answer, and anything unmatched connects normally). This reorders
    the list the client keeps (`_impl_obj._web_socket_routes`); returns False when that internal list is not there."""
    try:
        routes = context._impl_obj._web_socket_routes
        routes.remove(entry)  # ValueError if it is no longer there
        routes.insert(0, entry) if first else routes.append(entry)
        return True
    except Exception:  # noqa: BLE001 - another Playwright version: the caller decides what that means
        return False


def _request_record(url: str, method: str, resource_type: str, navigation: bool = False) -> dict:
    """What is kept about a blocked request: scheme, host and path only. The query string and fragment may carry form data."""
    try:
        parsed = urlsplit(url)
        shown = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except ValueError:  # an unparsable URL must never stop the request from being aborted
        shown = url.split("?", 1)[0].split("#", 1)[0]
    return {"url": shown, "method": method, "resource_type": resource_type, "navigation": navigation}


def _activate_wizard_network_guard(page: Page, blocked_requests: list[dict]) -> dict:
    """Block the context's network traffic until `release_wizard_network_guard`. Layers, because none is complete alone:

    * a context route that aborts every HTTP(S) request Playwright can see, and records it;
    * a context WebSocket route that never connects (the page sees an OPEN socket that goes nowhere);
    * `set_offline(True)`, which also fails what routing cannot see: prefetch hints, WebSockets opened inside dedicated
      workers, and requests a caller-installed `page.route(...)` passes through with `continue_()` (measured on Playwright
      1.64.1, Chromium; see tests/web/test_network_guard.py). Failures it causes are recorded through `requestfailed`;
    * the SharedWorker measures of `formfill.web.sharedworkers`, because neither routing nor offline emulation reaches them.

    Connectivity is context-wide: every page in the context goes offline (and gets `offline`/`online` events), not only the one
    being walked. The caller's own offline setting is recorded first and put back by the release.

    Not covered: connections the page opened before this call (WebSocket traffic of those was dropped in the measurement
    made; a SharedWorker's is stopped only where the DevTools protocol is available), a SharedWorker created during the walk
    by a script that holds the browser's original constructor and a blob: script, and anything outside the browser. While the guard is idle the HTTP
    route defers to the caller's routes, and the WebSocket route is moved behind them (`_place_websocket_route`).

    Returns what the walk should report: the SharedWorker fence in use."""
    context = page.context
    state = _NETWORK_GUARDS.get(context)
    if state is None:
        state = {"active": False, "blocked_requests": None, "prior_offline": False, "fence": None, "ws_route": None, "ws_parked": False}

        def record(entry: dict) -> None:
            if state["blocked_requests"] is not None:
                state["blocked_requests"].append(entry)

        def handle_request(route) -> None:
            if not state["active"]:
                route.fallback()
                return
            request = route.request
            try:
                record(_request_record(request.url, request.method, request.resource_type, request.is_navigation_request()))
            finally:
                route.abort("blockedbyclient")  # fail closed: aborted even if recording failed

        def handle_websocket(route) -> None:
            if state["active"]:
                record(_request_record(route.url, "WEBSOCKET", "websocket"))
                # Neither connect nor close: Playwright's sync close() can block the browser while a page is constructing a
                # WebSocket. The page therefore sees an open socket; whatever it sends is not forwarded anywhere.
            else:
                route.connect_to_server()

        def handle_failed(request) -> None:
            if state["active"] and "ERR_INTERNET_DISCONNECTED" in (request.failure or ""):
                record(_request_record(request.url, request.method, request.resource_type, request.is_navigation_request()))

        route_web_socket = getattr(context, "route_web_socket", None)
        if not callable(route_web_socket):
            raise RuntimeError("installed Playwright does not support WebSocket request interception (needs 1.48 or newer)")
        context.route("**/*", handle_request)
        try:
            route_web_socket("**/*", handle_websocket)
        except Exception:
            context.unroute("**/*", handle_request)
            raise
        state["ws_route"] = _websocket_route_entry(context, handle_websocket)
        context.on("requestfailed", handle_failed)
        _NETWORK_GUARDS[context] = state
    elif not state["active"] and state["ws_parked"] and not _place_websocket_route(context, state["ws_route"], first=True):
        # released earlier and parked behind the caller's routes; a caller's mock could now answer before the guard does
        raise RuntimeError("the WebSocket guard route could not be put back in front of the caller's routes")
    elif not state["active"]:
        state["ws_parked"] = False  # in front again (or never moved)

    was_active = state["active"]
    prior_offline = state["prior_offline"] if was_active else _context_was_offline(page)  # before anything is changed
    fence = SharedWorkerFence(page)
    try:
        install_fence(page)
        fence.engage()
        state["blocked_requests"] = blocked_requests
        context.set_offline(True)  # raises if it cannot be applied: the caller then refuses to interact with the page
    except BaseException:
        fence.release()
        if not was_active:
            state["blocked_requests"] = None
            with contextlib.suppress(Exception):
                context.set_offline(prior_offline)  # whatever was applied, the context goes back to how the caller had it
        raise
    if was_active:
        state["fence"].release()
    state.update(fence=fence, prior_offline=prior_offline, active=True)
    return {"fence": fence}


def _run_steps(page: Page, leaves, controls: dict, items: dict, policy: _steps.DiscoveryPolicy, timeout_ms: int) -> dict:
    """Walk a wizard: on each step fill what is on screen (re-discovering after every batch, because answers can reveal
    or enable more controls), verify it, then press the one allowed Next button.

    Submission safety, stated precisely:
    * A persistent browser-context guard (see `_activate_wizard_network_guard`) aborts HTTP(S) requests and new WebSocket
      connections during and after a wizard walk, including form navigations, `form.submit()`, `requestSubmit()`, fetch,
      XHR, popups and requests from dedicated workers and service workers, and puts the context offline for what routing
      cannot see, and contains SharedWorkers (formfill.web.sharedworkers). It remains active until the context closes or
      `release_wizard_network_guard(page)` is called after human review; if this function raises, it stays active and the
      exception says so. A controlled service worker is refused. Limits: connections the page opened before the walk, and
      the SharedWorker gaps listed in docs/OUTPUT_DESIGN.md.
    * Submit-type navigation controls are refused before any click, commit-labelled buttons are never pressed, and a
      capturing listener on `document` cancels submit events (a `window`-level capturing handler runs before it; the
      network layers stop what that handler sends). A request blocked during the walk stops it with
      `NEEDS_REVIEW`; every walk also ends incomplete, so `run_form(submit=True)` skips its own submit routine.
    * `allow_submit_type_navigation` is deprecated and has no effect: a submit-type control (or an off-page link) is always
      refused before any click.
    * Navigation controls are searched in the main document only, so a portal whose Next/Continue sits inside an open
      shadow root or an iframe stops safely as `no_safe_next_control` even when its fields were discovered and filled.

    Safety order matters: a page that has not settled is never filled or clicked, and a button is refused on its HTML
    metadata (form submit control, off-page link) before any click, never judged after the fact."""
    nav: dict = {"steps_visited": 0, "stop_reason": None, "notes": [], "resets_detected": [], "dialogs_seen": [],
                 "dialogs_accepted": 0, "popups_closed": 0, "step_controls": [], "settle": [],
                 "first_seen": {}, "first_ready": {}, "blocked_requests": []}
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

    reported_apis = 0
    fence: SharedWorkerFence | None = None

    def stable(step: int, where: str) -> bool:
        """Settle; on failure record why and return False. The caller must then stop: no filling, no clicking."""
        nonlocal reported_apis
        st = _steps.settle(page, policy)
        nav["settle"].append({**st, "step": step, "where": where})
        apis = _steps.blocked_apis(page)
        for api in apis[reported_apis:]:
            nav["blocked_requests"].append({"url": "", "method": "CONSTRUCT", "resource_type": api.lower(), "navigation": False})
        reported_apis = max(reported_apis, len(apis))
        if fence is not None:  # a SharedWorker that appeared since the guard started: taken offline now, and reported
            try:
                appeared = fence.scan()
            except Exception:  # noqa: BLE001 - one that cannot be contained must stop the walk like one that was seen
                appeared = [""]
            for url in appeared:
                nav["blocked_requests"].append(_request_record(url, "CONSTRUCT", "sharedworker"))
        if nav["blocked_requests"]:
            stop("outbound_request_blocked", step=step, where=where, request=nav["blocked_requests"][-1],
                 reason="page network traffic was blocked; the wizard stopped for human review")
            return False
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

    if page.evaluate("() => Boolean(navigator.serviceWorker && navigator.serviceWorker.controller)"):
        stop("service_worker_controls_page",
             reason="the page has an active service worker that can bypass Playwright request routing")
        return nav
    # A registered worker that does not control this page can still be woken by it (a message, a push) and send. Routing
    # blocked that on Playwright 1.64.1 but not on 1.48.0 (a message-triggered fetch reached the local server), so any
    # registration for the page's origin, or any running worker in the context, is refused whatever the installed version.
    registered = page.evaluate("() => navigator.serviceWorker ? navigator.serviceWorker.getRegistrations().then(r => r.length, () => 0) : 0")
    if registered or page.context.service_workers:
        stop("service_worker_registered", registrations=registered, running=len(page.context.service_workers),
             reason="a service worker is registered for this page's origin or running in this context; its requests are not reliably "
                    "blocked on every Playwright version, so nothing was filled or clicked. Create the context with service_workers='block'")
        return nav
    try:
        fence = _activate_wizard_network_guard(page, nav["blocked_requests"])["fence"]
        nav["network_guard_active"] = True
    except Exception as exc:
        stop("network_guard_unavailable", detail=str(exc).splitlines()[0],
             reason="the outbound request boundary could not be established; no wizard interaction was performed")
        return nav
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
                for c in dup:
                    sig = _signature(c)
                    prior_qid = next((qid for qid, prior in controls.items() if _signature(prior) == sig), None)
                    if prior_qid is not None:
                        controls[prior_qid] = c
                        _judge(page, c, items[prior_qid], nav, timeout_ms)
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
                if nav["blocked_requests"]:
                    stop("outbound_request_blocked", step=step, request=nav["blocked_requests"][-1],
                         reason="page network traffic was blocked; the wizard stopped for human review")
                elif events["dialog"]:
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
    if nav.get("network_guard_active"):
        nav["notes"].append({
            "kind": "network_guard_active",
            "reason": "outbound requests remain blocked until the browser context closes or release_wizard_network_guard(page) is called after human review; "
                      "the whole browser context was put offline, so other pages in it were affected too, and a page that reacts to "
                      "going offline (disabled inputs, an overlay) may have stopped this walk for that reason",
        })
        if fence is not None and fence.available:
            if fence.neutralised:
                nav["notes"].append({"kind": "shared_worker_taken_offline", "count": fence.neutralised,
                                     "reason": "SharedWorkers that already existed in this context were put offline through the DevTools protocol"})
        else:
            nav["notes"].append({"kind": "shared_worker_check_unavailable",
                                 "reason": "the DevTools protocol is not available here (not Chromium, or a persistent context), so a SharedWorker "
                                           "created before the walk could not be found or stopped"})
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
    attached = framework_attached(page, control) if control.kind in TEXTLIKE_KINDS else None
    try:
        warnings = fill_control(page, control, plan.answer, timeout_ms) or []
    except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
        return ItemResult(plan=plan, filled=False, detail=f"fill failed: {str(exc).splitlines()[0]}")
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
        result.artifacts["trace"] = str(Path(out_dir) / "trace.zip")
        (Path(out_dir) / "result.json").write_text(result.to_json())
    return result
