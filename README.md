# FormFiller

**FormFiller is a Python-based web-form automation prototype that helps answer Requests for Information (RFIs) using structured JSON source data.** It discovers form questions, matches them to relevant source information, validates candidate answers, fills supported controls in the browser, and checks the result before handing uncertain cases to a human reviewer.

The goal is to reduce repetitive RFI data entry without silently guessing answers or accidentally submitting a form.

## What it does

- **Discovers web forms:** inspects DOM-based pages to identify questions, labels, fields, options, and supported controls.
- **Matches source information:** retrieves relevant answers from JSON data and uses conservative matching so uncertain answers can be left for review.
- **Validates candidate answers:** checks the proposed value before interacting with the target field.
- **Fills browser controls:** uses Python and Playwright to enter text and interact with supported dropdowns and radio buttons.
- **Handles dynamic forms:** supports tested multi-step SPA workflows and some conditionally revealed fields.
- **Verifies the result:** checks values in the DOM and, where testable, whether the page's application state accepted them.
- **Uses safety checks:** flags uncertain or unsettled states for review and avoids final submission.

## How it works

```text
RFI web page
    ↓
Discover questions and form controls
    ↓
Load and normalize JSON source data
    ↓
Retrieve and match candidate answers
    ↓
Validate answers
    ↓
Fill supported controls with Playwright
    ↓
Verify DOM values and supported application-state changes
    ↓
Report results for human review
```

The workflow is designed to be conservative: if the system cannot safely handle a field or interaction, it should report the limitation rather than silently assume success.

## Technology

- **Python** — orchestration and implementation
- **Playwright** — browser automation
- **HTML/DOM inspection** — form discovery and control interaction
- **JSON** — structured source data
- **pytest** — automated regression testing

## Usage

```bash
pip install -e ".[web,dev]"      # Chromium needed; set FORMFILL_CHROMIUM=/path/to/chrome if Playwright's download is unavailable
python -m formfill fill --source company.json --url https://example/form --out-dir out [--wizard] [--redact] [--strict]
python -m formfill ask --source company.json "What is your workforce size?"   # no browser
python -m formfill check-source company.json
```

`fill` writes `result.json` (per-question outcome, source path, evidence, `human_submission`), plus `filled.png` and `trace.zip` unless `--redact`. No HTML report is generated. FormFiller **never submits**; a person reviews and submits.

## Question understanding

Retrieval scores each question against every JSON leaf by token overlap, then applies a soft alignment layer (`formfill/web/semantic.py`, `lexicon.json`): derivational stems, a small closed synonym lexicon, initialisms, abbreviations. "Workforce size", "headcount" and "number of people working in the company" resolve to `employee_count` with the path and the link recorded as evidence. Scope, negation, period, population, identifier and ambiguity checks run on the aligned tokens, and anything doubtful goes to REVIEW. No LLM, embeddings or vector DB are used (see `PROJECT_COMPLETION.md` section 6).

## Verification and test results

Verified on the current working tree (details, datasets and caveats in `PROJECT_COMPLETION.md`):

- **Tests:** 514 passed, 2 xfailed (intentional disputed labels); ruff and mypy clean.
- **Matching, development sets:** `benchmarks/rfi` 106/108 answered correct, 1 unsafe (a disputed label); `benchmarks/heldout` 119 answered, 0 unsafe. Semantic held-out v2 (author-written; first run 50 correct, 3 unsafe; 1 unsafe after fixes made once its failures were seen). Zero unsafe answers is **not** claimed.
- **Widget fixtures:** 12/12 fill, DOM read-back and fixture app-state. **SPA fixtures:** 26, zero submit events, zero submissions.
- **Demos:** `demo.py` PASS; `demo_web.py` NEEDS_REVIEW by design.

```bash
python -m pytest -q
python tools/evaluate_semantic.py --split dev --out-dir <new dir>
python tools/evaluate_widgets3d.py --out-dir <new dir>
```

**Important:** results are from local fixtures written by the project's author. No real portal has been tested, and DOM read-back or fixture state is not proof of server-side persistence.

## Safety and human review

FormFiller is intended to assist with data entry, not to make the final business decision or submit an RFI autonomously.

- Uncertain answers or unsupported interactions should be flagged for human review.
- A value visible in the DOM is not necessarily proof that the website's internal application state accepted it.
- Application-state commitment in a test fixture is not proof of server-side persistence.
- FormFiller has no submit code path. Final submission is left to a human reviewer, and the report says so (`human_submission`).

## Current limitations

- **Real-portal validation is pending.** The current evidence comes from local fixtures and local demo applications, not a real RFI portal.
- **Late conditional fields may be missed.** Fields revealed well after an interaction may appear outside the current settling window.
- **Widget coverage is incomplete.** Only supported and tested widget patterns are handled; other custom controls may stop with a review reason.
- **Some navigation is unsupported.** Finding fields inside an open Shadow DOM does not mean navigation controls inside shadow roots or iframes are fully supported.
- **Answer coverage is limited.** The matcher may abstain when it cannot identify a sufficiently supported answer. This is preferable to guessing but means some questions need manual completion.
- **Answer correctness depends on source data and matching.** Correctly filling a field does not guarantee that the source answer is complete, current, or appropriate for the RFI.
- **Saving is not confirmed.** DOM readback and application-state checks do not prove server-side persistence.

## Repository guide

- `formfill/web/` — web-form discovery, understanding, retrieval, validation, execution, and pipeline logic.
- `tests/` — automated tests.
- `tools/` — evaluation and provenance utilities.
- `benchmarks/spa/fixtures/` — local SPA and widget test fixtures.
- `benchmarks/spa/results/` — recorded evaluation outputs.
- `docs/` — design notes, evaluation reports, and implementation details.

## Project status

FormFiller is a tested prototype for JSON-driven RFI web-form automation. Its current focus is reliable form discovery, conservative answer matching, supported browser interactions, verification, and safe handoff for human review.

The next milestone is to test on a real RFI portal in an authorized, non-submitting environment. See `PROJECT_COMPLETION.md` for status and limitations.
