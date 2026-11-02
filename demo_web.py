"""Run with:

    python demo_web.py              # fill the small example page (examples/web/) and do not submit it
    python demo_web.py --submit     # also submit it, but only if every check passes (the example page is local and sends nothing)

    # the portfolio demo: a fictional eight-section security questionnaire (see docs/demo/DEMO_GUIDE.md)
    python demo_web.py --form docs/demo/security_questionnaire.html --source docs/demo/company_source.json --out output/demo

    # after deciding in the review page, enter the approved and edited answers and read them back again
    python demo_web.py --form docs/demo/security_questionnaire.html --source docs/demo/company_source.json \\
        --out output/demo-reviewed --review output/demo/review.json

Opens the page in headless Chromium, discovers the form, answers it from the JSON source, reads the page back to verify,
and writes result.json, audit_report.md and filled.png to --out (default output/web), plus trace.zip with --trace. Nothing is
submitted unless --submit is given and every check passed; the submit control is never pressed otherwise. Set FORMFILL_CHROMIUM to
use a specific Chromium executable. View a trace with `playwright show-trace`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from formfill.web.pipeline import run_url
from formfill.web.result import ItemResult, RunResult, field_state

ROOT = Path(__file__).resolve().parent
SUCCESS_TEXT = "Thank you, your response was received"  # shown by the local example pages after a submit


def _clip(text: object, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 3] + "..."


def print_item(i: ItemResult) -> None:
    p = i.plan
    state, _ = field_state(i)
    label = p.question + (" *" if p.required and not p.question.rstrip().endswith("*") else "")
    proposal_source = (p.alternatives[0].get("source") if p.alternatives else "") or ""
    if p.status == "ANSWER":
        shown = p.answer if i.verified else f"{p.answer} (page holds: {i.observed})"
        if p.method == "human_approved":
            how = f"approved by the reviewer (proposal from {proposal_source}) [{p.method}]"
        elif p.method == "human_edited":
            how = f"typed by the reviewer [{p.method}]"
        else:
            how = f"{p.source} [{p.confidence_category}, {p.method}]"
    else:
        shown = ""
        reason = re.sub(r" \(\d{4}-[^)]*\)", "", p.reason or "")  # drop the decision timestamp from "rejected by the reviewer (...)"
        how = _clip(reason, 86)
        if p.proposed_answer is not None and not reason.startswith("rejected by the reviewer"):
            how = f"proposal, not entered: {_clip(p.proposed_answer, 24)} from {proposal_source} [{p.method}, {p.confidence_category}]"
    print(f"{state.value.upper():<14}{_clip(label, 46):<48}{_clip(shown, 30):<32}{how}")


def print_report(result: RunResult) -> None:
    """One line per question, grouped by the page's own section headings. ASCII only, so a redirected Windows console cannot choke."""
    print(f"{'STATE':<14}{'QUESTION':<48}{'VALUE':<32}EVIDENCE / REASON")
    print("-" * 150)
    by_section: dict[str, list[ItemResult]] = {}  # a conditional field found in a later round still prints under its own heading
    for i in result.items:
        by_section.setdefault(i.section, []).append(i)
    for section, items in by_section.items():
        print(f"\n[{section or 'no section'}]")
        for i in items:
            print_item(i)
    if result.unsupported:
        print("\n[Controls FormFiller cannot fill - reported, never touched]")
        for u in result.unsupported:
            print(f"{'UNSUPPORTED':<14}{_clip(u.get('label') or u.get('html_id') or u.get('tag'), 46):<48}{'':<32}{_clip(u.get('reason') or u.get('kind'), 86)}")
    counts = result.summary()["counts"]
    print("\n" + " | ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items() if n)
          + (f" | {len(result.unsupported)} unsupported control(s)" if result.unsupported else ""))
    print(f"Run status: {result.status}")
    if result.submission:
        print(f"Submission: {result.submission}")
    else:
        print("Submission: not attempted. Review the form, then submit it yourself in the portal.")
    for w in result.warnings:
        print(f"Warning: {_clip(w, 200)}")
    print(f"Artifacts: {', '.join(Path(v).name for v in result.artifacts.values())}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fill a local example questionnaire from a JSON source, verify it, and never submit it by itself.")
    ap.add_argument("--form", type=Path, default=ROOT / "examples" / "web" / "rfi_form.html", help="the HTML page to fill (default: the small example)")
    ap.add_argument("--source", type=Path, default=ROOT / "examples" / "web" / "rfi_source.json", help="the JSON source of facts")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "web", help="where result.json, audit_report.md and filled.png go")
    ap.add_argument("--trace", action="store_true", help="also record a Playwright trace (trace.zip); it holds page content and the answers entered")
    ap.add_argument("--review", type=Path, help="a review.json made in the review page: its approved and edited answers are entered and read back")
    ap.add_argument("--submit", action="store_true", help="also press Submit, but only if every check passes: it is refused while a required question or a declaration is open, an answer failed, or an unsupported control has no decision")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a source value with a character the console cannot show must not crash the report

    extra = {}
    if args.review:
        from formfill.web.review import decisions_planner, load_review

        extra["planner"] = decisions_planner(load_review(args.review))
    result = run_url(
        args.form.resolve().as_uri(), args.source, out_dir=args.out, submit=args.submit, success_text=SUCCESS_TEXT,
        trace=args.trace,  # off unless asked: a trace holds page content and answers (run_url records none by default)
        **extra,
    )
    print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
