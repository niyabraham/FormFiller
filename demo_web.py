"""Run with:

    python demo_web.py            # fill the example RFI page, do not submit
    python demo_web.py --submit   # also submit (only if no required item needs review)

Opens examples/web/rfi_form.html in headless Chromium, discovers the form,
answers it from examples/web/rfi_source.json, verifies, and writes
output/web/{result.json,filled.png,trace.zip}. Set FORMFILL_CHROMIUM to use a
specific Chromium executable. View the trace with `playwright show-trace`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from formfill.web.pipeline import run_url

ROOT = Path(__file__).resolve().parent


def main() -> None:
    submit = "--submit" in sys.argv
    out = ROOT / "output" / "web"
    result = run_url(
        (ROOT / "examples" / "web" / "rfi_form.html").as_uri(),
        ROOT / "examples" / "web" / "rfi_source.json",
        out_dir=out, submit=submit, success_text="Thank you, your response was received",
    )
    print(f"{'QUESTION':<44}{'STATUS':<8}{'ANSWER':<24}SOURCE / REASON")
    print("-" * 110)
    for i in result.items:
        p = i.plan
        detail = f"{p.source} ({p.confidence:.2f})" if p.status == "ANSWER" else p.reason
        verdict = "" if p.status == "REVIEW" else (" ok" if i.verified else " MISMATCH")
        print(f"{p.question[:42]:<44}{p.status:<8}{str(p.answer if p.status == 'ANSWER' else ''):<24}{detail}{verdict}")
    print(f"\nRun status: {result.status}")
    if result.submission:
        print(f"Submission: {result.submission}")
    for w in result.warnings:
        print(f"Warning: {w}")
    print(f"Artifacts: {', '.join(Path(v).name for v in result.artifacts.values())} in output/web/")


if __name__ == "__main__":
    main()
