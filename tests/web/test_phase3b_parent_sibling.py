"""Phase 3B-B regression tests: parent- and sibling-aware retrieval.

The same field name often appears under several parents (`franchisor.year_founded` /
`franchisee.year_founded`) or in several list items (`terminals.0.doors` / `terminals.1.doors`).
Context is used only as *evidence that the question names one of them*:

  * path evidence    -- the question (or the form section it sits in) names a parent that only one
                        candidate has ("franchisor", "cargo", "billing");
  * item evidence    -- the question contains the literal value of a sibling field of one list item
                        ("Omaha" -> the terminal whose `city` is Omaha, "CEO" -> the leader whose `role` is CEO);
  * ancestor evidence -- the question names an entity and the candidate is that entity's own field, not a
                        deeper collection under it.

Context never raises a score and never decides alone: it lowers the *rivals* of a candidate the question
names, so a candidate that was too weak before is still REVIEW. When the question does not name an entity,
or names several, nothing changes and the item stays REVIEW. Positive tests assert the value; REVIEW tests
assert that no answer is carried.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from formfill.web import retrieve as R
from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source, retrieve
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


FRANCHISE = {"franchisor": {"name": "Brasa Grill Franchising LLC", "year_founded": 2005},
             "franchisee": {"name": "Alvarado Hospitality Group LLC", "year_founded": 2013}}
GROUP = {"company": {"employees": 250}, "parent_company": {"employees": 9000}, "subsidiary": {"employees": 80}}


# --------------------------------------------------------------------------
# A. the question names one entity (path evidence)
# --------------------------------------------------------------------------
class TestQuestionNamesTheEntity:
    def test_franchisor_year(self):
        assert_answer(ask("Year the franchisor was founded", FRANCHISE, "number"), 2005, "franchisor.year_founded")

    def test_franchisee_year(self):
        assert_answer(ask("Year the franchisee was founded", FRANCHISE, "number"), 2013, "franchisee.year_founded")

    @pytest.mark.parametrize("label,expected", [
        ("Number of employees of the parent company", 9000),
        ("Number of employees of the subsidiary", 80),
    ])
    def test_company_parent_subsidiary(self, label, expected):
        assert_answer(ask(label, GROUP, "number"), expected)

    def test_department(self):
        src = {"departments": {"engineering": {"employees": 120}, "sales": {"employees": 40}}}
        assert_answer(ask("Number of employees in the sales department", src, "number"), 40,
                      "departments.sales.employees")
        assert_answer(ask("Number of employees in the engineering department", src, "number"), 120)

    def test_two_leaf_parents_that_share_a_word_are_told_apart_by_the_other_word(self):
        src = {"insurance": {"employers_liability": {"limit": 10000000}, "public_liability": {"limit": 5000000}}}
        assert_answer(ask("Employers' liability insurance limit (GBP)", src, "number"), 10000000)
        assert_answer(ask("Public liability insurance limit (GBP)", src, "number"), 5000000)

    def test_cargo_vs_auto_liability(self):
        src = {"carrier": {"insurance": {"cargo": {"limit": 250000}, "autoLiability": {"limit": 1000000}}}}
        assert_answer(ask("Cargo insurance limit (USD)", src, "number"), 250000, "carrier.insurance.cargo.limit")

    def test_the_winner_is_not_always_the_first_or_highest_listed_parent(self):
        # the later key wins when it is the one that is named
        src = {"alpha": {"year_founded": 1999}, "omega": {"year_founded": 2020}}
        assert_answer(ask("Year omega was founded", src, "number"), 2020)
        assert_answer(ask("Year alpha was founded", src, "number"), 1999)


# --------------------------------------------------------------------------
# B. the entity stays ambiguous -> REVIEW (hierarchy alone never decides)
# --------------------------------------------------------------------------
class TestEntityStaysAmbiguous:
    def test_no_entity_named(self):
        assert_review(ask("Year founded", FRANCHISE, "number"))

    def test_no_entity_named_even_with_three_parents(self):
        assert_review(ask("Number of employees", GROUP, "number"))

    def test_both_entities_named(self):
        assert_review(ask("Year the franchisor and the franchisee were founded", FRANCHISE, "number"))

    def test_an_unrelated_entity_word_does_not_pick_one(self):
        assert_review(ask("Year the joint venture was founded", FRANCHISE, "number"))

    def test_the_filers_own_entity_is_not_assumed(self):
        # "company"/"organisation" is self-reference, not a named entity: unchanged from Phase 3A
        src = {"supplier": {"company_number": "07894213"}, "parent": {"company_number": "05512004"}}
        assert_review(ask("Companies House registration number", src))

    def test_ein_of_the_organisation_vs_an_affiliate_is_not_decided_by_hierarchy(self):
        src = {"org": {"ein": "46-3381920"}, "affiliates": {"chapters": [{"ein": "46-3381920-1"}]}}
        assert_review(ask("Employer Identification Number (EIN)", src))

    @pytest.mark.xfail(strict=True, reason="disputed label: company vs subsidiary employees, left to REVIEW policy; see Phase 3A")
    def test_organisation_employees_with_a_subsidiary_present_is_review(self):
        assert_review(ask("How many employees does the organization have?",
                          {"company": {"employees": 250}, "subsidiary": {"employees": 80}}, "number"))


# --------------------------------------------------------------------------
# C. the form section names the entity
# --------------------------------------------------------------------------
class TestSectionEvidence:
    ADDR: ClassVar[dict] = {"address": {"hq": {"street": "12 MG Road"}, "billing": {"street": "PO Box 44"}}}

    def test_headquarters_section(self):
        assert_answer(ask("Street", self.ADDR, section="Headquarters address"), "12 MG Road", "address.hq.street")

    def test_billing_section(self):
        assert_answer(ask("Street", self.ADDR, section="Billing address"), "PO Box 44", "address.billing.street")

    def test_a_section_that_names_no_entity_decides_nothing(self):
        assert_review(ask("Street", self.ADDR, section="Company"))

    def test_the_questions_own_words_outrank_the_section_heading(self):
        # both entities are named (one by the label, one by the heading): no rival is set aside and the
        # Phase 3A score decides; the label is the more specific statement
        assert_answer(ask("Billing street", self.ADDR, section="Headquarters address"), "PO Box 44")

    def test_question_naming_the_entity_agrees_with_the_section(self):
        assert_answer(ask("Billing street", self.ADDR, section="Billing address"), "PO Box 44")


# --------------------------------------------------------------------------
# D. repeated list items distinguished by a sibling value (item evidence)
# --------------------------------------------------------------------------
class TestSiblingValues:
    TERMINALS: ClassVar[dict] = {"carrier": {"terminals": [{"city": "Omaha", "state": "NE", "doors": 48},
                                           {"city": "Kansas City", "state": "MO", "doors": 30}]}}
    LEADERS: ClassVar[dict] = {"leadership": [{"role": "CEO", "name": "Ravi Menon", "email": "ravi@acme.example"},
                              {"role": "CISO", "name": "Priya Nair", "email": "priya@acme.example"}]}
    STORES: ClassVar[dict] = {"franchisee": {"employees": 310, "locations": [
        {"store_no": "114", "city": "San Antonio", "employees": 42, "opened": "2018-05-07"},
        {"store_no": "131", "city": "Austin", "employees": 38, "opened": "2020-11-16"}]}}

    def test_terminal_by_city(self):
        assert_answer(ask("Number of dock doors at the Omaha terminal", self.TERMINALS, "number"), 48,
                      "carrier.terminals.0.doors")
        assert_answer(ask("Number of dock doors at the Kansas City terminal", self.TERMINALS, "number"), 30,
                      "carrier.terminals.1.doors")

    def test_leader_by_role(self):
        assert_answer(ask("CEO email", self.LEADERS), "ravi@acme.example")
        assert_answer(ask("CISO name", self.LEADERS), "Priya Nair")

    def test_store_by_number_and_by_city(self):
        assert_answer(ask("Date store 114 opened", self.STORES, "date"), "2018-05-07")
        assert_answer(ask("Employees at store #131", self.STORES, "number"), 38)
        assert_answer(ask("Number of employees at the San Antonio store", self.STORES, "number"), 42)

    def test_no_sibling_value_in_the_question(self):
        assert_review(ask("Number of dock doors", self.TERMINALS, "number"))

    def test_a_value_that_matches_no_item_decides_nothing(self):
        assert_review(ask("Number of dock doors at the Denver terminal", self.TERMINALS, "number"))

    def test_a_role_nobody_has(self):
        assert_review(ask("CTO email", self.LEADERS))

    def test_both_items_named(self):
        assert_review(ask("Number of dock doors at Omaha and Kansas City", self.TERMINALS, "number"))

    def test_a_sibling_word_that_is_a_substring_of_another_value_is_not_enough(self):
        src = {"offices": [{"city": "New York", "staff": 30}, {"city": "York", "staff": 5}]}
        assert_answer(ask("Staff in the York office", src, "number"), 5)
        assert_review(ask("Staff in the Leeds office", src, "number"))

    def test_numeric_sibling_values_are_not_used(self):
        # store numbers stored as JSON integers carry no word: a limitation, left to REVIEW
        src = {"stores": [{"store_no": 114, "employees": 42}, {"store_no": 131, "employees": 38}]}
        assert_review(ask("Employees at store 114", src, "number"))

    def test_single_item_list(self):
        src = {"branch_offices": [{"city": "Newark", "staff": 11}]}
        assert_answer(ask("Staff at the Newark branch", src, "number"), 11)

    def test_total_still_ambiguous_with_branches(self):
        src = {"Headcount": {"Total internal staff": 74}, "Branch offices": [{"city": "Newark", "staff": 11}, {"city": "Albany", "staff": 8}]}
        assert_review(ask("Total number of personnel", src, "number"))


# --------------------------------------------------------------------------
# E. entity-level field vs the same field in a collection under it (ancestor evidence)
# --------------------------------------------------------------------------
class TestAncestorEvidence:
    SRC = TestSiblingValues.STORES

    def test_employees_of_the_entity_are_not_a_stores_employees(self):
        assert_answer(ask("Number of employees of the franchisee", self.SRC, "number"), 310, "franchisee.employees")

    def test_unnamed_entity_stays_ambiguous(self):
        assert_review(ask("Number of employees", self.SRC, "number"))

    def test_item_evidence_beats_the_entity_when_the_item_is_named(self):
        assert_answer(ask("Number of employees of the franchisee at store 131", self.SRC, "number"), 38)


# --------------------------------------------------------------------------
# F. Phase 3B-A safety is preserved inside these contexts
# --------------------------------------------------------------------------
class TestSafetyRulesStillApply:
    def test_qualifier(self):
        assert_review(ask("Number of production employees of the franchisee", TestSiblingValues.STORES, "number"))

    def test_counting_modifier_on_a_named_entity(self):
        src = {"franchisor": {"trailers": 85}, "franchisee": {"trailers": 310}}
        assert_answer(ask("Number of trailers of the franchisor", src, "number"), 85)
        assert_review(ask("Number of refrigerated trailers of the franchisor", src, "number"))

    def test_period(self):
        src = {"franchisor": {"revenue_last_year": 5}, "franchisee": {"revenue_last_year": 9}}
        assert_answer(ask("Franchisor revenue, last year", src, "number"), 5)
        assert_review(ask("Franchisor revenue, two years ago", src, "number"))

    def test_negation(self):
        src = {"franchisor": {"whistleblower_policy": True}, "franchisee": {"whistleblower_policy": False}}
        assert_answer(ask("Does the franchisor have a whistleblower policy?", src, "radio", options=YN), "yes")
        assert_review(ask("Does the franchisor lack a whistleblower policy?", src, "radio", options=YN))

    def test_placeholder(self):
        src = {"franchisor": {"owner": "None"}, "franchisee": {"owner": "Eduardo Alvarado"}}
        assert_review(ask("Franchisor owner", src))
        assert_answer(ask("Franchisee owner", src), "Eduardo Alvarado")


# --------------------------------------------------------------------------
# G. context never raises a score and only moves rivals
# --------------------------------------------------------------------------
class TestContextOnlyLowersRivals:
    def _cands(self, label, src):
        q = understand_control(Control(control_id="c", kind="number", label=label))
        return {c.path: c for c in retrieve(q, index_source(src))}

    def test_winner_score_is_unchanged_and_the_rival_is_lower(self, monkeypatch):
        before = {}
        monkeypatch.setattr(R, "CONTEXT_PENALTY", 1.0)
        before = self._cands("Year the franchisor was founded", FRANCHISE)
        monkeypatch.undo()
        after = self._cands("Year the franchisor was founded", FRANCHISE)
        assert after["franchisor.year_founded"].score == before["franchisor.year_founded"].score
        assert after["franchisee.year_founded"].score < before["franchisee.year_founded"].score

    def test_a_candidate_that_was_too_weak_is_not_rescued_by_a_penalised_rival(self):
        src = {"franchisor": {"turnover_note": 1}, "franchisee": {"turnover_note": 2}}
        assert_review(ask("Franchisor annual turnover note details", src, "number"))

    def test_the_penalised_rival_says_why(self):
        c = self._cands("Year the franchisor was founded", FRANCHISE)["franchisee.year_founded"]
        assert any("franchisor" in f for f in c.flags), c.flags

    def test_the_winner_records_its_evidence(self):
        c = self._cands("Year the franchisor was founded", FRANCHISE)["franchisor.year_founded"]
        assert any("franchisor" in e for e in c.evidence), c.evidence

    def test_plan_item_exposes_evidence_for_an_answer(self):
        item = ask("Year the franchisor was founded", FRANCHISE, "number")
        assert item.status == "ANSWER" and any("franchisor" in e for e in item.evidence)


# --------------------------------------------------------------------------
# H. known costs, kept visible
# --------------------------------------------------------------------------
class TestKnownCosts:
    def test_entity_words_still_dilute_a_modifier_when_no_context_was_needed(self):
        # Phase 3B-A behaviour, unchanged: a single parent names the entity and the key explains most of the words
        assert_answer(ask("Customer support personnel (headcount)", {"headcount": {"support": 57}}, "number"), 57)

    def test_a_filler_verb_in_a_count_costs_coverage_when_context_had_to_pick_the_candidate(self):
        # "work" cannot be told from a modifier without a word list; when hierarchy picked the candidate, it must
        # not also hide an unexplained word, so this natural phrasing stays REVIEW (the plain one answers)
        src = {"departments": {"engineering": {"employees": 120}, "sales": {"employees": 40}}}
        assert_review(ask("How many employees work in the sales department?", src, "number"))
        assert_answer(ask("Number of employees in the sales department", src, "number"), 40)

    def test_opening_is_not_matched_to_opened(self):
        # tokeniser limitation (no stemming of -ing/-ed pairs), out of scope for this batch
        assert_review(ask("Opening date of store 114", TestSiblingValues.STORES, "date"))
