"""The structured result of one run -- the primary output of the system.

A web form has no output *file*; the output is (a) what the form now holds,
(b) a machine-readable record of every question's outcome and provenance,
and (c) evidence artifacts. See docs/OUTPUT_DESIGN.md.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from formfill.web.models import AnswerPlanItem


@dataclass
class ItemResult:
    plan: AnswerPlanItem
    filled: bool = False
    observed: Any = None  # what the page holds after the run
    verified: bool | None = None  # None = nothing to verify (REVIEW item)
    browser_valid: bool | None = None  # HTML constraint validation on the control
    detail: str = ""
    prefilled_warning: bool = False  # a REVIEW control already held a value (template default)
    app_state: str = "not_checked"  # client-side application state: "confirmed" | "mismatch" | "not_checked" (needs a caller-supplied reader)
    server_persistence: str = "not_checked"  # always "not_checked": FormFiller never submits, so nothing can have reached a backend

    @property
    def outcome(self) -> str:
        """One word per question, from strongest to weakest evidence. Mutually exclusive:

        needs_review        left for a person (no/weak/ambiguous/unsafe source, attestation, disabled control)
        failed              planned as an answer but could not be entered, or the page does not hold it afterwards
        unverified          entered, but there is nothing to read back
        verified_dom        entered and read back from the DOM (what the user would see)
        verified_client_state  as above, and the application's own client-side state agrees (only when a state reader was given)
        """
        if self.plan.status != "ANSWER":
            return "needs_review"
        if not self.filled or self.verified is False or self.app_state == "mismatch":
            return "failed"
        if self.verified is None:
            return "unverified"
        return "verified_client_state" if self.app_state == "confirmed" else "verified_dom"


def overall_status(items: list[ItemResult]) -> str:
    """FAILED: an answer could not be entered or read back. NEEDS_REVIEW: at least one question is left for a person.
    FILLED: every question was answered and read back. None of these means "submitted": FormFiller never submits."""
    if any(i.outcome == "failed" for i in items):
        return "FAILED"
    if any(i.plan.status == "REVIEW" for i in items):
        return "NEEDS_REVIEW"
    return "FILLED"


def human_submission(result: RunResult, *, incomplete: bool = False, unsettled: bool = False) -> dict:
    """Is the form ready for a person to review and submit? FormFiller itself never submits; this block only says what
    a human should look at first. `ready_for_human_review` is False when the form is knowingly not fully filled."""
    blockers: list[str] = []
    for i in result.items:
        if i.plan.status == "REVIEW" and i.plan.required:
            blockers.append(f"required question needs an answer: {i.plan.question!r} ({i.plan.reason})")
        elif i.outcome == "failed":
            blockers.append(f"answer could not be entered or read back: {i.plan.question!r}")
    if incomplete:
        blockers.append("the wizard walk stopped before completion could be confirmed")
    if unsettled:
        blockers.append("an answer was entered while the page was still changing")
    return {"performed_by_formfill": False, "action_required": "a person must review the form and submit it themselves",
            "ready_for_human_review": not blockers, "blockers": blockers}


@dataclass
class RunResult:
    url: str
    status: str
    items: list[ItemResult]
    human_submission: dict = field(default_factory=dict)  # never "submitted": see human_submission()
    not_asked: list[dict] = field(default_factory=list)  # controls that stayed hidden or disabled and were therefore never asked
    artifacts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    navigation: dict = field(default_factory=dict)  # step-navigation record (only with a DiscoveryPolicy): steps, stop reason, notes
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished_at: str = ""

    @property
    def review_items(self) -> list[ItemResult]:
        return [i for i in self.items if i.plan.status == "REVIEW"]

    def to_dict(self, redact: bool = False) -> dict:
        """JSON-ready record. With `redact=True` every company value (raw, answer, observed, alternatives' values, page defaults)
        is replaced by "[redacted]"; source paths, statuses, scores and reasons stay, so the report is still auditable."""
        d = asdict(self)
        for raw, it in zip(d["items"], self.items):
            raw["outcome"] = it.outcome
        d["review_items"] = [
            {"question_id": i.plan.question_id, "question": i.plan.question, "required": i.plan.required,
             "reason": i.plan.reason, "alternatives": i.plan.alternatives}
            for i in self.review_items
        ]
        d["summary"] = self.summary()
        if redact:
            _redact(d)
        return d

    def summary(self) -> dict:
        from collections import Counter

        return {"questions": len(self.items), **dict(sorted(Counter(i.outcome for i in self.items).items())),
                "status": self.status, "ready_for_human_review": self.human_submission.get("ready_for_human_review")}

    def to_json(self, redact: bool = False) -> str:
        return json.dumps(self.to_dict(redact), indent=2, default=str)


REDACTED = "[redacted]"


def _redact(d: dict) -> None:
    d["redacted"] = True
    for it in d["items"]:
        for k in ("observed",):
            if it.get(k) not in (None, "", [], False):
                it[k] = REDACTED
        p = it["plan"]
        for k in ("raw_value", "answer"):
            if p.get(k) is not None:
                p[k] = REDACTED
        if p.get("reason"):
            p["reason"] = _scrub_detail(p["reason"])
        p["evidence"] = [_scrub_detail(e) for e in p.get("evidence", [])]
        _redact_alts(p.get("alternatives", []))
        if it.get("detail"):
            it["detail"] = _scrub_detail(it["detail"])
    for r in d.get("review_items", []):
        r["reason"] = _scrub_detail(r["reason"]) if r.get("reason") else r.get("reason")
        _redact_alts(r.get("alternatives", []))
    for w in range(len(d.get("warnings", []))):
        d["warnings"][w] = _scrub_detail(d["warnings"][w])


def _redact_alts(alts: list[dict]) -> None:
    for alt in alts:
        alt["value"] = REDACTED
        alt["flags"] = [_scrub_detail(f) for f in alt.get("flags", [])] or alt.get("flags", [])
        alt["evidence"] = [_scrub_detail(e) for e in alt.get("evidence", [])] or alt.get("evidence", [])


def _scrub_detail(text: str) -> str:
    """Details can quote values ("expected 'x', page holds 'y'"): keep the shape, drop the quoted parts."""
    import re

    return re.sub(r"'[^']*'|\"[^\"]*\"", REDACTED, text)
