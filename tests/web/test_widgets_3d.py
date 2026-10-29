"""Phase 3D: widget commitment and verification against SurveyJS-compatible local fixtures (benchmarks/spa/fixtures/w3d_*).

Three separate things are asserted and must not be conflated:
  DOM read-back   what the page's own elements hold afterwards (what the pipeline can observe in any app)
  app state       what the application recorded (window.__state; only measurable because these fixtures expose it)
  discovery       whether a conditional question that depends on a commit appeared and was answered
Generic local fixtures say nothing about the reliability of any real portal."""

import json
from pathlib import Path

import pytest

from formfill.web import execute
from formfill.web.pipeline import release_wizard_network_guard, run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "spa"
SOURCE = json.loads((BENCH / "source.json").read_text())

import sys

sys.path.insert(0, str(BENCH.parents[1]))
from benchmarks.spa.server import serve


@pytest.fixture(scope="module")
def base():
    with serve() as url:
        yield url


@pytest.fixture
def run(page, base):
    def _run(fid, policy=False, **kw):
        release_wizard_network_guard(page)
        page.goto(f"{base}/{fid}")
        res = run_form(page, SOURCE, policy=DiscoveryPolicy() if policy else None, **kw)
        return res, page.evaluate("() => window.__state || {}"), page

    return _run


MODES = pytest.mark.parametrize("policy", [False, True], ids=["policy=None", "policy=DiscoveryPolicy()"])


def by_label(res, text):
    return next(i for i in res.items if text.lower() in i.plan.question.lower())


def no_submission(page, res):
    """No form submit event, no submission attempt recorded by the pipeline, and (policy mode) the page-side submit counter is 0."""
    assert res.submission == {} and page.evaluate("() => window.__ffSubmits || 0") == 0


@MODES
def test_blur_commit_reaches_app_state_and_reveals_conditional(run, policy):
    res, state, page = run("w3d_blur_commit.html", policy=policy)
    assert state == {"name": "Acme Robotics Ltd", "email": "info@acme-robotics.example", "city": "Leeds"}  # app state
    assert all(by_label(res, k).verified for k in ("company name", "email", "city"))  # DOM read-back
    assert page.input_value("#city") == "Leeds"  # conditional field discovered and filled
    assert not any(execute.UNSETTLED in w for w in res.warnings)  # a normal page that goes quiet promptly is not flagged
    no_submission(page, res)


@MODES
def test_blur_commit_delayed_reveal_is_discovered_and_filled(run, policy):
    # no email field, so the name is the last answer of the first pass; city renders 60 ms after its commit
    res, state, page = run("w3d_blur_commit.html?mode=delay", policy=policy)
    assert state == {"name": "Acme Robotics Ltd", "city": "Leeds"}
    assert state["city"] == "Leeds" and by_label(res, "city").verified and page.input_value("#city") == "Leeds"
    assert not any(execute.UNSETTLED in w for w in res.warnings)


def test_unsettled_page_is_reported_not_treated_as_settled(run, monkeypatch):
    monkeypatch.setattr(execute, "_SETTLE_MAX_MS", 300)  # a page that re-renders every 30 ms never reaches the 150 ms quiet window
    res, state, _ = run("w3d_blur_commit.html?mode=churn")
    item = by_label(res, "company name")
    assert item.filled and item.detail.startswith(execute.UNSETTLED)
    assert any(execute.UNSETTLED in w for w in res.warnings) and res.status == "NEEDS_REVIEW"  # never FILLED
    assert state["name"] == "Acme Robotics Ltd"  # the answer itself still committed; only completeness is in doubt


def test_unsettled_page_blocks_submit(run, monkeypatch):
    monkeypatch.setattr(execute, "_SETTLE_MAX_MS", 300)
    res, _, _ = run("w3d_blur_commit.html?mode=churn", submit=True)
    assert res.submission["outcome"] == "SKIPPED" and res.status == "NEEDS_REVIEW"


def test_blur_revert_is_not_reported_as_success(run):
    res, state, _ = run("w3d_blur_commit.html?mode=revert")
    item = by_label(res, "company name")
    assert not item.verified and "name" not in state


@MODES
def test_readonly_combobox_option_is_picked_and_committed(run, policy):
    res, state, page = run("w3d_readonly_combobox.html", policy=policy)  # decorative wrapper over the input: still clickable
    item = by_label(res, "country")
    assert item.filled and item.verified
    assert state["country"] == "United Kingdom" and page.input_value("#country") == "United Kingdom"
    assert page.evaluate("() => window.__sideEffects") == {"clicks": 0, "submits": 0}
    no_submission(page, res)


@MODES
def test_unopenable_readonly_combobox_stops_with_clear_reason(run, policy):
    res, state, page = run("w3d_readonly_combobox.html?mode=dead", policy=policy, timeout_ms=5000)
    item = by_label(res, "country")
    # our own error (not Playwright's 5 s action timeout); asserted on content, not on elapsed wall-clock time
    assert not item.filled and item.detail.startswith("fill failed: unsupported readonly combobox") and "Timeout" not in item.detail
    assert "country" not in state
    no_submission(page, res)


@MODES
def test_overlapping_submit_button_is_never_clicked_keyboard_opens_list(run, policy):
    res, state, page = run("w3d_readonly_combobox.html?mode=overlap", policy=policy)
    item = by_label(res, "country")
    assert item.filled and item.verified and state["country"] == "United Kingdom"  # opened with the keyboard instead
    assert page.evaluate("() => window.__sideEffects") == {"clicks": 0, "submits": 0}  # the Submit button got no click, no submit
    no_submission(page, res)


@MODES
def test_overlapping_submit_button_and_no_keyboard_support_is_a_safe_unsupported_stop(run, policy):
    res, state, page = run("w3d_readonly_combobox.html?mode=overlap_dead", policy=policy)
    item = by_label(res, "country")
    assert not item.filled and "click refused" in item.detail and "Submit application" in item.detail and "Timeout" not in item.detail
    assert page.evaluate("() => window.__sideEffects") == {"clicks": 0, "submits": 0} and "country" not in state
    no_submission(page, res)


def test_overlapping_navigation_button_is_never_clicked(run):
    # default mode only: with a policy the walk is allowed to press a button labelled Continue, which would blur this test
    for mode in ("overlap_nav", "overlap_dead"):
        _, _, page = run(f"w3d_readonly_combobox.html?mode={mode}")
        assert page.evaluate("() => window.__sideEffects") == {"clicks": 0, "submits": 0}, mode


@MODES
def test_styled_radio_selected_through_label_not_forced(run, policy):
    res, state, page = run("w3d_styled_radio.html", policy=policy, timeout_ms=3000)
    item = by_label(res, "sector")
    assert item.filled and item.verified
    assert state["sector"] == "Manufacturing" and page.is_checked("#r1") and not page.is_checked("#r2")
    no_submission(page, res)


@MODES
@pytest.mark.parametrize("fid", ["controlled", "cond_sync", "combobox"])
def test_ordinary_and_controlled_inputs_unchanged(page, base, fid, policy):
    page.goto(f"{base}/{fid}.html")
    res = run_form(page, SOURCE, policy=DiscoveryPolicy() if policy else None)
    assert any(i.verified for i in res.items), fid
    assert not any(execute.UNSETTLED in w for w in res.warnings)
    no_submission(page, res)
