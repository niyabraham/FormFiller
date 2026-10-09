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
NEGATORS = {"not", "non", "optional", "disabled", "disable", "without", "unsupported", "never", "inapplicable"}

# "in total" widens a question: it is dropped unless the key carries "total" itself (customers.total).
NEUTRAL = {"total"}
# "your organization" / "company" is the form-filler referring to itself. It still scores (a key under
# `company.` is better evidence), but a key that lacks it is not penalised for it. A genuinely different
# entity is a QUALIFIERS word ("parent", "subsidiary"), which stays mandatory.
SELF_REFERENCE = {"company"}

# Phrase fixes applied before splitting.
_PHRASES = [
    (re.compile(r"\be[\s-]?mail\b"), "email"),
    (re.compile(r"\bfull[\s_-]?time\b"), "fulltime"),
    (re.compile(r"\bpart[\s_-]?time\b"), "parttime"),
    (re.compile(r"\bdate of birth\b"), "birth date"),
    # spelled-out acronyms meet their short form on both sides (question text and JSON keys)
    (re.compile(r"\bmulti[\s-]?factor(?:\s+authentication)?\b"), "mfa"),
    (re.compile(r"\bsingle[\s-]?sign[\s-]?on\b"), "sso"),
    (re.compile(r"\bdata protection officer\b"), "dpo"),
    (re.compile(r"\bchief information security officer\b"), "ciso"),
    (re.compile(r"\bpersonally identifiable information\b"), "pii"),
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
    "surname": ["last", "name"], "zip": ["postal"], "postcode": ["postal"],
    "hq": ["headquarter"],
    # the two inflections the Phase 2 benchmark demonstrated (supported/support, encrypted/encryption)
    "supported": ["support"], "encrypted": ["encryption"], "encrypt": ["encryption"],
}


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
