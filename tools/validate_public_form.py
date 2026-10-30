"""Non-submitting validation run against a page you are allowed to test, using a fictional JSON source.

    python tools/validate_public_form.py --url https://example.test/form --source my_fictional_source.json \
        [--policy] [--out-dir output/public_validation] [--confirm-ms 1000] [--readiness-timeout-ms 5000] [--headed] [--trace]

Safety: this script has no submit option. It always calls the pipeline in its non-submitting mode, and a test checks that
the file never asks the pipeline to submit. Use it only on pages whose owner permits testing, with fictional data. Use `--policy` for
multi-step (wizard) forms: it presses only recognised Next-style buttons and refuses submit-type controls.

It prints one row per question (ANSWER/REVIEW, what the page holds afterwards, whether it matched), the overall status and
any warnings, and writes result.json, audit_report.md and filled.png (plus trace.zip with --trace) to --out-dir. Set FORMFILL_CHROMIUM to use a specific
Chromium. A finished run on a real page is evidence for that page only; it does not show the pipeline works elsewhere.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formfill.web.pipeline import DEFAULT_CONFIRM_MS, run_url
from formfill.web.steps import DiscoveryPolicy


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True, help="http(s) page to test; never submitted")
    ap.add_argument("--source", required=True, help="fictional JSON source file")
    ap.add_argument("--out-dir", default="output/public_validation")
    ap.add_argument("--policy", action="store_true", help="walk multi-step forms with the step-navigation policy")
    ap.add_argument("--confirm-ms", type=int, default=DEFAULT_CONFIRM_MS, help="wait before the final read-back; 0 disables")
    ap.add_argument("--readiness-timeout-ms", type=int, default=5000)
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--trace", action="store_true",
                    help="also save a Playwright trace (trace.zip). It holds the page content and the answers entered; cookie and "
                         "authorization values are removed from it")
    args = ap.parse_args(argv)
    if not args.url.lower().startswith(("http://", "https://")):
        ap.error("--url must start with http:// or https://")

    kwargs: dict = {"submit": False, "confirm_ms": args.confirm_ms, "readiness_timeout_ms": args.readiness_timeout_ms}
    if args.policy:
        kwargs["policy"] = DiscoveryPolicy()
    result = run_url(args.url, args.source, out_dir=args.out_dir, headless=not args.headed, trace=args.trace, **kwargs)

    print(f"{'QUESTION':<46}{'PLAN':<8}{'FILLED':<8}{'VERIFIED':<10}PAGE HOLDS / REASON")
    print("-" * 120)
    for i in result.items:
        p = i.plan
        held = str(i.observed)[:40] if p.status == "ANSWER" else p.reason[:60]
        print(f"{p.question[:44]:<46}{p.status:<8}{i.filled!s:<8}{i.verified!s:<10}{held}")
    counts = Counter(i.plan.status for i in result.items)
    print(f"\nControls processed: {len(result.items)} (ANSWER {counts['ANSWER']}, REVIEW {counts['REVIEW']})")
    print(f"Run status: {result.status}")
    print(f"Submission attempted: {bool(result.submission.get('attempted'))}")
    for w in result.warnings:
        print(f"Warning: {w}")
    print(f"Artifacts: {', '.join(Path(v).name for v in result.artifacts.values())} in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
