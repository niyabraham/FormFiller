"""Audit report: a human-readable account of one run (Markdown), derived only from the RunResult.

Counts of filled, verified, skipped, blocked, invalid and review-required fields; every question with its state, evidence and
reason; the navigation history (steps, transitions, why the walk stopped); requests that were blocked or relayed; controls
FormFiller could not handle. `redact_values=True` replaces entered answers and evidence values with a marker so the report can
be shared without the company data in it. The report never states that a questionnaire was submitted unless the result says
so, and it repeats that approval or filling is not a submission or a signature.
"""

from __future__ import annotations

from pathlib import Path

from formfill.web.artifacts import write_text_atomic
from formfill.web.result import FieldState, RunResult, field_state

REDACTED = "[redacted]"


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ").strip()[:200]


def render_audit_report(result: RunResult, *, redact_values: bool = False) -> str:
    s = result.summary()
    nav = result.navigation or {}
    walked = "steps_visited" in nav  # a multi-step walk (a one-page run may still carry resume notes here)
    counts = s["counts"]
    filled = sum(1 for i in result.items if i.filled)
    invalid = len(s["invalid"])
    blocked = len(nav.get("blocked_requests") or [])
    lines = [
        "# FormFiller audit report",
        "",
        f"- Run: `{result.run_id}` started {result.started_at}, finished {result.finished_at or 'n/a'}",
        f"- Page: {_cell(result.url.split('?', 1)[0])}",
        f"- Overall status: **{result.status}**",
        f"- Submission: {s['submission']}",
    ]
    if walked:
        lines += [f"- Multi-step walk: {nav.get('steps_visited', 0)} step(s), stopped: `{nav.get('stop_reason')}`"
                  f" (completion: {nav.get('completion', 'n/a')})",
                  f"- Network: {nav.get('network_mode', 'block_all')}; {blocked} request(s) blocked, "
                  f"{len(nav.get('permitted_requests') or [])} relayed under explicit rules"]
    lines += ["", "> " + s["note"], "", "## Counts", "", "| measure | count |", "|---|---|",
              f"| questions | {s['total']} |", f"| filled (entered) | {filled} |",
              *[f"| state: {k} | {v} |" for k, v in counts.items()],
              f"| browser-invalid after filling | {invalid} |", f"| blocked requests | {blocked} |",
              f"| required still open | {len(s['required_unanswered'])} |", f"| attestations / consents (never answered) | {len(s['attestations'])} |",
              f"| unsupported controls (not touched) | {s['unsupported_controls']} |", ""]

    lines += ["## Questions", "", "| # | question | section | state | answer (or proposal) | source | method | confidence | why |",
              "|---|---|---|---|---|---|---|---|---|"]
    for n, item in enumerate(result.items, 1):
        p = item.plan
        state, why = field_state(item)
        answer = p.answer if p.status == "ANSWER" else p.proposed_answer
        answer = REDACTED if (redact_values and answer not in (None, "")) else answer
        if p.status != "ANSWER" and answer not in (None, ""):
            answer = f"proposed, not entered: {answer}"  # a suggestion for the reviewer must never read as an answer
        conf = f"{p.confidence:.2f}" + (f" ({p.confidence_category})" if p.confidence_category else "") if p.status == "ANSWER" else ""
        reason = p.reason or why
        lines.append(f"| {n} | {_cell(p.question)} | {_cell(item.section)} | {state.value} | {_cell(answer)} | {_cell(p.source)} | "
                     f"{_cell(p.method)} | {conf} | {_cell(reason)} |")
    lines.append("")

    if s["required_unanswered"]:
        lines += ["## Required questions still open", ""] + [f"- {_cell(q['question'])}: {_cell(q.get('why'))}" for q in s["required_unanswered"]] + [""]
    if s["conflicts"]:
        lines += ["## Conflicting evidence", ""] + [f"- {_cell(c['question'])}: {_cell(c.get('conflicts') or c.get('why'))}" for c in s["conflicts"]] + [""]
    if s["duplicates"]:
        lines += ["## Questions asked more than once", ""] + [f"- {_cell(d['question'])} ({len(d['question_ids'])} controls)" for d in s["duplicates"]] + [""]

    if walked:
        lines += ["## Navigation", "", "| step | heading | transition | required open |", "|---|---|---|---|"]
        for st in nav.get("steps", []):
            lines.append(f"| {st.get('step')} | {_cell(st.get('heading'))} | {st.get('transition') or 'last step reached'} | "
                         f"{len(st.get('required_unresolved') or [])} |")
        lines += ["", f"Stopped: `{nav.get('stop_reason')}`."]
        for note in nav.get("notes", []):
            if note.get("kind") == nav.get("stop_reason") and note.get("reason"):
                lines.append(f"Reason: {_cell(note['reason'])}")
                break
        rv = nav.get("revisit")
        if rv:
            lines.append(f"Back re-verification: {len(rv['reverified'])} answer(s) still held, {len(rv['mismatched'])} changed; "
                         f"returned to the last step: {rv['returned_to_last_step']}.")
        lines.append("")
        if nav.get("blocked_requests"):
            lines += ["### Blocked requests", ""] + [f"- {r['method']} {_cell(r['url'] or r['resource_type'])}"
                                                     + (f" - {_cell(r['reason'])}" if r.get("reason") else "")
                                                     for r in nav["blocked_requests"][:50]] + [""]
        if nav.get("permitted_requests"):
            lines += ["### Requests relayed under explicit rules", ""] + [
                f"- {r['method']} {_cell(r['url'])} -> {r.get('status')} (rule: {_cell(r.get('rule'))}"
                + ("; carried entered answers" if r.get("carries_answers") else "") + ")" for r in nav["permitted_requests"][:50]] + [""]
    if result.unsupported:
        lines += ["## Controls FormFiller cannot fill (left for a person)", ""] + [
            f"- {_cell(u.get('label') or u.get('html_id') or u.get('tag'))} ({u.get('kind')}{', required' if u.get('required') else ''})"
            for u in result.unsupported] + [""]
    if result.warnings:
        lines += ["## Warnings", ""] + [f"- {_cell(w)}" for w in result.warnings] + [""]
    verified = counts.get(FieldState.VERIFIED.value, 0)
    lines += ["## Bottom line", "",
              f"{verified} of {s['total']} question(s) verified on the page; {len(s['required_unanswered'])} required question(s) "
              f"still open; {counts.get(FieldState.NEEDS_REVIEW.value, 0)} need a person. Nothing in this report is a submission "
              "or a signature.", ""]
    return "\n".join(lines)


def write_audit_report(result: RunResult, path: str | Path, *, redact_values: bool = False) -> Path:
    return write_text_atomic(path, render_audit_report(result, redact_values=redact_values))
