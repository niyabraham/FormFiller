"""A text answer typed into a server-rendered input just before a UI framework takes the input over can be wiped by that
framework. Measured on a public page (README): the page's own bundle assigned `.value = ""` about 1.5 s after an early fill, the
same moment React's internal keys first appeared on the node; a fill after that held.

The run therefore re-enters a text answer ONCE when it is gone on the same node AND a framework attached to the node after the
answer was typed. Everything else stays a reported failure. The fixture is written from the measured behaviour, not copied.
"""

import pytest

from formfill.web.discover import discover
from formfill.web.execute import framework_attached
from formfill.web.pipeline import release_wizard_network_guard, run_form

pytestmark = pytest.mark.browser

SOURCE = {"company": {"name": "Acme Robotics Ltd"}}


def _open(page, mode, ms=700):
    from pathlib import Path

    release_wizard_network_guard(page)
    page.goto((Path(__file__).parent / "fixtures" / "late_hydrate.html").as_uri() + f"?mode={mode}&ms={ms}")


def _run(page, mode, **kw):
    _open(page, mode)
    return run_form(page, SOURCE, confirm_ms=1500, **kw)


def test_value_wiped_by_hydration_is_re_entered_once_and_reported(page):
    res = _run(page, "hydrate")
    item = res.items[0]
    assert item.reentered and item.verified is True and item.observed == "Acme Robotics Ltd"
    assert "re-entered once" in item.detail and res.status == "FILLED"
    assert any("re-entered once" in w for w in res.warnings)  # a recovery is never silent
    assert page.evaluate("() => window.__hydrationEvents") == ["initial-answer-input", "hydration-reset"]
    assert page.input_value("#v") == "Acme Robotics Ltd"


def test_re_entry_does_not_happen_when_nothing_was_wiped(page):
    for mode in ("keep", "already"):
        res = _run(page, mode)
        assert not res.items[0].reentered and res.items[0].verified is True and res.status == "FILLED", mode
        assert not res.warnings


def test_a_reset_without_framework_evidence_is_a_failure_not_retried(page):
    res = _run(page, "reset_nokeys")
    item = res.items[0]
    assert not item.reentered and item.verified is False and item.observed == "" and res.status == "FAILED"
    assert item.framework_attached_at_fill is False
    assert page.evaluate("() => window.__hydrationEvents") == [
        "initial-answer-input", "reset-without-framework"
    ]


def test_a_second_loss_after_re_entry_is_still_a_failure(page):
    res = _run(page, "hydrate_twice")
    item = res.items[0]
    assert item.reentered and item.verified is False and res.status == "FAILED"
    assert page.evaluate("() => window.__hydrationEvents") == [
        "initial-answer-input", "hydration-reset", "reentry-input", "second-reset"
    ]


def test_failed_run_after_re_entry_blocks_submission(page):
    _open(page, "hydrate_twice")
    res = run_form(page, SOURCE, confirm_ms=1500, submit=True)
    assert res.status == "FAILED" and res.submission["attempted"] is False


def test_framework_state_is_recorded_when_the_answer_is_typed(page):
    _open(page, "already")
    ctl = discover(page).controls[0]
    assert framework_attached(page, ctl) is True
    res = run_form(page, SOURCE, confirm_ms=0)
    assert res.items[0].framework_attached_at_fill is True
    _open(page, "reset_nokeys")
    assert run_form(page, SOURCE, confirm_ms=0).items[0].framework_attached_at_fill is False


def test_review_items_and_choices_are_never_re_entered(page):
    page.set_content("<body><label for='x'>Blood type of the chief executive</label><input id='x'>"
                     "<script>setTimeout(()=>{x['__reactFiber$z']={};x.value=''},300)</script></body>")
    res = run_form(page, SOURCE, confirm_ms=600)
    assert res.items[0].plan.status == "REVIEW" and not res.items[0].reentered and page.input_value("#x") == ""
