"""Neighbouring concepts must not answer each other's questions.

Found while preparing the portfolio demo: with no RPO fact in the source, "Recovery point objective (RPO) in hours" was answered with
the recovery *time* objective (`business_continuity.rto_hours` = 8, score 0.87, category "medium"). The two phrases share `recovery`,
`objective` and `hours` and differ in one word (`point` / `time`); nothing in the scorer treated that word as a distinction, and the
form-section bonus lifted the partial overlap over the answer threshold.

The same shape fails for other pairs of phrases that differ in one meaning-bearing word: encryption *in transit* vs *at rest*,
*authentication* vs *authorization*, *minimum* vs *maximum*, a *frequency* vs a *scope*. These tests pin the safe behaviour:

* the neighbour's fact is never entered (the question abstains, `REVIEW`, no answer), and it is not offered as a proposal either;
* when the question's own fact exists, it is still found, whatever else is in the source;
* related word forms of the same concept (`apply` / `applicable`) are not mistaken for neighbours.

A REVIEW never counts as a correct answer: tests that expect an ANSWER assert the value and the source, tests that expect REVIEW assert
the status AND that no answer is carried.
"""

from __future__ import annotations

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import MIN_CONFIDENCE, build_plan, plan_question
from formfill.web.retrieve import index_source, retrieve
from formfill.web.understand import understand, understand_control

YN = [Option("yes", "Yes"), Option("no", "No")]
BC = "Business continuity"


def control(label, kind="text", section="", options=None, cid="c1"):
    return Control(control_id=cid, kind=kind, label=label, section=section, options=options or [])


def ask(label, source, kind="text", section="", options=None):
    return plan_question(understand_control(control(label, kind, section, options)), index_source(source))


def assert_answer(item, value, source):
    assert item.status == "ANSWER", (item.reason, item.alternatives)
    assert item.answer == value and item.source == source


def assert_review(item):
    assert item.status == "REVIEW" and item.answer is None, (item.status, item.answer, item.source, item.confidence)


# ---- the reported failure: RPO and RTO ---------------------------------------------------------------------------------------------------

RPO_QUESTIONS = [
    ("Recovery point objective (RPO) in hours", BC),
    ("Recovery point objective (RPO) in hours", ""),
    ("RPO (hours)", BC),
    ("What is your recovery point objective?", BC),
    ("Recovery point objective", ""),
]
RTO_QUESTIONS = [
    ("Recovery time objective (RTO) in hours", BC),
    ("Recovery time objective (RTO) in hours", ""),
    ("RTO (hours)", BC),
    ("What is your recovery time objective?", BC),
    ("Recovery time objective", ""),
]
# the same fact written in the ways a source can write it: a short key, a spelled-out key, nested, with and without the unit
RTO_FACTS = [
    {"business_continuity": {"rto_hours": 8}},
    {"business_continuity": {"recovery_time_objective": 8}},
    {"disaster_recovery": {"rto": 8}},
    {"rto_hours": 8},
    {"dr": {"rto_hours": 8, "backup_frequency": "daily"}},
]
RPO_FACTS = [
    {"business_continuity": {"rpo_hours": 1}},
    {"business_continuity": {"recovery_point_objective": 1}},
    {"disaster_recovery": {"rpo": 1}},
    {"rpo_hours": 1},
    {"dr": {"rpo_hours": 1, "backup_frequency": "daily"}},
]


BOTH_FACTS = [
    {"business_continuity": {"rto_hours": 8, "rpo_hours": 1}},
    {"business_continuity": {"recovery_time_objective": 8, "recovery_point_objective": 1}},
]


class TestRpoRtoMustNotAnswerEachOther:
    @pytest.mark.parametrize("source", RTO_FACTS, ids=lambda s: str(s)[:48])
    @pytest.mark.parametrize("label, section", RPO_QUESTIONS)
    def test_rpo_missing_but_rto_present_the_rpo_question_abstains(self, label, section, source):
        assert_review(ask(label, source, "number", section))

    @pytest.mark.parametrize("source", RPO_FACTS, ids=lambda s: str(s)[:48])
    @pytest.mark.parametrize("label, section", RTO_QUESTIONS)
    def test_rto_missing_but_rpo_present_the_rto_question_abstains(self, label, section, source):
        assert_review(ask(label, source, "number", section))

    def test_the_reported_case_exactly(self):
        item = ask("Recovery point objective (RPO) in hours", {"business_continuity": {"rto_hours": 8}}, "number", BC)
        assert_review(item)
        assert item.answer != 8

    def test_the_neighbour_stays_visible_to_the_reviewer_but_cannot_be_auto_answered(self):
        q = understand_control(control("Recovery point objective (RPO) in hours", "number", BC))
        top = retrieve(q, index_source({"business_continuity": {"rto_hours": 8}}))[0]
        assert top.path == "business_continuity.rto_hours" and top.score < MIN_CONFIDENCE
        assert top.flags, "the reviewer must be told why the candidate was held back"

    def test_the_neighbours_value_is_not_offered_as_a_proposal_either(self):
        # a proposal is one click from "Approve": a reviewer must not be handed the wrong concept's value
        for label, source in (("Recovery point objective (RPO) in hours", {"business_continuity": {"rto_hours": 8}}),
                              ("Recovery time objective (RTO) in hours", {"business_continuity": {"rpo_hours": 1}})):
            item = ask(label, source, "number", BC)
            assert_review(item)
            assert item.proposed_answer is None, (item.proposed_answer, item.reason)

    @pytest.mark.parametrize("source", BOTH_FACTS, ids=["short keys", "spelled-out keys"])
    @pytest.mark.parametrize("label, section", RPO_QUESTIONS)
    def test_both_present_the_rpo_question_gets_the_rpo_fact(self, label, section, source):
        item = ask(label, source, "number", section)
        assert item.status == "ANSWER" and item.answer == 1 and item.source.endswith(("rpo_hours", "recovery_point_objective")), (item.answer, item.source)

    @pytest.mark.parametrize("source", BOTH_FACTS, ids=["short keys", "spelled-out keys"])
    @pytest.mark.parametrize("label, section", RTO_QUESTIONS)
    def test_both_present_the_rto_question_gets_the_rto_fact(self, label, section, source):
        item = ask(label, source, "number", section)
        assert item.status == "ANSWER" and item.answer == 8 and item.source.endswith(("rto_hours", "recovery_time_objective")), (item.answer, item.source)

    @pytest.mark.parametrize("source", RPO_FACTS, ids=lambda s: str(s)[:48])
    def test_rpo_present_the_rpo_question_still_matches_it(self, source):
        item = ask("Recovery point objective (RPO) in hours", source, "number", BC)
        assert item.status == "ANSWER" and item.answer == 1

    @pytest.mark.parametrize("source", RTO_FACTS, ids=lambda s: str(s)[:48])
    def test_rto_present_the_rto_question_still_matches_it(self, source):
        item = ask("Recovery time objective (RTO) in hours", source, "number", BC)
        assert item.status == "ANSWER" and item.answer == 8

    def test_a_confident_match_keeps_its_confidence_category(self):
        item = ask("Recovery time objective (RTO) in hours", {"business_continuity": {"rto_hours": 8}}, "number", BC)
        assert item.status == "ANSWER" and item.confidence_category == "high" and item.confidence == 1.0

    def test_an_ambiguous_recovery_objective_question_goes_to_a_person(self):
        # asks for "the recovery objective" without saying which: two different facts are equally relevant
        item = ask("Recovery objective in hours", {"business_continuity": {"rto_hours": 8, "rpo_hours": 1}}, "number", BC)
        assert_review(item)

    def test_repeated_rpo_labels_in_one_form_never_take_the_rto_fact(self):
        # the same label twice (two sections of one form): both resolve the same way, and a missing neighbour never fills either
        src = {"business_continuity": {"rto_hours": 8}}
        controls = [control("Recovery point objective (RPO) in hours", "number", "Primary site", cid="a"),
                    control("Recovery point objective (RPO) in hours", "number", "Secondary site", cid="b")]
        plans = build_plan(understand(controls), index_source(src))
        assert [p.status for p in plans] == ["REVIEW", "REVIEW"] and [p.answer for p in plans] == [None, None]

    def test_an_unrelated_source_still_abstains_with_no_matching_value(self):
        item = ask("Recovery point objective (RPO) in hours", {"company": {"name": "Acme Corp"}}, "number", BC)
        assert_review(item)
        assert "no matching value" in item.reason


# ---- the other concept pairs: wrong answers found by probing, now pinned -----------------------------------------------------------------

MUST_ABSTAIN = [
    # (id, question, kind, section, source)
    ("transit-from-rest", "Is data encrypted in transit?", "radio", "Encryption", {"encryption": {"data_at_rest": True}}),
    ("rest-from-transit", "Is data encrypted at rest?", "radio", "Encryption", {"encryption": {"data_in_transit": True}}),
    ("transit-from-rest-long", "Is customer data encrypted in transit?", "radio", "Encryption", {"encryption": {"customer_data_encrypted_at_rest": True}}),
    ("rest-from-transit-long", "Is customer data encrypted at rest?", "radio", "Encryption", {"encryption": {"customer_data_encrypted_in_transit": True}}),
    ("authn-from-authz", "Authentication method", "text", "Access control", {"access_control": {"authorization_method": "RBAC"}}),
    ("authz-from-authn", "Authorization method", "text", "Access control", {"access_control": {"authentication_method": "SAML SSO"}}),
    ("strong-authn-from-authz", "Is strong authentication enforced?", "radio", "Access control", {"access_control": {"strong_authorization_enforced": True}}),
    ("authz-enforced-from-authn", "Is role-based authorization enforced?", "radio", "Access control",
     {"access_control": {"role_based_authentication_enforced": True}}),
    ("deletion-from-retention", "Data deletion period (days)", "number", "Data protection", {"data_protection": {"data_retention_days": 90}}),
    ("retention-from-deletion", "Data retention period (days)", "number", "Data protection", {"data_protection": {"data_deletion_days": 30}}),
    ("backup-frequency-from-retention", "Backup frequency", "text", "Backup and recovery", {"backup": {"retention_days": 30}}),
    ("backup-retention-from-frequency", "Backup retention period (days)", "number", "Backup and recovery", {"backup": {"frequency": "daily"}}),
    ("response-time-from-notification", "Incident response time (hours)", "number", "Incident response", {"incident_response": {"notification_hours": 72}}),
    ("notification-time-from-response", "Customer breach notification time (hours)", "number", "Incident response",
     {"incident_response": {"response_time_hours": 4}}),
    ("minimum-from-maximum", "Minimum password length", "number", "Access control", {"access_control": {"maximum_password_length": 64}}),
    ("maximum-from-minimum", "Maximum password age (days)", "number", "Access control", {"access_control": {"minimum_password_age_days": 1}}),
    ("frequency-from-scope", "Penetration test frequency", "text", "Security testing", {"security_testing": {"penetration_test_scope": "external"}}),
]
MUST_ANSWER = [
    # (id, question, kind, section, source, value, source path)
    ("transit-own-fact", "Is data encrypted in transit?", "radio", "Encryption", {"encryption": {"data_at_rest": True, "data_in_transit": False}},
     "no", "encryption.data_in_transit"),
    ("rest-own-fact", "Is data encrypted at rest?", "radio", "Encryption", {"encryption": {"data_at_rest": True, "data_in_transit": False}},
     "yes", "encryption.data_at_rest"),
    ("authn-own-fact", "Authentication method", "text", "Access control",
     {"access_control": {"authorization_method": "RBAC", "authentication_method": "SAML SSO"}}, "SAML SSO", "access_control.authentication_method"),
    ("authz-own-fact", "Authorization model", "text", "Access control",
     {"access_control": {"authorization_model": "RBAC", "authentication_method": "SAML SSO"}}, "RBAC", "access_control.authorization_model"),
    ("retention-own-fact", "Data retention period (days)", "number", "Data protection",
     {"data_protection": {"retention_days": 90, "deletion_days": 30}}, 90, "data_protection.retention_days"),
    ("deletion-own-fact", "Data deletion period (days)", "number", "Data protection",
     {"data_protection": {"retention_days": 90, "deletion_days": 30}}, 30, "data_protection.deletion_days"),
    ("backup-frequency-own-fact", "Backup frequency", "text", "Backup and recovery",
     {"backup": {"retention_days": 30, "frequency": "daily"}}, "daily", "backup.frequency"),
    ("backup-retention-own-fact", "Backup retention period (days)", "number", "Backup and recovery",
     {"backup": {"retention_days": 30, "frequency": "daily"}}, 30, "backup.retention_days"),
    ("response-time-own-fact", "Incident response time (hours)", "number", "Incident response",
     {"incident_response": {"notification_hours": 72, "response_time_hours": 4}}, 4, "incident_response.response_time_hours"),
]
ONLY_THE_OTHER = [pytest.param(*row[1:], id=row[0]) for row in MUST_ABSTAIN]


class TestRelatedConceptsAreNotInterchangeable:
    @pytest.mark.parametrize("label, kind, section, source", ONLY_THE_OTHER)
    def test_only_the_neighbouring_fact_exists_the_question_abstains(self, label, kind, section, source):
        item = ask(label, source, kind, section, YN if kind == "radio" else None)
        assert_review(item)
        assert item.proposed_answer is None, f"the neighbour's value was offered as a proposal: {item.proposed_answer!r}"

    @pytest.mark.parametrize("label, kind, section, source, value, path",
                             [pytest.param(*row[1:], id=row[0]) for row in MUST_ANSWER])
    def test_the_questions_own_fact_is_still_found_beside_its_neighbour(self, label, kind, section, source, value, path):
        assert_answer(ask(label, source, kind, section, YN if kind == "radio" else None), value, path)


# ---- valid matches must not be lost -----------------------------------------------------------------------------------------------------

class TestRelatedWordFormsAreTheSameConcept:
    """A different word form of the SAME word is not a different concept: these answered before and must still answer."""

    def test_apply_and_applicable(self):
        item = ask("Does GDPR apply to your organization?", {"privacy": {"gdpr_applicable": True}}, "radio", "Privacy", YN)
        assert_answer(item, "yes", "privacy.gdpr_applicable")

    def test_supported_and_support(self):
        assert_answer(ask("Do you support SSO?", {"access": {"sso_supported": True}}, "radio", "Access control", YN), "yes", "access.sso_supported")

    def test_encrypted_and_encryption(self):
        assert_answer(ask("Is customer data encrypted at rest?", {"encryption": {"customer_data_at_rest": True}}, "radio", "Encryption", YN),
                      "yes", "encryption.customer_data_at_rest")

    def test_how_often_and_frequency(self):
        assert_answer(ask("How often are backups tested?", {"backup_test_frequency": "monthly"}), "monthly", "backup_test_frequency")

    def test_an_acronym_and_its_spelled_out_form(self):
        assert_answer(ask("Do you maintain a business continuity plan (BCP)?", {"policies": {"bcp_exists": True}}, "radio", "", YN), "yes", "policies.bcp_exists")
        assert_answer(ask("Recovery time objective (RTO) in hours", {"dr": {"recovery_time_objective_hours": 8}}, "number"), 8, "dr.recovery_time_objective_hours")


class TestOtherSafetyBehaviourIsUnchanged:
    def test_an_unmatched_question_still_abstains(self):
        assert_review(ask("Do you have cyber insurance?", {"company": {"name": "Acme Corp"}}, "radio", "", YN))

    def test_two_equally_relevant_facts_with_different_values_are_still_ambiguous(self):
        item = ask("Number of offices", {"company": {"offices_eu": 3, "offices_uk": 5}}, "number")
        assert_review(item)

    def test_a_partial_match_that_names_a_different_scope_is_still_held_back(self):
        # the existing scope guard: "remote" employees are not all employees
        assert_review(ask("Number of employees working remotely", {"company": {"employees": 180}}, "number"))


class TestRetentionIsNotDeletion:
    """Review follow-up: the one wrong answer left on the related-concept probes. `retention_days_after_termination` is exactly half
    explained by "How long after termination is customer data deleted (days)?" and was answered; a key about a topic the question never
    names ("retention") now needs MORE than half of the question explained."""

    RETENTION = {"data_protection": {"retention_days_after_termination": 90}}
    DELETION = {"data_protection": {"deletion_days_after_termination": 30}}

    def test_a_retention_fact_does_not_answer_a_deletion_question(self):
        item = ask("How long after termination is customer data deleted (days)?", self.RETENTION, kind="number", section="Data protection")
        assert_review(item)

    def test_a_deletion_fact_does_not_answer_a_retention_question(self):
        item = ask("How long is customer data retained after termination (days)?", self.DELETION, kind="number", section="Data protection")
        assert_review(item)

    def test_each_question_is_still_answered_from_its_own_fact(self):
        both = {"data_protection": {**self.RETENTION["data_protection"], **self.DELETION["data_protection"]}}
        assert_answer(ask("Deletion days after termination", both, kind="number", section="Data protection"), 30,
                      "data_protection.deletion_days_after_termination")
        assert_answer(ask("Retention days after termination", both, kind="number", section="Data protection"), 90,
                      "data_protection.retention_days_after_termination")


class TestAProposalIsTheKindOfContactDetailAsked:
    """Review follow-up: with the CISO's email gated off as a neighbouring concept, "Contact Email" was offered the incident contact's
    PHONE NUMBER because both keys say "contact". A proposal (like an answer) must be the kind of detail the question asks for."""

    PHONE_ONLY = {"security": {"incident_contact_phone": "+1 512 555 0147"}}
    EMAIL_ONLY = {"contact_email": "ops@acme.example"}

    @pytest.mark.parametrize("label", ["Contact Email", "Contact email address"])
    def test_an_email_question_is_never_offered_a_phone_number(self, label):
        item = ask(label, self.PHONE_ONLY)
        assert item.status == "REVIEW" and item.answer is None
        assert item.proposed_answer is None

    @pytest.mark.parametrize("label", ["Contact phone", "Contact telephone number"])
    def test_a_phone_question_is_never_offered_an_email(self, label):
        item = ask(label, self.EMAIL_ONLY)
        assert item.status == "REVIEW" and item.answer is None
        assert item.proposed_answer is None

    def test_the_right_kind_of_contact_detail_is_still_answered(self):
        both = {**self.EMAIL_ONLY, **self.PHONE_ONLY}
        assert_answer(ask("Contact email", both), "ops@acme.example", "contact_email")

    def test_a_format_hint_in_the_label_is_not_a_different_concept(self):
        """"Contact phone Format 3 3 4" asks for the contact phone; "Format 3 3 4" says how to write it, not what it is."""
        item = ask("Contact phone Format 3 3 4", self.PHONE_ONLY)
        assert item.status == "REVIEW" and item.answer is None
        assert item.proposed_answer == "+1 512 555 0147"
