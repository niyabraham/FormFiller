"""Attestation / consent detection (no browser).

Genuine attestations must go to REVIEW whatever the source JSON holds; ordinary factual questions that merely share a word
("Service Level Agreement", "Single sign-on", "Payment terms") must stay eligible for normal source matching.

These cases were written by the project to pin the intended behaviour and to keep earlier mistakes from returning. They are
not an independent measure of accuracy on real questionnaires: wording nobody thought of can still be missed (or flagged).
"""

from __future__ import annotations

import pytest

from formfill.web.models import Control, Option
from formfill.web.plan import ATTESTATION_REASON_PREFIX, is_attestation, plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control

YN = ["Yes", "No"]


def control(kind, label, *, help_text="", section="", placeholder="", options=()):
    return Control(control_id="c1", kind=kind, label=label, help_text=help_text, section=section, placeholder=placeholder,
                   options=[Option(o.lower(), o) for o in options])


def flagged(kind, label, **kw):
    c = control(kind, label, **kw)
    return is_attestation(c, understand_control(c).text)


# (kind, label, extra keyword arguments)
ATTESTATIONS = [
    # checkboxes
    ("checkbox", "I confirm the answers are accurate", {}),
    ("checkbox", "I agree to the Vendor Code of Conduct", {}),
    ("checkbox", "I declare the information above is true and complete", {}),
    ("checkbox", "We certify that we are not excluded from federal healthcare programs", {}),
    ("checkbox", "Terms and conditions", {}),
    ("checkbox", "Privacy policy", {}),
    ("checkbox", "Consent", {}),
    ("checkbox", "I have read and agree", {}),
    ("checkbox", "Acknowledge receipt of the instructions", {}),
    ("checkbox", "I accept responsibility for the accuracy of this submission", {}),
    ("checkbox", "Check this box to agree", {}),
    ("checkbox", "Please tick to indicate you have read the terms", {}),
    # agreement, acceptance, consent in a question or statement, on any control type
    *[(k, "Do you agree that the information is accurate?", {"options": YN if k in ("radio", "select") else ()})
      for k in ("radio", "select", "text", "checkbox")],
    ("radio", "Do you accept the terms and conditions?", {"options": YN}),
    ("radio", "Do you accept the data processing agreement?", {"options": YN}),
    ("radio", "Do you accept liability for data breaches caused by your subcontractors?", {"options": YN}),
    ("radio", "Terms accepted", {"options": YN}),
    ("radio", "Acceptance of terms", {"options": YN}),
    ("radio", "Agreement to terms", {"options": YN}),
    ("select", "Agreement to the data processing addendum", {"options": YN}),
    ("radio", "Do you consent to processing of this information?", {"options": YN}),
    ("radio", "Consent to be contacted", {"options": YN}),
    ("radio", "I consent to my data being processed", {"options": YN}),
    ("radio", "Do you give consent for us to contact your referees?", {"options": YN}),
    ("radio", "Do you give us permission to contact your referees?", {"options": YN}),
    ("radio", "Marketing consent", {"options": YN}),
    ("radio", "We agree to comply with all applicable laws", {"options": YN}),
    ("radio", "Do you agree to a right-to-audit clause?", {"options": YN}),
    ("radio", "I understand that submitting false information may disqualify the bid", {"options": YN}),
    ("radio", "I have read and understood the privacy notice", {"options": YN}),
    ("radio", "Do you acknowledge that you are responsible for subcontractors?", {"options": YN}),
    ("radio", "Data protection acknowledgement", {"options": YN}),
    ("radio", "Acknowledgment of receipt of addendum 1", {"options": YN}),
    ("radio", "Please confirm that you have read and accepted the supplier handbook", {"options": YN}),
    ("radio", "Anti-bribery undertaking", {"options": YN}),
    ("radio", "The supplier undertakes to notify the buyer of any change", {"options": YN}),
    ("radio", "Do you warrant that the goods are free from defects?", {"options": YN}),
    ("radio", "Do you represent that you are not debarred from public contracts?", {"options": YN}),
    # certification, declaration, accuracy of the form
    ("text", "Declaration: I certify that the answers are complete and accurate.", {}),
    ("text", "The undersigned hereby declares that the above is true", {}),
    ("radio", "We hereby certify compliance with the supplier code", {"options": YN}),
    ("radio", "Do you have any conflicts of interest to declare?", {"options": YN}),
    ("radio", "Self-certification of independence", {"options": YN}),
    ("radio", "Non-collusion certification", {"options": YN}),
    ("radio", "Certification of independent price determination", {"options": YN}),
    ("radio", "Self-declaration of compliance", {"options": YN}),
    ("radio", "Confirm that the information provided is accurate and complete", {"options": YN}),
    ("radio", "Confirmation that the information is accurate", {"options": YN}),
    ("radio", "Bidder's confirmation of eligibility", {"options": YN}),
    ("radio", "Is the information provided in this questionnaire accurate?", {"options": YN}),
    ("radio", "Are the above answers true and correct?", {"options": YN}),
    ("radio", "The information supplied is complete", {"options": YN}),
    ("radio", "I swear that the above is true", {"options": YN}),
    # authorisation to act or to release information
    ("radio", "By submitting, you authorize this organization to verify the information.", {"options": YN}),
    ("radio", "Authorisation to release information to third parties", {"options": YN}),
    ("radio", "Are you authorised to sign on behalf of the company?", {"options": YN}),
    ("radio", "Are you authorised to bind the company?", {"options": YN}),
    ("radio", "I am a duly authorised representative of the company", {"options": YN}),
    ("radio", "Authorise credit check", {"options": YN}),
    # signatures
    ("text", "Authorized signature", {}),
    ("text", "8. Authorised signature *", {}),
    ("text", "Signature", {}),
    ("text", "Signature of authorised officer", {}),
    ("text", "Electronic signature", {}),
    ("text", "Signed by", {}),
    ("text", "Date signed", {}),
    ("date", "Date of signature", {}),
    ("text", "Signature date", {}),
    # wording only in help text, placeholder, section heading, or option labels
    ("text", "Your name", {"help_text": "Sign to acknowledge the declaration."}),
    ("text", "Full name", {"help_text": "By typing your name you agree to be bound by the terms."}),
    ("text", "Name", {"help_text": "I understand that false statements may lead to rejection."}),
    ("text", "Name", {"help_text": "By completing this section you certify that you are entitled to bid."}),
    ("text", "Initials", {"help_text": "Type your initials to acknowledge the terms above."}),
    ("text", "Full name", {"placeholder": "Type your full name to sign"}),
    ("text", "Full name", {"placeholder": "Sign here"}),
    ("text", "Full name", {"section": "Declaration"}),
    ("text", "Full name", {"section": "Declaration and signature"}),
    ("text", "Name", {"section": "Final declaration"}),
    ("text", "Title", {"section": "Supplier attestation"}),
    ("text", "Company", {"section": "Terms & Conditions"}),
    ("text", "Date", {"section": "Terms and conditions"}),
    ("text", "Position", {"section": "Acknowledgement"}),
    ("text", "Print name", {"section": "Signature"}),
    ("text", "Job title", {"section": "Authorisation and consent"}),
    ("radio", "Data processing addendum", {"options": ["I agree", "I do not agree"]}),
    ("select", "Data processing addendum", {"options": ["I accept", "I decline"]}),
    ("radio", "Data processing addendum", {"options": ["Yes, I accept the terms", "No"]}),
    ("radio", "Responses", {"options": ["I confirm", "I cannot confirm"]}),
    ("radio", "Compliance statement", {"options": ["I certify compliance", "Not certified"]}),
]

FACTS = [
    # "conditions", "terms", "agreement", "confirmation", "sign", "understand", "authorization", "acknowledge", "consent"
    ("text", "Operating conditions", {}),
    ("text", "Storage conditions", {}),
    ("text", "Payment terms", {}),
    ("select", "Payment terms requested", {"options": ["Net 30", "Net 45", "Net 60"]}),
    ("text", "Delivery terms", {}),
    ("text", "Terms of service URL", {}),
    ("text", "Contract terms start date", {}),
    ("text", "What are your standard terms and conditions of sale?", {}),
    ("text", "Accepted payment terms", {}),
    ("text", "Service Level Agreement", {}),
    ("radio", "Service Level Agreement", {"options": YN}),
    ("text", "Agreement number", {}),
    ("text", "Agreement date", {}),
    ("text", "Master services agreement date", {}),
    ("text", "Agreed delivery date", {}),
    ("radio", "Is a data processing agreement available?", {"options": YN}),
    ("text", "Confirmation email", {}),
    ("email", "Confirm email", {}),
    ("text", "Confirmation number", {}),
    ("radio", "Order confirmation sent?", {"options": YN}),
    ("radio", "Do you send order confirmation emails?", {"options": YN}),
    ("text", "Please confirm your email address", {}),
    ("radio", "Do you confirm shipments by email?", {"options": YN}),
    ("text", "Sign-in method", {}),
    ("text", "Sign-on protocol", {}),
    ("text", "Single sign-on provider", {}),
    ("radio", "Do you support single sign-on?", {"options": YN}),
    ("radio", "Does the product support single sign-on?", {"options": YN}),
    ("radio", "Is single sign-on (SSO) supported?", {"options": YN}),
    ("checkbox", "Has SSO enabled", {}),
    ("radio", "Do you use code signing for releases?", {"options": YN}),
    ("radio", "Do you support digital signatures?", {"options": YN}),
    ("text", "Digital signature algorithm", {}),
    ("text", "Signature-based detection tool", {}),
    ("text", "Detection engine", {"section": "Signature-based detection"}),
    ("radio", "Are emails signed with DKIM?", {"options": YN}),
    ("radio", "Do you support SAML signature validation?", {"options": YN}),
    ("radio", "Do you use signed firmware updates?", {"options": YN}),
    ("radio", "Signature required on delivery?", {"options": YN}),
    ("radio", "Do you have a signed NDA with your employees?", {"options": YN}),
    ("radio", "Do employees sign confidentiality agreements?", {"options": YN}),
    ("radio", "Are contractors required to sign NDAs?", {"options": YN}),
    ("text", "Name of authorised signatory", {}),
    ("text", "Position of signatory", {}),
    ("text", "Authorised representative", {}),
    ("radio", "Do you understand the scope of this questionnaire?", {"options": YN}),
    ("text", "Understanding of the scope", {}),
    ("text", "Authorization method", {}),
    ("radio", "Do you support role-based authorization?", {"options": YN}),
    ("text", "Authentication and authorization mechanism", {}),
    ("text", "Access control model", {"section": "Authentication & Authorization"}),
    ("radio", "Is multi-factor authorisation required for admins?", {"options": YN}),
    ("radio", "Do you have an authorised reseller programme?", {"options": YN}),
    ("text", "Number of authorised dealers", {}),
    ("text", "Mean time to acknowledge a security incident", {}),
    ("text", "Incident acknowledgement time (hours)", {}),
    ("text", "Support acknowledgement SLA", {}),
    ("radio", "Do you accept credit cards?", {"options": YN}),
    ("radio", "Do you accept purchase orders?", {"options": YN}),
    ("radio", "Do you accept returns?", {"options": YN}),
    ("text", "Accepted file formats", {}),
    ("radio", "Do you have a privacy policy?", {"options": YN}),
    ("url", "Privacy policy URL", {}),
    ("date", "Date of last privacy policy review", {}),
    ("radio", "Is your privacy notice reviewed annually?", {"options": YN}),
    ("radio", "Do you obtain consent before processing personal data?", {"options": YN}),
    ("text", "Consent management platform", {}),
    ("text", "Consent records retention period", {}),
    ("radio", "Do you use a cookie consent banner?", {"options": YN}),
    ("radio", "Do you collect parental consent for under-13 users?", {"options": YN}),
    ("radio", "Do you have a process for customers to give consent?", {"options": YN}),
    ("radio", "Do you honour consent withdrawal requests?", {"options": YN}),
    ("radio", "Do you undertake annual penetration testing?", {"options": YN}),
    ("radio", "Do you maintain a warrant canary?", {"options": YN}),
    ("text", "Warranty period", {}),
    ("text", "Total declared value of shipments", {}),
    ("text", "Customs declaration number", {}),
    ("radio", "Do you provide a statement of applicability?", {"options": YN}),
    # certifications held are facts; certifying the form is not
    ("radio", "Do you hold ISO 27001 certification?", {"options": YN}),
    ("checkbox_group", "Which certifications do you hold?", {}),
    ("text", "SOC 2 certifications", {}),
    ("text", "Certifying body", {}),
    ("number", "Number of certified engineers", {}),
    ("radio", "Do you hold a SOC 2 Type II attestation?", {"options": YN}),
    # accuracy words without a statement about the form
    ("radio", "Is the information security policy approved by management?", {"options": YN}),
    ("radio", "Is the data correct at the point of entry (input validation)?", {"options": YN}),
    ("radio", "Do you verify that customer information is accurate?", {"options": YN}),
    ("radio", "Is your information security programme audited and complete?", {"options": YN}),
    ("radio", "Is all information correct and up to date in the CMDB?", {"options": YN}),
    # Likert points are not agreements
    ("radio", "Our staff are trained", {"options": ["Strongly agree", "Agree", "Disagree"]}),
    # plain
    ("text", "Legal company name", {"help_text": "Please enter the registered name, as shown on your certificate."}),
    ("text", "Country of incorporation", {}),
    ("text", "Primary contact name", {"section": "Contact details"}),
    ("text", "Full name", {"placeholder": "e.g. Acme Corp"}),
]


def _id(case):
    kind, label, extra = case
    detail = ", ".join(f"{k}={v}" for k, v in extra.items() if v)
    return f"{kind}: {label}" + (f" [{detail}]" if detail else "")


@pytest.mark.parametrize("case", ATTESTATIONS, ids=_id)
def test_attestation_is_flagged(case):
    kind, label, extra = case
    assert flagged(kind, label, **extra), "a genuine attestation was not recognised"


@pytest.mark.parametrize("case", FACTS, ids=_id)
def test_ordinary_factual_question_is_not_flagged(case):
    kind, label, extra = case
    assert not flagged(kind, label, **extra), "an ordinary factual question was sent to human review as an attestation"


# ---- end to end through plan_question: a matching source value must not answer an attestation -------------------------------

POISONED_SOURCE = {
    "information_accurate": True, "answers_complete": True, "information_provided_accurate": True, "terms_accepted": True,
    "consent": True, "consent_to_be_contacted": True, "authorised": True, "signature": "Fictional Vendor LLC",
    "data_processing_addendum": "I agree", "full_name": "Fictional Vendor LLC", "signed_by": "Fictional Vendor LLC",
    "agreement_to_terms": True, "declaration": True, "self_certification_of_independence": True,
    "marketing_consent": True, "bidders_confirmation_of_eligibility": True,
}


@pytest.mark.parametrize("case", [
    ("radio", "Is the information provided in this questionnaire accurate?", {"options": YN}),
    ("radio", "Are the above answers true and correct?", {"options": YN}),
    ("radio", "Data processing addendum", {"options": ["I agree", "I do not agree"]}),
    ("radio", "Agreement to terms", {"options": YN}),
    ("radio", "Marketing consent", {"options": YN}),
    ("radio", "Bidder's confirmation of eligibility", {"options": YN}),
    ("radio", "Self-certification of independence", {"options": YN}),
    ("text", "Signed by", {}),
    ("text", "Full name", {"placeholder": "Type your full name to sign"}),
    ("text", "Full name", {"section": "Declaration and signature"}),
], ids=_id)
def test_source_value_never_answers_an_attestation(case):
    kind, label, extra = case
    c = control(kind, label, **extra)
    item = plan_question(understand_control(c), index_source(POISONED_SOURCE))
    assert item.status == "REVIEW" and item.answer is None
    assert item.reason.startswith(ATTESTATION_REASON_PREFIX)


@pytest.mark.parametrize(("kind", "label", "options", "source", "expected"), [
    ("text", "Payment terms", (), {"payment_terms": "Net 30"}, "Net 30"),
    ("text", "Operating conditions", (), {"operating_conditions": "Dry, ambient"}, "Dry, ambient"),
    ("text", "Sign-in method", (), {"sign_in_method": "Password and MFA"}, "Password and MFA"),
    ("radio", "Do you support single sign-on?", YN, {"sso": {"single_sign_on": True}}, "yes"),
    ("email", "Confirmation email", (), {"confirmation_email": "orders@acme.example"}, "orders@acme.example"),
    ("text", "Service Level Agreement", (), {"service_level_agreement": "99.9% monthly uptime"}, "99.9% monthly uptime"),
    ("text", "Authorization method", (), {"authorization_method": "OAuth 2.0"}, "OAuth 2.0"),
    ("radio", "Do you have a privacy policy?", YN, {"privacy_policy": True}, "yes"),
])
def test_factual_questions_are_still_answered_from_source(kind, label, options, source, expected):
    c = control(kind, label, options=options)
    item = plan_question(understand_control(c), index_source(source))
    assert item.status == "ANSWER" and item.answer == expected, (item.reason, item.alternatives)


# ---- a heading applies to every control after it, so it must name the act itself --------------------------------------------


@pytest.mark.parametrize("section", ["Service Level Agreement", "Authentication & Authorization", "Signature-based detection",
                                     "Operating conditions", "Payment terms", "Consent management", "Master Services Agreement questionnaire"])
def test_topic_headings_do_not_flag_the_controls_under_them(section):
    assert not flagged("text", "Primary contact name", section=section)


@pytest.mark.parametrize("section", ["Declaration", "Declarations", "Terms and conditions", "Signature", "Acknowledgement",
                                     "Supplier attestation", "Applicant declaration", "Consent", "2. Authorisation and consent"])
def test_act_headings_flag_the_controls_under_them(section):
    assert flagged("text", "Primary contact name", section=section)


@pytest.mark.parametrize("kind", ["radio", "text"])
def test_a_bare_consent_or_signature_label_is_still_recognised_when_it_has_help_text(kind):
    """Anchored patterns must judge the label itself, not the label joined to the text after it."""
    opts = YN if kind == "radio" else ()
    assert flagged(kind, "Consent", help_text="Optional.", options=opts)
    assert flagged(kind, "Signature", help_text="Use your full legal name.", section="Contact details", options=opts)
    assert not flagged(kind, "Consent management platform", help_text="Name of the tool.", options=opts)


def test_flagged_item_carries_the_reason_the_submit_gate_keys_on():
    c = control("checkbox", "I agree to the terms")
    item = plan_question(understand_control(c), index_source({"terms": True}))
    assert item.status == "REVIEW" and item.reason.startswith(ATTESTATION_REASON_PREFIX)


# ---- wording found missing by an independent review, and the rules added for it -----------------------------------------------
#
# These come from a review that probed the detector with phrasings nobody had tuned it on. Each rule below was added because
# the wording is an act (promising, being bound, signing, vouching) and has no ordinary factual reading. Wording whose
# factual reading is common stays unflagged on purpose, see KNOWN_GAPS.

AUDIT_ATTESTATIONS = [
    ("radio", "Will you comply with and be bound by these terms?", {"options": YN}),
    ("radio", "Are you willing to be bound by the code of conduct?", {"options": YN}),
    ("radio", "Do you undertake to notify us of any changes?", {"options": YN}),
    ("radio", "Does the bidder warrant that it has full authority to enter into this contract?", {"options": YN}),
    ("radio", "Is this a true and complete statement?", {"options": YN}),
    ("radio", "Do the answers above reflect the truth?", {"options": YN}),
    ("radio", "Have you read the privacy notice?", {"options": YN}),
    ("text", "E-signature", {}),
    ("text", "Initial here", {}),
    ("text", "Type your name to confirm", {}),
    ("radio", "Clause 14.2 limitation of liability", {"options": ["Agree", "Disagree"]}),
    ("select", "Clause 14.2 limitation of liability", {"options": ["Select...", "Accepted", "Declined"]}),
    ("radio", "Data processing addendum", {"options": ["I have read and accept", "I do not accept"]}),
]


@pytest.mark.parametrize("case", AUDIT_ATTESTATIONS, ids=_id)
def test_wording_found_missing_by_the_review_is_now_flagged(case):
    kind, label, extra = case
    assert flagged(kind, label, **extra)


@pytest.mark.parametrize("case", AUDIT_ATTESTATIONS, ids=_id)
def test_wording_found_missing_by_the_review_goes_to_review_whatever_the_source_holds(case):
    kind, label, extra = case
    source = {"anything": True, "terms": True, "agree": "Agree", "signature": "Fictional Vendor LLC", "e_signature": "Fictional Vendor LLC",
              "initial_here": "FV", "clause_14_2_limitation_of_liability": "Agree", "data_processing_addendum": "I agree"}
    item = plan_question(understand_control(control(kind, label, **extra)), index_source(source))
    assert item.status == "REVIEW" and item.answer is None and item.reason.startswith(ATTESTATION_REASON_PREFIX)


# Near misses with the same words and an ordinary factual meaning.
NEAR_MISSES = [
    ("radio", "Do you undertake penetration testing?", {"options": YN}),
    ("radio", "Are you bound by any exclusivity agreements?", {"options": YN}),
    ("radio", "Have you read the annual report?", {"options": YN}),
    ("radio", "Does the platform warrant uptime through an SLA credit?", {"options": YN}),
    ("radio", "The onboarding portal is easy to use", {"options": ["Strongly agree", "Agree", "Neutral", "Disagree", "Strongly disagree"]}),
    ("radio", "Ticket status", {"options": ["Acknowledged", "Pending", "Closed"]}),
    ("select", "Preferred contact method", {"options": ["Select...", "Email", "Phone"]}),
    ("radio", "Is the dataset complete?", {"options": YN}),
]


@pytest.mark.parametrize("case", NEAR_MISSES, ids=_id)
def test_near_misses_with_a_factual_meaning_are_not_flagged(case):
    kind, label, extra = case
    assert not flagged(kind, label, **extra)


# ---- each tier-1 pattern, alone: labels on a free-text field, which tier 2 never looks at ----------------------------------------
# (A mutation check found that removing any of these patterns used to fail no test.)

SINGLE_PATTERN_CASES = [
    ("_ACCEPT_ANSWER", "text", "Yes, I accept"),
    ("_READ_AND_AGREE", "text", "Read and understood by the signatory"),
    ("_ACKNOWLEDGE", "text", "Acknowledgement of the risks involved"),
    ("_CONFIRM", "text", "Confirmation of eligibility"),
    ("_AGREEMENT_TO", "text", "Agreement to the above"),
    ("_DECLARATION", "text", "Declaration of conflicts of interest"),
    ("_UNDERTAKE", "text", "The bidder undertakes to notify the buyer"),
    ("_BOUND", "text", "Bound by the code of conduct since"),
    ("_READ_LEGAL", "text", "Have you read the privacy notice"),
]


@pytest.mark.parametrize(("pattern", "kind", "label"), SINGLE_PATTERN_CASES)
def test_each_tier_one_pattern_is_exercised_by_a_case_only_it_catches(pattern, kind, label):
    assert flagged(kind, label)


def test_an_option_that_reads_i_accept_flags_a_neutral_label():
    """Only `_ACCEPT_ANSWER` recognises these options; the label says nothing."""
    assert flagged("radio", "Selection", options=["I accept", "I decline"])


# ---- every exemption in _FACTUAL_COMPOUND, once: a statement-style yes/no that would be flagged without it --------------------------

FACTUAL_COMPOUND_CASES = [
    "Service level agreement offered", "Agreement number provided", "Order confirmation sent automatically",
    "Confirmation email sent", "Confirm email address required", "Authorization method documented",
    "Role-based authorization implemented", "Authentication and authorization implemented", "Multi-factor authorization enforced",
    "Authorized resellers only", "Consent management platform used", "Cookie consent shown", "Operating conditions documented",
    "Terms of payment documented", "Terms start date shown", "Incident acknowledgement automated", "Time to acknowledge tracked",
    "Acknowledgement time tracked", "Warrant canary published", "Permission model documented", "File permission documented",
]


@pytest.mark.parametrize("label", FACTUAL_COMPOUND_CASES)
def test_known_factual_compounds_are_not_flagged_on_a_yes_no_statement(label):
    assert not flagged("radio", label, options=YN)
    assert not flagged("checkbox", label)
