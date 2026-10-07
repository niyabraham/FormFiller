"""Reasoning layer, step 3: choose an answer per question and emit the
AnswerPlan -- the *only* thing the browser layer receives.

Policy ("never guess"), applied in this order. Any failure -> REVIEW with a
human-readable reason and the candidates considered:

  0. attestation / consent checkbox           -> REVIEW  (always; legal declarations)
  1. control disabled                         -> REVIEW
  2. no candidate at all                      -> REVIEW  (no source value)
  3. best score < MIN_CONFIDENCE              -> REVIEW  (weak evidence)
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
from typing import Any

from formfill.web.models import AnswerPlanItem, Candidate, Question
from formfill.web.retrieve import Leaf, retrieve
from formfill.web.validate import validate_answer

MIN_CONFIDENCE = 0.6
MIN_MARGIN = 0.15

# Declarations the organisation legally stands behind. Policy, not scoring:
# these are never answered by software, whatever the source JSON contains.
_ATTESTATION = re.compile(r"\b(i|we)\s+(confirm|agree|accept|certify|declare|consent|acknowledge|attest)\b|"
                          r"\b(terms|conditions|privacy policy|consent)\b", re.IGNORECASE)


def _same_value(a: Any, b: Any) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _alts(cands: list[Candidate], skip: int = 0) -> list[dict]:
    return [{"source": c.path, "value": c.value, "score": c.score} for c in cands[skip:3 + skip]]


def plan_question(question: Question, leaves: list[Leaf]) -> AnswerPlanItem:
    c = question.control
    base = dict(
        question_id=question.question_id, question=question.text,
        field_type=c.kind, required=c.required,
    )

    def review(reason: str, cands: list[Candidate], confidence: float = 0.0) -> AnswerPlanItem:
        return AnswerPlanItem(**base, status="REVIEW", reason=reason, confidence=confidence, alternatives=_alts(cands))

    if c.disabled:
        return review("control is disabled", [])
    if c.kind == "checkbox" and _ATTESTATION.search(question.text):
        return review("attestation/consent checkbox: a human must confirm it, never auto-ticked", [])

    cands = retrieve(question, leaves)
    if not cands:
        return review("no matching value in the source data", [])

    top = cands[0]
    if top.score < MIN_CONFIDENCE:
        return review(
            f"best candidate {top.path!r} is too weak (score {top.score:.2f} < {MIN_CONFIDENCE})", cands, top.score
        )

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
        confidence=min(1.0, top.score), alternatives=_alts(cands, skip=1),
    )


def build_plan(questions: list[Question], leaves: list[Leaf]) -> list[AnswerPlanItem]:
    return [plan_question(q, leaves) for q in questions]
