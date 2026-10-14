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

## Verification and test results

The latest recorded verification on the `phase3d-widget-commitment` branch reported:

- **Automated tests:** 415 passed, 2 xfailed (expected failures).
- **Widget fixtures:** 12/12 for filling, DOM readback, and fixture application-state commitment.
- **SPA fixtures:** 26 tested fixtures, with zero submission events and zero submission attempts reported.
- **Demo scripts:** `demo.py` passed; `demo_web.py` ran successfully.
- **Matching evaluations:** development and additional-set outcomes were unchanged by the widget work. These are development evaluations, not proof of generalisation to unseen real-world portals.

Run the test suite from the repository root:

```bash
python -m pytest -q
```

The widget evaluation script is:

```bash
python tools/evaluate_widgets3d.py
```

See the `docs/` and `benchmarks/spa/results/` directories for evaluation details, fixture definitions, provenance information, and recorded outputs.

**Important:** These results are from automated tests and local fixtures. They do not establish production readiness or guarantee that a real website has saved the entered data.

## Safety and human review

FormFiller is intended to assist with data entry, not to make the final business decision or submit an RFI autonomously.

- Uncertain answers or unsupported interactions should be flagged for human review.
- A value visible in the DOM is not necessarily proof that the website's internal application state accepted it.
- Application-state commitment in a test fixture is not proof of server-side persistence.
- Final submission is left to a human reviewer; the system does not claim that an RFI has been submitted successfully.

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

The next major validation milestone is to test the workflow on a real RFI portal in an authorized, non-submitting environment and document the results.
