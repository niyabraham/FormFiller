"""Radios / checkboxes whose options all carry the same value (the Selenium demo's inputs have no value attribute, so every option is
"on"): the source's "Default radio" was turned into the value "on", which names no single option. The radio fill did nothing yet
verified True (it already held "on"), and the checkbox group ended with both boxes unchecked. Such answers now go to review.
Structure taken from the live Selenium result.json; the page here is a deterministic local fixture."""

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

HTML = ('<form onsubmit="return false">'
        '<div><label><input type=checkbox id=c1 name=my-check checked> Checked checkbox</label></div>'
        '<div><label><input type=checkbox id=c2 name=my-check> Default checkbox</label></div>'
        '<div><label><input type=radio id=r1 name=my-radio checked> Checked radio</label></div>'
        '<div><label><input type=radio id=r2 name=my-radio> Default radio</label></div></form>')

STATE = "()=>['c1','c2','r1','r2'].map(i=>document.getElementById(i).checked)"


@pytest.mark.parametrize("src", [{"my_radio": "Default radio"}, {"my_check": ["Default checkbox"]}, {"my_radio": "on", "my_check": ["on"]}])
def test_options_with_a_shared_value_go_to_review_and_the_page_is_untouched(page, src):
    page.set_content(HTML)
    res = run_form(page, src, confirm_ms=0)
    group = {"my_radio": "my-radio", "my_check": "my-check"}[next(iter(src))]
    item = next(i for i in res.items if i.plan.question == group)
    assert item.plan.status == "REVIEW" and "share the value" in item.plan.reason
    assert res.status == "NEEDS_REVIEW" and page.evaluate(STATE) == [True, False, True, False]


def test_options_with_distinct_values_are_still_selected(page):
    page.set_content('<form onsubmit="return false"><label><input type=radio name=size value=s> Small</label>'
                     '<label><input type=radio name=size value=l> Large</label></form>')
    res = run_form(page, {"size": "Large"}, confirm_ms=0)
    assert res.items[0].plan.status == "ANSWER" and res.items[0].verified is True
    assert page.evaluate("()=>document.querySelector('input[value=l]').checked") is True


def test_review_alternatives_keep_the_other_candidates(page):
    page.set_content('<form onsubmit="return false"><label>Dropdown (select) <select name=s><option>Open</option><option>Two</option></select></label>'
                     '<label>Dropdown (datalist) <input name=d list=o><datalist id=o><option value=Seattle></datalist></label></form>')
    res = run_form(page, {"dropdown_select": "Two", "dropdown_datalist": "Seattle"}, confirm_ms=0)
    datalist = next(i for i in res.items if "datalist" in i.plan.question)
    assert datalist.plan.status == "REVIEW" and "Seattle" in [a["value"] for a in datalist.plan.alternatives]
