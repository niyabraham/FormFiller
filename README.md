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

### Validating on a page you are allowed to test (never submits)

```bash
python tools/validate_public_form.py --url https://example.test/form --source my_fictional_source.json [--policy] [--confirm-ms 1000]
```

This script has **no submit option**; it always runs the pipeline in non-submitting mode and a test checks that. Use fictional data and only pages whose owner permits testing. `--policy` walks multi-step forms (pressing only recognised Next-style buttons and refusing submit-type controls). It prints one row per question and the overall status, and writes `result.json`, `filled.png` and `trace.zip` to `--out-dir`. Raise `--confirm-ms` (up to 10000) if a page may reset fields several seconds after they are typed.

## Verification and test results

**These are automated-test and local-fixture results. They are not a validation of any real portal** (see "Current limitations" below).

Re-verified after the unsupported-controls change, built on `main` at `4726e0d` (PR #12), in a fresh virtual environment (Python 3.13, Chrome for Testing 153.0.8010.12 supplied through `FORMFILL_CHROMIUM`, Linux):

- **Automated tests:** `python -m pytest -q` gave **652 passed, 2 xfailed (expected failures), 0 failed** in about 6 min (613 before the unsupported-controls change plus 39 new tests, and two older submit-type tests rewritten).
- **CI:** the `Tests` workflow passed on the previous changes' pull requests; CI for this change is recorded on its own pull request. On the merge commit of PR #6 the first CI attempt failed once in `tests/web/test_probe_hydration.py::test_interval_bounds_contain_the_pages_own_true_interval`; re-running the same commit passed and the test passed 10 of 10 local runs. It is an intermittent diagnostic test whose cause has not been investigated.
- **SPA fixtures:** `python tools/evaluate_spa.py --policy --out-dir <dir>` ran 26 fixtures: 0 crashes, 0 submit events, 0 submission attempts, 0 submissions in its `submit=True` probe, 0 dialogs accepted, a correct safe stop on 12 of 12 expected cases, and all 3 planted resets detected (the 3 lost values it reports are those planted resets). Without `--policy` the script runs the pre-Phase-3C single-page behaviour as a baseline, and in that mode its `submit=True` probe does submit 10 local fixture pages (see `docs/PHASE3C_SPA_EVALUATION.md`); that mode was not re-run.
- **Widget fixtures:** `python tools/evaluate_widgets3d.py --out-dir <dir>` reported 12 of 12 expected fields passing fill, DOM readback and fixture application-state commitment, conditional discovery 3/3, and no side-effect or unsettled-report mismatches.
- **Demo scripts:** `demo.py` finished with "Final verification: PASS"; `demo_web.py` ran and reported `NEEDS_REVIEW` (the example page contains questions the source data does not answer, plus a consent checkbox that is never auto-ticked).
- **Matching evaluations:** development and additional-set evaluations are recorded in `docs/` and `benchmarks/`. These are development evaluations, not proof of generalisation to unseen real-world portals. They were not re-run for this update.
- **Lint and types:** neither is configured in the project or CI. Run ad hoc with `--line-length 140` over `formfill/web/`, ruff reports 8 findings both before and after the latest change (none introduced by it). mypy was not run for this change.

Run the test suite from the repository root:

```bash
python -m pytest -q
```

Both evaluation scripts require an output directory (`--out-dir`) and write there; nothing in `benchmarks/` is overwritten.

### Bugs found and fixed in this round

Both were reproduced locally before being fixed, and each has a regression test.

1. **Outcome depended on timing after a page reload.** The old README listed `test_document_navigation_stops_and_loss_is_reported` as intermittent with an uninvestigated cause. Repeating the `nav_reload` scenario 25 times gave `NEEDS_REVIEW` 15 times and `FAILED` 10 times. Instrumenting the read-back showed the cause: after a document reload the final read-back sometimes ran before the reloaded app had re-mounted its controls, found nothing, and kept the earlier "verified" verdict; when it ran after the re-mount it saw the empty field and reported the loss. The run now waits (bounded, using the same readiness check as a first load) for controls to reappear after a document navigation before judging. After the fix: 40 of 40 runs gave `FAILED`, and 80 of 80 under 8-way parallel load. Regression test: `test_loss_after_reload_is_failed_even_when_the_app_remounts_late` (a page that re-mounts 400 ms after the reload, which failed deterministically before the fix).
2. **A value wiped after the read-back was reported as `FILLED`.** With `tests/web/fixtures/late_reset.html` (the app wipes or replaces the field 500 ms after the first input) the run reported `FILLED` with the answer "verified" while the field was empty, and `submit=True` would not have been blocked. The only read-back ran within milliseconds of filling. The run now waits `confirm_ms` (default 1000 ms, configurable from 0 to 10000) after the last answer before its final read-back, so a reset inside that window is reported as `FAILED` and blocks submission. Regression tests: `test_value_wiped_after_fill_is_reported_failed_not_filled` (reset and replace modes), `test_reset_blocks_submission`, `test_stable_page_is_still_filled`, `test_confirmation_window_can_be_disabled_and_is_bounded`. At this point it is detection only; the one narrow exception is item 5.

3. **A date-format hint replaced the control's name as its label.** When a control had no `<label>`/`aria-label`, discovery used `placeholder || title || name || id` as its label, so a box whose placeholder was only `YYYY-MM-DD` or `dd/mm/yyyy` was identified by that hint instead of its name. This matches the two unmatched date rows in the first real-page run (below). Now a bare date/time format hint is used as a label only when nothing else exists. Separately, a plain text box showing a date format (`dd/mm/yyyy`, `MM/DD/YYYY`, ...) now receives an ISO source date written in that format; an unsupported or ambiguous format (`mm/dd/yy`, `d/m/yyyy`) or a source value that is not an ISO date goes to `REVIEW` instead of being typed. A date is never matched merely because it looks like a date: the control still needs a name or label that retrieval links to the source key. Regression tests: `tests/web/test_format_hints_and_choice_interference.py` (three of them fail on the old code).
4. **A later choice silently undoing an earlier one was reported only as "page holds None".** Radios that are not grouped by the browser (different or missing `name`) but behave as one choice in the application were treated as independent questions; entering the second cleared the first, and the report did not say why. After each choice (radio, checkbox, select) the run now re-reads the earlier choice answers and, if one changed, records which fill undid it on both items and adds a run warning. The earlier answer is still `verified: false`, the run is still `FAILED`, submission stays blocked, and nothing is re-entered or chosen automatically; a human decides. Browser-grouped radios (same `name`) were already one question with one selection, and separate groups still fill independently; both are pinned by tests. `result.json` now also records each processed control's discovery metadata (`controls`: name, id, placeholder, section, options), so a run can be diagnosed without the page's HTML.

5. **A text answer typed before the page's framework took the input over was lost.** Measured on the HelloForms vendor-questionnaire template (two owner-run probes, below): the server-rendered input accepted a value typed right after the load event, and about 1.5 s later the page's own framework bundle assigned `.value = ""` to the same node (named by a setter trace), at the moment React's internal keys first appeared on that node. When the probe instead waited until those keys existed, the first fill held. The pipeline now records, for each text-like answer, whether a React/Vue/Svelte framework already owned the node when the answer was typed. If the answer is later gone on the same node **and** a framework attached to that node after it was typed, the already-planned answer is entered **once more**, read back, and checked again after a further confirmation window; the item and the run both say so (`reentered`, detail text, run warning). Nothing else is re-entered: a value that disappears with no such evidence is a genuine reset, a value lost a second time is a failure, and review items, choices and non-text controls are never re-entered. Regression tests: `tests/web/test_hydration_reentry.py` against `tests/web/fixtures/late_hydrate.html`, a local page written from the measured behaviour (three of the tests fail on the previous code). One live pipeline run on the HelloForms page (owner-reported, `validate_public_form.py --confirm-ms 4000`, fictional data) found all three answered text fields already framework-owned when they were typed (`framework_attached_at_fill: true`), so **the re-entry did not trigger** (`reentered: false`) and all three values held through the 4 s window; the recovery path has therefore been exercised only on the local fixture, not on the live page. Whether a pipeline fill lands before or after hydration depends on timing, so another run may differ.

6. **Controls FormFiller cannot handle were skipped without a word, and the run could end `FILLED`.** A form with one answerable text field and a required file upload, contenteditable region, custom ARIA listbox or signature canvas was reported `FILLED` with no warning (found by a fresh unfamiliar-form evaluation; the benchmark's failure cards had listed file uploads as "not surfaced"). The run now lists every **visible, enabled** control it cannot fill or verify in `result.json` under `unsupported`, and never touches it: file uploads (`file_upload`), password fields (`password`), `contenteditable` regions (`contenteditable`), non-native ARIA `textbox`, `searchbox`, `listbox`, `radiogroup` (reported once for the group), `radio`, `checkbox`, `switch`, `slider`, `spinbutton` (`aria_<role>`), and canvases that look like signature or drawing pads (`canvas_signature`: at least 40x20 px and "sign" or "draw" in its label, id, class or title). Each record has `kind`, `label`, `tag`, `html_id`, `name`, `input_type`, `role`, `required`, `required_basis` (`attribute` or `label text`), a `reason` and `frame_index`. Hidden, disabled and `aria-hidden`/`inert` controls are not reported; a visually hidden file input is reported when a visible `<label>` points at it. Native text/select/radio/checkbox controls, ARIA comboboxes and their popups, ordinary charts and tiny tracking canvases are not reported. Regression tests: `tests/web/test_unsupported_controls.py` (23 of its 26 tests fail on the previous pipeline).

**Status and submission rules.** `FILLED` is never reported when any unsupported control is visible: such a run ends `NEEDS_REVIEW` (or stays `FAILED`/`SUBMITTED*` if another rule already set that), with a run warning naming the controls. With `submit=True`, **any** unresolved unsupported control refuses submission. A **required** one (required attribute, `aria-required="true"`, or "*" / "(required)" in its label) always refuses it, because this tool cannot answer it. An **optional** one refuses it unless a person has made an explicit decision by passing its `ack_id` (shown in `result.json`: the `html_id`, else `name`, else `label`) in `run_form(..., acknowledge_unsupported=[...])`. `ack_id` is `null` when the identifier is empty or shared with another unsupported control, and such a control can never be acknowledged by id. Every optional one must be listed, and listing an id that is not on the page changes nothing. An acknowledged run still never reports `FILLED`. Nothing is uploaded, typed or invented for these controls. In a wizard, controls on steps already left behind stay reported.

Also pinned by new tests (they already passed): an iframe form that appears late is filled, a form with no supported answer ends `NEEDS_REVIEW` with nothing typed and no submission, and a form that renders after the readiness timeout is never filled or submitted.

## Safety and human review

FormFiller is intended to assist with data entry, not to make the final business decision or submit an RFI autonomously.

- Uncertain answers or unsupported interactions should be flagged for human review.
- A value visible in the DOM is not necessarily proof that the website's internal application state accepted it.
- Application-state commitment in a test fixture is not proof of server-side persistence.
- Final submission is left to a human reviewer; the system does not claim that an RFI has been submitted successfully.
- Even with `submit=True`, submission is refused when any answer failed verification, was never successfully entered (for example a field whose commit step timed out), or a required item still needs review. Any unsupported control (see bug 6) also refuses submission: a required one always, an optional one unless explicitly acknowledged.

## Current limitations

- **Real-portal validation is only partly done.** Two non-submitting runs were made by the project owner against `https://www.qapractice.com/practice-forms` with fictional data (`validate_public_form.py --confirm-ms 5000`); the development environment's network policy blocks that site, so these are the owner's reported results, not re-run by the developer. Run 1 (before PR #7): 11 controls, 2 date boxes labelled only by their placeholders (`YYYY-MM-DD`, `dd/mm/yyyy`) left in `REVIEW`, `forms-comm-email` unverified, `FAILED`. Run 2 (with PR #7): 11 controls, 10 answered and 9 verified, including `forms-dob` = `1998-04-12`; `forms-doj` left in `REVIEW` because the source has no matching value (correct); `forms-comm-email` still unverified (page held nothing while `forms-comm-phone` held `phone`); run `FAILED`, with the new warning that a later choice undid an earlier one; no submission attempted. So the label fix is confirmed on that page. The recorded discovery metadata for run 2 shows both comm radios have **no `name` attribute** (identified by id only) and one option each, so the browser treats them as two independent groups; each was entered successfully (the click is checked by Playwright), yet only the later one is checked afterwards, so the page itself makes them behave as one choice. The page's HTML and JavaScript were not inspected, so the mechanism on the page is inferred, not read. All text fields still held their values after the 5000 ms confirmation window, so no delayed reset was reproduced on this page. One probe run (`probe_hydration.py --selector "#forms-first-name" --delay-ms 0`, headless Chromium 156, owner-reported) recorded that the page **removed and re-created the first-name input at about 929 ms, before the load event (about 1049 ms)**; a value typed after load (probe fill at about 1120 ms) landed on the replacement element and held, and a second fill at about 9.2 s held. The probe's own verdict for that first fill reads `MARKER_NEVER_OBSERVED` only because it was watching the original, detached node. This is one run on one page: it shows an early element replacement, not a reset of a filled value. A probe run on the HelloForms vendor-questionnaire template (`--selector "#try-it input[type='text']" --delay-ms 0`, headless Chromium 156, owner-reported) shows a **genuine post-fill reset of the same element, not a node replacement**: the field was filled at about 6.38 s (about 180 ms after the load event), stayed attached and the same node, and its value was cleared 1.39-1.50 s later (a `value` attribute mutation, `value=""`), during a burst of long tasks run by a `MessagePort.onmessage` listener (a scheduler pattern). The framework internals that React attaches to DOM nodes first appeared on the field at that same moment (about 7.875 s), and were absent when the value was typed; a second fill at about 14.4 s held. A second probe with the setter hook (intrusive, owner-reported) named the writer: the page's own framework bundle (`/assets/fw-C8RmI4-W.js`, minified, so the exact framework function is not identified) assigned `.value = ""` to the field 1529.5 ms after the fill, at the same moment React's internal keys first appeared on the node. A third probe that waited until those keys existed before typing got `HELD`. The `$_TSR` flag the probe watches disappeared before the reset, so it is not a reliable readiness signal. These are single runs on one page in one browser; they establish the mechanism on that page, not on pages in general. The pipeline's handling of it is described in bug 5 above. A pipeline run on the HelloForms vendor-questionnaire template (owner-reported, `--confirm-ms 4000`): 5 visible controls, 3 answered and verified (first name, last name, security contact email), 2 required items left in `REVIEW` because the fictional source has no vendor or product name, 6 hidden controls not asked, status `NEEDS_REVIEW`, no submission attempted. Iframes and wizards have been tested on local fixtures only, not on a real public page.
- **Late conditional fields may be missed.** Fields revealed well after an interaction may appear outside the current settling window.
- **Widget coverage is incomplete.** Only supported and tested widget patterns are handled. Controls it cannot handle are now listed under `unsupported` and keep a run from being `FILLED`, but detection is by markup: a custom widget built from plain `div`s with no ARIA role, `contenteditable` or canvas is not recognised and is still invisible to the report; a disabled unsupported control is not reported; and controls in cross-origin iframes may not be inspected.
- **Some navigation is unsupported.** Finding fields inside an open Shadow DOM does not mean navigation controls inside shadow roots or iframes are fully supported.
- **Answer coverage is limited.** The matcher may abstain when it cannot identify a sufficiently supported answer. This is preferable to guessing but means some questions need manual completion.
- **Answer correctness depends on source data and matching.** Correctly filling a field does not guarantee that the source answer is complete, current, or appropriate for the RFI.
- **Post-fill resets are detected within a window; only one kind is recovered.** The run re-reads answers `confirm_ms` (default 1000 ms) after the last one is entered and reports a changed value as a failure. The one recovery is a single re-entry of a text answer that was cleared after a UI framework attached to its node (bug 5 above); it is based on one page and one run pair, and only React/Vue/Svelte-style node keys are recognised, so a page that hydrates differently is not covered. A reset after the window is not seen. The default window (1 s) is shorter than the 1.4-1.5 s reset measured on HelloForms, so use `--confirm-ms` of 3000 or more on pages that boot slowly. The pipeline also waits up to 5 seconds by default (capped at 10 seconds) for visible supported controls before initial discovery on the ordinary single-page path; it does not wait for framework hydration. `tools/probe_hydration.py` measures timing on a given page.
- **Saving is not confirmed.** DOM readback and application-state checks do not prove server-side persistence.

## Repository guide

- `formfill/web/` — web-form discovery, understanding, retrieval, validation, execution, and pipeline logic.
- `tests/` — automated tests.
- `tools/` — evaluation and provenance utilities, `validate_public_form.py` (non-submitting run against a page you may test), and `probe_hydration.py`, a read-only diagnostic that fills one text field with a fictional marker, never submits, and reports whether and when the page clears it.
- `benchmarks/spa/fixtures/` — local SPA and widget test fixtures.
- `benchmarks/spa/results/` — recorded evaluation outputs.
- `docs/` — design notes, evaluation reports, and implementation details.

## Project status

FormFiller is a tested prototype for JSON-driven RFI web-form automation. Its current focus is reliable form discovery, conservative answer matching, supported browser interactions, verification, and safe handoff for human review.

The next major validation milestone is a controlled, non-submitting run against a public or explicitly authorized form, using fictional data, via `tools/validate_public_form.py`, followed by documenting field discovery, answer matching, fill/read-back verification, and any resets or unsupported widgets. Automated CI tests cover local fixtures; they do not replace this real-portal validation.
