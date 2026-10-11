"""Phase 3B-A regression tests: deterministic safety hardening.

The four patterns behind the six unsafe answers measured on the held-out set
(docs/HELDOUT_EVALUATION.md, section 3). Each has negative examples (must be REVIEW,
carrying no answer) and positive twins (the source *does* hold the value: must be
answered, with the value asserted, so a blanket "send everything to REVIEW" fix fails).

  1. unexplained modifier   "Sales headcount", "Number of refrigerated trailers",
                            "Number of recruiters who are certified"
  2. temporal scope         "two financial years ago" vs "last financial year"
  3. negation vocabulary    "lack", "lack of" -- sent to REVIEW, never inverted
  4. placeholder values     "None", "N/A", "TBD" are not answers
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.tokens import period_markers, tokenize
from formfill.web.understand import understand_control

YN = [Option("yes", "Yes"), Option("no", "No")]


def ask(label, source, kind="text", section="", options=None):
    control = Control(control_id="c1", kind=kind, label=label, section=section, options=options or [])
    return plan_question(understand_control(control), index_source(source))


def assert_answer(item, value, source=None):
    assert item.status == "ANSWER", (item.reason, item.alternatives)
    assert item.answer == value
    if source:
        assert item.source == source


def assert_review(item):
    assert item.status == "REVIEW" and item.answer is None, (item.status, item.answer, item.source)


# --------------------------------------------------------------------------
# 1. missing critical modifiers  (held-out unsafe #1, #5, #6)
# --------------------------------------------------------------------------
class TestUnexplainedModifier:
    # the three observed cases, with the data shape of the held-out forms
    def test_sales_headcount_is_not_the_total_headcount(self):  # unsafe #1
        assert_review(ask("Sales headcount", {"Number of employees": 86}, "number"))

    def test_refrigerated_trailers_is_not_all_trailers(self):  # unsafe #5
        assert_review(ask("Number of refrigerated trailers", {"carrier": {"fleet": {"trailers": 640}}}, "number"))

    def test_certified_recruiters_is_not_all_recruiters(self):  # unsafe #6
        assert_review(ask("Number of recruiters who are certified", {"Headcount": {"Recruiters": 31}}, "number"))

    # positive twins: the source has the narrow value
    def test_sales_headcount_answered_when_the_source_has_sales_staff(self):
        src = {"Number of employees": 86, "Sales staff": 14}
        assert_answer(ask("Sales headcount", src, "number"), 14, "Sales staff")

    def test_refrigerated_trailers_answered_from_the_reefer_key(self):
        src = {"fleet": {"trailers": 640, "refrigerated_trailers": 120}}
        assert_answer(ask("Number of refrigerated trailers", src, "number"), 120, "fleet.refrigerated_trailers")

    def test_certified_recruiters_answered_when_the_source_has_the_count(self):
        src = {"Headcount": {"Recruiters": 31, "Certified recruiters": 12}}
        assert_answer(ask("Number of recruiters who are certified", src, "number"), 12, "Headcount.Certified recruiters")

    # the general question is untouched
    @pytest.mark.parametrize("label", ["Number of employees", "Headcount", "Total employees"])
    def test_plain_headcount_questions_still_answer_the_total(self, label):
        assert_answer(ask(label, {"Number of employees": 86}, "number"), 86)

    def test_plain_trailer_question_still_answers(self):
        assert_answer(ask("Number of trailers", {"carrier": {"fleet": {"trailers": 640}}}, "number"), 640)

    # the case that blocked a stricter rule in Phase 3A: the key carries the narrow word, the generic
    # population noun ("employees") is implied by the parent
    def test_full_time_employees_with_a_full_time_key_still_answers(self):
        assert_answer(ask("Number of full-time employees", {"company": {"full_time": 210}}, "number"), 210, "company.full_time")

    def test_key_that_explains_the_modifier_but_not_the_noun_is_not_penalised(self):
        assert_answer(ask("Number of annual employees", {"company": {"annual": 5}}, "number"), 5)

    # an unexplained generic noun is dropped only when it is generic: a different noun is not
    def test_an_unexplained_specific_noun_is_still_a_mismatch(self):
        assert_review(ask("Number of fulltime contractors", {"company": {"full_time": 210}}, "number"))

    @pytest.mark.parametrize("label", ["Number of certified recruiters", "Number of recruiters certified"])
    def test_word_order_does_not_matter(self, label):
        assert_review(ask(label, {"Headcount": {"Recruiters": 31}}, "number"))


class TestStrictnessIsLimitedToCounts:
    """Exactly-half-explained is capped only when the question counts a population. A narrower population is a
    different number; for a text/date/choice answer the same extra word is usually decoration, and capping it cost
    12 correct answers on the development set when tried for every question (see docs/PHASE3B_A_EVALUATION.md)."""

    @pytest.mark.parametrize("label", [
        "How many refrigerated trailers do you operate?",
        "No. of refrigerated trailers",
        "Total number of refrigerated trailers",
        "Refrigerated trailer headcount",
    ])
    def test_count_wordings_are_recognised(self, label):
        assert_review(ask(label, {"carrier": {"fleet": {"trailers": 640}}}, "number"))

    @pytest.mark.parametrize("label,source,expected", [
        ("Reporting currency", {"company": {"currency": "USD"}}, "USD"),
        ("Customer support contact e-mail", {"company": {"support_email": "help@acme.example"}}, "help@acme.example"),
        ("Date of last penetration test", {"pentest": {"last_date": "2025-11-10"}}, "2025-11-10"),
    ])
    def test_non_count_questions_keep_their_phase_3a_behaviour(self, label, source, expected):
        kind = "date" if label.startswith("Date") else "text"
        assert_answer(ask(label, source, kind), expected)

    def test_certifications_held_is_not_a_count(self):
        src = {"compliance": {"certifications": ["iso27001", "soc2"]}}
        opts = [Option("iso27001", "ISO 27001"), Option("soc2", "SOC 2"), Option("pci", "PCI DSS")]
        assert_answer(ask("Which certifications do you hold?", src, "checkbox_group", options=opts), ["iso27001", "soc2"])


# --------------------------------------------------------------------------
# 2. temporal scope  (held-out unsafe #3)
# --------------------------------------------------------------------------
class TestTemporalScope:
    SRC: ClassVar[dict] = {"Gross fees last financial year": 6840000, "Gross fees estimated current year": 7200000}

    def test_two_years_ago_is_not_last_year(self):  # unsafe #3
        assert_review(ask("10. Gross fees, two financial years ago (GBP)", self.SRC, "number"))

    def test_last_year_still_answers(self):
        assert_answer(ask("9. Gross fees, last financial year (GBP)", self.SRC, "number"),
                      6840000, "Gross fees last financial year")

    def test_current_year_still_answers(self):
        assert_answer(ask("11. Estimated gross fees for the current year (GBP)", self.SRC, "number"),
                      7200000, "Gross fees estimated current year")

    def test_two_years_ago_answered_when_the_source_has_it(self):
        src = {**self.SRC, "Gross fees two financial years ago": 6100000}
        assert_answer(ask("Gross fees, two financial years ago", src, "number"), 6100000, "Gross fees two financial years ago")

    def test_previous_year_equals_last_year(self):
        assert_answer(ask("Gross fees, previous financial year", self.SRC, "number"), 6840000)

    def test_one_year_ago_equals_last_year(self):
        assert_answer(ask("Gross fees one financial year ago", self.SRC, "number"), 6840000)

    def test_specific_year_must_match(self):
        src = {"Placements 2025": 1260, "Placements 2024": 1105}
        assert_answer(ask("Placements in 2024", src, "number"), 1105, "Placements 2024")
        assert_review(ask("Placements in 2023", src, "number"))

    def test_year_keyed_object_is_read_by_its_year_key(self):
        src = {"placements": {"2025": 1260, "2024": 1105}}
        assert_answer(ask("Placements 2024", src, "number"), 1105, "placements.2024")
        assert_answer(ask("Placements 2025", src, "number"), 1260, "placements.2025")
        assert_review(ask("Placements 2022", src, "number"))
        assert_review(ask("Placements 2023", src, "number"))

    def test_period_in_the_question_but_none_in_the_key_is_not_assumed(self):
        assert_review(ask("Gross fees three years ago", {"Gross fees": 7000000}, "number"))

    def test_a_question_without_a_period_is_not_penalised(self):
        assert_answer(ask("Gross fees", {"Gross fees": 7000000}, "number"), 7000000)

    def test_last_name_is_not_a_period(self):
        assert_answer(ask("Last name", {"contact": {"last_name": "Haines"}}), "Haines")
        assert period_markers("Last name") == frozenset()

    @pytest.mark.parametrize("text,expected", [
        ("Gross fees, last financial year", {"-1y"}),
        ("previous fiscal year revenue", {"-1y"}),
        ("two financial years ago", {"-2y"}),
        ("3 years ago", {"-3y"}),
        ("one year ago", {"-1y"}),
        ("current year", {"0y"}),
        ("this financial year", {"0y"}),
        ("next year forecast", {"+1y"}),
        ("last quarter", {"-1q"}),
        ("revenue 2024", {"2024"}),
        ("Gross fees last financial year", {"-1y"}),
        ("gross_fees_two_years_ago", {"-2y"}),
        ("claims in the last 5 years", frozenset()),  # a window, not a point in time: handled by wording equality
    ])
    def test_period_markers(self, text, expected):
        assert period_markers(text) == frozenset(expected)


# --------------------------------------------------------------------------
# 3. negation vocabulary  (held-out unsafe #4)
# --------------------------------------------------------------------------
class TestLackNegation:
    SRC: ClassVar[dict] = {"governance": {"whistleblower_policy": True}}

    @pytest.mark.parametrize("label", [
        "Does the organisation lack a whistleblower policy?",
        "Does the organisation lack of a whistleblower policy?",
        "Lack of a whistleblower policy",
        "Absence of a whistleblower policy",
        "Is a whistleblower policy absent?",
    ])
    def test_lack_is_reviewed_not_answered_yes(self, label):  # unsafe #4
        assert_review(ask(label, self.SRC, "radio", options=YN))

    def test_the_plain_question_still_answers_yes(self):
        assert_answer(ask("Does the organisation have a whistleblower policy?", self.SRC, "radio", options=YN), "yes")

    def test_answer_is_never_the_inverse(self):  # "no" would be the correct reading, but it is not computed
        item = ask("Does the organisation lack a whistleblower policy?", self.SRC, "radio", options=YN)
        assert item.answer not in ("yes", "no")

    def test_a_key_that_carries_the_same_negation_is_answered_as_stated(self):
        src = {"governance": {"lacks_whistleblower_policy": True}}
        assert_answer(ask("Does the organisation lack a whistleblower policy?", src, "radio", options=YN), "yes")

    def test_a_negated_key_is_not_used_for_the_plain_question(self):
        src = {"governance": {"lacks_whistleblower_policy": True}}
        assert_review(ask("Does the organisation have a whistleblower policy?", src, "radio", options=YN))

    @pytest.mark.parametrize("word", ["lack", "lacks", "lacking", "absence", "absent"])
    def test_vocabulary(self, word):
        from formfill.web.tokens import NEGATORS
        assert (set(tokenize(word)) & NEGATORS), word

    def test_words_that_merely_contain_lack_are_not_negators(self):
        from formfill.web.tokens import NEGATORS
        for word in ["black", "blackout", "slack", "placks"]:
            assert not (set(tokenize(word)) & NEGATORS), word


# --------------------------------------------------------------------------
# 4. placeholder strings  (held-out unsafe #2)
# --------------------------------------------------------------------------
class TestPlaceholderValues:
    def test_none_string_is_not_a_company_name(self):  # unsafe #2
        assert_review(ask("Parent company name", {"Parent company": "None"}))

    @pytest.mark.parametrize("value", ["None", "none", " NONE ", "N/A", "n/a", "N.A.", "Not applicable", "TBD", "tba",
                                       "Unknown", "null", "nil", "-", "--", "—", "To be determined", "None."])
    def test_placeholders(self, value):
        assert_review(ask("Parent company name", {"Parent company": value}))

    def test_review_reason_names_the_placeholder(self):
        item = ask("Parent company name", {"Parent company": "None"})
        assert "placeholder" in item.reason.lower() and "None" in item.reason

    def test_real_parent_company_is_still_answered(self):
        assert_answer(ask("Parent company name", {"Parent company": "Meridian Holdings plc"}), "Meridian Holdings plc")

    def test_a_dropdown_with_that_option_may_still_be_answered(self):
        opts = [Option("None", "None"), Option("Minor", "Minor"), Option("Major", "Major")]
        assert_answer(ask("Claims history", {"Claims history": "None"}, "select", options=opts), "None")

    def test_none_is_not_a_yes_no_answer(self):
        assert_review(ask("Is the company FDA registered?", {"Is the company FDA registered?": "None"}, "radio", options=YN))

    @pytest.mark.parametrize("value", ["Nonesuch Ltd", "Anon", "North America", "NA", "None of the Above Inc"])
    def test_values_that_merely_contain_a_placeholder_word_are_answers(self, value):
        assert_answer(ask("Parent company name", {"Parent company": value}), value)

    def test_zero_and_false_are_values_not_placeholders(self):
        assert_answer(ask("Number of warehouses", {"Number of warehouses": 0}, "number"), 0)
        assert_answer(ask("Is the company FDA registered?", {"Is the company FDA registered?": False}, "radio", options=YN), "no")
