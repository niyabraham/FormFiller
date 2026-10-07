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
    "many", "much", "please", "number", "total", "provide", "enter", "if", "any",
    "for", "in", "to", "and", "or", "with", "on", "by", "our", "we", "us", "have",
    "has", "list", "give", "state", "specify", "select", "choose", "which", "who",
    "that", "this", "be", "at", "as", "from", "it", "its", "required", "optional",
}

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
}

# Phrase fixes applied before splitting.
_PHRASES = [
    (re.compile(r"\be[\s-]?mail\b"), "email"),
    (re.compile(r"\bfull[\s_-]?time\b"), "fulltime"),
    (re.compile(r"\bpart[\s_-]?time\b"), "parttime"),
    (re.compile(r"\bdate of birth\b"), "birth date"),
]

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
}


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case, split camelCase / snake_case / punctuation, drop stopwords,
    stem, expand synonyms. Order-preserving, duplicates removed. (List
    indices in JSON paths are skipped by the caller, not here.)"""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)  # camelCase -> camel Case
    text = re.sub(r"\([^)]*\)", " ", text)  # parenthetical hints, e.g. "(DD/MM/YYYY)"
    text = text.lower()
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    out: list[str] = []
    for raw in re.split(r"[^a-z0-9]+", text):
        if not raw or raw in STOPWORDS:
            continue
        tok = _stem(raw)
        if tok in STOPWORDS:
            continue
        for t in SYNONYMS.get(tok, [tok]):
            if t not in out:
                out.append(t)
    return out
