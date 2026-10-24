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

## Setup

Requires Python 3.11 or newer. From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

`playwright install chromium` downloads the browser the web pipeline drives. To use a Chromium you already have, set `FORMFILL_CHROMIUM` to its executable path (the tests and `demo_web.py` honour it). Browser tests are skipped automatically when no Chromium can be launched, so a run without a browser reports fewer passes rather than failing.

## Demos

Both demos use the fictional data under `examples/` and never contact a real site.

```bash
python demo.py        # legacy PDF proof of concept: match, fill, verify, human-review step
python demo_web.py    # fills the local example RFI page (examples/web/rfi_form.html); does not submit
```

`demo_web.py` writes `output/web/result.json`, `filled.png` and `trace.zip`. Passing `--submit` also submits, but only the local example page and only when no required item needs review; the default never submits.

## Verification and test results

Verified on `main` at merge commit `c0adc05` (PR #2), in a fresh clone with a fresh virtual environment (Python 3.13, Playwright Chromium 1194, Linux):

- **Automated tests:** two full-suite runs were performed on this commit. One run had 562 passed and 2 xfailed (expected failures), in about 3 min 48 s. The other had 561 passed, 1 failed, and 2 xfailed. See the note on an intermittent test below.
- **SPA fixtures:** `python tools/evaluate_spa.py --policy --out-dir <dir>` ran 26 fixtures with no crashes and reported 0 submit events, 0 submission attempts, 0 submissions in its `submit=True` probe, 0 dialogs accepted, and a correct safe stop on 12 of 12 expected cases. The 3 lost values it reports are planted resets and a full reload, which the run detects and ends as failed. Without `--policy` the script runs the pre-Phase-3C single-page behaviour as a baseline, and in that mode its `submit=True` probe does submit 10 local fixture pages (see `docs/PHASE3C_SPA_EVALUATION.md`).
- **Widget fixtures:** `python tools/evaluate_widgets3d.py --out-dir <dir>` reported 12 of 12 expected fields passing fill, DOM readback and fixture application-state commitment, conditional discovery 3/3, and no side-effect or unsettled-report mismatches.
- **Demo scripts:** `demo.py` finished with "Final verification: PASS"; `demo_web.py` ran and reported `NEEDS_REVIEW` (the example page contains questions the source data does not answer, plus a consent checkbox that is never auto-ticked).
- **Matching evaluations:** development and additional-set evaluations are recorded in `docs/` and `benchmarks/`. These are development evaluations, not proof of generalisation to unseen real-world portals. They were not re-run for this update.

Run the test suite from the repository root:

```bash
python -m pytest -q
```

Both evaluation scripts require an output directory (`--out-dir`) and write there; nothing in `benchmarks/` is overwritten.

**Intermittent test:** `tests/web/test_spa_browser.py::test_document_navigation_stops_and_loss_is_reported` passes on its own and in most full runs, but failed once in two full-suite runs of `c0adc05` (`assert 'NEEDS_REVIEW' == 'FAILED'`). The same failure also reproduced once in 12 parallel runs under CPU load on the earlier commit `4ffe03b`, so it predates PR #2. It appears to be timing-sensitive; the cause has not been investigated or fixed. If it fails, re-run it alone before treating it as a regression.

**Important:** These results are from automated tests and local fixtures. They do not establish production readiness or guarantee that a real website has saved the entered data.

## Safety and human review

FormFiller is intended to assist with data entry, not to make the final business decision or submit an RFI autonomously.

- Uncertain answers or unsupported interactions should be flagged for human review.
- A value visible in the DOM is not necessarily proof that the website's internal application state accepted it.
- Application-state commitment in a test fixture is not proof of server-side persistence.
- Final submission is left to a human reviewer; the system does not claim that an RFI has been submitted successfully.
- Even with `submit=True`, submission is refused when any answer failed verification, was never successfully entered (for example a field whose commit step timed out), or a required item still needs review.

## Current limitations

- **Real-portal validation is pending.** The current evidence includes local fixtures and a limited, non-submitting fill test on a public QA practice form using fictional data; this is not a full end-to-end validation of a real RFI portal.
- **Late conditional fields may be missed.** Fields revealed well after an interaction may appear outside the current settling window.
- **Widget coverage is incomplete.** Only supported and tested widget patterns are handled; other custom controls may stop with a review reason.
- **Some navigation is unsupported.** Finding fields inside an open Shadow DOM does not mean navigation controls inside shadow roots or iframes are fully supported.
- **Answer coverage is limited.** The matcher may abstain when it cannot identify a sufficiently supported answer. This is preferable to guessing but means some questions need manual completion.
- **Answer correctness depends on source data and matching.** Correctly filling a field does not guarantee that the source answer is complete, current, or appropriate for the RFI.
- **Post-fill resets are detected but not automatically recovered.** A page that clears or replaces an input shortly after it is typed (for example while an app finishes loading) is reported as a failed or unverified item rather than re-entered automatically. The read-only diagnostic `tools/probe_hydration.py` can measure this on a given page. The pipeline now waits up to 5 seconds by default (capped at 10 seconds) for visible supported controls before initial discovery on the ordinary single-page path, but it does not yet retry a value that resets after filling.
- **Saving is not confirmed.** DOM readback and application-state checks do not prove server-side persistence.

## Repository guide

- `formfill/web/` — web-form discovery, understanding, retrieval, validation, execution, and pipeline logic.
- `tests/` — automated tests.
- `tools/` — evaluation and provenance utilities, and `probe_hydration.py`, a read-only diagnostic that fills one text field with a fictional marker, never submits, and reports whether and when the page clears it.
- `benchmarks/spa/fixtures/` — local SPA and widget test fixtures.
- `benchmarks/spa/results/` — recorded evaluation outputs.
- `docs/` — design notes, evaluation reports, and implementation details.

## Project status

FormFiller is a tested prototype for JSON-driven RFI web-form automation. Its current focus is reliable form discovery, conservative answer matching, supported browser interactions, verification, and safe handoff for human review.

The next major validation milestone is a controlled, non-submitting run against a public or explicitly authorized form, using fictional data, followed by documenting field discovery, answer matching, fill/read-back verification, and any resets or unsupported widgets. Automated CI tests cover local fixtures; they do not replace this real-portal validation.
