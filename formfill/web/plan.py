"""Reasoning layer, step 3: choose an answer per question and emit the
AnswerPlan -- the *only* thing the browser layer receives.

Policy ("never guess"), applied in this order. Any failure -> REVIEW with a
human-readable reason and the candidates considered:

  0. attestation / consent / declaration      -> REVIEW  (always, any control type; legal declarations)
  1. control disabled                         -> REVIEW
  2. no candidate at all                      -> REVIEW  (no source value)
  3. best score < MIN_CONFIDENCE              -> REVIEW  (weak evidence)
  3b. the value is a placeholder ("None", "N/A", "TBD") and no option offers it -> REVIEW
  4. runner-up within MIN_MARGIN of the best
     and holding a *different* value          -> REVIEW  (ambiguous / conflicting)
  5. value fails deterministic validation     -> REVIEW  (wrong type, invalid option, ...)
  otherwise                                   -> ANSWER, with source path and confidence

The thresholds are starting values chosen from the research, not tuned on
real data; they live here as constants so they can be calibrated in one
place once there is a labelled sample of real RFIs.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from formfill.web.models import AnswerPlanItem, Candidate, Question
from formfill.web.retrieve import Leaf, retrieve
from formfill.web.validate import is_placeholder, validate_answer

MIN_CONFIDENCE = 0.6
MIN_MARGIN = 0.15

ATTESTATION_REASON = "attestation/consent: a human must confirm it, never auto-filled"
ATTESTATION_REASON_PREFIX = "attestation/consent"  # the submit gate in pipeline.py keys on this prefix

# Declarations, agreements, and permissions the organisation legally stands behind. Policy, not scoring: these are never
# answered by software, whatever the source JSON contains.
#
# Two tiers, either of which sends the question to a human:
#
#  1. Explicit evidence of an act, for any control type: the respondent agreeing, certifying, declaring, consenting, signing,
#     authorising, or vouching for the accuracy of the form ("I agree", "you consent", "Authorised signature", "Is the information
#     provided accurate?"), in the question, help text, placeholder, section heading, or an option label such as "I accept".
#  2. Broad wording ("agreement", "consent", "confirmation", "terms", "authorization", ...) on a control that can say yes: a
#     checkbox, or a choice with a yes/agree option, whose label is a statement and not a question. These words also name
#     ordinary facts ("Service Level Agreement", "Operating conditions", "Confirmation email", "Authorization method",
#     "Payment terms"), so known factual compounds are set aside first; an unknown compound still goes to review, which is
#     the safe direction. A free-text, number or date field is not affected, since it cannot be "ticked".
#
# Wording that matches neither tier is answered like any other question, so when a real attestation slips by, add a pattern
# and a regression test (tests/web/test_attestation_detection.py).
_ENUM = r"^\W*(?:\d+(?:\.\d+)*[.):]?\s+)?"  # optional leading question number, anchored at the start of the text
_ADV = r"(?:(?:hereby|herewith|do|have|has|also|further|fully|duly|expressly|solemnly|irrevocably|truthfully)\s+)*"
_NOT_TECHNIQUE = (
    r"(?![- ]?(?:algorithm|scheme|standard|method|provider|solution|tool|based|verification|support|required|"
    r"on\s+delivery|upon\s+delivery|capture|pad))"
)
_LEGAL_DOC = (  # documents whose acceptance is a legal act; "payment terms" and "delivery terms" are facts, not these
    r"(?:terms\s*(?:and|&|/)\s*conditions|terms\s+of\s+(?:use|service|sale|business|engagement|participation)|t\s*&\s*cs?|"
    r"terms|conditions|privacy\s+(?:policy|notice|statement)|(?:acceptable|fair)\s+use\s+policy|code\s+of\s+conduct|eula|"
    r"licen[cs]e\s+agreement|(?:master|services?|user|customer|data\s+processing|non-?disclosure|confidentiality)\s+agreement|"
    r"nda|dpa|disclaimer|liability|responsibility|declaration|statement|policy|policies|agreement|contract)"
)

_FIRST_PERSON = (  # "I agree", "We hereby certify"
    rf"\b(?:i|we)\s+{_ADV}(?:agree|consent|certify|attest|declare|acknowledge|affirm|authori[sz]e|warrant|confirm|understand)\b"
)
_SECOND_PERSON = (  # "By submitting you agree", "Do you consent"; "confirm" and "understand" only before "that"
    rf"\byou\s+{_ADV}(?:agree|consent|certify|attest|declare|acknowledge|affirm|authori[sz]e)\b|"
    rf"\byou\s+{_ADV}(?:confirm|understand)\s+that\b"
)
_ACCEPT_ANSWER = rf"{_ENUM}(?:yes\W+)?(?:i|we)\s+(?:do\s+not\s+|don'?t\s+)?(?:accept|decline|disagree)\W*$"  # an option such as "I accept"
_ACCEPT_LEGAL = (  # accepting a legal document; "Do you accept credit cards?" and "Accepted payment terms" are facts
    rf"\baccept(?:s|ed|ing|ance)?\s+(?:of\s+)?(?:(?:the|these|our|your|all|such|this)\s+)?{_LEGAL_DOC}\b|"
    r"\b(?:terms|conditions|policy|agreement|disclaimer)\s+(?:accepted|acceptance)\b"
)
_READ_AND_AGREE = (
    r"\bread\s+and\s+(?:agree|accept|understand|understood|acknowledge)\b|"
    r"\bhave\s+read\s+(?:and\s+\w+\s+)?(?:the|our|these|this)\b"
)
_BARE_VERBS = r"\b(?:agrees?|certif(?:y|ies)|declar(?:e|es|ing)|attests?|affirms?)\b"  # almost never a statement of fact
_CONSENT = (  # consenting, not asking about consent practices ("Do you obtain consent?", "Consent management platform")
    rf"{_ENUM}(?:your\s+|my\s+|our\s+|written\s+)?consent(?:\s+to\b|\W*$)|"
    rf"\byou\s+(?:give|provide|grant)\s+(?:your\s+)?consent\b|\b(?:give|provide|grant)\s+(?:your|my|our)\s+consent\b|"
    rf"{_ENUM}(?:please\s+)?(?:give|provide|grant)\s+(?:your\s+)?consent\b|\b(?:please|kindly)\s+(?:consent|acknowledge)\b"
)
_ACKNOWLEDGE = (  # not "Mean time to acknowledge a security incident"
    r"\backnowledg(?:e|es|ing|ement|ment)s?\s+(?:that|receipt\s+of|of\s+receipt|and\s+(?:agree|accept)|"
    r"(?:of\s+)?(?:the\s+)?(?:terms|conditions|declaration|statement|policy|risks?|disclaimer|addend\w*))\b"
)
_ACCURACY = (  # vouching for the form itself, with or without a verb: "Is the information provided accurate?"
    r"\b(?:above|provided|given|submitted|supplied|herein|foregoing|this\s+(?:form|application|questionnaire|submission|declaration|statement|response)|"
    r"(?:the|my|our|your|these|those)\s+(?:answers?|responses?|statements?|information(?!\s+(?:security|technology|systems?|management|governance|classification|asset))))"
    r"\b[^.?!]{0,60}\b(?:true|truth|accurate|correct|truthful|complete)\b|"
    r"\b(?:true|accurate|truthful)(?:\s+and\s+\w+)?\s+(?:statement|declaration|account|representation)\b"  # "a true and complete statement"
)
_CONFIRM = (  # "confirm the accuracy of ...", "confirm that you ..."; not "Confirmation email" or "Confirm email"
    r"\bconfirm(?:s|ing|ation)?\s+(?:of\s+|that\s+)(?:(?:the|all)\s+)?(?:accuracy|truth|correctness|completeness|validity|information|answers?|statements?|eligibility|compliance|authority)\b|"
    r"\bconfirmation\s+of\s+(?:eligibility|compliance|authority)\b|"
    r"\bconfirm(?:s|ing)?\s+that\s+(?:you|we|i|your|our)\b"
)
_AUTHORISE = (  # not "Authorization method", "role-based authorization" or "Name of authorised signatory" (a fact from the source)
    r"\bauthori[sz]ation\s+(?:to|for)\s+(?:release|contact|verify|obtain|disclose|share|process|conduct|check|investigate|perform|collect|use|access|inspect|audit)\b|"
    r"\bauthori[sz]ed\s+(?:to\s+(?:sign|bind|act|represent|submit)|signature)\b|"
    rf"\b(?:i|we)\s+(?:am|are)\s+(?:a\s+|an\s+|the\s+)?{_ADV}authori[sz]ed\b|"
    r"\bauthori[sz]e\s+(?:us|this|the\s+(?:organi[sz]ation|company|bank|institution|release|disclosure|verification|credit|use))\b"
)
_WARRANT = (  # "Does the bidder warrant that it has full authority" as well as "we warrant that"
    rf"\b(?:you|we|i)\s+{_ADV}(?:warrant|represent|swear)\s+(?:that|and)\b|\bwarrants?\s+that\b|\bself-?(?:certif\w*|declar\w*|attest\w*)\b"
)
_UNDERTAKE = r"\bundertak(?:e|es|ing)\s+to\b"  # a promise; "Do you undertake penetration testing?" is a fact and has no "to"
_BOUND = rf"\bbound\s+by\s+(?:the|these|our|this|all|its|their)\s+{_LEGAL_DOC}\b"  # "Are you willing to be bound by the code of conduct?"
_READ_LEGAL = rf"\b(?:you|we|i)\s+(?:have\s+)?read\s+(?:and\s+\w+\s+)?(?:the|our|these|this)\s+{_LEGAL_DOC}\b"  # "Have you read the privacy notice?"
_PERMISSION = rf"\b(?:give|grant)\s+(?:us\s+|the\s+\w+\s+)?permission\b|{_ENUM}permission\s+(?:to|for)\b"
_SIGNING = (  # signing as an act or a signature field; not "Sign-in", "Single sign-on", "code signing", "digital signature algorithm"
    r"\bsign(?:s|ed|ing)?\s+(?:here|below|above|on\s+behalf|and\s+date|to\s+(?:confirm|certify|acknowledge|agree|accept|attest|declare|submit|authori[sz]e|bind))\b|"
    rf"{_ENUM}signed\s+by\b|"
    r"\b(?:type|enter|print|write|initial)\b[^.?!]{0,40}\bto\s+(?:sign|certify|attest|acknowledge|agree|accept|declare|consent|confirm)\b|"
    r"\binitials?\s+(?:here|below|above)\b|"
    rf"\be-signature\b{_NOT_TECHNIQUE}|"
    r"\bto\s+sign\s+(?:this|the\s+(?:form|declaration|statement|document|agreement|application)|below|here|electronically|digitally)\b|"
    r"\b(?:authori[sz]ed|your|company|corporate|legal|official|electronic|e-|typed|printed|handwritten|applicant'?s?|officer'?s?|director'?s?|"
    rf"signatory'?s?|representative'?s?|witness)\s+signature\b{_NOT_TECHNIQUE}|"
    rf"{_ENUM}signature\b{_NOT_TECHNIQUE}|"
    r"\bsignature\s+(?:of|by|line|block|here)\b|"
    r"\bdate\s+(?:of\s+)?(?:signature|signing)\b|\bdate\s+signed\b"
)
_CERTIFICATION = (  # "Certification that ...", "Non-collusion certification"; not "ISO 27001 certification" or "Certifications held"
    r"\bnon-?collusion\b|"
    r"\bcertification\s+(?:that|statement|of\s+(?:accuracy|truth|correctness|completeness|non-?\w+|independent\w*|eligibility|compliance))\b"
)
_AGREEMENT_TO = r"\bagreement\s+(?:to|that)\b"  # "Agreement to terms"; not "Agreement number" or "Service Level Agreement"
_DECLARATION = r"(?<!customs )(?<!tax )(?<!vat )(?<!import )(?<!export )(?<!income )\bdeclarations?\b(?!\s+of\s+conformity)"

_ATTESTATION = re.compile("|".join([
    _FIRST_PERSON, _SECOND_PERSON, _ACCEPT_ANSWER, _ACCEPT_LEGAL, _READ_AND_AGREE, _BARE_VERBS, _CONSENT, _ACKNOWLEDGE,
    _ACCURACY, _CONFIRM, _AUTHORISE, _WARRANT, _UNDERTAKE, _BOUND, _READ_LEGAL, _PERMISSION, _SIGNING, _CERTIFICATION,
    _AGREEMENT_TO, _DECLARATION,
]), re.IGNORECASE)

# Option labels are checked with the first-person subset only: "I agree" / "I accept" / "I have read and accept" under a neutral
# label is an agreement, but a bare "Agree" is a Likert point and "Accepted" is a status.
_OPTION_ATTESTATION = re.compile("|".join([_FIRST_PERSON, _ACCEPT_ANSWER, _ACCEPT_LEGAL, _READ_AND_AGREE]), re.IGNORECASE)
# ... except when the bare words are the whole choice: a control that offers only "Agree / Disagree" (or "Accept / Decline")
# is a yes/no on an agreement, not a scale. Three or more points (strongly agree, neutral, ...) are still a scale.
_BINARY_AGREEMENT = (
    frozenset({"agree", "disagree"}), frozenset({"accept", "decline"}), frozenset({"accept", "reject"}),
    frozenset({"accepted", "declined"}), frozenset({"accepted", "rejected"}),
)
_PLACEHOLDER_OPTION = re.compile(r"^\W*(?:select|choose|pick|please).*$|^\W*$", re.IGNORECASE)


def _is_binary_agreement(control) -> bool:
    words = {re.sub(r"[^a-z]+", " ", o.label.casefold()).strip() for o in control.options if not _PLACEHOLDER_OPTION.match(o.label)}
    return frozenset(words) in _BINARY_AGREEMENT


# A heading applies to every control after it until the next heading, so only headings that name the act itself count
# ("Declaration", "Terms and conditions", "Signature"). "Service Level Agreement", "Authentication & Authorization" and
# "Signature-based detection" are topics, not attestations.
_ATTESTATION_HEADING = re.compile(
    rf"{_ENUM}(?:(?:final|applicant|supplier|vendor|bidder|company|legal|signed|compliance|general|data\s+protection|privacy|gdpr|authori[sz]ed|statutory)\s+)?"
    rf"(?:declarations?|attestations?|acknowledg(?:e)?ments?|undertakings?|signatures?{_NOT_TECHNIQUE}|terms\s*(?:and|&)\s*conditions|"
    r"certification\s+(?:statement|of\s+accuracy))\b|"
    rf"{_ENUM}(?:authori[sz]ations?\s+(?:and|&)\s+)?consents?\W*$",
    re.IGNORECASE,
)

# Tier 2: broad stems, the wording that earlier versions of this module flagged on every control.
_ATTESTATION_STEMS = re.compile(
    r"\b(?:agree(?:ment)?|consent|acknowledg(?:e|es|ement|ment)|authori[sz](?:e|es|ation|ed|ing)|declar(?:e|es|ation)|"
    r"attest(?:s|ed|ing)?|certif(?:y|ies|ying)|affirm(?:s|ation)?|accept(?:ance)?|confirm(?:ation)?|understand(?:ing)?|"
    r"permission|undertak(?:es|ing|ings)|warrants?|terms|conditions|privacy\s+policy)\b",
    re.IGNORECASE,
)
# Compounds in which those stems name a fact or a document, not an act. Anything not listed still goes to review.
_FACTUAL_COMPOUND = re.compile("|".join([
    r"(?:service[- ]level|master(?:\s+services?)?|data\s+processing|non-?disclosure|confidentiality|licen[cs]e|subscription|framework|"
    r"supply|partnership|reseller|distribution|software|customer|vendor|supplier|employment|maintenance|support|lease|sla|dpa|nda|msa)\s+agreements?",
    r"agreements?\s+(?:number|no\.?|date|id|ref(?:erence)?|version|type|term|length|start|end|expiry|status|document|template|period|duration|value)",
    r"(?:order|booking|email|e-mail|shipping|delivery|payment|registration|reservation|appointment|receipt|purchase)\s+confirmations?",
    r"confirmation\s+(?:email|e-mail|number|no\.?|code|message|link|page|letter|time|contact|id|status|date|sms|notification)",
    r"confirm\s+(?:email|e-mail|password)",
    r"authori[sz]ation\s+(?:method|model|policy|mechanism|controls?|service|server|flow|framework|process|system|protocol|header|token|code|level|scheme|type|rules?)",
    r"(?:role|attribute|policy|permission)[- ]based\s+(?:access|authori[sz]ation)",
    r"authentication\s*(?:and|&|/|,)\s*authori[sz]ation",
    r"(?:multi[- ]?factor|two[- ]factor|2fa|mfa)\s+authori[sz]ation",
    r"authori[sz]ed\s+(?:reseller|dealer|distributor|partner|service|representative|user|personnel|person|access|vendor|subcontractor|supplier|agent|installer|importer|signatory)s?",
    r"consent\s+(?:management|banner|withdrawal|records?|logs?|mechanism|platform|form|tracking|tool|period|retention)",
    r"cookie\s+consent",
    r"(?:operating|storage|working|environmental|weather|ambient|site|road|market|economic|trading|trade|payment|delivery|shipping|contract|"
    r"contractual|commercial|credit|pricing|price|warranty|lead[- ]time)\s+(?:terms|conditions)",
    r"(?:terms|conditions)\s+of\s+(?:payment|delivery|trade|supply|reference|employment)",
    r"terms\s+(?:start|end|date|length|version|url|link)",
    r"(?:incident|ticket|alert|support|response|request)\s+acknowledg\w*",
    r"time\s+to\s+acknowledg\w*",
    r"acknowledg\w*\s+(?:time|sla|window|period)",
    r"warrant\s+canary",
    r"permissions?\s+(?:model|management|policy|levels?|matrix|system|set|controls?|review)",
    r"(?:file|access|user|role|admin|folder)\s+permissions?",
]), re.IGNORECASE)
_AFFIRMATIVE_OPTION = re.compile(r"^\W*(?:yes|y|true|agree|accept|confirm|consent|i\s+\w+|we\s+\w+|checked|ticked)\b", re.IGNORECASE)
_QUESTION_FORM = re.compile(
    rf"\?\s*$|{_ENUM}(?:do|does|did|is|are|was|were|can|could|will|would|should|have|has|what|which|how|when|where|who)\b",
    re.IGNORECASE,
)


def _can_affirm(control) -> bool:
    """A checkbox, or a choice with a yes/agree option: the control could be answered with a bare "yes"."""
    if control.kind == "checkbox":
        return True
    return control.kind in ("radio", "select") and any(
        _AFFIRMATIVE_OPTION.match(o.label) or _AFFIRMATIVE_OPTION.match(o.value) for o in control.options
    )


def is_attestation(control, text: str) -> bool:
    """True when the question, its help text, placeholder, section heading, or (for choices) its option labels read as the
    respondent agreeing to, declaring, certifying, consenting to, signing, or vouching for something."""
    # each part on its own, so a pattern anchored to the start or end of a text means that text, not the joined string
    if any(_ATTESTATION.search(part) for part in (text, control.help_text, control.placeholder, control.section) if part):
        return True
    if _ATTESTATION_HEADING.search(control.section or ""):
        return True
    if any(_OPTION_ATTESTATION.search(o.label) or _OPTION_ATTESTATION.search(o.value) for o in control.options):
        return True
    if _is_binary_agreement(control):
        return True
    if _can_affirm(control) and (control.kind == "checkbox" or not _QUESTION_FORM.search(text)):
        return bool(_ATTESTATION_STEMS.search(_FACTUAL_COMPOUND.sub(" ", text)))
    return False


def _same_value(a: Any, b: Any) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _option_equals(control, value: Any) -> bool:
    """A dropdown/radio that really offers "None" or "N/A" may be answered with it."""
    v = str(value).strip().casefold()
    return any(v in (str(o.value).strip().casefold(), str(o.label).strip().casefold()) for o in control.options)


def _alts(cands: list[Candidate], skip: int = 0) -> list[dict]:
    return [{"source": c.path, "value": c.value, "score": c.score, **({"flags": c.flags} if c.flags else {}),
             **({"evidence": c.evidence} if c.evidence else {})}
            for c in cands[skip:3 + skip]]


def plan_question(question: Question, leaves: list[Leaf]) -> AnswerPlanItem:
    c = question.control
    base = {"question_id": question.question_id, "question": question.text, "field_type": c.kind, "required": c.required}

    def review(reason: str, cands: list[Candidate], confidence: float = 0.0) -> AnswerPlanItem:
        return AnswerPlanItem(**base, status="REVIEW", reason=reason, confidence=confidence, alternatives=_alts(cands))

    if c.disabled:
        return review("control is disabled", [])
    if is_attestation(c, question.text):
        return review(ATTESTATION_REASON, [])

    cands = retrieve(question, leaves)
    if not cands:
        return review("no matching value in the source data", [])

    top = cands[0]
    if top.score < MIN_CONFIDENCE:
        why = f" -- {'; '.join(top.flags)}" if top.flags else ""
        return review(
            f"best candidate {top.path!r} is too weak (score {top.score:.2f} < {MIN_CONFIDENCE}){why}", cands, top.score
        )

    if is_placeholder(top.value) and not _option_equals(c, top.value):
        return review(f"{top.path!r} holds the placeholder {top.value!r}, not an answer; a human must decide what it means",
                      cands, top.score)

    if len(cands) > 1:
        runner = cands[1]
        if top.score - runner.score < MIN_MARGIN and not _same_value(top.value, runner.value):
            return review(
                f"ambiguous: {top.path!r} and {runner.path!r} are about equally relevant but disagree",
                cands, top.score,
            )

    result = validate_answer(top.value, c)
    if not result.ok:
        return review(f"{top.path!r}: {result.reason}", cands, top.score)

    return AnswerPlanItem(
        **base, status="ANSWER", source=top.path, raw_value=top.value, answer=result.value,
        confidence=min(1.0, top.score), alternatives=_alts(cands, skip=1), evidence=list(top.evidence),
    )


def build_plan(questions: list[Question], leaves: list[Leaf]) -> list[AnswerPlanItem]:
    plans = [plan_question(q, leaves) for q in questions]
    # Two questions whose wording differs ONLY in a parenthetical qualifier, e.g. "Dropdown (select)" / "Dropdown (datalist)". Matching
    # drops parentheticals as hints, so both reduce to the same tokens and one source value would answer both, silently putting the
    # value meant for one control into the other. Such answers go to a human. (Questions that merely share tokens, such as
    # "Is SSO supported?" / "Do you support SSO?", are ordinary rephrasings of one fact and are not affected.)
    def split(text: str) -> tuple[str, str]:
        hints = " ".join(re.findall(r"\(([^)]*)\)", text)).lower().strip()
        return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", text)).strip().lower(), hints

    groups: dict[tuple[str, str], list[int]] = {}
    for i, (q, p) in enumerate(zip(questions, plans)):
        if p.status == "ANSWER" and p.source:
            groups.setdefault((split(q.text)[0], p.source), []).append(i)
    for idxs in groups.values():
        if len(idxs) > 1 and len({split(questions[i].text)[1] for i in idxs}) > 1:
            for i in idxs:
                plans[i] = replace(plans[i], status="REVIEW", answer=None, confidence=0.0,
                                   reason=(f"{len(idxs)} questions that differ only in a parenthetical qualifier matched the same source value "
                                           f"({plans[i].source!r}); it may belong to only one of them"),
                                   alternatives=[{"source": plans[i].source, "value": plans[i].raw_value, "score": plans[i].confidence}] + plans[i].alternatives)
    return plans
