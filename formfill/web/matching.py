"""Requirement C: the layered matcher's configuration and its calibrated confidence categories.

Layers, in the order plan.plan_question applies them:

1. exact and normalised matching (retrieve.py: token overlap, scope/period/polarity guards)
2. deterministic domain terms and synonyms (tokens.py: SOC 2 / ISO 27001 / PCI DSS names, BCP, RTO, pentest, 2FA, ...)
3. evidence validation (evidence.py): certification/compliance claims need a stated status; another entity's fact is never the
   answer; contradictory facts send the question to review
4. semantic similarity (semantic.py): proposals for a reviewer when layers 1-3 abstain; never entered automatically
5. optional LLM reranking (llm.py): only when a reranker is passed explicitly; proposals only, never entered automatically
6. confidence categories, calibrated on the development benchmark (below)

Calibration (benchmarks/rfi dev set, recorded run of the deterministic matcher; checked on benchmarks/heldout):

    score 1.0 (every word of the key explained)     dev 56/56 correct   held-out 50/50
    0.6 <= score < 1.0 (partial match)              dev 43/45 correct   held-out 57/57

The two dev errors (a wrong count and a fill failure) were both in the partial band, which is the only split the data
supports; finer bands did not differ (docs/MATCHING.md). So: "high" = exact key match or a stated status, "medium" = partial
match above the answer threshold, "low" = a proposal only (semantic or LLM), never entered automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from formfill.web.llm import Reranker
from formfill.web.semantic import SimilarityBackend

# Minimum similarity for a semantic proposal, chosen on benchmarks/semantic/dev.json only (docs/MATCHING.md has the sweep).
SEMANTIC_MIN_SIMILARITY = 0.30


@dataclass(frozen=True)
class MatcherConfig:
    evidence_checks: bool = True
    semantic: bool = True
    semantic_min_similarity: float = SEMANTIC_MIN_SIMILARITY
    backend: SimilarityBackend | None = field(default=None, compare=False)  # None: semantic.default_backend()
    reranker: Reranker | None = field(default=None, compare=False)  # an llm.Reranker (llm.py); None: no LLM layer (the default)


DEFAULT_MATCHER = MatcherConfig()
DETERMINISTIC_ONLY = MatcherConfig(evidence_checks=False, semantic=False)


def confidence_category(score: float, method: str) -> str:
    if method in ("semantic", "llm"):
        return "low"
    if method == "status_evidence" or score >= 0.999:
        return "high"
    return "medium"
