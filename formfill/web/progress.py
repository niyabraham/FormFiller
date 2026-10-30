"""Resumable progress for a questionnaire run: a versioned, validated JSON file, written atomically after every verified step.

What is stored: the run id and timestamps, the target (origin and path only: a query string may carry tokens), the navigation
progress (steps, their fingerprints and transitions, the stop reason), and per question its identity on the page (label,
name, id, section, kind), the planned answer and where it came from, whether it was entered and verified, its state, and why
it needs review. What is never stored: cookies, session tokens, credentials, browser profiles or storage state. The file
does contain answers (confidential company data): it is written owner-only where the OS supports it (artifacts.py).

Resuming (`run_form(..., progress_path=..., resume=True)`) never trusts the file blindly:

1. the file must parse, carry this schema and version, and be complete; a stale file (older than `max_age_hours`) is refused;
2. the page must be on the same origin as the saved target;
3. the current form is re-discovered and each control is matched to a saved question by its identity;
4. a matched control is READ BACK: if it already holds the saved answer it is verified and not entered again (no duplicate
   action); if it is empty the question is planned and entered as normal; if it holds a different value it is NOT
   overwritten and goes to review;
5. a control that matches several saved questions (or a saved question that matches several controls) stops the walk for
   review (`resume_ambiguous`): the state cannot be told apart safely.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page

from formfill.web.artifacts import write_text_atomic
from formfill.web.execute import matches, read_back
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.result import ItemResult, field_state
from formfill.web.verify import signature

SCHEMA = "formfill.progress"
SCHEMA_VERSION = 1


class ProgressError(ValueError):
    """The progress file cannot be used to resume (corrupt, incomplete, incompatible, stale, or for another target)."""


class ResumeConflict(RuntimeError):
    """The current page cannot be matched to the saved state without guessing."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def target_of(url: str) -> dict:
    try:
        p = urlsplit(url)
        return {"origin": f"{p.scheme}://{p.netloc}".lower(), "path": p.path}
    except ValueError:
        return {"origin": "", "path": ""}


def _sig_dict(c: Control) -> dict:
    label, name, html_id, section, kind = signature(c)
    return {"label": label, "name": name, "html_id": html_id, "section": section, "kind": kind}


def _json_safe(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


def field_record(qid: str, item: ItemResult, control: Control) -> dict:
    p = item.plan
    state, why = field_state(item)
    return {"question_id": qid, "signature": _sig_dict(control), "question": p.question, "required": bool(p.required),
            "step": item.step, "status": p.status, "answer": _json_safe(p.answer), "source": p.source,
            "method": p.method, "confidence": p.confidence, "reason": p.reason, "entered": item.filled,
            "verified": item.verified, "ever_verified": item.ever_verified, "state": state.value, "state_detail": why}


def _nav_summary(nav: dict) -> dict:
    return {"steps_visited": nav.get("steps_visited", 0), "stop_reason": nav.get("stop_reason"), "state": nav.get("state"),
            "steps": [{k: s.get(k) for k in ("step", "fingerprint", "path", "heading", "transition")} for s in nav.get("steps", [])],
            "network_mode": nav.get("network_mode", "block_all"),
            "blocked_requests": len(nav.get("blocked_requests") or []),
            "permitted_requests": len(nav.get("permitted_requests") or [])}


@dataclass
class ProgressWriter:
    """Checkpoint callback for `run_form`: writes the whole state atomically each time it is called."""

    path: Path
    target_url: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=_now)
    resumed_from: str | None = None
    previous_fields: list[dict] = field(default_factory=list)  # a resumed run keeps what the earlier run recorded but did not meet again
    writes: int = 0

    def carried_over(self, controls: dict) -> list[dict]:
        here = {_key(_sig_dict(c)) for c in controls.values()}
        return [{**f, "carried_over": True, "state_detail": "recorded by the earlier run; not on screen in this one, not re-verified"}
                for f in self.previous_fields if _key(f["signature"]) not in here]

    def build(self, nav: dict, items: dict, controls: dict, event: str) -> dict:
        current = [field_record(q, items[q], controls[q]) for q in items if q in controls]
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "run_id": self.run_id, "created_at": self.created_at,
                "updated_at": _now(), "event": event, "resumed_from": self.resumed_from, "target": target_of(self.target_url),
                "navigation": _nav_summary(nav), "fields": current + self.carried_over(controls)}

    def __call__(self, nav: dict, items: dict, controls: dict, event: str) -> None:
        write_text_atomic(self.path, json.dumps(self.build(nav, items, controls, event), indent=2, default=str))
        self.writes += 1


# ---- loading and validating -------------------------------------------------------------------------------------------------

_FIELD_TYPES: dict[str, type] = {"question_id": str, "signature": dict, "question": str, "required": bool, "status": str, "entered": bool,
                "state": str}
_SIG_KEYS = {"label", "name", "html_id", "section", "kind"}


def validate_progress(data: Any) -> dict:
    """Return `data` if it is a complete progress document of this schema version; raise ProgressError otherwise."""
    if not isinstance(data, dict):
        raise ProgressError("progress file is not a JSON object")
    if data.get("schema") != SCHEMA:
        raise ProgressError(f"not a FormFiller progress file (schema {data.get('schema')!r})")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ProgressError(f"incompatible progress schema version {data.get('schema_version')!r} (this version reads {SCHEMA_VERSION})")
    top_level: tuple[tuple[str, type], ...] = (("run_id", str), ("updated_at", str), ("target", dict), ("navigation", dict), ("fields", list))
    for key, expected in top_level:
        if not isinstance(data.get(key), expected):
            raise ProgressError(f"incomplete progress file: {key!r} is missing or not a {expected.__name__}")
    if not isinstance(data["target"].get("origin"), str) or not data["target"]["origin"]:
        raise ProgressError("incomplete progress file: no target origin")
    for i, f in enumerate(data["fields"]):
        if not isinstance(f, dict):
            raise ProgressError(f"incomplete progress file: field {i} is not an object")
        for key, typ in _FIELD_TYPES.items():
            if not isinstance(f.get(key), typ):
                raise ProgressError(f"incomplete progress file: field {i} has no valid {key!r}")
        if set(f["signature"]) != _SIG_KEYS:
            raise ProgressError(f"incomplete progress file: field {i} has an invalid signature")
        if f["status"] not in ("ANSWER", "REVIEW"):
            raise ProgressError(f"incomplete progress file: field {i} has status {f['status']!r}")
    try:
        datetime.fromisoformat(data["updated_at"])
    except ValueError:
        raise ProgressError("incomplete progress file: 'updated_at' is not a timestamp") from None
    return data


def load_progress(path: str | Path, *, max_age_hours: float | None = 72.0, now: datetime | None = None) -> dict:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ProgressError(f"no progress file at {p}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProgressError(f"corrupt progress file ({exc.msg} at line {exc.lineno})") from None
    data = validate_progress(data)
    if max_age_hours is not None:
        age = (now or datetime.now(UTC)) - datetime.fromisoformat(data["updated_at"])
        if age > timedelta(hours=max_age_hours):
            raise ProgressError(f"stale progress file: last written {age.total_seconds() / 3600:.1f} h ago "
                                f"(limit {max_age_hours} h); start a new run or pass a larger max_age_hours deliberately")
    return data


# ---- resuming -----------------------------------------------------------------------------------------------------------------


def _key(sig: dict) -> tuple:
    return tuple(sig.get(k) for k in ("label", "name", "html_id", "section", "kind"))


class Reconciler:
    """Matches controls on the current page to saved questions (see the module docstring, steps 3-5)."""

    def __init__(self, progress: dict):
        self.saved: dict[tuple, list[dict]] = {}
        for f in progress["fields"]:
            self.saved.setdefault(_key(f["signature"]), []).append(f)
        self.used: set[tuple] = set()
        self.log: list[dict] = []

    def __call__(self, page: Page, control: Control, step: int | None) -> ItemResult | None:
        key = _key(_sig_dict(control))
        matches_ = self.saved.get(key, [])
        if not matches_:
            return None
        if len(matches_) > 1:
            raise ResumeConflict(f"{len(matches_)} saved questions look exactly like {control.label!r}; the saved state cannot be "
                                 "matched to the page without guessing")
        if key in self.used:
            raise ResumeConflict(f"several controls on the page look exactly like the saved question {control.label!r}")
        self.used.add(key)
        saved = matches_[0]
        if saved["status"] != "ANSWER":
            self.log.append({"question": saved["question"], "action": "replanned (was REVIEW)"})
            return None  # planned again: the source or a person's decision may have changed since
        obs = read_back(page, control)
        held = obs.value if obs.found else None
        plan = AnswerPlanItem(question_id=control.control_id, question=saved["question"], field_type=control.kind,
                              required=control.required, status="ANSWER", source=saved.get("source"), answer=saved.get("answer"),
                              raw_value=saved.get("answer"), confidence=float(saved.get("confidence") or 0.0),
                              method=saved.get("method") or "deterministic", validation="restored from progress file")
        if obs.found and matches(saved.get("answer"), held) and obs.valid:
            self.log.append({"question": saved["question"], "action": "re-verified, not re-entered"})
            return ItemResult(plan=plan, filled=True, attempted=True, observed=held, verified=True, ever_verified=True,
                              browser_valid=True, section=control.section, step=step,
                              detail="restored from the progress file: the page already holds the saved answer (re-verified, not entered again)")
        if held in (None, "", False, []):
            self.log.append({"question": saved["question"], "action": "empty on the page: planned and entered again"})
            return None
        self.log.append({"question": saved["question"], "action": "page holds a different value: not overwritten"})
        review = AnswerPlanItem(question_id=control.control_id, question=saved["question"], field_type=control.kind,
                                required=control.required, status="REVIEW", proposed_answer=saved.get("answer"),
                                reason=(f"resume: the page holds {held!r}, which differs from the saved answer {saved.get('answer')!r}; "
                                        "it was not overwritten - a person must decide which is right"))
        return ItemResult(plan=review, observed=held, section=control.section, step=step)


def check_target(progress: dict, page_url: str) -> list[str]:
    """Raise ProgressError when the page is not on the saved target's origin; return notes for smaller differences."""
    here = target_of(page_url)
    saved = progress["target"]
    if here["origin"] != saved["origin"]:
        raise ProgressError(f"the page is on {here['origin'] or 'no origin'}, but the progress file is for {saved['origin']}")
    return [] if here["path"] == saved.get("path") else [f"page path {here['path']!r} differs from the saved {saved.get('path')!r}"]
