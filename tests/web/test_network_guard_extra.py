"""Requirement B: further channels through which a page could send data during a guarded walk. Local servers only (two
127.0.0.1 ports = two origins). Every blocking test has a positive control that runs the same page action WITHOUT the guard
and must reach the server; otherwise "nothing arrived" would prove nothing.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from formfill.web.netpolicy import AllowRule, NetworkPolicy
from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser
SOURCE = {"company": {"name": "Acme Corp"}}
PAGE = b"""<!doctype html><html><body><label for="org">Legal company name</label><input id="org">
<button type="button" id="next">Next</button><div id="slot"></div></body></html>"""


def frame_page(other_base: str) -> bytes:
    """The cross-origin frame: on a message it sends a fetch, or starts a SharedWorker whose script sends one."""
    return (f"""<!doctype html><html><body><p>embedded</p><script>
window.addEventListener('message', e => {{
  if (e.data === 'fetch') fetch('{other_base}/xo-fetch', {{method: 'POST', body: 'fictional'}}).catch(() => {{}});
  if (e.data === 'worker') {{
    try {{ new SharedWorker(URL.createObjectURL(new Blob(["fetch('{other_base}/xo-worker', {{method:'POST', body:'x'}}).catch(()=>{{}})"]))); }}
    catch (err) {{ window.__err = err.name; }}
  }}
}});
</script></body></html>""").encode()


class _Recorder:
    def __init__(self):
        self.received: list[str] = []
        self.other = ""

    def paths(self):
        return [p.split("?")[0] for p in self.received]

    def wait_for(self, path, seconds=2.5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if path in self.paths():
                return True
            time.sleep(0.05)
        return False


def _serve(rec: _Recorder):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body=b"ok", ctype="text/plain", headers=()):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/page":
                return self._send(200, PAGE, "text/html")
            if path == "/frame":
                return self._send(200, frame_page(rec.self_base), "text/html")
            rec.received.append(self.path)
            if path == "/hop":
                return self._send(302, b"", headers=[("Location", f"{rec.other}/landing")])
            if path == "/file.csv":
                return self._send(200, b"a,b\n1,2\n", "text/csv", [("Content-Disposition", 'attachment; filename="file.csv"')])
            return self._send(200)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            rec.received.append(self.path)
            return self._send(200)

        def do_OPTIONS(self):
            rec.received.append("OPTIONS " + self.path)
            return self._send(200, b"", headers=[("Access-Control-Allow-Headers", "*"), ("Access-Control-Allow-Methods", "*")])

        def log_message(self, *_):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(scope="module")
def origins():
    a, b = _Recorder(), _Recorder()
    sa, sb = _serve(a), _serve(b)
    a.self_base, b.self_base = f"http://127.0.0.1:{sa.server_address[1]}", f"http://127.0.0.1:{sb.server_address[1]}"
    a.other, b.other = b.self_base, a.self_base
    try:
        yield a, b
    finally:
        sa.shutdown()
        sb.shutdown()


@pytest.fixture
def ab(origins):
    for r in origins:
        r.received.clear()
    return origins


def open_page(page, a, b, on_next: str, with_frame: bool = False):
    release_wizard_network_guard(page)
    page.goto(f"{a.self_base}/page")
    if with_frame:
        page.evaluate("(src) => { const f = document.createElement('iframe'); f.id = 'xo'; f.src = src; document.getElementById('slot').append(f); }",
                      f"{b.self_base}/frame")
        page.wait_for_function("() => { try { return document.getElementById('xo').contentWindow.length >= 0 } catch (e) { return true } }")
        page.wait_for_timeout(300)
    page.evaluate("(code) => document.getElementById('next').addEventListener('click', new Function(code))", on_next)


def walk(page, **kw):
    return run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0, **kw)


TO_FRAME = "document.getElementById('xo').contentWindow.postMessage('{msg}', '*')"


# ---- a cross-origin iframe ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("msg", "path"), [("fetch", "/xo-fetch"), ("worker", "/xo-worker")])
def test_control_a_cross_origin_iframe_can_send_without_the_guard(page, ab, msg, path):
    a, b = ab
    open_page(page, a, b, TO_FRAME.format(msg=msg), with_frame=True)
    page.click("#next")
    assert b.wait_for(path), f"positive control failed: {msg} from the cross-origin frame never reached its server"


def test_a_fetch_from_a_cross_origin_iframe_is_blocked_and_recorded(page, ab):
    a, b = ab
    open_page(page, a, b, TO_FRAME.format(msg="fetch"), with_frame=True)
    result = walk(page)
    page.wait_for_timeout(900)
    assert "/xo-fetch" not in b.paths()
    assert any(r["url"].endswith("/xo-fetch") for r in result.navigation["blocked_requests"])
    assert result.status == "NEEDS_REVIEW"


def test_a_shared_worker_started_in_a_cross_origin_iframe_is_refused_but_not_reported(page, ab):
    """The fence is installed in every frame, cross-origin ones included, so the worker is never created. It records the
    attempt in its own frame (a cross-origin frame cannot write to the top page), so the walk does not list it."""
    a, b = ab
    open_page(page, a, b, TO_FRAME.format(msg="worker"), with_frame=True)
    walk(page)
    page.wait_for_timeout(900)
    assert "/xo-worker" not in b.paths()
    frame = next(f for f in page.frames if f.url.startswith(b.self_base))
    assert frame.evaluate("() => window.__err") == "SecurityError"


# ---- downloads ------------------------------------------------------------------------------------------------------------------

DOWNLOAD = "const l = document.createElement('a'); l.href = '/file.csv'; l.download = 'file.csv'; document.body.append(l); l.click();"


def test_control_a_download_reaches_the_server_without_the_guard(browser, ab):
    a, b = ab
    context = browser.new_context(accept_downloads=True)
    try:
        page = context.new_page()
        open_page(page, a, b, DOWNLOAD)
        page.click("#next")
        assert a.wait_for("/file.csv")
    finally:
        context.close()


def test_a_download_started_by_next_is_blocked_before_it_reaches_the_server(browser, ab):
    a, b = ab
    context = browser.new_context(accept_downloads=True)
    try:
        page = context.new_page()
        open_page(page, a, b, DOWNLOAD)
        result = walk(page)
        page.wait_for_timeout(700)
        assert "/file.csv" not in a.paths()
        assert result.navigation["blocked_requests"] and result.status == "NEEDS_REVIEW"
    finally:
        context.close()


# ---- WebTransport ---------------------------------------------------------------------------------------------------------------

WEBTRANSPORT = "try { window.__wt = new WebTransport('https://127.0.0.1:9/wt'); window.__wtState = 'constructed'; } catch (e) { window.__wtState = e.name; }"


def test_control_webtransport_can_be_constructed_without_the_guard(page, ab):
    a, b = ab
    open_page(page, a, b, WEBTRANSPORT)
    if not page.evaluate("() => typeof WebTransport === 'function'"):
        pytest.fail("this Chromium has no WebTransport: the blocking test below would prove nothing")
    page.click("#next")
    assert page.evaluate("() => window.__wtState") == "constructed"


def test_webtransport_is_refused_during_a_walk_and_the_attempt_stops_it(page, ab):
    a, b = ab
    open_page(page, a, b, WEBTRANSPORT)
    result = walk(page)
    assert page.evaluate("() => window.__wtState") == "SecurityError"
    assert result.navigation["stop_reason"] == "outbound_request_blocked"
    assert any(r["resource_type"] == "webtransport" for r in result.navigation["blocked_requests"])


def test_after_release_webtransport_behaves_as_before(page, ab):
    a, b = ab
    open_page(page, a, b, "")
    walk(page)
    release_wizard_network_guard(page)
    page.evaluate(WEBTRANSPORT)
    assert page.evaluate("() => window.__wtState") == "constructed"


# ---- a relayed request that redirects to another origin -------------------------------------------------------------------------

HOP = "fetch('/hop').catch(() => {})"


def test_control_a_redirect_to_another_origin_is_followed_without_the_guard(page, ab):
    a, b = ab
    open_page(page, a, b, HOP)
    page.click("#next")
    assert b.wait_for("/landing")


def test_a_relayed_request_is_not_followed_to_another_origin(page, ab):
    a, b = ab
    open_page(page, a, b, HOP)
    policy = NetworkPolicy(rules=(AllowRule(origin=a.self_base, path="/hop", methods=frozenset({"GET"})),))
    result = walk(page, network_policy=policy)
    page.wait_for_timeout(700)
    assert "/hop" in a.paths()  # the allowed first hop was relayed ...
    assert "/landing" not in b.paths()  # ... but the redirect to another origin was checked and refused
    refused = [r for r in result.navigation["blocked_requests"] if "redirect hop refused" in (r.get("reason") or "")]
    assert refused and refused[0]["url"].endswith("/landing")
    assert result.navigation["stop_reason"] == "outbound_request_blocked"


def test_the_walk_records_which_playwright_and_browser_it_ran_on(page, ab):
    a, b = ab
    open_page(page, a, b, "")
    versions = walk(page).navigation["versions"]
    assert versions["playwright"] and versions["browser"]


def test_the_download_gate_never_outlives_its_context(browser, ab):
    """The gate is browser-wide DevTools interception: a context closed without a release must not leave it blocking other
    contexts' downloads."""
    a, b = ab
    guarded = browser.new_context(accept_downloads=True)
    page = guarded.new_page()
    open_page(page, a, b, DOWNLOAD)
    result = walk(page)
    assert any(r["resource_type"] == "download" for r in result.navigation["blocked_requests"])
    guarded.close()  # closed without release_wizard_network_guard
    other = browser.new_context(accept_downloads=True)
    try:
        page2 = other.new_page()
        a.received.clear()
        open_page(page2, a, b, DOWNLOAD)
        page2.click("#next")
        assert a.wait_for("/file.csv")
    finally:
        other.close()
