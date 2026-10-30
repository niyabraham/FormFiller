# Compatibility matrix

What FormFiller does with common form patterns, and how each claim was checked. **Fixture results and real-page results are
kept apart:** a fixture is a page written for this project, so it shows behaviour on that pattern, not on any named portal. No
real company RFI portal has been tested.

Environment for every fixture row: Windows 11, Python 3.12, Playwright 1.64.1, Chromium 156, with the suite also run on Linux
(Ubuntu 24.04 under WSL), Python 3.11; see `docs/PROGRESS.md` for the latest counts. Tests run headless.

Outcomes: **supported** (filled and read back); **review** (left for a person, with the reason); **reported** (listed under
`unsupported`, never touched; a run that has one is never `FILLED`); **stops** (the walk ends safely, with a stop reason);
**not supported** (FormFiller does not see or handle it; the gap is pinned by a test where one exists).

## Single-page patterns (local fixtures)

| pattern | controls | outcome | limitations | evidence |
|---|---|---|---|---|
| plain HTML form | text, textarea, email, url, tel, number, date, select (single, multiple), radio groups, checkbox, checkbox groups, colour | supported | values must pass the control's constraints, or the item goes to review | `test_browser.py`, `test_retrieve_plan.py`, `test_color_input.py`; `benchmarks/rfi` (192 questions), `benchmarks/heldout` (272) |
| React-style controlled inputs | text, select | supported (events dispatched so app state commits) | checked against `window.__state` in fixtures only | `test_spa_browser.py::test_controlled_inputs_commit_to_app_state`, `test_widgets_3d.py` |
| framework hydration that wipes a typed value | text | supported: one re-entry, reported | React/Vue/Svelte evidence only; a second loss is a failure | `test_hydration_reentry.py` |
| Vue-style state bound to `input`/`change` events | text, select, number, checkbox | supported | no real Vue or Angular build tested | `test_compatibility.py::test_vue_style_...` |
| fields revealed by an earlier answer (sync and async) | any supported | supported (found in a later discovery round) | a reveal that needs a server request stops a guarded walk | `test_browser.py::test_conditional_field_appears_after_its_trigger_is_answered`, `test_spa_browser.py::test_conditional_async_control_found_after_answer` |
| form rendered late by JavaScript, or in an iframe that appears late | any supported | supported (waits up to `readiness_timeout_ms`) | later than the timeout: not seen | `test_browser.py::test_pipeline_waits_for_delayed_javascript_form`, `test_compatibility.py::test_a_form_that_renders_late...` |
| validation that marks a field invalid after filling | text | rejected (state `rejected`, run `FAILED`), listed under `invalid` | the page's own rules are not predicted | `test_compatibility.py::test_a_field_the_page_marks_invalid...` |
| labels by `aria-labelledby`, `aria-label`, wrapping `<label>`, `title` | text, email, tel, url | supported | - | `test_compatibility.py::test_unconventional_labels...` |
| text in a nearby `<div>` with no association | text | review (the question is the control's name; nothing matches) | not inferred from layout | same test |
| the same question in several sections (primary / billing contact) | text, email | supported when the source distinguishes them (section context); otherwise review | listed as duplicates for the reviewer | `test_compatibility.py::test_repeated_question_blocks...` |
| dates in a shown format (DD/MM/YYYY), number ranges, min/max dates | date, text, number | supported; outside the constraints: review, nothing forced | ambiguous format hints are not guessed | `test_compatibility.py::test_dates_and_numbers...`, `test_format_hints_and_choice_interference.py` |
| ARIA combobox (editable, read-only, overlapping buttons) | combobox | supported for the tested patterns; unopenable list: safe stop | other combobox implementations untested | `test_spa_browser.py::test_comboboxes_pick_options_not_just_type`, `test_widgets_3d.py` |
| styled radio (hidden input, clickable label) | radio | supported (label click, never forced) | - | `test_widgets_3d.py::test_styled_radio_selected_through_label_not_forced` |
| options sharing one value (`on`) | radio, checkbox | review | cannot tell options apart | `test_duplicate_option_values.py` |
| hidden copies of fields (`aria-hidden`, `inert`, honeypots) | any | hidden ones ignored, never touched | - | `test_hidden_duplicates.py` |
| the site's own search / filter box (lone control or search-type box in nav, header, footer, aside, outside any form) | text, search | not a question: not asked, never typed into | a lone, form-less questionnaire control placed inside a landmark would be missed | `test_page_furniture.py` (RW-2) |
| open shadow DOM, same-origin iframe | any supported | supported | - | `test_spa_browser.py::test_open_shadow_and_iframe_found_closed_shadow_reported`, `test_browser.py::test_iframe_control_is_filled` |
| closed shadow root, cross-origin iframe | - | reported / not inspected | contents cannot be read | same tests; README limitations |
| file upload, password, `contenteditable`, signature canvas, custom ARIA textbox / listbox / slider | - | reported, never touched | a canvas without "sign"/"draw" wording may be missed | `test_unsupported_controls.py` |
| dropdown built from plain `<div>`s with no ARIA role | - | not supported: not seen, nothing clicked | invisible to discovery | `test_compatibility.py::test_a_dropdown_built_from_plain_divs...` |
| `<datalist>` suggestions | text | filled as text; options not read | any text is accepted | README limitations |
| attestations, consents, declarations, signatures | any | review, never answered | wording-based detection | `test_attestation_detection.py`, `test_browser.py` |

## Multi-step patterns (local fixtures and a 127.0.0.1 server)

| pattern | navigation | outcome | limitations | evidence |
|---|---|---|---|---|
| client-side wizard, 4 sections, conditional field, required validation | Next (allow-listed labels) | supported; stops before the declaration for a person | final step never submitted | `test_wizard_navigation.py`; `tools/evaluate_wizards.py` (16 scenarios) |
| Back re-verification of earlier answers | Back, then Next | supported (opt-in `revisit_with_back`); a lost value is `rejected` | client-side wizards only | same |
| loop, Next that changes nothing, validation messages after Next, redirect to another origin | - | stops with `navigation_loop`, `no_change_after_next`, `validation_error_after_next`, `unexpected_redirect` | - | same; `test_wizard_navigation.py::test_transition_classification_table` |
| server-backed single-page app (sections from an API, optional autosave) | Next + relayed API calls | stops at the first request by default; supported with explicit allow rules; an autosave carrying answers needs `answer_data=True` | rules must name the exact origin and path | same; `docs/SECURITY_MODEL.md` |
| server-rendered wizard (form POST per step, post/redirect/get) | submit-type Next | refused by default; supported with a `form_navigation` rule; the final "Submit" is never pressed | each redirect hop must match a rule | same |
| save and resume (portal keeps a draft) | - | supported with a progress file: values are matched by control and read back; a changed value goes to review | same origin and path only; 72-hour limit by default | `test_progress_resume.py` |
| unfamiliar Next labels ("Onward") | - | stops (`no_safe_next_control`); a visible Submit is never pressed | labels outside the allow list are never guessed | `test_spa_browser.py::test_unfamiliar_next_label_with_submit_true_is_skipped` |
| Next inside a shadow root or iframe | - | not found, so the walk stops (by design: the Next search covers the main document only) | no test pins this case | `formfill/web/steps.py` docstring |
| login, single sign-on, CAPTCHA, payment pages | - | not supported, never bypassed | - | `docs/SECURITY_MODEL.md` |
| page with a registered service worker | - | refused before anything is touched (guarded walk) | - | `test_network_guard.py` |

## Real pages (fictional data, nothing submitted)

| page | when / who | result | status |
|---|---|---|---|
| Selenium's public test form (`selenium.dev/selenium/web/web-form.html`) | 29 Oct 2026, this branch, `tools/validate_public_form.py` | 11 controls; text, textarea, colour, date and range filled and verified (5); both dropdowns and the checkbox and radio groups in review; password and file upload reported, not touched | `NEEDS_REVIEW`, nothing submitted (same outcome as the owner's earlier run) |
| QA practice form (`qapractice.com`) | earlier, by the project owner, not re-run | 10 answered, 9 verified; a radio group without `name` not verifiable | `FAILED` |
| HelloForms vendor-questionnaire template | earlier, by the project owner, not re-run | a value cleared by the page's framework 1.5 s after typing; 3 answers verified; re-entry did not trigger | - |

These pages are practice and template forms. None is a company RFI portal, and none required a login or a multi-step walk.
