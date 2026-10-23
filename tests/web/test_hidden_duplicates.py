"""Browser tests: controls the page marks aria-hidden="true" or inert are not questions.

Found on a public template page: a scaled, aria-hidden, disabled thumbnail of the form (a "duplicate" Vendor / company name
field), plus an sr-only aria-hidden checkbox that is the site's menu toggle (discovered as the question "hf-mobile-menu").
Neither was written to (disabled / no value), but each became a REVIEW item, three of them marked required.

The rule is in discover.py: such a control is reported with visible=False, which the pipeline already counts as
"stayed hidden" and never asks. Fixture: fixtures/rfi_hidden_duplicates.html (fictional; local file, no network).
"""

import pytest

from formfill.web.discover import discover
from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

SOURCE = {
    "company": {"name": "Acme Corp", "website_url": "https://acme.example"},
    "security": {"contact": {"email": "sec@acme.example"}},
    "privacy": {"processes_personal_data": True, "dpo_name": "A. Rao", "retention_period": "24 months"},
}

REAL = {"vendor", "first", "last", "sec-email", "web", "dpo", "retention"}  # html ids of the real questions (+ the radio, by name)
HIDDEN_BY_PAGE = {"site-menu", "t-vendor", "t-product", "t-email", "preview-vendor", "promo-email", "hp"}


def visibility(page):
    return {(c.html_id or c.name): c.visible for c in discover(page).controls}


# ---- discovery -----------------------------------------------------------------


def test_aria_hidden_and_inert_controls_are_not_visible(open_fixture):
    vis = visibility(open_fixture("rfi_hidden_duplicates.html"))
    for hidden in HIDDEN_BY_PAGE:
        assert vis[hidden] is False, hidden
    # the real form, and a control under an explicit aria-hidden="false", are ordinary visible controls
    for real in ("vendor", "first", "last", "sec-email", "web", "pd"):
        assert vis[real] is True, real


def test_it_is_aria_hidden_not_disabled_that_hides_a_control(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    controls = {(c.html_id or c.name): c for c in discover(page).controls}
    assert controls["preview-vendor"].disabled is False and controls["preview-vendor"].visible is False  # enabled, aria-hidden
    assert controls["promo-email"].disabled is False and controls["promo-email"].visible is False  # enabled, inert
    assert controls["t-vendor"].disabled is True and controls["t-vendor"].visible is False  # the thumbnail: both


def test_toggling_aria_hidden_and_inert_toggles_discovery(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    page.evaluate("document.getElementById('web').parentElement.setAttribute('aria-hidden', 'true')")
    assert visibility(page)["web"] is False
    page.evaluate("document.getElementById('web').parentElement.setAttribute('aria-hidden', 'false')")
    assert visibility(page)["web"] is True
    page.evaluate("document.getElementById('web').parentElement.setAttribute('inert', '')")
    assert visibility(page)["web"] is False
    page.evaluate("document.getElementById('web').parentElement.removeAttribute('inert')")
    assert visibility(page)["web"] is True


def test_an_ancestor_far_above_the_control_hides_it(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    page.evaluate("document.getElementById('try-it').setAttribute('aria-hidden', 'true')")
    vis = visibility(page)
    assert vis["vendor"] is False and vis["sec-email"] is False  # whole subtree


def test_control_in_an_open_shadow_root_follows_its_hosts_ancestors(page):
    page.set_content("""
      <div id="ok"></div>
      <div aria-hidden="true"><div id="hid"></div></div>
      <script>
        for (const id of ['ok', 'hid']) {
          const root = document.getElementById(id).attachShadow({mode: 'open'});
          root.innerHTML = '<label for="x">Shadow ' + id + '</label><input id="x" name="s_' + id + '">';
        }
      </script>""")
    vis = {c.name: c.visible for c in discover(page).controls}
    assert vis == {"s_ok": True, "s_hid": False}


def test_a_display_none_control_is_still_hidden_and_a_disabled_visible_one_is_still_visible(open_fixture):
    # unchanged behaviour: rfi_conditional has a `hidden` question and a visible disabled one
    page = open_fixture("rfi_conditional.html")
    vis = visibility(page)
    assert vis["x"] is False and vis["fax"] is True


# ---- end to end -------------------------------------------------------------------


def test_only_the_real_form_is_asked_and_nothing_hidden_is_touched(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    result = run_form(page, SOURCE)
    asked = {i.plan.question for i in result.items}
    assert "hf-mobile-menu" not in asked and "site-menu" not in asked
    assert "Preview vendor name" not in asked and "Promo signup email" not in asked
    assert not [i for i in result.items if i.plan.reason == "control is disabled"]  # the thumbnail produced these
    assert [i.plan.question for i in result.items].count("Vendor / company name") == 1  # no duplicate vendor question

    for hidden in ("t-vendor", "t-product", "t-email", "preview-vendor", "promo-email", "hp"):
        assert page.input_value(f"#{hidden}") == "", hidden
    assert not page.is_checked("#site-menu")
    assert any("7 control(s) stayed hidden" in w for w in result.warnings)


def test_real_answers_are_filled_and_verified(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    result = run_form(page, SOURCE)
    assert page.input_value("#vendor") == "Acme Corp"
    assert page.input_value("#sec-email") == "sec@acme.example"
    assert page.input_value("#web") == "https://acme.example"  # aria-hidden="false" wrapper
    assert page.is_checked("input[name=pd][value=yes]")
    answered = [i for i in result.items if i.plan.status == "ANSWER"]
    assert answered and all(i.verified for i in answered)


def test_legitimate_conditional_reveals_still_work(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    vis = visibility(page)
    assert vis["dpo"] is False and vis["retention"] is False  # not asked while hidden
    result = run_form(page, SOURCE)
    got = {i.plan.question: i for i in result.items}
    assert got["DPO name"].verified and page.input_value("#dpo") == "A. Rao"  # revealed by `hidden`
    assert got["Data retention period"].verified and page.input_value("#retention") == "24 months"  # revealed by aria-hidden flipping


def test_conditional_reveal_not_triggered_leaves_them_hidden(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    src = {k: v for k, v in SOURCE.items() if k != "privacy"}
    result = run_form(page, src)
    assert all(i.plan.question not in ("DPO name", "Data retention period") for i in result.items)
    assert page.input_value("#dpo") == "" and page.input_value("#retention") == ""


def test_company_name_is_never_typed_into_the_name_fields(open_fixture):
    # the other half of the public-page failure, end to end: the only name in the source is the company's
    page = open_fixture("rfi_hidden_duplicates.html")
    result = run_form(page, SOURCE)
    got = {i.plan.question: i for i in result.items}
    for label, ident in (("First name", "first"), ("Last name", "last")):
        assert got[label].plan.status == "REVIEW" and got[label].plan.answer is None
        assert page.input_value(f"#{ident}") == ""
    assert got["Vendor / company name"].verified and page.input_value("#vendor") == "Acme Corp"


def test_submit_safeguards_unchanged_the_run_never_submits_by_default(open_fixture):
    page = open_fixture("rfi_hidden_duplicates.html")
    result = run_form(page, SOURCE)  # submit defaults to False
    assert result.submission == {}
