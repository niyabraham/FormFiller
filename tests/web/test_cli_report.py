"""Source loading, the CLI, the per-question outcome taxonomy, redaction, not_asked and the client-state reader."""

from __future__ import annotations

import json

import pytest

from formfill.web import cli
from formfill.web.models import AnswerPlanItem
from formfill.web.pipeline import run_form
from formfill.web.result import ItemResult, RunResult
from formfill.web.source import SourceError, describe, load_source

# ---- source loading (pure Python) ---------------------------------------------------------------------------------------


def write(tmp_path, text, name="s.json"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_source_ok_and_described(tmp_path):
    p = write(tmp_path, json.dumps({"a": {"city": "Leeds"}, "b": {"city": "Hull"}, "n": None, "e": "", "tbd": "TBD", "tags": ["x", "y"]}))
    d = describe(load_source(p))
    assert d["answerable_values"] == 4  # a.city, b.city, tbd, tags (null and "" skipped; a list of scalars is ONE leaf)
    assert d["placeholder_values"] == ["tbd"]
    assert "city" in d["same_field_name_under_different_parents"]


@pytest.mark.parametrize("text,needle", [
    ("{not json", "invalid JSON at line 1"),
    ("[1, 2]", "top level must be a JSON object"),
    ('"just a string"', "top level must be a JSON object"),
    ("{}", "no answerable values"),
    ('{"a": null, "b": "", "c": []}', "no answerable values"),
])
def test_load_source_rejects_unusable_files_with_a_clear_message(tmp_path, text, needle):
    with pytest.raises(SourceError, match=needle):
        load_source(write(tmp_path, text))


def test_load_source_missing_file(tmp_path):
    with pytest.raises(SourceError, match="not found"):
        load_source(tmp_path / "nope.json")


# ---- CLI (pure Python parts) --------------------------------------------------------------------------------------------


def test_cli_ask_prints_json(tmp_path, capsys):
    p = write(tmp_path, json.dumps({"employee_count": 150, "company_name": "ABC"}))
    assert cli.main(["ask", "--source", str(p), "--kind", "number", "What is your company's workforce size?"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ANSWER" and out["answer"] == 150 and out["source"] == "employee_count"


def test_cli_ask_review_has_reason(tmp_path, capsys):
    p = write(tmp_path, json.dumps({"employee_count": 150}))
    cli.main(["ask", "--source", str(p), "How many employees will you have next year?", "--kind", "number"])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "REVIEW" and out["answer"] is None and out["reason"]


def test_cli_bad_source_exits_3(tmp_path, capsys):
    assert cli.main(["check-source", "--source", str(write(tmp_path, "{oops"))]) == 3
    assert "invalid JSON" in capsys.readouterr().err
    assert cli.main(["fill", "--source", str(tmp_path / "x.json"), "--url", "http://example.invalid"]) == 3


def test_cli_has_no_submit_option():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["fill", "--source", "s", "--url", "u", "--submit"])


# ---- outcome taxonomy (pure Python) -------------------------------------------------------------------------------------


def item(status="ANSWER", filled=True, verified=True, app_state="not_checked"):
    return ItemResult(plan=AnswerPlanItem("q", "Q", "text", False, status, answer="x" if status == "ANSWER" else None),
                      filled=filled, verified=verified, app_state=app_state)


@pytest.mark.parametrize("it,expected", [
    (item("REVIEW", False, None), "needs_review"),
    (item(filled=False, verified=None), "failed"),
    (item(verified=False), "failed"),
    (item(verified=None), "unverified"),
    (item(), "verified_dom"),
    (item(app_state="confirmed"), "verified_client_state"),
    (item(app_state="mismatch"), "failed"),
])
def test_outcome_taxonomy(it, expected):
    assert it.outcome == expected
    assert it.server_persistence == "not_checked"  # FormFiller never submits, so nothing can have been persisted


def test_summary_counts_outcomes():
    r = RunResult(url="u", status="NEEDS_REVIEW", items=[item(), item(), item("REVIEW", False, None)])
    s = r.to_dict()["summary"]
    assert s["verified_dom"] == 2 and s["needs_review"] == 1 and s["questions"] == 3


def test_redaction_removes_values_but_keeps_paths_and_reasons():
    plan = AnswerPlanItem("q", "Q", "text", False, "ANSWER", source="company.name", raw_value="Acme Corp", answer="Acme Corp",
                          alternatives=[{"source": "other", "value": "Secret Ltd", "score": 0.5, "flags": ["differs: 'Secret Ltd'"]}],
                          evidence=["question cites ['Omaha']"], reason=None)
    review = AnswerPlanItem("r", "R", "text", True, "REVIEW", reason="'Zed' holds the placeholder 'TBD'")
    r = RunResult(url="u", status="NEEDS_REVIEW", items=[ItemResult(plan=plan, filled=True, observed="Acme Corp", verified=True,
                                                                    detail="expected 'Acme Corp', page holds 'Acme Co'"),
                                                         ItemResult(plan=review)])
    text = r.to_json(redact=True)
    for secret in ("Acme Corp", "Secret Ltd", "Omaha", "Zed", "Acme Co"):
        assert secret not in text, secret
    d = json.loads(text)
    assert d["redacted"] is True and d["items"][0]["plan"]["source"] == "company.name" and d["items"][0]["outcome"] == "verified_dom"
    assert "placeholder" in d["items"][1]["plan"]["reason"]


# ---- browser: CLI fill, not_asked, state reader -------------------------------------------------------------------------

browser_only = pytest.mark.browser

BASIC = {"company": {"name": "Acme Corp", "full_time": 210, "employees": 250, "website_url": "https://acme.example",
                     "country": "India", "founded": "2009-03-14"},
         "security": {"contact": {"email": "sec@acme.example"}}, "certifications": {"iso_27001": True}}


def _run_cli(tmp_path, *extra):
    """The real entry point, in its own process (the shared browser fixture already owns a Playwright loop here)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    fx = Path(__file__).parent / "fixtures" / "rfi_basic.html"
    src = write(tmp_path, json.dumps(BASIC))
    out = tmp_path / "run"
    proc = subprocess.run([sys.executable, "-m", "formfill", "fill", "--source", str(src), "--url", str(fx), "--out-dir", str(out), *extra],
                          capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    return proc, out


@browser_only
def test_cli_fill_writes_the_documented_artifacts_and_never_submits(browser, tmp_path):
    proc, out = _run_cli(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert {p.name for p in out.iterdir()} == {"result.json", "filled.png", "trace.zip"}
    data = json.loads((out / "result.json").read_text())
    assert data["status"] == "NEEDS_REVIEW" and data["human_submission"]["performed_by_formfill"] is False
    assert data["summary"]["verified_dom"] >= 6
    assert "NOT performed by FormFiller" in proc.stdout and "verified_dom" in proc.stdout


@browser_only
def test_cli_redacted_run_writes_no_screenshot_or_trace_and_no_values(browser, tmp_path):
    proc, out = _run_cli(tmp_path, "--redact", "--quiet")
    assert proc.returncode == 0, proc.stderr
    assert [p.name for p in out.iterdir()] == ["result.json"]
    text = (out / "result.json").read_text()
    for v in ("Acme Corp", "sec@acme.example", "acme.example", "2009-03-14"):
        assert v not in text, v
    assert "company.name" in text  # the audit trail (paths) survives


@browser_only
def test_cli_strict_exits_1_when_not_ready(browser, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    fx = Path(__file__).parent / "fixtures" / "rfi_basic.html"
    src = write(tmp_path, json.dumps({"company": {"name": "Acme Corp"}}))  # the required email is unanswerable
    proc = subprocess.run([sys.executable, "-m", "formfill", "fill", "--source", str(src), "--url", str(fx), "--out-dir", str(tmp_path / "o"),
                           "--strict", "--quiet", "--no-trace"], capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    assert proc.returncode == 1, proc.stderr


@browser_only
def test_not_asked_lists_controls_that_never_appeared(open_fixture):
    page = open_fixture("rfi_basic.html")
    res = run_form(page, BASIC)
    assert isinstance(res.not_asked, list)  # structure; this fixture reveals everything it has
    page.set_content('<label for="a">Company name</label><input id="a" name="a">'
                     '<label for="h">Hidden question</label><input id="h" name="h" style="display:none">')
    res = run_form(page, {"company_name": "Acme"})
    assert [n["label"] for n in res.not_asked] == ["Hidden question"] and res.not_asked[0]["why"] == "stayed hidden"
    assert any("stayed hidden" in w for w in res.warnings)


APP_PAGE = """
<label for="name">Company name</label><input id="name" name="name">
<label for="phone">Phone</label><input id="phone" name="phone">
<script>window.__s = {}; document.getElementById('name').addEventListener('change', e => window.__s.name = e.target.value);
/* the app never records the phone */</script>
"""


@browser_only
def test_state_reader_distinguishes_dom_from_client_state(page):
    page.set_content(APP_PAGE)
    res = run_form(page, {"company_name": "Acme", "phone": "+44 20 7946 0000"}, state_reader=lambda p: p.evaluate("window.__s"))
    by = {i.plan.question: i for i in res.items}
    assert by["Company name"].outcome == "verified_client_state" and by["Company name"].app_state == "confirmed"
    assert by["Phone"].outcome == "verified_dom" and by["Phone"].app_state == "not_checked"  # absent from app state: no claim either way


@browser_only
def test_state_reader_mismatch_is_a_failure(page):
    page.set_content(APP_PAGE.replace("e.target.value", "'something else'"))
    res = run_form(page, {"company_name": "Acme"}, state_reader=lambda p: p.evaluate("window.__s"))
    it = next(i for i in res.items if i.plan.question == "Company name")
    assert it.app_state == "mismatch" and it.outcome == "failed" and res.status == "FAILED"


@browser_only
def test_broken_state_reader_does_not_break_the_run(page):
    page.set_content(APP_PAGE)

    def boom(_):
        raise RuntimeError("no store")

    res = run_form(page, {"company_name": "Acme"}, state_reader=boom)
    assert any("state reader failed" in i.detail for i in res.items) and res.items[0].outcome == "verified_dom"
