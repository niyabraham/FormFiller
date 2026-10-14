# Phase 3D: widget commitment and verification

Base: Phase 3C commit `1d1dbd0` (branch `phase3d-widget-commitment`; code commit `5f0b4cf`). Investigation baseline: a public-demo validation report (SurveyJS, SauceDemo; kept outside the repository).
Local, generic SurveyJS-compatible fixtures only. **This says nothing about the reliability of any real portal.**

## Design (all in `formfill/web/execute.py`; discovery, retrieval, planning, navigation untouched)
1. **Blur-commit.** After every text-like `fill()` the field is blurred (a real focus change) and the DOM is allowed to go quiet
   (<=1.5 s cap, 120 ms quiet window). Frameworks that commit on blur then update state and render conditional questions, which
   the existing round loop discovers. A DOM value is evidence of what the page holds, **not** proof the app recorded it; the
   pipeline cannot see app state, so app-state commitment is reported only where a fixture publishes `window.__state`.
2. **Readonly combobox.** Detected (`readOnly`/`aria-readonly`) before `fill()`. Opened as a person would: click the point where it
   is drawn (a cover element takes the pointer), then focus + ArrowDown. The option is clicked, then `aria-expanded` and the shown
   value are verified. If neither opens a list: `unsupported readonly combobox ...` after <=3 s instead of a 5 s `fill()` timeout.
3. **Styled radio.** If the native input is hit-testable it is `check()`ed as before; otherwise its accessible `<label>` is clicked and
   `checked` verified. No JavaScript value setting. No label: clear "unsupported styled radio" error.

## Evidence (`benchmarks/spa/results/phase3d/`)
| | fill ok | DOM read-back | app state | conditional found+filled |
|---|---|---|---|---|
| 3C (before) | 3/5 | 3/5 | 2/5 | 1/1 (DOM ok, **app state not committed**) |
| 3D (after) | 5/5 | 5/5 | 5/5 | 1/1 (committed) |
Before: readonly combobox and styled radio each burn the full 5 s timeout. Failure-mode fixtures: `?mode=revert` (app clears the field on
blur) is reported unverified; `?mode=dead` (list never opens) stops with a clear reason in ~3 s.
Non-regression: 26 SPA fixtures identical (only settle-ms jitter); dev 195/195 and held-out outcomes unchanged (dev still has its 1 disputed
unsafe answer); `demo.py` PASS; `demo_web.py` output identical apart from ids/timestamps; suite 398 passed, 2 xfailed (391 + 7 new).

## Remaining limitations
- Checkbox/checkbox-group styled like radios are not given the label path (out of scope; same fix would apply).
- Blur is applied to every text-like fill in default mode too; a page that validates/rewrites on blur will now do so (verification reports it).
- Custom comboboxes that open only on hover/other gestures, or filter-as-you-type readonly lists, are reported unsupported.
- Shadow-root/iframe navigation-button search and the repeated "no longer in the DOM" note are unchanged (out of scope).
- App-state commitment is unmeasurable on real sites; only DOM read-back is available there.

## Review round 2 (evidence in `benchmarks/spa/results/phase3d_review_round2/`)
**Guarded readonly-combobox open** (`execute.py::_open_readonly_combobox`, `_CLICK_TARGET_JS`). Before any click the element at the combobox centre is
hit-tested. The click goes ahead only if that element is the combobox, a wrapper containing it, or a wrapper in its immediate container that holds no
other control. Buttons, links, tabs, other inputs/selects/textareas, `[tabindex]` elements, form/body-level wrappers, or nothing, are refused: nothing is
clicked and the keyboard path (focus + ArrowDown) is tried; if that fails the error says `click refused: <why> (<target>)`. No JavaScript sets widget state.
Fixtures: `w3d_readonly_combobox.html` (decorative wrapper: click path), `?mode=overlap` (Submit button over the centre), `?mode=overlap_nav`
(Continue button), `?mode=overlap_dead` (button + no keyboard support). Mutation check: with the guard disabled the overlap fixtures record 1 click
(and 1 submit event); with it enabled 0.
**Delayed conditional rendering and honest settling.** `_commit` now distinguishes reaching the 150 ms quiet window from hitting the 1500 ms cap.
The cap case returns a warning; `_fill_one` stores it in the item's `detail`, `run_form` adds a `RunResult.warning`, the status becomes `NEEDS_REVIEW`
(never `FILLED`) and `submit=True` is skipped. Normal pages that go quiet promptly produce no warning (asserted in 3 fixtures × 2 modes).
Fixtures: `w3d_blur_commit.html` (synchronous reveal), `?mode=delay` (no email field, so the name is the last answer; city appears 60 ms after the commit;
with the quiet window cut to 20 ms the city is missed, with 150 ms it is found), `?mode=churn` (ticker every 30 ms: unsettled).
Limit: a reveal that starts later than 150 ms after the blur is not waited for in default mode.
**Policy mode.** Readonly-combobox, styled-radio, blur, delayed-reveal and ordinary/controlled/combobox tests run with `policy=None` and
`DiscoveryPolicy()`; they check matching/fill/DOM read-back/app state where exposed, and no submission side effect. Exceptions: `?mode=churn`
(policy mode would stop `page_not_settled` by design) and the `overlap_nav` button (a policy walk may legitimately press a button labelled Continue).
**Provenance.** Both evaluators now use `tools/_provenance.py` (recipe `formfill-src-v2`). Earlier outputs used `v1a` (SPA) / `v1b` (widget), the same diff
with/without a trailing newline; they are left as recorded.
**Wall-clock assertion removed.** The unsupported-combobox test now asserts our own error text and the absence of a Playwright "Timeout", not elapsed time.

## Final verification (commit `5f0b4cf`; `benchmarks/spa/results/phase3d_final_verification/`)
Fresh run on the committed tree: `python -m pytest -q` 415 passed, 2 xfailed; `demo.py` PASS; `demo_web.py` identical to Phase 3C apart from ids/timestamps;
widget evaluation 12/12 fill, 12/12 DOM read-back, 12/12 fixture app state, 0 side effects on planted overlay controls, unsettled page flagged only on the churn fixture;
26 SPA fixtures identical to Phase 3C (0 submit events, 0 submission attempts); dev 195/195 and additional-set 276/276 outcomes unchanged.
Dev and additional-set outputs do not record commit/hash; their provenance is asserted in that directory's `PROVENANCE.json`.
