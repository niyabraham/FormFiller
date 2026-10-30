"""Real-world compatibility test harness: run FormFiller against public demo / template forms (never submitting) and score it.

    python tools/evaluate_realworld.py run   --out-dir output/realworld [--forms id,id] [--sources full,tricky]
    python tools/evaluate_realworld.py score --out-dir output/realworld [--forms id,id] [--sources full,tricky]

`run` visits each form in benchmarks/realworld/forms.json with each fictional source (forms.json "sources") and writes, per
form and source: result.json, audit_report.md, filled.png (FormFiller's own outputs), questions.json (question metadata ONLY:
no answers, so ground truth can be written blind), requests.json, console.json and run.json (the harness's own record).

`score` compares result.json with the hand-written ground truth in benchmarks/realworld/truth/<form>.<source>.json (written
from questions.json and the source file before the answers were looked at) and prints precision, coverage and the safety
checks, separately. Skipped or reviewed questions are never counted as correct answers.

Safety (this is a test, not a submission exercise):
* submit=True is never passed. FormFiller never presses a final-action button; the harness records every click and submit
  event the page sees and flags any final-action label.
* every run uses the multi-step network guard (DiscoveryPolicy), even on single-page forms, so nothing leaves the browser
  after the walk starts. On top of that the harness aborts every non-GET/HEAD request during the walk, records every request
  and whether it finished or failed, and flags any walk-phase request that completed or any write attempt.
* fictional data only; no accounts, no CAPTCHA handling, no cookie-banner clicking.
Requests made while the page loads, before the walk starts, are the page's own (analytics, ads, schema downloads) and are
reported as such; FormFiller does not control them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FORMS = ROOT / "benchmarks" / "realworld" / "forms.json"
TRUTH = ROOT / "benchmarks" / "realworld" / "truth"
FINAL_ACTION = re.compile(r"\b(submit|send|complete|finish|finali[sz]e|sign|certify|attest|agree|accept|pay|place order|apply)\b", re.I)

TRIPWIRE_JS = r"""
(() => {
  const log = (kind, data) => { try { console.log('__ff_' + kind + '__' + JSON.stringify(data)); } catch (e) {} };
  window.addEventListener('offline', () => log('offline', {}));  // FormFiller's guard puts the context offline when it engages
  document.addEventListener('submit', e => log('submit', {action: (e.target && e.target.action) || ''}), true);
  document.addEventListener('click', e => {
    const t = e.target && e.target.closest ? e.target.closest('button, a, input, [role=button], label') : null;
    if (!t) return;
    const attr = t.getAttribute('type');
    const tag = t.tagName.toLowerCase();
    // would this click activate a form's submission? (a <button> outside any form, or type=button, cannot)
    const submits = !!t.form && (attr === 'submit' || attr === 'image' || (tag === 'button' && attr === null));
    const text = (t.innerText || t.value || t.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    log('click', {tag, type: t.type || '', submits, text});
  }, true);
})();
"""


def load_forms(only: set[str] | None, mechanics: bool = False) -> tuple[dict, list[dict]]:
    """Mechanics forms (forms.json "mechanics": true) and the mechanics source are a separate evaluation: they never mix with the
    answer-matching forms and sources (benchmarks/realworld/mechanics/README.md)."""
    data = json.loads(FORMS.read_text(encoding="utf-8"))
    forms = [f for f in data["forms"] if (not only or f["id"] in only) and bool(f.get("mechanics")) == mechanics]
    if mechanics:
        data = {**data, "sources": {"mechanics": data["mechanics_source"]}}
    return data, forms


def short(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}" if p.scheme in ("http", "https") else url.split("?", 1)[0][:80]


def norm(s) -> str:
    return " ".join(str(s).replace("*", " ").casefold().split())


# ---- run ------------------------------------------------------------------------------------------------------------------------


def run_one(browser, form: dict, source_name: str, source: dict, out_root: Path) -> dict:
    from formfill.web.netpolicy import NetworkPolicy
    from formfill.web.pipeline import run_form
    from formfill.web.steps import DiscoveryPolicy

    out = out_root / form["id"] / source_name
    out.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(service_workers="block", viewport={"width": 1280, "height": 1000})
    ctx.add_init_script(TRIPWIRE_JS)
    st: dict = {"phase": "load", "reqs": {}, "console": [], "clicks": [], "submits": [], "page_errors": [], "dialogs": [], "harness_blocked": []}

    def on_request(req):
        st["reqs"][req] = {"phase": st["phase"], "method": req.method, "url": short(req.url), "host": urlsplit(req.url).netloc,
                           "type": req.resource_type, "outcome": "pending"}

    def on_finished(req):
        if req in st["reqs"]:
            st["reqs"][req]["outcome"] = "finished"

    def on_failed(req):
        if req in st["reqs"]:
            st["reqs"][req]["outcome"] = "failed"

    def on_console(msg):
        t = msg.text
        if t.startswith("__ff_click__"):
            st["clicks"].append(json.loads(t[len("__ff_click__"):]))
        elif t.startswith("__ff_offline__"):
            if st["phase"] == "prewalk":
                st["phase"] = "walk"
                st["guard_seen"] = True
        elif t.startswith("__ff_submit__"):
            st["submits"].append(json.loads(t[len("__ff_submit__"):]))
        elif msg.type in ("error", "warning"):
            st["console"].append({"type": msg.type, "text": t[:200], "phase": st["phase"]})

    def write_guard(route, request):  # the harness's own, stricter layer on top of FormFiller's guard
        if st["phase"] in ("prewalk", "walk") and request.method not in ("GET", "HEAD", "OPTIONS"):
            st["harness_blocked"].append({"method": request.method, "url": short(request.url)})
            return route.abort("blockedbyclient")
        return route.fallback()

    ctx.on("request", on_request)
    ctx.on("requestfinished", on_finished)
    ctx.on("requestfailed", on_failed)
    ctx.on("console", on_console)
    ctx.route("**/*", write_guard)
    rules = form.get("network_rules") or []

    def permitted(r: dict) -> bool:
        return any(r["method"] in ru.get("methods", ["GET"]) and r["host"] == urlsplit(ru["origin"]).netloc
                   and fnmatch(urlsplit(r["url"]).path, ru.get("path", "/*")) for ru in rules)

    page = ctx.new_page()
    page.on("pageerror", lambda e: st["page_errors"].append({"text": str(e)[:200], "phase": st["phase"]}))
    page.on("dialog", lambda d: (st["dialogs"].append({"type": d.type, "message": d.message[:80]}), d.dismiss()))

    row: dict = {"form": form["id"], "source": source_name, "url": form["url"], "crashed": None}
    t0 = time.perf_counter()
    result = None
    try:
        page.goto(form["url"], wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:  # noqa: BLE001 - busy pages never go idle; the walk has its own readiness wait
            pass
        page.wait_for_timeout(1500)
        if form.get("setup_js"):  # harness-side preparation only (e.g. remove a consent overlay); recorded in run.json
            page.evaluate(form["setup_js"])
            row["setup_js"] = form["setup_js"]
            page.wait_for_timeout(500)
        row["loaded_url"] = short(page.url)
        row["title"] = page.title()[:80]
        st["phase"] = "prewalk"  # run_form has started; FormFiller's guard engages a little later (the page then sees `offline`)
        result = run_form(page, source, policy=DiscoveryPolicy(**{"revisit_with_back": bool(form.get("back")), **form.get("policy", {})}), confirm_ms=1500,
                          readiness_timeout_ms=15000, out_dir=out,
                          network_policy=NetworkPolicy.from_dict({"rules": rules}) if rules else None)
    except Exception as exc:  # noqa: BLE001 - a crash is a result
        row["crashed"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        (out / "crash.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        st["phase"] = "after"
    if form.get("oracle_js") and result is not None:
        try:
            row["oracle"] = page.evaluate(form["oracle_js"])  # what the page itself shows, read independently of FormFiller
        except Exception as exc:  # noqa: BLE001
            row["oracle"] = f"oracle failed: {type(exc).__name__}"
    row["elapsed_s"] = round(time.perf_counter() - t0, 1)
    try:
        page.screenshot(path=str(out / "final_view.png"))
    except Exception:  # noqa: BLE001
        pass

    reqs = list(st["reqs"].values())
    walk = [r for r in reqs if r["phase"] == "walk"]
    pre = [r for r in reqs if r["phase"] == "prewalk"]
    row["guard_observed"] = bool(st.get("guard_seen"))
    row["requests"] = {
        "before_walk": sum(1 for r in reqs if r["phase"] == "load"),
        "before_guard_in_run": len(pre),  # run_form started, guard not yet engaged: documented as outside the guard (SECURITY_MODEL.md)
        "before_guard_completed": [{k: r[k] for k in ("method", "type", "url")} for r in pre if r["outcome"] == "finished"],
        "before_walk_hosts": dict(Counter(r["host"] for r in reqs if r["phase"] == "load").most_common(8)),
        "during_walk": len(walk),
        "during_walk_failed": sum(1 for r in walk if r["outcome"] == "failed"),
        "during_walk_completed": [r for r in walk if r["outcome"] == "finished" and not permitted(r)],
        "relayed_under_explicit_rules": [r for r in walk if r["outcome"] == "finished" and permitted(r)],
        "during_walk_writes": [r for r in walk if r["method"] not in ("GET", "HEAD", "OPTIONS")],
        "harness_blocked_writes": st["harness_blocked"],
    }
    final_clicks = [c for c in st["clicks"] if FINAL_ACTION.search(c.get("text", "")) or c.get("submits")]
    row["clicks"] = {"total": len(st["clicks"]), "texts": [c["text"] for c in st["clicks"] if c.get("text")][:30], "final_action_like": final_clicks}
    row["submit_events"] = len(st["submits"])
    row["dialogs"] = st["dialogs"]
    row["console_errors"] = [c for c in st["console"] if c["type"] == "error"][:10]
    row["page_errors"] = st["page_errors"][:10]
    row["violations"] = []
    if row["submit_events"]:
        row["violations"].append(f"{row['submit_events']} submit event(s) reached the page")
    if final_clicks:
        row["violations"].append(f"click(s) on final-action-like controls: {final_clicks}")
    if row["requests"]["during_walk_completed"]:
        row["violations"].append(f"{len(row['requests']['during_walk_completed'])} request(s) completed during the walk")
    # critical = something may have got out or been pressed: the batch stops. A blocked write attempt is recorded but is not critical.
    row["critical"] = list(row["violations"])
    if result is not None and not row["guard_observed"]:
        row["violations"].append("the page never saw the guard engage (no offline event): the walk cannot be treated as guarded")
        row["critical"].append(row["violations"][-1])
    if row["requests"]["during_walk_writes"] or st["harness_blocked"]:
        row["violations"].append("write request(s) attempted during the walk (blocked)")

    if result is not None:
        d = result.to_dict()
        nav = d.get("navigation") or {}
        row.update({"status": d["status"], "stop_reason": nav.get("stop_reason"), "completion": nav.get("completion"),
                    "steps_visited": nav.get("steps_visited"), "network_mode": nav.get("network_mode"),
                    "formfill_blocked_requests": [{"method": b.get("method"), "url": b.get("url"), "type": b.get("resource_type"),
                                                   "reason": b.get("reason")} for b in nav.get("blocked_requests") or []][:20],
                    "notes": [n.get("kind") for n in nav.get("notes") or []], "warnings": d.get("warnings", [])[:6],
                    "unsupported": [{"kind": u.get("kind"), "label": (u.get("label") or "")[:50], "required": u.get("required")} for u in d.get("unsupported", [])],
                    "revisit": nav.get("revisit"), "field_states": dict(Counter(i["state"] for i in d["items"]))})
        (out / "questions.json").write_text(json.dumps({
            "form": form["id"], "source": source_name,
            "questions": [{"question": i["plan"]["question"], "type": i["plan"]["field_type"], "required": i["plan"]["required"],
                           "step": i.get("step"), "section": i.get("section")} for i in d["items"]],
            "unsupported": row["unsupported"], "steps": [{"step": s.get("step"), "heading": s.get("heading")} for s in nav.get("steps", [])]},
            indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "requests.json").write_text(json.dumps(reqs, indent=1), encoding="utf-8")
    (out / "console.json").write_text(json.dumps({"console": st["console"], "page_errors": st["page_errors"]}, indent=1), encoding="utf-8")
    (out / "run.json").write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
    ctx.close()  # also ends the network guard
    return row


def cmd_run(args) -> int:
    from playwright.sync_api import sync_playwright

    data, forms = load_forms(set(args.forms.split(",")) if args.forms else None, args.mechanics)
    names = args.sources.split(",") if args.sources else list(data["sources"])
    sources = {n: json.loads((ROOT / data["sources"][n]).read_text(encoding="utf-8")) for n in names}
    out_root = Path(args.out_dir)
    from importlib.metadata import version

    with sync_playwright() as p:
        browser = p.chromium.launch()
        print(f"Playwright {version('playwright')}, Chromium {browser.version}; {len(forms)} form(s) x {len(sources)} source(s)")
        bad = 0
        for form in forms:
            for name, src in sources.items():
                row = run_one(browser, form, name, src, out_root)
                bad += bool(row["violations"]) + bool(row["crashed"])
                if row["critical"]:
                    print(f"  CRITICAL on {form['id']}/{name}: {row['critical']} - stopping the batch")
                    browser.close()
                    return 2
                print(f"  {form['id']:<22} {name:<7} {row.get('status', '-'):<13} steps={row.get('steps_visited')} stop={row.get('stop_reason')} "
                      f"{'CRASH ' + row['crashed'] if row['crashed'] else ''} {'VIOLATIONS ' + str(row['violations']) if row['violations'] else ''}")
        browser.close()
    return 1 if bad else 0


# ---- score ----------------------------------------------------------------------------------------------------------------------


def find_truth(entries: list[dict], label: str) -> dict | None:
    n = norm(label)
    for e in entries:
        if e.get("regex"):
            if re.search(e["match"], label, re.I):
                return e
        elif norm(e["match"]) == n:
            return e
    return None


def same(a, b) -> bool:
    return norm(a) == norm(b)


def score_one(out_root: Path, form_id: str, source: str) -> dict | None:
    rj, tj = out_root / form_id / source / "result.json", TRUTH / f"{form_id}.{source}.json"
    if not rj.exists():
        return None
    if not tj.exists():
        return {"form": form_id, "source": source, "error": f"no ground truth file {tj.name}"}
    result, truth = json.loads(rj.read_text(encoding="utf-8")), json.loads(tj.read_text(encoding="utf-8"))
    entries = truth["questions"]
    c = Counter()
    detail = []
    for i in result["items"]:
        p = i["plan"]
        t = find_truth(entries, p["question"])
        if t is None:
            c["unlabelled"] += 1
            detail.append({"question": p["question"], "outcome": "UNLABELLED"})
            continue
        expect = t["expect"]
        chrome = t.get("chrome", False)
        if not chrome:
            c["questions"] += 1
            c["expected_answerable"] += expect == "answer"
        else:
            c["page_chrome"] += 1
        entered = p["status"] == "ANSWER" and i["filled"]
        held = i.get("observed")
        if entered:
            c["entered_chrome" if chrome else "entered"] += 1
            if expect == "answer" and any(same(held, a) or same(p["answer"], a) for a in t["accept"]):
                outcome = "CORRECT"
                c["correct"] += 1
                c["correct_verified"] += bool(i["verified"])
            elif expect == "answer":
                outcome = "WRONG_VALUE"
                c["wrong_value"] += 1
            else:
                outcome = "UNSAFE (expected review)"
                c["unsafe"] += 1
        elif p["status"] == "ANSWER":
            outcome = "ANSWER_NOT_ENTERED"
            c["answer_not_entered"] += 1
            c["missed"] += expect == "answer"
        else:
            if expect == "answer":
                outcome = "MISSED (review, answer expected)"
                c["missed"] += 1
                c["proposal_right"] += bool(p.get("proposed_answer") is not None and any(same(p["proposed_answer"], a) for a in t["accept"]))
            else:
                outcome = "CORRECT_ABSTENTION"
                c["correct_abstentions"] += 1
        detail.append({"question": p["question"], "expect": expect, "entered": entered, "held": held, "outcome": outcome,
                       "reason": (p.get("reason") or "")[:90]})
    entered_n = c["entered"] + c["entered_chrome"]
    run = json.loads((out_root / form_id / source / "run.json").read_text(encoding="utf-8"))
    return {"form": form_id, "source": source, "status": result["status"], "steps": run.get("steps_visited"), "stop": run.get("stop_reason"),
            "questions": c["questions"], "expected_answerable": c["expected_answerable"], "entered": entered_n, "correct": c["correct"],
            "wrong_value": c["wrong_value"], "unsafe": c["unsafe"], "missed": c["missed"],
            "correct_abstentions": c["correct_abstentions"], "answer_not_entered": c["answer_not_entered"], "page_chrome": c["page_chrome"],
            "unsupported": len(result.get("unsupported", [])), "unlabelled": c["unlabelled"], "verified_of_correct": c["correct_verified"],
            "precision": (c["correct"] / entered_n) if entered_n else None, "coverage": (c["correct"] / c["expected_answerable"]) if c["expected_answerable"] else None,
            "violations": run["violations"], "detail": detail}


def pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def cmd_score(args) -> int:
    data, forms = load_forms(set(args.forms.split(",")) if args.forms else None, args.mechanics)
    names = args.sources.split(",") if args.sources else list(data["sources"])
    out_root = Path(args.out_dir)
    rows = [r for f in forms for n in names if (r := score_one(out_root, f["id"], n))]
    print(f"{'form':<22}{'src':<7}{'status':<13}{'q':>3}{'ans?':>5}{'ent':>4}{'ok':>4}{'bad':>4}{'unsafe':>7}{'miss':>5}{'abst':>5}{'unsup':>6}  precision  coverage  violations")
    tot = Counter()
    for r in rows:
        if "error" in r:
            print(f"{r['form']:<22}{r['source']:<7}{r['error']}")
            continue
        print(f"{r['form']:<22}{r['source']:<7}{r['status']:<13}{r['questions']:>3}{r['expected_answerable']:>5}{r['entered']:>4}{r['correct']:>4}"
              f"{r['wrong_value']:>4}{r['unsafe']:>7}{r['missed']:>5}{r['correct_abstentions']:>5}{r['unsupported']:>6}  {pct(r['precision']):>9}  {pct(r['coverage']):>8}  "
              f"{len(r['violations'])}{'  UNLABELLED=' + str(r['unlabelled']) if r['unlabelled'] else ''}")
        for k in ("questions", "expected_answerable", "entered", "correct", "wrong_value", "unsafe", "missed", "correct_abstentions", "unsupported", "unlabelled"):
            tot[k] += r[k]
    if tot["questions"]:
        print(f"{'TOTAL':<29}{'':<13}{tot['questions']:>3}{tot['expected_answerable']:>5}{tot['entered']:>4}{tot['correct']:>4}{tot['wrong_value']:>4}{tot['unsafe']:>7}"
              f"{tot['missed']:>5}{tot['correct_abstentions']:>5}{tot['unsupported']:>6}  "
              f"{pct(tot['correct'] / tot['entered'] if tot['entered'] else None):>9}  {pct(tot['correct'] / tot['expected_answerable'] if tot['expected_answerable'] else None):>8}")
    (out_root / "scores.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "score"):
        sp = sub.add_parser(name)
        sp.add_argument("--out-dir", required=True)
        sp.add_argument("--forms")
        sp.add_argument("--sources")
        sp.add_argument("--mechanics", action="store_true", help="the mechanics-only evaluation (separate forms and source; never mixed with matching metrics)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return cmd_run(args) if args.cmd == "run" else cmd_score(args)


if __name__ == "__main__":
    raise SystemExit(main())
