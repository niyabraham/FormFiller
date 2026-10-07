"""The structured result of one run -- the primary output of the system.

A web form has no output *file*; the output is (a) what the form now holds,
(b) a machine-readable record of every question's outcome and provenance,
and (c) evidence artifacts. See docs/OUTPUT_DESIGN.md.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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


def overall_status(items: list[ItemResult], submission: dict | None) -> str:
    failed = any(i.plan.status == "ANSWER" and (not i.filled or i.verified is False) for i in items)
    outcome = (submission or {}).get("outcome")
    if failed or outcome in ("ERROR", "BLOCKED_BY_VALIDATION"):
        return "FAILED"
    if outcome == "CONFIRMED":
        return "SUBMITTED"
    if outcome == "UNCONFIRMED":
        return "SUBMITTED_UNCONFIRMED"
    if any(i.plan.status == "REVIEW" for i in items):
        return "NEEDS_REVIEW"
    return "FILLED"


@dataclass
class RunResult:
    url: str
    status: str
    items: list[ItemResult]
    submission: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished_at: str = ""

    @property
    def review_items(self) -> list[ItemResult]:
        return [i for i in self.items if i.plan.status == "REVIEW"]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["review_items"] = [
            {"question_id": i.plan.question_id, "question": i.plan.question, "required": i.plan.required,
             "reason": i.plan.reason, "alternatives": i.plan.alternatives}
            for i in self.review_items
        ]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
