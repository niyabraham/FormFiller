"""Phase 3C: SPA browser behaviour against local fixtures (benchmarks/spa). Nothing here touches a real portal."""

import json
from pathlib import Path

import pytest

from formfill.web.pipeline import run_form
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
        page.goto(f"{base}/{fid}.html")
        pol = policy if isinstance(policy, DiscoveryPolicy) else (DiscoveryPolicy() if policy else None)
        res = run_form(page, SOURCE, policy=pol, **kw)
        state = page.evaluate("() => window.__state || {}")
        return res, state, page

    return _run


def answered(res):
    return {i.plan.question.replace(" *", ""): i for i in res.items if i.plan.status == "ANSWER"}


@pytest.mark.parametrize("fid", ["wiz_hidden", "wiz_unmount", "wiz_async", "wiz_route", "wiz_guard", "wiz_labels"])
def test_wizard_all_steps_filled_and_committed(run, fid):
    res, state, page = run(fid)
    assert res.navigation["steps_visited"] == 3
    assert {k: state[k] for k in GT[fid]["expected"]} == GT[fid]["expected"]
    assert all(i.verified for i in answered(res).values())
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


def test_document_navigation_stops_and_loss_is_reported(run):
    res, _, _ = run("nav_reload")
    assert res.navigation["stop_reason"] == "document_navigation"
    assert res.status == "FAILED"


def test_reset_during_navigation_is_detected(run):
    res, _, _ = run("nav_reset")
    assert res.navigation["resets_detected"] == ["Company website"]
    assert answered(res)["Company website"].verified is False


def test_attestation_stays_review(run):
    _, state, _ = run("attest")
    assert "certify" not in state and state.get("signer", "") == ""


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


def test_intercepted_submit_button_is_refused_by_default_but_opt_in_navigates(run):
    res, _, _ = run("spa_submit_type_intercepted")
    assert res.navigation["stop_reason"] == "submit_type_next_refused" and res.navigation["steps_visited"] == 1
    res2, state2, page2 = run("spa_submit_type_intercepted", DiscoveryPolicy(allow_submit_type_navigation=True))
    assert res2.navigation["steps_visited"] == 3 and state2["city"] == "Leeds"
    assert page2.evaluate("() => window.__submitted") == 0


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


def test_opt_in_policy_finds_submit_type(page):
    from formfill.web.steps import next_button

    page.set_content('<form><button type="submit">Next</button></form>')
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
    assert res.navigation["steps_visited"] == 3 and all(i.verified for i in answered(res).values())
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
