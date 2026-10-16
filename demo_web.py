"""Run with:

    python demo_web.py            # fill the example RFI page; a person submits it

FormFiller never submits. Opens examples/web/rfi_form.html in headless Chromium, discovers the form,
answers it from examples/web/rfi_source.json, verifies, and never submits; it writes
output/web/{result.json,filled.png,trace.zip}. Set FORMFILL_CHROMIUM to use a
specific Chromium executable. View the trace with `playwright show-trace`.
"""

from __future__ import annotations

from pathlib import Path

from formfill.web.pipeline import run_url

ROOT = Path(__file__).resolve().parent


def main() -> None:
    out = ROOT / "output" / "web"
    result = run_url(
        (ROOT / "examples" / "web" / "rfi_form.html").as_uri(),
        ROOT / "examples" / "web" / "rfi_source.json",
        out_dir=out,
    )
    print(f"{'QUESTION':<44}{'STATUS':<8}{'ANSWER':<24}SOURCE / REASON")
    print("-" * 110)
    for i in result.items:
        p = i.plan
        detail = f"{p.source} ({p.confidence:.2f})" if p.status == "ANSWER" else p.reason
        verdict = "" if p.status == "REVIEW" else (" ok" if i.verified else " MISMATCH")
        print(f"{p.question[:42]:<44}{p.status:<8}{p.answer if p.status == 'ANSWER' else ''!s:<24}{detail}{verdict}")
    print(f"\nRun status: {result.status}")
    hs = result.human_submission
    print(f"Submission: not performed by FormFiller - {hs['action_required']} (ready for review: {hs['ready_for_human_review']})")
    for w in result.warnings:
        print(f"Warning: {w}")
    print(f"Artifacts: {', '.join(Path(v).name for v in result.artifacts.values())} in output/web/")


if __name__ == "__main__":
    main()
