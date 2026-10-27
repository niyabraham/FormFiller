"""Two controls whose labels differ only in a dropped parenthetical ("Dropdown (select)" / "Dropdown (datalist)") reduce to the same
tokens. Before, one source value answered both with confidence 1.0 and the run ended FILLED, so the select's "Two" was typed into
the datalist box. Reproduced on a deterministic local fixture (not a live page). Such answers now go to review."""

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

HTML = ('<form onsubmit="return false"><label>Dropdown (select) <select name=s><option>Open</option><option>One</option>'
        '<option>Two</option></select></label><label>Dropdown (datalist) <input name=d list=o>'
        '<datalist id=o><option value=Seattle><option value=Chicago></datalist></label></form>')


@pytest.mark.parametrize("src", [{"dropdown": "Two"}, {"dropdown_select": "Two", "dropdown_datalist": "Seattle"}])
def test_one_value_never_answers_two_indistinguishable_questions(page, src):
    page.set_content(HTML)
    res = run_form(page, src, confirm_ms=0)
    assert res.status == "NEEDS_REVIEW"
    assert [i.plan.status for i in res.items] == ["REVIEW", "REVIEW"]
    assert all("differ only in a parenthetical qualifier" in i.plan.reason for i in res.items)
    assert page.input_value("input[name=d]") == "" and page.input_value("select") == "Open"


def test_distinct_questions_with_one_value_each_are_still_answered(page):
    page.set_content('<form onsubmit="return false"><label>Legal name <input name=a></label><label>Website <input name=b></label></form>')
    res = run_form(page, {"company": {"legal_name": "Northwind Ltd", "website": "https://n.example"}}, confirm_ms=0)
    assert [i.plan.status for i in res.items] == ["ANSWER", "ANSWER"] and res.status == "FILLED"


def test_plain_rephrasings_of_one_fact_are_not_affected(page):
    page.set_content('<form onsubmit="return false"><label>Website <input name=a></label><label>Company website <input name=b></label></form>')
    res = run_form(page, {"website": "https://n.example"}, confirm_ms=0)
    assert [i.plan.status for i in res.items] == ["ANSWER", "ANSWER"]
