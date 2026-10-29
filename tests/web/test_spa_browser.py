"""Phase 3C: SPA browser behaviour against local fixtures (benchmarks/spa). Nothing here touches a real portal."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "spa"
SOURCE = json.loads((BENCH / "source.json").read_text())
GT = json.loads((BENCH / "ground_truth.json").read_text())

import sys

sys.path.insert(0, str(BENCH.parents[1]))
from benchmarks.spa.server import serve


@pytest.fixture(scope="module")
def base():
    with serve() as url:
        yield url


@pytest.fixture
def run(page, base):
    def _run(fid, policy=True, **kw):
        release_wizard_network_guard(page)
        # The wizard guard blocks every request, so the fixtures' /api/delay call (a slow endpoint on the local benchmark server)
        # can no longer be answered by that server during a guarded walk. This init script answers it inside the page after the
        # same delay instead. What the tests still exercise is FormFiller's settle logic, which waits on the page's own pending
        # fetch (its counter wraps whatever `window.fetch` is when the walk starts); what they no longer exercise is a real
        # server round trip, which the guard exists to prevent. Tests of the guard itself are in test_network_guard.py.
        page.add_init_script(
            """(() => {
              if (window.__ffLocalDelayMock) return;
              window.__ffLocalDelayMock = true;
              const originalFetch = window.fetch.bind(window);
              window.fetch = (input, init) => {
                const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                if (url.pathname !== '/api/delay') return originalFetch(input, init);
                const ms = Math.min(3000, Math.max(0, Number(url.searchParams.get('ms')) || 0));
                return new Promise(resolve => setTimeout(() => resolve(new Response('ok')), ms));
              };
            })();"""
        )
        page.goto(f"{base}/{fid}.html")
        pol = policy if isinstance(policy, DiscoveryPolicy) else (DiscoveryPolicy() if policy else None)
        res = run_form(page, SOURCE, policy=pol, **kw)
        state = page.evaluate("() => window.__state || {}")
        return res, state, page

    return _run


@pytest.fixture
def request_target():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/form":
                body = b"""<!doctype html><form id="f" action="/collect" method="post">
                  <label for="org">Legal company name</label><input id="org">
                  <button type="button" id="next">Next</button></form>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            received.append(("GET", self.path))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append(("POST", self.path))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_OPTIONS(self):
            received.append(("OPTIONS", self.path))
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def answered(res):
    return {i.plan.question.replace(" *", ""): i for i in res.items if i.plan.status == "ANSWER"}


@pytest.mark.parametrize("fid", ["wiz_hidden", "wiz_unmount", "wiz_async", "wiz_route", "wiz_guard", "wiz_labels"])
def test_wizard_all_steps_filled_and_committed(run, fid):
    res, state, page = run(fid)
    assert res.navigation["steps_visited"] == 3
    assert {k: state[k] for k in GT[fid]["expected"]} == GT[fid]["expected"]
    assert all(i.ever_verified for i in answered(res).values())
    # an answer on an earlier step is no longer on the page, so it cannot be read back now (None, with nothing observed); an
    # answer that IS on the page must read back as verified. A failed read-back (False) is never acceptable.
    assert all(i.verified is True or (i.verified is None and i.observed is None) for i in answered(res).values())
    assert page.evaluate("() => window.__submitted") == 0


def test_default_mode_stays_on_first_step(run):
    res, state, _ = run("wiz_unmount", policy=False)
    assert set(state) == {"name", "website"} and res.navigation == {}


def test_conditional_async_control_found_after_answer(run):
    _, state, _ = run("cond_async")
    assert state["detail"] == "Leeds"


def test_disabled_control_filled_once_enabled(run):
    _, state, _ = run("enable_after")
    assert state["phone"] == "+44 20 7946 0000"


def test_controlled_inputs_commit_to_app_state(run):
    _, state, _ = run("controlled", policy=False)
    assert state["name"] == "Acme Robotics Ltd"


def test_comboboxes_pick_options_not_just_type(run):
    _, state, _ = run("combobox")
    assert state["country"] == "United Kingdom" and state["industry"] == "Manufacturing"


def test_open_shadow_and_iframe_found_closed_shadow_reported(run):
    res, state, _ = run("shadow_iframe")
    assert state["website"] and state["email"] and "phone" not in state
    assert any(n["kind"] == "opaque_custom_element" for n in res.navigation["notes"])


def test_submit_labelled_button_never_pressed(run):
    res, _, page = run("trap_submit")
    assert res.navigation["stop_reason"] == "no_safe_next_control"
    assert page.evaluate("() => window.__submitted") == 0


def test_dialog_dismissed_and_run_stops(run):
    res, _, _ = run("nav_dialog")
    assert res.navigation["stop_reason"] == "dialog_on_navigation" and res.navigation["dialogs_accepted"] == 0


def test_document_navigation_request_is_blocked_before_leaving_browser(run):
    res, _, _ = run("nav_reload")
    assert res.navigation["stop_reason"] == "outbound_request_blocked"
    assert res.navigation["blocked_requests"][-1]["navigation"] is True
    assert res.status == "NEEDS_REVIEW"


def test_reset_during_navigation_is_detected(run):
    res, _, _ = run("nav_reset")
    assert res.navigation["resets_detected"] == ["Company website"]
    assert answered(res)["Company website"].verified is False


def test_attestation_stays_review(run):
    _, state, _ = run("attest")
    assert "certify" not in state and state.get("signer", "") == ""


@pytest.mark.parametrize(("attack", "expected_stop"), [
    ("document.getElementById('f').requestSubmit()", "submit_event_observed"),
    ("HTMLFormElement.prototype.submit.call(document.getElementById('f'))", "outbound_request_blocked"),
    ("fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {})", "outbound_request_blocked"),
    ("const x=new XMLHttpRequest(); x.open('POST','/collect'); x.send('fictional')", "outbound_request_blocked"),
    ("location.assign('/collect?fictional=1')", "outbound_request_blocked"),
    ("new WebSocket('ws://' + location.host + '/collect')", "outbound_request_blocked"),
])
def test_network_from_safe_next_is_blocked_before_local_server(request_target, page, attack, expected_stop):
    base, received = request_target
    page.goto(f"{base}/form")
    page.evaluate("(code) => document.querySelector('#next').addEventListener('click', new Function(code))", attack)

    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)

    assert result.navigation["stop_reason"] == expected_stop
    assert result.status == "NEEDS_REVIEW"
    assert received == []
    assert result.navigation["network_guard_active"] is True
    if expected_stop == "submit_event_observed":
        assert page.evaluate("() => window.__ffSubmits") == 1
        assert result.navigation["blocked_requests"] == []
    else:
        assert result.navigation["blocked_requests"]


def test_delayed_next_request_remains_blocked_after_run_returns(request_target, page):
    base, received = request_target
    page.goto(f"{base}/form")
    page.evaluate(
        "() => document.querySelector('#next').addEventListener('click', "
        "() => setTimeout(() => fetch('/collect', {method:'POST', body:'fictional'}).catch(() => {}), 400))"
    )

    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    assert result.status == "NEEDS_REVIEW"
    page.wait_for_timeout(600)

    assert received == []
    assert result.navigation["blocked_requests"]
    assert result.navigation["blocked_requests"][-1]["method"] == "POST"


def test_remounted_wizard_answer_is_rechecked_and_reset_detected(page):
    page.set_content(
        "<div id='app'></div><script>"
        "const app=document.getElementById('app');"
        "function showFirst(){app.innerHTML='<label for=\"org\">Legal company name</label>'"
        "+'<input id=\"org\"><button type=\"button\" id=\"next\">Next</button>'; "
        "document.getElementById('next').onclick=()=>{app.innerHTML="
        "'<label for=\"org\">Legal company name</label><input id=\"org\">';};}"
        "showFirst();</script>"
    )
    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    item = answered(result)["Legal company name"]
    assert item.ever_verified is True
    assert item.verified is False and item.observed == ""
    assert "no longer in the DOM" not in item.detail
    assert result.navigation["resets_detected"] == ["Legal company name"]
    assert result.status == "FAILED"


@pytest.mark.parametrize("text,ok", [("Next", True), ("Continue", True), ("Save and continue", True), ("Submit application", False),
                                      ("Continue and submit", False), ("Finish", False), ("Back", False), ("", False)])
def test_safe_next_labels(text, ok):
    assert DiscoveryPolicy().is_safe_next(text) is ok


# ---- review round 2: submit-type controls are refused on their HTML metadata, before any click ---------------------------


@pytest.mark.parametrize("fid", ["trap_submit_button", "trap_submit_input", "trap_submit_default", "trap_submit_image"])
def test_submit_type_next_is_never_clicked(run, fid):
    """A really-submitting form whose 'Next'/'Continue' control is a submit control. The text passes the allow list; the HTML type must not."""
    res, state, page = run(fid)
    assert res.navigation["stop_reason"] == "submit_type_next_refused"
    assert page.evaluate("() => window.__submitted") == 0  # the app's own submission side effect never ran
    assert page.evaluate("() => window.__ffSubmits") == 0  # no submit event of any kind
    assert page.locator("#thanks").count() == 0
    assert page.locator("#step1").is_visible() and res.navigation["steps_visited"] == 1  # still on step 1: nothing was pressed
    note = next(n for n in res.navigation["notes"] if n["kind"] == "submit_type_next_refused")
    assert "submit" in note["button"] and any(b["submit_type"] for b in note["buttons_seen"])
    assert set(state) == {"name", "website"}  # step 1 was filled, nothing beyond
    assert res.status == "NEEDS_REVIEW" and any("stopped early" in w for w in res.warnings)


def test_intercepted_submit_button_is_refused_even_with_the_deprecated_opt_in(run):
    """An SPA that intercepts the submit cannot be told from one that does not before the click, so it is always refused."""
    for policy in (None, DiscoveryPolicy(allow_submit_type_navigation=True)):
        res, _, page = run("spa_submit_type_intercepted", policy) if policy else run("spa_submit_type_intercepted")
        assert res.navigation["stop_reason"] == "submit_type_next_refused" and res.navigation["steps_visited"] == 1
        assert page.evaluate("() => window.__submitted") == 0


def test_opt_in_does_not_unlock_commit_labels(run):
    res, _, page = run("trap_submit", DiscoveryPolicy(allow_submit_type_navigation=True))  # button says "Submit application"
    assert res.navigation["stop_reason"] == "no_safe_next_control" and page.evaluate("() => window.__submitted") == 0


def test_submit_flag_is_not_honoured_after_a_refused_next(run):
    res, _, page = run("trap_submit_button", submit=True)
    assert res.submission["outcome"] == "SKIPPED" and page.evaluate("() => window.__submitted") == 0


@pytest.mark.parametrize("html,expect", [
    ('<form><button type="button">Next</button></form>', "found"),
    ("<button>Next</button>", "found"),  # outside a form a type-less button submits nothing
    ('<div role="button" tabindex="0">Continue</div>', "found"),
    ('<a role="button" href="#">Next</a>', "found"),
    ("<form><button>Next</button></form>", "refused"),  # type-less button in a form IS a submit button
    ('<form><button type="submit">Next</button></form>', "refused"),
    ('<form><input type="submit" value="Continue"></form>', "refused"),
    ('<form><input type="image" alt="Next"></form>', "refused"),  # image submit button: label comes from alt
    ('<form><input type="image" alt="Continue" value="Continue"></form>', "refused"),
    ('<input type="image" alt="Next">', "found"),  # outside a form an image input submits nothing
    ('<form><input type="image" alt="Submit application"></form>', "none"),  # commit label: never a Next
    ('<form id="f"></form><button type="submit" form="f">Next</button>', "refused"),  # ownership via the form= attribute
    ('<a role="button" href="/elsewhere">Next</a>', "refused"),  # leaves the page
    ("<form><button type=\"button\">Submit application</button></form>", "none"),
])
def test_next_button_html_metadata(page, html, expect):
    from formfill.web.steps import next_button

    page.set_content(html)
    assert next_button(page, DiscoveryPolicy())["state"] == expect


def test_opt_in_policy_no_longer_finds_submit_type(page):
    from formfill.web.steps import next_button

    page.set_content('<form><button type="submit">Next</button></form>')
    assert next_button(page, DiscoveryPolicy(allow_submit_type_navigation=True))["state"] == "refused"
    page.set_content('<div><button type="button">Next</button></div>')  # a plain navigation button is still pressed
    assert next_button(page, DiscoveryPolicy(allow_submit_type_navigation=True))["state"] == "found"
    page.set_content('<a role="button" href="/elsewhere">Next</a>')
    assert next_button(page, DiscoveryPolicy(allow_submit_type_navigation=True))["state"] == "refused"  # off-page links stay refused


# ---- review round 2: an unsettled page is never filled or clicked -------------------------------------------------------


@pytest.mark.parametrize("fid", ["wiz_loading_forever", "wiz_churn"])
def test_unsettled_page_is_not_touched(run, fid):
    res, state, page = run(fid, DiscoveryPolicy(settle_timeout_ms=600), submit=True)
    assert res.navigation["stop_reason"] == "page_not_settled"
    assert res.items == [] and state == {}  # nothing discovered, filled, or clicked
    assert res.status == "NEEDS_REVIEW" and res.submission["outcome"] == "SKIPPED"
    assert page.evaluate("() => window.__submitted") == 0
    note = next(n for n in res.navigation["notes"] if n["kind"] == "page_not_settled")
    assert note["where"] == "step start" and note["waited_ms"] >= 600


def test_page_that_goes_unstable_after_next_stops_before_step_two(run):
    res, state, _ = run("wiz_churn_step2", DiscoveryPolicy(settle_timeout_ms=600))
    assert res.navigation["stop_reason"] == "page_not_settled"
    assert set(state) == {"name", "website"}  # step 2 was reached on screen but never read or filled
    assert next(n for n in res.navigation["notes"] if n["kind"] == "page_not_settled")["where"] == "after Next"


def test_a_slow_but_settling_page_is_still_navigated(run):
    res, state, _ = run("wiz_async", DiscoveryPolicy(settle_timeout_ms=4000))
    assert res.navigation["steps_visited"] == 3 and state["city"] == "Leeds"


def test_timeout_is_a_policy_knob(run):
    res, state, _ = run("wiz_async", DiscoveryPolicy(settle_timeout_ms=100, settle_quiet_ms=50))  # 400 ms async render, 100 ms patience
    assert res.navigation["stop_reason"] == "page_not_settled" and state == {}


def test_complete_walk_is_unconfirmed_not_filled(run):
    """The walk reaches step 3, but the page cannot say that step 3 is the last: completion stays unconfirmed."""
    res, _, _ = run("wiz_unmount")
    items = answered(res)
    assert res.navigation["steps_visited"] == 3 and all(i.ever_verified for i in items.values())
    assert items["Legal company name"].verified is None
    assert items["Legal company name"].observed is None
    assert items["Headquarters country"].verified is True
    assert res.navigation["stop_reason"] == "no_safe_next_control" and res.navigation["completion"] == "unconfirmed"
    assert res.status == "NEEDS_REVIEW" and any("could not confirm" in w for w in res.warnings)
    assert any(n["kind"] == "completion_unconfirmed" for n in res.navigation["notes"])


# ---- review round 3: uncertain completion is never submitted --------------------------------------------------------------


def _nothing_submitted(page):
    assert page.evaluate("() => window.__submitted") == 0  # the app's own side effect
    assert page.evaluate("() => window.__ffSubmits") == 0  # no submit event at all
    assert page.locator("#thanks").count() == 0


def test_trap_submit_with_submit_true_is_skipped(run):
    res, _, page = run("trap_submit", submit=True)  # only button says "Submit application"; a mid-wizard trap
    assert res.navigation["stop_reason"] == "no_safe_next_control" and res.navigation["completion"] == "unconfirmed"
    assert res.submission["outcome"] == "SKIPPED" and "unconfirmed" in res.submission["detail"]
    assert res.status == "NEEDS_REVIEW"
    _nothing_submitted(page)


def test_unfamiliar_next_label_with_submit_true_is_skipped(run):
    """Step 1 of 3 has a Next we do not recognise ('Onward') and a REAL visible Submit button. Before this rule the
    submit routine would have found and pressed it."""
    res, state, page = run("wiz_unfamiliar_next", submit=True)
    assert res.navigation["stop_reason"] == "no_safe_next_control" and res.navigation["steps_visited"] == 1
    assert res.submission["outcome"] == "SKIPPED" and res.status == "NEEDS_REVIEW"
    assert set(state) == {"name", "website"}
    assert page.locator("#submit").is_visible()  # the dangerous button was there the whole time
    _nothing_submitted(page)


def test_genuine_final_step_with_submit_true_is_not_submitted(run):
    """A walk that really did reach the last step looks identical to the cases above, so it is treated the same way:
    filled and verified, reported as unconfirmed, NOT submitted. Submitting needs a later, explicit final-step policy."""
    res, state, page = run("wiz_unmount", submit=True)
    assert res.navigation["steps_visited"] == 3 and state["city"] == "Leeds"
    assert res.navigation["completion"] == "unconfirmed" and res.submission["outcome"] == "SKIPPED"
    assert res.status == "NEEDS_REVIEW"
    assert page.locator("#submit").is_visible()  # the real final Submit button is on screen, untouched
    _nothing_submitted(page)


@pytest.mark.parametrize("fid", ["trap_submit_button", "trap_submit_input", "trap_submit_default", "trap_submit_image", "spa_submit_type_intercepted"])
def test_refused_submit_type_with_submit_true_is_skipped(run, fid):
    res, _, page = run(fid, submit=True)
    assert res.navigation["stop_reason"] == "submit_type_next_refused" and res.navigation["completion"] == "incomplete"
    assert res.submission["outcome"] == "SKIPPED"
    _nothing_submitted(page)


def test_without_a_policy_submit_true_still_works_as_before(page, base):
    """The single-page path is unchanged: no policy, no walk, so no completion question."""
    page.goto(f"{base}/wiz_unfamiliar_next.html")
    res = run_form(page, SOURCE, submit=True)
    assert res.navigation == {}


# ---- review round 2: stage-aware discovery -----------------------------------------------------------------------------


def test_first_seen_stage_is_recorded(run):
    res, _, _ = run("wiz_unmount")
    seen = {v["label"]: (v["step"], v["round"]) for v in res.navigation["first_seen"].values()}
    assert seen["Legal company name"] == (1, 1) and seen["Contact email"] == (2, 1) and seen["Headquarters city"] == (3, 1)


def test_conditional_control_is_first_seen_after_its_trigger(run):
    res, _, _ = run("cond_async")
    seen = {v["label"]: (v["step"], v["round"]) for v in res.navigation["first_seen"].values()}
    assert seen["Headquarters city"] == (1, 2)


def test_hidden_later_steps_are_not_seen_early(run):
    res, _, _ = run("wiz_hidden")  # all three steps are in the DOM from the start, two of them hidden
    seen = {v["label"]: v["step"] for v in res.navigation["first_seen"].values()}
    assert seen["Contact phone number"] == 2 and seen["Headquarters country"] == 3


def test_stage_classifier():
    sys.path.insert(0, str(BENCH.parents[1] / "tools"))
    from evaluate_spa import classify_stage

    assert classify_stage({"step": 2}, {"step": 2, "round": 1}) == "on_time"
    assert classify_stage({"step": 2}, {"step": 1, "round": 1}) == "early"
    assert classify_stage({"step": 2}, {"step": 3, "round": 1}) == "late"
    assert classify_stage({"step": 2}, {"step": 2, "round": 2}) == "late"  # needed other answers first, ground truth says it was there on arrival
    assert classify_stage({"step": 1, "after": "sector"}, {"step": 1, "round": 1}) == "early"
    assert classify_stage({"step": 1, "after": "sector"}, {"step": 1, "round": 2}) == "on_time"
    assert classify_stage({"step": 1}, None) == "missing"


def test_evaluator_flags_wrong_stage_expectations(browser, base):
    """The evaluator must be able to fail: give it ground truth that is deliberately one step off."""
    sys.path.insert(0, str(BENCH.parents[1] / "tools"))
    from evaluate_spa import run_one

    gt = json.loads(json.dumps(GT["wiz_unmount"]))
    gt["stages"] = [{"step": 1, "discoverable": ["name", "website", "email"]}, {"step": 2, "discoverable": ["phone"]},
                    {"step": 3, "discoverable": ["city"]}, {"step": 1, "discoverable": ["country"]}]  # email expected a step too early (found at 2), country expected at step 1 (found at 3)
    row = run_one(browser, base, "wiz_unmount", gt, SOURCE, True)
    verdicts = {k: v["verdict"] for k, v in row["stage_report"].items()}
    assert verdicts["email"] == "late" and verdicts["name"] == "on_time"
    assert verdicts["country"] == "late" and verdicts["phone"] == "on_time"
    gt["stages"] = [{"step": 1, "discoverable": ["name", "website"]}]  # nothing else is expected at all
    row = run_one(browser, base, "wiz_unmount", gt, SOURCE, True)
    assert row["stage_counts"]["unexpected"] == 4


# ---- regression: read-back must not race a reloaded document (confirmed bug) ---------------------------------------
# Found by repeating nav_reload: its outcome flipped between FAILED and NEEDS_REVIEW (15/25 vs 10/25 locally) because the
# final discover/read-back sometimes ran while the reloaded app had not re-mounted, so "not found" kept the old verdict.

_RELOAD_SLOW = """<!doctype html><html><body><div id="app"></div><script>
  const reloaded = sessionStorage.getItem('reloaded') === '1';
  function mount() {
    document.getElementById('app').innerHTML =
      '<label for="co">Legal company name</label><input id="co" name="co" type="text">' +
      '<button type="button" id="nx">Next</button>';
    document.getElementById('nx').addEventListener('click', () => {
      sessionStorage.setItem('reloaded', '1');
      setTimeout(() => location.reload(), 30);
    });
  }
  if (reloaded) setTimeout(mount, 400); else mount();   // the booting app re-mounts well after the load event
</script></body></html>"""


def _serve_reload_slow(page):
    # Answered locally by a page-level route (no network is involved). A guarded walk would abort the page's own reload request
    # (see test_document_navigation_request_is_blocked_before_leaving_browser), so this is how the regression (read-back racing
    # a reloaded document) is still reproduced; it is a test of read-back, not of the guard.
    page.route("http://reload.test/slow.html", lambda r: r.fulfill(status=200, content_type="text/html", body=_RELOAD_SLOW))
    page.goto("http://reload.test/slow.html")


def test_loss_after_reload_is_failed_even_when_the_app_remounts_late(page):
    _serve_reload_slow(page)
    res = run_form(page, SOURCE, policy=DiscoveryPolicy())
    item = answered(res)["Legal company name"]
    assert res.navigation["stop_reason"] == "document_navigation"
    assert item.verified is False and item.observed == ""  # the reload wiped the value and that was actually observed
    assert res.status == "FAILED"
