"""Requirement G: resumable progress, safe recovery, audit report, and artifact privacy. Local fixtures only."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from formfill.web.artifacts import posix_permissions, write_text_atomic
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.progress import (
    SCHEMA,
    SCHEMA_VERSION,
    ProgressError,
    Reconciler,
    ResumeConflict,
    check_target,
    load_progress,
    validate_progress,
)
from formfill.web.report import render_audit_report
from formfill.web.result import ItemResult, RunResult
from formfill.web.steps import DiscoveryPolicy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.wizards.server import serve  # noqa: E402

FULL = {
    "company": {"legal_name": "Fictional Vendor LLC", "website": "https://vendor.example", "employees": 120},
    "security": {"incident_response_plan": True, "incident_response_exercise_date": "2026-03-14", "encryption_at_rest": "AES-256",
                 "contact": {"email": "security@vendor.example", "phone": "+44 20 7946 0000"}},
}
NO_EMAIL = {"company": FULL["company"], "security": {**FULL["security"], "contact": {"phone": "+44 20 7946 0000"}}}


def good_doc(**over) -> dict:
    doc = {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "run_id": "abc", "updated_at": datetime.now(UTC).isoformat(),
           "target": {"origin": "http://127.0.0.1:1", "path": "/w"}, "navigation": {}, "fields": [
               {"question_id": "q1", "signature": {"label": "Name", "name": "n", "html_id": "n", "section": "", "kind": "text"},
                "question": "Name", "required": False, "status": "ANSWER", "entered": True, "state": "verified", "answer": "X"}]}
    doc.update(over)
    return doc


# ---- the file: validation, atomic writes, permissions ---------------------------------------------------------------------------


@pytest.mark.parametrize(("content", "message"), [
    ("{not json", "corrupt"),
    (json.dumps([1, 2]), "not a JSON object"),
    (json.dumps({**good_doc(), "schema": "something.else"}), "not a FormFiller progress file"),
    (json.dumps({**good_doc(), "schema_version": 99}), "incompatible"),
    (json.dumps({k: v for k, v in good_doc().items() if k != "fields"}), "incomplete"),
    (json.dumps(good_doc(fields=[{"question_id": "q1"}])), "incomplete"),
    (json.dumps(good_doc(fields=[{**good_doc()["fields"][0], "status": "SUBMITTED"}])), "incomplete"),
    (json.dumps(good_doc(updated_at=(datetime.now(UTC) - timedelta(days=30)).isoformat())), "stale"),
])
def test_a_progress_file_that_cannot_be_trusted_is_refused(tmp_path, content, message):
    path = tmp_path / "progress.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProgressError, match=message):
        load_progress(path)


def test_a_valid_file_loads_and_a_missing_one_is_reported(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps(good_doc()), encoding="utf-8")
    assert load_progress(path)["run_id"] == "abc"
    with pytest.raises(ProgressError, match="no progress file"):
        load_progress(tmp_path / "missing.json")


def test_resuming_on_another_origin_is_refused():
    doc = validate_progress(good_doc())
    with pytest.raises(ProgressError, match="progress file is for"):
        check_target(doc, "http://localhost:1/w")
    assert check_target(doc, "http://127.0.0.1:1/w?token=x") == []
    assert check_target(doc, "http://127.0.0.1:1/other") != []


def test_atomic_writes_leave_no_temporary_files_and_are_owner_only_where_supported(tmp_path):
    target = tmp_path / "out" / "result.json"
    write_text_atomic(target, '{"a": 1}')
    write_text_atomic(target, '{"a": 2}')
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in target.parent.iterdir()] == ["result.json"]
    if posix_permissions():
        assert (target.stat().st_mode & 0o777) == 0o600 and (target.parent.stat().st_mode & 0o777) == 0o700
    else:
        assert os.name == "nt"  # documented: on Windows files inherit the folder's access control; modes are not applied


def test_a_control_that_matches_two_saved_questions_is_ambiguous():
    f = good_doc()["fields"][0]
    rec = Reconciler(validate_progress(good_doc(fields=[f, {**f, "question_id": "q2"}])))
    with pytest.raises(ResumeConflict):
        rec(None, Control(control_id="c9", kind="text", label="Name", name="n", html_id="n"), 1)


# ---- resuming a walk on a live page -------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site():
    with serve() as (base, rec):
        yield base, rec


def fresh_draft(page, url):
    release_wizard_network_guard(page)
    page.goto(url)
    page.evaluate("() => localStorage.clear()")
    page.reload()


@pytest.mark.browser
def test_a_walk_is_resumed_from_its_progress_file_and_saved_answers_are_re_verified_not_re_entered(page, site, tmp_path):
    base, _ = site
    url = f"{base}/client_wizard.html?persist=1"
    progress = tmp_path / "progress.json"
    fresh_draft(page, url)
    first = run_form(page, NO_EMAIL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress)
    assert first.navigation["stop_reason"] == "required_unresolved" and first.navigation["steps_visited"] == 3
    saved = load_progress(progress)
    assert saved["event"] == "finished" and saved["navigation"]["steps_visited"] == 3
    assert {f["question"]: f["state"] for f in saved["fields"]}["Security contact email"] == "needs_review"
    with pytest.raises(ValueError, match="already exists"):
        run_form(page, NO_EMAIL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress)  # never overwritten silently

    # later: the browser is reopened on the draft (here: a reload), and the source now has the missing fact
    release_wizard_network_guard(page)
    page.reload()
    edits_before = page.evaluate("() => ({...window.__edits})")
    second = run_form(page, FULL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress, resume=True)
    log = {e["question"]: e["action"] for e in second.navigation["resume"]["log"]}
    assert log["Security contact phone"] == "re-verified, not re-entered"
    assert log["Security contact email"].startswith("replanned")
    edits = page.evaluate("() => window.__edits")
    assert edits.get("sec_phone", 0) == edits_before.get("sec_phone", 0)  # the restored value was not typed again
    assert edits.get("sec_email", 0) > 0
    phone = next(i for i in second.items if i.plan.question == "Security contact phone")
    assert phone.state.value == "verified" and "restored from the progress file" in phone.detail
    assert second.navigation["stop_reason"] == "required_unresolved" and second.navigation["steps"][-1]["heading"] == "4. Declaration"
    resumed = load_progress(progress)
    assert resumed["resumed_from"] == saved["run_id"] and resumed["run_id"] != saved["run_id"]
    carried = [f["question"] for f in resumed["fields"] if f.get("carried_over")]
    assert "Legal company name" in carried  # earlier steps are kept, marked as not re-verified in this run
    assert page.evaluate("() => window.__submitted") == 0


@pytest.mark.browser
def test_a_value_changed_since_the_saved_run_is_not_overwritten(page, site, tmp_path):
    base, _ = site
    url = f"{base}/client_wizard.html?persist=1"
    progress = tmp_path / "progress.json"
    fresh_draft(page, url)
    run_form(page, NO_EMAIL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress)
    release_wizard_network_guard(page)
    page.evaluate("() => { const d = JSON.parse(localStorage.getItem('ff_draft')); d.state.sec_phone = '+1 555 0100'; "
                  "localStorage.setItem('ff_draft', JSON.stringify(d)); }")
    page.reload()
    result = run_form(page, FULL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress, resume=True)
    phone = next(i for i in result.items if i.plan.question == "Security contact phone")
    assert phone.state.value == "needs_review" and "differs from the saved answer" in phone.plan.reason
    assert page.evaluate("() => window.__state.sec_phone") == "+1 555 0100"  # left as the page holds it (the walk moved on to step 4)
    assert page.evaluate("() => window.__edits.sec_phone || 0") == 0  # and never typed into


@pytest.mark.browser
def test_the_progress_file_and_result_never_contain_cookies_or_tokens(page, site, tmp_path):
    base, _ = site
    progress = tmp_path / "progress.json"
    release_wizard_network_guard(page)
    page.context.add_cookies([{"name": "session", "value": "SECRET-SESSION-TOKEN", "url": base}])
    page.goto(f"{base}/client_wizard.html?token=SECRET-QUERY-TOKEN")
    result = run_form(page, FULL, policy=DiscoveryPolicy(), confirm_ms=0, progress_path=progress, out_dir=tmp_path / "out")
    for path in (progress, tmp_path / "out" / "result.json", tmp_path / "out" / "audit_report.md"):
        text = path.read_text(encoding="utf-8")
        assert "SECRET-SESSION-TOKEN" not in text, path
        assert "SECRET-QUERY-TOKEN" not in text, path
    assert load_progress(progress)["target"] == {"origin": base, "path": "/client_wizard.html"}  # no query string kept
    assert "SECRET-QUERY-TOKEN" not in json.dumps(result.navigation)


# ---- audit report -----------------------------------------------------------------------------------------------------------------


def make_result() -> RunResult:
    ok = AnswerPlanItem(question_id="a", question="Legal company name", field_type="text", required=True, status="ANSWER",
                        source="company.legal_name", answer="Fictional Vendor LLC", confidence=1.0, confidence_category="high")
    att = AnswerPlanItem(question_id="b", question="I certify the information is accurate", field_type="checkbox", required=True,
                         status="REVIEW", reason="attestation/consent: a human must confirm it, never auto-filled")
    items = [ItemResult(plan=ok, filled=True, attempted=True, verified=True, ever_verified=True, observed="Fictional Vendor LLC"),
             ItemResult(plan=att)]
    return RunResult(url="http://127.0.0.1:1/form?token=abc", status="NEEDS_REVIEW", items=items,
                     navigation={"steps_visited": 2, "stop_reason": "required_unresolved", "steps": [
                         {"step": 1, "heading": "Company", "transition": "advanced", "required_unresolved": []},
                         {"step": 2, "heading": "Declaration", "transition": None, "required_unresolved": [{"question": "I certify"}]}],
                         "notes": [{"kind": "required_unresolved", "reason": "a required question is open"}],
                         "blocked_requests": [{"url": "http://127.0.0.1:1/api", "method": "POST", "resource_type": "fetch"}]})


def test_the_audit_report_counts_states_and_explains_the_stop():
    text = render_audit_report(make_result())
    assert "| state: verified | 1 |" in text and "| state: needs_review | 1 |" in text
    assert "| blocked requests | 1 |" in text and "| required still open | 1 |" in text
    assert "Stopped: `required_unresolved`" in text and "Reason: a required question is open" in text
    assert "Fictional Vendor LLC" in text and "token=abc" not in text
    assert "not a submission" in text.lower() or "nothing in this report is a submission" in text.lower()


def test_a_redacted_report_hides_the_answers():
    text = render_audit_report(make_result(), redact_values=True)
    assert "Fictional Vendor LLC" not in text and "[redacted]" in text


def test_a_proposal_for_review_is_never_shown_as_an_answer():
    result = make_result()
    result.items.append(ItemResult(plan=AnswerPlanItem(
        question_id="c", question="Incident response process", field_type="text", required=False, status="REVIEW",
        method="semantic", proposed_answer="Yes", reason="semantic proposal for a reviewer")))
    row = next(line for line in render_audit_report(result).splitlines() if "Incident response process" in line)
    assert "proposed, not entered: Yes" in row and "| needs_review |" in row
    redacted = next(line for line in render_audit_report(result, redact_values=True).splitlines() if "Incident response process" in line)
    assert "proposed, not entered: [redacted]" in redacted
