"""Reasoning layer, step 2a: soft term alignment between a question and one candidate JSON key.

Retrieval scores a question against every JSON leaf by token overlap (retrieve.py). Overlap alone misses obvious
paraphrases ("workforce size" vs `employee_count`, "electronic logging devices" vs `eld`, "USDOT" vs `dotNumber`).
This module finds *principled* equivalences for one (question, leaf) pair and rewrites the question's tokens onto the
leaf's tokens, so the unchanged scoring and every safety cap (scope, polarity, period, counting, context) run on the
aligned tokens. Matches made here are SOFT: each carries a weight below 1.0 and the final score is multiplied by the
weakest weight used, so an exact match always outranks a soft one, and the evidence is recorded for the reviewer.

Mechanisms (each can be switched off for ablation: `Config`):

  measure      handled in retrieve.assess_leaf, not here: in a counting question a measure word (count, number, size,
               quantity) is implicit on both sides, so `employee_count` answers "how many employees" and a question's
               "size" is not an unexplained modifier. It never adds words to the question (that would dilute the
               explained-fraction safety check).
  stem         derivational variants: certification / certified, incorporated / incorporation.  0.95
  lexicon      words that name the same kind of fact, from formfill/web/lexicon.json.          0.90
  initialism   a leaf token spelled by the initials of consecutive question words ("electronic logging device" -> eld),
               or an acronym in the question whose spelled-out form is also in the question.   0.90
  abbreviation a prefix of at least 3 letters ("pen" ~ "penetration") or the short word "id".   0.85
  compound     a 1-2 letter prefix glued to the leaf word ("usdot" ~ "dot").                    0.85
  provider     an optional pluggable `TermProvider` (e.g. a WordNet or embedding backend). None by default.

Nothing here chooses an answer: it only decides which words count as explained. Candidate selection, thresholds,
ambiguity and validation stay in retrieve.py / plan.py / validate.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

LEXICON_PATH = Path(__file__).with_name("lexicon.json")

MEASURE = frozenset({"count", "number", "total", "size", "quantity"})

W_MEASURE, W_STEM, W_LEXICON, W_INITIALISM, W_ABBREV, W_COMPOUND = 1.0, 0.95, 0.90, 0.90, 0.85, 0.85


class TermProvider(Protocol):
    """Optional extra source of term equivalence (WordNet, embeddings, ...). Returns a weight in (0, 1) or 0 for 'no'."""

    name: str

    def similarity(self, question_term: str, leaf_term: str) -> float: ...


@dataclass(frozen=True)
class Config:
    stem: bool = True
    lexicon: bool = True
    initialism: bool = True
    abbreviation: bool = True
    compound: bool = True
    provider: TermProvider | None = None
    provider_min: float = 0.75  # a provider's similarity below this is ignored


DEFAULT = Config()
OFF = Config(stem=False, lexicon=False, initialism=False, abbreviation=False, compound=False)


@dataclass
class Alignment:
    tokens: set[str]  # question tokens after rewriting onto the leaf's tokens
    weight: float = 1.0  # weakest link used; multiplies the leaf's score
    links: list[str] = field(default_factory=list)  # human-readable: "'workforce' ~ 'employee' (lexicon 0.90)"


# ---- derivational stemming (alignment only; the shared tokenizer is unchanged) -------------------------------------------
_SUFFIXES = sorted(["ification", "ication", "ifications", "ified", "ifies", "ify", "ations", "ation", "ated", "ates", "ate",
                    "ments", "ment", "ings", "ing", "ized", "ised", "ize", "ise", "ied", "ies", "ed", "ers", "er", "ors", "or",
                    "ly", "ity", "ive", "able", "ous", "ion", "ions"], key=len, reverse=True)


def _tense(word: str) -> str:
    return "ing" if word.endswith("ing") else "ed" if word.endswith(("ed", "ied")) else ""


def same_stem(a: str, b: str) -> bool:
    """Derivational variants of one word (certification / certified). Words that differ in tense ("opening" = planned or
    in progress, "opened" = done) are not variants: that changes which fact is asked for."""
    if a == b or len(a) < 5 or len(b) < 5 or dstem(a) != dstem(b):
        return False
    return not (_tense(a) and _tense(b) and _tense(a) != _tense(b))


def dstem(word: str) -> str:
    for s in _SUFFIXES:
        if word.endswith(s) and len(word) - len(s) >= 4:
            return word[: -len(s)]
    return word


# ---- lexicon ------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _lexicon() -> dict:
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _group_index() -> dict[str, int]:
    from formfill.web.tokens import _stem

    idx: dict[str, int] = {}
    for gi, group in enumerate(_lexicon()["synonym_groups"]):
        for w in group:
            for f in _forms(_stem(w.lower())):
                idx.setdefault(f, gi)
    return idx


def lexicon_phrases() -> list[tuple[re.Pattern, str]]:
    return [(re.compile(p["pattern"]), p["replace"]) for p in _lexicon()["phrases"]]


def light_words() -> frozenset[str]:
    return frozenset(_lexicon()["light_words"])


def _forms(w: str) -> set[str]:
    """Inflected spellings of one word: enable / enabled / enabling all reach the same entry."""
    one_e = lambda x: x[:-1] if x.endswith("e") else x
    return {w, dstem(w), one_e(w), one_e(dstem(w))}


def _same_group(a: str, b: str) -> bool:
    idx = _group_index()
    ga = {idx[f] for f in _forms(a) if f in idx}
    gb = {idx[f] for f in _forms(b) if f in idx}
    return bool(ga & gb)


# ---- the alignment ------------------------------------------------------------------------------------------------------
def _initials(seq: list[str]) -> str:
    return "".join(t[0] for t in seq)


def _runs(seq: list[str], length: int):
    for i in range(len(seq) - length + 1):
        yield i, seq[i : i + length]


def align(q_seq: list[str], leaf_tokens: frozenset[str], is_count: bool, cfg: Config = DEFAULT,
          parent_tokens: frozenset[str] = frozenset()) -> Alignment:
    """Rewrite the question's tokens onto the key's words (`leaf_tokens`, and the words of its parent path) where a
    principled equivalence exists. `q_seq` is the ordered token list of the question (concept_tokens)."""
    leaf_tokens = leaf_tokens | parent_tokens
    q = set(q_seq)
    out = Alignment(tokens=q)
    weights: list[float] = []

    def link(msg: str, w: float) -> None:
        out.links.append(f"{msg} ({w:.2f})")
        weights.append(w)

    free_leaf = [t for t in leaf_tokens if t not in q]  # leaf words the question does not already contain
    # question words that already match this leaf exactly stay; only the rest may be consumed by a soft match
    consumable = [t for t in q_seq if t not in leaf_tokens and t in q]

    for L in sorted(free_leaf):
        if L in q:
            continue
        done = False
        # initialism: leaf token spelled by consecutive question words
        if cfg.initialism and 3 <= len(L) <= 6 and L.isalpha():
            for _, run in _runs(q_seq, len(L)):
                if _initials(run) == L and all(t in consumable for t in run):
                    for t in run:
                        q.discard(t)
                        consumable.remove(t)
                    q.add(L)
                    link(f"'{' '.join(run)}' spells '{L}'", W_INITIALISM)
                    done = True
                    break
        if done:
            continue
        for t in list(consumable):
            kind, w = None, 0.0
            if cfg.stem and same_stem(t, L):
                kind, w = "stem", W_STEM
            elif cfg.lexicon and _same_group(t, L):
                kind, w = "lexicon", W_LEXICON
            elif cfg.abbreviation and t != L and (
                    (len(t) >= 3 and len(L) >= len(t) + 3 and L.startswith(t)) or
                    (len(L) >= 3 and len(t) >= len(L) + 3 and t.startswith(L)) or
                    (t == "id" and L.startswith("identif"))):
                kind, w = "abbreviation", W_ABBREV
            elif cfg.compound and len(L) >= 3 and t.endswith(L) and 1 <= len(t) - len(L) <= 2 and t.isalpha():
                kind, w = "compound", W_COMPOUND
            elif cfg.provider is not None:
                s = cfg.provider.similarity(t, L)
                if s >= cfg.provider_min:
                    kind, w = f"provider:{cfg.provider.name}", min(s, 0.8)
            if kind:
                q.discard(t)
                consumable.remove(t)
                q.add(L)
                link(f"'{t}' ~ '{L}' [{kind}]", w)
                break

    # an acronym in the question whose own expansion is also in the question: "Legal Entity Identifier (LEI)"
    if cfg.initialism:
        for A in [t for t in q_seq if t in leaf_tokens and 3 <= len(t) <= 6 and t.isalpha()]:
            for _, run in _runs(q_seq, len(A)):
                if _initials(run) == A and A not in run and all(t in q for t in run):
                    for t in run:
                        q.discard(t)
                    link(f"'{' '.join(run)}' is the expansion of '{A}'", W_INITIALISM)
                    break

    out.tokens = q
    out.weight = min(weights) if weights else 1.0
    return out
