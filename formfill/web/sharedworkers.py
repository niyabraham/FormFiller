"""SharedWorker containment for the wizard network guard.

A SharedWorker's requests are invisible to Playwright request routing, and offline emulation set on the page does not reach
them, so the guard needs two further measures. Neither is complete; `docs/OUTPUT_DESIGN.md` states what is left.

1. `FENCE_JS`, an in-page replacement for the `SharedWorker` constructor. It refuses to construct a worker while the browser
   reports itself offline (the guard turns the context offline), and is inert otherwise. It is installed in every frame of every
   page in the context when the guard starts and, as a context init script, in every document loaded afterwards (same-origin iframes,
   `about:blank` and `srcdoc` frames included). It also repoints `SharedWorker.prototype.constructor`. A page that kept a
   reference to the original constructor before the guard started is not stopped by it. The same fence is applied to
   `WebTransport` (HTTP/3 sessions, which routing does not see and offline emulation was not measured against).
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
from typing import Any

from playwright.sync_api import Page

# Idempotent per realm. Blocks only while the browser reports offline, using the getter captured before any page script can
# replace it, so after `release_wizard_network_guard` the constructor behaves as before.
FENCE_JS = """
(() => {
  if (window.__ffFence) return;
  window.__ffFence = true;
  const online = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine').get;
  const record = name => {
    for (const w of [window.top, window.parent, window]) {
      try { (w.__ffBlockedApis = w.__ffBlockedApis || []).push(name); return; } catch (e) { /* cross-origin parent */ }
    }
  };
  // Constructors whose traffic neither request routing nor offline emulation is known to cover. Each refuses to construct
  // while the browser reports offline (the guard), and behaves as the original otherwise.
  const fence = name => {
    const Original = window[name];
    if (typeof Original !== 'function') return;
    const Fence = function () {
      if (!new.target) return Original.apply(this, arguments);  // the browser's own "requires new" TypeError
      if (!online.call(navigator)) {
        record(name);
        throw new DOMException(name + ' is disabled while FormFiller holds the network guard', 'SecurityError');
      }
      return Reflect.construct(Original, arguments, new.target === Fence ? Original : new.target);
    };
    Object.defineProperty(Fence, 'name', {value: name});
    Fence.prototype = Original.prototype;
    Object.defineProperty(Original.prototype, 'constructor', {value: Fence, writable: true, configurable: true});
    window[name] = Fence;
  };
  fence('SharedWorker');
  fence('WebTransport');
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
_PAGE_SESSIONS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _page_session(page: Page):
    """A page-level DevTools session, created once and deliberately never detached: detaching it resets the page's network
    emulation, which would silently put an offline context back online."""
    if page not in _PAGE_SESSIONS:
        _PAGE_SESSIONS[page] = page.context.new_cdp_session(page)
    return _PAGE_SESSIONS[page]


def _context_id(page: Page) -> str:
    """The DevTools id of the page's browser context, to tell its SharedWorkers (and downloads) from other contexts'."""
    context = page.context
    if context not in _CONTEXT_IDS:
        _CONTEXT_IDS[context] = _page_session(page).send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
    return _CONTEXT_IDS[context]


class DownloadGate:
    """Chromium only. A download the page starts with the `download` attribute (`<a download>` clicked, attached or not) is a
    request made by the browser process: Playwright's request routing never sees it and offline emulation does not stop it
    (measured: the full URL, query string included, reached the server). DevTools request interception on the BROWSER target
    does see it. While engaged, every such request that comes from a frame of this context is failed and recorded; requests
    of other contexts in the same browser continue untouched. Ordinary page requests are not paused by it (measured)."""

    def __init__(self, page: Page, record):
        self._page = page
        self._record = record
        self._cdp: Any = None  # a browser-level CDPSession once engaged
        self._context_id: str | None = None
        self.available = False
        self.blocked = 0

    def engage(self) -> None:
        browser = self._page.context.browser
        if browser is None:
            return
        try:
            self._cdp = browser.new_browser_cdp_session()
            self._context_id = _context_id(self._page)
        except Exception:  # noqa: BLE001 - not Chromium: nothing to intercept with
            self._cdp = None
            return
        self._cdp.on("Fetch.requestPaused", self._on_paused)
        self._cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})  # raises if it cannot: the guard then refuses
        self.available = True
        self._closed = False
        self._page.context.once("close", lambda *_: self._context_closed())  # never outlive the context it guards

    def _context_closed(self) -> None:
        self._closed = True
        self.release()

    def _our_frames(self) -> set[str]:
        frames: set[str] = set()
        for t in self._cdp.send("Target.getTargets")["targetInfos"]:
            if t.get("browserContextId") == self._context_id and t["type"] in ("page", "iframe"):
                frames.add(t["targetId"])
        for tab in self._page.context.pages:
            try:
                stack = [_page_session(tab).send("Page.getFrameTree")["frameTree"]]
            except Exception:  # noqa: BLE001 - a closing tab: its targets above still count
                continue
            while stack:
                node = stack.pop()
                frames.add(node["frame"]["id"])
                stack.extend(node.get("childFrames", []))
        return frames

    def _on_paused(self, event: dict) -> None:
        request_id = event["requestId"]
        frame = event.get("frameId")
        if getattr(self, "_closed", False) or frame is None:
            ours = False  # a closed context has no pages; a request with no frame was not started by a page
        else:
            try:
                ours = frame in self._our_frames()
            except Exception:  # noqa: BLE001 - cannot tell: treat it as ours (fail closed)
                ours = True
        try:
            if ours:
                self.blocked += 1
                url = event["request"]["url"]
                self._record({"url": url.split("?", 1)[0].split("#", 1)[0], "method": event["request"].get("method", "GET"),
                              "resource_type": "download", "navigation": False,
                              "reason": "a download started by the page is a browser-level request; downloads are never sent during a walk"})
                self._cdp.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
            else:
                self._cdp.send("Fetch.continueRequest", {"requestId": request_id})
        except Exception:  # noqa: BLE001 - the request is already gone
            pass

    def release(self) -> None:
        if self._cdp is None:
            return
        with contextlib.suppress(Exception):
            self._cdp.send("Fetch.disable")
        with contextlib.suppress(Exception):
            self._cdp.detach()
        self._cdp = None
        self.available = False


class SharedWorkerFence:
    """Take this context's existing SharedWorkers offline (Chromium). `available` is False where that cannot be done."""

    def __init__(self, page: Page, timeout_ms: int = 2000):
        self._page = page
        self._timeout_ms = timeout_ms
        self._cdp: Any = None  # a browser-level CDPSession once engaged
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
