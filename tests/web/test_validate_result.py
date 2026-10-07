"""Deterministic validation and result-status logic (no browser)."""

import pytest

from formfill.web.models import AnswerPlanItem, Control, Option
from formfill.web.result import ItemResult, overall_status
from formfill.web.validate import validate_answer


def c(kind, **kw):
    return Control(control_id="c1", kind=kind, label="L", **kw)


@pytest.mark.parametrize("value,ok,expected", [
    (250, True, 250), ("1,200", True, 1200), (3.0, True, 3), (3.5, False, None),
    ("many", False, None), (True, False, None), (-1, False, None),
])
def test_number(value, ok, expected):
    r = validate_answer(value, c("number", min="0"))
    assert r.ok is ok and (not ok or r.value == expected)


def test_number_max_and_step():
    assert not validate_answer(11, c("number", max="10")).ok
    assert validate_answer(2.5, c("number", step="any")).ok


def test_date_iso_only_and_range():
    assert validate_answer("2009-03-14", c("date")).value == "2009-03-14"
    assert not validate_answer("14/03/2009", c("date")).ok
    assert not validate_answer("2030-01-01", c("date", max="2026-12-31")).ok


def test_email_and_url():
    assert validate_answer("a@b.co", c("email")).ok and not validate_answer("a@b", c("email")).ok
    assert validate_answer("https://x.com", c("url")).ok and not validate_answer("x.com", c("url")).ok


def test_text_constraints_never_truncate():
    assert not validate_answer("x" * 21, c("text", maxlength=20)).ok
    assert not validate_answer("abc-12", c("text", pattern="[A-Z]{3}-[0-9]{4}")).ok
    assert validate_answer("ABC-1234", c("text", pattern="[A-Z]{3}-[0-9]{4}")).ok


def test_empty_and_structured_values_rejected():
    assert not validate_answer("  ", c("text")).ok
    assert not validate_answer(None, c("text")).ok
    assert not validate_answer({"a": 1}, c("text")).ok


def test_choice_matches_value_or_label_case_insensitively():
    ctl = c("select", options=[Option("IN", "India")])
    assert validate_answer("india", ctl).value == "IN" and validate_answer("in", ctl).value == "IN"
    assert not validate_answer("Nepal", ctl).ok


def test_multi_choice_requires_every_item_valid():
    ctl = c("checkbox_group", options=[Option("iso", "ISO 27001"), Option("soc2", "SOC 2")])
    assert validate_answer(["ISO 27001", "soc2"], ctl).value == ["iso", "soc2"]
    assert not validate_answer(["ISO 27001", "HIPAA"], ctl).ok


def test_checkbox_boolean():
    assert validate_answer("yes", c("checkbox")).value is True
    assert validate_answer(False, c("checkbox")).value is False
    assert not validate_answer("maybe", c("checkbox")).ok


# ---- result status ------------------------------------------------------------


def item(status, filled=False, verified=None):
    p = AnswerPlanItem("q", "Q", "text", True, status)
    return ItemResult(plan=p, filled=filled, verified=verified)


def test_status_matrix():
    ok = item("ANSWER", True, True)
    assert overall_status([ok], None) == "FILLED"
    assert overall_status([ok, item("REVIEW")], None) == "NEEDS_REVIEW"
    assert overall_status([item("ANSWER", False)], None) == "FAILED"
    assert overall_status([item("ANSWER", True, False)], None) == "FAILED"
    assert overall_status([ok], {"outcome": "CONFIRMED"}) == "SUBMITTED"
    assert overall_status([ok], {"outcome": "UNCONFIRMED"}) == "SUBMITTED_UNCONFIRMED"
    assert overall_status([ok], {"outcome": "BLOCKED_BY_VALIDATION"}) == "FAILED"
    assert overall_status([ok, item("REVIEW")], {"outcome": "SKIPPED"}) == "NEEDS_REVIEW"
