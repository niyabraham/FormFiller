"""SharedWorker containment for the wizard network guard.

A SharedWorker's requests are invisible to Playwright request routing, and offline emulation set on the page does not reach
them, so the guard needs two further measures. Neither is complete; `docs/OUTPUT_DESIGN.md` states what is left.

1. `FENCE_JS`, an in-page replacement for the `SharedWorker` constructor. It refuses to construct a worker while the browser
   reports itself offline (the guard turns the context offline), and is inert otherwise. It is installed in every frame of every
   page in the context when the guard starts and, as a context init script, in every document loaded afterwards (same-origin iframes,
   `about:blank` and `srcdoc` frames included). It also repoints `SharedWorker.prototype.constructor`. A page that kept a
   reference to the original constructor before the guard started is not stopped by it.
2. `SharedWorkerFence`, Chromium only (it uses the DevTools protocol through Playwright's `CDPSession`): it finds SharedWorkers
   that already belong to the page's browser context and puts each of them offline through its own DevTools session. A worker
   created later can be found again with `scan()`, but not before it has started running, so a worker that sends a request
   from its start-up script can still get one out. Where the DevTools protocol is not available the fence says so and
   cannot look at all.
"""

from __future__ import annotations

import contextlib
import json
import weakref

from playwright.sync_api import Page

# Idempotent per realm. Blocks only while the browser reports offline, using the getter captured before any page script can
# replace it, so after `release_wizard_network_guard` the constructor behaves as before.
FENCE_JS = """
(() => {
  if (window.__ffSharedWorkerFence || !window.SharedWorker) return;
  window.__ffSharedWorkerFence = true;
  const Original = window.SharedWorker;
  const online = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine').get;
  const record = () => {
    for (const w of [window.top, window.parent, window]) {
      try { (w.__ffBlockedApis = w.__ffBlockedApis || []).push('SharedWorker'); return; } catch (e) { /* cross-origin parent */ }
    }
  };
  const Fence = function SharedWorker() {
    if (!new.target) return Original.apply(this, arguments);  // the browser's own "requires new" TypeError
    if (!online.call(navigator)) {
      record();
      throw new DOMException('SharedWorker is disabled while FormFiller holds the network guard', 'SecurityError');
    }
    return Reflect.construct(Original, arguments, new.target === Fence ? Original : new.target);
  };
  Fence.prototype = Original.prototype;
  Object.defineProperty(Original.prototype, 'constructor', {value: Fence, writable: true, configurable: true});
  window.SharedWorker = Fence;
})()
"""

_FENCED_CONTEXTS: weakref.WeakSet = weakref.WeakSet()  # contexts that already carry the init script


def install_fence(page: Page) -> None:
    """Put the in-page fence into every frame of every page in the context now, and every document the context loads later.
    The guard is context-wide, so the fence is too. Raises if a live frame refuses it."""
    context = page.context
    if context not in _FENCED_CONTEXTS:
        context.add_init_script(FENCE_JS)
        _FENCED_CONTEXTS.add(context)
    for tab in context.pages:
        for frame in tab.frames:
            try:
                frame.evaluate(FENCE_JS)
            except Exception:
                if not frame.is_detached():
                    raise


_CONTEXT_IDS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _context_id(page: Page) -> str:
    """The DevTools id of the page's browser context, to tell its SharedWorkers from other contexts'. The page-level session
    that answers is deliberately never detached: detaching it resets the page's network emulation, which would silently put
    an offline context back online."""
    context = page.context
    if context not in _CONTEXT_IDS:
        _CONTEXT_IDS[context] = context.new_cdp_session(page).send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
    return _CONTEXT_IDS[context]


class SharedWorkerFence:
    """Take this context's existing SharedWorkers offline (Chromium). `available` is False where that cannot be done."""

    def __init__(self, page: Page, timeout_ms: int = 2000):
        self._page = page
        self._timeout_ms = timeout_ms
        self._cdp = None
        self._context_id: str | None = None
        self._sessions: dict[str, str] = {}  # targetId -> DevTools session id
        self._answers: dict[int, dict] = {}
        self._next_id = 0
        self.available = False
        self.neutralised = 0

    def engage(self) -> int:
        """Open the DevTools connection and neutralise what exists. Returns the number of workers found; raises if one cannot be
        taken offline, because then the guard cannot claim to have contained it."""
        browser = self._page.context.browser
        if browser is None:
            return 0
        try:
            self._cdp = browser.new_browser_cdp_session()
            self._context_id = _context_id(self._page)
        except Exception:  # noqa: BLE001 - not Chromium: nothing to look at
            self._cdp = None
            return 0
        self._cdp.on("Target.receivedMessageFromTarget", self._on_message)
        self.available = True
        return len(self.scan())

    def scan(self) -> list[str]:
        """Neutralise SharedWorkers of this context not seen before. Returns their URLs; raises if one cannot be taken offline."""
        if not self.available:
            return []
        found = []
        for target in self._cdp.send("Target.getTargets")["targetInfos"]:
            if target["type"] != "shared_worker" or target.get("browserContextId") != self._context_id:
                continue
            if target["targetId"] in self._sessions:
                continue
            session = self._cdp.send("Target.attachToTarget", {"targetId": target["targetId"], "flatten": False})["sessionId"]
            self._sessions[target["targetId"]] = session
            self._call(session, "Network.enable")
            self._call(session, "Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
            found.append(target["url"])
            self.neutralised += 1
        return found

    def release(self) -> None:
        """Detach from every worker (which ends the offline emulation applied through that session)."""
        if self._cdp is None:
            return
        for session in self._sessions.values():
            with contextlib.suppress(Exception):
                self._cdp.send("Target.detachFromTarget", {"sessionId": session})
        self._sessions.clear()
        with contextlib.suppress(Exception):
            self._cdp.detach()
        self._cdp = None
        self.available = False

    def _on_message(self, event: dict) -> None:
        with contextlib.suppress(ValueError, KeyError):
            message = json.loads(event["message"])
            if "id" in message:
                self._answers[message["id"]] = message

    def _call(self, session: str, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        call_id = self._next_id
        self._cdp.send("Target.sendMessageToTarget",
                       {"sessionId": session, "message": json.dumps({"id": call_id, "method": method, "params": params or {}})})
        waited = 0
        while call_id not in self._answers:
            if waited >= self._timeout_ms:
                raise RuntimeError(f"SharedWorker did not answer {method}")
            self._page.wait_for_timeout(10)  # lets Playwright deliver the worker's answer
            waited += 10
        answer = self._answers.pop(call_id)
        if "error" in answer:
            raise RuntimeError(f"SharedWorker refused {method}: {answer['error'].get('message', answer['error'])}")
        return answer
