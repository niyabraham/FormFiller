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
                           "required", "disabled" vs "enabled") -> score <= 0.3

"Number of full-time employees": plain overlap ties `full_time` and
`employees` (each explains one of two question tokens). The scope-word
penalty breaks the tie the safe way -- the total is a different answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from formfill.web.models import Candidate, Question
from formfill.web.tokens import NEGATORS, NEUTRAL, QUALIFIERS, SELF_REFERENCE, tokenize

SECTION_BONUS = 0.2
QUALIFIER_PENALTY = 0.6
UNEXPLAINED_CAP = 0.5  # must stay below plan.MIN_CONFIDENCE (asserted in tests)
POLARITY_CAP = 0.3
MIN_EXPLAINED_FRACTION = 0.5  # at least this share of the question's words must be explained by the key/path


@dataclass
class Leaf:
    path: str
    value: Any
    leaf_tokens: frozenset[str]
    parent_tokens: frozenset[str]


def index_source(data: Any) -> list[Leaf]:
    """Flatten JSON into answerable leaves: scalars, and lists of scalars
    (kept whole so multi-select questions can use them). Nulls and empty
    values are not answers and are skipped."""
    leaves: list[Leaf] = []

    def walk(node: Any, segments: list[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, segments + [str(k)])
        elif isinstance(node, list):
            if node and all(not isinstance(x, (dict, list)) for x in node):
                add(node, segments)
            else:
                for i, v in enumerate(node):
                    walk(v, segments + [str(i)])
        elif node is not None and node != "":
            add(node, segments)

    def add(value: Any, segments: list[str]) -> None:
        named = [s for s in segments if not s.isdigit()]  # list indices carry no meaning
        if not named:
            return
        leaves.append(
            Leaf(
                path=".".join(segments),
                value=value,
                leaf_tokens=frozenset(tokenize(named[-1])),
                parent_tokens=frozenset(t for s in named[:-1] for t in tokenize(s)),
            )
        )

    walk(data, [])
    return [leaf for leaf in leaves if leaf.leaf_tokens]


def assess_leaf(q_tokens: set[str], section_tokens: set[str], leaf: Leaf) -> tuple[float, list[str]]:
    """Score one leaf and say why it was capped, if it was."""
    # words like "total" widen a question; they only count when the key carries them too
    q_eff = q_tokens - (NEUTRAL - leaf.leaf_tokens - leaf.parent_tokens)
    if not q_eff:
        return 0.0, []
    leaf_hit = q_eff & leaf.leaf_tokens
    if not leaf_hit:
        return 0.0, []
    explained_by = leaf.leaf_tokens | leaf.parent_tokens
    parent_hit = (q_eff & leaf.parent_tokens) - leaf.leaf_tokens
    precision = len(leaf_hit) / len(leaf.leaf_tokens)
    recall = (len(leaf_hit) + 0.5 * len(parent_hit)) / len(q_eff)
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
    elif unexplained and (len(q_eff) - len(unexplained)) / len(q_eff) < MIN_EXPLAINED_FRACTION:
        flags.append(f"only {len(q_eff) - len(unexplained)} of {len(q_eff)} question words are explained by the key or its path "
                     f"(unexplained: {sorted(unexplained)})")
        score = min(score, UNEXPLAINED_CAP)
    neg_q, neg_l = q_tokens & NEGATORS, explained_by & NEGATORS
    if neg_q != neg_l:
        flags.append(f"polarity differs: question has {sorted(neg_q) or 'none'}, key path has {sorted(neg_l) or 'none'}")
        score = min(score, POLARITY_CAP)
    return score, flags


def score_leaf(q_tokens: set[str], section_tokens: set[str], leaf: Leaf) -> float:
    return assess_leaf(q_tokens, section_tokens, leaf)[0]


def retrieve(question: Question, leaves: list[Leaf], top_k: int = 5) -> list[Candidate]:
    q = set(question.concept_tokens)
    section = set(tokenize(question.control.section))
    scored = []
    for leaf in leaves:
        s, flags = assess_leaf(q, section, leaf)
        if s > 0:
            scored.append((s, flags, leaf))
    scored.sort(key=lambda t: (-t[0], t[2].path))
    return [Candidate(leaf.path, leaf.value, round(s, 4), flags) for s, flags, leaf in scored[:top_k]]
