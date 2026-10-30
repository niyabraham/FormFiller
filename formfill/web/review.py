"""Requirement F: the human review workflow, separate from filling and from submitting.

    run_form(...)                    ->  result            (fill + verify; never submits)
    build_review(result)             ->  review file       (what a person must look at, with evidence)
    person decides in the review UI  ->  review file      (approve / edit / reject / acknowledge, re-validated, saved atomically)
    run_form(..., planner=decisions_planner(review file)) (fills approved and edited answers and verifies them again)
    the person submits in the portal, themselves

A decision is about one question, identified by what the page shows (label, name, id, section, kind), not by a run's control id.

* approve      accept the proposed answer: a planned answer, or a proposal a reviewer was offered (semantic/LLM). If the proposal
               has changed since it was approved (the source changed), the approval no longer applies: back to REVIEW.
* edit         enter this value instead; it is validated against the control's own constraints (type, options, min/max,
               length, pattern) before it is accepted, and again against the live control when it is filled.
* reject       FormFiller enters nothing; the person completes the question in the portal.
* acknowledge  the only decision for an attestation/consent/declaration: the person will complete it in the portal themselves.
               FormFiller never ticks, signs or accepts it, whatever the review file says.

Approving an answer is not a signature, a certification or a submission. Review files contain answers (confidential): they are
written owner-only where the OS supports it, and the review UI (review_server.py) serves them on 127.0.0.1 only, behind a token.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from formfill.web.artifacts import write_text_atomic
from formfill.web.matching import MatcherConfig
from formfill.web.models import AnswerPlanItem, Control, Option, Question
from formfill.web.plan import ATTESTATION_REASON_PREFIX, build_plan
from formfill.web.result import RunResult, field_state
from formfill.web.validate import validate_answer

SCHEMA = "formfill.review"
SCHEMA_VERSION = 1
ACTIONS = ("pending", "approve", "edit", "reject", "acknowledge")
NOT_A_SIGNATURE = ("Reviewing or approving answers is not submitting the questionnaire, and it is not a signature, certification "
                   "or acceptance of any terms. FormFiller never submits; you submit in the portal yourself.")


class ReviewError(ValueError):
    """A review file or a decision that cannot be used."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def question_key(control: Control | dict) -> list:
    if isinstance(control, dict):
        return [control.get("label"), control.get("name"), control.get("html_id"), control.get("section"), control.get("kind")]
    return [control.label, control.name, control.html_id, control.section, control.kind]


_CONSTRAINTS = ("kind", "label", "required", "min", "max", "step", "minlength", "maxlength", "pattern", "placeholder")


def _control_from(entry: dict) -> Control:
    con = entry["control"]
    return Control(control_id=entry["question_id"], options=[Option(**o) for o in con.get("options", [])],
                   **{k: con.get(k) for k in _CONSTRAINTS if k in con})


def build_review(result: RunResult) -> dict:
    """The review document for one run: every question with its evidence, state and reason, and a pending decision."""
    controls = {c["control_id"]: c for c in result.controls}
    items = []
    for item in result.items:
        p = item.plan
        con = controls.get(p.question_id, {})
        state, why = field_state(item)
        attestation = (p.reason or "").startswith(ATTESTATION_REASON_PREFIX)
        proposed = p.answer if p.status == "ANSWER" else p.proposed_answer
        items.append({
            "question_id": p.question_id, "key": question_key(con) if con else [p.question, None, None, item.section, p.field_type],
            "question": p.question, "section": item.section, "required": p.required, "field_type": p.field_type,
            "control": {k: con.get(k) for k in _CONSTRAINTS} | {"options": con.get("options", [])},
            "status": p.status, "proposed": proposed, "method": p.method, "confidence": p.confidence,
            "confidence_category": p.confidence_category, "source": p.source, "raw_value": p.raw_value,
            "alternatives": p.alternatives, "conflicts": p.conflicts, "validation": p.validation, "reason": p.reason,
            "state": state.value, "state_detail": why, "filled": item.filled, "verified": item.verified,
            "observed": item.observed, "attestation": attestation,
            "decision": {"action": "pending", "value": None, "note": "", "decided_at": None, "validation": None},
        })
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "run_id": result.run_id, "created_at": _now(), "updated_at": _now(),
            "page": result.url, "status": result.status, "notice": NOT_A_SIGNATURE, "items": items}


def validate_review(doc: Any) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ReviewError("not a FormFiller review file")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError(f"incompatible review schema version {doc.get('schema_version')!r}")
    if not isinstance(doc.get("items"), list):
        raise ReviewError("review file has no items")
    for i, it in enumerate(doc["items"]):
        if not isinstance(it, dict) or not isinstance(it.get("key"), list) or not isinstance(it.get("decision"), dict):
            raise ReviewError(f"review item {i} is incomplete")
        if it["decision"].get("action") not in ACTIONS:
            raise ReviewError(f"review item {i} has an unknown decision {it['decision'].get('action')!r}")
    return doc


def load_review(path: str | Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReviewError(f"no review file at {path}") from None
    except json.JSONDecodeError as exc:
        raise ReviewError(f"corrupt review file ({exc.msg})") from None
    return validate_review(doc)


def save_review(doc: dict, path: str | Path) -> Path:
    doc["updated_at"] = _now()
    return write_text_atomic(path, json.dumps(validate_review(doc), indent=2, default=str))


def decide(doc: dict, question_id: str, action: str, value: Any = None, note: str = "") -> dict:
    """Record one decision after checking it. Returns the item. Raises ReviewError (with the reason) when it cannot apply."""
    if action not in ACTIONS:
        raise ReviewError(f"unknown action {action!r}")
    item = next((it for it in doc["items"] if it["question_id"] == question_id), None)
    if item is None:
        raise ReviewError(f"no question {question_id!r} in this review")
    if item["attestation"] and action in ("approve", "edit"):
        raise ReviewError("an attestation, consent or declaration is never answered by FormFiller; mark it 'acknowledge' and "
                          "complete it yourself in the portal")
    if action == "approve" and item["proposed"] is None:
        raise ReviewError("there is no proposed answer to approve; edit it instead")
    checked = None
    if action in ("approve", "edit"):
        candidate = item["proposed"] if action == "approve" else value
        result = validate_answer(candidate, _control_from(item))
        if not result.ok:
            raise ReviewError(f"not a valid answer for this field: {result.reason}")
        checked = result.value
    item["decision"] = {"action": action, "value": checked if action == "edit" else (item["proposed"] if action == "approve" else None),
                        "note": str(note)[:500], "decided_at": _now(), "validation": "ok" if checked is not None else None}
    return item


def decisions_planner(doc: dict, matcher: MatcherConfig | None = None):
    """A `planner` for run_form that applies the review decisions on top of the normal plan (see the module docstring)."""
    by_key = {json.dumps(it["key"]): it for it in validate_review(doc)["items"] if it["decision"]["action"] != "pending"}

    def plan(questions: list[Question], leaves) -> list[AnswerPlanItem]:
        plans = build_plan(questions, leaves, matcher)
        out = []
        for q, p in zip(questions, plans, strict=True):
            it = by_key.get(json.dumps(question_key(q.control)))
            out.append(p if it is None else _apply(q, p, it))
        return out

    return plan


def _apply(q: Question, p: AnswerPlanItem, it: dict) -> AnswerPlanItem:
    d = it["decision"]
    when = d.get("decided_at")
    if p.reason and p.reason.startswith(ATTESTATION_REASON_PREFIX):
        return replace(p, reason=f"{p.reason}; the reviewer will complete it in the portal" if d["action"] == "acknowledge" else p.reason)
    if d["action"] in ("reject", "acknowledge"):
        return replace(p, status="REVIEW", answer=None, reason=f"rejected by the reviewer ({when}): to be completed in the portal by a person")
    current = p.answer if p.status == "ANSWER" else p.proposed_answer
    if d["action"] == "approve" and str(current) != str(d["value"]):
        return replace(p, status="REVIEW", answer=None,
                       reason=f"the proposal changed since it was approved ({d['value']!r} -> {current!r}); review it again")
    result = validate_answer(d["value"], q.control)
    if not result.ok:
        return replace(p, status="REVIEW", answer=None, reason=f"the reviewer's answer does not fit the field now: {result.reason}")
    method = "human_approved" if d["action"] == "approve" else "human_edited"
    return replace(p, status="ANSWER", answer=result.value, raw_value=d["value"], method=method, reason=None, validation="ok",
                   confidence_category="human", source=p.source if d["action"] == "approve" else "reviewer",
                   evidence=[*p.evidence, f"{method.replace('_', ' ')} at {when}" + (f": {d['note']}" if d.get("note") else "")])
