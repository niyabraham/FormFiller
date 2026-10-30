"""RW-1 (REAL_WORLD_TESTING_REPORT.md): a label that is a single word must not be answered from a longer key whose other words are
qualifiers the label does not carry.

Found on public forms: `Last` (a last-name box) was answered with a date from `security.pen_test.last_date`; `Email` was answered
with a CISO mailbox from `security.ciso_email`. Both scored 0.667 (precision 0.5, recall 1.0), just above the 0.6 answer threshold.

The cap applies only when the extra words are NOT slot words (name, size, count, exist). Those describe the kind of value and are
implied by the question: "Number of customers" answers `customer count`, "Do you have subsidiaries?" answers `subsidiaries_exist`.
The "keeps answering" tests below are the five answers a rule without that exception would have lost on the project's benchmarks.
"""

from __future__ import annotations

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control

YN = [Option("yes", "Yes"), Option("no", "No")]


def ask(label: str, source: dict, kind: str = "text"):
    c = Control(control_id="q", kind=kind, label=label, options=YN if kind in ("radio", "select") else [])
    return plan_question(understand_control(c), index_source(source))


# ---- must NOT be auto-answered ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("label,source,why", [
    ("Last", {"security": {"pen_test": {"last_date": "2026-02-17"}}}, "'last' is a modifier; `last_date` is a date, not a last name"),
    ("Email", {"security": {"ciso_email": "ciso@brightloop.io"}}, "a CISO mailbox is not 'the' e-mail address"),
    ("Phone", {"security": {"incident_contact_phone": "+1 512 555 0147"}}, "an incident line is not 'the' phone number"),
    ("Contact", {"security": {"incident_contact_phone": "+1 512 555 0147"}}, "'contact' alone does not say which contact detail"),
])
def test_a_one_word_label_is_not_answered_from_a_key_with_an_unexplained_qualifier(label, source, why):
    plan = plan_question(understand_control(Control(control_id="q", kind="text", label=label)), index_source(source))
    assert plan.status == "REVIEW", f"{label!r} was answered ({plan.answer!r} from {plan.source}): {why}"
    assert plan.answer is None
    assert "explains only part of the key" in (plan.reason or "")  # the reviewer is told why, not just 'too weak'


def test_the_reviewer_still_sees_the_candidate_as_a_proposal():
    plan = ask("Email", {"security": {"ciso_email": "ciso@brightloop.io"}})
    assert plan.status == "REVIEW"
    assert any(a["source"] == "security.ciso_email" for a in plan.alternatives) or plan.proposed_answer == "ciso@brightloop.io"


# ---- must KEEP answering ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("label,source,kind,expected", [
    # the five benchmark answers a rule without the slot-word exception would have lost
    ("Total staff headcount", {"company": {"workforce_size": 250}}, "number", 250),
    ("Number of personnel", {"company": {"workforce_size": 250}}, "number", 250),
    ("Do you have subsidiaries?", {"company": {"subsidiaries_exist": False}}, "radio", "no"),
    ("Who is your Data Protection Officer?", {"privacy": {"dpo_name": "A. Rao"}}, "text", "A. Rao"),
    ("Number of customers", {"Product": {"Customer count": 1850}}, "number", 1850),
    # one-word labels with an exact key, and with a key whose extra words are stripped or implied
    ("Email", {"contact": {"email": "ops@acme.example"}}, "text", "ops@acme.example"),
    ("Website", {"company": {"website": "https://acme.example"}}, "text", "https://acme.example"),
    ("Website", {"company": {"website_url": "https://acme.example"}}, "text", "https://acme.example"),
    ("Phone", {"contact": {"phone_number": "+44 20 7946 0000"}}, "text", "+44 20 7946 0000"),
    ("City", {"company": {"hq": {"city": "Austin"}}}, "text", "Austin"),
])
def test_a_one_word_label_is_still_answered_when_the_extra_key_words_only_say_what_kind_of_value_it_is(label, source, kind, expected):
    plan = ask(label, source, kind)
    assert plan.status == "ANSWER", f"{label!r} -> {plan.reason}"
    assert plan.answer == expected or str(plan.answer).casefold() == str(expected).casefold()


def test_with_both_a_name_and_an_email_key_the_question_asking_who_is_answered_with_the_name():
    """Today this is reviewed as an ambiguity between `dpo_name` and `dpo_email`. `name` is a slot word, `email` is a different kind of
    value, so after the cap `dpo_email` can no longer compete for a question that asks who the officer is."""
    plan = ask("Who is your Data Protection Officer?", {"privacy": {"dpo_name": "A. Rao", "dpo_email": "dpo@acme.example"}})
    assert plan.status == "ANSWER" and plan.answer == "A. Rao"
