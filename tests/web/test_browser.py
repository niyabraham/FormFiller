"""Browser integration tests against local fixture pages (no network).

Pattern borrowed from MiniWoB++/WebArena: small, controllable pages and a
programmatic success check on the resulting DOM state.
"""

import json

import pytest

from formfill.web.discover import discover
from formfill.web.execute import read_back, submit
from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

BASIC_SOURCE = {
    "company": {"name": "Acme Corp", "full_time": 210, "employees": 250, "website_url": "https://acme.example",
                "country": "India", "founded": "2009-03-14"},
    "security": {"contact": {"email": "sec@acme.example"}},
    "certifications": {"iso_27001": True},
}


def by_label(schema):
    return {c.label: c for c in schema.controls}


# ---- discovery ---------------------------------------------------------------


def test_discovery_captures_labels_constraints_and_options(open_fixture):
    schema = discover(open_fixture("rfi_basic.html"))
    c = by_label(schema)
    org = c["Organization name *"]
    assert (org.kind, org.required, org.maxlength, org.section) == ("text", True, 20, "Company details")
    ft = c["Number of full-time employees"]
    assert (ft.kind, ft.min, ft.help_text) == ("number", "0", "Whole numbers only")
    assert c["Security contact email"].kind == "email"  # wrapping <label>
    assert c["Website"].kind == "url"  # aria-labelledby
    country = c["Country"]
    assert [o.value for o in country.options] == ["IN", "US"]  # placeholder option excluded
    iso = c["Do you hold ISO 27001 certification?"]  # fieldset legend
    assert iso.kind == "radio" and [o.label for o in iso.options] == ["Yes", "No"]
    assert c["I confirm the answers are accurate"].kind == "checkbox"
    assert c["Describe your incident response process"].kind == "textarea"
    assert c["Describe your incident response process"].section == "Controls"
    assert len({x.control_id for x in schema.controls}) == len(schema.controls)


def test_rediscovery_keeps_ids(open_fixture):
    page = open_fixture("rfi_basic.html")
    first = [c.control_id for c in discover(page).controls]
    assert first == [c.control_id for c in discover(page).controls]


def test_checkbox_group_multiselect_and_iframe(open_fixture):
    page = open_fixture("rfi_widgets.html")
    page.wait_for_selector("iframe")
    page.frame_locator("#fr").locator("#fe").wait_for()
    c = by_label(discover(page))
    assert c["Certifications held"].kind == "checkbox_group" and len(c["Certifications held"].options) == 3
    assert c["Operating regions"].kind == "multiselect"
    assert c["Frame email"].frame_index == 1  # found inside the iframe


# ---- end to end --------------------------------------------------------------


def test_end_to_end_fills_answers_and_flags_the_rest(open_fixture, tmp_path):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, out_dir=tmp_path)
    got = {i.plan.question: i for i in result.items}

    assert got["Organization name"].plan.status == "ANSWER"
    assert page.input_value("#org") == "Acme Corp"
    assert page.input_value("#ft") == "210" and got["Number of full-time employees"].plan.source == "company.full_time"
    assert page.input_value("[name=sec_email]") == "sec@acme.example"
    assert page.input_value("#web") == "https://acme.example"
    assert page.input_value("#founded") == "2009-03-14"
    assert page.input_value("#country") == "IN"
    assert page.is_checked("input[name=iso][value=yes]")
    # no source value -> untouched and flagged
    assert got["Describe your incident response process"].plan.status == "REVIEW"
    assert page.input_value("#ir") == ""
    assert not page.is_checked("input[name=agree]")

    assert all(i.verified for i in result.items if i.plan.status == "ANSWER")
    assert result.status == "NEEDS_REVIEW"
    data = json.loads((tmp_path / "result.json").read_text())
    assert data["status"] == "NEEDS_REVIEW" and len(data["review_items"]) == 2
    assert (tmp_path / "filled.png").stat().st_size > 0


def test_submit_blocked_while_required_items_need_review(open_fixture):
    page = open_fixture("rfi_basic.html")
    src = {k: v for k, v in BASIC_SOURCE.items() if k != "security"}  # required email now unresolved
    result = run_form(page, src, submit=True, success_text="Thank you")
    assert result.submission["outcome"] == "SKIPPED" and result.status == "NEEDS_REVIEW"
    assert page.locator("#done").is_hidden()  # nothing was sent


def test_optional_attestation_blocks_submission_even_when_all_required_answers_are_present(open_fixture):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, submit=True, success_text="Thank you, your response was received")
    assert result.submission["outcome"] == "SKIPPED"
    assert result.status == "NEEDS_REVIEW"
    assert any("attestation" in item.plan.reason for item in result.items if item.plan.status == "REVIEW")
    assert page.locator("#done").is_hidden()


def test_optional_attestation_blocks_submission_without_confirmation_text(open_fixture):
    page = open_fixture("rfi_basic.html")
    result = run_form(page, BASIC_SOURCE, submit=True, success_text="Never appears", out_dir=None)
    assert result.submission["outcome"] == "SKIPPED" and result.status == "NEEDS_REVIEW"
    assert page.locator("#done").is_hidden()


def test_browser_validation_blocks_submission_and_is_reported(open_fixture):
    page = open_fixture("rfi_strict.html")
    page.fill("#code", "BAD")  # violates the pattern; the browser must refuse to submit
    outcome = submit(page, "button[type=submit]", success_text="Registration accepted", timeout_ms=800)
    assert outcome["outcome"] == "BLOCKED_BY_VALIDATION" and outcome["invalid_controls"]
    assert page.locator("#ok").is_hidden()
    page.fill("#code", "ABC-1234")
    assert submit(page, "button[type=submit]", success_text="Registration accepted")["outcome"] == "CONFIRMED"


def test_invalid_dom_readback_is_not_verified_or_filled(page):
    page.set_content(
        "<label for='org'>Organization name</label><input id='org'>"
        "<script>document.getElementById('org').addEventListener('input', e => "
        "e.target.setCustomValidity('fixture says invalid'))</script>"
    )
    result = run_form(page, BASIC_SOURCE, confirm_ms=0)
    item = next(i for i in result.items if i.plan.status == "ANSWER")
    assert item.observed == "Acme Corp" and item.browser_valid is False
    assert item.verified is False and result.status == "FAILED"


def test_optional_attestation_blocks_requested_submission(page):
    page.set_content(
        "<form onsubmit=\"window.__submitted=true;event.preventDefault()\">"
        "<label><input type='checkbox'>Do you agree that the information is accurate?</label>"
        "<button id='send' type='submit'>Send</button></form><script>window.__submitted=false</script>"
    )
    result = run_form(
        page,
        {"company": {"information_is_accurate": True}},
        submit=True,
        submit_selector="#send",
        confirm_ms=0,
    )
    assert result.items[0].plan.status == "REVIEW"
    assert result.submission["outcome"] == "SKIPPED"
    assert page.evaluate("() => window.__submitted") is False


ATTESTATION_FORM = (
    "<form onsubmit=\"window.__submitted=true;event.preventDefault()\">"
    "<label for='org'>Organization name</label><input id='org'>{extra}"
    "<button id='send' type='submit'>Send</button></form><script>window.__submitted=false</script>"
)
ATTESTATION_SOURCE = {
    "company": {"name": "Fictional Vendor LLC"}, "data_processing_addendum": "agree", "full_name": "Fictional Vendor LLC",
    "information_provided_accurate": "yes", "marketing_consent": True,
}


def test_control_the_same_form_without_an_attestation_is_submitted(page):
    page.set_content(ATTESTATION_FORM.format(extra=""))
    result = run_form(page, ATTESTATION_SOURCE, submit=True, submit_selector="#send", confirm_ms=0)
    assert [i.plan.status for i in result.items] == ["ANSWER"] and page.input_value("#org") == "Fictional Vendor LLC"
    assert result.submission["attempted"] is True and page.evaluate("() => window.__submitted") is True


def test_a_submission_the_page_never_confirms_is_reported_unconfirmed_not_submitted(page):
    """End to end through run_form: the form is clean, so the request is made; the page then says nothing, which must never be
    reported as a confirmed submission (local fixture; nothing leaves the machine)."""
    page.set_content(ATTESTATION_FORM.format(extra=""))
    result = run_form(page, ATTESTATION_SOURCE, submit=True, submit_selector="#send", success_text="Thank you, your response was received",
                      confirm_ms=0, timeout_ms=800)
    assert result.submission["attempted"] is True and page.evaluate("() => window.__submitted") is True
    assert result.submission["outcome"] == "UNCONFIRMED" and result.status == "SUBMITTED_UNCONFIRMED"


def test_the_same_clean_form_is_confirmed_when_the_page_does_say_so(page):
    page.set_content(ATTESTATION_FORM.format(extra="").replace(
        "window.__submitted=true;event.preventDefault()", "window.__submitted=true;event.preventDefault();document.body.append('Thank you, your response was received')"))
    result = run_form(page, ATTESTATION_SOURCE, submit=True, submit_selector="#send", success_text="Thank you, your response was received",
                      confirm_ms=0, timeout_ms=800)
    assert result.submission["outcome"] == "CONFIRMED" and result.status == "SUBMITTED"


@pytest.mark.parametrize("extra", [
    # the agreement is in the option labels, the question itself is neutral
    "<fieldset><legend>Data processing addendum</legend><label><input type='radio' name='dpa' value='agree'> I agree</label>"
    "<label><input type='radio' name='dpa' value='no'> I do not agree</label></fieldset>",
    # the signature instruction is only in the placeholder
    "<label for='n'>Full name</label><input id='n' placeholder='Type your full name to sign'>",
    # a vouching question with no verb
    "<label for='a'>Is the information provided in this questionnaire accurate?</label>"
    "<select id='a'><option value=''>-</option><option value='yes'>Yes</option><option value='no'>No</option></select>",
    # a statement-style consent radio
    "<fieldset><legend>Marketing consent</legend><label><input type='radio' name='mc' value='yes'> Yes</label>"
    "<label><input type='radio' name='mc' value='no'> No</label></fieldset>",
])
def test_optional_attestation_variants_block_requested_submission(page, extra):
    page.set_content(ATTESTATION_FORM.format(extra=extra))
    result = run_form(page, ATTESTATION_SOURCE, submit=True, submit_selector="#send", confirm_ms=0)
    flagged = [i for i in result.items if i.plan.status == "REVIEW"]
    assert flagged and all(i.plan.reason.startswith("attestation/consent") and not i.plan.required for i in flagged)
    assert any(i.plan.status == "ANSWER" and i.verified for i in result.items)  # the ordinary answer was entered ...
    assert result.submission["outcome"] == "SKIPPED" and result.submission["attempted"] is False  # ... but nothing is submitted
    assert result.status == "NEEDS_REVIEW" and page.evaluate("() => window.__submitted") is False
    assert page.locator("input:checked").count() == 0 and page.input_value("#org") == "Fictional Vendor LLC"


# ---- widgets, conditional fields, defaults -----------------------------------


def test_multi_value_controls(open_fixture):
    page = open_fixture("rfi_widgets.html")
    src = {"certifications": ["ISO 27001", "PCI DSS"], "operating_regions": ["APAC", "Americas"]}
    result = run_form(page, src)
    got = {i.plan.question: i for i in result.items}
    assert got["Certifications held"].verified and got["Operating regions"].verified
    assert page.is_checked("input[value=iso27001]") and not page.is_checked("input[value=soc2]")
    assert page.eval_on_selector("#regions", "e => Array.from(e.selectedOptions).map(o => o.value)") == ["apac", "amer"]


def test_iframe_control_is_filled(open_fixture):
    page = open_fixture("rfi_widgets.html")
    page.frame_locator("#fr").locator("#fe").wait_for()
    result = run_form(page, {"frame_email": "f@x.com"})
    item = next(i for i in result.items if i.plan.question == "Frame email")
    assert item.verified and page.frame_locator("#fr").locator("#fe").input_value() == "f@x.com"


def test_template_default_on_unresolved_control_is_flagged_not_trusted(open_fixture):
    page = open_fixture("rfi_widgets.html")
    result = run_form(page, {})
    tier = next(i for i in result.items if i.plan.question == "Preselected by the template")
    assert tier.plan.status == "REVIEW" and tier.prefilled_warning and tier.observed == "gold"


def test_pattern_violation_in_source_goes_to_review_before_touching_the_page(open_fixture):
    page = open_fixture("rfi_widgets.html")
    result = run_form(page, {"registration_code": "abc-12"})
    item = next(i for i in result.items if i.plan.question == "Registration code")
    assert item.plan.status == "REVIEW" and page.input_value("#code") == ""


def test_conditional_field_appears_after_its_trigger_is_answered(open_fixture):
    page = open_fixture("rfi_conditional.html")
    result = run_form(page, {"gdpr_applies": True, "dpo_name": "A. Rao"})
    got = {i.plan.question: i for i in result.items}
    assert got["DPO name"].verified and page.input_value("#dpo") == "A. Rao"
    assert got["Fax number"].plan.status == "REVIEW" and "disabled" in got["Fax number"].plan.reason
    assert any("stayed hidden" in w for w in result.warnings)  # "Never shown question"


def test_conditional_field_never_revealed_when_trigger_unanswered(open_fixture):
    page = open_fixture("rfi_conditional.html")
    result = run_form(page, {"dpo_name": "A. Rao"})
    assert all(i.plan.question != "DPO name" for i in result.items)
    assert page.input_value("#dpo") == ""


def test_field_vanishing_mid_run_is_a_recorded_failure_not_a_crash(open_fixture):
    page = open_fixture("rfi_basic.html")
    page.evaluate("document.getElementById('web').remove()")  # simulate dynamic page change
    result = run_form(page, BASIC_SOURCE)
    assert all(i.plan.question != "Website" for i in result.items)  # simply not in the form any more
    page2 = open_fixture("rfi_basic.html")
    # remove the element *after* discovery, before fill: patch discover to delay removal
    from formfill.web import pipeline

    real = pipeline.fill_control

    def sabotage(pg, control, answer, timeout_ms=5000):
        if control.label == "Website":
            pg.evaluate("document.getElementById('web').remove()")
        return real(pg, control, answer, 800)

    pipeline.fill_control = sabotage
    try:
        result = run_form(page2, BASIC_SOURCE, timeout_ms=800)
    finally:
        pipeline.fill_control = real
    web = next(i for i in result.items if i.plan.question == "Website")
    assert web.filled is False and "fill failed" in web.detail and result.status == "FAILED"


def test_read_back_reports_what_the_page_actually_holds(open_fixture):
    page = open_fixture("rfi_basic.html")
    ctl = next(c for c in discover(page).controls if c.label == "Number of full-time employees")
    page.fill("#ft", "-5")  # violates min=0
    obs = read_back(page, ctl)
    assert obs.value == "-5" and obs.valid is False

# ---- asynchronous readiness and empty-page safety ----------------------------


def test_pipeline_waits_for_delayed_javascript_form(page):
    page.set_content("""
        <!doctype html><html><body>
          <div id="mount"></div>
          <script>
            setTimeout(() => {
              document.querySelector("#mount").innerHTML =
                '<label for="org">Organization name</label><input id="org" name="org">';
            }, 150);
          </script>
        </body></html>
    """)

    result = run_form(page, {"company": {"name": "Delayed Corp"}}, timeout_ms=1500)

    assert len(result.items) == 1
    assert result.items[0].plan.status == "ANSWER"
    assert result.items[0].verified is True
    assert page.input_value("#org") == "Delayed Corp"
    assert result.status == "FILLED"


def test_empty_page_is_not_filled_and_is_never_submitted(page):
    page.set_content("""
        <!doctype html><html><body>
          <form id="f">
            <button type="submit">Submit</button>
          </form>
          <script>
            window.submitted = false;
            document.querySelector("#f").addEventListener("submit", event => {
              event.preventDefault();
              window.submitted = true;
            });
          </script>
        </body></html>
    """)

    result = run_form(page, {}, submit=True, readiness_timeout_ms=100)

    assert result.items == []
    assert result.status == "NEEDS_REVIEW"
    assert result.submission["attempted"] is False
    assert result.submission["outcome"] == "SKIPPED"
    assert page.evaluate("() => window.submitted") is False
    assert any("no form controls" in warning for warning in result.warnings)

def test_pipeline_readiness_detects_controls_inside_iframes(page):
    page.set_content("""
        <!doctype html><html><body>
          <iframe title="embedded form" srcdoc="
            <label for='email'>Security contact email</label>
            <input id='email' type='email'>
          "></iframe>
        </body></html>
    """)

    result = run_form(
        page,
        {"security": {"contact": {"email": "sec@example.test"}}},
        timeout_ms=1500,
    )

    assert len(result.items) == 1
    assert result.items[0].verified is True
    assert page.frames[1].locator("#email").input_value() == "sec@example.test"
    assert result.status == "FILLED"



# ---- regression: a value wiped shortly after the read-back must not be reported as FILLED (confirmed bug) ----------
# late_reset.html re-renders its control 500 ms after the first input event. Before the confirmation window existed the
# only read-back ran within milliseconds of filling, so the run said FILLED/verified while the field was empty.

SOURCE_VENDOR = {"company": {"name": "Acme Robotics Ltd"}}


def _late_reset(page, mode):
    from pathlib import Path

    page.goto((Path(__file__).parent / "fixtures" / "late_reset.html").as_uri() + f"?mode={mode}")
    return page


@pytest.mark.parametrize("mode", ["reset", "replace"])
def test_value_wiped_after_fill_is_reported_failed_not_filled(page, mode):
    _late_reset(page, mode)
    result = run_form(page, SOURCE_VENDOR)
    item = result.items[0]
    assert item.plan.status == "ANSWER" and item.filled is True
    assert item.verified is False and item.observed == ""
    assert result.status == "FAILED"


def test_stable_page_is_still_filled(page):
    _late_reset(page, "none")
    result = run_form(page, SOURCE_VENDOR)
    assert result.items[0].verified is True and result.status == "FILLED"


def test_reset_blocks_submission(page):
    _late_reset(page, "reset")
    result = run_form(page, SOURCE_VENDOR, submit=True)
    assert result.status == "FAILED"
    assert result.submission["attempted"] is False and result.submission["outcome"] == "SKIPPED"


def test_confirmation_window_can_be_disabled_and_is_bounded(page):
    _late_reset(page, "reset")
    assert run_form(page, SOURCE_VENDOR, confirm_ms=0).status == "FILLED"  # documents the old single-instant behaviour
    with pytest.raises(ValueError):
        run_form(page, SOURCE_VENDOR, confirm_ms=-1)
    with pytest.raises(ValueError):
        run_form(page, SOURCE_VENDOR, confirm_ms=60_000)


def test_pipeline_waits_for_iframe_form_that_appears_late(page):
    page.set_content("""
        <!doctype html><html><body><script>
          setTimeout(() => {
            const f = document.createElement("iframe");
            f.srcdoc = "<label for='email'>Security contact email</label><input id='email' type='email'>";
            document.body.append(f);
          }, 300);
        </script></body></html>
    """)
    result = run_form(page, {"security": {"contact": {"email": "sec@example.test"}}}, timeout_ms=1500)
    assert len(result.items) == 1 and result.items[0].verified is True
    assert page.frames[1].locator("#email").input_value() == "sec@example.test"
    assert result.status == "FILLED"


def test_form_with_no_supported_answer_is_review_and_nothing_is_typed(page):
    page.set_content("<body><label for='x'>Blood type of the chief executive</label><input id='x'></body>")
    result = run_form(page, {"company": {"name": "Acme Robotics Ltd"}}, submit=True)
    assert result.status == "NEEDS_REVIEW"
    assert [i.plan.status for i in result.items] == ["REVIEW"]
    assert page.input_value("#x") == ""
    assert result.submission.get("attempted") is not True


def test_form_that_renders_after_the_readiness_timeout_is_never_filled(page):
    page.set_content("<body><div id='m'></div><script>setTimeout(() => { m.innerHTML = "
                     "'<label for=a>Company website</label><input id=a>'; }, 1500)</script></body>")
    result = run_form(page, {"company": {"website": "https://acme.example"}}, readiness_timeout_ms=300, submit=True)
    assert result.items == [] and result.status == "NEEDS_REVIEW"
    assert result.submission["attempted"] is False
    assert any("no form controls" in w for w in result.warnings)
