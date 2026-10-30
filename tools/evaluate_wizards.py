"""Navigation and safety benchmark for the multi-step wizard fixtures. Kept separate from the matching reports: it measures how
a guarded walk moves through a questionnaire and what leaves the browser, not which source fact answers which question.

    python tools/evaluate_wizards.py --out-dir output/eval_wizards

Scenarios and their expected outcomes: benchmarks/wizards/scenarios.json (its sha256 is recorded in the report). Everything
runs against a 127.0.0.1 server started by this script; nothing outside the machine is contacted, nothing is written into
benchmarks/, and the data is fictional.

Per scenario: steps visited, stop reason, status, field states, requests relayed and blocked, and what the server received.
Safety invariants, checked on every scenario (a violation makes the exit code 1):
  * no final submission reached the server, and the page's own submit handler never ran;
  * every request that reached the server during the walk is in `navigation.permitted_requests` (or is a redirect hop of one);
  * no request carrying an entered answer reached the server unless the scenario's policy has an `answer_data` rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from benchmarks.wizards.server import serve  # noqa: E402
from formfill.web.netpolicy import NetworkPolicy  # noqa: E402
from formfill.web.pipeline import release_wizard_network_guard, run_form  # noqa: E402
from formfill.web.steps import DiscoveryPolicy  # noqa: E402

SCENARIOS = ROOT / "benchmarks" / "wizards" / "scenarios.json"


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=False).stdout.strip()


def network_policy(base: str, rules: dict, names: list[str] | None) -> NetworkPolicy | None:
    if not names:
        return None
    return NetworkPolicy.from_dict({"rules": [{**rules[n], "origin": rules[n]["origin"].replace("{base}", base)} for n in names]})


def _path(url: str) -> str:
    return urlsplit(url).path


def run_scenario(page, base: str, rec, spec: dict, data: dict) -> dict:
    release_wizard_network_guard(page)  # the previous scenario's guard stays on (fail closed) until released
    rec.requests.clear()
    rec.autosaves.clear()
    rec.final_submissions = 0
    rec.sessions.clear()
    page.goto(base + spec["url"])
    # The page's own start-up requests (server_spa.html fetches section 1 from an inline script, which does not hold up the
    # load event) happen before the walk and its guard; wait for them so they are not counted as traffic during the walk.
    page.wait_for_load_state("networkidle")
    before = len(rec.requests)
    names = spec.get("rules") or []
    policy = network_policy(base, data["rules"], names)
    started = time.perf_counter()
    result = run_form(page, data["sources"][spec["source"]], policy=DiscoveryPolicy(**spec.get("policy", {})),
                      network_policy=policy, submit=spec.get("submit", False), confirm_ms=0)
    elapsed = round(time.perf_counter() - started, 2)
    nav = result.navigation or {}
    during = rec.requests[before:]
    permitted = nav.get("permitted_requests") or []

    # every request the server saw must be accounted for by a relayed request (or one of its redirect hops)
    accounted = Counter(_path(r["url"]) for r in permitted)
    accounted.update(_path(h) for r in permitted for h in r.get("redirect_hops") or [])
    unaccounted = []
    for method, path, _ in during:
        if accounted[path] > 0:
            accounted[path] -= 1
        else:
            unaccounted.append(f"{method} {path}")

    entered = [str(i.plan.answer) for i in result.items if i.filled and len(str(i.plan.answer)) >= 4]
    answer_rule = any(data["rules"][n].get("answer_data") for n in names)
    carried = [f"{m} {p}" for m, p, body in during if any(v.lower() in (p + " " + body).lower() for v in entered)]
    submitted_in_page = page.evaluate("() => window.__submitted ?? null")

    states = Counter(i.state.value for i in result.items)
    revisit = nav.get("revisit") or {}
    observed = {
        "steps_visited": nav.get("steps_visited"),
        "stop_reason": nav.get("stop_reason"),
        "completion": nav.get("completion"),
        "status": result.status,
        "field_states": dict(states),
        "verified": states.get("verified", 0),
        "rejected": states.get("rejected", 0),
        "permitted": len(permitted),
        "carrying_answers": sum(1 for r in permitted if r.get("carries_answers")),
        "blocked": len(nav.get("blocked_requests") or []),
        "server_requests": len(during),
        "server_posts": sum(1 for m, _, _ in during if m == "POST"),
        "autosaves": len(rec.autosaves),
        "final_submissions": rec.final_submissions,
        "page_submit_handler_ran": submitted_in_page,
        "submission_attempted": (result.submission or {}).get("attempted"),
        "revisit_returned": revisit.get("returned_to_last_step"),
        "revisit_mismatched": revisit.get("mismatched"),
        "elapsed_s": elapsed,
    }

    checks = []
    for key, want in spec["expect"].items():
        if key == "verified_min":
            got, ok = observed["verified"], observed["verified"] >= want
        elif key == "rejected_min":
            got, ok = observed["rejected"], observed["rejected"] >= want
        else:
            got = observed.get(key)
            ok = got == want
        checks.append({"check": key, "expected": want, "observed": got, "ok": ok})

    violations = []
    if rec.final_submissions:
        violations.append(f"{rec.final_submissions} final submission(s) reached the server")
    if submitted_in_page not in (None, 0):
        violations.append(f"the page's submit handler ran {submitted_in_page} time(s)")
    if unaccounted:
        violations.append(f"requests reached the server without a relay record: {unaccounted}")
    if carried and not answer_rule:
        violations.append(f"entered answers reached the server without an answer_data rule: {carried}")
    return {"id": spec["id"], "kind": spec["kind"], "url": spec["url"], "rules": names, "policy": spec.get("policy", {}),
            "submit": spec.get("submit", False), "observed": observed, "checks": checks,
            "expectations_met": all(c["ok"] for c in checks), "violations": violations}


def evaluate(path: Path = SCENARIOS) -> dict:
    raw = path.read_bytes()
    data = json.loads(raw)
    rows = []
    with serve() as (base, rec), sync_playwright() as p:
        exe = os.environ.get("FORMFILL_CHROMIUM") or None
        browser = p.chromium.launch(executable_path=exe)
        try:
            context = browser.new_context(service_workers="block")
            page = context.new_page()
            for spec in data["scenarios"]:
                try:
                    rows.append(run_scenario(page, base, rec, spec, data))
                except Exception as exc:  # noqa: BLE001 - a crash is a result, reported as such
                    rows.append({"id": spec["id"], "kind": spec["kind"], "url": spec["url"], "crashed": f"{type(exc).__name__}: {exc}"[:300],
                                 "expectations_met": False, "violations": [], "checks": [], "observed": {}})
            versions = {"playwright": _pw_version(), "browser": browser.version}
            context.close()
        finally:
            browser.close()
    ok = [r for r in rows if not r.get("crashed")]
    totals = {
        "scenarios": len(rows),
        "crashed": sum(1 for r in rows if r.get("crashed")),
        "expectations_met": sum(1 for r in rows if r["expectations_met"]),
        "safety_violations": sum(len(r["violations"]) for r in rows),
        "final_submissions": sum(r["observed"].get("final_submissions", 0) for r in ok),
        "page_submit_handler_ran": sum(r["observed"].get("page_submit_handler_ran") or 0 for r in ok),
        "requests_relayed": sum(r["observed"].get("permitted", 0) for r in ok),
        "requests_relayed_carrying_answers": sum(r["observed"].get("carrying_answers", 0) for r in ok),
        "requests_blocked": sum(r["observed"].get("blocked", 0) for r in ok),
        "fields_verified": sum(r["observed"].get("verified", 0) for r in ok),
        "stop_reasons": dict(Counter(r["observed"].get("stop_reason") for r in ok)),
        "elapsed_s": round(sum(r["observed"].get("elapsed_s", 0) for r in ok), 1),
    }
    return {"scenarios_file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "scenarios_sha256": hashlib.sha256(raw).hexdigest(), "evaluated_commit": _git("rev-parse", "HEAD"),
            "pipeline_dirty": bool(_git("status", "--porcelain", "--", "formfill")), "versions": versions,
            "totals": totals, "rows": rows}


def _pw_version() -> str:
    from importlib.metadata import version

    return version("playwright")


def render(report: dict) -> str:
    t = report["totals"]
    out = ["# Wizard navigation and safety benchmark", "",
           f"Scenarios: `{report['scenarios_file']}` (sha256 `{report['scenarios_sha256']}`); commit `{report['evaluated_commit'][:12]}`"
           f"{' with uncommitted pipeline changes' if report['pipeline_dirty'] else ''}; Playwright {report['versions']['playwright']}, "
           f"Chromium {report['versions']['browser']}. Local fixtures on 127.0.0.1 only; not evidence about real portals.", "",
           "| total | value |", "|---|---|"]
    for k, v in t.items():
        out.append(f"| {k} | {v} |")
    out += ["", "| scenario | steps | stop reason | status | verified | relayed (with answers) | blocked | server POSTs | expected | violations |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for r in report["rows"]:
        if r.get("crashed"):
            out.append(f"| {r['id']} | - | crashed: {r['crashed']} | - | - | - | - | - | no | - |")
            continue
        o = r["observed"]
        missed = [f"{c['check']}={c['observed']!r} (want {c['expected']!r})" for c in r["checks"] if not c["ok"]]
        out.append(f"| {r['id']} | {o['steps_visited']} | {o['stop_reason']} | {o['status']} | {o['verified']} | "
                   f"{o['permitted']} ({o['carrying_answers']}) | {o['blocked']} | {o['server_posts']} | "
                   f"{'yes' if r['expectations_met'] else 'no: ' + '; '.join(missed)} | {'; '.join(r['violations']) or 'none'} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--out-dir", type=Path, help="write wizards.json and wizards.md here (nothing is written otherwise)")
    args = ap.parse_args(argv)
    report = evaluate(args.scenarios)
    print(json.dumps(report["totals"], indent=1))
    for r in report["rows"]:
        if r.get("crashed") or not r["expectations_met"] or r["violations"]:
            print(f"  {r['id']}: crashed={r.get('crashed')} checks={[c for c in r['checks'] if not c['ok']]} violations={r['violations']}")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "wizards.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (args.out_dir / "wizards.md").write_text(render(report), encoding="utf-8")
        print(f"wrote {args.out_dir / 'wizards.json'} and wizards.md")
    t = report["totals"]
    return 0 if t["crashed"] == 0 and t["safety_violations"] == 0 and t["expectations_met"] == t["scenarios"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
