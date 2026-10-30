"""Requirement F: the review workflow (decisions, re-validation, application to a new run) and the local review page."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

import pytest

from formfill.web.models import AnswerPlanItem
from formfill.web.pipeline import run_form
from formfill.web.result import ItemResult, RunResult
from formfill.web.review import (
    NOT_A_SIGNATURE,
    ReviewError,
    build_review,
    decide,
    decisions_planner,
    load_review,
    save_review,
)
from formfill.web.review_server import ReviewServer

FORM = """<!doctype html><html><body><form id="f" onsubmit="window.__submitted=true;event.preventDefault()">
<label for="org">Legal company name</label><input id="org" name="org">
<label for="emp">Number of employees</label><input id="emp" name="emp" type="number" min="1" max="100000">
<fieldset><legend>Do you maintain a documented incident response process?</legend>
  <label><input type="radio" name="ir" value="yes"> Yes</label><label><input type="radio" name="ir" value="no"> No</label></fieldset>
<label><input type="checkbox" id="cert" name="cert"> I certify that the information provided is accurate</label>
<button type="submit">Submit</button></form><script>window.__submitted=false</script></body></html>"""
SOURCE = {"company": {"legal_name": "Fictional Vendor LLC"}, "security": {"incident_response_plan": True}}


def first_run(page):
    page.set_content(FORM)
    return run_form(page, SOURCE, confirm_ms=0)


def by_question(doc, text):
    return next(i for i in doc["items"] if i["question"].startswith(text))


# ---- decisions -------------------------------------------------------------------------------------------------------------------


@pytest.mark.browser
def test_a_review_shows_evidence_reason_state_and_a_pending_decision_for_every_question(page):
    doc = build_review(first_run(page))
    assert doc["notice"] == NOT_A_SIGNATURE and "not a signature" in doc["notice"]
    org = by_question(doc, "Legal company name")
    assert org["status"] == "ANSWER" and org["source"] == "company.legal_name" and org["state"] == "verified" and org["filled"]
    ir = by_question(doc, "Do you maintain")
    assert ir["status"] == "REVIEW" and ir["proposed"] == "yes" and ir["method"] == "semantic" and not ir["filled"]
    emp = by_question(doc, "Number of employees")
    assert emp["status"] == "REVIEW" and emp["proposed"] is None and "no matching value" in emp["reason"]
    cert = by_question(doc, "I certify")
    assert cert["attestation"] is True
    assert all(i["decision"]["action"] == "pending" for i in doc["items"])


@pytest.mark.browser
def test_decisions_are_validated_against_the_field_and_attestations_can_only_be_acknowledged(page, tmp_path):
    doc = build_review(first_run(page))
    emp = by_question(doc, "Number of employees")["question_id"]
    with pytest.raises(ReviewError, match="not a valid answer"):
        decide(doc, emp, "edit", "about two hundred")
    with pytest.raises(ReviewError, match="not a valid answer"):
        decide(doc, emp, "edit", 250000)  # above the field's max
    edited = decide(doc, emp, "edit", "120")
    assert edited["decision"]["action"] == "edit" and edited["decision"]["value"] == 120 and edited["decision"]["validation"] == "ok"
    cert = by_question(doc, "I certify")["question_id"]
    with pytest.raises(ReviewError, match="never answered by FormFiller"):
        decide(doc, cert, "approve")
    decide(doc, cert, "acknowledge")
    with pytest.raises(ReviewError, match="no proposed answer"):
        decide(doc, by_question(doc, "Number of employees")["question_id"], "approve")
    path = save_review(doc, tmp_path / "review.json")
    saved = {i["question"]: i["decision"]["action"] for i in load_review(path)["items"]}
    assert saved["Number of employees"] == "edit" and saved[by_question(doc, "I certify")["question"]] == "acknowledge"


@pytest.mark.browser
def test_approved_and_edited_answers_are_filled_and_verified_on_the_next_run_and_the_attestation_never(page):
    doc = build_review(first_run(page))
    decide(doc, by_question(doc, "Do you maintain")["question_id"], "approve")
    decide(doc, by_question(doc, "Number of employees")["question_id"], "edit", "120", note="from the HR system")
    decide(doc, by_question(doc, "I certify")["question_id"], "acknowledge")
    page.set_content(FORM)
    second = run_form(page, SOURCE, confirm_ms=0, planner=decisions_planner(doc))
    items = {i.plan.question: i for i in second.items}
    ir = items["Do you maintain a documented incident response process?"]
    assert ir.plan.method == "human_approved" and ir.state.value == "verified" and page.is_checked("input[value=yes]")
    emp = items["Number of employees"]
    assert emp.plan.method == "human_edited" and emp.plan.source == "reviewer" and emp.state.value == "verified"
    assert page.input_value("#emp") == "120" and "from the HR system" in " ".join(emp.plan.evidence)
    cert = next(i for q, i in items.items() if q.startswith("I certify"))
    assert cert.plan.status == "REVIEW" and not page.is_checked("#cert")
    assert page.evaluate("() => window.__submitted") is False  # reviewing and filling are not submitting


@pytest.mark.browser
def test_an_approval_does_not_survive_a_change_of_the_proposal(page):
    doc = build_review(first_run(page))
    decide(doc, by_question(doc, "Do you maintain")["question_id"], "approve")
    page.set_content(FORM)
    changed = {**SOURCE, "security": {"incident_response_plan": False}}
    second = run_form(page, changed, confirm_ms=0, planner=decisions_planner(doc))
    ir = next(i for i in second.items if i.plan.question.startswith("Do you maintain"))
    assert ir.plan.status == "REVIEW" and "changed since it was approved" in ir.plan.reason and not page.is_checked("input[value=no]")


def test_a_broken_review_file_is_refused(tmp_path):
    bad = tmp_path / "review.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(ReviewError, match="corrupt"):
        load_review(bad)
    bad.write_text(json.dumps({"schema": "formfill.review", "schema_version": 9, "items": []}), encoding="utf-8")
    with pytest.raises(ReviewError, match="incompatible"):
        load_review(bad)


# ---- the local review page ----------------------------------------------------------------------------------------------------


def small_review(tmp_path):
    plan_a = AnswerPlanItem(question_id="a", question="Number of employees", field_type="number", required=True, status="REVIEW",
                            reason="no matching value in the source data")
    plan_b = AnswerPlanItem(question_id="b", question="I agree to the terms", field_type="checkbox", required=True, status="REVIEW",
                            reason="attestation/consent: a human must confirm it, never auto-filled")
    result = RunResult(url="http://127.0.0.1/form", status="NEEDS_REVIEW", items=[ItemResult(plan=plan_a), ItemResult(plan=plan_b)],
                       controls=[{"control_id": "a", "kind": "number", "label": "Number of employees", "name": "emp", "html_id": "emp",
                                  "section": "", "min": "1", "max": "100000", "options": []},
                                 {"control_id": "b", "kind": "checkbox", "label": "I agree to the terms", "name": "t", "html_id": "t",
                                  "section": "", "options": []}])
    return save_review(build_review(result), tmp_path / "review.json")


def request(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_the_review_server_listens_on_loopback_only_and_requires_its_token(tmp_path):
    path = small_review(tmp_path)
    with pytest.raises(ValueError, match="127.0.0.1 only"):
        ReviewServer(path, host="0.0.0.0")
    srv = ReviewServer(path).start()
    try:
        base = f"http://127.0.0.1:{srv.port}"
        assert request(base + "/")[0] == 403
        assert request(base + "/?token=wrong")[0] == 403
        assert request(base + "/api/review")[0] == 403
        assert request(base + "/api/review", headers={"X-Review-Token": srv.token, "Host": "evil.example"})[0] == 403  # rebinding
        status, headers, body = request(srv.url)
        assert status == 200 and "nonce-" in headers["Content-Security-Policy"] and headers["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in headers
        status, _, body = request(base + "/api/review", headers={"X-Review-Token": srv.token})
        assert status == 200 and json.loads(body)["items"][0]["question"] == "Number of employees"
        bad = request(base + "/api/decision", "POST", {"X-Review-Token": srv.token, "Content-Type": "application/json"},
                      json.dumps({"question_id": "a", "action": "edit", "value": "lots"}).encode())
        assert bad[0] == 400 and "not a valid answer" in json.loads(bad[2])["error"]
        ok = request(base + "/api/decision", "POST", {"X-Review-Token": srv.token, "Content-Type": "application/json"},
                     json.dumps({"question_id": "a", "action": "edit", "value": "120"}).encode())
        assert ok[0] == 200 and load_review(path)["items"][0]["decision"]["value"] == 120
        att = request(base + "/api/decision", "POST", {"X-Review-Token": srv.token, "Content-Type": "application/json"},
                      json.dumps({"question_id": "b", "action": "approve"}).encode())
        assert att[0] == 400
    finally:
        srv.stop()


@pytest.mark.browser
def test_the_review_page_edits_validates_and_never_offers_to_submit(browser, tmp_path):
    path = small_review(tmp_path)
    srv = ReviewServer(path).start()
    context = browser.new_context()
    try:
        page = context.new_page()
        page.goto(srv.url)
        page.wait_for_selector(".item")
        assert "not a signature" in page.inner_text("#notice")
        assert page.get_by_role("button", name=re.compile("submit|send|sign", re.I)).count() == 0
        employees = page.locator('.item[data-qid="a"]')
        employees.locator("input.edit").fill("lots")
        employees.locator('button[data-action="edit"]').click()
        page.wait_for_selector(".err")
        assert "not a valid answer" in employees.locator(".msg").inner_text()
        employees.locator("input.edit").fill("120")
        employees.locator('button[data-action="edit"]').click()
        # Locator waits run in Playwright's isolated world: the page's CSP (no eval) blocks `wait_for_function` on Playwright 1.48.
        # A regex keeps the match case-sensitive, like the textContent.includes() check it replaces.
        page.locator('.item[data-qid="a"]').filter(has_text=re.compile(re.escape("edit (120)"))).wait_for()
        terms = page.locator('.item[data-qid="b"]')
        assert terms.locator('button[data-action="approve"]').count() == 0 and terms.locator('button[data-action="edit"]').count() == 0
        terms.locator('button[data-action="acknowledge"]').click()
        page.locator('.item[data-qid="b"]').filter(has_text=re.compile(re.escape("Decision: acknowledge"))).wait_for()
        saved = load_review(path)
        assert [i["decision"]["action"] for i in saved["items"]] == ["edit", "acknowledge"]
    finally:
        context.close()
        srv.stop()
