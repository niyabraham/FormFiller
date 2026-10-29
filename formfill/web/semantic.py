"""Requirement C, semantic layer: similarity search over the source's keys, for questions the deterministic matcher cannot place.

It only PROPOSES. A proposal is shown to the reviewer next to the question (AnswerPlanItem.proposed_answer, method "semantic")
and is never entered automatically: a similar-sounding key is not evidence that its value answers the question. Proposals go
through the same safety gates as answers (another entity's fact, control validation) and are not made for attestations,
certification/compliance claims, or contradictions.

Backends (chosen once per process, see `default_backend`):

* `LexicalSimilarity` (default; built in, offline, no dependency, deterministic): cosine similarity over the canonical tokens of
  tokens.tokenize (so domain terms and abbreviations meet: "BCP" ~ "business continuity plan"), light word stems ("enforced" ~
  "enforce", "scanning" ~ "scan") and character trigrams of each stem. It knows nothing about meaning beyond spelling and the
  synonym table; its job is recall for a reviewer, not judgement.
* `EmbeddingSimilarity` (optional): a sentence-transformers model loaded from LOCAL files only (HF_HUB_OFFLINE is set before
  loading), used when FORMFILL_EMBEDDING_MODEL names a model directory and the package is installed. Nothing is downloaded and
  nothing leaves the machine. Not installed by default: it pulls in PyTorch (hundreds of MB) for a layer that only proposes.

docs/MATCHING.md records the comparison and the evaluation.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from formfill.web.retrieve import Leaf
from formfill.web.tokens import STOPWORDS, tokenize


class SimilarityBackend(Protocol):
    name: str

    def scores(self, query: str, documents: Sequence[str]) -> list[float]: ...


def leaf_document(leaf: Leaf) -> str:
    """What a key is about, in words: its path without list indices ("security vulnerability scanning frequency")."""
    return " ".join(seg.replace("_", " ") for seg in leaf.path.split(".") if not seg.isdigit())


def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            w = w[: -len(suffix)]
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]  # scann -> scan
    return w


def _features(text: str) -> dict[str, float]:
    words = [w for w in re.findall(r"[a-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).lower()) if w not in STOPWORDS]
    feats: dict[str, float] = {}
    for t in tokenize(text):
        feats[f"t:{t}"] = feats.get(f"t:{t}", 0.0) + 2  # canonical tokens (domain terms, synonyms) weigh most
    for w in words:
        s = _stem(w)
        feats[f"w:{s}"] = feats.get(f"w:{s}", 0.0) + 1
        padded = f"^{s}$"
        for i in range(len(padded) - 2):
            feats[f"c:{padded[i:i + 3]}"] = feats.get(f"c:{padded[i:i + 3]}", 0.0) + 0.25
    return feats


class LexicalSimilarity:
    """Cosine similarity of fixed-weight features. No IDF: with a source of a handful of keys IDF is unstable (the same match
    scored 0.16 against a two-key source and 0.33 against a seven-key one), and a threshold must mean the same everywhere."""

    name = "lexical"

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        q = _features(query)
        qn = math.sqrt(sum(x * x for x in q.values())) or 1.0
        out = []
        for d in documents:
            f = _features(d)
            dn = math.sqrt(sum(x * x for x in f.values())) or 1.0
            out.append(sum(q.get(k, 0.0) * x for k, x in f.items()) / (qn * dn))
        return out


class EmbeddingSimilarity:
    """Cosine similarity of sentence embeddings. `model` is anything with `encode(list[str]) -> list[vector]`; by default a
    sentence-transformers model loaded from a local directory."""

    def __init__(self, model_path: str | None = None, model=None):
        if model is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")  # never download a model during a run
            from sentence_transformers import SentenceTransformer  # optional dependency

            model = SentenceTransformer(model_path, local_files_only=True)
        self.model = model
        self.name = f"embeddings:{model_path or type(model).__name__}"

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        vecs = self.model.encode([query, *documents])
        qv = list(vecs[0])
        qn = math.sqrt(sum(x * x for x in qv)) or 1.0
        out = []
        for d in vecs[1:]:
            dv = list(d)
            dn = math.sqrt(sum(x * x for x in dv)) or 1.0
            out.append(sum(a * b for a, b in zip(qv, dv, strict=True)) / (qn * dn))
        return out


@lru_cache(maxsize=1)
def default_backend() -> SimilarityBackend:
    path = os.environ.get("FORMFILL_EMBEDDING_MODEL")
    if path:
        try:
            return EmbeddingSimilarity(path)
        except Exception:  # noqa: BLE001 - not installed or not loadable: the built-in backend still works
            pass
    return LexicalSimilarity()


def rank(question_text: str, leaves: list[Leaf], backend: SimilarityBackend | None = None) -> list[tuple[Leaf, float]]:
    """Leaves by similarity to the question, best first."""
    if not leaves:
        return []
    backend = backend or default_backend()
    sims = backend.scores(question_text, [leaf_document(leaf) for leaf in leaves])
    return sorted(zip(leaves, sims, strict=True), key=lambda t: (-t[1], t[0].path))
