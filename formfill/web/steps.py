"""Browser layer, step 3: safe navigation of multi-step (wizard) single-page forms.

Everything here is about *where the form is*, never *what to answer*. It is only used when the caller passes a
`DiscoveryPolicy` to `run_form`; without one the pipeline behaves exactly as before (one page, no clicks).

The policy is deliberately conservative. It will press a button only when the button's visible text is on an
explicit allow list of "go to the next step" labels AND is not on the deny list of commit-style labels
(submit, finish, confirm, pay, ...) AND, by default, is not a submit-type control (see below). It never presses anything
else, never accepts a browser dialog, closes any popup it did not ask for, and stops, recording why, on anything unexpected.
This is risk reduction, not a guarantee that nothing can ever be submitted: `DiscoveryPolicy.allow_submit_type_navigation`
no longer unlocks anything: a form submit control is always refused, because it cannot be told from a real submission
before the click. The post-click submit-event counter remains only as a tripwire for unexpected cases; it is not relied on. Next-button search covers the main document only (not open shadow
roots or iframes), which is a narrower reach than field discovery.

    no_safe_next_control   no allowed Next button on the page. Ambiguous by nature: the genuine last step, or a Next we do not recognise.
                           Completion is UNCONFIRMED: status NEEDS_REVIEW, never FILLED, and submit=True is skipped
    submit_type_next_refused  the only Next-looking button is a form submit control (button type=submit, a <button> with no
                           type inside a form, <input type=submit|image>) or a link that leaves the page: refused BEFORE any click,
                           because a submission cannot be undone once it has happened
    page_not_settled       the page never went quiet within the policy's timeout (spinner, polling, constant DOM churn): nothing
                           is filled or clicked on a page whose state is uncertain
    next_disabled          the Next button is disabled (required answers missing; REVIEW items need a person)
    dialog_on_navigation   Next opened an alert/confirm/prompt (dismissed, never accepted)
    popup_opened           Next opened a new window (closed)
    document_navigation    Next replaced the whole document (SPA state and our handles are gone)
    submit_event_observed  a form `submit` event fired while navigating (should be impossible with the deny list)
    no_change_after_next   Next was pressed and the step did not change (same URL, headings and visible questions)
    validation_error_after_next  Next was pressed, the step did not change, and the page shows validation messages
    navigation_loop        Next led back to a step that was already visited
    unexpected_redirect    the page moved to another origin
    required_unresolved    a REQUIRED question on the step is not verified (REVIEW, failed, unsupported): Next is not pressed
    max_steps              the policy's step limit was reached
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from playwright.sync_api import Page

_ALLOW = re.compile(
    r"^(?:next(?:\s+step)?|continue(?:\s+to\b.*)?|proceed(?:\s+to\s+next)?|forward|go\s+to\s+next(?:\s+step)?|"
    r"save\s*(?:and|&)\s*(?:continue|next)|next\s*(?:>|›|»|→)|(?:>|›|»|→))$"
)
# "Go back one step" labels. Used only by the optional re-verification pass (DiscoveryPolicy.revisit_with_back): moving back
# changes nothing on the server in a client-side wizard, and the same metadata refusals as Next apply (no submit controls,
# no links that leave the page).
_BACK = re.compile(r"^(?:back|go\s+back|previous(?:\s+step)?|prev|(?:<|\u2039|\u00ab|\u2190)\s*(?:back|previous)?|back\s+to\s+previous(?:\s+step)?)$")
_BACK_DENY = re.compile(r"\b(?:submit|send|finish|finali[sz]e|complete|confirm|pay|sign|certify|attest|agree|accept|delete|remove|"
                        r"cancel|reset|clear|discard|exit|logout|log\s*out|home)\b")

_DENY = re.compile(
    r"\b(?:submit|send|finish|finali[sz]e|complete|apply|confirm|pay|purchase|order|register|sign|certify|attest|agree|accept|"
    r"delete|remove|cancel|reset|clear|discard|back|previous|prev|save\s+draft)\b"
)


# Stop reasons after which completion is NOT established. `no_safe_next_control` is in here on purpose: it is what the genuine
# last step looks like, but it is also what a Next button we do not recognise ("Onward", an icon, another language) looks like,
# and the two cannot be told apart from the page. So a walk that ends this way is "unconfirmed", never FILLED, and is never
# submitted automatically. A future, explicit final-step policy must be designed separately; absence of a Next button is not evidence.
INCOMPLETE_STOPS = frozenset({
    "no_safe_next_control", "page_not_settled", "document_navigation", "dialog_on_navigation", "popup_opened", "submit_type_next_refused",
    "next_click_failed", "submit_event_observed", "outbound_request_blocked", "network_guard_unavailable",
    "service_worker_controls_page", "service_worker_registered", "next_disabled", "no_change_after_next", "max_steps",
    "validation_error_after_next", "navigation_loop", "unexpected_redirect", "required_unresolved", "resume_ambiguous",
})


@dataclass
class DiscoveryPolicy:
    max_steps: int = 12
    max_rounds_per_step: int = 5  # conditional reveals: answer, wait, look again
    # DEPRECATED, NO EFFECT. A form-owned submit control is how a page *submits*; an SPA that intercepts it (preventDefault)
    # cannot be told apart from one that does not until after the click, which is too late. Submit-type controls are therefore
    # always refused and need a person, whatever this says. Kept only so existing callers still construct a policy.
    allow_submit_type_navigation: bool = False
    settle_quiet_ms: int = 150  # DOM must be quiet this long to count as settled
    settle_timeout_ms: int = 4000
    allow: re.Pattern = field(default=_ALLOW, repr=False)
    deny: re.Pattern = field(default=_DENY, repr=False)
    # Before pressing Next, every REQUIRED question on the step must be verified. Otherwise the walk stops with
    # `required_unresolved` so a person answers it first. Set True only for a portal that is known to validate on its own.
    advance_with_unresolved_required: bool = False
    # After the forward walk reaches the last recognisable step, go Back step by step and read every earlier answer again (a
    # wizard that unmounts its steps cannot be checked otherwise), then return forward. Client-side wizards only.
    revisit_with_back: bool = False
    back: re.Pattern = field(default=_BACK, repr=False)
    back_deny: re.Pattern = field(default=_BACK_DENY, repr=False)

    def is_safe_next(self, text: str) -> bool:
        t = re.sub(r"\s+", " ", text or "").strip().casefold()
        return bool(t) and bool(self.allow.match(t)) and not self.deny.search(t)

    def is_safe_back(self, text: str) -> bool:
        t = re.sub(r"\s+", " ", text or "").strip().casefold()
        return bool(t) and bool(self.back.match(t)) and not self.back_deny.search(t)


_INSTALL_JS = """
() => {
  if (window.__ffInstalled) return;
  window.__ffInstalled = true; window.__ffPending = 0; window.__ffSubmits = 0;
  const f = window.fetch;
  if (f) window.fetch = function () { window.__ffPending++; return f.apply(this, arguments).finally(() => { window.__ffPending--; }); };
  const s = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () { window.__ffPending++; this.addEventListener('loadend', () => { window.__ffPending--; }); return s.apply(this, arguments); };
  window.__ffPermittedSubmits = 0;
  document.addEventListener('submit', event => {
    // One submit may pass when the walk itself pressed a Next button that a network-policy rule allows to post its form
    // (a server-rendered wizard step). The flag is set immediately before that click and consumed here.
    if (window.__ffAllowNextSubmit) { window.__ffAllowNextSubmit = false; window.__ffPermittedSubmits++; return; }
    window.__ffSubmits++;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  // SharedWorker attempts (see formfill.web.sharedworkers) are collected here, whichever frame made them.
  window.__ffBlockedApis = window.__ffBlockedApis || [];
}
"""

_SETTLE_JS = """
([quiet, timeout]) => new Promise(resolve => {
  const t0 = performance.now(); let last = t0;
  const mo = new MutationObserver(() => { last = performance.now(); });
  mo.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  const tick = () => {
    const now = performance.now();
    if ((window.__ffPending || 0) > 0 || document.querySelector('[aria-busy="true"]')) last = now;
    if (now - last >= quiet) { mo.disconnect(); resolve({settled: true, waited: Math.round(now - t0)}); }
    else if (now - t0 >= timeout) { mo.disconnect(); resolve({settled: false, waited: Math.round(now - t0)}); }
    else setTimeout(tick, 25);
  };
  tick();
})
"""

_BUTTONS_JS = """
() => {
  document.querySelectorAll('[data-ff-nav]').forEach(e => e.removeAttribute('data-ff-nav'));
  const vis = e => { try { return e.checkVisibility ? e.checkVisibility() : !!(e.offsetWidth || e.offsetHeight); } catch (x) { return true; } };
  const out = []; let n = 0;
  document.querySelectorAll('button, [role=button], input[type=button], input[type=submit], input[type=image]').forEach(e => {
    if (!vis(e)) return;
    const text = ((e.tagName === 'INPUT' ? (e.value || e.getAttribute('alt')) : e.textContent) || e.getAttribute('aria-label') || e.getAttribute('alt') || '').replace(/\\s+/g, ' ').trim();
    e.setAttribute('data-ff-nav', String(n));
    const tag = e.tagName.toLowerCase();
    // effective type: <button> with no/invalid type attribute is a submit button; only elements owned by a form can submit it
    const type = (tag === 'button' || tag === 'input') ? String(e.type || '').toLowerCase() : null;
    const href = tag === 'a' ? (e.getAttribute('href') || '') : null;
    out.push({index: n++, text, disabled: e.disabled === true || e.getAttribute('aria-disabled') === 'true',
              tag, type, role: e.getAttribute('role'), in_form: !!e.form, form_index: e.form ? Array.from(document.forms).indexOf(e.form) : null,
              // button.formAction is the document URL when the button has no formaction attribute; the form owner's action is what posts
              form_action: e.getAttribute && e.getAttribute('formaction') ? e.formAction : (e.form ? e.form.action : null), href,
              form_method: e.form ? String(e.getAttribute('formmethod') || e.form.getAttribute('method') || 'get').toLowerCase() : null,
              submit_type: !!e.form && (type === 'submit' || type === 'image'),
              leaves_page: tag === 'a' && !!href && !href.startsWith('#') && !/^javascript:/i.test(href)});
  });
  return out;
}
"""


def install(page: Page) -> None:
    """Track network/submit activity and cancel submit events during a wizard walk. Main frame only; lost on full navigation."""
    page.evaluate(_INSTALL_JS)


def blocked_apis(page: Page) -> list[str]:
    """Browser APIs the page tried to use while the walk had them disabled (see _INSTALL_JS), oldest first."""
    try:
        return list(page.evaluate("() => window.__ffBlockedApis || []"))
    except Exception:  # noqa: BLE001 - mid-navigation
        return []


def installed(page: Page) -> bool:
    try:
        return bool(page.evaluate("() => !!window.__ffInstalled"))
    except Exception:  # noqa: BLE001 - mid-navigation
        return False


def settle(page: Page, policy: DiscoveryPolicy) -> dict:
    """Wait until the page has been quiet (no DOM mutations, no pending fetch/XHR, no aria-busy) for the policy's
    quiet window. Returns {"settled": bool, "waited": ms}; never raises (a page that navigates away is reported)."""
    try:
        return page.evaluate(_SETTLE_JS, [policy.settle_quiet_ms, policy.settle_timeout_ms])
    except Exception:  # noqa: BLE001
        return {"settled": False, "waited": 0, "navigated": True}


def next_button(page: Page, policy: DiscoveryPolicy, form_navigation=None) -> dict:
    """Find the one button we are willing to press. Returns {"state": "found"|"disabled"|"refused"|"none", "text", "index",
    "seen": [...]}. A form submit control is refused, except when `form_navigation(action_url, method)` (the network policy's
    explicit rule lookup) returns a rule for that form's action: then it is "found" with `"form_navigation": rule`."""
    return _pick(page.evaluate(_BUTTONS_JS), policy.is_safe_next, form_navigation)


def back_button(page: Page, policy: DiscoveryPolicy) -> dict:
    """Like next_button, for the optional Back re-verification pass. Submit controls and off-page links are always refused."""
    return _pick(page.evaluate(_BUTTONS_JS), policy.is_safe_back, None)


def _pick(buttons: list[dict], acceptable, form_navigation) -> dict:
    safe = [b for b in buttons if acceptable(b["text"])]
    seen = [{k: b[k] for k in ("text", "tag", "type", "in_form", "submit_type", "disabled")} for b in buttons]
    refused, usable = [], []
    for b in safe:
        rule = None
        if b["submit_type"] and not b["leaves_page"] and form_navigation is not None and b.get("form_action"):
            rule = form_navigation(b["form_action"], (b.get("form_method") or "get").upper())
        if rule is not None:
            usable.append({**b, "form_navigation": rule})
        elif b["submit_type"] or b["leaves_page"]:
            refused.append(b)
        else:
            usable.append(b)
    for b in usable:
        if not b["disabled"]:
            return {"state": "found", "text": b["text"], "index": b["index"], "seen": seen,
                    **({"form_navigation": b["form_navigation"]} if b.get("form_navigation") else {})}
    if usable:
        return {"state": "disabled", "text": usable[0]["text"], "index": usable[0]["index"], "seen": seen}
    if refused:
        b = refused[0]
        why = ("form submit control" if b["submit_type"] else "link that leaves the page")
        return {"state": "refused", "text": b["text"], "index": b["index"], "seen": seen,
                "detail": f"<{b['tag']}{' type=' + b['type'] if b['type'] else ''}> {b['text']!r}: {why}"}
    return {"state": "none", "seen": seen}


def allow_next_submit(page: Page) -> None:
    """Let exactly one form submit event through (see _INSTALL_JS); used only for a policy-permitted form navigation."""
    page.evaluate("() => { window.__ffAllowNextSubmit = true; }")


def set_id_floor(page: Page, floor: int) -> None:
    """Make discovery continue numbering above `floor` in a freshly loaded document, so control ids from an earlier document
    of the same walk are never reused for a different control."""
    page.evaluate("(n) => { window.__ffCounter = Math.max(window.__ffCounter || 0, n); }", floor)


def click_next(page: Page, index: int, timeout_ms: int) -> None:
    page.locator(f'[data-ff-nav="{index}"]').first.click(timeout=timeout_ms)


def submits(page: Page) -> int:
    try:
        return int(page.evaluate("() => window.__ffSubmits || 0"))
    except Exception:  # noqa: BLE001
        return 0
