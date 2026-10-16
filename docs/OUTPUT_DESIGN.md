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
  "human_submission": { "performed_by_formfill": false, "action_required": "a person must review the form and submit it themselves", "ready_for_human_review": true, "blockers": [] },
  "server_persistence": "not_checked",
  "not_asked": [ { "label": "...", "reason": "control stayed hidden" } ],
  "artifacts": { "screenshot_filled": "filled.png", "trace": "trace.zip", "result_json": "result.json" },
  "warnings": ["1 control(s) stayed hidden and were not asked"]
}
```

## 4. Status vocabulary (business outcome)

**[CURRENT] FormFiller never submits.** There is no submit code path; submit-type and off-page controls are refused before any click. Final submission is a human action.

| status | meaning | rule in code |
|---|---|---|
| `FILLED` | every discovered question answered and read back in the DOM; nothing submitted | no REVIEW, no failures, walk completed and page settled |
| `NEEDS_REVIEW` | at least one question needs a human; nothing wrong was entered | any REVIEW item |
| `FAILED` | a fill failed or a read-back mismatched | any ANSWER not filled/verified |

Per-question `outcome`: `needs_review`, `failed`, `unverified`, `verified_dom` (value read back from the DOM), `verified_client_state` (also confirmed by a caller-supplied `state_reader`). `server_persistence` is always `not_checked`. The `human_submission` block states that submission was not performed and lists any `blockers` to review.

## 5. Supporting artifacts

| artifact | notes |
|---|---|
| `result.json` | primary output |
| `filled.png` | full-page screenshot of the filled page (not written with `--redact`) |
| `trace.zip` | Playwright trace, `playwright show-trace` (not written with `--redact`) |

No HTML report is generated. Not implemented: confirmation text or ID, after-submit screenshot (nothing is submitted), HAR, run persistence.

## 6. Open questions for the guide

1. [RESOLVED] The end goal is *filled but not submitted*: a human clicks Send.
2. [OBSOLETE] Confirmation signals are not needed while FormFiller does not submit.
3. Who consumes `result.json`: a reviewer UI, an API, an audit store? That decides persistence and retention.
4. Do answers need to be reproducible years later (then keep the source JSON snapshot hash in the result — easy to add)?
