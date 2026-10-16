"""Browser layer, step 3: safe navigation of multi-step (wizard) single-page forms.

Everything here is about *where the form is*, never *what to answer*. It is only used when the caller passes a
`DiscoveryPolicy` to `run_form`; without one the pipeline behaves exactly as before (one page, no clicks).

The policy is deliberately conservative. It will press a button only when the button's visible text is on an
explicit allow list of "go to the next step" labels AND is not on the deny list of commit-style labels
(submit, finish, confirm, pay, ...) AND is not a submit-type control (see below). It never presses anything
else, never accepts a browser dialog, closes any popup it did not ask for, and stops, recording why, on anything unexpected.
This is risk reduction, not a guarantee that nothing can ever be submitted: a "Next" button that itself performs a
script-driven submission cannot be told apart from a real one before the click, and the post-click submit-event counter
is only a second line of defence that cannot see every script-driven submission. There is no opt-in that allows
submit-type controls. Next-button search covers the main document only (not open shadow roots or iframes), which is a
narrower reach than field discovery.

    no_safe_next_control   no allowed Next button on the page. Ambiguous by nature: the genuine last step, or a Next we do not recognise.
                           Completion is UNCONFIRMED: status NEEDS_REVIEW, never FILLED
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
    no_change_after_next   Next was pressed and the set of visible controls did not change
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
    "next_click_failed", "submit_event_observed", "next_disabled", "no_change_after_next", "max_steps",
})


@dataclass
class DiscoveryPolicy:
    max_steps: int = 12
    max_rounds_per_step: int = 5  # conditional reveals: answer, wait, look again
    settle_quiet_ms: int = 150  # DOM must be quiet this long to count as settled
    settle_timeout_ms: int = 4000
    allow: re.Pattern = field(default=_ALLOW, repr=False)
    deny: re.Pattern = field(default=_DENY, repr=False)

    def is_safe_next(self, text: str) -> bool:
        t = re.sub(r"\s+", " ", text or "").strip().casefold()
        return bool(t) and bool(self.allow.match(t)) and not self.deny.search(t)


_INSTALL_JS = """
() => {
  if (window.__ffInstalled) return;
  window.__ffInstalled = true; window.__ffPending = 0; window.__ffSubmits = 0;
  const f = window.fetch;
  if (f) window.fetch = function () { window.__ffPending++; return f.apply(this, arguments).finally(() => { window.__ffPending--; }); };
  const s = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () { window.__ffPending++; this.addEventListener('loadend', () => { window.__ffPending--; }); return s.apply(this, arguments); };
  document.addEventListener('submit', () => { window.__ffSubmits++; }, true);
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
              form_action: e.formAction || null, href,
              submit_type: !!e.form && (type === 'submit' || type === 'image'),
              leaves_page: tag === 'a' && !!href && !href.startsWith('#') && !/^javascript:/i.test(href)});
  });
  return out;
}
"""


def install(page: Page) -> None:
    """Install the page-side counters (pending fetch/XHR, submit events). Lost on a full navigation."""
    page.evaluate(_INSTALL_JS)


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


def next_button(page: Page, policy: DiscoveryPolicy) -> dict:
    """Find the one button we are willing to press. Returns {"state": "found"|"disabled"|"none", "text", "index", "seen": [...]}"""
    buttons = page.evaluate(_BUTTONS_JS)
    safe = [b for b in buttons if policy.is_safe_next(b["text"])]
    seen = [{k: b[k] for k in ("text", "tag", "type", "in_form", "submit_type", "disabled")} for b in buttons]
    refused = [b for b in safe if b["submit_type"] or b["leaves_page"]]  # a form-owned submit control is how a page *submits*: never pressed
    usable = [b for b in safe if b not in refused]
    for b in usable:
        if not b["disabled"]:
            return {"state": "found", "text": b["text"], "index": b["index"], "seen": seen}
    if usable:
        return {"state": "disabled", "text": usable[0]["text"], "index": usable[0]["index"], "seen": seen}
    if refused:
        b = refused[0]
        why = ("form submit control" if b["submit_type"] else "link that leaves the page")
        return {"state": "refused", "text": b["text"], "index": b["index"], "seen": seen,
                "detail": f"<{b['tag']}{' type=' + b['type'] if b['type'] else ''}> {b['text']!r}: {why}"}
    return {"state": "none", "seen": seen}


def click_next(page: Page, index: int, timeout_ms: int) -> None:
    page.locator(f'[data-ff-nav="{index}"]').first.click(timeout=timeout_ms)


def submits(page: Page) -> int:
    try:
        return int(page.evaluate("() => window.__ffSubmits || 0"))
    except Exception:  # noqa: BLE001
        return 0
