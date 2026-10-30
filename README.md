# FormFiller

## 1. Project Overview

FormFiller is a Python prototype that fills in web forms for **Requests for Information (RFIs)**, such as vendor and security questionnaires, using answers stored in a JSON file. It reads the form, finds the answer in your data, checks it, types it into the page, and reads the page back to confirm.

The aim is to save repetitive data entry **without guessing and without submitting anything by itself**. When it is not sure, it leaves the field alone and asks a person to decide, showing the evidence it found.

It is a tested prototype. It has not been proven on real company RFI portals (see sections 9 and 10).

## 2. How It Works

1. **Read the source data.** Your JSON file is flattened into a list of facts (for example `company.legal_name = "Northwind Ltd"`). It is the only knowledge base: FormFiller never invents an answer.
2. **Discover the form.** Playwright (a browser automation library) opens the page and lists every visible control with its label, section, type, options and whether it is required. Hidden controls are not asked.
3. **Match an answer, in layers** (`docs/MATCHING.md`):
   - exact and normalised word matching, with domain terms (SOC 2, ISO 27001, PCI DSS, BCP, RTO, 2FA, ...) and guards for scope, period, entity names and topic;
   - evidence checks: a certification or compliance claim ("Are you SOC 2 certified?") is answered only from a stated status, a subsidiary's or parent's fact is never used for the company, and facts that contradict each other send the question to review;
   - similarity search, and optionally an LLM, can only **propose** an answer for a person to approve; they never enter one.
4. **Validate** the value against the control: numbers and ranges, dates and their shown format, e-mail and URL formats, allowed options, length limits, hex colours.
5. **Plan.** Each question becomes `ANSWER` (value, source path, method, confidence category) or `REVIEW` (reason, candidates, and any proposal). Only the plan reaches the browser.
6. **Fill and verify.** Only `ANSWER` items are entered; the page is read back after a short wait. Each field ends in one state: `proposed`, `entered`, `verified`, `rejected`, `skipped` or `needs_review`.
7. **Multi-step forms** (opt-in): a navigation state machine presses recognised Next buttons, checks that each press really moved to a new step (and detects loops, no change, validation errors and redirects), stops before Next while a required question is open, and can go Back to re-verify earlier answers. The browser's network is blocked during the walk unless explicit rules allow named requests (`docs/SECURITY_MODEL.md`). The final submit step is never pressed.
8. **Report.** `result.json`, a Markdown audit report and a screenshot. Optional: a progress file to resume an interrupted walk, and a review file with a person's decisions, edited on a local review page.

## 3. Key Features

Everything below is implemented and covered by automated tests on local fixture pages (`docs/COMPATIBILITY.md` has the full matrix).

- Supported controls: text, textarea, email, url, tel, number, date, colour, select, radio groups, checkbox, checkbox groups, and ARIA comboboxes (tested patterns only). Open shadow DOM, same-origin iframes, late-rendering pages, conditionally revealed fields.
- Layered matching with provenance on every answer and proposal (`method`, `source`, `confidence_category`, `conflicts`, `validation`) and abstention instead of guessing.
- Multi-step walks: client-side wizards, server-backed single-page apps and server-rendered (form POST) wizards, with every transition recorded; Back re-verification; loop, no-change, validation-error and redirect detection; required-field gate.
- Network guard during walks, with an explicit allow-list policy for portals that must reach their server between steps; every relayed request is recorded, and requests carrying entered answers need explicit permission.
- Field-level and questionnaire-level verification: read-back, values the page clears or rejects, choices that undo each other, a review summary (required questions still open, conflicts, attestations, blocked actions).
- Human review: a local, token-protected review page to approve, edit or reject each answer; decisions are re-validated and applied on the next run. Approving is not a signature and not a submission.
- Save and resume: a versioned progress file; on resume every restored value is read back from the page, and a value that changed since is left for review, never overwritten.
- Audit report per run (`audit_report.md`), with optional redaction of the answers.
- A non-submitting validation tool for pages you are allowed to test.
- A legacy PDF proof of concept (`formfill/*.py`, `demo.py`) that preceded the web pipeline.

## 4. Safety and Human Review

- **The default never submits.** Submission happens only if the caller passes `submit=True` to `run_form`, and never after a multi-step walk. The validation tool and the review page have no submit option at all.
- **Uncertain answers go to `REVIEW`:** no match, a weak match, two plausible answers with different values, contradicting facts, a certification or compliance claim without a stated status, another entity's fact, a value that fails validation, disabled controls, and attestations. An attestation is wording in which the respondent agrees, consents, declares, certifies, signs, authorises something, or vouches that the form is accurate; it is detected on any control type and is never answered from the source data (the review page only lets a person acknowledge it, to complete in the portal). The detection is wording-based; see section 10.
- **Proposals are never answers.** Similarity and LLM suggestions appear as `proposed_answer` on a `REVIEW` item (and as "proposed, not entered" in the audit report) until a person approves them.
- **Controls it cannot fill are reported, never touched:** file uploads, password fields, `contenteditable` regions, custom ARIA widgets (textbox, listbox, slider and similar), and signature-style canvases. A run with any of them is never `FILLED`.
- **Submission is refused** (when `submit=True`) if any answer failed or was never entered, a required item needs review, the page never settled, a walk stopped early, or an unsupported control is present (an optional one can be acknowledged by its `ack_id` in `acknowledge_unsupported`; a required one always blocks).
- **Multi-step navigation never presses a submit-type button, a link that leaves the page, or a button labelled Submit, Send, Sign, Certify, Accept, Finish and similar,** and never accepts browser dialogs. A submit-type Next is pressed only when an explicit `form_navigation` rule covers that form.
- **The browser's network is blocked during a walk, on the channels that were tested. This is not absolute network isolation** (`docs/SECURITY_MODEL.md` lists what is blocked, what is permitted, what was not tested and what cannot be guaranteed). By default nothing is let out; with a `NetworkPolicy`, only requests matching an explicit rule are relayed, the browser itself stays offline, and every relayed request is recorded. Any blocked attempt stops the walk and keeps the status at `NEEDS_REVIEW`. The block stays on after the run until the browser context closes or `release_wizard_network_guard(page)` is called after review.
- **A value shown in the page is not proof of saving.** FormFiller checks the page, not the server, and never claims a form was saved or submitted unless the page shows a confirmation text you supplied.
- **Artifacts are protected:** written atomically, owner-only on POSIX systems, with URLs reduced to scheme, host and path. Progress and result files hold no cookies or tokens. Playwright traces are off by default; when requested, cookie and authorization values are removed from them. Generated output is git-ignored.
- **Optional AI services stay optional.** Nothing leaves the machine unless code enables the LLM layer and `FORMFILL_LLM_ALLOW_EXTERNAL=1` confirms it (section 7).

## 5. Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.11+ | All code |
| Playwright (Chromium) | Opens pages, reads controls, fills and reads back, walks wizards |
| JSON | Source data, results, progress and review files |
| pypdf | The legacy PDF proof of concept only |
| pytest, ruff, mypy, pip-audit | Tests, lint, type checking, dependency audit (`pip install -e ".[dev]"`) |
| sentence-transformers (optional, `.[semantic]`) | A local embedding model for similarity proposals; never downloaded at run time |
| anthropic (optional, `.[llm]`) | An LLM second opinion that only proposes; off unless explicitly enabled; tested with a fake client only |
| GitHub Actions | Lint, types, dependency audit, matching report; tests on Python 3.11 and 3.12 with Chromium required; wizard navigation report |

Matching is deterministic by default. Without the optional extras there are no machine-learning models and no external services.

## 6. Project Structure

- `formfill/web/` — the web pipeline:
  - reading the form: `discover.py`, `understand.py`, `tokens.py`;
  - matching: `retrieve.py` (scores facts), `evidence.py` (claims, conflicts), `semantic.py` (proposals), `llm.py` (optional), `matching.py` (configuration, confidence categories), `plan.py` (ANSWER or REVIEW), `validate.py`;
  - filling: `execute.py`, `verify.py`;
  - multi-step: `navigation.py` (state machine), `steps.py` (Next/Back rules), `guard.py`, `netpolicy.py`, `sharedworkers.py` (network guard);
  - results: `result.py` (states, summary), `report.py` (audit report), `progress.py` (resume), `review.py` and `review_server.py` (human review), `artifacts.py` (safe writing);
  - `pipeline.py` runs everything (`run_form`, `run_url`).
- `formfill/*.py`, `demo.py` — the older PDF proof of concept.
- `tests/` — automated tests; `tests/web/fixtures/` holds small HTML pages used by them.
- `benchmarks/` — fictional forms with expected answers: `rfi/` (development set), `heldout/` (second set), `semantic/` (matching dev and eval sets), `spa/` (browser fixtures), `wizards/` (multi-step fixtures, local server and scenarios).
- `tools/` — evaluation scripts and `validate_public_form.py`.
- `examples/` — fictional sample data and a local sample RFI page.
- `docs/` — `SECURITY_MODEL.md`, `MATCHING.md`, `COMPATIBILITY.md`, `OUTPUT_DESIGN.md` (result format), `PROGRESS.md` (implementation log), and earlier design notes and evaluation reports.

## 7. Setup and Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # add ,semantic or ,llm for the optional layers
playwright install chromium
```

Playwright 1.48 or newer is required (the network guard uses WebSocket routing); the guard measurements were made on 1.64.1 and, for the guard tests, 1.48.0.

| environment variable | effect |
|---|---|
| `FORMFILL_CHROMIUM` | path of a Chromium executable to use instead of Playwright's |
| `FORMFILL_REQUIRE_BROWSER=1` | browser tests fail instead of being skipped when Chromium cannot be launched (CI sets it) |
| `FORMFILL_EMBEDDING_MODEL` | directory of a local sentence-transformers model for similarity proposals (needs `.[semantic]`); falls back to the built-in backend if it cannot be loaded |
| `FORMFILL_LLM=anthropic` and `FORMFILL_LLM_ALLOW_EXTERNAL=1` | read by `llm.reranker_from_env()`, which code passes as `MatcherConfig(reranker=...)`; sends the question text and candidate key paths to Anthropic's API (the SDK reads `ANTHROPIC_API_KEY`). `FORMFILL_LLM_SEND_VALUES=1` also sends the candidate values; `FORMFILL_LLM_MODEL` picks the model. Without the confirmation variable it refuses to start |

## 8. How to Run

All examples use fictional data and local pages.

```bash
python demo_web.py        # fills examples/web/rfi_form.html; never submits unless you add --submit
python demo.py            # the older PDF proof of concept
python -m pytest -q       # the automated tests
```

`demo_web.py` writes `output/web/result.json`, `audit_report.md`, `filled.png` and `trace.zip`. It ends `NEEDS_REVIEW` because the sample page asks questions the sample data does not answer.

To try a page you are allowed to test (never submits; use fictional data only):

```bash
python tools/validate_public_form.py --url https://example.test/form --source my_fictional_source.json \
    [--policy] [--confirm-ms 1000] [--out-dir output/public_validation] [--trace]
```

Source keys should resemble the form's wording (for example `company.legal_name` for "Legal name"). `--policy` walks multi-step forms with the network blocked, so a portal that loads its next step from its server stops at `outbound_request_blocked`. Use `--confirm-ms 3000` or more on pages that start slowly. `--trace` also saves a Playwright trace, which holds the page content and the answers entered.

**In code:**

```python
from formfill.web.pipeline import run_form, release_wizard_network_guard
from formfill.web.steps import DiscoveryPolicy
from formfill.web.netpolicy import NetworkPolicy, AllowRule

result = run_form(page, source)                                     # one page; nothing is submitted
result = run_form(page, source, policy=DiscoveryPolicy(),          # a multi-step walk, network blocked
                  out_dir="output/run1", progress_path="output/run1/progress.json")
result = run_form(page, source, policy=DiscoveryPolicy(), progress_path="output/run1/progress.json",
                  resume=True)                                      # continue it later; restored values are read back
policy = NetworkPolicy(rules=(AllowRule(origin="https://portal.example", path="/api/section/*", note="load the next section"),))
result = run_form(page, source, policy=DiscoveryPolicy(), network_policy=policy)   # allow named requests only
release_wizard_network_guard(page)                                  # after a person has reviewed the result
```

`run_url(url, source_path, out_dir=..., trace=False)` launches Chromium itself.

**Human review:**

```bash
python -m formfill.web.review_server output/run1/result.json --build   # prints http://127.0.0.1:<port>/?token=...
```

Decisions are saved to `review.json` next to the result. Apply them on the next run with `run_form(..., planner=decisions_planner(load_review("output/run1/review.json")))` (`formfill/web/review.py`); each decision is re-validated against the control first, and an approval goes back to review if the proposal it approved has changed since or the value no longer fits the field.

**Source data.** Any JSON object holding facts about the company; nesting is fine and keys should resemble the wording of the questions they answer (see `examples/web/rfi_source.json`):

```json
{ "company": { "name": "Acme Corp", "employees": 250, "website_url": "https://acme.example" },
  "security": { "contact": { "email": "security@acme.example" } },
  "certifications": { "iso_27001": { "status": "certified" } } }
```

Add keys only for facts you can stand behind. A certification is answered "Yes" only from a stated status such as `certified`, `true` or `compliant`; `in progress`, `planned` or a mere mention leads to review. Attestations are never answered from the source, so keys such as `terms_accepted` are not used.

**Statuses** (`docs/OUTPUT_DESIGN.md` has the exact rules): `FILLED` (everything answered and verified, nothing submitted), `NEEDS_REVIEW` (a person must act), `FAILED` (a fill or read-back failed, or the page rejected a value), `SUBMITTED` / `SUBMITTED_UNCONFIRMED` (only after `submit=True` and every check passed).

## 9. Testing and Evaluation

**Checked on 29 Oct 2026, on branch `feature/rfi-completion`.**

### Automated tests (local fixture pages)

- Windows 11, Python 3.12, Playwright 1.64.1 with its Chromium, `FORMFILL_REQUIRE_BROWSER=1`: **1258 passed, 2 expected failures (xfail), 0 failed, 0 skipped** (`python -m pytest -q`, 10 to 15 minutes). Before this work: 1123 passed, 2 xfailed.
- Linux (Ubuntu 24.04 under WSL), Python 3.11, Playwright 1.64.1, same strict mode: 1252 passed, 2 xfailed, 0 failed, 0 skipped. This run was made before the last six tests were added; those files were re-run on Linux afterwards and pass (`docs/PROGRESS.md`).
- Playwright 1.48.0 (the oldest supported version), Linux: the network-guard, wizard, policy, progress and review tests pass.
- `ruff check formfill tools tests benchmarks`: no findings. `mypy` (settings in `pyproject.toml`): no issues. `pip-audit`: no known vulnerabilities in the project's dependencies. No code formatter is configured.
- The two expected failures are a disputed company-versus-subsidiary label in the benchmarks, kept as strict `xfail` (they fail the run if they start passing).
- CI (`.github/workflows/tests.yml`) runs on pull requests and on pushes to `main`; it has not run on this branch yet.

### Fixture-based evaluations (not real websites)

These use fictional forms written by the project. Results show behaviour on those forms only.

| Evaluation | Result |
|---|---|
| Matching, development set (`benchmarks/rfi`, 192 questions, browser) | precision 98.1 %, coverage 55.2 % (before this work: 98.0 %, 52.6 %) |
| Matching, second set (`benchmarks/heldout`, 272 questions, browser) | precision 100 %, coverage 40.1 % (before: 100 %, 39.3 %) |
| Matching layers, `benchmarks/semantic` eval set (30 cases, written and hashed before the layers existed) | precision 1.00, coverage 0.71, 0 unsafe answers, 4 of 4 proposals right (before: 0.78, 0.41, 2 unsafe) |
| Wizard navigation and safety (`tools/evaluate_wizards.py`, 16 scenarios) | 16 of 16 expected outcomes, 0 final submissions, 0 requests reaching the server without a relay record, 0 answers sent without permission |
| Multi-step and SPA fixtures (`tools/evaluate_spa.py --policy`, 26 fixtures) | 0 crashes, 0 submit events, 0 submissions, 0 dialogs accepted, 11 of 12 expected safe stops, 1 of 3 planted resets detected, 77 of 82 controls discovered |
| Widget fixtures (`tools/evaluate_widgets3d.py`) | 12 of 12 expected fields filled and read back, 3 of 3 conditional fields found |

On both browser matching benchmarks every changed decision went from a missed answer to a correct one. The SPA row is unchanged since the network guard was added: three fixtures stop at their first network request or page reload (`outbound_request_blocked`), so their later steps and planted resets are not reached. That is the block working as designed; the expected results were not edited.

To reproduce (they need `--out-dir` and write nothing into `benchmarks/`):

```bash
python tools/evaluate_baseline.py --out-dir output/eval_dev
python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir output/eval_heldout
python tools/evaluate_matching.py --out-dir output/eval_matching          # no browser; dev and eval sets
python tools/evaluate_wizards.py --out-dir output/eval_wizards
python tools/evaluate_spa.py --policy --out-dir output/eval_spa
```

"Precision" is the share of answered questions that were correct; "coverage" is the share of expected answers that were filled. The held-out set was frozen before it was first run, but it has since been used to guide fixes, so it is no longer independent evidence. The semantic eval set was written by the same author as the dev set; see `docs/MATCHING.md` for what that means.

### Real webpage experiments (fictional data, nothing submitted)

- **Selenium's public test form (`selenium.dev` web-form), re-run on this branch on 29 Oct 2026:** 11 controls found, plus 2 reported as unsupported (password, file upload). Text, textarea, colour, date and range were filled and verified; the two dropdown questions and the checkbox and radio groups went to `REVIEW`; status `NEEDS_REVIEW`, nothing submitted. Same outcome as the owner's earlier run.
- **QA practice form (`qapractice.com`), owner's earlier runs, not re-run:** 11 controls; 10 answered and 9 verified. One choice (radios without a `name`) could not be verified. The run ended `FAILED`.
- **HelloForms vendor-questionnaire template, owner's earlier run, not re-run:** a text answer typed right after page load was cleared about 1.5 s later by the page's own framework. In the later full run, 3 answers were verified and the automatic re-entry did **not** trigger, so that recovery is tested on a local fixture only.

These show the pipeline running on public practice and template pages. They are not evidence that it works on real company portals.

## 10. Current Limitations

- **Not validated on real RFI portals.** No company portal, login, or real multi-step questionnaire has been tested.
- **Multi-step walks need the portal's cooperation.** By default every request is blocked, so a portal that loads steps, validates fields or autosaves through its server stops with `outbound_request_blocked` unless you write allow rules for those endpoints. Single sign-on, CAPTCHA, login and payment pages are never handled.
- **The network block has gaps** (`docs/SECURITY_MODEL.md`): connections the page opened before the walk are not closed, requests the page makes before the walk starts are not blocked, a `SharedWorker` made with a constructor the page kept from before the walk and a `blob:` script can send before it is noticed, the DevTools-based layers need Chromium, offline emulation is context-wide and can make a page stop the walk, and only Playwright 1.48.0 and 1.64.1 with their Chromium builds were measured.
- **Matching is conservative by design.** Coverage is about half on the development set and 40 % on the second set; a correct fill is only as good as the source data, and untested wording can still be matched wrongly. Similarity proposals depend on spelling and the synonym table unless a local embedding model is configured.
- **Attestation detection is wording-based.** A genuine attestation phrased in an unexpected way, on a free-text or number field, is answered like any other question; some factual yes/no questions with unusual wording go to review.
- **Detection of unsupported controls is by markup.** A widget built from plain `div`s with no ARIA role is not seen; controls in cross-origin iframes or closed shadow roots are not inspected; datalist options are not read.
- **Page behaviour is only partly handled.** Fields that appear well after an interaction can be missed, a reset after the confirmation window is not seen, and the single re-entry recovers React/Vue/Svelte patterns only. Next buttons inside shadow roots or iframes are not found.
- **Saving is not confirmed.** A correct read-back does not prove the server stored the value.
- **The review page is for one local reviewer.** It has no accounts, no audit of who decided, and no concurrent editing.
- **Windows file permissions** are inherited from the output folder; only POSIX systems get owner-only files automatically.
- **No logging module.** Runs are explained through `result.json`, the audit report and warnings.

## 11. Future Improvements

- Validate on real, permitted multi-step portals, and with a test set written by someone else.
- Read datalist options; support more custom widgets and navigation inside shadow roots and iframes.
- A reviewed final-step workflow in which a person explicitly approves submission.
- Multi-reviewer review with identities and an audit trail.
- OS-level egress control (a proxy or firewall rule) as a stronger boundary than the in-browser guard.

## 12. Behaviour Changes in This Version

- `run_url` no longer records a Playwright trace by default (`trace=True` to ask for one); traces are scrubbed of cookie and authorization values. Reason: Playwright stores a portal's session cookie in the trace.
- A multi-step walk now stops before Next while a required question is unanswered (`required_unresolved`). `DiscoveryPolicy(advance_with_unresolved_required=True)` restores the old behaviour.
- Certification and compliance questions are answered only from a stated status; a source that merely mentions the standard now leads to review.
- `run_form` refuses to overwrite an existing progress file unless `resume=True`.
- Internal helpers moved out of `pipeline.py` into `guard.py`, `verify.py` and `navigation.py`; `run_form`, `run_url` and `release_wizard_network_guard` are unchanged and still importable from `formfill.web.pipeline`.
