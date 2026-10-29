# FormFiller

## 1. Project Overview

FormFiller is a Python prototype that fills in web forms for **Requests for Information (RFIs)**, such as vendor and security questionnaires, using answers stored in a JSON file. It reads the form, finds the answer in your data, checks it, types it into the page, and reads the page back to confirm.

The aim is to save repetitive data entry **without guessing and without submitting anything by itself**. When it is not sure, it leaves the field alone and asks a person to decide.

It is a tested prototype. It has not been proven on real company portals (see sections 9 and 10).

## 2. How It Works

1. **Read the source data.** Your JSON file is flattened into a list of possible answers (for example `company.legal_name = "Northwind Ltd"`).
2. **Discover the form.** Playwright (a browser automation library) opens the page and lists every visible control with its label, type, options and whether it is required. Controls hidden by the page are not asked.
3. **Understand each question.** The label text is cleaned and reduced to key words.
4. **Match an answer.** Each question is scored against the source keys by word overlap. A match is used only if the score is high enough and no other answer with a different value is nearly as good.
5. **Validate.** The value is checked against the control: numbers, ISO dates, e-mail and URL formats, allowed options, length limits, hex colours.
6. **Plan.** Each question becomes either `ANSWER` (with the value and where it came from) or `REVIEW` (with the reason). Only this plan reaches the browser.
7. **Fill.** Only `ANSWER` items are entered. After a short wait (`confirm_ms`, default 1 s) the page is read back.
8. **Verify and report.** The result (`result.json`, a screenshot and a Playwright trace) lists each item, what the page holds, and an overall status: `FILLED`, `NEEDS_REVIEW`, `FAILED`, or (only if submission was asked for and allowed) `SUBMITTED` / `SUBMITTED_UNCONFIRMED`.

For multi-step forms, a **policy** mode can press recognised "Next" buttons and repeat the steps above on each page.

## 3. Key Features

Everything below is implemented and covered by automated tests on local fixture pages.

- Supported controls: text, textarea, email, url, tel, number, date, colour, select, radio groups, checkbox, checkbox groups, and ARIA comboboxes (tested patterns only).
- Conservative matching with abstention instead of guessing, plus handling for qualifiers, booleans, nested JSON, and option mapping.
- Multi-step forms (opt-in policy, run with the network blocked; see section 4), conditionally revealed fields, open shadow DOM, iframes in the same browser process, and waiting for pages that render late.
- Read-back verification, plus detection of values that the page clears after filling.
- One automatic re-entry of a text answer that a UI framework (React/Vue/Svelte) wiped after it attached to the field.
- Detection of choices that silently undo each other.
- Reporting of visible controls it cannot handle (see section 4).
- A non-submitting validation tool for pages you are allowed to test.
- A legacy PDF proof of concept (`formfill/*.py`, `demo.py`) that preceded the web pipeline.

## 4. Safety and Human Review

- **The default never submits.** Submission happens only if the caller passes `submit=True` to `run_form`. The command-line validation tool has no submit option at all.
- **Uncertain answers go to `REVIEW`.** This covers no match, a weak match, two plausible answers with different values, a value that fails validation, disabled controls, attestations, and questions whose labels differ only in a bracketed qualifier but would get the same value. An attestation is wording in which the respondent agrees, consents, declares, certifies, signs, authorises something, or vouches that the form is accurate. It is detected on any control type (checkbox, radio, select, text), in the question, help text, placeholder, section heading or "I agree"-style option labels, and is never answered from the source data. Facts that merely share a word ("Single sign-on", "Payment terms", "Service Level Agreement", "Do you hold ISO 27001 certification?") are not treated as attestations. The detection is wording-based, so it can miss unusual phrasing and can over-flag some yes/no questions; see section 10.
- **Controls it cannot fill are reported, never touched.** These are file uploads, password fields, `contenteditable` regions, custom ARIA widgets (textbox, listbox, slider and similar), and signature-style canvases. They appear under `unsupported` in `result.json`, and a run with any of them is never `FILLED`.
- **Submission is refused** (when `submit=True`) if any answer failed or was never entered, a required item needs review, the page never settled, a multi-step walk stopped early, or any unsupported control is present. A required unsupported control always blocks. An optional one blocks unless a person lists its `ack_id` in `acknowledge_unsupported`. An `ack_id` that is empty or shared by several controls cannot be acknowledged.
- **Multi-step navigation never presses a submit-type button** or a link that leaves the page, and never accepts browser dialogs. After a multi-step walk the final submit step is always skipped.
- **A multi-step walk blocks the browser's network traffic on the channels that were tested. This is not absolute network isolation: some requests can leave the browser before they are detected (see the limits below).** While it walks, the browser context blocks HTTP(S) requests before they are sent, does not forward WebSocket connections, goes offline for what request routing cannot see (this also stops WebRTC STUN traffic to a local listener), and a `SharedWorker` is stopped by replacing its constructor in every frame and, on Chromium, by taking existing ones offline. The whole context goes offline, not just the walked page, and the caller's own offline setting is restored on release. Any blocked attempt stops the walk, is listed in `result.json` under `navigation.blocked_requests`, and keeps the status at `NEEDS_REVIEW`. The block stays on after the run, so a delayed request is also stopped, until you close the browser or call `release_wizard_network_guard(page)` after reviewing. This was checked with a local server that records every request it receives (`tests/web/test_network_guard.py`), including cases where routing alone let requests through. Limits: connections the page opened before the walk are not closed (a WebSocket's messages were dropped in the one measurement), a `SharedWorker` made with a constructor the page kept from before the walk and a `blob:` script can send before the walk notices it (the walk then stops and reports it, but the request is not recalled), a page with a registered service worker is refused, a page that reacts to going offline can stop the walk, and a portal that must contact its server between steps will stop. Details in `docs/OUTPUT_DESIGN.md`.
- **A value shown in the page is not proof of saving.** The tool checks the page, not the server, and never claims a form was saved or submitted successfully unless the page itself shows a confirmation text you supplied.
- Radio and checkbox options that share one value (some pages give every option `on`) cannot be told apart, so they go to `REVIEW`.

## 5. Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.11+ | All code |
| Playwright (Chromium) | Opens pages, reads controls, fills and reads back |
| JSON | Source data and result reports |
| pypdf | The legacy PDF proof of concept only |
| pytest | Automated tests (`reportlab` builds the PDF test fixtures) |
| GitHub Actions | Runs the test suite on pushes to `main` and on pull requests |

There are no machine-learning models, embeddings or external services. Matching is rule-based and deterministic.

## 6. Project Structure

- `formfill/web/` — the web pipeline: `discover.py` (finds controls), `understand.py` and `tokens.py` (read labels), `retrieve.py` (scores answers), `plan.py` (ANSWER or REVIEW), `validate.py` (checks values), `execute.py` (fills and reads back), `steps.py` (multi-step navigation rules), `pipeline.py` (runs everything), `result.py` (report format).
- `formfill/*.py`, `demo.py` — the older PDF proof of concept.
- `tests/` — automated tests; `tests/web/fixtures/` holds small HTML pages used by them.
- `benchmarks/` — fictional RFI forms with expected answers (`rfi/` development set, `heldout/` second set, `spa/` browser fixtures).
- `tools/` — evaluation scripts and `validate_public_form.py`.
- `examples/` — fictional sample data and a local sample RFI page.
- `docs/` — design notes and evaluation reports.

## 7. Setup and Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

Playwright 1.48 or newer is required (the multi-step network block uses WebSocket routing). To use a Chromium you already have, set `FORMFILL_CHROMIUM` to its path. Browser tests are skipped automatically if no browser can be launched, so a run without one reports fewer passes instead of failing. Lint is optional: `pip install ruff` (it is not configured in the project or CI).

## 8. How to Run

All examples use fictional data and local pages.

```bash
python demo_web.py        # fills examples/web/rfi_form.html; never submits unless you add --submit
python demo.py            # the older PDF proof of concept
python -m pytest -q       # the automated tests
```

`demo_web.py` writes `output/web/result.json`, `filled.png` and `trace.zip`. It ends `NEEDS_REVIEW` because the sample page asks questions the sample data does not answer.

To try a page you are allowed to test (never submits; use fictional data only):

```bash
python tools/validate_public_form.py --url https://example.test/form --source my_fictional_source.json \
    [--policy] [--confirm-ms 1000] [--out-dir output/public_validation]
```

Source keys should resemble the form's wording (for example `company.legal_name` for "Legal name"). `--policy` walks multi-step forms with the network blocked (section 4), so a portal that loads its next step from its server will stop at `outbound_request_blocked`; the browser is closed when the tool ends, which ends the block. Use `--confirm-ms 3000` or more on pages that start slowly.

In code: `run_form(page, source, submit=False)` or `run_url(url, source_path, ...)` from `formfill/web/pipeline.py`.

**Source data.** The source is any JSON object holding facts about the company; nesting is fine and keys should resemble the wording of the questions they answer (see `examples/web/rfi_source.json`):

```json
{ "company": { "name": "Acme Corp", "employees": 250, "website_url": "https://acme.example" },
  "security": { "contact": { "email": "security@acme.example" } },
  "certifications": { "iso_27001": true } }
```

A question is answered only when exactly one clearly best key matches and its value passes the control's constraints; otherwise it goes to `REVIEW` with the candidates listed. Add keys for facts you can stand behind. Do not add keys such as `terms_accepted` or `information_accurate` expecting them to be used: attestations are never answered from the source.

**Statuses** (`docs/OUTPUT_DESIGN.md` has the exact rules): `FILLED` (everything answered and verified, nothing submitted), `NEEDS_REVIEW` (a person must act: unanswered or attestation items, an unverifiable answer, an unsupported control, an incomplete walk, a blocked request, or a refused submission), `FAILED` (a fill or read-back failed), `SUBMITTED` / `SUBMITTED_UNCONFIRMED` (only after `submit=True` and every check passed).

## 9. Testing and Evaluation

**Checked on 28 Oct 2026, on `main` at `cf2b71a` (Linux, Python 3.13, Chromium).** Re-run for this README.

### Automated tests (local fixture pages)

- `python -m pytest -q`: **669 passed, 2 expected failures (xfail), 0 failed** in about 6 minutes.
- `ruff check formfill`: no findings. Run on the whole repository (including tools, tests and benchmarks) it reports 21 findings, which are outside the package and not fixed.
- Type checking is not configured and was not run.
- CI (`.github/workflows/tests.yml`) runs `pytest` on Python 3.11. One diagnostic test (`test_probe_hydration.py::test_interval_bounds_contain_the_pages_own_true_interval`) failed once in CI and passed on re-run; its cause was not investigated.

### Fixture-based evaluations (not real websites)

These use fictional forms written by the project. Results show behaviour on those forms only.

| Evaluation | Result |
|---|---|
| Matching, development set (`benchmarks/rfi`, 192 questions) | precision 98.0 %, coverage 52.6 % |
| Matching, second set (`benchmarks/heldout`, 272 questions) | precision 100 %, coverage 39.3 % |
| Multi-step and SPA fixtures (`tools/evaluate_spa.py --policy`, 26 fixtures) | 0 crashes, 0 submit events, 0 submissions, 0 dialogs accepted, 12 of 12 expected safe stops, 3 of 3 planted resets detected |
| Widget fixtures (`tools/evaluate_widgets3d.py`) | 12 of 12 expected fields filled and read back, 3 of 3 conditional fields found |

The table above was measured on `main`, before the multi-step network block existed, and the matching and widget rows were reproduced unchanged on this branch (dev 98.0 % / 52.6 %, second set 100 % / 39.3 %, widgets 12 of 12). The multi-step row was not: with the network block on, the same command (`tools/evaluate_spa.py --policy`) gives 0 crashes, 0 submit events, 0 submissions and 0 dialogs accepted as before, but 11 of 12 expected safe stops, 1 of 3 planted resets detected and 77 of 82 controls discovered. Three fixtures now stop at their first network request or page reload (`wiz_async`, `cond_async`, `nav_reload`) with `outbound_request_blocked`, so later steps are not reached and the planted reset never happens. This is the block working as designed; the fixtures' expected results were not edited to hide it.

To reproduce them (they need `--out-dir` and write nothing into `benchmarks/`):

```bash
python tools/evaluate_baseline.py --out-dir output/eval_dev
python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir output/eval_heldout
python tools/evaluate_spa.py --policy --out-dir output/eval_spa      # multi-step and SPA fixtures
```

"Precision" is the share of answered questions that were correct; "coverage" is the share of expected answers that were filled. The second set was frozen before it was first run, but it has since been used to guide fixes, so it is no longer independent evidence. The evaluation scripts need `--out-dir` and write nothing into `benchmarks/`. Details are in `docs/`.

### Real webpage experiments (run by the project owner; not re-run here)

The development environment cannot reach these sites, so these are reported results, with fictional data and no submission.

- **QA practice form (`qapractice.com`), two runs:** 11 controls; in the later run, 10 answered and 9 verified. One choice (the communication radios, which have no `name`) could not be verified. The run ended `FAILED`.
- **HelloForms vendor-questionnaire template:** a text answer typed right after page load was cleared about 1.5 s later by the page's own framework. In the later full run, 3 answers were verified and the automatic re-entry did **not** trigger, so that recovery is tested on a local fixture only.
- **Selenium demo form (`selenium.dev` web-form):** 11 controls found, plus 2 reported as unsupported (password, file upload). Text, textarea, colour, date and range were filled and verified; the two dropdown questions and the checkbox and radio groups went to `REVIEW`; status `NEEDS_REVIEW`, nothing submitted.

These show the pipeline running on three real pages. They are not evidence that it works on real company portals.

## 10. Current Limitations

- **Not validated on real RFI portals.** Real-page evidence is three public practice or template forms, run by the owner.
- **Detection of unsupported controls is by markup.** A widget built from plain `div`s with no ARIA role, `contenteditable` or canvas is not seen. Disabled unsupported controls are not reported, controls in cross-origin iframes may not be inspected, and a signature canvas without "sign" or "draw" in its label may be missed.
- **Datalist options are not read,** so a datalist box accepts any text; it only receives answers that pass matching.
- **Page behaviour is only partly handled.** Fields that appear well after an interaction can be missed. A reset after the confirmation window is not seen. The one recovery (single re-entry) recognises React/Vue/Svelte patterns only. Next buttons inside shadow roots or iframes are not found, so such multi-step forms stop safely.
- **Final steps are left to a person.** Multi-step runs always stop short of the last submit step. Answers still need human review.
- **Multi-step mode blocks all network traffic, including the portal's own.** A portal that loads the next step or validates a field from its server will stop with `outbound_request_blocked`. This is deliberate, and it means many real portals will not complete a walk. Single-page runs (no policy) have no such block, and filling a field can fire the page's own autosave handlers.
- **The network block has gaps.** It does not claim to block every channel. It cannot close connections the page opened before the walk; a `SharedWorker` made with a constructor the page kept from before the walk and a `blob:` script can send before it is noticed (the walk then stops and reports it); without Chromium's DevTools protocol a `SharedWorker` that already exists cannot be found; WebRTC was tested for STUN to a local listener only, and WebTransport and DNS prefetch not at all; offline emulation is context-wide and can make a page stop the walk; and the measurements were made on Playwright 1.64.1 with its Chromium (the network-guard tests were also run on 1.48.0, which behaves differently in two ways listed in `docs/OUTPUT_DESIGN.md`). A caller's browser context should be created with `service_workers="block"` (`run_url` does this).
- **Attestation detection is wording-based.** A genuine attestation phrased in a way the patterns do not cover, on a free-text or number field, is answered like any other question; and some factual yes/no questions with unusual wording may be sent to review. The regression cases were written by the project, so they are not evidence about real portals.
- **Saving is not confirmed.** A correct read-back does not prove the server stored the value.
- **Matching is limited by design.** Word-overlap rules abstain often (coverage is about half on the fixture sets), and a correct fill is only as good as the source data. Matching may still pick a wrong value in untested wording.
- **No logging module.** Runs are explained through `result.json` and its warnings.
- **Legacy PDF code** is a small proof of concept and is not part of the web pipeline.

## 11. Future Improvements

- Read datalist options and use them for validation.
- Validate on more real, permitted forms, and with an independently written test set.
- Support more custom widgets and navigation inside shadow roots and iframes.
- Add a reviewed final-step policy so a person can approve submission explicitly.
- Configure linting and type checking in CI.
