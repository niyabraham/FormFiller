"""The wizard network guard: what a guarded walk lets out of the browser.

Layers, because none is complete alone (each measured with a local server, see tests/web/test_network_guard.py):

* a context route that sees every HTTP(S) request Playwright can see. With the default `NetworkPolicy` (no rules) it aborts
  and records each one. With allow rules, a request the policy permits is replayed by Playwright's own request client and the
  response is handed back to the page (`_relay`), one redirect hop at a time with each hop re-checked; everything else is
  aborted and recorded;
* a context WebSocket route that never connects (on 1.64.1 the page sees an OPEN socket that goes nowhere). WebSockets are
  never allowed, whatever the policy says;
* `set_offline(True)`, kept on in every mode, which fails what routing cannot see: prefetch hints, WebSockets opened inside
  dedicated workers, WebRTC, and requests a caller-installed `page.route(...)` passes through with `continue_()`;
* the SharedWorker measures of `formfill.web.sharedworkers`;
* on Chromium, browser-level request interception for downloads (`<a download>` requests bypass routing and offline mode).

This is not absolute network isolation; docs/SECURITY_MODEL.md lists what is blocked, permitted, monitored, untested and what
cannot be guaranteed. The guard is per browser context: every page in the context goes offline, not only the walked one.
"""

from __future__ import annotations

import contextlib
import warnings as _warnings
import weakref
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Page

from formfill.web.netpolicy import NetworkPolicy
from formfill.web.sharedworkers import DownloadGate, SharedWorkerFence, install_fence

_NETWORK_GUARDS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_REDIRECTS = {301, 302, 303, 307, 308}


def guard_state(page: Page) -> dict | None:
    """The guard's state for this page's context, or None when no guard was ever installed."""
    return _NETWORK_GUARDS.get(page.context)


def guard_active(page: Page) -> bool:
    state = _NETWORK_GUARDS.get(page.context)
    return bool(state and state["active"])


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
    state["permitted_requests"] = None
    state["fence"].release()
    if state.get("downloads") is not None:
        state["downloads"].release()
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
    found by what the wrapper closes over), or None when the client does not keep one in the expected place.

    PLAYWRIGHT INTERNAL: `context._impl_obj._web_socket_routes`. Isolated here and in `_place_websocket_route`; checked by
    `test_the_playwright_internal_the_websocket_parking_relies_on_is_still_where_it_was_expected`. Blocking while the guard is
    active never depends on it."""
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


def _request_record(url: str, method: str, resource_type: str, navigation: bool = False, **extra) -> dict:
    """What is kept about a request: scheme, host and path only. The query string and fragment may carry form data."""
    try:
        parsed = urlsplit(url)
        shown = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except ValueError:  # an unparsable URL must never stop the request from being aborted
        shown = url.split("?", 1)[0].split("#", 1)[0]
    return {"url": shown, "method": method, "resource_type": resource_type, "navigation": navigation, **extra}


def _post_body(request) -> bytes | None:
    try:
        return request.post_data_buffer
    except Exception:  # noqa: BLE001 - a body Playwright cannot expose: treat it as unknown, which the policy refuses for writes
        return None


def _relay(route, request, state: dict) -> None:
    """Replay a permitted request with Playwright's request client (the browser stays offline) and give the response to the
    page. Redirects are followed here, not by the browser, so each hop is checked against the policy first; the page then sees
    the final response at the URL it asked for. Any failure aborts the request and records why: fail closed."""
    policy: NetworkPolicy = state["policy"]
    url, method, body = request.url, request.method, _post_body(request)
    nav = request.is_navigation_request()
    hops: list[str] = []
    try:
        for _ in range(policy.max_redirects + 1):
            resp = route.fetch(url=url, method=method, post_data=body, max_redirects=0, timeout=policy.relay_timeout_ms)
            location = resp.headers.get("location")
            if resp.status in _REDIRECTS and location:
                nxt = urljoin(url, location)
                if resp.status in (301, 302, 303) and method not in ("GET", "HEAD"):
                    method, body = "GET", None
                hop = policy.decide(nxt, method, request.resource_type, body, state["entered"])
                hops.append(_request_record(nxt, method, request.resource_type)["url"])
                if not hop.allowed:
                    state["record"](_request_record(nxt, method, request.resource_type, nav,
                                                    reason=f"redirect hop refused: {hop.reason}"))
                    route.abort("blockedbyclient")
                    return
                url = nxt
                continue
            data = resp.body()
            if len(data) > policy.max_response_bytes:
                state["record"](_request_record(request.url, request.method, request.resource_type, nav,
                                                reason=f"response of {len(data)} bytes exceeds the relay limit"))
                route.abort("blockedbyclient")
                return
            route.fulfill(response=resp)
            if state["permitted_requests"] is not None:
                decision = policy.decide(request.url, request.method, request.resource_type, _post_body(request), state["entered"])
                state["permitted_requests"].append(_request_record(
                    request.url, request.method, request.resource_type, nav, status=resp.status, redirect_hops=hops,
                    rule=(decision.rule.note or f"{decision.rule.origin}{decision.rule.path}") if decision.rule else None,
                    carries_answers=decision.carries_answers))
            return
        state["record"](_request_record(request.url, request.method, request.resource_type, nav,
                                        reason=f"more than {policy.max_redirects} redirects"))
        route.abort("blockedbyclient")
    except Exception as exc:  # noqa: BLE001 - relay failure: the page gets a failed request, the walk a record
        state["record"](_request_record(request.url, request.method, request.resource_type, nav,
                                        reason=f"relay failed: {str(exc).splitlines()[0][:160]}"))
        with contextlib.suppress(Exception):
            route.abort("failed")


def _activate_wizard_network_guard(page: Page, blocked_requests: list[dict], policy: NetworkPolicy | None = None,
                                   permitted_requests: list[dict] | None = None, entered: Iterable[str] | None = None) -> dict:
    """Block the context's network traffic until `release_wizard_network_guard` (see the module docstring for the layers).

    `policy` (default: block everything) decides which HTTP(S) requests are relayed; `entered` is the live collection of
    values FormFiller has typed, which the policy uses to refuse requests that would carry them. Relayed requests are appended
    to `permitted_requests`, refused ones to `blocked_requests`.

    Connectivity is context-wide: every page in the context goes offline (and gets `offline`/`online` events), not only the one
    being walked. The caller's own offline setting is recorded first and put back by the release.

    Not covered: connections the page opened before this call (WebSocket traffic of those was dropped in the measurement
    made; a SharedWorker's is stopped only where the DevTools protocol is available), a SharedWorker created during the walk
    by a script that holds the browser's original constructor and a blob: script, and anything outside the browser. While the
    guard is idle the HTTP route defers to the caller's routes, and the WebSocket route is moved behind them.

    Returns what the walk should report: the SharedWorker fence in use."""
    context = page.context
    state = _NETWORK_GUARDS.get(context)
    if state is None:
        state = {"active": False, "blocked_requests": None, "permitted_requests": None, "prior_offline": False, "fence": None,
                 "ws_route": None, "ws_parked": False, "policy": NetworkPolicy(), "entered": set()}

        def record(entry: dict) -> None:
            if state["blocked_requests"] is not None:
                state["blocked_requests"].append(entry)

        state["record"] = record

        def handle_request(route) -> None:
            if not state["active"]:
                route.fallback()
                return
            request = route.request
            try:
                decision = state["policy"].decide(request.url, request.method, request.resource_type, _post_body(request),
                                                  state["entered"])
            except Exception as exc:  # noqa: BLE001 - a policy that cannot decide blocks
                decision = None
                reason = f"policy error: {exc}"
            if decision is not None and decision.allowed:
                _relay(route, request, state)
                return
            try:
                extra = {} if state["policy"].blocks_everything else {"reason": decision.reason if decision else reason}
                record(_request_record(request.url, request.method, request.resource_type, request.is_navigation_request(), **extra))
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
    downloads = DownloadGate(page, state["record"])
    try:
        install_fence(page)
        fence.engage()
        downloads.engage()
        state["blocked_requests"] = blocked_requests
        state["permitted_requests"] = permitted_requests
        state["policy"] = policy or NetworkPolicy()
        state["entered"] = entered if entered is not None else set()
        context.set_offline(True)  # raises if it cannot be applied: the caller then refuses to interact with the page
    except BaseException:
        fence.release()
        downloads.release()
        if not was_active:
            state["blocked_requests"] = None
            state["permitted_requests"] = None
            with contextlib.suppress(Exception):
                context.set_offline(prior_offline)  # whatever was applied, the context goes back to how the caller had it
        raise
    if was_active:
        state["fence"].release()
        if state.get("downloads") is not None:
            state["downloads"].release()
    state.update(fence=fence, downloads=downloads, prior_offline=prior_offline, active=True)
    return {"fence": fence, "downloads": downloads}
