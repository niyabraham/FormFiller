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
from enum import Enum
from typing import Any

from formfill.web.models import AnswerPlanItem


@dataclass
class ItemResult:
    plan: AnswerPlanItem
    filled: bool = False
    observed: Any = None  # what the page holds after the run
    verified: bool | None = None  # current read-back matched; None = unobservable or no ANSWER to verify
    ever_verified: bool = False  # at least one read-back matched while the control was mounted
    browser_valid: bool | None = None  # HTML constraint validation on the control
    detail: str = ""
    prefilled_warning: bool = False  # a REVIEW control already held a value (template default)
    framework_attached_at_fill: bool | None = None  # text-like answers: did a UI framework (React/Vue/Svelte) already own the node when it was filled? None = not checked
    reentered: bool = False  # the value was cleared after the framework attached to the node, and was entered once more
    attempted: bool = False  # a fill was attempted (False for REVIEW items and for answers proposed but never entered)
    section: str = ""  # form section / wizard step heading the question was asked under
    step: int | None = None  # wizard step on which the question was first answered (None for one-page runs)
    revisit_verified: bool | None = None  # re-checked on the Back re-verification pass: True matched, False differed, None not revisited

    @property
    def state(self) -> FieldState:
        return field_state(self)[0]


class FieldState(str, Enum):
    """Where one question stands. Exactly one applies; see field_state() for the rules."""

    PROPOSED = "proposed"  # an answer was planned but never entered (walk stopped earlier, or a resumed run did not reach it)
    ENTERED = "entered"  # entered, but no read-back has confirmed it yet
    VERIFIED = "verified"  # a read-back of the live control matched (now, or while it was last on screen: see the qualifier)
    REJECTED = "rejected"  # the fill failed, the browser says the value is invalid, or the page changed/cleared it
    SKIPPED = "skipped"  # deliberately not attempted (the control is disabled)
    NEEDS_REVIEW = "needs_review"  # no answer may be entered without a person (no evidence, ambiguity, attestation, ...)


def field_state(item: ItemResult) -> tuple[FieldState, str]:
    """(state, qualifier). A fill call that did not raise is never "verified": only a matching read-back is."""
    plan = item.plan
    if plan.status != "ANSWER":
        if (plan.reason or "").startswith("control is disabled"):
            return FieldState.SKIPPED, "control is disabled"
        return FieldState.NEEDS_REVIEW, plan.reason or ""
    if not item.filled:
        if item.attempted or item.detail.startswith("fill failed"):
            return FieldState.REJECTED, item.detail or "fill failed"
        return FieldState.PROPOSED, "not entered"
    if item.verified is True:
        return FieldState.VERIFIED, "current read-back matched"
    if item.verified is False:
        return FieldState.REJECTED, item.detail or "read-back did not match"
    if item.revisit_verified is False:
        return FieldState.REJECTED, "the value was gone or changed when the wizard was revisited"
    if item.ever_verified:
        return FieldState.VERIFIED, "matched while on screen; not observable now"
    return FieldState.ENTERED, "not yet read back"


def overall_status(items: list[ItemResult], submission: dict | None) -> str:
    outcome = (submission or {}).get("outcome")
    if not items:
        return "FAILED" if outcome in ("ERROR", "BLOCKED_BY_VALIDATION") else "NEEDS_REVIEW"
    failed = any(i.plan.status == "ANSWER" and (not i.filled or i.verified is False or i.revisit_verified is False) for i in items)
    if failed or outcome in ("ERROR", "BLOCKED_BY_VALIDATION"):
        return "FAILED"
    if any(i.plan.status == "ANSWER" and i.verified is None for i in items):
        return "NEEDS_REVIEW"
    if outcome == "SKIPPED":
        return "NEEDS_REVIEW"  # submission was asked for and refused for a safety reason: never "FILLED"
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
    controls: list[dict] = field(default_factory=list)  # discovery metadata for every processed control (diagnostic)
    navigation: dict = field(default_factory=dict)  # step-navigation record (only with a DiscoveryPolicy): steps, stop reason, notes
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished_at: str = ""
    unsupported: list[dict] = field(default_factory=list)  # visible controls that cannot be filled or verified (never touched); each needs a person

    @property
    def review_items(self) -> list[ItemResult]:
        return [i for i in self.items if i.plan.status == "REVIEW"]

    def summary(self) -> dict:
        return review_summary(self)

    def to_dict(self) -> dict:
        d = asdict(self)
        for item_dict, item in zip(d["items"], self.items, strict=True):
            state, why = field_state(item)
            item_dict["state"] = state.value
            item_dict["state_detail"] = why
        d["summary"] = review_summary(self)
        d["review_items"] = [
            {"question_id": i.plan.question_id, "question": i.plan.question, "required": i.plan.required,
             "reason": i.plan.reason, "alternatives": i.plan.alternatives}
            for i in self.review_items
        ]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def _norm_question(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (text or "").casefold()).split())


def review_summary(result: RunResult) -> dict:
    """What a person must look at before proceeding, for the whole questionnaire. Reviewing is not submitting: this summary
    never says a form is ready to submit, only what is still open."""
    counts = {s.value: 0 for s in FieldState}
    rows = []
    for item in result.items:
        state, why = field_state(item)
        counts[state.value] += 1
        rows.append((item, state, why))

    def brief(item: ItemResult, why: str = "") -> dict:
        return {"question_id": item.plan.question_id, "question": item.plan.question, "required": item.plan.required,
                "section": item.section, **({"why": why} if why else {})}

    required_open = [brief(i, f"{s.value}: {w}") for i, s, w in rows if i.plan.required and s is not FieldState.VERIFIED]
    required_open += [{"question_id": None, "question": u.get("label") or u.get("html_id") or u.get("tag"), "required": True,
                       "section": "", "why": f"unsupported control: {u.get('reason')}"} for u in result.unsupported if u.get("required")]
    attestations = [brief(i) for i, _, _ in rows if (i.plan.reason or "").startswith("attestation/consent")]
    conflicts = [{**brief(i), "conflicts": i.plan.conflicts} for i, _, _ in rows if i.plan.conflicts]
    conflicts += [brief(i, "the page treats this and another control as one choice") for i, _, _ in rows
                  if "overwritten by the page when" in i.detail]
    by_text: dict[str, list[ItemResult]] = {}
    for i, _, _ in rows:
        by_text.setdefault(_norm_question(i.plan.question), []).append(i)
    duplicates = [{"question": group[0].plan.question, "question_ids": [g.plan.question_id for g in group],
                   "sources": sorted({str(g.plan.source) for g in group if g.plan.source})}
                  for text, group in by_text.items() if text and len(group) > 1]
    nav = result.navigation or {}
    blocked = list(nav.get("blocked_requests") or [])
    refused = [n for n in nav.get("notes", []) if n.get("kind") in ("submit_type_next_refused", "dialog_on_navigation",
                                                                     "popup_opened", "required_unresolved")]
    return {
        "counts": counts,
        "total": len(rows),
        "required_unanswered": required_open,
        "needs_review": [brief(i, w) for i, s, w in rows if s is FieldState.NEEDS_REVIEW],
        "rejected": [brief(i, w) for i, s, w in rows if s is FieldState.REJECTED],
        "invalid": [brief(i, i.detail) for i, _, _ in rows if i.browser_valid is False],
        "attestations": attestations,
        "conflicts": conflicts,
        "duplicates": duplicates,
        "unsupported_controls": len(result.unsupported),
        "blocked_actions": {"requests": len(blocked), "refused_or_dismissed": refused},
        "submission": "not attempted" if not result.submission else result.submission.get("outcome"),
        "note": "Approving or filling answers is not submitting the questionnaire and is not a signature; submission stays a "
                "separate, human action.",
    }
