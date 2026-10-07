# Output design: what does the system finally produce?

*Guide's open question: "What exactly is expected as the final output?" A web form has no output file like a filled PDF.*

Labels used throughout: **[CONFIRMED]** stated by the guide · **[CURRENT]** implemented in this repo · **[FINDING]** verified in a source this session · **[RECOMMEND]** our proposal · **[FUTURE]** not built · **[OPEN]** needs a decision.

## 1. Conclusion

**[RECOMMEND]** The primary output is a **machine-readable run result (`result.json`)**. The browser's final state is a *side effect*; `result.json` is the *record*. It is supported by evidence artifacts (screenshot, Playwright trace). This is what [`formfill/web/result.py`](../formfill/web/result.py) emits today.

Why not "the filled form" as the output: a form that has been filled in a browser session is not durable, not diffable, and not auditable. The business needs to know *which questions were answered from which source value*, *which were not*, and *whether the portal accepted it*. Only a structured record carries that.

## 2. What comparable systems return (evidence for the choice)

| System | Output | Per-answer confidence | Per-answer source | Unanswered handling |
|---|---|---|---|---|
| rfp-autopilot [FINDING] | same `.xlsx` with answer, confidence, source, status colours | yes | source IDs | `Needs SME review` below 0.48 |
| security-questionnaire-responder [FINDING] | YAML (canonical), JSON, XLSX | yes | cited KB entries | flagged for human below 0.7 |
| Form-Flow-AI [FINDING, README only] | `MagicFillResult` with filled vs unfilled fields | not verified | not verified | unfilled list |
| Skyvern [FINDING] | task result + optional JSON-schema extraction | no | no | agent-dependent |
| Stagehand `extract()` [FINDING] | schema-validated object | no | no | schema failure |
| Browser Use [FINDING] | agent history / action results | no | no | none (no abstain concept) |
| Conveyor, Vanta [FINDING, vendor/third-party pages, not independently verified] | drafts with citations, confidence tiers, approval workflow, audit trail | yes | yes | "needs review" queue |

Reading: the **browser agents return task-level results with no provenance**; the **questionnaire tools return per-answer results with confidence and source**. We need the second shape, produced on top of a browser executor. No surveyed project does both (see `GITHUB_LANDSCAPE.md`).

## 3. Result schema (implemented)

```jsonc
{
  "run_id": "9f2c1a7b3d4e",
  "url": "file:///.../rfi_form.html",
  "status": "NEEDS_REVIEW",            // see 4
  "started_at": "2026-10-07T01:17:00+00:00",
  "finished_at": "2026-10-07T01:17:03+00:00",
  "items": [
    {
      "plan": {
        "question_id": "f0-c2",
        "question": "Number of full-time employees",
        "field_type": "number",
        "required": false,
        "status": "ANSWER",              // ANSWER | REVIEW
        "source": "company.full_time",   // provenance: JSON path
        "raw_value": 210,                // as found in the JSON
        "answer": 210,                   // after validation/transformation
        "confidence": 0.87,
        "reason": null,                  // why REVIEW
        "alternatives": [{"source": "company.employees", "value": 250, "score": 0.40}]
      },
      "filled": true,
      "observed": "210",                 // read back from the page afterwards
      "verified": true,                  // observed == answer
      "browser_valid": true,             // HTML constraint validation
      "detail": "",
      "prefilled_warning": false         // a REVIEW control already held a page default
    }
  ],
  "review_items": [ { "question_id": "...", "question": "...", "required": true, "reason": "...", "alternatives": [] } ],
  "submission": { "attempted": true, "outcome": "CONFIRMED", "final_url": "...", "confirmation_text": "Thank you, ..." },
  "artifacts": { "screenshot_filled": "filled.png", "screenshot_after_submit": "after_submit.png", "trace": "trace.zip", "result_json": "result.json" },
  "warnings": ["1 control(s) stayed hidden and were not asked"]
}
```

## 4. Status vocabulary (business outcome)

| status | meaning | rule in code |
|---|---|---|
| `FILLED` | every discovered question answered and verified; not submitted | no REVIEW, no failures, no submission |
| `NEEDS_REVIEW` | at least one question needs a human; nothing wrong was entered | any REVIEW item (also when submit was skipped because a required item is unresolved) |
| `SUBMITTED` | submitted and the portal's confirmation was seen | submission outcome `CONFIRMED` |
| `SUBMITTED_UNCONFIRMED` | submit clicked; no success signal observed | outcome `UNCONFIRMED` |
| `FAILED` | a fill failed, a read-back mismatched, or the browser/portal rejected the submit | any ANSWER not filled/verified, or `ERROR`/`BLOCKED_BY_VALIDATION` |

Submission outcomes: `CONFIRMED`, `UNCONFIRMED`, `BLOCKED_BY_VALIDATION`, `NO_SUBMIT_CONTROL`, `ERROR`, `SKIPPED` (we refused: a required item needs review or a verification failed).

**[CURRENT] Submission is opt-in** (`submit=False` by default) and is refused while any *required* question is in REVIEW. Optional blanks do not block submission and remain listed in `review_items`.

## 5. Supporting artifacts

| artifact | MVP | notes |
|---|---|---|
| `result.json` | **yes** | primary output |
| full-page screenshot before submit | **yes** | `filled.png` |
| screenshot after submit | **yes** | `after_submit.png` (confirmation evidence) |
| Playwright trace (`trace.zip`) | **yes** (via `run_url`) | `playwright show-trace`; contains screenshots, DOM snapshots, actions [FINDING: playwright.dev trace viewer docs] |
| confirmation text + final URL | **yes** | inside `submission` |
| submission/confirmation ID | [FUTURE] | needs a per-portal extraction rule; [OPEN] whether portals show one |
| HAR / network log, DOM snapshot of the confirmation page | [FUTURE] | add when audit requirements are known |
| PDF/print of the confirmation | [FUTURE] | only if a customer needs a receipt |
| persistence (DB) of runs, reviewer decisions | [FUTURE] | files are enough until there is a review UI |

## 6. Open questions for the guide

1. Is the end goal *filled but not submitted* (a human clicks Send) or *submitted*? The code supports both; the default is the safe one.
2. Is there a confirmation signal per portal (text, reference number, email)? Without it `SUBMITTED_UNCONFIRMED` is the best we can say.
3. Who consumes `result.json`: a reviewer UI, an API, an audit store? That decides persistence and retention.
4. Do answers need to be reproducible years later (then keep the source JSON snapshot hash in the result — easy to add)?
