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
      "ever_verified": true,             // at least one matching read-back while the control was mounted
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
| `NEEDS_REVIEW` | at least one question needs a human, an answer is no longer observable, or a requested submission was refused | any REVIEW item, any ANSWER with `verified: null`, or submission outcome `SKIPPED` (also when wizard completion is unconfirmed or a network request was blocked) |
| `SUBMITTED` | submitted and the portal's confirmation was seen | submission outcome `CONFIRMED` |
| `SUBMITTED_UNCONFIRMED` | submit clicked; no success signal observed | outcome `UNCONFIRMED` |
| `FAILED` | a fill failed, a read-back mismatched/was invalid, or the browser/portal rejected the submit | any ANSWER not filled/verified, or `ERROR`/`BLOCKED_BY_VALIDATION` |

For wizard controls removed from the DOM, `verified` and `observed` are cleared because the current value cannot be checked. `ever_verified` records that an earlier visible read-back matched; this is not evidence that the site retained the value or saved it on its server.

Submission outcomes: `CONFIRMED`, `UNCONFIRMED`, `BLOCKED_BY_VALIDATION`, `NO_SUBMIT_CONTROL`, `ERROR`, `SKIPPED` (we refused: an item needs review, a verification failed or is not current, a control cannot be filled, the page never settled, or a wizard walk was incomplete or had a network request blocked).

**[CURRENT] Submission is opt-in** (`submit=False` by default) and is refused while any required question or any attestation/consent item is in REVIEW, any answer is not currently verified, or any unsupported control is unacknowledged. Other optional blanks do not block submission and remain listed in `review_items`. A wizard walk (`DiscoveryPolicy`) is always incomplete, so `submit=True` is always skipped after one.

### Wizard network guard

With a `DiscoveryPolicy`, `run_form` blocks the browser context's network traffic while it walks. It does not block every channel a browser has: it blocks the channels listed here, each measured with a local server that records what it receives (`tests/web/test_network_guard.py`, Playwright 1.64.1 with its Chromium), and the last section lists what is known to get through or was not tested. Layers, because routing alone was measured to be incomplete:

| layer | what it stops |
|---|---|
| context route (`pipeline._activate_wizard_network_guard`) | every HTTP(S) request Playwright can see, aborted before it is sent and recorded in `navigation.blocked_requests` (scheme, host and path only): form navigation, `form.submit()`, `requestSubmit()`, fetch, XHR, `sendBeacon`, images, scripts, CSS, iframes, popups, `EventSource`, `a[ping]`, requests from dedicated workers and from service workers, and the script request of a `SharedWorker` loaded from a URL |
| context WebSocket route | new WebSocket connections: they are not forwarded, and no upgrade request reaches the server. **On Playwright 1.64.1 the page sees an OPEN socket** (`readyState` 1, `onopen` fires, `send()` succeeds) whose messages go nowhere; it is not a closed socket. (On 1.48.0 see the version differences below.) Playwright cannot remove a WebSocket route and the first matching one wins, so the guard's route is kept in front of the caller's while the guard is active and behind them after release (see Lifecycle) |
| `context.set_offline(True)` | what routing cannot see: `<link rel=prefetch>`, a WebSocket opened inside a dedicated worker, WebRTC STUN/ICE traffic to a local UDP listener, and requests that a caller's own `page.route(...)` passes through with `continue_()` (a page-level route runs before the context route and would otherwise send the request). Failures it causes are reported through `requestfailed`. Measured on 1.64.1: offline alone also fails a main-frame WebSocket, even one a caller routed with `connect_to_server()`, so a WebSocket route registered after the guard cannot open one either |
| SharedWorker fence (`formfill/web/sharedworkers.py`) | a SharedWorker's requests escape the layers above. The page's `SharedWorker` constructor is replaced in every frame of every page in the context when the guard starts and, through a context init script, in every document the context loads later (same-origin iframes, `about:blank` and `srcdoc` frames included), and `SharedWorker.prototype.constructor` points at the replacement; it throws while the browser reports offline, and the attempt is recorded and stops the walk. On Chromium, SharedWorkers that already exist in the context are put offline through the DevTools protocol, and a scan at every settle point reports and puts offline any that appeared. Release ends the DevTools part; the replacement constructor stays in the page but behaves as the original once the browser is online |

A recorded blocked request stops the walk (`outbound_request_blocked`), makes the run incomplete, and keeps `submit=True` skipped. The result carries a warning naming the first blocked request.

**Lifecycle.**
- The guard stays on after `run_form` returns, so a request scheduled by a Next handler for later (a timer) is still blocked; it is appended to `result.navigation["blocked_requests"]` in memory, but a `result.json` already written is not updated.
- It ends only when the context is closed or `release_wizard_network_guard(page)` is called, after a person has reviewed the result and before navigating on. Release is idempotent: a second call does nothing, so it never overrides what the caller set since.
- **Connectivity is the caller's.** Playwright has no getter for `set_offline`, so the guard infers the caller's setting before it changes anything (the page's `navigator.onLine`, checked against a fresh context in the same browser so a host that is really offline is not mistaken for emulation) and release puts the context back to it: a context the caller had offline stays offline. Where the browser cannot be asked (a persistent context) an offline page is taken to be the caller's own setting.
- **If `run_form` raises after the guard started, the guard stays on** (the page's state is unknown, so nothing is let out) and the exception carries a note saying so and naming `release_wizard_network_guard(page)`; no result is returned. If the guard itself cannot be installed (including a SharedWorker that cannot be put offline, or a WebSocket route that cannot be put back in front), the walk stops with `network_guard_unavailable` before the page is touched, and the context is returned to the connectivity it had.
- While the guard is on, `page.goto(...)` to a network URL fails (`ERR_BLOCKED_BY_CLIENT`, or `ERR_INTERNET_DISCONNECTED` if a caller route passes it through).
- **When the guard is idle, HTTP routes the caller registered keep working** (the guard's route defers with `fallback()`). WebSocket routes cannot be deferred to by API, so the guard reorders the client's own list of WebSocket routes (`context._impl_obj._web_socket_routes`, a Playwright internal): behind the caller's after release, in front again at the next walk. If that list is not where it is expected, nothing can be parked: release emits a `RuntimeWarning` that WebSocket mocks registered before the first guarded walk stay shadowed (their sockets would connect to the real server), and later walks still run with the guard in front. If it was parked but cannot be put back in front, the next walk refuses to start (`network_guard_unavailable`). Blocking while the guard is active never depends on this list. Alternatives weighed: dropping the WebSocket route removes the dependency but also the second layer and the recording of WebSocket attempts, and refusing contexts that already hold WebSocket mocks needs the same internal list to detect them. Tested with a mock registered before the first walk, after two walk/release cycles, and after release; the real server received nothing.
- The guard's HTTP route and its WebSocket route stay registered on the context for its lifetime (Playwright cannot remove the second); idle, the HTTP route costs one Python round trip per request.
- Needs Playwright 1.48 or newer: every API used exists there (checked by running the guard tests on 1.48.0 with its Chromium 130, Python 3.11, Linux; the other measurements above were made on 1.64.1). Differences found on 1.48.0: a WebSocket route added after a page has loaded does not apply to that page, so a socket that page opens is stopped by the offline switch alone, the page sees an error rather than an open socket, and the attempt is not recorded in `blocked_requests`; and a registered service worker's request reached the server, which is why registered workers are refused (below). Other Playwright and Chromium versions were not measured.

**Offline emulation disrupts the page.** Connectivity is context-wide, so every page in the context goes offline, receives an `offline` event, and fails its own requests until release (then an `online` event). A page that reacts to going offline (disables its inputs, shows an overlay, clears or hides the form) stops the walk for reasons that look unrelated (`control_stayed_disabled`, `no_change_after_next`, `next_click_failed`, `no_safe_next_control`); the result carries a `network_guard_active` note that names this as a possible cause. That is fail-closed, not a data loss: nothing is filled on a disabled control.

**What it does not guarantee.** This is not absolute network isolation. Some requests can leave the browser before the guard or the scan detects them, and a detected one is reported, not recalled.
- A request already in flight when the guard starts is not cancelled (one measurement: it completed).
- A WebSocket the page opened before the walk: in the measurement made, what the page sent during the walk was not delivered (tested on 1.64.1); that is the offline switch's effect, not a documented guarantee. An `EventSource` or other long-lived connection opened earlier was not measured.
- SharedWorkers, the main residual:
  - A worker created during the walk by a script that holds the browser's original constructor (kept before the guard started) is not stopped when its script is a `blob:` or `data:` URL: the worker is found by the next scan and the walk stops, but one that sends from its start-up script has already sent (measured: 8 of 8 reached the local server). With an `http(s)` script URL the script request is blocked.
  - An event-driven attach to a new worker lost the race 4 times in 15 against a start-up fetch, so a scan cannot prevent that case; Playwright's `CDPSession` cannot use the browser-level auto-attach that would.
  - Without the DevTools protocol (not Chromium, or a persistent context) a SharedWorker that exists before the walk cannot be found or stopped; the result then carries a `shared_worker_check_unavailable` note.
  - Cross-origin iframes were not tested.
- The guard is per browser context: other tabs in the same context are blocked and offline too. (A route the caller adds after the guard is active, even a pass-through one, cannot send anything: the offline layer fails the request.)
- Submit events are cancelled by a capturing listener on `document`. A capturing handler the page registered on `window` runs before it, so it sees the event first; whatever request it then makes is stopped by the network layers, not by the cancellation.
- A service worker is refused up front: one that controls the page (`service_worker_controls_page`), and any other that is registered for the page's origin or running in the context (`service_worker_registered`). Routing blocked a registered, non-controlling worker's request on Playwright 1.64.1, but on 1.48.0 such a request reached the local server (measured on Linux), so the walk does not rely on it. Create the context with `service_workers="block"` (`run_url` does); `run_form` cannot enforce that for a context it did not create. A worker registered for another origin and not running is not seen.
- Tested channels beyond HTTP: WebRTC STUN/ICE to a local UDP listener (blocked). Not tested: other WebRTC traffic, WebTransport, DNS lookups for resource hints, anything outside the browser.
- A multi-step portal that fetches from its server between steps (loading the next step, validating a field) will be stopped by this guard with `outbound_request_blocked`: it is a safety trade-off, not a bug.
- Single-page runs without a policy have no network guard. Filling a field can fire the page's own change/blur handlers, including autosave calls.

### Attestations and consent

Two tiers in `plan.is_attestation`, either of which sends a question to `REVIEW` with a reason starting `attestation/consent` (the submit gate keys on that prefix, so even an **optional** one blocks `submit=True`):

1. **Explicit evidence of an act**, on any control type: the respondent agreeing, certifying, declaring, consenting, acknowledging that, accepting a terms/policy document, authorising a release or action, signing (signature fields, "sign below"), or vouching for the form ("Is the information provided accurate?", "I confirm the answers are correct"). It is looked for in the question, help text, placeholder, section heading, and (first-person only, e.g. "I agree") option labels. A heading counts only if it names the act ("Declaration", "Terms and conditions"), because a heading applies to every control after it.
2. **Broad wording** ("agreement", "consent", "terms", "confirmation", "authorization", ...) on a control that can answer "yes" (a checkbox, or a choice with a yes/agree option) whose label is a statement and not a question, after setting aside known factual compounds ("Service Level Agreement", "Operating conditions", "Confirmation email", "Authorization method", "Payment terms"). An unknown compound still goes to review, which is the safe direction.

Ordinary facts stay answerable: "Single sign-on", "Sign-in method", "Payment terms", "Do you accept credit cards?", "Do you hold ISO 27001 certification?", "Name of authorised signatory" (a name taken from the source, labelled ANSWER in the frozen held-out set).

**Added after an independent review** (each is an act with no ordinary factual reading, and has a test): promising ("undertake to", "warrants that" with any subject), being bound ("bound by the code of conduct"), "Have you read the privacy notice?", "initial here", "e-signature", "type your name to confirm", "a true and complete statement", "reflect the truth", a control whose only options are Agree/Disagree or Accept/Decline (exactly two; a scale with three or more points is still a scale), and an option "I have read and accept". "Do you support e-signature?" is therefore flagged too, as "electronic signature" already was: the safe direction.

**Known gaps, left unflagged on purpose** because their factual reading is common and the frozen held-out set labels a near-identical field (`Name of authorised signatory`) as a fact from the source: free-text "Full name of declarant", "Authorised by", "Name of person signing"; a status option "Acknowledged"; a bare "Confirm?". Such a field is filled from the source without review, so a person must look at any signature block the tool has typed into.

**Limits.** This is wording-based, not understanding. A genuine attestation phrased in a way no pattern covers, on a free-text or non-yes/no control, is answered like any other question. Unusual factual wording that merely resembles an attestation on a yes/no control is sent to review. The regression cases in `tests/web/test_attestation_detection.py` were written by the project and tuned during development; they are not an independent measure of accuracy on real questionnaires. On the project's own fixture benchmarks (464 questions) the detector changes no decision relative to the version before the all-control-types widening; those benchmarks hold only 8 attestation-type questions, so that is weak evidence about attestation recall.

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
