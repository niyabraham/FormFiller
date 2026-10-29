"""Deterministic text normalisation shared by question understanding and
JSON retrieval. Both sides go through the *same* function, so "Number of
full-time employees?" and `company.full_time` end up in the same token space.

This is the MVP "alias/keyword normalisation" level. It is a few dozen
lines on purpose: a synonym table is cheap to read, test and extend, and
every miss it causes lands in REVIEW rather than in a wrong answer.
"""

from __future__ import annotations

import re

# Words that carry no meaning for matching (dropped on both sides).
STOPWORDS = {
    "the", "a", "an", "of", "your", "you", "do", "does", "is", "are", "what", "how",
    "many", "much", "please", "number", "provide", "enter", "if", "any",
    "for", "in", "to", "and", "or", "with", "on", "by", "our", "we", "us", "have",
    "has", "list", "give", "specify", "select", "choose", "which", "who",
    "that", "this", "be", "at", "as", "from", "it", "its", "required",
}
# Phase 3A: "total", "state" and "optional" are no longer stopwords. "total" and "state" are real
# key names (customers.total, address.state); "optional" is polarity (see NEGATORS) -- dropping it
# made "Is MFA optional?" identical to "Is MFA required?". "state" as an imperative verb ("Please
# state your name") is still dropped, by context, in tokenize().

# Scope words: if the question says "full-time employees", a key that does not
# carry that scope (e.g. plain `employees`) answers a *different* question
# (the total). Retrieval penalises candidates missing a scope word the
# question contains. Found by testing the guide's own example (a plain token
# overlap scored `employees` and `full_time` as an exact tie). Small and
# deliberately conservative: a miss here sends the item to REVIEW.
QUALIFIERS = {
    "fulltime", "parttime", "permanent", "temporary", "annual", "legal", "registered",
    "billing", "mailing", "primary", "secondary", "previous", "former", "current",
    "headquarter", "trading",
    # Phase 3A: words that narrow *which entity or population* is meant. A key that does not carry
    # them answers a different question (the total, the company itself), so they must be explained.
    "parent", "subsidiary", "affiliate", "holding", "ultimate", "sister",
    "production", "domestic", "foreign", "international", "global", "regional",
}

# Polarity markers. A question and the key it is matched to must carry the *same* markers: "Is MFA
# optional?" must not read `mfa_required`, "Is SSO disabled?" must not read `sso_enabled`. Uncertain
# cases are sent to REVIEW rather than inverted. ("no" is deliberately absent: "Registration No.")
NEGATORS = {"not", "non", "optional", "disabled", "disable", "without", "unsupported", "never", "inapplicable",
            # Phase 3B-A: "Does the organisation lack a whistleblower policy?" read `whistleblower_policy: true`
            # and answered "yes". Nothing is inverted: the marker only has to match on both sides, else REVIEW.
            "lack", "lacking", "absence", "absent"}

# A generic noun a key may leave implicit: `company.full_time` answers "full-time employees". Such a word is not
# held against a key (see retrieve.assess_leaf); every other unexplained word is a modifier the key must carry.
IMPLICIT_NOUNS = {"employee"}

# "in total" widens a question: it is dropped unless the key carries "total" itself (customers.total).
NEUTRAL = {"total"}
# "your organization" / "company" is the form-filler referring to itself. It still scores (a key under
# `company.` is better evidence), but a key that lacks it is not penalised for it. A genuinely different
# entity is a QUALIFIERS word ("parent", "subsidiary"), which stays mandatory.
SELF_REFERENCE = {"company"}

# Requirement C: words that name a DIFFERENT legal entity than the one filling in the form. A fact stored under such a key
# (`subsidiaries.0.soc2_certified`, `affiliates.0.pci_dss_compliant`, `parent_company.iso27001`) answers only a question that
# names that entity too; otherwise a subsidiary's certification would be attributed to the company itself. (The inverse, a
# question naming the scope while the key lacks it, is already handled by QUALIFIERS.)
ENTITY_SCOPE = {"subsidiary", "affiliate", "parent", "holding", "sister"}

# Requirement C: security/compliance TOPICS. When a question names a topic and the key names a different one, they are about
# different things even if other words match ("Date of last disaster recovery test" is not `pentest.last_date`). Found on the
# development benchmark once "pentest" was expanded to "penetration test" (docs/MATCHING.md).
TOPICS = {"penetration", "vulnerability", "disaster", "continuity", "incident", "encryption", "backup", "audit", "training",
          "insurance", "malware", "phishing", "patch", "firewall", "logging", "retention"}

# Words that say a question (or the form section it sits in) is about an organisation. A generic `name` key under an
# organisation key (`company.name`, `vendor.name`) answers only such a question: "Name", "Full name" or "Contact name"
# would otherwise be answered with the company's name. ("organization", "business", "firm" are already "company".)
ORGANISATION_WORDS = {"company", "vendor", "supplier", "contractor", "institution", "employer", "entity", "enterprise",
                      "corporation", "corp"}

# Phrase fixes applied before splitting.
_PHRASES = [
    (re.compile(r"\be[\s-]?mail\b"), "email"),
    (re.compile(r"\bfull[\s_-]?time\b"), "fulltime"),
    (re.compile(r"\bpart[\s_-]?time\b"), "parttime"),
    (re.compile(r"\bdate of birth\b"), "birth date"),
    # Name parts are one concept each, not "name" plus a modifier. Left as two tokens, `company.name` explains half of
    # "First name" and scores 0.67, so a company name was typed into a person's field. "Surname" (one word) and
    # "last_name" / "lastName" (any key style) land on the same token as "Last name".
    (re.compile(r"\b(?:first|given|fore)[\s_-]?name\b"), "firstname"),
    (re.compile(r"\bmiddle[\s_-]?name\b"), "middlename"),
    (re.compile(r"\b(?:last|family|sur)[\s_-]?name\b"), "lastname"),
    # spelled-out acronyms meet their short form on both sides (question text and JSON keys)
    (re.compile(r"\bmulti[\s-]?factor(?:\s+authentication)?\b"), "mfa"),
    (re.compile(r"\bsingle[\s-]?sign[\s-]?on\b"), "sso"),
    (re.compile(r"\bdata protection officer\b"), "dpo"),
    (re.compile(r"\bchief information security officer\b"), "ciso"),
    (re.compile(r"\bpersonally identifiable information\b"), "pii"),
    # Requirement C, domain terms: a standard's name is one concept however it is written, so "SOC 2", "soc2" and "SOC II"
    # meet, and "ISO/IEC 27001", "ISO 27001" and `iso27001` meet. (A key such as `soc2_type2` used to share nothing with the
    # question "SOC 2 Type II": "soc", "2" vs "soc2", "type2".)
    (re.compile(r"\bsoc[\s_-]*(?:2|ii)\b"), "soc2"),
    (re.compile(r"\bsoc[\s_-]*(?:1|i)\b(?![\s_-]*(?:agree|accept|certify|confirm|consent))"), "soc1"),
    (re.compile(r"\btype[\s_-]*(?:2|ii)\b"), "type2"),
    (re.compile(r"\btype[\s_-]*(?:1|i)\b(?![\s_-]*(?:agree|accept|certify|confirm|consent|have|am))"), "type1"),
    (re.compile(r"\biso[\s_/-]*(?:iec[\s_/-]*)?(\d{4,5})\b"), r"iso\1"),
    (re.compile(r"\bpci(?:[\s_-]*dss)?\b"), "pcidss"),  # "PCI" alone means PCI DSS in questionnaires and their data
    (re.compile(r"\bcyber[\s_-]*essentials\b"), "cyberessentials"),
    # abbreviations that security questionnaires and their source data use interchangeably with the spelled-out phrase
    (re.compile(r"\bincident[\s_-]+response\b"), "incident response"),
    (re.compile(r"\bir(?=[\s_-]+(?:plan|team|process|policy|procedure|owner|playbook)s?\b)"), "incident response"),
    (re.compile(r"\bbcp\b"), "business continuity plan"),
    (re.compile(r"\bdrp\b"), "disaster recovery plan"),
    (re.compile(r"\bdr(?=[\s_-]+(?:plan|rto|rpo|site|test)s?\b)"), "disaster recovery"),
    (re.compile(r"\brto\b"), "recovery time objective"),
    (re.compile(r"\brpo\b"), "recovery point objective"),
    (re.compile(r"\bpen[\s_-]?tests?\b|\bpentests?\b"), "penetration test"),
    (re.compile(r"\bvulns?\b"), "vulnerability"),
    (re.compile(r"\b(?:2\s?fa|two[\s_-]?factor(?:\s+authentication)?)\b"), "mfa"),  # "2FA" arrives as "2 fa" (camelCase split)
    (re.compile(r"\bhow\s+(?:often|frequently)\b"), "frequency"),
]

# "State" the noun (address.state) vs "state" the imperative ("Please state your name").
_STATE_VERB = re.compile(r"\bstate\b(?=\s+(?:the|your|our|how|whether|if|any|a|an|which|what|number|name|details?)\b)")
_ACRONYM = re.compile(r"[A-Z][A-Z0-9]{1,6}")
_NOT_ACRONYMS = {"optional", "required"}

# canonical token <- surface tokens (applied after stemming). A value may
# expand to several tokens.
SYNONYMS: dict[str, list[str]] = {
    "staff": ["employee"], "headcount": ["employee"], "personnel": ["employee"],
    "workforce": ["employee"], "worker": ["employee"],
    "url": ["website"], "site": ["website"], "web": ["website"], "homepage": ["website"],
    "telephone": ["phone"], "tel": ["phone"], "mobile": ["phone"], "cell": ["phone"],
    "dob": ["birth", "date"], "birthdate": ["birth", "date"], "birthday": ["birth", "date"],
    "organization": ["company"], "organisation": ["company"], "org": ["company"],
    "firm": ["company"], "business": ["company"],
    "zip": ["postal"], "postcode": ["postal"],  # ("surname" is a phrase fix above: it must meet "last name" as one token)
    "hq": ["headquarter"],
    # the two inflections the Phase 2 benchmark demonstrated (supported/support, encrypted/encryption)
    "supported": ["support"], "encrypted": ["encryption"], "encrypt": ["encryption"],
    # Requirement C: how often something happens
    "cadence": ["frequency"], "frequently": ["frequency"], "often": ["frequency"],
}


# --- period scope (Phase 3B-A) -------------------------------------------------------------------
# "Gross fees, two financial years ago" must not read `gross_fees_last_financial_year`. A period is a
# point in time ("-2y" = two years back, "0y" = this year, "2024"), taken from the raw text of the question
# and of the key path. "last name" is not a period: "last" only counts next to a period noun.
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10}
_ADJ = r"(?:(?:financial|fiscal|calendar|tax|trading|accounting)\s+)?"
_UNIT = r"(year|quarter|month)s?"
_RELATIVE = re.compile(rf"\b(last|previous|prior|preceding|current|this|next)\s+{_ADJ}{_UNIT}\b")
_AGO = re.compile(rf"\b(\d{{1,2}}|{'|'.join(_NUMBER_WORDS)})\s+{_ADJ}{_UNIT}\s+ago\b")
_YEAR = re.compile(r"\b(?:19|20)\d\d\b")
_SIGN = {"last": "-1", "previous": "-1", "prior": "-1", "preceding": "-1", "current": "0", "this": "0", "next": "+1"}


def period_markers(text: str) -> frozenset[str]:
    """Points in time named by `text`: {"-1y"} last year, {"-2y"} two years ago, {"0y"} this year,
    {"+1y"} next year, {"2024"} a calendar year. A window ("the last 5 years") is not a point: empty."""
    t = text.lower().replace("_", " ")
    out = {f"{_SIGN[m.group(1)]}{m.group(2)[0]}" for m in _RELATIVE.finditer(t)}
    for m in _AGO.finditer(t):
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1)]
        out.add(f"-{n}{m.group(2)[0]}")
    out |= set(_YEAR.findall(t))
    return frozenset(out)


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and re.search(r"(?:ss|x|ch|sh)es$", token):
        return token[:-2]  # processes -> process (was "processe"), branches -> branch; sizes/caches keep the plain rule
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case, split camelCase / snake_case / punctuation, drop stopwords,
    stem, expand synonyms. Order-preserving, duplicates removed. (List
    indices in JSON paths are skipped by the caller, not here.)"""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)  # camelCase -> camel Case
    acronyms = [m.group(1).lower() for m in re.finditer(r"\(\s*([^)]*?)\s*\)", text)
                if _ACRONYM.fullmatch(m.group(1)) and m.group(1).lower() not in _NOT_ACRONYMS]
    text = re.sub(r"\([^)]*\)", " ", text)  # other parenthetical hints, e.g. "(DD/MM/YYYY)"
    text = text.lower().replace("_", " ")  # snake_case: "_" is a word character, so \b would not fire
    text = _STATE_VERB.sub(" ", text)
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    out: list[str] = []
    for raw in re.split(r"[^a-z0-9]+", text) + acronyms:
        if not raw or raw in STOPWORDS:
            continue
        tok = _stem(raw)
        if tok in STOPWORDS:
            continue
        for t in SYNONYMS.get(tok, [tok]):
            if t not in out:
                out.append(t)
    return out
