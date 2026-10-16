"""Command line: `python -m formfill ...` (or the `formfill` script after `pip install -e .`).

    formfill fill --source company.json --url https://portal.example/rfi --out-dir out/
    formfill fill --source company.json --url examples/web/rfi_form.html --out-dir out/ --redact
    formfill ask  --source company.json "How many employees does your company have?"
    formfill check-source --source company.json

FormFiller never submits. `fill` fills what it can prove, leaves the rest for a person, reads every answer back, writes the
report, and stops. Exit codes: 0 ran to the end, 1 --strict and not ready for human review, 2 usage, 3 source error,
4 browser or navigation error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from formfill.web.source import SourceError, describe, load_source


def _url(arg: str) -> str:
    if "://" in arg:
        return arg
    p = Path(arg)
    if p.is_file():
        return p.resolve().as_uri()
    raise SystemExit(f"error: {arg!r} is neither a URL nor an existing HTML file")


def _print_table(result) -> None:
    print(f"{'QUESTION':<46}{'OUTCOME':<22}{'ANSWER':<22}SOURCE / REASON")
    print("-" * 118)
    for i in result.items:
        p = i.plan
        detail = f"{p.source} ({p.confidence:.2f})" if p.status == "ANSWER" else (p.reason or "")
        shown = "" if p.status != "ANSWER" else str(p.answer)
        print(f"{p.question[:44]:<46}{i.outcome:<22}{shown[:20]:<22}{detail[:90]}")
    s = result.summary()
    print(f"\nstatus: {result.status}   questions: {s['questions']}   " +
          "   ".join(f"{k}: {v}" for k, v in s.items() if k not in ("questions", "status", "ready_for_human_review")))
    hs = result.human_submission
    print(f"submission: NOT performed by FormFiller - {hs['action_required']}")
    print(f"ready for human review: {hs['ready_for_human_review']}")
    for b in hs["blockers"]:
        print(f"  blocker: {b}")
    for w in result.warnings:
        print(f"warning: {w}")
    for a in result.not_asked:
        print(f"not asked ({a['why']}): {a['label']}")


def cmd_fill(args) -> int:
    from formfill.web.pipeline import run_url
    from formfill.web.steps import DiscoveryPolicy

    try:
        load_source(args.source)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if args.chromium:
        import os

        os.environ["FORMFILL_CHROMIUM"] = args.chromium
    kw: dict = {"redact": args.redact, "screenshot": not (args.no_screenshot or args.redact), "timeout_ms": args.timeout_ms}
    if args.wizard:
        kw["policy"] = DiscoveryPolicy()
    try:
        result = run_url(_url(args.url), args.source, out_dir=args.out_dir, trace=not (args.no_trace or args.redact),
                         headless=not args.headed, **kw)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - browser missing, page unreachable, ...
        print(f"error: {type(exc).__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 4
    if not args.quiet:
        _print_table(result)
    print(f"artifacts: {json.dumps(dict(result.artifacts), indent=2)}")
    return 1 if args.strict and not result.human_submission["ready_for_human_review"] else 0


def cmd_ask(args) -> int:
    from formfill.web.models import Control, Option
    from formfill.web.plan import plan_question
    from formfill.web.retrieve import index_source
    from formfill.web.understand import understand_control

    try:
        source = load_source(args.source)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    control = Control(control_id="q", kind=args.kind, label=args.question, options=[Option(o, o) for o in args.option])
    item = plan_question(understand_control(control), index_source(source))
    out = {"question": item.question, "status": item.status, "answer": item.answer, "source": item.source,
           "confidence": round(item.confidence, 3), "reason": item.reason, "evidence": item.evidence,
           "alternatives": item.alternatives}
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_check_source(args) -> int:
    try:
        d = describe(load_source(args.source))
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({k: v for k, v in d.items() if k != "paths" or args.paths}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="formfill", description="Fill a DOM-based RFI form from JSON company data. Never submits.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fill", help="fill a web form and write a report (never submits)")
    f.add_argument("--source", required=True, help="JSON file with the company data")
    f.add_argument("--url", required=True, help="page URL, or a local .html file")
    f.add_argument("--out-dir", default="output/run", help="where result.json, filled.png and trace.zip are written")
    f.add_argument("--wizard", action="store_true", help="walk multi-step forms by pressing safe Next buttons (never Submit)")
    f.add_argument("--headed", action="store_true", help="show the browser window")
    f.add_argument("--chromium", help="path to a Chromium executable (default: Playwright's, or $FORMFILL_CHROMIUM)")
    f.add_argument("--timeout-ms", type=int, default=5000)
    f.add_argument("--redact", action="store_true", help="company values are replaced by [redacted] in result.json; screenshot and trace are not written")
    f.add_argument("--no-screenshot", action="store_true")
    f.add_argument("--no-trace", action="store_true")
    f.add_argument("--strict", action="store_true", help="exit 1 unless the form is ready for human review")
    f.add_argument("--quiet", action="store_true")
    f.set_defaults(fn=cmd_fill)
    a = sub.add_parser("ask", help="which source value would answer this question? (no browser)")
    a.add_argument("--source", required=True)
    a.add_argument("question")
    a.add_argument("--kind", default="text", help="text|number|date|email|url|tel|select|radio|checkbox|textarea|multiselect")
    a.add_argument("--option", action="append", default=[], help="an allowed option (repeat for several)")
    a.set_defaults(fn=cmd_ask)
    c = sub.add_parser("check-source", help="validate and describe a source file")
    c.add_argument("--source", required=True)
    c.add_argument("--paths", action="store_true", help="also list every answerable path")
    c.set_defaults(fn=cmd_check_source)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
