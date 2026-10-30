"""Browser layer: the wizard navigation state machine.

A guarded walk through a multi-step questionnaire, as explicit states and checked transitions rather than a click-Next loop:

    PREFLIGHT -> GUARDING -> [ SETTLING -> FILLING -> VERIFYING -> GATING -> ADVANCING -> CONFIRMING -> REVERIFYING ]* -> STOPPED
                                                                                    (optional) -> REVISITING -> STOPPED

For every step:

1. SETTLING    wait for a quiet page (no DOM churn, no pending fetch/XHR, no aria-busy); never act on an unstable page.
2. FILLING     discover visible controls, plan answers (validated, evidence-backed), enter them; re-discover after each batch,
               because answers can reveal or enable more controls (conditional fields).
3. VERIFYING   read every answer of the step back from the live control.
4. GATING      a REQUIRED question that is not verified (REVIEW, failed, unsupported) stops the walk before Next is pressed,
               unless the policy says the portal validates on its own (`advance_with_unresolved_required`).
5. ADVANCING   press the one allowed Next control (explicit allow list, commit-style deny list, submit controls refused unless
               an explicit network-policy rule permits that form's step POST).
6. CONFIRMING  a click is not a transition: take a snapshot (URL, headings, step indicator, visible questions, validation
               messages) and classify it against the step before: ADVANCED, NO_CHANGE, VALIDATION_ERROR, LOOP (back to a
               visited step), REDIRECTED (another origin), or a replaced document. Anything but ADVANCED stops the walk.
7. REVERIFYING read the answers of earlier steps that are still on the page: a value the move discarded is a reset.

A checkpoint callback receives the state after each verified step and each transition, so progress can be persisted and a
walk resumed (formfill/web/progress.py). The walk never presses a final Submit/Sign/Certify/Accept control: those labels are
denied, and every walk ends "incomplete" or "unconfirmed", so `run_form(submit=True)` never submits after one.

`revisit_with_back`: after the forward walk reaches the last recognisable step, press Back step by step (client-side wizards),
read every earlier answer again, and return forward. This turns "verified while on screen" into "still held after navigating".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from formfill.web import steps as _steps
from formfill.web.discover import discover, find_unsupported
from formfill.web.guard import _activate_wizard_network_guard, _request_record
from formfill.web.models import AnswerPlanItem, Control, FormSchema, Question
from formfill.web.netpolicy import NetworkPolicy, origin_of, redact_url
from formfill.web.progress import ResumeConflict
from formfill.web.result import FieldState, ItemResult, field_state
from formfill.web.sharedworkers import SharedWorkerFence
from formfill.web.understand import understand
from formfill.web.verify import entered_texts, fill_one, judge, note_interference, signature


class NavState(str, Enum):
    PREFLIGHT = "preflight"
    GUARDING = "guarding"
    SETTLING = "settling"
    FILLING = "filling"
    VERIFYING = "verifying"
    GATING = "gating"
    ADVANCING = "advancing"
    CONFIRMING = "confirming"
    REVERIFYING = "reverifying"
    REVISITING = "revisiting"
    STOPPED = "stopped"


class Outcome(str, Enum):
    ADVANCED = "advanced"
    NO_CHANGE = "no_change"
    VALIDATION_ERROR = "validation_error"
    LOOP = "loop"
    REDIRECTED = "redirected"


_SNAPSHOT_JS = r"""
() => {
  const vis = e => { try { return e.checkVisibility ? e.checkVisibility() : !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); } catch (x) { return true; } };
  const txt = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const pick = sel => Array.from(document.querySelectorAll(sel)).filter(vis).map(txt).filter(Boolean);
  const indicator = pick('[aria-current="step"],[role=tab][aria-selected="true"],[aria-current="page"][role=tab],.step.active,.active-step,.current-step');
  const headings = pick('h1,h2,h3');
  const legends = pick('legend');
  const errors = pick('[role=alert],[aria-live=assertive],.error,.errors,.field-error,.invalid-feedback,.error-message,[data-error]');
  const invalid = Array.from(document.querySelectorAll('[aria-invalid="true"]')).filter(vis)
    .map(e => e.getAttribute('aria-label') || e.name || e.id || e.tagName.toLowerCase());
  return {url: location.href, indicator: indicator.slice(0, 3).join(' | ').slice(0, 200),
          headings: headings.slice(0, 8).map(t => t.slice(0, 160)), legends: legends.slice(0, 8).map(t => t.slice(0, 160)),
          errors: errors.slice(0, 10).map(t => t.slice(0, 200)),
          invalid: invalid.slice(0, 10)};
}
"""


def _sig_key(c: Control) -> tuple[str, ...]:
    return tuple("" if x is None else str(x) for x in signature(c))


@dataclass(frozen=True)
class StepSnapshot:
    """What identifies the step on screen. The fingerprint deliberately ignores control ids (a re-render of the same step
    gets new nodes) and validation messages (a refused Next shows them on the same step)."""

    url: str
    indicator: str
    headings: tuple[str, ...]  # visible h1-h3, in page order
    signatures: tuple[tuple[str, ...], ...]
    control_ids: frozenset[str]
    errors: tuple[str, ...]
    legends: tuple[str, ...] = ()  # fieldset legends: part of what identifies a step, but not its title

    @property
    def origin(self) -> str:
        return origin_of(self.url)

    @property
    def fingerprint(self) -> str:
        try:
            p = urlsplit(self.url)
            where = f"{p.path}?{p.query}#{p.fragment}"
        except ValueError:
            where = self.url
        raw = json.dumps([where, self.indicator, list(self.headings), list(self.legends), [list(s) for s in self.signatures]])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def describe(self) -> dict:
        try:
            path = urlsplit(self.url).path
        except ValueError:
            path = ""
        return {"fingerprint": self.fingerprint, "path": path, "indicator": self.indicator,
                "heading": next((h for h in reversed(self.headings) if h), ""), "questions": len(self.signatures),
                "errors": list(self.errors)}


def take_snapshot(page: Page, schema: FormSchema) -> StepSnapshot:
    data = page.evaluate(_SNAPSHOT_JS)
    visible = [c for c in schema.controls if c.visible]
    errors = tuple(data["errors"]) + tuple(f"marked invalid: {x}" for x in data["invalid"])
    return StepSnapshot(url=data["url"], indicator=data["indicator"], headings=tuple(data["headings"]),
                        signatures=tuple(sorted(_sig_key(c) for c in visible)),
                        control_ids=frozenset(c.control_id for c in visible), errors=errors, legends=tuple(data["legends"]))


def classify(before: StepSnapshot, after: StepSnapshot, visited: dict[str, int], current_step: int, start_origin: str) -> Outcome:
    """What pressing Next did. Pure: the decision table is tested without a browser."""
    if start_origin and after.origin and after.origin != start_origin:
        return Outcome.REDIRECTED
    if after.fingerprint == before.fingerprint:
        return Outcome.VALIDATION_ERROR if after.errors else Outcome.NO_CHANGE
    earlier = visited.get(after.fingerprint)
    if earlier is not None and earlier < current_step:
        return Outcome.LOOP
    return Outcome.ADVANCED


def unresolved_required(step_ids: list[str], items: dict[str, ItemResult], controls: dict[str, Control],
                        unsupported: list[dict]) -> list[dict]:
    """Required questions on the step that a person still has to answer before the step can be left."""
    out = []
    for qid in step_ids:
        item, control = items[qid], controls[qid]
        if not (control.required or item.plan.required):
            continue
        state, why = field_state(item)
        if state is not FieldState.VERIFIED:
            out.append({"question": item.plan.question, "state": state.value, "why": why})
    for u in unsupported:
        if u.get("required"):
            out.append({"question": u.get("label") or u.get("html_id") or u.get("tag"), "state": "unsupported",
                        "why": u.get("reason", "")})
    return out


_ID_NUM = re.compile(r"c(\d+)$")
# Stops after which the page is in a known, settled state where going Back is harmless: the end of the recognisable wizard, or
# a step that waits for a person. Every other stop (a blocked request, an unstable page, a dialog, ...) ends the walk as it is.
_REVISIT_AFTER = frozenset({"no_safe_next_control", "required_unresolved", "next_disabled"})

Planner = Callable[[list[Question]], list[AnswerPlanItem]]
Reconciler = Callable[[Page, Control, int | None], ItemResult | None]
Checkpoint = Callable[[dict, dict, dict, str], None]


class WizardWalker:
    """One guarded walk. `run()` returns the navigation record (`RunResult.navigation`). `items`/`controls` are filled in place,
    keyed by question id, exactly as the one-page path does."""

    def __init__(self, page: Page, planner: Planner, controls: dict, items: dict, policy: _steps.DiscoveryPolicy, timeout_ms: int,
                 network: NetworkPolicy | None = None, checkpoint: Checkpoint | None = None, reconcile: Reconciler | None = None):
        self.page, self.planner, self.controls, self.items = page, planner, controls, items
        self.policy, self.timeout_ms = policy, timeout_ms
        self.network = network or NetworkPolicy()
        self._checkpoint, self.reconcile = checkpoint, reconcile
        self.entered: set[str] = set()
        self.fence: SharedWorkerFence | None = None
        self.downloads = None
        self.reported_apis = 0
        self.visited: dict[str, int] = {}  # step fingerprint -> first step index it was seen at
        self.path: list[str] = []  # forward path of step fingerprints
        self.start_origin = ""
        self.id_floor = 0
        self.events: dict = {"dialog": None, "popup": None}
        self.nav: dict = {"steps_visited": 0, "stop_reason": None, "notes": [], "resets_detected": [], "dialogs_seen": [],
                          "dialogs_accepted": 0, "popups_closed": 0, "step_controls": [], "settle": [],
                          "first_seen": {}, "first_ready": {}, "blocked_requests": [], "permitted_requests": [],
                          "state": NavState.PREFLIGHT.value, "state_history": [], "steps": [],
                          "network_mode": "block_all" if self.network.blocks_everything else "allow_listed",
                          "network_policy": self.network.to_dict(), "versions": _versions(page)}

    # ---- bookkeeping -------------------------------------------------------------------------------------------------------
    def state(self, s: NavState, step: int = 0, **detail) -> None:
        self.nav["state"] = s.value
        history = self.nav["state_history"]
        if len(history) < 400:
            history.append({"state": s.value, "step": step, **detail})

    def stop(self, code: str, **note) -> None:
        self.nav["stop_reason"] = code
        if note:
            self.nav["notes"].append({"kind": code, **note})
        self.state(NavState.STOPPED, note.get("step", 0), reason=code)

    def checkpoint(self, event: str) -> None:
        if self._checkpoint is None:
            return
        try:
            self._checkpoint(self.nav, self.items, self.controls, event)
        except Exception as exc:  # noqa: BLE001 - losing a checkpoint must not hide the walk's own outcome
            self.nav["notes"].append({"kind": "checkpoint_failed", "event": event, "detail": str(exc).splitlines()[0][:200]})

    def _bump_floor(self, schema: FormSchema) -> None:
        for c in schema.controls:
            m = _ID_NUM.search(c.control_id)
            if m:
                self.id_floor = max(self.id_floor, int(m.group(1)))

    # ---- page events -------------------------------------------------------------------------------------------------------
    def _on_dialog(self, d) -> None:
        self.events["dialog"] = f"{d.type}: {d.message}"
        self.nav["dialogs_seen"].append(self.events["dialog"])
        d.dismiss()  # never accept: accepting means agreeing to something the form's author asked a person

    def _on_popup(self, p) -> None:
        self.events["popup"] = p.url
        self.nav["popups_closed"] += 1
        with contextlib.suppress(Exception):  # the popup may already be gone
            p.close()

    # ---- settle + safety checks --------------------------------------------------------------------------------------------
    def stable(self, step: int, where: str) -> bool:
        """Settle; on failure record why and return False. The caller must then stop: no filling, no clicking."""
        page, nav, policy = self.page, self.nav, self.policy
        self.state(NavState.SETTLING, step, where=where)
        st = _steps.settle(page, policy)
        nav["settle"].append({**st, "step": step, "where": where})
        apis = _steps.blocked_apis(page)
        for api in apis[self.reported_apis:]:
            nav["blocked_requests"].append({"url": "", "method": "CONSTRUCT", "resource_type": api.lower(), "navigation": False})
        self.reported_apis = max(self.reported_apis, len(apis))
        if self.fence is not None:  # a SharedWorker that appeared since the guard started: taken offline now, and reported
            try:
                appeared = self.fence.scan()
            except Exception:  # noqa: BLE001 - one that cannot be contained must stop the walk like one that was seen
                appeared = [""]
            for url in appeared:
                nav["blocked_requests"].append(_request_record(url, "CONSTRUCT", "sharedworker"))
        if nav["blocked_requests"]:
            self.stop("outbound_request_blocked", step=step, where=where, request=nav["blocked_requests"][-1],
                      reason="page network traffic was blocked; the wizard stopped for human review")
            return False
        if st.get("navigated") or not _steps.installed(page):
            self.stop("document_navigation", step=step, where=where,
                      reason="the document changed under us while waiting for the page to settle; its state is uncertain")
            return False
        if not st["settled"]:
            self.stop("page_not_settled", step=step, where=where, waited_ms=st["waited"],
                      reason=f"no quiet window of {policy.settle_quiet_ms} ms within {policy.settle_timeout_ms} ms "
                             "(still loading, polling, or constantly re-rendering); nothing was filled or clicked on an unstable page")
            return False
        return True

    def _preflight(self) -> bool:
        page = self.page
        self.state(NavState.PREFLIGHT)
        if page.evaluate("() => Boolean(navigator.serviceWorker && navigator.serviceWorker.controller)"):
            self.stop("service_worker_controls_page",
                      reason="the page has an active service worker that can bypass Playwright request routing")
            return False
        # A registered worker that does not control this page can still be woken by it (a message, a push) and send. Routing
        # blocked that on Playwright 1.64.1 but not on 1.48.0 (a message-triggered fetch reached the local server), so any
        # registration for the page's origin, or any running worker in the context, is refused whatever the installed version.
        registered = page.evaluate("() => navigator.serviceWorker ? navigator.serviceWorker.getRegistrations().then(r => r.length, () => 0) : 0")
        if registered or page.context.service_workers:
            self.stop("service_worker_registered", registrations=registered, running=len(page.context.service_workers),
                      reason="a service worker is registered for this page's origin or running in this context; its requests are not reliably "
                             "blocked on every Playwright version, so nothing was filled or clicked. Create the context with service_workers='block'")
            return False
        return True

    def _start_guard(self) -> bool:
        self.state(NavState.GUARDING)
        try:
            guard = _activate_wizard_network_guard(self.page, self.nav["blocked_requests"], self.network,
                                                   self.nav["permitted_requests"], self.entered)
            self.fence, self.downloads = guard["fence"], guard["downloads"]
            self.nav["network_guard_active"] = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.stop("network_guard_unavailable", detail=str(exc).splitlines()[0],
                      reason="the outbound request boundary could not be established; no wizard interaction was performed")
            return False

    # ---- filling one step --------------------------------------------------------------------------------------------------
    def _remember(self, qid: str, item: ItemResult) -> None:
        if item.filled:
            self.entered.update(entered_texts(item.plan.answer))

    def _fill_step(self, step: int, answered_sigs: set) -> tuple[list[str], bool]:
        page, nav, items, controls = self.page, self.nav, self.items, self.controls
        step_ids: list[str] = []
        for rnd in range(1, self.policy.max_rounds_per_step + 1):
            self.state(NavState.FILLING, step, round=rnd)
            schema = discover(page)
            self._bump_floor(schema)
            new = [c for c in schema.controls if c.visible and c.control_id not in items]
            for c in new:
                nav["first_seen"].setdefault(c.control_id, {"step": step, "round": rnd, "label": c.label})
            dup = [c for c in new if signature(c) in answered_sigs]  # same question re-rendered (Back, re-mount): not asked twice
            for c in dup:
                sig = signature(c)
                prior_qid = next((qid for qid, prior in controls.items() if signature(prior) == sig), None)
                if prior_qid is not None:
                    controls[prior_qid] = c
                    judge(page, c, items[prior_qid], nav, self.timeout_ms)
            ready = [c for c in new if c not in dup and not c.disabled]
            if self.reconcile is not None:  # resuming: a control the saved run already answered is re-verified, not re-entered
                still = []
                for c in ready:
                    try:
                        restored = self.reconcile(page, c, step)
                    except ResumeConflict as exc:
                        self.stop("resume_ambiguous", step=step, detail=str(exc),
                                  reason="the page cannot be matched to the saved progress without guessing; a person must check it")
                        return step_ids, True
                    if restored is None:
                        still.append(c)
                        continue
                    controls[c.control_id] = c
                    items[c.control_id] = restored
                    self._remember(c.control_id, restored)
                    answered_sigs.add(signature(c))
                    step_ids.append(c.control_id)
                ready = still
            if not ready:
                break
            for c in ready:
                nav["first_ready"].setdefault(c.control_id, {"step": step, "round": rnd, "label": c.label})
            questions = understand(ready)
            for question, plan in zip(questions, self.planner(questions), strict=True):
                controls[plan.question_id] = question.control
                items[plan.question_id] = fill_one(page, question.control, plan, self.timeout_ms, step=step)
                self._remember(plan.question_id, items[plan.question_id])
                note_interference(page, controls, items, plan.question_id)
                answered_sigs.add(signature(question.control))
                step_ids.append(plan.question_id)
            if not self.stable(step, f"after filling round {rnd}"):
                return step_ids, True
        return step_ids, False

    # ---- the forward walk --------------------------------------------------------------------------------------------------
    def _press(self, step: int, nb: dict) -> bool:
        """Press the chosen control and wait for the page; returns False (after recording a stop) when the walk must end."""
        page, nav = self.page, self.nav
        self.state(NavState.ADVANCING, step, button=nb["text"], form_navigation=bool(nb.get("form_navigation")))
        before_submits = _steps.submits(page)
        self.events["dialog"] = self.events["popup"] = None
        expect_document = bool(nb.get("form_navigation"))
        try:
            if expect_document:
                rule = nb["form_navigation"]
                nav["notes"].append({"kind": "form_navigation", "step": step, "button": nb["text"],
                                     "rule": rule.note or f"{rule.origin}{rule.path}",
                                     "reason": "a Next control that posts its form was pressed because an explicit network-policy rule allows it"})
                _steps.allow_next_submit(page)
                try:
                    with page.expect_navigation(timeout=self.timeout_ms, wait_until="load"):
                        _steps.click_next(page, nb["index"], self.timeout_ms)
                except PlaywrightTimeout:
                    with contextlib.suppress(Exception):
                        page.evaluate("() => { window.__ffAllowNextSubmit = false; }")  # never leave the one-time pass open
                else:
                    _steps.install(page)
                    _steps.set_id_floor(page, self.id_floor)
            else:
                _steps.click_next(page, nb["index"], self.timeout_ms)
        except Exception as exc:  # noqa: BLE001
            if nav["blocked_requests"]:
                self.stop("outbound_request_blocked", step=step, request=nav["blocked_requests"][-1],
                          reason="page network traffic was blocked; the wizard stopped for human review")
            elif self.events["dialog"]:
                self.stop("dialog_on_navigation", step=step, dialog=self.events["dialog"], reason="dismissed, not accepted")
            else:
                self.stop("next_click_failed", step=step, detail=str(exc).splitlines()[0])
            return False
        if self.events["dialog"]:
            self.stop("dialog_on_navigation", step=step, dialog=self.events["dialog"], reason="dismissed, not accepted")
            return False
        if self.events["popup"]:
            self.stop("popup_opened", step=step, url=redact_url(self.events["popup"]), reason="closed")
            return False
        if not self.stable(step, "after Next"):
            if nav["stop_reason"] == "document_navigation":
                with contextlib.suppress(Exception):  # best effort: the walk stops here either way
                    page.wait_for_load_state("load", timeout=self.timeout_ms)
            return False
        if _steps.submits(page) > before_submits:
            self.stop("submit_event_observed", step=step, reason="a form submit event fired during navigation")
            return False
        return True

    def _forward(self) -> None:
        page, nav, items, controls, policy = self.page, self.nav, self.items, self.controls, self.policy
        answered_sigs: set = set()
        form_navigation = None if self.network.blocks_everything else self.network.form_navigation_rule
        for step in range(1, policy.max_steps + 1):
            nav["steps_visited"] = step
            if not self.stable(step, "step start"):
                return
            step_ids, halted = self._fill_step(step, answered_sigs)
            nav["step_controls"].append(step_ids)
            if halted:
                return
            self.state(NavState.VERIFYING, step)
            for qid in step_ids:  # verify while the step is still on screen
                judge(page, controls[qid], items[qid], nav)
            here_unsupported = find_unsupported(page)
            nav["unsupported"] = _merge_unsupported(nav.get("unsupported", []), here_unsupported)  # steps that will be left behind
            schema = discover(page)
            self._bump_floor(schema)
            for c in schema.controls:
                if c.visible and c.disabled and c.control_id not in items:
                    nav["notes"].append({"kind": "control_stayed_disabled", "step": step, "control": c.label,
                                         "reason": "disabled after every other answer on the step was entered; not filled"})
            snap = take_snapshot(page, schema)
            if not self.start_origin:
                self.start_origin = snap.origin
            self.visited.setdefault(snap.fingerprint, step)
            self.path.append(snap.fingerprint)
            record = {"step": step, **snap.describe(), "question_ids": list(step_ids),
                      "states": {s.value: sum(1 for q in step_ids if field_state(items[q])[0] is s) for s in FieldState},
                      "transition": None}
            nav["steps"].append(record)
            self.checkpoint("step_verified")

            self.state(NavState.GATING, step)
            open_required = unresolved_required(step_ids, items, controls, here_unsupported)
            record["required_unresolved"] = open_required
            if open_required and not policy.advance_with_unresolved_required:
                self.stop("required_unresolved", step=step, questions=[q["question"] for q in open_required],
                          reason="a required question on this step is not answered and verified; a person must answer it before "
                                 "the walk may leave the step")
                return

            nb = _steps.next_button(page, policy, form_navigation)
            if nb["state"] == "none":
                self.stop("no_safe_next_control", step=step, buttons_seen=nb["seen"],
                          reason="no button on the page matches the allowed next-step labels (last step, or a label we will not press)")
                return
            if nb["state"] == "refused":
                self.stop("submit_type_next_refused", step=step, button=nb["detail"], buttons_seen=nb["seen"],
                          reason="the only next-step-looking button can submit the form or leave the page; refused without clicking")
                return
            if nb["state"] == "disabled":
                self.stop("next_disabled", step=step, button=nb["text"],
                          reason="the next-step button is disabled; required answers are probably missing (see REVIEW items)")
                return
            if not self._press(step, nb):
                record["transition"] = "stopped"
                return

            self.state(NavState.CONFIRMING, step)
            after_schema = discover(page)
            self._bump_floor(after_schema)
            after = take_snapshot(page, after_schema)
            outcome = classify(snap, after, self.visited, step, self.start_origin)
            record["transition"] = outcome.value
            self.state(NavState.REVERIFYING, step, outcome=outcome.value)
            self._reverify(after_schema)  # did the move discard or change earlier answers? (also before stopping)
            self.checkpoint("transition")
            if outcome is Outcome.REDIRECTED:
                self.stop("unexpected_redirect", step=step, origin=after.origin,
                          reason=f"the page moved from {self.start_origin} to another origin")
                return
            if outcome is Outcome.VALIDATION_ERROR:
                self.stop("validation_error_after_next", step=step, errors=list(after.errors),
                          reason="Next did not leave the step and the page shows validation messages")
                return
            if outcome is Outcome.NO_CHANGE:
                self.stop("no_change_after_next", step=step, reason="the step did not change after pressing Next")
                return
            if outcome is Outcome.LOOP:
                self.stop("navigation_loop", step=step, back_to_step=self.visited[after.fingerprint],
                          reason="Next led back to a step that was already visited")
                return
        else:
            nav["stop_reason"] = "max_steps"
            self.state(NavState.STOPPED, policy.max_steps, reason="max_steps")

    def _reverify(self, schema: FormSchema) -> None:
        """Read back every answer given so far. A control that the page re-rendered (same question, new node) is matched by its
        signature, so a remount that dropped the value is a detected reset rather than an unobservable answer."""
        present = {c.control_id for c in schema.controls}
        by_sig: dict = {}
        for c in schema.controls:
            if c.visible and c.control_id not in self.items:
                by_sig.setdefault(signature(c), c)
        for qid in [q for ids in self.nav["step_controls"] for q in ids]:
            if qid not in present:
                remounted = by_sig.get(signature(self.controls[qid]))
                if remounted is not None:
                    self.controls[qid] = remounted
            judge(self.page, self.controls[qid], self.items[qid], self.nav)

    # ---- optional Back re-verification ---------------------------------------------------------------------------------------
    def _recheck_visible(self, step_no: int, rv: dict) -> None:
        schema = discover(self.page)
        self._bump_floor(schema)
        by_sig = {signature(c): c for c in schema.controls if c.visible}
        for qid, item in self.items.items():
            c = by_sig.get(signature(self.controls[qid]))
            if c is None or item.plan.status != "ANSWER" or not item.filled:
                continue
            self.controls[qid] = c
            judge(self.page, c, item, self.nav, self.timeout_ms)
            item.revisit_verified = item.verified is True
            rv["reverified" if item.verified else "mismatched"].append(item.plan.question)
        rv["steps_checked"].append(step_no)

    def _revisit(self) -> None:
        page, nav, policy = self.page, self.nav, self.policy
        rv: dict = {"steps_checked": [], "reverified": [], "mismatched": [], "returned_to_last_step": False, "stopped": None}
        nav["revisit"] = rv
        last = len(self.path) - 1
        pos = last
        while pos > 0:
            self.state(NavState.REVISITING, pos + 1, direction="back")
            bb = _steps.back_button(page, policy)
            if bb["state"] != "found":
                rv["stopped"] = f"no usable Back control on step {pos + 1} ({bb['state']})"
                break
            self.events["dialog"] = self.events["popup"] = None
            try:
                _steps.click_next(page, bb["index"], self.timeout_ms)
            except Exception as exc:  # noqa: BLE001
                rv["stopped"] = f"Back could not be pressed: {str(exc).splitlines()[0][:120]}"
                break
            if self.events["dialog"] or self.events["popup"]:
                rv["stopped"] = "Back opened a dialog or a popup"
                break
            if not self.stable(pos + 1, "after Back"):
                return
            snap = take_snapshot(page, discover(page))
            if snap.fingerprint != self.path[pos - 1]:
                rv["stopped"] = f"Back from step {pos + 1} did not lead to step {pos}"
                break
            pos -= 1
            self._recheck_visible(pos + 1, rv)
        while pos < last:
            self.state(NavState.REVISITING, pos + 1, direction="forward")
            nb = _steps.next_button(page, policy)
            if nb["state"] != "found":
                rv["stopped"] = rv["stopped"] or f"could not return forward from step {pos + 1} ({nb['state']})"
                break
            self.events["dialog"] = self.events["popup"] = None
            try:
                _steps.click_next(page, nb["index"], self.timeout_ms)
            except Exception as exc:  # noqa: BLE001
                rv["stopped"] = rv["stopped"] or f"Next could not be pressed on the way back: {str(exc).splitlines()[0][:120]}"
                break
            if not self.stable(pos + 1, "after Next (returning)"):
                return
            snap = take_snapshot(page, discover(page))
            if snap.fingerprint != self.path[pos + 1]:
                rv["stopped"] = rv["stopped"] or f"Next from step {pos + 1} did not return to step {pos + 2}"
                break
            pos += 1
            self._recheck_visible(pos + 1, rv)
        rv["returned_to_last_step"] = pos == last
        self.checkpoint("revisit")

    # ---- entry point -------------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        nav = self.nav
        if not self._preflight() or not self._start_guard():
            return nav
        page = self.page
        page.on("dialog", self._on_dialog)
        page.on("popup", self._on_popup)
        try:
            _steps.install(page)
            self._forward()
            if self.policy.revisit_with_back and nav["stop_reason"] in _REVISIT_AFTER and len(self.path) > 1:
                self._revisit()
        finally:
            page.remove_listener("dialog", self._on_dialog)
            page.remove_listener("popup", self._on_popup)
        if nav.get("network_guard_active"):
            nav["notes"].append({
                "kind": "network_guard_active",
                "reason": "outbound requests remain blocked until the browser context closes or release_wizard_network_guard(page) is called after human review; "
                          "the whole browser context was put offline, so other pages in it were affected too, and a page that reacts to "
                          "going offline (disabled inputs, an overlay) may have stopped this walk for that reason",
            })
            if not self.network.blocks_everything:
                nav["notes"].append({"kind": "network_policy_allow_listed", "permitted": len(nav["permitted_requests"]),
                                     "reason": "requests matching the explicit allow rules were relayed by FormFiller and recorded under "
                                               "navigation.permitted_requests; everything else was blocked"})
            if self.downloads is None or not self.downloads.available:
                nav["notes"].append({"kind": "download_check_unavailable",
                                     "reason": "the DevTools protocol is not available here (not Chromium, or a persistent context), so a "
                                               "download the page starts with <a download> could not be intercepted"})
            fence = self.fence
            if fence is not None and fence.available:
                if fence.neutralised:
                    nav["notes"].append({"kind": "shared_worker_taken_offline", "count": fence.neutralised,
                                         "reason": "SharedWorkers that already existed in this context were put offline through the DevTools protocol"})
            else:
                nav["notes"].append({"kind": "shared_worker_check_unavailable",
                                     "reason": "the DevTools protocol is not available here (not Chromium, or a persistent context), so a SharedWorker "
                                               "created before the walk could not be found or stopped"})
        self.checkpoint("finished")
        return nav


def _versions(page: Page) -> dict:
    """Playwright and browser versions: the guard's behaviour was measured per version (docs/SECURITY_MODEL.md)."""
    out: dict[str, str | None] = {"playwright": None, "browser": None}
    with contextlib.suppress(Exception):
        from importlib.metadata import version

        out["playwright"] = version("playwright")
    with contextlib.suppress(Exception):
        out["browser"] = page.context.browser.version if page.context.browser else None
    return out


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
