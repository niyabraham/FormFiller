"""Reasoning layer, step 2: question-driven retrieval from the JSON source.

The *question* drives the search: every question is scored against every
JSON leaf, so the JSON is never "matched to the form" field-by-field the
other way round. No embeddings, no vector store, no LLM -- this is the
Level 1-2 (exact + alias) matcher of the research, with a precision/recall
score so near-misses can be told apart from real matches.

Scoring, for question tokens Q, leaf-key tokens L and parent-path tokens P:

    precision = |Q & L| / |L|                      (is the whole key explained by the question?)
    recall    = (|Q & L| + 0.5 * |(Q & P) - L|) / |Q|
    score     = F1(precision, recall)
                x 0.6 if the question has a scope word ("full-time", "legal", ...) the key lacks
                + 0.2 if the control's section names a parent

Phase 3A safety caps (applied last, so the section bonus cannot undo them). A capped candidate
stays visible to the reviewer but can never be auto-answered, because both caps are below
plan.MIN_CONFIDENCE:

  * unexplained scope   -- a scope word ("parent", "production", ...) the key and its path lack, or
                           more than half of the question's words unexplained -> score <= 0.5
  * polarity            -- question and key carry different negation markers ("optional" vs
                           "required", "disabled" vs "enabled", "lack" vs none) -> score <= 0.3
  * period (3B-A)       -- the question names a point in time ("two financial years ago", "2023") that the
                           key path does not carry, or carries differently -> score <= 0.3. "last"/"current"
                           year may rely on a key that names no period.

Phase 3B-B parent/sibling context (applied after scoring, in `retrieve`). The same field name under
different parents (`franchisor.year_founded` / `franchisee.year_founded`) or in different list items
(`terminals.0.doors` / `terminals.1.doors`) is told apart only by *evidence that the question names one of
them*, never by position or by "nearest/highest parent":

  * path evidence     -- the question or its form section names a parent only one candidate has
  * item evidence     -- the question contains the literal value of a sibling field of one list item
                         ("Omaha" -> the terminal whose city is Omaha); those words also count as explained
  * ancestor evidence -- the question names the entity and the candidate is that entity's own field, not
                         the same field in a collection under it

Candidates without the evidence are multiplied by CONTEXT_PENALTY (rivals only: a candidate named by the
question keeps its score, so a weak one stays REVIEW). No entity named, or several -> nothing changes.
"The organisation"/"company" is self-reference, not a named entity, and is never evidence.

"Number of full-time employees": plain overlap ties `full_time` and
`employees` (each explains one of two question tokens). The scope-word
penalty breaks the tie the safe way -- the total is a different answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from formfill.web import semantic
from formfill.web.models import Candidate, Question
from formfill.web.tokens import (
    COMPOSITE_MARKERS,
    ENTITY_QUALIFIERS,
    IMPLICIT_NOUNS,
    NEGATORS,
    NEUTRAL,
    QUALIFIERS,
    SELF_REFERENCE,
    entity_modifiers,
    modality_markers,
    period_markers,
    tokenize,
)

SECTION_BONUS = 0.2
QUALIFIER_PENALTY = 0.6
UNEXPLAINED_CAP = 0.5  # must stay below plan.MIN_CONFIDENCE (asserted in tests)
POLARITY_CAP = 0.3
MIN_EXPLAINED_FRACTION = 0.5  # generic guard (Phase 3A): capped when FEWER than this share of the question's words is explained
COUNT_MIN_EXPLAINED_FRACTION = 0.5  # counting questions (Phase 3B-A): capped when AT MOST this share is explained
PERIOD_CAP = 0.3
CONTEXT_PENALTY = 0.6  # Phase 3B-B: score multiplier for a rival of a candidate the question names
CONTEXT_RULES = frozenset({"path", "item", "ancestor", "count_recheck"})  # switchable one by one for ablation runs
SIBLING_CREDIT = True  # words citing a sibling value of the list item count as explained
_NOT_EVIDENCE = {"yes", "no", "true", "false", "none", "unknown", "null", "tbd", "tba"}
# a question may name these periods and rely on a key that says nothing about time (the latest/current value);
# any other period ("two years ago", "2023", "next year") must be carried by the key.
_IMPLICIT_PERIODS = {"-1y", "0y"}


@dataclass
class Leaf:
    path: str
    value: Any
    leaf_tokens: frozenset[str]
    parent_tokens: frozenset[str]
    period: frozenset[str] = frozenset()  # points in time named by the key path ("last financial year", "2024")
    shape: tuple[str, ...] = ()  # named path segments without list indices: identical for repeated list items
    item_id: tuple[str, ...] = ()  # path through the innermost list index; () when not inside a list item
    item_values: tuple[frozenset[str], ...] = ()  # word sets of the string fields beside this one in its list item


def _item_values(item: dict) -> list[tuple[str, frozenset[str]]]:
    """Word sets of the short string fields of one list item ("Omaha", "CEO", "114"): what a question can
    cite to say *which* item it means. Numbers and booleans are not used; a value of more than four words,
    or of words that are not distinctive (yes, none, 2-letter codes), is not evidence."""
    out = []
    for k, v in item.items():
        if not isinstance(v, str):
            continue
        toks = frozenset(tokenize(v))
        if 1 <= len(toks) <= 4 and not toks & _NOT_EVIDENCE and all(len(t) >= 3 or t.isdigit() for t in toks):
            out.append((str(k), toks))
    return out


def index_source(data: Any) -> list[Leaf]:
    """Flatten JSON into answerable leaves: scalars, and lists of scalars
    (kept whole so multi-select questions can use them). Nulls and empty
    values are not answers and are skipped."""
    leaves: list[Leaf] = []

    def walk(node: Any, segments: list[str], item_id: tuple[str, ...] = (), item_vals: list | None = None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, [*segments, str(k)], item_id, item_vals)
        elif isinstance(node, list):
            if node and all(not isinstance(x, (dict, list)) for x in node):
                add(node, segments, item_id, item_vals)
            else:
                for i, v in enumerate(node):
                    ident = (*segments, str(i))
                    walk(v, [*segments, str(i)], ident, _item_values(v) if isinstance(v, dict) else [])
        elif node is not None and node != "":
            add(node, segments, item_id, item_vals)

    def add(value: Any, segments: list[str], item_id: tuple[str, ...], item_vals: list | None) -> None:
        named = [s for s in segments if not s.isdigit()]  # list indices carry no meaning
        if not named:
            return
        beside = tuple(toks for key, toks in (item_vals or [])
                       if not (len(segments) == len(item_id) + 1 and key == segments[-1]))  # not the leaf's own value
        leaves.append(
            Leaf(
                path=".".join(segments),
                value=value,
                leaf_tokens=frozenset(tokenize(named[-1])),
                parent_tokens=frozenset(t for s in named[:-1] for t in tokenize(s)),
                period=period_markers(" ".join(s for s in segments if not s.isdigit() or period_markers(s))),
                shape=tuple(named),
                item_id=item_id,
                item_values=beside,
            )
        )

    walk(data, [])
    return [leaf for leaf in leaves if leaf.leaf_tokens]


def sibling_matches(q_tokens: set[str], leaf: Leaf) -> list[frozenset[str]]:
    """Sibling values of this leaf's list item that the question cites in full ("Omaha", "San Antonio")."""
    own = leaf.leaf_tokens | leaf.parent_tokens
    return [toks for toks in leaf.item_values if toks <= q_tokens and not toks & own]


def sibling_evidence(q_tokens: set[str], leaf: Leaf) -> frozenset[str]:
    """All question words that belong to such a cited value."""
    return frozenset().union(*sibling_matches(q_tokens, leaf))


_LIGHT = semantic.light_words()
SOFT_PREFIX = "soft match: "
_YEAR_LIKE = re.compile(r"(?:19|20)\d\d")


_NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"])}


def _assess(q_tokens: set[str], section_tokens: set[str], leaf: Leaf,
                q_period: frozenset[str] = frozenset(), is_count: bool = False,
                q_seq: list[str] | None = None, sem: semantic.Config = semantic.DEFAULT,
                q_modality: frozenset[str] = frozenset(), q_modality_soft: frozenset[str] = frozenset()) -> tuple[float, list[str], float | None, frozenset[str]]:
    """Score one leaf and say why it was capped, if it was. With `q_seq` (the question's ordered tokens) the question is
    first aligned onto this leaf's key words (formfill/web/semantic.py); the alignment is soft, so its weakest link
    multiplies the score, and every cap below still runs on the aligned tokens."""
    if is_count:
        # a measure word is implicit in a counting question: `employee_count` answers "how many employees", and a
        # question's "size" explains nothing a key must carry. A key made only of a measure word (`employees.count`)
        # is the count of its parent.
        measure = semantic.MEASURE
        q_tokens = q_tokens - measure
        if q_seq is not None:
            q_seq = [t for t in q_seq if t not in measure]
        core = leaf.leaf_tokens - semantic.MEASURE
        if core and core != leaf.leaf_tokens:
            leaf = replace(leaf, leaf_tokens=core)
        elif not core and leaf.parent_tokens:
            leaf = replace(leaf, leaf_tokens=leaf.parent_tokens, parent_tokens=frozenset())
    if "current" in q_tokens and not leaf.period and not (leaf.leaf_tokens | leaf.parent_tokens) & QUALIFIERS:
        # "current headcount" asks for the present value, which is what a key naming no period holds. A key that names
        # a qualifier ("previous_", "former_", "full_time") or a period still has to be named by the question.
        q_tokens = q_tokens - {"current"}
        q_seq = [t for t in q_seq if t != "current"] if q_seq is not None else None
    links: list[str] = []
    weight = 1.0
    if q_seq is not None:
        al = semantic.align(q_seq, leaf.leaf_tokens, is_count, sem, leaf.parent_tokens)
        if al.links:
            q_tokens, weight, links = al.tokens | (q_tokens - set(q_seq)), al.weight, al.links
    q_tokens = q_tokens - (_LIGHT - leaf.leaf_tokens - leaf.parent_tokens)  # "do you HOLD ISO 27001" asks the same as "ISO 27001"
    # words like "total" widen a question; they only count when the key carries them too
    q_eff = q_tokens - (NEUTRAL - leaf.leaf_tokens - leaf.parent_tokens)
    if not q_eff:
        return 0.0, [], None, frozenset()
    leaf_hit = q_eff & leaf.leaf_tokens
    if not leaf_hit:
        return 0.0, [], None, frozenset()
    if leaf_hit <= SELF_REFERENCE and leaf.leaf_tokens - SELF_REFERENCE:
        return 0.0, [], None, frozenset()  # "your company" names the asker, not the fact: `company_name` is not evidence for "which sector does your company ..."
    cited = sibling_matches(q_eff, leaf) if SIBLING_CREDIT else []  # values of sibling fields of this list item that the question cites ("Omaha")
    sibling_hit = frozenset().union(*cited)
    explained_by = leaf.leaf_tokens | leaf.parent_tokens | sibling_hit
    parent_hit = (q_eff & leaf.parent_tokens) - leaf.leaf_tokens
    precision = len(leaf_hit) / len(leaf.leaf_tokens)
    # one unit of credit per cited value, however many words it has: "Omaha" and "Kansas City" are equal evidence
    recall = (len(leaf_hit) + 0.5 * len(parent_hit) + len(cited)) / len(q_eff)
    score = 2 * precision * recall / (precision + recall)
    scope_missing = (q_eff & QUALIFIERS) - explained_by
    if scope_missing:
        score *= QUALIFIER_PENALTY  # the key lacks a scope word the question insists on
    if section_tokens & leaf.parent_tokens:
        score += SECTION_BONUS

    flags: list[str] = []
    unexplained = q_eff - explained_by - SELF_REFERENCE
    if scope_missing:
        flags.append(f"question scope {sorted(scope_missing)} is not in the key or its path")
        score = min(score, UNEXPLAINED_CAP)
    elif is_count:
        # A count of a narrower population is a different number ("Sales headcount" vs the total, "refrigerated
        # trailers" vs all trailers), so for count questions exactly half explained is not enough. A generic noun the
        # parent scope leaves implicit ("full-time employees" vs company.full_time) is not held against the key.
        modifiers = unexplained - IMPLICIT_NOUNS
        base = len(q_eff) - len(unexplained & IMPLICIT_NOUNS)
        explained = base - len(modifiers)
        crossed = leaf.leaf_tokens - q_eff - NEUTRAL - _LIGHT  # words only the key carries: it counts a narrower population
        spelled = {_NUMBER_WORDS[t] for t in modifiers if t in _NUMBER_WORDS}
        crossed = crossed - spelled  # "last five years" and `last_5_years` name the same number
        modifiers = modifiers - {t for t in modifiers if _NUMBER_WORDS.get(t) in leaf.leaf_tokens}
        if modifiers and crossed:
            # "regulatory inspections passed" vs `gcp_inspections_passed`: the question's modifier is not in the key AND the key's
            # own modifier ("gcp") is not in the question, so the two count different subsets. Counting questions only.
            flags.append(f"counting question: modifier {sorted(modifiers)} is not in the key, and the key adds {sorted(crossed)} "
                         f"which the question does not name")
            score = min(score, UNEXPLAINED_CAP)
        elif modifiers and explained / base <= COUNT_MIN_EXPLAINED_FRACTION:
            flags.append(f"counting question: only {explained} of {base} words are explained by the key or its path "
                         f"(unexplained modifier: {sorted(modifiers)})")
            score = min(score, UNEXPLAINED_CAP)
    elif unexplained and (len(q_eff) - len(unexplained)) / len(q_eff) < MIN_EXPLAINED_FRACTION:
        flags.append(f"only {len(q_eff) - len(unexplained)} of {len(q_eff)} question words are explained by the key or its path "
                     f"(unexplained: {sorted(unexplained)})")
        score = min(score, UNEXPLAINED_CAP)
    # identifier conflict: "ISO 9001" is not `iso_13485_certified`. A number-bearing word in the question that the key does not
    # carry, against a different number-bearing word in the key, names a different standard / form / tier.
    key_words = leaf.leaf_tokens | leaf.parent_tokens
    q_ids = {t for t in unexplained if any(c.isdigit() for c in t) and not _YEAR_LIKE.fullmatch(t)
             and not any(t in k for k in key_words)}  # "SOC 2" in the question is the "soc2" of the key, not a conflict
    k_ids = {t for t in key_words if any(c.isdigit() for c in t) and not _YEAR_LIKE.fullmatch(t)} - q_eff
    if q_ids and k_ids:
        flags.append(f"identifier differs: question names {sorted(q_ids)}, key path names {sorted(k_ids)}")
        score = min(score, POLARITY_CAP)
    if q_period and ((leaf.period and q_period != leaf.period) or (not leaf.period and q_period - _IMPLICIT_PERIODS)):
        flags.append(f"period differs: question names {sorted(q_period)}, key path names {sorted(leaf.period) or 'none'}")
        score = min(score, PERIOD_CAP)
    neg_q, neg_l = q_tokens & NEGATORS, explained_by & NEGATORS
    if neg_q != neg_l:
        flags.append(f"polarity differs: question has {sorted(neg_q) or 'none'}, key path has {sorted(neg_l) or 'none'}")
        score = min(score, POLARITY_CAP)
    # Safeguards found by held-out v3 (each is a word CLASS, none names a field or a question):
    # 1. entity: "parent_company.employees" holds the parent's count, not "the company's"; a key naming another legal entity that
    #    the question does not name answers a different question, whether or not a rival exists.
    other_entity = ((key_words & ENTITY_QUALIFIERS) | entity_modifiers(leaf.path)) - q_tokens
    rival: float | None = None
    if other_entity:
        flags.append(f"key path names another entity {sorted(other_entity)} that the question does not")
        rival = score  # still a rival (see retrieve(): only when the top answer does not explain more of the question than this key): if the plain key and this one disagree, the question never said which entity it meant
        score = min(score, UNEXPLAINED_CAP)
    # 2. composite: "total ... including X" is a sum; a key holding one component does not answer it unless the key says so too.
    composite = (q_tokens & COMPOSITE_MARKERS) - key_words
    if composite:
        flags.append(f"question asks for a composite ({sorted(composite)}) that the key does not claim to hold")
        score = min(score, UNEXPLAINED_CAP)
    # 3. modality: `audit_required` is an obligation, not an audit; a plan or a request is not a fact that holds. The families
    #    named by the question and by the key path must agree (read from raw words: "required" is a stopword in tokens).
    k_modality = modality_markers(leaf.path)
    # key narrows by a modality the question never named, or the question insists on one the key lacks; a soft verb ("enforced")
    # on either side satisfies the other side's obligation but never creates a mismatch on its own
    if (k_modality - q_modality_soft) or (q_modality - modality_markers(leaf.path, soft=True)):
        flags.append(f"modality differs: question {sorted(q_modality_soft | q_modality) or 'none'}, key path {sorted(k_modality) or 'none'}")
        score = min(score, POLARITY_CAP)
    if links and weight < 1.0 and score > 0:
        score *= weight  # a soft match never outranks an exact one
    if links:
        flags.append(SOFT_PREFIX + "; ".join(links))  # moved to Candidate.evidence by retrieve(): not a cap reason
    return score, flags, rival, frozenset(q_eff & explained_by)


def assess_leaf(*args: Any, **kwargs: Any) -> tuple[float, list[str]]:
    score, flags, _, _ = _assess(*args, **kwargs)
    return score, flags


def score_leaf(q_tokens: set[str], section_tokens: set[str], leaf: Leaf, q_period: frozenset[str] = frozenset(),
               is_count: bool = False) -> float:
    return assess_leaf(q_tokens, section_tokens, leaf, q_period, is_count)[0]


SEMANTIC = semantic.DEFAULT  # module switch used by retrieve(); tests and ablations replace it


def _count_modifiers_ignoring_entity(q: set[str], leaf: Leaf) -> set[str]:
    """Unexplained modifiers of a counting question when words explained only by the parent path (which
    entity is counted) are not allowed to dilute them. Empty when the leaf explains more than half of the rest."""
    q_eff = q - (NEUTRAL - leaf.leaf_tokens - leaf.parent_tokens)
    explained_by = leaf.leaf_tokens | leaf.parent_tokens | sibling_evidence(q_eff, leaf)
    unexplained = q_eff - explained_by - SELF_REFERENCE
    modifiers = unexplained - IMPLICIT_NOUNS
    parent_only = (q_eff & leaf.parent_tokens) - leaf.leaf_tokens
    base = len(q_eff) - len(unexplained & IMPLICIT_NOUNS) - len(parent_only)
    if modifiers and base > 0 and (base - len(modifiers)) / base <= COUNT_MIN_EXPLAINED_FRACTION:
        return modifiers
    return set()


def _apply_context(scored: list[list], q: set[str], section: set[str], is_count: bool = False) -> None:
    """Phase 3B-B. `scored` rows are [score, flags, evidence, leaf]. Lowers the rivals of a candidate the
    question (or its form section) names; never raises a score, never decides when no entity is named or
    when several are."""
    named_by = q | section
    live = [r for r in scored if r[0] > 0]
    protected: set[int] = set()
    penalise: dict[int, str] = {}

    def own_parents(leaf: Leaf) -> frozenset[str]:
        return leaf.parent_tokens - leaf.leaf_tokens - SELF_REFERENCE

    # --- path evidence: same field name under different parents -----------------------------------
    by_key: dict[frozenset[str], list[list]] = {}
    for r in live:
        by_key.setdefault(r[3].leaf_tokens, []).append(r)
    for group in by_key.values():
        if len({r[3].parent_tokens for r in group}) < 2:
            continue
        if "path" not in CONTEXT_RULES and "ancestor" not in CONTEXT_RULES:
            continue
        distinct = {}
        for r in group:
            others = frozenset().union(*(own_parents(o[3]) for o in group if o[3].parent_tokens != r[3].parent_tokens))
            distinct[id(r)] = (named_by & own_parents(r[3])) - others
        winners = [r for r in group if distinct[id(r)]] if "path" in CONTEXT_RULES else []
        for r in winners:
            protected.add(id(r))
            r[2].append(f"path names {sorted(distinct[id(r)])}, which the other candidates' paths do not carry")
        for r in group:
            if winners and not distinct[id(r)]:
                penalise[id(r)] = (f"the question or its section names {sorted(set().union(*(distinct[id(w)] for w in winners)))}, "
                                   "which this path does not carry")

        # --- ancestor evidence: the entity's own field vs the same field in a collection under it ---
        for i in group if "ancestor" in CONTEXT_RULES else []:
            pre_i = i[3].shape[:-1]
            named_i = named_by & own_parents(i[3])
            if not pre_i or not named_i or own_parents(i[3]) - named_by:
                continue  # needs a path of which every part is named by the question
            for j in group:
                pre_j = j[3].shape[:-1]
                if len(pre_j) > len(pre_i) and pre_j[: len(pre_i)] == pre_i and id(j) not in penalise:
                    penalise[id(j)] = (f"the question names {sorted(named_i)}, whose own field is {i[3].path!r}; "
                                       "this one sits in a collection under it")
                    i[2].append(f"every part of the path ({sorted(named_i)}) is named; deeper collection set aside")
                    protected.add(id(i))

    # --- item evidence: repeated list items told apart by a sibling value ------------------------
    by_shape: dict[tuple[str, ...], list[list]] = {}
    for r in live if "item" in CONTEXT_RULES else []:
        if r[3].item_id:
            by_shape.setdefault(r[3].shape, []).append(r)
    for group in by_shape.values():
        if len({r[3].item_id for r in group}) < 2:
            continue
        hits = {id(r): sibling_evidence(q, r[3]) for r in group}
        for r in group:
            if hits[id(r)]:
                protected.add(id(r))
                r[2].append(f"question cites {sorted(hits[id(r)])}, a value in this list item")
        if any(hits.values()):
            for r in group:
                if not hits[id(r)] and id(r) not in penalise:
                    penalise[id(r)] = "the question cites a value of another list item, not of this one"

    for r in live:
        if id(r) in penalise and id(r) not in protected:
            r[0] *= CONTEXT_PENALTY
            r[1].append(f"context: {penalise[id(r)]}")
        elif r[2] and is_count and "count_recheck" in CONTEXT_RULES:
            # context picked this candidate: it must not also launder an unexplained modifier
            # ("refrigerated trailers of the franchisor" is not `franchisor.trailers`)
            mods = _count_modifiers_ignoring_entity(q, r[3])
            if mods:
                r[0] = min(r[0], UNEXPLAINED_CAP)
                r[1].append(f"counting question: unexplained modifier {sorted(mods)}; the named entity does not explain it")


def retrieve(question: Question, leaves: list[Leaf], top_k: int = 5) -> list[Candidate]:
    q = set(question.concept_tokens)
    section = set(tokenize(question.control.section))
    scored: list[list] = []
    rivals: dict[str, float] = {}
    explained_by_path: dict[str, frozenset[str]] = {}
    for leaf in leaves:
        s, flags, rival, explained = _assess(q, section, leaf, question.period, question.is_count, question.concept_tokens, SEMANTIC,
                                  modality_markers(question.text), modality_markers(question.text, soft=True))
        if s > 0:
            scored.append([s, flags, [], leaf])
            explained_by_path[leaf.path] = explained
            if rival is not None:
                rivals[leaf.path] = rival
    _apply_context(scored, q, section, question.is_count)
    for row in scored:  # soft-match notes are evidence for the reviewer, not reasons a score was capped
        soft = [f for f in row[1] if f.startswith(SOFT_PREFIX)]
        row[1] = [f for f in row[1] if not f.startswith(SOFT_PREFIX)]
        row[2] = soft + row[2]
    scored.sort(key=lambda t: (-t[0], t[3].path))
    if scored:  # an entity-capped key is a fair rival only if the best answer does not explain more of the question than it does
        best = explained_by_path[scored[0][3].path]
        for path in [p for p in rivals if not best <= explained_by_path[p]]:
            del rivals[path]
    return [Candidate(leaf.path, leaf.value, round(s, 4), flags, evidence, rivals.get(leaf.path)) for s, flags, evidence, leaf in scored[:top_k] + [r for r in scored[top_k:] if r[3].path in rivals]]
