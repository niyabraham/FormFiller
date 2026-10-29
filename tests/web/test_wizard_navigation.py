"""Requirement A: multi-step questionnaires end to end, against local fixtures only (benchmarks/wizards; 127.0.0.1).

Three kinds of wizard: a client-side one (four sections, conditional field, required validation, Back), a single-page app that
loads its sections from its server and can autosave, and a server-rendered wizard that moves between steps with real form
POSTs. Each scenario checks what the page shows, what the app/server actually received, and that the final "Submit
questionnaire" control was never pressed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from formfill.web.navigation import Outcome, StepSnapshot, classify
from formfill.web.netpolicy import AllowRule, NetworkPolicy
from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.result import FieldState
from formfill.web.steps import DiscoveryPolicy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.wizards.server import serve  # noqa: E402

pytestmark = pytest.mark.browser

CLIENT_SOURCE = {
    "company": {"legal_name": "Fictional Vendor LLC", "website": "https://vendor.example", "employees": 120,
                "headquarters_city": "Leeds"},
    "security": {"incident_response_plan": True, "incident_response_exercise_date": "2026-03-14", "encryption_at_rest": "AES-256",
                 "contact": {"email": "security@vendor.example", "phone": "+44 20 7946 0000"}},
}


@pytest.fixture(scope="module")
def site():
    with serve() as (base, rec):
        yield base, rec


@pytest.fixture
def server(site):
    base, rec = site
    rec.requests.clear()
    rec.autosaves.clear()
    rec.final_submissions = 0
    rec.sessions.clear()
    return base, rec


def walk(page, url, source=CLIENT_SOURCE, policy=None, **kw):
    release_wizard_network_guard(page)
    page.goto(url)
    return run_form(page, source, policy=policy or DiscoveryPolicy(), confirm_ms=0, **kw)


def states(result):
    return {i.plan.question: i.state.value for i in result.items}


# ---- client-side wizard ---------------------------------------------------------------------------------------------------------


def test_a_four_section_client_wizard_is_walked_end_to_end_and_stops_at_the_declaration(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html")
    nav = result.navigation
    assert nav["steps_visited"] == 4
    assert [s["transition"] for s in nav["steps"]] == ["advanced", "advanced", "advanced", None]
    assert [s["heading"] for s in nav["steps"]] == ["1. Company", "2. Security practices", "3. Contacts", "4. Declaration"]
    st = states(result)
    for q in ("Legal company name", "Company website", "Number of employees", "Do you have a documented incident response plan?",
              "Date of the last incident response exercise", "Encryption at rest", "Security contact email", "Security contact phone"):
        assert st[q] == "verified", (q, st)
    # the date question only exists once "Yes" was chosen: it was found on step 2 after the radio answer (conditional field)
    seen = {v["label"]: (v["step"], v["round"]) for v in nav["first_seen"].values()}
    assert seen["Date of the last incident response exercise *"][0] == 2 and seen["Date of the last incident response exercise *"][1] >= 2
    # the declaration is an attestation: REVIEW, required, so the walk stops there for a person; nothing is submitted
    assert st["I certify that the information provided in this questionnaire is accurate"] == "needs_review"
    assert nav["stop_reason"] == "required_unresolved" and nav["completion"] == "incomplete"
    assert page.evaluate("() => window.__submitted") == 0 and page.is_checked("#f_certify") is False
    app = page.evaluate("() => window.__state")
    assert app["legal_name"] == "Fictional Vendor LLC" and app["ir_plan"] == "Yes" and app["ir_test_date"] == "2026-03-14"
    assert result.status == "NEEDS_REVIEW"
    assert result.summary()["required_unanswered"][0]["question"].startswith("I certify")


def test_submit_true_never_presses_the_final_submit_of_a_wizard(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html", submit=True)
    assert result.submission["outcome"] == "SKIPPED" and result.submission["attempted"] is False
    assert page.evaluate("() => window.__submitted") == 0


def test_back_pass_re_verifies_every_earlier_answer_and_returns_to_the_last_step(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html", policy=DiscoveryPolicy(revisit_with_back=True))
    rv = result.navigation["revisit"]
    assert rv["returned_to_last_step"] is True and rv["stopped"] is None and rv["mismatched"] == []
    assert rv["steps_checked"] == [3, 2, 1, 2, 3, 4]
    assert "Legal company name" in rv["reverified"] and "Security contact email" in rv["reverified"]
    moves = page.evaluate("() => window.__moves")
    assert moves[-6:] == ["back 4", "back 3", "back 2", "next 1", "next 2", "next 3"]
    item = next(i for i in result.items if i.plan.question == "Legal company name")
    assert item.revisit_verified is True and item.state is FieldState.VERIFIED
    assert result.navigation["stop_reason"] == "required_unresolved"  # the human gate is still the last word
    assert page.evaluate("() => window.__submitted") == 0


def test_an_answer_lost_while_moving_back_is_detected(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html?variant=lose", policy=DiscoveryPolicy(revisit_with_back=True))
    rv = result.navigation["revisit"]
    assert "Company website" in rv["mismatched"]
    assert "Company website" in result.navigation["resets_detected"]
    item = next(i for i in result.items if i.plan.question == "Company website")
    assert item.revisit_verified is False and item.state is FieldState.REJECTED
    assert result.status == "FAILED"


def test_a_next_that_leads_back_to_an_earlier_step_is_a_detected_loop(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html?variant=loop")
    nav = result.navigation
    assert nav["stop_reason"] == "navigation_loop" and nav["steps"][-1]["transition"] == Outcome.LOOP.value
    assert next(n for n in nav["notes"] if n["kind"] == "navigation_loop")["back_to_step"] == 1


def test_a_next_that_changes_nothing_is_detected(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html?variant=stuck")
    assert result.navigation["stop_reason"] == "no_change_after_next" and result.navigation["steps_visited"] == 2


def test_a_required_question_without_an_answer_stops_the_walk_before_next(page, server):
    base, _ = server
    source = {"company": CLIENT_SOURCE["company"], "security": {**CLIENT_SOURCE["security"], "contact": {"phone": "+44 20 7946 0000"}}}
    result = walk(page, f"{base}/client_wizard.html", source=source)
    nav = result.navigation
    assert nav["stop_reason"] == "required_unresolved" and nav["steps_visited"] == 3
    note = next(n for n in nav["notes"] if n["kind"] == "required_unresolved")
    assert note["questions"] == ["Security contact email"]
    assert "next 3" not in page.evaluate("() => window.__moves")  # Next was not pressed on step 3


def test_a_refused_next_with_validation_messages_is_detected(page, server):
    base, _ = server
    source = {"company": CLIENT_SOURCE["company"], "security": {**CLIENT_SOURCE["security"], "contact": {"phone": "+44 20 7946 0000"}}}
    result = walk(page, f"{base}/client_wizard.html", source=source, policy=DiscoveryPolicy(advance_with_unresolved_required=True))
    nav = result.navigation
    assert nav["stop_reason"] == "validation_error_after_next"
    errors = next(n for n in nav["notes"] if n["kind"] == "validation_error_after_next")["errors"]
    assert any("Security contact email" in e for e in errors)


def test_every_step_and_state_transition_is_recorded(page, server):
    base, _ = server
    result = walk(page, f"{base}/client_wizard.html")
    seq = [h["state"] for h in result.navigation["state_history"]]
    for expected in ("preflight", "guarding", "settling", "filling", "verifying", "gating", "advancing", "confirming",
                     "reverifying", "stopped"):
        assert expected in seq
    assert result.navigation["state"] == "stopped"
    assert all(len(s["fingerprint"]) == 16 for s in result.navigation["steps"])


# ---- server-backed single-page app ------------------------------------------------------------------------------------------


def spa_rules(base, *, autosave=False):
    rules = [AllowRule(origin=base, path="/api/section/*", methods=frozenset({"GET"}), resource_types=frozenset({"fetch"}),
                       note="load the next section")]
    if autosave:
        rules.append(AllowRule(origin=base, path="/api/answers", methods=frozenset({"POST"}), resource_types=frozenset({"fetch"}),
                               answer_data=True, note="autosave of the section's answers (the portal stores drafts)"))
    return NetworkPolicy(rules=tuple(rules))


def test_by_default_a_server_backed_wizard_stops_at_its_first_request(page, server):
    base, rec = server
    result = walk(page, f"{base}/server_spa.html")
    assert result.navigation["stop_reason"] == "outbound_request_blocked"
    assert rec.paths("GET").count("/api/section/2") == 0  # never reached the server
    assert result.navigation["blocked_requests"][0]["url"].endswith("/api/section/2")


def test_an_explicit_rule_lets_the_wizard_load_its_sections_and_nothing_else(page, server):
    base, rec = server
    result = walk(page, f"{base}/server_spa.html", network_policy=spa_rules(base))
    nav = result.navigation
    assert nav["network_mode"] == "allow_listed"
    assert nav["steps_visited"] == 3 and nav["stop_reason"] == "no_safe_next_control"  # the last section only has Submit
    assert [r["url"].rsplit("/", 1)[1] for r in nav["permitted_requests"]] == ["2", "3"]
    assert all(r["carries_answers"] is False and r["status"] == 200 for r in nav["permitted_requests"])
    assert "POST" not in [m for m, _, _ in rec.requests]  # no answers left the browser
    assert rec.final_submissions == 0 and page.evaluate("() => window.__submitted") == 0
    assert all(i.state is FieldState.VERIFIED or i.state is FieldState.NEEDS_REVIEW for i in result.items)
    assert page.evaluate("() => navigator.onLine") is False  # the browser itself stayed offline: requests were relayed


def test_an_autosave_is_blocked_unless_a_rule_allows_answer_data(page, server):
    base, rec = server
    result = walk(page, f"{base}/server_spa.html?autosave=1", network_policy=spa_rules(base))
    nav = result.navigation
    assert nav["stop_reason"] == "outbound_request_blocked"
    blocked = nav["blocked_requests"][0]
    assert blocked["url"].endswith("/api/answers") and blocked["method"] == "POST"
    assert "answer" in blocked["reason"] or "changes server state" in blocked["reason"]
    assert rec.autosaves == [] and "/api/answers" not in rec.paths()


def test_an_explicitly_allowed_autosave_is_relayed_and_recorded_as_carrying_answers(page, server):
    base, rec = server
    result = walk(page, f"{base}/server_spa.html?autosave=1", network_policy=spa_rules(base, autosave=True))
    nav = result.navigation
    assert nav["steps_visited"] == 3 and nav["stop_reason"] == "no_safe_next_control"
    saves = [r for r in nav["permitted_requests"] if r["url"].endswith("/api/answers")]
    assert len(saves) == 2 and all(r["carries_answers"] for r in saves)
    assert rec.autosaves[0]["answers"]["org_name"] == "Fictional Vendor LLC"
    assert rec.final_submissions == 0


# ---- server-rendered wizard with form POSTs -------------------------------------------------------------------------------------


def classic_rules(base, path="/classic/step/*"):
    return NetworkPolicy(rules=(
        AllowRule(origin=base, path=path, methods=frozenset({"POST", "GET"}), resource_types=frozenset({"document"}),
                  answer_data=True, form_navigation=True, note="step-to-step form POST of the registration wizard"),
    ))


def test_a_form_post_wizard_is_refused_without_an_explicit_rule(page, server):
    base, rec = server
    result = walk(page, f"{base}/classic/start")
    assert result.navigation["stop_reason"] == "submit_type_next_refused"
    assert rec.paths("POST") == []


@pytest.mark.parametrize("query", ["", "?prg=1"])
def test_a_form_post_wizard_is_walked_with_a_form_navigation_rule_and_never_submitted(page, server, query):
    base, rec = server
    result = walk(page, f"{base}/classic/start{query}", network_policy=classic_rules(base))
    nav = result.navigation
    assert nav["steps_visited"] == 3, nav["notes"]
    assert nav["stop_reason"] == "no_safe_next_control"  # step 3 only offers "Submit questionnaire", which is denied
    assert rec.final_submissions == 0 and "/classic/submit" not in rec.paths()
    assert rec.paths("POST") == ["/classic/step/1", "/classic/step/2"]
    posts = [r for r in nav["permitted_requests"] if r["method"] == "POST"]
    assert len(posts) == 2 and all(r["carries_answers"] and r["navigation"] for r in posts)
    if query:
        assert all(r["redirect_hops"] for r in posts)  # post/redirect/get: the relay followed each hop after checking it
    assert [n["kind"] for n in nav["notes"]].count("form_navigation") == 2
    assert page.input_value("#hq_city") == "Leeds"


def test_a_rule_that_covers_only_the_first_step_stops_the_walk_at_the_second(page, server):
    base, rec = server
    result = walk(page, f"{base}/classic/start", network_policy=classic_rules(base, path="/classic/step/1"))
    assert result.navigation["stop_reason"] == "submit_type_next_refused" and result.navigation["steps_visited"] == 2
    assert rec.paths("POST") == ["/classic/step/1"]


# ---- the transition table, without a browser --------------------------------------------------------------------------------------


def snap(url="http://127.0.0.1:1/w#1", heading="Step 1", sigs=(("Name", "", "", "", "text"),), errors=()):
    return StepSnapshot(url=url, indicator="", headings=(heading,), signatures=tuple(sigs), control_ids=frozenset({"x"}), errors=errors)


def test_transition_classification_table():
    a, b = snap(), snap(url="http://127.0.0.1:1/w#2", heading="Step 2", sigs=(("Email", "", "", "", "email"),))
    assert classify(a, b, {a.fingerprint: 1}, 1, "http://127.0.0.1:1") is Outcome.ADVANCED
    assert classify(a, snap(), {a.fingerprint: 1}, 1, "http://127.0.0.1:1") is Outcome.NO_CHANGE
    assert classify(a, snap(errors=("Please complete: Name",)), {a.fingerprint: 1}, 1, "http://127.0.0.1:1") is Outcome.VALIDATION_ERROR
    assert classify(b, a, {a.fingerprint: 1, b.fingerprint: 2}, 2, "http://127.0.0.1:1") is Outcome.LOOP
    assert classify(a, snap(url="http://localhost:9/x"), {a.fingerprint: 1}, 1, "http://127.0.0.1:1") is Outcome.REDIRECTED
