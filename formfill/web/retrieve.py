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

"Number of full-time employees": plain overlap ties `full_time` and
`employees` (each explains one of two question tokens). The scope-word
penalty breaks the tie the safe way -- the total is a different answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from formfill.web.models import Candidate, Question
from formfill.web.tokens import QUALIFIERS, tokenize

SECTION_BONUS = 0.2
QUALIFIER_PENALTY = 0.6


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


def score_leaf(q_tokens: set[str], section_tokens: set[str], leaf: Leaf) -> float:
    if not q_tokens:
        return 0.0
    leaf_hit = q_tokens & leaf.leaf_tokens
    if not leaf_hit:
        return 0.0
    parent_hit = (q_tokens & leaf.parent_tokens) - leaf.leaf_tokens
    precision = len(leaf_hit) / len(leaf.leaf_tokens)
    recall = (len(leaf_hit) + 0.5 * len(parent_hit)) / len(q_tokens)
    f1 = 2 * precision * recall / (precision + recall)
    if (q_tokens & QUALIFIERS) - leaf.leaf_tokens - leaf.parent_tokens:
        f1 *= QUALIFIER_PENALTY  # the key lacks a scope word the question insists on
    if section_tokens & leaf.parent_tokens:
        f1 += SECTION_BONUS
    return f1


def retrieve(question: Question, leaves: list[Leaf], top_k: int = 5) -> list[Candidate]:
    q = set(question.concept_tokens)
    section = set(tokenize(question.control.section))
    scored = [(score_leaf(q, section, leaf), leaf) for leaf in leaves]
    scored = [(s, leaf) for s, leaf in scored if s > 0]
    scored.sort(key=lambda t: (-t[0], t[1].path))
    return [Candidate(leaf.path, leaf.value, round(s, 4)) for s, leaf in scored[:top_k]]
