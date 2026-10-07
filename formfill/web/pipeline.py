"""Orchestration: form first, then source, then answers, then browser.

    discover -> understand -> retrieve + plan (+validate) -> fill
             -> (re-discover for conditional fields) -> read-back verify
             -> [optional] submit -> RunResult

`run_form` takes an already-open Playwright Page, so the caller owns
browser launch, navigation, sign-in and tracing; tests drive it with local
fixture pages. `run_url` is the convenience wrapper that does the launch.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from formfill.web.discover import discover
from formfill.web.execute import fill_control, matches, read_back, submit as submit_form
from formfill.web.models import AnswerPlanItem, Control
from formfill.web.plan import build_plan
from formfill.web.result import ItemResult, RunResult, overall_status
from formfill.web.retrieve import index_source
from formfill.web.understand import understand


def run_form(
    page: Page,
    source: Any,
    *,
    submit: bool = False,
    submit_selector: str | None = None,
    success_text: str | None = None,
    out_dir: str | Path | None = None,
    max_rounds: int = 3,
    timeout_ms: int = 5000,
) -> RunResult:
    leaves = index_source(source)
    controls: dict[str, Control] = {}
    items: dict[str, ItemResult] = {}

    # Rounds handle conditional fields: answering one question can reveal more.
    for _ in range(max_rounds):
        schema = discover(page)
        new = [c for c in schema.controls if c.visible and c.control_id not in items]
        if not new:
            break
        questions = understand(new)
        for question, plan in zip(questions, build_plan(questions, leaves)):
            controls[plan.question_id] = question.control
            items[plan.question_id] = _fill_one(page, question.control, plan, timeout_ms)

    schema = discover(page)
    hidden = [c for c in schema.controls if not c.visible and c.control_id not in items]

    # Independent read-back of everything we touched or flagged.
    for qid, item in items.items():
        obs = read_back(page, controls[qid])
        item.observed = obs.value
        item.browser_valid = obs.valid
        if item.plan.status == "ANSWER":
            ok = obs.found and matches(item.plan.answer, obs.value)
            item.verified = ok
            if not ok:
                item.detail = (item.detail + f" expected {item.plan.answer!r}, page holds {obs.value!r}").strip()
            elif not obs.valid:
                item.detail = (item.detail + f" browser says invalid: {obs.message}").strip()
        else:
            held = obs.value not in (None, "", False, [])
            item.prefilled_warning = held
            if held:
                item.detail = f"REVIEW control already holds {obs.value!r} (page default) - not our answer"

    warnings = []
    if hidden:
        warnings.append(f"{len(hidden)} control(s) stayed hidden and were not asked")
    out = Path(out_dir) if out_dir else None
    artifacts: dict = {}
    if out:
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "filled.png"), full_page=True)
        artifacts["screenshot_filled"] = str(out / "filled.png")

    submission: dict = {}
    if submit:
        blockers = [i for i in items.values() if i.plan.status == "REVIEW" and i.plan.required]
        broken = [i for i in items.values() if i.plan.status == "ANSWER" and i.verified is False]
        if blockers or broken:
            submission = {"attempted": False, "outcome": "SKIPPED",
                          "detail": f"{len(blockers)} required item(s) need review, {len(broken)} failed verification"}
        else:
            submission = submit_form(page, submit_selector, success_text, timeout_ms)
            if out:
                page.screenshot(path=str(out / "after_submit.png"), full_page=True)
                artifacts["screenshot_after_submit"] = str(out / "after_submit.png")

    result = RunResult(
        url=page.url, status=overall_status(list(items.values()), submission if submit else None),
        items=list(items.values()), submission=submission, artifacts=artifacts, warnings=warnings,
    )
    result.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if out:
        (out / "result.json").write_text(result.to_json())
        result.artifacts["result_json"] = str(out / "result.json")
    return result


def _fill_one(page: Page, control: Control, plan: AnswerPlanItem, timeout_ms: int) -> ItemResult:
    if plan.status != "ANSWER":
        return ItemResult(plan=plan)
    try:
        fill_control(page, control, plan.answer, timeout_ms)
    except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
        return ItemResult(plan=plan, filled=False, detail=f"fill failed: {str(exc).splitlines()[0]}")
    return ItemResult(plan=plan, filled=True)


def run_url(url: str, source_path: str | Path, *, out_dir: str | Path | None = None, trace: bool = True,
            headless: bool = True, **kwargs: Any) -> RunResult:
    """Launch Chromium, open `url`, run the pipeline, optionally save a
    Playwright trace next to the result. `FORMFILL_CHROMIUM` can point at a
    specific Chromium executable."""
    from playwright.sync_api import sync_playwright

    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=exe)
        context = browser.new_context()
        if trace and out_dir:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        try:
            page.goto(url)
            result = run_form(page, source, out_dir=out_dir, **kwargs)
        finally:
            if trace and out_dir:
                trace_path = Path(out_dir) / "trace.zip"
                context.tracing.stop(path=str(trace_path))
            browser.close()
    if trace and out_dir:
        result.artifacts["trace"] = str(Path(out_dir) / "trace.zip")
        (Path(out_dir) / "result.json").write_text(result.to_json())
    return result
