"""Submit gate: an answer whose commit failed (filled=False) must block submission even when the read-back later looks right.

The executor leaves a field with `blur` so frameworks that commit on blur record the answer (execute._commit). If the page's
main thread is busy, the blur times out and `_fill_one` records `filled=False`. The typed text can still be on the page, so
the final read-back (`_judge`) reports verified=True. The submit gate used to look only at `verified is False`, so such an
item did not block `submit=True`, while the run status (`overall_status`) already said FAILED: a form could be submitted
with an answer the application may never have recorded.

Local fixture only (fixtures/rfi_blur_stall.html): the page counts submit events itself; nothing is sent anywhere.
"""

from pathlib import Path

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SOURCE = {"company": {"name": "Acme Corp"}}
SUBMIT = "button[type=submit]"
DONE = "Thank you, your response was received"


def open_stalled(page, block_ms):
    page.goto((FIXTURES / "rfi_blur_stall.html").as_uri() + f"?block={block_ms}")
    return page


def test_failed_commit_with_correct_readback_does_not_submit(page):
    open_stalled(page, 1500)
    res = run_form(page, SOURCE, submit=True, submit_selector=SUBMIT, success_text=DONE, timeout_ms=500)
    item = res.items[0]
    assert item.plan.question == "Organization name" and item.plan.status == "ANSWER"

    # the trap: the commit (blur) failed, but the text is on the page and the read-back agrees
    assert item.filled is False and "Locator.blur" in item.detail
    assert item.verified is True and page.input_value("#org") == "Acme Corp"

    # the gate must still hold
    assert res.submission["outcome"] == "SKIPPED" and res.submission["attempted"] is False
    assert "not entered or failed verification" in res.submission["detail"]
    assert page.evaluate("() => window.__submits") == 0
    assert res.status == "FAILED"


def test_same_situation_without_submit_is_failed_and_records_no_submission(page):
    open_stalled(page, 1500)
    res = run_form(page, SOURCE, timeout_ms=500)
    assert res.status == "FAILED" and res.submission == {}
    assert res.items[0].filled is False and res.items[0].verified is True


def test_a_healthy_page_still_submits(page):
    # the gate did not turn into a blanket refusal: no stall, the commit succeeds, the form is submitted (to the local page)
    open_stalled(page, 0)
    res = run_form(page, SOURCE, submit=True, submit_selector=SUBMIT, success_text=DONE, timeout_ms=2000)
    item = res.items[0]
    assert item.filled is True and item.verified is True
    assert res.submission["outcome"] == "CONFIRMED" and res.status == "SUBMITTED"
    assert page.evaluate("() => window.__submits") == 1
