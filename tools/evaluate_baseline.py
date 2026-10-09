"""Evaluate the deterministic web pipeline against the Phase 2 RFI benchmark.

    python tools/evaluate_baseline.py            # run everything, print summary, write results/
    python tools/evaluate_baseline.py --case c05_boolean

Reads only the generated benchmark files (form.html / source.json / truth.json).
Correctness is judged against the ground truth and against what the *page
actually holds afterwards* (the harness reads the DOM itself; it does not
trust the pipeline's own read-back).

Writes benchmarks/rfi/results/{baseline.json, failures.md}. Nothing is
committed or sent anywhere; no third-party site is contacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formfill.web.discover import discover
from formfill.web.pipeline import run_form
from formfill.web.plan import MIN_CONFIDENCE, MIN_MARGIN
from formfill.web.retrieve import index_source, retrieve
from formfill.web.understand import (
    clean_question_text,
    understand_control,
)
from formfill.web.validate import validate_answer

BENCH = ROOT / "benchmarks" / "rfi"
CLASSES = ["form discovery problem", "question understanding problem", "retrieval problem", "ambiguity problem",
           "validation problem", "browser execution problem", "submission/verification problem"]

_DOM_JS = """
(name) => {
  const els = [...document.querySelectorAll('[name="' + name + '"]')];
  if (!els.length) return {found: false};
  const e = els[0], t = (e.type || '').toLowerCase(), tag = e.tagName.toLowerCase();
  let v;
  if (t === 'radio') { const c = els.find(x => x.checked); v = c ? c.value : null; }
  else if (t === 'checkbox') v = els.length > 1 ? els.filter(x => x.checked).map(x => x.value) : e.checked;
  else if (tag === 'select' && e.multiple) v = [...e.selectedOptions].map(o => o.value);
  else v = e.value;
  return {found: true, value: v};
}
"""


# ----------------------------------------------------------------- helpers
def norm(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, list):
        return sorted(str(norm(x)) for x in v)
    if v is None:
        return None
    s = str(v).strip()
    try:
        f = float(s.replace(",", "")) if s and s.lower() not in ("nan", "inf") else None
    except ValueError:
        f = None
    if f is not None:
        return str(int(f)) if f.is_integer() else str(f)
    return s


def eq(a: Any, b: Any) -> bool:
    return norm(a) == norm(b)


def get_path(data: Any, path: str) -> Any:
    cur = data
    for seg in path.split("."):
        cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
    return cur


def label_key(s: str) -> str:
    return " ".join(clean_question_text(s).lower().split())


# ------------------------------------------------------------- per-question
def retrieval_class(q: dict, cands: list, source: Any) -> str:
    """Mutually exclusive outcome of retrieval alone, judged against truth."""
    if not cands:
        return "none"
    top = cands[0]
    if len(cands) > 1 and top.score - cands[1].score < MIN_MARGIN and str(top.value).strip().lower() != str(cands[1].value).strip().lower():
        return "ambiguous"
    if q["expect"] == "ANSWER" and q["source"]:
        try:
            expected_val = get_path(source, q["source"])
        except (KeyError, IndexError, ValueError):
            expected_val = None
        right = top.path == q["source"] or (expected_val is not None and str(top.value) == str(expected_val))
        if not right:
            return "incorrect_top"
        return "weak_correct" if top.score < MIN_CONFIDENCE else "correct"
    return "spurious"  # a candidate exists although no answer is expected


def evaluate_question(q: dict, ctx: dict) -> dict:
    page, source, leaves = ctx["page"], ctx["source"], ctx["leaves"]
    ctrl0, ctrl = ctx["initial"].get(q["control"]), ctx["final"].get(q["control"])
    item = ctx["items"].get(ctrl.control_id) if ctrl else None
    rec: dict[str, Any] = {
        "case": ctx["case"], "control": q["control"], "question": q["question"], "expect": q["expect"],
        "expected_answer": q["answer"], "expected_source": q["source"], "tags": q["tags"], "trap": q["trap"],
        "note": q["note"], "when": q["when"], "source_style": ctx["style"],
        "discovered": ctrl is not None, "kind_ok": None, "label_ok": None, "discovered_label": ctrl.label if ctrl else None,
        "initially_visible": ctrl0.visible if ctrl0 else None,
    }
    if ctrl:
        rec["kind_ok"] = ctrl.kind == q["kind"]
        rec["label_ok"] = label_key(ctrl.label) == label_key(q["question"])
        rec["discovered_kind"] = ctrl.kind
        rec["options_changed"] = ctrl0 is not None and [o.value for o in ctrl0.options] != [o.value for o in ctrl.options]
        rec["disabled_at_discovery"] = bool(ctrl0 and ctrl0.disabled)

    # --- retrieval (pure function, same objects the pipeline uses)
    cands = []
    if ctrl and q["expect"] != "ABSENT":
        question = understand_control(ctrl)
        cands = retrieve(question, leaves)
        top_leaf = next((lf for lf in leaves if cands and lf.path == cands[0].path), None)
        rec["unmatched_tokens"] = (sorted(set(question.concept_tokens) - top_leaf.leaf_tokens - top_leaf.parent_tokens)
                                   if top_leaf else [])
        rec["retrieval"] = retrieval_class(q, cands, source)
        rec["top"] = {"path": cands[0].path, "value": cands[0].value, "score": cands[0].score} if cands else None
        rec["runner_up"] = {"path": cands[1].path, "score": cands[1].score} if len(cands) > 1 else None
    else:
        rec["retrieval"] = "n/a"

    # --- decision
    plan = item.plan if item else None
    rec["decision"] = plan.status if plan else "NOT_ASKED"
    rec["answer"] = plan.answer if plan else None
    rec["chosen_source"] = plan.source if plan else None
    rec["confidence"] = plan.confidence if plan else None
    rec["reason"] = plan.reason if plan else None
    rec["alternatives"] = plan.alternatives if plan else []

    # --- validation (direct call on the *expected* source value)
    rec["validation"] = "n/a"
    if ctrl and q["expect"] == "ANSWER" and q["source"] and not q["trap"]:
        v = validate_answer(get_path(source, q["source"]), ctrl)
        rec["validation"] = ("rejected_valid" if not v.ok else "accepted_correct" if eq(v.value, q["answer"])
                             else "accepted_wrong_value")
        rec["validation_detail"] = v.reason
    elif ctrl and q["invalid_source"]:
        v = validate_answer(get_path(source, q["invalid_source"]), ctrl)
        rec["validation"] = "accepted_invalid" if v.ok else "rejected_invalid"
        rec["validation_detail"] = v.reason

    # --- browser execution (only when the pipeline attempted a fill)
    rec["browser"] = "n/a"
    rec["dom"] = None
    if ctrl and ctx["read_dom"]:
        d = page.evaluate(_DOM_JS, q["control"])
        rec["dom"] = d.get("value") if d.get("found") else None
    if item and plan.status == "ANSWER":
        dom_ok = eq(plan.answer, rec["dom"])
        if not item.filled:
            rec["browser"] = "fill_failure"
        elif not dom_ok:
            rec["browser"] = "dom_differs_from_plan"
        elif item.verified is False:
            rec["browser"] = "verification_false_alarm"
        else:
            rec["browser"] = "ok"
        if not dom_ok and item.verified:
            rec["browser"] = "verification_missed_failure"
        rec["pipeline_verified"] = item.verified

    # --- planning outcome (judged on the end state of the form where we can read it)
    held = rec["dom"] if ctx["read_dom"] and rec["decision"] == "ANSWER" else rec["answer"]
    if q["expect"] == "ANSWER":
        if rec["decision"] == "ANSWER":
            if item is not None and not item.filled:
                rec["outcome"] = "fill_failed"  # a recorded failure, not a wrong value in the form
            else:
                rec["outcome"] = "correct_answer" if eq(held, q["answer"]) else "wrong_answer"
        elif rec["decision"] == "REVIEW":
            rec["outcome"] = "missed_answer"
        else:
            rec["outcome"] = "not_asked"
    elif q["expect"] == "REVIEW":
        rec["outcome"] = {"REVIEW": "correct_review", "ANSWER": "unsafe_answer"}.get(rec["decision"], "not_surfaced")
    else:  # ABSENT
        rec["outcome"] = "correctly_unasked" if rec["decision"] == "NOT_ASKED" else "asked_hidden_control"
    return rec


def classify(rec: dict, all_recs: dict[str, dict]) -> tuple[str | None, str]:
    """Failure class by decision procedure over stage evidence (see PHASE2_EVALUATION.md §4)."""
    out = rec["outcome"]
    if out == "correct_answer" and rec["browser"] in ("dom_differs_from_plan", "verification_false_alarm"):
        return "submission/verification problem", "form holds the expected value but the pipeline's own check disagreed (run reported FAILED)"
    if out in ("correct_answer", "correct_review", "correctly_unasked"):
        return None, ""
    if rec["expect"] == "ABSENT":
        return "browser execution problem", "hidden control was asked/filled"
    if not rec["discovered"]:
        return "form discovery problem", "control not found by the extractor"
    if rec["kind_ok"] is False:
        return "form discovery problem", f"control classified as {rec['discovered_kind']!r}"
    if rec["label_ok"] is False:
        return "form discovery problem", f"label read as {rec['discovered_label']!r}"
    if rec["expect"] == "ANSWER" and rec.get("options_changed"):
        return "form discovery problem", "options changed after the first discovery pass (late-loading list); not re-read"
    if rec["expect"] == "ANSWER" and rec.get("disabled_at_discovery") and rec["decision"] == "REVIEW":
        return "browser execution problem", "control was disabled at discovery and enabled by a later answer; never revisited"
    if rec["decision"] == "NOT_ASKED":
        if rec["when"]:
            trig = all_recs.get(f"{rec['case']}:{rec['when'][0]}")
            if trig and trig["outcome"] != "correct_answer":
                cls, why = classify(trig, all_recs)
                return cls, f"cascade: trigger {trig['control']!r} not answered ({why})"
        if rec["initially_visible"] is False:
            return "form discovery problem", "control hidden in a wizard step; pipeline never navigates"
    if rec["browser"] in ("fill_failure", "dom_differs_from_plan") or out == "fill_failed":
        return "browser execution problem", rec["browser"]
    if rec["browser"] in ("verification_false_alarm", "verification_missed_failure"):
        return "submission/verification problem", rec["browser"]
    if rec["trap"]:
        return "question understanding problem", f"trap: {rec['trap']}"
    if rec["validation"] in ("accepted_invalid",) or (rec["validation"] in ("rejected_valid", "accepted_wrong_value")
                                                      and rec["retrieval"] == "correct"):
        return "validation problem", rec.get("validation_detail") or rec["validation"]
    if (rec["retrieval"] == "ambiguous" and (rec.get("top") or {}).get("score", 0) >= MIN_CONFIDENCE) or (
            rec["reason"] or "").startswith("ambiguous") or (
            out == "unsafe_answer" and "ambiguous" in rec["tags"]):
        return "ambiguity problem", rec["reason"] or "near-tie between candidates"
    if out == "unsafe_answer" and rec.get("unmatched_tokens"):
        return "retrieval problem", (f"chose {rec['chosen_source']!r} although question words {rec['unmatched_tokens']} "
                                     "are not explained by that key or its parents")
    return "retrieval problem", rec["reason"] or f"retrieval={rec['retrieval']}"


# ------------------------------------------------------------------- driver
def make_ctx(page, case_id: str, style: str, source: Any, result, initial, final, read_dom: bool) -> dict:
    return {"page": page, "case": case_id, "style": style, "source": source, "leaves": index_source(source),
            "items": {i.plan.question_id: i for i in result.items}, "initial": initial, "final": final, "read_dom": read_dom}


def by_name(schema) -> dict:
    out: dict = {}
    for c in schema.controls:
        if c.name and c.name not in out:
            out[c.name] = c
    return out


def run_case(browser, entry: dict) -> tuple[list[dict], dict | None]:
    d = BENCH / entry["id"]
    truth = json.loads((d / "truth.json").read_text())
    source = json.loads((d / "source.json").read_text())
    page = browser.new_context().new_page()
    page.set_default_timeout(4000)
    page.goto((d / "form.html").as_uri())
    initial = by_name(discover(page))
    sub = entry["kind"] == "submission"
    result = run_form(page, source, submit=sub, success_text=entry.get("success_text"), timeout_ms=4000)
    final = by_name(discover(page)) if not sub else initial
    ctx = make_ctx(page, entry["id"], entry["source_style"], source, result, initial, final, read_dom=not sub)
    recs = [evaluate_question(q, ctx) for q in truth["questions"]]
    sub_rec = None
    if sub:
        got = result.submission.get("outcome")
        sub_rec = {"case": entry["id"], "description": entry["description"], "expected_outcome": entry["expected_outcome"],
                   "outcome": got, "expected_status": entry["expected_status"], "status": result.status,
                   "ok": got == entry["expected_outcome"] and result.status == entry["expected_status"],
                   "note": entry.get("note", "")}
    page.context.close()
    return recs, sub_rec


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


METRIC_DEFINITIONS = {
    "scored_questions": "N = every question whose truth is ANSWER or REVIEW (ABSENT controls, which must stay unasked, are excluded). "
                        "Each is placed in exactly one confusion cell.",
    "auto_answered": "A = questions where the pipeline decided ANSWER (includes the ones it then failed to fill).",
    "correct_answers": "C = ANSWER decided, expected ANSWER, and the form (read from the DOM) holds the expected value.",
    "unsafe_answers": "U = ANSWER decided and either the value is wrong where ANSWER was expected, or ANSWER was decided where REVIEW was expected. "
                      "A fill failure is NOT unsafe (no wrong value reaches the form) but is NOT correct either.",
    "precision": "C / A",
    "coverage": "A / N",
    "review_rate": "R / N, R = questions the pipeline sent to REVIEW",
    "not_surfaced_rate": "S / N, S = questions never asked (not discovered, or behind an unrevealed step)",
    "answerable_recall": "C / (expected-ANSWER count)",
    "identity": "A = C + U + F (fill_failed);  N = A + R + S",
}


def confusion(asked: list[dict]) -> dict:
    """Exhaustive partition of the scored questions. Every question lands in exactly one cell."""
    cells = {
        "expected_ANSWER__predicted_ANSWER__correct": ("correct_answer",),
        "expected_ANSWER__predicted_ANSWER__incorrect_value": ("wrong_answer",),
        "expected_ANSWER__predicted_ANSWER__fill_failed": ("fill_failed",),
        "expected_ANSWER__predicted_REVIEW": ("missed_answer",),
        "expected_ANSWER__not_asked": ("not_asked",),
        "expected_REVIEW__predicted_REVIEW": ("correct_review",),
        "expected_REVIEW__predicted_ANSWER": ("unsafe_answer",),
        "expected_REVIEW__not_asked": ("not_surfaced",),
    }
    out = {name: sum(r["outcome"] in outs for r in asked) for name, outs in cells.items()}
    assert sum(out.values()) == len(asked), "confusion matrix does not partition the scored questions"
    return out


def summarise(recs: list[dict]) -> dict:
    asked = [r for r in recs if r["expect"] != "ABSENT"]
    n = len(asked)
    answered = [r for r in asked if r["decision"] == "ANSWER"]
    correct = [r for r in answered if r["outcome"] == "correct_answer"]
    unsafe = [r for r in answered if r["outcome"] in ("wrong_answer", "unsafe_answer")]
    failed = [r for r in answered if r["outcome"] == "fill_failed"]
    reviewed = [r for r in asked if r["decision"] == "REVIEW"]
    surfaced_not = [r for r in asked if r["decision"] == "NOT_ASKED"]
    expect_ans = [r for r in asked if r["expect"] == "ANSWER"]
    assert len(answered) == len(correct) + len(unsafe) + len(failed), "answered != correct + unsafe + fill_failed"
    assert n == len(answered) + len(reviewed) + len(surfaced_not), "N != answered + review + not surfaced"
    return {
        "questions": n, "expected_answer": len(expect_ans), "expected_review": n - len(expect_ans),
        "auto_answered": len(answered), "correct_answers": len(correct), "unsafe_answers": len(unsafe),
        "fill_failed": len(failed), "review": len(reviewed), "not_surfaced": len(surfaced_not),
        "precision_pct": pct(len(correct), len(answered)), "coverage_pct": pct(len(answered), n),
        "review_rate_pct": pct(len(reviewed), n),
        "not_surfaced_pct": pct(len(surfaced_not), n),
        "answerable_recall_pct": pct(len(correct), len(expect_ans)),
        "correct_review": sum(r["outcome"] == "correct_review" for r in asked),
        "missed_answers": sum(r["outcome"] == "missed_answer" for r in asked),
        "wrong_answer_where_answer_expected": sum(r["outcome"] == "wrong_answer" for r in asked),
        "unsafe_answer_where_review_expected": sum(r["outcome"] == "unsafe_answer" for r in asked),
        "verification_false_alarms": sum(r["browser"] in ("dom_differs_from_plan", "verification_false_alarm") and r["outcome"] == "correct_answer" for r in asked),
        "confusion": confusion(asked),
    }


def stage_metrics(recs: list[dict]) -> dict:
    exp = [r for r in recs if r["expect"] != "ABSENT"]
    disc = {"expected_controls": len(exp), "found": sum(r["discovered"] for r in exp),
            "missed": sum(not r["discovered"] for r in exp),
            "wrong_kind": sum(r["discovered"] and r["kind_ok"] is False for r in exp),
            "wrong_label": sum(r["discovered"] and r["label_ok"] is False for r in exp)}
    ret = Counter(r["retrieval"] for r in exp if r["retrieval"] != "n/a")
    plan = Counter(r["outcome"] for r in recs)
    val = Counter(r["validation"] for r in recs if r["validation"] != "n/a")
    br = Counter(r["browser"] for r in recs if r["browser"] != "n/a")
    return {"discovery": disc, "retrieval": dict(ret), "planning": dict(plan), "validation": dict(val), "browser": dict(br)}


def breakdown(recs: list[dict], keyfn) -> dict:
    groups: dict = defaultdict(list)
    for r in recs:
        if r["expect"] == "ABSENT":
            continue
        for k in keyfn(r):
            groups[k].append(r)
    return {k: summarise(v) for k, v in sorted(groups.items())}


# --------------------------------------------------------- failure write-up
def future_solution(r: dict, cls: str) -> str:
    t = set(r["tags"])
    if cls == "form discovery problem":
        if "custom_widget" in t and "shadow_dom" in t:
            return "Pierce open shadow roots in the extractor (Playwright CSS already pierces open shadow DOM)."
        if "custom_widget" in t:
            return "Discover ARIA-role widgets (radio/combobox/switch/textbox) and add a per-widget driver; verify by reading aria-checked/text."
        if "file_upload" in t:
            return "Discover file inputs and surface them as REVIEW items (never auto-attach)."
        if "async_options" in t:
            return "Wait for network/DOM idle and re-read options before validating a choice control; re-discover choice controls just before planning."
        if r["initially_visible"] is False or "multistep" in t:
            return "Wizard navigation: when all visible questions are resolved, click Next/Continue and re-discover (deterministic)."
        return "Label resolution fallbacks: nearest preceding text / table header cell / aria snapshot name; flag low-confidence labels."
    if cls == "question understanding problem":
        return "Do not drop negating/modal words ('optional', 'not', 'without', 'disable'); detect polarity and send to REVIEW, or add LLM question understanding."
    if cls == "validation problem":
        return "Deterministic option-mapping layer (value->label normalisation, numeric bands, list->count) before any model; ISO-only dates are a policy choice."
    if cls == "ambiguity problem":
        return "Graded section/parent-path scoring and explicit subject scoping; keep REVIEW when evidence is genuinely tied."
    if cls == "browser execution problem":
        if "readonly_datepicker" in t:
            return "Per-widget driver: open the picker and click the date; detect readonly inputs before attempting fill."
        if "enabled_later" in t or r.get("disabled_at_discovery"):
            return "Re-check disabled controls after each fill round (state changes), instead of freezing the plan at first sight."
        return "Inspect the fill/read-back path for this control type."
    if cls == "submission/verification problem":
        return "Compare read-back through the control's own normalisation (masks, trimming); treat 'page normalised my value' differently from 'fill lost my value'."
    if r["outcome"] == "unsafe_answer" or r["outcome"] == "wrong_answer":
        return "Require every content token of the question to be explained (coverage), not F1 alone; penalise unmatched modifiers; REVIEW otherwise."
    if t & {"acronym_in_parens", "number_word"}:
        return "Tokenisation: keep parenthetical acronyms; normalise number words/digits."
    if t & {"bool_in_parent", "list_by_value"}:
        return "Structure-aware retrieval: treat generic leaf names (exists/enabled/frequency) as inheriting meaning from the parent path; index list items by discriminator value."
    if t & {"morphology", "spelling", "tokenisation", "synonym", "paraphrase"}:
        return "Lemmatisation + larger curated synonym table first; embeddings only for what remains."
    ret = r.get("retrieval")
    if ret == "weak_correct":
        return ("The correct candidate was already ranked first but under-scored: lexical normalisation (lemmas, derived forms, "
                "spelling variants, parenthetical acronyms) and score calibration. No model needed to reach the threshold.")
    if ret == "incorrect_top":
        return "Generic words ('data', 'last', 'access') outrank specific ones: weight tokens by specificity across the source keys; use path structure."
    if ret == "ambiguous":
        return "Break near-ties deterministically first (type compatibility, graded section/parent evidence); REVIEW only if still tied."
    if ret == "none":
        return ("No lexical overlap at all: add synonym/abbreviation entries; whatever remains after that is the genuinely semantic "
                "residual (candidate for embeddings/LLM selection).")
    return "Inspect: retrieval was correct but the item still failed downstream."


def failure_markdown(failures: list[dict], run: dict, accounting: dict | None = None) -> str:
    out = ["# Failure cards (generated by tools/evaluate_baseline.py)\n",
           f"- evaluated commit: `{run['evaluated_commit']}` (pipeline_dirty={run['pipeline_dirty']})",
           f"- benchmark: v{run['benchmark_version']} ({run['benchmark_split']} split, digest `{run['benchmark_digest']}`)",
           f"- thresholds: MIN_CONFIDENCE={run['thresholds']['MIN_CONFIDENCE']}, MIN_MARGIN={run['thresholds']['MIN_MARGIN']}",
           f"- reproduce: `{run['reproduction_command']}`",
           "- metric definitions: see `baseline.json` -> `run.metric_definitions`"]
    if accounting:
        out.append(f"- {accounting['failure_cards']} cards = {accounting['unsuccessful_scored_outcomes']} unsuccessful scored outcomes "
                   f"+ {accounting['correct_outcomes_flagged_as_failure']} correct answer whose verification disagreed "
                   f"({', '.join(accounting['flagged_controls'])}); see `baseline.json` -> `failure_accounting`\n")
    by_cls: dict = defaultdict(list)
    for f in failures:
        by_cls[f["failure_class"]].append(f)
    for cls in CLASSES:
        rows = by_cls.get(cls, [])
        if not rows:
            continue
        out.append(f"\n## {cls} ({len(rows)})\n")
        for f in rows:
            top = f.get("top")
            out.append(
                "```\n"
                f"FORM QUESTION:   [{f['case']}] {f['question']}\n"
                f"JSON:            expected source={f['expected_source']!r}; top candidate="
                f"{(top['path'] + ' = ' + repr(top['value']) + ' (score ' + str(top['score']) + ')') if top else 'none'}\n"
                f"CURRENT DECISION: {f['decision']}"
                + (f" -> {f['answer']!r} from {f['chosen_source']}" if f["decision"] == "ANSWER" else "")
                + (f" ({f['reason']})" if f["reason"] else "") + "\n"
                f"EXPECTED:        {'REVIEW' if f['expect'] == 'REVIEW' else repr(f['expected_answer'])}"
                f"  [{f['expect']}]\n"
                f"WHY IT FAILED:   {f['why']}\n"
                f"FUTURE SOLUTION: {f['future']}\n"
                "```\n")
    return "\n".join(out)


REPRO_COMMAND = "python tools/build_benchmark.py && python tools/evaluate_baseline.py"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - metadata is best effort
        return ""


def benchmark_digest() -> str:
    """Content hash of every benchmark input, so a result can be tied to the exact fixtures it ran on."""
    h = hashlib.sha256()
    for f in sorted(BENCH.glob("*/*")):
        if f.name in ("form.html", "source.json", "truth.json", "thanks.html"):
            h.update(f.relative_to(BENCH).as_posix().encode() + f.read_bytes())
    return h.hexdigest()[:16]


def run_metadata(manifest_doc: dict) -> dict:
    """Provenance of a run. `pipeline_dirty` is true when formfill/ differs from the recorded commit."""
    return {
        "evaluated_commit": _git("rev-parse", "HEAD"),
        "pipeline_dirty": bool(_git("status", "--porcelain", "--", "formfill")),
        "benchmark_version": manifest_doc.get("benchmark_version"),
        "benchmark_split": manifest_doc.get("split"),
        "benchmark_digest": benchmark_digest(),
        "thresholds": {"MIN_CONFIDENCE": MIN_CONFIDENCE, "MIN_MARGIN": MIN_MARGIN},
        "metric_definitions": METRIC_DEFINITIONS,
        "reproduction_command": REPRO_COMMAND,
    }


def failure_accounting(all_recs: list[dict], failures: list[dict]) -> dict:
    """Why the failure-card count can differ from the number of unsuccessful scored outcomes."""
    scored = [r for r in all_recs if r["expect"] != "ABSENT"]
    unsuccessful = [r for r in scored if r["outcome"] not in ("correct_answer", "correct_review")]
    flagged_but_correct = [r for r in failures if r["outcome"] in ("correct_answer", "correct_review")]
    ra = [f for f in failures if f["failure_class"] in ("retrieval problem", "ambiguity problem")]
    by = Counter(f["outcome"] for f in ra)
    out = {
        "unsuccessful_scored_outcomes": len(unsuccessful),
        "correct_outcomes_flagged_as_failure": len(flagged_but_correct),
        "flagged_controls": [f"{f['case']}:{f['control']}" for f in flagged_but_correct],
        "failure_cards": len(failures),
        "retrieval_and_ambiguity_cards": len(ra),
        "retrieval_and_ambiguity_missed_answers": by.get("missed_answer", 0),
        "retrieval_and_ambiguity_cascade_not_asked": by.get("not_asked", 0),
        "retrieval_and_ambiguity_unsafe_answers": by.get("unsafe_answer", 0) + by.get("wrong_answer", 0),
        "note": "failure cards = unsuccessful scored outcomes + correct answers whose pipeline verification disagreed with the form",
    }
    assert out["failure_cards"] == out["unsuccessful_scored_outcomes"] + out["correct_outcomes_flagged_as_failure"]
    assert out["retrieval_and_ambiguity_cards"] == (out["retrieval_and_ambiguity_missed_answers"]
        + out["retrieval_and_ambiguity_cascade_not_asked"] + out["retrieval_and_ambiguity_unsafe_answers"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="run a single case id")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    manifest_doc = json.loads((BENCH / "manifest.json").read_text())
    manifest = manifest_doc["cases"]
    if args.case:
        manifest = [e for e in manifest if e["id"] == args.case]
    from playwright.sync_api import sync_playwright

    all_recs: list[dict] = []
    subs: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("FORMFILL_CHROMIUM") or None)
        for entry in manifest:
            recs, sub = run_case(browser, entry)
            if entry["kind"] == "extraction":
                all_recs.extend(recs)
            if sub:
                subs.append(sub)
        browser.close()

    index = {f"{r['case']}:{r['control']}": r for r in all_recs}
    failures = []
    for r in all_recs:
        cls, why = classify(r, index)
        r["failure_class"], r["why"] = cls, why
        if cls:
            r["future"] = future_solution(r, cls)
            failures.append(r)

    report = {
        "run": run_metadata(manifest_doc),
        "cases": len({r["case"] for r in all_recs}), "overall": summarise(all_recs),
        "overall_excluding_disputed": summarise([r for r in all_recs if "disputed" not in r["tags"]]), "stages": stage_metrics(all_recs),
        "by_tag": breakdown(all_recs, lambda r: r["tags"] or ["untagged"]),
        "by_source_style": breakdown(all_recs, lambda r: [r["source_style"]]),
        "by_case": breakdown(all_recs, lambda r: [r["case"]]),
        "failure_classes": dict(Counter(f["failure_class"] for f in failures)),
        "failure_accounting": failure_accounting(all_recs, failures),
        "unsafe_answers": [{k: r[k] for k in ("case", "question", "expect", "expected_answer", "answer", "chosen_source",
                                               "confidence", "failure_class", "why")}
                           for r in all_recs if r["outcome"] in ("wrong_answer", "unsafe_answer")],
        "submission": subs, "questions": all_recs,
    }
    o = report["overall"]
    print(f"cases={report['cases']} questions={o['questions']} (expected ANSWER {o['expected_answer']}, REVIEW {o['expected_review']})")
    print(f"auto-answered={o['auto_answered']}  correct={o['correct_answers']}  UNSAFE={o['unsafe_answers']}")
    print(f"precision={o['precision_pct']}%  coverage={o['coverage_pct']}%  review_rate={o['review_rate_pct']}%  "
          f"not_surfaced={o['not_surfaced_pct']}%  answerable_recall={o['answerable_recall_pct']}%")
    print("confusion:", o["confusion"])
    d = report["overall_excluding_disputed"]
    print(f"excluding disputed labels: N={d['questions']} answered={d['auto_answered']} correct={d['correct_answers']} "
          f"unsafe={d['unsafe_answers']} precision={d['precision_pct']}%")
    print("failure classes:", report["failure_classes"])
    print("submission:", [(s["case"], s["outcome"], "OK" if s["ok"] else "MISMATCH") for s in subs])
    if not args.no_write and not args.case:
        res = BENCH / "results"
        res.mkdir(exist_ok=True)
        (res / "baseline.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        (res / "failures.md").write_text(failure_markdown(failures, report["run"], report["failure_accounting"]), encoding="utf-8")
        print(f"wrote {res.relative_to(ROOT)}/baseline.json and failures.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
