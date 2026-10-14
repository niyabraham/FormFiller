"""Phase 3D widget evaluation on the local SurveyJS-compatible fixtures (benchmarks/spa/fixtures/w3d_*).

    python tools/evaluate_widgets3d.py --out-dir <dir>

Four things are reported separately, per field, because they are different claims:
  fill_ok       the pipeline's fill step reported no error
  dom_readback  the pipeline's independent read of the page's own element matched the planned answer
  app_state     the application's own record (window.__state, exposed by the fixture) holds the expected value.
                Only measurable because the fixtures publish it; a real portal gives no such view.
  unsettled     the pipeline reported (warning + NEEDS_REVIEW) that the page never went quiet after a field was left
  side effects  clicks/submits received by a control planted over a combobox (must stay 0)
  discovered    a conditional question (one that exists only after an earlier answer is committed) was found and filled
Generic local fixtures; this says nothing about the reliability of any real portal.
Run against another checkout with FORMFILL_PIPELINE_ROOT=<path> (used for the 'before' run on a clean worktree).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("FORMFILL_PIPELINE_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))
sys.path.append(str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from benchmarks.spa.server import serve
from formfill.web import execute as _execute
from formfill.web.pipeline import run_form

UNSETTLED = getattr(_execute, "UNSETTLED", "page did not go quiet")  # the Phase 3C code has no such constant

sys.path.append(str(Path(__file__).resolve().parent))
from _provenance import RECIPE, pipeline_source_sha256

BENCH = Path(__file__).resolve().parent.parent / "benchmarks" / "spa"
LABEL = {"name": "company name", "email": "email", "city": "city", "country": "country", "sector": "sector"}


def _git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=False).stdout.strip()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    gt = json.loads((BENCH / "ground_truth_3d.json").read_text())
    source = json.loads((BENCH / "source.json").read_text())
    rows = []
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("FORMFILL_CHROMIUM") or None)
        for fid, spec in gt.items():
            ctx = b.new_context()
            page = ctx.new_page()
            page.set_default_timeout(4000)
            page.goto(f"{base}/{fid.replace('?', '.html?') if '?' in fid else fid + '.html'}")
            t0 = time.monotonic()
            res = run_form(page, source, timeout_ms=5000)
            secs = round(time.monotonic() - t0, 2)
            state = page.evaluate("() => window.__state || {}")
            fields = {}
            keys = set(spec["expected"]) | {k for k, l in LABEL.items() if any(l in i.plan.question.lower() for i in res.items)}
            for key in sorted(keys):
                item = next((i for i in res.items if LABEL[key] in i.plan.question.lower()), None)
                exp = spec["expected"].get(key)
                fields[key] = {"expected": exp, "present": item is not None,
                               "fill_ok": bool(item and item.filled), "dom_readback": bool(item and item.verified),
                               "app_state": (state.get(key) == exp) if exp is not None else None,
                               "conditional": key in spec.get("conditional", []),
                               "detail": (item.detail if item else "")[:160]}
            side = page.evaluate("() => window.__sideEffects || null")
            rows.append({"fixture": fid, "desc": spec["desc"], "seconds": secs, "status": res.status, "warnings": res.warnings,
                         "unsettled_reported": any(UNSETTLED in w for w in res.warnings), "expect_unsettled": spec.get("expect_unsettled", False),
                         "side_effects": side, "side_effects_expected": spec.get("side_effects_expected"),
                         "submission_attempts": 0 if res.submission == {} else 1, "app_state": state, "fields": fields})
            ctx.close()
        b.close()
    import formfill
    prov = {"pipeline_module": str(Path(formfill.__file__).parent), "evaluated_commit": _git("rev-parse", "HEAD"),
            "pipeline_diff_sha256": pipeline_source_sha256(ROOT), "hash_recipe": RECIPE,
            "ground_truth_3d_sha256": sha(BENCH / "ground_truth_3d.json"), "tool_sha256": sha(Path(__file__)),
            "fixtures_sha256": {f.name: sha(f) for f in sorted((BENCH / "fixtures").glob("w3d_*.html"))}}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "widget_results.json").write_text(json.dumps({"provenance": prov, "results": rows}, indent=2) + "\n")
    tot = {m: sum(1 for r in rows for f in r["fields"].values() if f["expected"] is not None and f[m]) for m in ("fill_ok", "dom_readback", "app_state")}
    n = sum(1 for r in rows for f in r["fields"].values() if f["expected"] is not None)
    cond = [f for r in rows for f in r["fields"].values() if f["conditional"]]
    print(f"{n} expected fields: fill_ok {tot['fill_ok']}, dom_readback {tot['dom_readback']}, app_state {tot['app_state']}; "
          f"conditional discovered+filled {sum(f['fill_ok'] for f in cond)}/{len(cond)}")
    bad_side = [r["fixture"] for r in rows if r["side_effects_expected"] is not None and r["side_effects"] != r["side_effects_expected"]]
    bad_unsettled = [r["fixture"] for r in rows if r["unsettled_reported"] != r["expect_unsettled"]]
    print(f"side-effect mismatches: {bad_side or 'none'}; unsettled-report mismatches: {bad_unsettled or 'none'}")
    for r in rows:
        print(f"  {r['fixture']:38} {r['seconds']:5}s", {k: (f['fill_ok'], f['dom_readback'], f['app_state']) for k, f in r['fields'].items()})


if __name__ == "__main__":
    main()
