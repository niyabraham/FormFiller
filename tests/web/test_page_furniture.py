"""RW-2 (REAL_WORLD_TESTING_REPORT.md): a page's own search / filter box is not a question.

Found on SurveyJS's documentation site: `<input id="sidebar-search" type="text" placeholder="Type to filter the list...">` inside an
`<aside>`, outside any form, was discovered as a question and typed with "Type II" (from `soc2.type`) on three demo pages.

Discovery now treats a control as page furniture, not a question, when it sits in a navigation landmark (nav, header, footer, aside,
or role search / navigation / banner / contentinfo / complementary), is outside any <form> / role=form, and is either a search-type
box or the only fillable control in that landmark. The last two conditions protect a real questionnaire placed in a side panel or a
header: it has a form element or several controls, and is still asked.
"""

from __future__ import annotations

import pytest

from formfill.web.discover import discover
from formfill.web.pipeline import run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

SOURCE = {"company": {"legal_name": "Fictional Vendor LLC"}, "soc2": {"type": "Type II"}, "security": {"ciso_email": "ciso@vendor.example"}}

MAIN = '<main><h1>Vendor registration</h1><label>Legal company name <input id="legal"></label></main>'


def page_with(html: str):
    return f"<!doctype html><html><body>{html}</body></html>"


def asked(page) -> list[str]:
    return [c.label for c in discover(page).controls if c.visible]


FURNITURE = {
    "lone text box in an aside (the SurveyJS case)": '<aside><div><input id="sidebar-search" type="text" placeholder="Type to filter the list..."></div></aside>' + MAIN,
    "search box in a header": '<header><input type="search" placeholder="Search"></header>' + MAIN,
    "lone text box in a nav": '<nav><input id="q" placeholder="Find a page"></nav>' + MAIN,
    "lone text box in a footer": '<footer><input id="news" placeholder="Newsletter"></footer>' + MAIN,
    "box inside role=search": '<div role="search"><input id="s" placeholder="Search the site"></div>' + MAIN,
    "role=complementary lone box": '<div role="complementary"><input id="c" placeholder="Filter"></div>' + MAIN,
}


@pytest.mark.parametrize("name", list(FURNITURE))
def test_a_page_furniture_input_is_not_asked_and_never_typed_into(page, name):
    page.set_content(page_with(FURNITURE[name]))
    assert asked(page) == ["Legal company name"], name
    result = run_form(page, SOURCE, confirm_ms=0)
    assert page.input_value("#legal") == "Fictional Vendor LLC"
    for el in page.query_selector_all("aside input, header input, nav input, footer input, [role=search] input, [role=complementary] input"):
        assert el.input_value() == "", f"{name}: the furniture input was typed into"
    assert [i.plan.question for i in result.items] == ["Legal company name"]


def test_a_search_type_box_is_excluded_even_next_to_another_control(page):
    """The lone-control condition is for plain text boxes; a type=search box is a search box wherever it is in a landmark. Its
    neighbour is not claimed to be furniture (it is not alone), so it is still asked."""
    page.set_content(page_with('<aside><input id="srch" type="search" placeholder="Search"><input id="other" placeholder="Other"></aside>' + MAIN))
    labels = asked(page)
    assert "Search" not in labels and "Legal company name" in labels and "Other" in labels


def test_the_same_holds_in_a_multi_step_walk(page):
    page.set_content(page_with(FURNITURE["lone text box in an aside (the SurveyJS case)"]))
    result = run_form(page, SOURCE, policy=DiscoveryPolicy(), confirm_ms=0)
    assert [i.plan.question for i in result.items] == ["Legal company name"]
    assert page.input_value("#sidebar-search") == ""


# ---- a real questionnaire in a landmark is still asked ---------------------------------------------------------------------------------


REAL = {
    "form element inside an aside": '<aside><form><label>Legal company name <input id="legal"></label></form></aside>',
    "role=form inside an aside": '<aside><div role="form"><label>Legal company name <input id="legal"></label></div></aside>',
    "several controls in an aside, no form element": '<aside><label>Legal company name <input id="legal"></label><label>Website <input id="web"></label></aside>',
    "several controls in a header": '<header><label>Legal company name <input id="legal"></label><label>Website <input id="web"></label></header>',
    "lone control in main": MAIN,
    "lone control in a header that belongs to a section (not the page header)": '<section><header><label>Legal company name <input id="legal"></label></header></section>',
    "lone control in a footer that belongs to an article": '<article><footer><label>Legal company name <input id="legal"></label></footer></article>',
    "lone control in a section": '<section><label>Legal company name <input id="legal"></label></section>',
}


@pytest.mark.parametrize("name", list(REAL))
def test_a_real_questionnaire_in_or_outside_a_landmark_is_still_asked(page, name):
    page.set_content(page_with(REAL[name]))
    assert "Legal company name" in asked(page), name
    run_form(page, SOURCE, confirm_ms=0)
    assert page.input_value("#legal") == "Fictional Vendor LLC"
