"""Wizard network guard: what a protected walk lets out of the browser (local 127.0.0.1 server only; nothing leaves the machine).

Every blocking test has a positive control: the same page action, run WITHOUT the guard, must reach the local server. That is
what makes "the server received nothing" evidence instead of an assumption. The server records every request line it gets
(HTTP methods and WebSocket upgrades alike), so these tests observe the destination, not only what FormFiller reports.

Behaviour measured on Playwright 1.64.1 with its Chromium. If a browser upgrade changes what routing can see, a control or a
blocking test here fails and the notes in docs/OUTPUT_DESIGN.md must be revisited.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from formfill.web import pipeline
from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

SOURCE = {"company": {"name": "Acme Corp"}}
PAGE = b"""<!doctype html><html><body><form id="f" action="/collect" method="post">
<label for="org">Legal company name</label><input id="org">
<button type="button" id="next">Next</button></form><iframe name="sink" hidden></iframe></body></html>"""
SW_JS = b"""self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('message', () => { fetch('/sw-collect', {method: 'POST', body: 'x'}).catch(() => {}); });"""


@pytest.fixture(scope="module")
def target():
    received: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, body=b"ok", ctype="text/plain", extra=()):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/page", "/scope/page"):
                return self._reply(PAGE, "text/html")
            if path in ("/sw.js", "/scope/sw.js"):
                return self._reply(SW_JS, "text/javascript", [("Service-Worker-Allowed", "/")])
            received.append(("GET", self.path))
            self._reply()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            received.append(("POST", self.path))
            self._reply(b"")

        def do_OPTIONS(self):
            received.append(("OPTIONS", self.path))
            self._reply(b"", extra=[("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*")])

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def base(target):
    target[1].clear()
    return target[0]


@pytest.fixture
def received(target):
    return target[1]


def paths(received):
    return [p.split("?")[0] for _, p in received]


def wait_for_path(received, path, seconds=2.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path in paths(received):
            return True
        time.sleep(0.05)
    return False


def open_page(page, base, handler_js):
    page.goto(f"{base}/page")
    page.evaluate("(code) => document.querySelector('#next').addEventListener('click', new Function(code))", handler_js)


def walk(page, **kw):
    return run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0, **kw)


def host_of(base):
    return base.split("//", 1)[1]


def mechanisms(base):
    """name -> (page code run by the Next button, path the local server would see if it got out)."""
    h = host_of(base)
    post = "{method:'POST',body:'fictional'}"
    return {
        "sendBeacon": ("navigator.sendBeacon('/beacon', 'fictional')", "/beacon"),
        "image": ("new Image().src = '/img?fictional=1'", "/img"),
        "window.open": ("window.open('/popup?fictional=1')", "/popup"),
        "window.open noopener": ("window.open('/popup-noopener', '_blank', 'noopener')", "/popup-noopener"),
        "form into hidden iframe": ("const f=document.getElementById('f'); f.target='sink'; HTMLFormElement.prototype.submit.call(f)", "/collect"),
        "form target=_blank": ("const f=document.getElementById('f'); f.target='_blank'; HTMLFormElement.prototype.submit.call(f)", "/collect"),
        "EventSource": ("new EventSource('/events')", "/events"),
        "a[ping]": ("const a=document.createElement('a'); a.href='#x'; a.ping='/ping'; document.body.append(a); a.click()", "/ping"),
        "script src": ("const s=document.createElement('script'); s.src='/script.js'; document.head.append(s)", "/script.js"),
        "css url()": ("const s=document.createElement('style'); s.textContent='body{background:url(/css-bg)}'; document.head.append(s)", "/css-bg"),
        "iframe src": ("const i=document.createElement('iframe'); i.src='/frame'; document.body.append(i)", "/frame"),
        "fetch keepalive": (f"fetch('/keepalive',{{method:'POST',body:'fictional',keepalive:true}}).catch(()=>{{}})", "/keepalive"),
        "fetch no-cors": (f"fetch('/nocors',{{mode:'no-cors',method:'POST',body:'fictional'}}).catch(()=>{{}})", "/nocors"),
        "link rel=prefetch": ("const l=document.createElement('link'); l.rel='prefetch'; l.href='/prefetch'; document.head.append(l)", "/prefetch"),
        "dedicated Worker fetch": (f"new Worker(URL.createObjectURL(new Blob([\"fetch('{base}/worker-fetch',{post}).catch(()=>{{}})\"])))", "/worker-fetch"),
        "WebSocket inside a Worker": (f"new Worker(URL.createObjectURL(new Blob([\"new WebSocket('ws://{h}/worker-ws')\"])))", "/worker-ws"),
        "SharedWorker fetch": (f"new SharedWorker(URL.createObjectURL(new Blob([\"fetch('{base}/shared-fetch',{post}).catch(()=>{{}})\"])))", "/shared-fetch"),
    }


MECHANISM_NAMES = list(mechanisms("http://127.0.0.1:1"))


@pytest.mark.parametrize("name", MECHANISM_NAMES)
def test_control_the_action_reaches_the_server_without_the_guard(page, base, received, name):
    code, path = mechanisms(base)[name]
    open_page(page, base, code)
    page.click("#next")
    assert wait_for_path(received, path), f"positive control failed: {name} never reached the local server, so the blocking test proves nothing"


@pytest.mark.parametrize("name", MECHANISM_NAMES)
def test_the_action_is_stopped_by_the_guard_before_it_reaches_the_server(page, base, received, name):
    code, path = mechanisms(base)[name]
    open_page(page, base, code)

    result = walk(page)
    page.wait_for_timeout(900)  # long enough for the control above to have arrived

    assert path not in paths(received), f"{name} reached the server: {received}"
    assert "/collect" not in paths(received)
    assert result.status == "NEEDS_REVIEW" and result.navigation["network_guard_active"] is True
    assert result.navigation["completion"] in ("incomplete", "unconfirmed")


@pytest.mark.parametrize("name", [n for n in MECHANISM_NAMES if n != "WebSocket inside a Worker"])
def test_every_visible_attempt_is_recorded_and_stops_the_walk(page, base, received, name):
    code, _ = mechanisms(base)[name]
    open_page(page, base, code)
    result = walk(page)
    assert result.navigation["stop_reason"] == "outbound_request_blocked"
    assert result.navigation["blocked_requests"], "the attempt must be reported, not just dropped"
    assert any("blocked and not sent" in w for w in result.warnings)


def test_a_websocket_opened_inside_a_worker_cannot_reach_the_server_but_is_not_reported(page, base, received):
    code, path = mechanisms(base)["WebSocket inside a Worker"]
    open_page(page, base, code)
    result = walk(page)
    page.wait_for_timeout(900)
    assert path not in paths(received)
    assert result.status == "NEEDS_REVIEW"
    # offline emulation makes the worker's socket fail silently; no Playwright event describes it, so nothing is recorded
    assert result.navigation["stop_reason"] == "no_change_after_next" and result.navigation["blocked_requests"] == []


def test_a_websocket_attempt_never_reaches_the_server_and_the_page_sees_an_open_socket_that_goes_nowhere(page, base, received):
    """Documented behaviour, not an accident: the guard neither connects nor closes the socket. That is what Playwright 1.64.1
    does; on 1.48.0 (measured on Linux) a WebSocket route added after the page loaded does not apply to that page, so the
    socket is stopped by the offline switch alone and the page sees an error, and the attempt is not recorded. In both cases
    nothing reaches the server."""
    page.goto(f"{base}/page")
    page.evaluate("""() => document.querySelector('#next').addEventListener('click', () => {
        window.__ws = {events: []}; const ws = new WebSocket('ws://' + location.host + '/ws-page'); window.__ws.sock = ws;
        ws.onopen = () => { window.__ws.events.push('open'); try { ws.send('fictional') } catch (e) { window.__ws.events.push('send-error') } };
        ws.onerror = () => window.__ws.events.push('error');
    })""")
    result = walk(page)
    page.wait_for_timeout(700)
    state = page.evaluate("() => ({events: window.__ws.events, readyState: window.__ws.sock.readyState})")
    assert received == []  # no upgrade request and no message arrived, whatever the page saw
    assert state in ({"events": ["open"], "readyState": 1}, {"events": ["error"], "readyState": 3})
    if state["events"] == ["open"]:  # the WebSocket route handled it: recorded, and the walk stopped
        assert result.navigation["blocked_requests"][0]["method"] == "WEBSOCKET"
        assert result.navigation["stop_reason"] == "outbound_request_blocked"


@pytest.mark.parametrize("name", ["fetch keepalive", "link rel=prefetch", "SharedWorker fetch", "form target=_blank"])
def test_submit_true_never_submits_after_a_blocked_attempt(page, base, received, name):
    code, _ = mechanisms(base)[name]
    open_page(page, base, code)
    result = walk(page, submit=True)
    page.wait_for_timeout(500)
    assert result.submission["outcome"] == "SKIPPED" and result.submission["attempted"] is False
    assert result.status == "NEEDS_REVIEW" and received == []


# ---- routes the caller installed -----------------------------------------------------------------------------------------


def test_control_a_passthrough_page_route_reaches_the_server_without_the_guard(page, base, received):
    page.route("**/*", lambda r: r.continue_())
    open_page(page, base, "fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})")
    page.click("#next")
    assert wait_for_path(received, "/collect")


def test_a_passthrough_page_route_cannot_bypass_the_guard(page, base, received):
    """A page-level route runs before the guard's context route; its continue_() sends the request to the network."""
    page.route("**/*", lambda r: r.continue_())
    open_page(page, base, "fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})")
    result = walk(page)
    page.wait_for_timeout(700)
    assert "/collect" not in paths(received)
    assert result.navigation["stop_reason"] == "outbound_request_blocked" and result.navigation["blocked_requests"]


def test_a_passthrough_context_route_registered_before_the_guard_cannot_bypass_it(page, base, received):
    page.context.route("**/*", lambda r: r.continue_())
    open_page(page, base, "fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})")
    result = walk(page)
    page.wait_for_timeout(700)
    assert "/collect" not in paths(received) and result.navigation["stop_reason"] == "outbound_request_blocked"


def test_pass_through_routes_added_after_the_guard_is_active_cannot_send_either(page, base, received):
    open_page(page, base, "")
    walk(page)
    page.context.route("**/*", lambda r: r.continue_())
    page.route("**/*", lambda r: r.continue_())
    outcome = page.evaluate("() => fetch('/late-caller-route', {method: 'POST', body: 'x'}).then(() => 'sent', () => 'refused')")
    page.wait_for_timeout(400)
    assert outcome == "refused" and "/late-caller-route" not in paths(received)


def test_a_callers_context_mock_still_works_after_the_guard_is_released(page, base, received):
    """The inactive guard defers to the caller's routes; it must not send mocked calls to the real server."""
    page.context.route("**/mocked/**", lambda r: r.fulfill(status=200, body="MOCK"))
    open_page(page, base, "")
    assert walk(page).navigation["network_guard_active"] is True
    release_wizard_network_guard(page)
    assert page.evaluate("() => fetch('/mocked/x').then(r => r.text())") == "MOCK"
    assert "/mocked/x" not in paths(received)


def test_a_callers_page_mock_is_answered_locally_while_the_guard_is_active(page, base, received):
    page.route("**/mocked/**", lambda r: r.fulfill(status=200, body="MOCK"))
    open_page(page, base, "window.__mock = fetch('/mocked/x').then(r => r.text())")
    result = walk(page)
    assert page.evaluate("() => window.__mock") == "MOCK" and "/mocked/x" not in paths(received)
    assert result.navigation["blocked_requests"] == []  # answered locally: nothing was blocked, nothing went out


# ---- lifecycle: active until an explicit release ------------------------------------------------------------------------------


def test_the_guard_stays_active_after_the_run_until_it_is_released(page, base, received):
    open_page(page, base, "")
    result = walk(page)
    assert result.navigation["network_guard_active"] is True

    outcome = page.evaluate("() => fetch('/after-run', {method: 'POST', body: 'x'}).then(() => 'sent', () => 'refused')")
    page.wait_for_timeout(300)
    assert outcome == "refused" and "/after-run" not in paths(received)

    release_wizard_network_guard(page)
    assert page.evaluate("() => fetch('/after-release', {method: 'POST', body: 'x'}).then(() => 'sent', () => 'refused')") == "sent"
    assert "/after-release" in paths(received)


def test_release_is_explicit_and_a_second_run_on_the_same_context_is_guarded_again(page, base, received):
    open_page(page, base, "")
    walk(page)
    release_wizard_network_guard(page)
    open_page(page, base, "fetch('/second-run', {method:'POST', body:'fictional'}).catch(() => {})")  # navigation works once released
    result = walk(page)
    page.wait_for_timeout(500)
    assert result.navigation["stop_reason"] == "outbound_request_blocked" and "/second-run" not in paths(received)


def test_release_without_a_guard_does_nothing(page, base):
    page.goto(f"{base}/page")
    release_wizard_network_guard(page)  # must not raise or change the context
    assert page.evaluate("() => navigator.onLine") is True


def test_release_puts_the_context_back_online(page, base):
    open_page(page, base, "")
    walk(page)
    assert page.evaluate("() => navigator.onLine") is False
    release_wizard_network_guard(page)
    assert page.evaluate("() => navigator.onLine") is True


def test_a_guard_that_cannot_be_installed_stops_before_anything_is_touched(page, base, received, monkeypatch):
    open_page(page, base, "fetch('/collect', {method:'POST', body:'x'}).catch(() => {})")
    monkeypatch.setattr(page.context, "set_offline", lambda *_: (_ for _ in ()).throw(RuntimeError("offline emulation unavailable")))
    result = walk(page)
    assert result.navigation["stop_reason"] == "network_guard_unavailable"
    assert result.items == [] and page.input_value("#org") == ""  # nothing was filled or clicked
    assert received == [] and result.status == "NEEDS_REVIEW"


def test_a_blocked_attempt_makes_the_run_incomplete_even_when_another_reason_ended_the_walk(page, base, monkeypatch):
    """Fail closed: a recorded blocked request is never 'complete', whatever stop reason the walk ended with."""
    page.goto(f"{base}/page")
    real = pipeline._run_steps

    def run_and_pretend_a_request_was_blocked(*args, **kw):
        nav = real(*args, **kw)
        nav["stop_reason"] = "max_steps"  # not the reason that normally goes with a blocked request
        nav["blocked_requests"].append({"url": "http://127.0.0.1:1/x", "method": "POST", "resource_type": "fetch", "navigation": False})
        return nav

    monkeypatch.setattr(pipeline, "_run_steps", run_and_pretend_a_request_was_blocked)
    result = walk(page, submit=True)
    assert result.status == "NEEDS_REVIEW" and result.submission["outcome"] == "SKIPPED"
    assert any("blocked and not sent" in w for w in result.warnings)


def test_a_request_record_never_keeps_the_query_string_and_never_raises():
    rec = pipeline._request_record("https://portal.example/api/save?answer=secret#frag", "POST", "fetch")
    assert rec["url"] == "https://portal.example/api/save" and "secret" not in str(rec)
    bad = pipeline._request_record("http://[::1/path?answer=secret", "GET", "fetch")  # unparsable: still recorded, still no query
    assert "secret" not in str(bad)


# ---- service workers ----------------------------------------------------------------------------------------------------------


def _register_scoped_worker(page, base):
    page.goto(f"{base}/scope/page")
    page.evaluate("() => navigator.serviceWorker.register('/scope/sw.js', {scope: '/scope/'}).then(() => navigator.serviceWorker.ready)")
    page.wait_for_timeout(400)
    page.goto(f"{base}/page")  # outside the worker's scope: registered and active, but not controlling this page


MESSAGE_THE_WORKER = ("navigator.serviceWorker.getRegistration('/scope/').then(r => r && r.active && r.active.postMessage('go'))")


def test_control_a_registered_service_worker_can_send_a_request_without_the_guard(page, base, received):
    _register_scoped_worker(page, base)
    page.evaluate("(code) => document.querySelector('#next').addEventListener('click', new Function(code))", MESSAGE_THE_WORKER)
    page.click("#next")
    assert wait_for_path(received, "/sw-collect")


def test_a_registered_service_worker_is_refused_before_anything_is_filled_or_clicked(page, base, received):
    """On Playwright 1.64.1 routing blocks a registered worker's request, but on 1.48.0 one reached the local server (measured in a
    Linux run), so the walk refuses any registration rather than depend on the version."""
    _register_scoped_worker(page, base)
    page.evaluate("(code) => document.querySelector('#next').addEventListener('click', new Function(code))", MESSAGE_THE_WORKER)
    result = walk(page)
    page.wait_for_timeout(900)
    assert result.navigation["stop_reason"] == "service_worker_registered" and result.items == []
    assert page.input_value("#org") == "" and "/sw-collect" not in paths(received)
    assert result.status == "NEEDS_REVIEW" and page.evaluate("() => navigator.onLine") is True and page.context not in pipeline._NETWORK_GUARDS


def test_a_page_controlled_by_a_service_worker_is_not_walked(page, base, received):
    page.goto(f"{base}/page")
    page.evaluate("() => navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready)")
    page.wait_for_timeout(400)
    page.reload()
    assert page.evaluate("() => !!navigator.serviceWorker.controller")  # precondition: the worker controls the page
    page.evaluate("() => document.querySelector('#next').addEventListener('click', () => fetch('/collect', {method:'POST', body:'x'}))")
    result = walk(page)
    assert result.navigation["stop_reason"] == "service_worker_controls_page"
    assert result.items == [] and page.input_value("#org") == "" and "/collect" not in paths(received)
    assert result.status == "NEEDS_REVIEW"


# ---- SharedWorker: what the guard stops, and what it cannot ---------------------------------------------------------------------
#
# Each blocking test has the same page action as a control that runs WITHOUT the guard and must reach the local server.


def _worker_blob(base, path):
    return f"URL.createObjectURL(new Blob([\"fetch('{base}{path}',{{method:'POST',body:'fictional'}}).catch(()=>{{}})\"]))"


def shared_worker_cases(base):
    """name -> (page setup run before the walk, code run by the Next button, path the local server would see)."""
    blob = lambda path: _worker_blob(base, path)  # noqa: E731
    return {
        "SharedWorker.prototype.constructor": ("", f"new (SharedWorker.prototype.constructor)({blob('/sw-ctor')})", "/sw-ctor"),
        "same-origin iframe present before the walk": (
            "const f = document.createElement('iframe'); f.id = 'fr'; document.body.append(f)",
            f"new (document.getElementById('fr').contentWindow.SharedWorker)({blob('/sw-iframe-before')})", "/sw-iframe-before"),
        "iframe created during the walk": (
            "", f"const f = document.createElement('iframe'); document.body.append(f); new f.contentWindow.SharedWorker({blob('/sw-iframe-during')})",
            "/sw-iframe-during"),
        "srcdoc iframe with its own script": (
            "", f"const u = {blob('/sw-srcdoc')}; const f = document.createElement('iframe'); "
                "f.srcdoc = '<script>new SharedWorker(\"' + u + '\")</scr' + 'ipt>'; document.body.append(f)",
            "/sw-srcdoc"),
    }


SHARED_WORKER_CASES = list(shared_worker_cases("http://127.0.0.1:1"))


def open_shared_worker_case(page, base, name):
    setup, code, path = shared_worker_cases(base)[name]
    page.goto(f"{base}/page")
    if setup:
        page.evaluate(f"() => {{ {setup} }}")
    page.evaluate("(code) => document.querySelector('#next').addEventListener('click', new Function(code))", code)
    return path


@pytest.mark.parametrize("name", SHARED_WORKER_CASES)
def test_control_the_shared_worker_route_reaches_the_server_without_the_guard(page, base, received, name):
    path = open_shared_worker_case(page, base, name)
    page.click("#next")
    assert wait_for_path(received, path), f"positive control failed: {name} never reached the local server"


@pytest.mark.parametrize("name", SHARED_WORKER_CASES)
def test_the_guard_stops_the_shared_worker_route_before_it_reaches_the_server(page, base, received, name):
    path = open_shared_worker_case(page, base, name)
    result = walk(page)
    page.wait_for_timeout(900)
    assert path not in paths(received), f"{name} reached the server: {received}"
    assert result.navigation["stop_reason"] == "outbound_request_blocked"
    assert result.navigation["blocked_requests"][0]["resource_type"] == "sharedworker"
    assert result.status == "NEEDS_REVIEW"


def start_preexisting_shared_worker(page, base):
    """A page that already has a SharedWorker (and its port) before FormFiller arrives; the worker sends when the page says go."""
    page.goto(f"{base}/page")
    page.evaluate(
        """(base) => {
        const src = `onconnect = e => { const p = e.ports[0]; p.onmessage = () => { fetch('${base}/sw-preexisting', {method:'POST', body:'fictional'}).catch(() => {}); }; p.start(); };`;
        window.__sw = new SharedWorker(URL.createObjectURL(new Blob([src])));
        window.__sw.port.start();
        document.querySelector('#next').addEventListener('click', () => window.__sw.port.postMessage('go'));
    }""", base)
    page.wait_for_timeout(300)  # the worker is running and connected


def test_control_a_shared_worker_created_before_the_walk_can_send_without_the_guard(page, base, received):
    start_preexisting_shared_worker(page, base)
    page.click("#next")
    assert wait_for_path(received, "/sw-preexisting")


def test_a_shared_worker_created_before_the_walk_is_taken_offline(page, base, received):
    start_preexisting_shared_worker(page, base)
    result = walk(page)
    page.wait_for_timeout(900)
    assert "/sw-preexisting" not in paths(received)
    assert any(n["kind"] == "shared_worker_taken_offline" and n["count"] == 1 for n in result.navigation["notes"])
    assert result.status == "NEEDS_REVIEW"


def test_a_shared_worker_taken_offline_works_again_after_release(page, base, received):
    start_preexisting_shared_worker(page, base)
    walk(page)
    page.click("#next")
    page.wait_for_timeout(600)
    assert "/sw-preexisting" not in paths(received)
    release_wizard_network_guard(page)
    page.click("#next")
    assert wait_for_path(received, "/sw-preexisting"), "release must end the worker's offline emulation too"


def test_a_shared_worker_that_cannot_be_taken_offline_stops_the_walk_before_anything_is_touched(page, base, received, monkeypatch):
    from formfill.web.sharedworkers import SharedWorkerFence

    start_preexisting_shared_worker(page, base)

    def refuse(self, *_a, **_k):
        raise RuntimeError("worker refused")

    monkeypatch.setattr(SharedWorkerFence, "_call", refuse)
    result = walk(page)
    assert result.navigation["stop_reason"] == "network_guard_unavailable" and result.items == []
    assert page.evaluate("() => navigator.onLine") is True  # the guard did not start, so nothing is left switched on
    assert result.status == "NEEDS_REVIEW"


def test_without_devtools_access_the_run_says_it_could_not_look_for_shared_workers(page, base, monkeypatch):
    open_page(page, base, "")
    monkeypatch.setattr(page.context.browser, "new_browser_cdp_session", lambda: (_ for _ in ()).throw(RuntimeError("no CDP")))
    result = walk(page)
    assert any(n["kind"] == "shared_worker_check_unavailable" for n in result.navigation["notes"])
    assert result.navigation["network_guard_active"] is True  # the other layers are unaffected


def test_a_worker_made_from_a_blob_with_a_constructor_the_page_kept_from_before_the_guard_is_reported_but_not_prevented(page, base, received):
    """A known gap, pinned only as far as it is true. The page captured `SharedWorker` before the guard, so it never meets the
    replacement, and a blob: script cannot be routed. The worker is found by the scan after the click and the walk stops, but
    one that sends from its start-up script has already got the request out (measured: 8 of 8 reached the local server). This
    asserts the report, not prevention."""
    page.goto(f"{base}/page")
    page.evaluate("""() => { window.__RealSW = window.SharedWorker;
        document.querySelector('#next').addEventListener('click', () => { window.__w = new window.__RealSW(URL.createObjectURL(new Blob(['onconnect = () => {}']))); }); }""")
    result = walk(page)
    assert result.navigation["stop_reason"] == "outbound_request_blocked"
    assert result.navigation["blocked_requests"][0]["resource_type"] == "sharedworker"


def test_a_worker_loaded_from_a_url_with_a_kept_constructor_is_stopped_because_its_script_is_a_blocked_request(page, base, received):
    page.goto(f"{base}/page")
    page.evaluate("""(base) => { window.__RealSW = window.SharedWorker;
        document.querySelector('#next').addEventListener('click', () => { window.__w = new window.__RealSW(base + '/shared-script.js'); }); }""", base)
    result = walk(page)
    page.wait_for_timeout(600)
    assert "/shared-script.js" not in paths(received)
    assert result.navigation["stop_reason"] == "outbound_request_blocked" and result.navigation["blocked_requests"]


def test_the_shared_worker_constructor_behaves_normally_after_release(page, base, received):
    open_page(page, base, "")
    walk(page)
    release_wizard_network_guard(page)
    page.evaluate(f"() => {{ window.__w = new SharedWorker({_worker_blob(base, '/sw-after-release')}); }}")
    assert wait_for_path(received, "/sw-after-release")
    assert page.evaluate("() => window.__w instanceof SharedWorker && window.__w.port !== undefined")


# ---- connectivity: the caller's own setting survives the guard -------------------------------------------------------------------


def form_page(browser, **context_options):
    context = browser.new_context(**context_options)
    pg = context.new_page()
    pg.set_content('<label for="org">Legal company name</label><input id="org"><button type="button" id="next">Next</button>')
    return context, pg


def online(page):
    return page.evaluate("() => navigator.onLine")


def test_a_context_the_caller_had_offline_is_offline_again_after_release(browser):
    context, pg = form_page(browser)
    try:
        context.set_offline(True)  # the caller's own choice, made before FormFiller
        walk(pg)
        release_wizard_network_guard(pg)
        assert online(pg) is False
    finally:
        context.close()


def test_starting_the_guard_does_not_reset_the_offline_emulation_it_finds(browser):
    """Detaching a page-level DevTools session resets the page's network emulation (measured); the fence must never do that."""
    context, pg = form_page(browser, offline=True)
    try:
        for _ in range(2):
            walk(pg)
            assert online(pg) is False
    finally:
        context.close()


def test_a_context_created_offline_stays_offline_after_release(browser):
    context, pg = form_page(browser, offline=True)
    try:
        walk(pg)
        assert online(pg) is False
        release_wizard_network_guard(pg)
        assert online(pg) is False
    finally:
        context.close()


def test_a_context_that_was_online_is_online_again_after_release(browser):
    context, pg = form_page(browser)
    try:
        walk(pg)
        assert online(pg) is False
        release_wizard_network_guard(pg)
        assert online(pg) is True
    finally:
        context.close()


def test_a_second_walk_while_the_guard_is_active_still_remembers_the_original_setting(browser):
    context, pg = form_page(browser)
    try:
        walk(pg)
        walk(pg)  # the page now reports offline because of the guard itself, which must not be recorded as the caller's choice
        assert online(pg) is False  # ... and the second activation must not have put the context back online
        release_wizard_network_guard(pg)
        assert online(pg) is True
    finally:
        context.close()


def test_releasing_twice_does_not_override_what_the_caller_set_in_between(browser):
    context, pg = form_page(browser)
    try:
        walk(pg)
        release_wizard_network_guard(pg)
        context.set_offline(True)  # the caller takes the context offline after the release
        release_wizard_network_guard(pg)  # a repeated release has nothing to undo
        assert online(pg) is False
    finally:
        context.close()


@pytest.mark.parametrize("caller_offline", [False, True])
def test_a_failed_activation_leaves_the_context_as_the_caller_had_it(browser, monkeypatch, caller_offline):
    from formfill.web.sharedworkers import SharedWorkerFence

    context, pg = form_page(browser, offline=caller_offline)
    try:
        monkeypatch.setattr(SharedWorkerFence, "engage", lambda self: (_ for _ in ()).throw(RuntimeError("cannot fence")))
        result = walk(pg)
        assert result.navigation["stop_reason"] == "network_guard_unavailable" and result.items == []
        assert online(pg) is (not caller_offline)
        assert pipeline._NETWORK_GUARDS[context]["active"] is False
    finally:
        context.close()


def test_a_page_that_is_not_walked_leaves_the_context_alone(page, base):
    page.goto(f"{base}/page")
    page.evaluate("() => navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready)")
    page.wait_for_timeout(400)
    page.reload()
    walk(page)  # stops with service_worker_controls_page before the guard exists
    assert online(page) is True and page.context not in pipeline._NETWORK_GUARDS


def test_an_exception_during_the_walk_is_reported_and_the_guard_can_be_released(page, base, received, monkeypatch):
    open_page(page, base, "fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})")
    real = pipeline.discover
    calls = []

    def crash_on_the_second_discovery(pg):
        calls.append(1)
        if len(calls) >= 2:
            raise RuntimeError("simulated crash during discovery")
        return real(pg)

    monkeypatch.setattr(pipeline, "discover", crash_on_the_second_discovery)
    with pytest.raises(RuntimeError, match="simulated crash") as raised:
        walk(page)
    monkeypatch.undo()
    notes = " ".join(getattr(raised.value, "__notes__", []))
    assert "release_wizard_network_guard" in notes and "still active" in notes  # not a silent state
    assert online(page) is False and pipeline._NETWORK_GUARDS[page.context]["active"] is True  # fail closed: nothing is let out
    outcome = page.evaluate("() => fetch('/after-crash', {method:'POST', body:'x'}).then(() => 'sent', () => 'refused')")
    assert outcome == "refused" and "/after-crash" not in paths(received)
    release_wizard_network_guard(page)
    assert online(page) is True and pipeline._NETWORK_GUARDS[page.context]["active"] is False


def test_an_exception_after_the_walk_returned_is_reported_too(page, base, monkeypatch):
    open_page(page, base, "")
    monkeypatch.setattr(pipeline, "overall_status", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late failure")))
    with pytest.raises(RuntimeError, match="late failure") as raised:
        walk(page)
    assert any("release_wizard_network_guard" in n for n in getattr(raised.value, "__notes__", []))
    monkeypatch.undo()
    release_wizard_network_guard(page)


def test_an_exception_before_any_guard_exists_gets_no_note(page, base):
    with pytest.raises(ValueError) as raised:
        run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=-1)
    assert not getattr(raised.value, "__notes__", [])


def test_the_whole_context_goes_offline_and_comes_back_other_pages_included(browser, base):
    """Connectivity is context-wide: a second tab is affected while the guard holds, and is restored by the release."""
    context, pg = form_page(browser)
    try:
        other = context.new_page()
        other.goto(f"{base}/page")
        other.evaluate("() => { window.__events = []; addEventListener('offline', () => __events.push('offline')); addEventListener('online', () => __events.push('online')); }")
        walk(pg)
        assert online(other) is False and other.evaluate("() => __events") == ["offline"]
        release_wizard_network_guard(pg)
        assert online(other) is True and other.evaluate("() => __events") == ["offline", "online"]
    finally:
        context.close()


def test_a_page_that_reacts_to_going_offline_stops_safely_and_the_report_names_the_cause(browser):
    context, pg = form_page(browser)
    try:
        pg.evaluate("() => addEventListener('offline', () => { document.getElementById('org').disabled = true })")
        result = walk(pg)
        assert result.status == "NEEDS_REVIEW" and not any(i.filled for i in result.items) and pg.input_value("#org") == ""
        note = next(n for n in result.navigation["notes"] if n["kind"] == "network_guard_active")
        assert "reacts to going offline" in note["reason"]
    finally:
        context.close()


# ---- WebSocket routes the caller registered ---------------------------------------------------------------------------------------

WEBSOCKET_PROBE = """(url) => new Promise(resolve => {
    const ws = new WebSocket(url);
    const timer = setTimeout(() => resolve('no reply'), 1200);
    ws.onopen = () => ws.send('hi');
    ws.onmessage = e => { clearTimeout(timer); resolve(e.data); };
    ws.onerror = () => { clearTimeout(timer); resolve('error'); };
})"""


def ws_url(base):
    return "ws://" + base.split("//", 1)[1] + "/mockws"


def mock_websocket(context):
    context.route_web_socket("**/mockws", lambda ws: ws.on_message(lambda message: ws.send("MOCK:" + message)))


def test_control_a_websocket_reaches_the_server_when_nothing_mocks_it(page, base, received):
    page.goto(f"{base}/page")
    page.evaluate(WEBSOCKET_PROBE, ws_url(base))
    assert "/mockws" in paths(received)


def test_a_callers_websocket_mock_answers_without_touching_the_server_at_all(page, base, received):
    mock_websocket(page.context)
    page.goto(f"{base}/page")
    assert page.evaluate(WEBSOCKET_PROBE, ws_url(base)) == "MOCK:hi" and "/mockws" not in paths(received)


def test_a_websocket_mock_registered_before_the_walk_still_answers_after_release_and_never_reaches_the_server(page, base, received):
    mock_websocket(page.context)
    open_page(page, base, "")
    for _ in range(2):  # the second cycle re-arms a guard that was parked behind the mock
        walk(page)
        release_wizard_network_guard(page)
        assert page.evaluate(WEBSOCKET_PROBE, ws_url(base)) == "MOCK:hi"
        open_page(page, base, "")
    assert "/mockws" not in paths(received)


def test_a_websocket_mock_registered_after_the_guard_was_released_answers_too(page, base, received):
    open_page(page, base, "")
    walk(page)
    release_wizard_network_guard(page)
    mock_websocket(page.context)
    page.goto(f"{base}/page")  # Playwright 1.48 applies a WebSocket route added after a page loaded only to pages loaded after it
    assert page.evaluate(WEBSOCKET_PROBE, ws_url(base)) == "MOCK:hi" and "/mockws" not in paths(received)


def test_while_the_guard_is_active_a_websocket_mock_registered_earlier_neither_answers_nor_reaches_the_server(page, base, received):
    mock_websocket(page.context)
    open_page(page, base, "")
    walk(page)
    assert page.evaluate(WEBSOCKET_PROBE, ws_url(base)) == "no reply" and "/mockws" not in paths(received)


def test_a_websocket_without_a_mock_connects_normally_after_release(page, base, received):
    open_page(page, base, "")
    walk(page)
    release_wizard_network_guard(page)
    page.evaluate(WEBSOCKET_PROBE, ws_url(base))
    assert "/mockws" in paths(received)


def test_if_the_websocket_route_cannot_be_parked_the_release_warns(page, base, monkeypatch):
    open_page(page, base, "")
    walk(page)
    monkeypatch.setattr(pipeline, "_place_websocket_route", lambda *a, **k: False)
    with pytest.warns(RuntimeWarning, match="shadowed"):
        release_wizard_network_guard(page)


def test_a_guard_whose_websocket_route_cannot_be_put_back_in_front_refuses_to_start(page, base, received, monkeypatch):
    open_page(page, base, "")
    walk(page)
    release_wizard_network_guard(page)  # parked behind the caller's routes
    monkeypatch.setattr(pipeline, "_place_websocket_route", lambda *a, **k: False)
    open_page(page, base, "fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})")
    result = walk(page)
    assert result.navigation["stop_reason"] == "network_guard_unavailable" and result.items == []
    assert "/collect" not in paths(received)


# ---- WebRTC: ICE gathering sends UDP, which routing never sees ----------------------------------------------------------------------


@pytest.fixture
def udp_sink():
    """A UDP socket on 127.0.0.1 that counts what arrives (an ICE server stand-in; nothing leaves the machine)."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.2)
    datagrams: list[int] = []
    stop = threading.Event()

    def listen():
        while not stop.is_set():
            try:
                datagrams.append(len(sock.recvfrom(4096)[0]))
            except (TimeoutError, OSError):
                continue

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1], datagrams
    finally:
        stop.set()
        thread.join()
        sock.close()


def webrtc_code(port):
    return (f"const pc = new RTCPeerConnection({{iceServers: [{{urls: 'stun:127.0.0.1:{port}'}}]}}); pc.createDataChannel('x'); "
            "pc.createOffer().then(o => pc.setLocalDescription(o))")


def test_control_webrtc_ice_gathering_reaches_a_local_udp_listener_without_the_guard(page, base, udp_sink):
    port, datagrams = udp_sink
    open_page(page, base, webrtc_code(port))
    page.click("#next")
    page.wait_for_timeout(2500)
    assert datagrams, "positive control failed: no STUN datagram arrived, so the blocking test proves nothing"


def test_webrtc_ice_gathering_is_stopped_by_the_guard_before_a_datagram_is_sent(page, base, udp_sink):
    port, datagrams = udp_sink
    open_page(page, base, webrtc_code(port))
    result = walk(page)
    page.wait_for_timeout(2500)
    assert datagrams == []
    assert result.status == "NEEDS_REVIEW" and result.navigation["network_guard_active"] is True


# ---- a WebSocket the page opened before the walk ---------------------------------------------------------------------------------------


@pytest.fixture
def echo_server():
    """A minimal local WebSocket server that records the text frames it receives; also serves the form page."""
    import base64
    import hashlib

    frames: list[str] = []
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Upgrade", "").lower() != "websocket":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)
                return
            accept = base64.b64encode(hashlib.sha1((self.headers["Sec-WebSocket-Key"] + guid).encode()).digest()).decode()
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
            self.wfile.flush()
            try:
                while True:
                    head = self.rfile.read(2)
                    if len(head) < 2:
                        return
                    size = head[1] & 0x7F
                    if size == 126:
                        size = int.from_bytes(self.rfile.read(2), "big")
                    mask = self.rfile.read(4)
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(self.rfile.read(size)))
                    if head[0] & 0x0F == 8:
                        return
                    frames.append(data.decode(errors="replace"))
            except OSError:
                return

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", frames
    finally:
        server.shutdown()
        server.server_close()


PREOPENED_SOCKET = """(url) => new Promise(resolve => {
    window.__ws = new WebSocket(url);
    window.__ws.onopen = () => resolve('open');
    document.querySelector('#next').addEventListener('click', () => window.__ws.send('sent-on-next'));
})"""


def wait_for_frame(frames, text, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if text in frames:
            return True
        time.sleep(0.05)
    return False


def test_control_a_websocket_opened_before_the_walk_delivers_what_the_page_sends(page, echo_server):
    base, frames = echo_server
    page.goto(f"{base}/page")
    assert page.evaluate(PREOPENED_SOCKET, "ws://" + base.split("//", 1)[1] + "/chat") == "open"
    page.click("#next")
    assert wait_for_frame(frames, "sent-on-next")


def test_a_websocket_opened_before_the_walk_does_not_deliver_what_the_page_sends_during_it(page, echo_server):
    """Measured on Playwright 1.64.1: the offline switch drops traffic on the existing connection. Not a guarantee for
    other browser versions; `docs/OUTPUT_DESIGN.md` says the same."""
    base, frames = echo_server
    page.goto(f"{base}/page")
    assert page.evaluate(PREOPENED_SOCKET, "ws://" + base.split("//", 1)[1] + "/chat") == "open"
    walk(page)
    page.evaluate("() => { try { window.__ws.send('sent-during-guard') } catch (e) {} }")
    assert not wait_for_frame(frames, "sent-on-next", 1.0) and not wait_for_frame(frames, "sent-during-guard", 1.0)


def test_a_window_level_capturing_submit_handler_runs_first_but_what_it_sends_is_blocked(page, base, received):
    """The cancelling listener is on `document`, so a capturing handler on `window` sees the submit event before it. The
    documentation says so; this shows the consequence is contained by the network layers."""
    page.goto(f"{base}/page")
    page.evaluate("""() => {
        window.__early = 0;
        window.addEventListener('submit', () => { window.__early++; fetch('/early-submit', {method: 'POST', body: 'fictional'}).catch(() => {}); }, true);
        document.querySelector('#next').addEventListener('click', () => document.getElementById('f').requestSubmit());
    }""")
    result = walk(page)
    page.wait_for_timeout(700)
    assert page.evaluate("() => window.__early") == 1  # it did run first
    assert "/early-submit" not in paths(received) and "/collect" not in paths(received)
    assert result.navigation["blocked_requests"] and result.status == "NEEDS_REVIEW"


def test_the_shared_worker_fence_covers_other_tabs_of_the_context_too(browser, base, received):
    context, pg = form_page(browser)
    try:
        before = context.new_page()
        before.goto(f"{base}/page")  # open before the walk
        walk(pg)
        after = context.new_page()  # opened while the guard is on
        after.set_content("<p>tab</p>")
        for tab in (before, after):
            outcome = tab.evaluate(f"() => {{ try {{ new SharedWorker({_worker_blob(base, '/sw-other-tab')}); return 'created'; }} catch (e) {{ return e.name; }} }}")
            assert outcome == "SecurityError"
        pg.wait_for_timeout(500)
        assert "/sw-other-tab" not in paths(received)
        release_wizard_network_guard(pg)
        assert before.evaluate(f"() => {{ try {{ new SharedWorker({_worker_blob(base, '/sw-other-tab')}); return 'created'; }} catch (e) {{ return e.name; }} }}") == "created"
    finally:
        context.close()


def test_without_the_client_internal_the_guard_still_works_across_cycles_and_release_warns(browser, monkeypatch):
    """If Playwright's WebSocket route list is not where the guard expects it, nothing can be parked: release says so, and the
    guard (never moved) keeps working for later walks instead of refusing to start."""
    monkeypatch.setattr(pipeline, "_websocket_route_entry", lambda *a, **k: None)
    context, pg = form_page(browser)
    try:
        walk(pg)
        with pytest.warns(RuntimeWarning, match="shadowed"):
            release_wizard_network_guard(pg)
        result = walk(pg)
        assert result.navigation["network_guard_active"] is True and result.navigation["stop_reason"] != "network_guard_unavailable"
        with pytest.warns(RuntimeWarning):
            release_wizard_network_guard(pg)
    finally:
        context.close()


def test_run_form_still_accepts_the_page_as_a_keyword_and_still_reports_an_active_guard(page, base, monkeypatch):
    open_page(page, base, "")
    monkeypatch.setattr(pipeline, "overall_status", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late failure")))
    with pytest.raises(RuntimeError) as raised:
        run_form(page=page, source=SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    assert any("release_wizard_network_guard" in n for n in getattr(raised.value, "__notes__", []))
    monkeypatch.undo()
    release_wizard_network_guard(page)


def test_the_playwright_internal_the_websocket_parking_relies_on_is_still_where_it_was_expected(browser):
    """The guard reorders the client's own list of WebSocket routes (see `_place_websocket_route`). If Playwright changes that,
    this fails with a clear message instead of leaving only indirect failures in the WebSocket mock tests."""
    context = browser.new_context()
    try:
        def handler(route):
            return None

        context.route_web_socket("**/*", handler)
        entry = pipeline._websocket_route_entry(context, handler)
        assert entry is not None, "Playwright's WebSocket route list moved: update pipeline._websocket_route_entry / _place_websocket_route"
        routes = context._impl_obj._web_socket_routes
        assert pipeline._place_websocket_route(context, entry, first=False) and routes[-1] is entry
        assert pipeline._place_websocket_route(context, entry, first=True) and routes[0] is entry
    finally:
        context.close()
