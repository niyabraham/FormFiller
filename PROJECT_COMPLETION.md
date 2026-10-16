# FormFiller — project completion record

Single source of truth for what the project is, what was verified, and what remains. Everything marked **verified** was run on the
working tree described in section 3; nothing here is copied from earlier sessions without saying so.

## 1. Objective and supported scope

Fill business RFI questions on **DOM-based web forms** (including supported SPA forms and multi-step wizards) from a **JSON file of
company data**, in **English**, with Playwright. Every entered value must trace to a source path; anything unsupported, ambiguous,
unsafe or unverifiable is left for a person. **FormFiller never submits**: final submission is a human action.

Supported: text/textarea/number/date/email/url/tel inputs, standard selects, radios and checkbox groups (native and label-styled),
multi-selects, ARIA comboboxes (incl. readonly), open shadow DOM, iframes, conditional reveals, wizard navigation by safe Next
buttons (opt-in `--wizard`). Not supported (reported, never guessed): file uploads, canvas/closed-shadow widgets, non-English forms,
CAPTCHAs, login flows, Next buttons inside shadow roots/iframes, anything needing a server round-trip to validate.

## 2. Definition of done and final status

| # | criterion | status | evidence |
|---|---|---|---|
| 1 | documented end-to-end workflow runs | **met** | `python -m formfill fill ...`, `demo_web.py`, CLI subprocess tests |
| 2 | JSON loading/normalisation as documented | **met** | `formfill/web/source.py`, `tests/web/test_cli_report.py` (invalid JSON, non-object, empty, placeholders, repeated names) |
| 3 | semantic retrieval handles paraphrases, measured | **met within a stated boundary** | section 6: held-out v2 paraphrase 40/61 answered, 0 wrong-source answers; remaining paraphrases go to REVIEW |
| 4 | unsupported/ambiguous handled conservatively | **met, with known exceptions** | held-out v2: 1 unsafe of 105 (label defect); `seen` set: 2 open; `benchmarks/rfi`: 1 disputed (section 6.4, 9) |
| 5 | scope/polarity/period/population/type validated | **met** | caps in `retrieve.py`, `validate.py`; 217+ unit tests; benchmark categories scope/negation/type |
| 6 | provenance retained | **met** | `source`, `raw_value`, `evidence`, `alternatives` per item in `result.json` |
| 7 | supported controls fill and verify | **met on local fixtures** | widgets 12/12, SPA 79/115 fills with the rest being deliberately unsupported/review fixtures |
| 8 | SPA/wizard behaviour tested within boundary | **met on local fixtures** | 26 SPA fixtures, 12/12 safe stops, 82/82 discovery recall |
| 9 | final submission stays human | **met** | no submit code path exists (section 5); 0 submit events / 0 submissions in every run |
| 10 | reports describe what happened | **met** | outcome taxonomy, `human_submission`, `not_asked`, redaction |
| 11 | regression, lint, types, demos run | **met** | section 7 |
| 12 | docs match implementation | **met** | README, `docs/OUTPUT_DESIGN.md`, this file |
| 13 | limitations explicit, no known critical defect in scope | **met with caveats** | section 9. **No real external portal has ever been tested.** |

## 3. Starting point and working tree

- Repo `https://github.com/niyabraham/FormFiller`, cloned fresh; branch `main` @ `4ffe03be74634932215fc4e3edb876beb33fd7ac`
  (merge of PR #1, Phase 3D). Remote branches: `heldout-evaluation`, `phase3a-retrieval-hardening`, `phase3b-parent-sibling-scoring`,
  `phase3c-spa-browser-reliability`, `phase3d-widget-commitment` (@ 08eb455, already merged into main via PR #1).
- All work is **uncommitted** on top of that commit (nothing committed, pushed, merged or opened as a PR). `git diff` is the review diff.
- Chromium: Playwright's download host is blocked in the sandbox; a pre-installed build at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`
  was used through `FORMFILL_CHROMIUM`.

## 4. Baseline before any change (verified)

| check | result |
|---|---|
| `pytest` | 415 passed, 2 xfailed (158.6 s) |
| `ruff` (ruff 0.17 defaults; repo had no ruff config) | 10 findings |
| `demo.py`, `demo_web.py` | PASS / NEEDS_REVIEW as designed |
| dev benchmark (`benchmarks/rfi`, 195 q) | 102 auto-answered, 100 correct, 1 unsafe (disputed label), coverage 53.1 % |
| additional set (`benchmarks/heldout`, 276 q) | 107 auto-answered, 107 correct, 0 unsafe, coverage 39.3 % |
| semantic dev / seen / held-out v2 (new, same code) | 48 / 35 / 43 correct; 2 / 4 / 4 unsafe |

## 5. Material defects found and what was done

1. **Automatic submission existed.** `run_form(submit=True)`, `execute.submit()`, `demo_web.py --submit`, and a
   `DiscoveryPolicy(allow_submit_type_navigation=True)` opt-in that could click a form submit control. **Removed entirely**: the parameters no
   longer exist (a `TypeError` test pins that), submit-type and off-page "Next" controls are always refused before any click, and the report
   carries `human_submission` (`performed_by_formfill: false`, `ready_for_human_review`, `blockers`). Statuses `SUBMITTED*` are gone.
   Residual risk (documented in `pipeline._run_steps`): a "Next" button that performs a script-driven submission cannot be told from a real
   Next before the click.
2. **Retrieval was keyword-overlap only.** "workforce size", "people working in the company", "head office", "electronic logging devices" (`eld`) all
   went to REVIEW. See section 6.
3. **Tokeniser bug:** `"company's"` became `company` + `s` (found by testing the user's own `employee_count` example).
4. **Safety gaps found by the new benchmarks, all fixed with tests:** status negations (`lapsed`, `expired`, `revoked`, ...) were not polarity markers;
   two different standard numbers ("ISO 9001" vs `iso_13485_certified`) matched; ambiguity compared only the runner-up, so a same-valued runner-up hid a
   differently-valued rival; a candidate whose only hit was the word "company" scored.
5. **Styled checkboxes** (hidden input under a decorator) timed out; now set through their label, which is refused if it contains a link/button.
6. **Reporting was coarse:** no per-question outcome, no list of never-asked controls, no way to separate DOM from client-state verification, values in
   logs. Added `outcome`, `not_asked`, optional `state_reader`, `--redact`.
7. **Quality gates were not reproducible:** added explicit `[tool.ruff]` / `[tool.mypy]` config and cleared all findings.

## 6. Semantic question understanding and retrieval

### 6.1 Architecture (simplest thing that measurably works)

```
question text ──tokenize (+closed phrase table, possessives, stopwords)──► question tokens, is_count, period
JSON source   ──index_source──► leaves (dotted path, value, key tokens, parent tokens, list-item context)
for every (question, leaf):
   align(question tokens → this key's words)      # semantic.py: soft, weighted, evidence-recording
   score  = F1(precision, recall) [+ section bonus] × weakest soft-match weight
   caps   = scope word, counting modifiers, polarity, period, identifier conflict, unexplained fraction   (retrieve.py)
   context= parent / sibling / ancestor evidence demotes rivals the question does not name                   (retrieve.py)
plan: best score ≥ 0.6, margin ≥ 0.15 over EVERY rival holding a different value, not a placeholder, passes type/option/range validation
      attestation/consent boxes are always REVIEW
```

Alignment mechanisms (`formfill/web/semantic.py`, each switchable for ablation): derivational **stems** (certification/certified; but never
across tense, so "opening" ≠ "opened"), a closed **lexicon** (`formfill/web/lexicon.json`: 12 synonym groups, 8 phrases; look-alike words such as
employer/employee are tested to stay apart), **initialisms** (electronic logging devices → `eld`, in both directions), **abbreviations**
(≥ 3-letter prefixes), **compounds** (`usdot` ~ `dot`), and a pluggable `TermProvider`. A soft match scores 0.85–0.95 of an exact one, so exact
always outranks soft, and the link is written to `evidence` for the reviewer. Counting questions treat measure words (count/number/size/total) as
implicit on both sides, without adding words to the question (adding them diluted the safety check and was removed after it produced an unsafe answer).

**No embeddings, LLM or vector DB are used, by decision.** Reasons: (a) the model hosts are blocked in this environment, so none could be obtained or
evaluated; (b) the measured failures were morphological/lexical, which the closed layer fixes without a dependency, privacy cost or nondeterminism;
(c) a similarity score is not an acceptance criterion in any case. The `TermProvider` hook is the integration point. I did measure the one resource that
was obtainable, WordNet 3.0 from PyPI (`tools/wordnet_provider.py`, ablation only): **+0 correct on dev and held-out v2, +3 on the seen set, 0 added
unsafe**, so it is not shipped. An embedding provider is **untested**; it would need an offline model and its own held-out evaluation.

### 6.2 Datasets (never compared as if equivalent)

| set | questions | role |
|---|---|---|
| `benchmarks/rfi` | 195 (browser) | Phase 2 development benchmark |
| `benchmarks/heldout` | 276 (browser) | earlier additional set, frozen 2026-10-10; its own docs call it development evidence |
| `benchmarks/semantic/dev.json` | 121 (no browser) | development for the semantic layer |
| `benchmarks/semantic/seen.json` | 141 | written first, but its baseline failures were read while writing the lexicon: **contaminated, treated as development** |
| `benchmarks/semantic/heldout.json` | 105 | held-out v2: written after tuning, new domains, digest frozen (`FROZEN.txt`) before its first run. **Same author as the code; no independent annotator.** |

### 6.3 Results (verified; "before" = untouched `main`, same evaluator)

| set | before: correct / unsafe | after: correct / unsafe | precision | coverage |
|---|---|---|---|---|
| semantic dev | 48 / 2 | **59 / 0** | 100 % | 77.6 % (was 63.2) |
| semantic seen | 35 / 4 | 48 / 2 | 96.0 % | 44.4 % (was 32.4) |
| **semantic held-out v2, first run** | 43 / 4 | **50 / 3** | 94.3 % | 68.5 % (was 58.9) |
| semantic held-out v2, after fixing what it exposed (2 fixes: status negations, then crossed count modifiers) | – | 50 / 1 (no longer clean; tuned after seeing it) | 98.0 % | 68.5 % |
| `benchmarks/rfi` (195) | 100 / 1 | 106 / 1 (same disputed one) | 98.1 % | 56.2 % (was 53.1) |
| `benchmarks/heldout` (276) | 107 / 0 | 119 / 0 | 100 % | 43.8 % (was 39.3) |

Both older benchmarks: **0 regressions** (`final_verification/compare_*_vs_start.md`). Alignment alone (all other changes kept) is worth +3 correct on
held-out v2; WordNet adds 0 on top.

### 6.4 What is still wrong (held-out v2, 1 unsafe of 105)

- `City` is expected REVIEW but the source has a single city key: a **label defect** (kept, frozen; arguably correct to answer).
- "How many regulatory inspections have you passed?" → `quality.gcp_inspections_passed` was a second unsafe answer. **Fixed in the stabilization pass**:
  in a *counting* question, when the question carries a modifier the key does not have **and** the key carries a modifier the question does not
  name (`regulatory` vs `gcp`), the two count different populations and the score is capped to REVIEW. "How many GCP inspections ..." is still answered.
  Spelled-out numbers equal their digits ("last five years" = `last_5_years`), which a first version of the rule got wrong (caught on the `seen` set).
  Tests: `tests/web/test_semantic.py` (last three). This fix was made *after* seeing the held-out failure, so held-out v2 is no longer a clean estimate; the first-run
  row in 6.3 is the honest one. The rule covers counting questions only: the same shape in a non-count question is not guarded beyond the generic checks.
- The first run also exposed the missing status-negation words (fixed, tested).
- 23 of 73 answerable questions are still REVIEW (safe misses), mostly paraphrases outside the closed vocabulary ("How big is your workforce?"),
  or qualifier words the key does not carry ("Registered company name" vs `legal_name`, "Annual turnover" vs `turnover_gbp`). By design these stay REVIEW.
- The `seen` set still has 2 unsafe (a wrong-source paraphrase "Name of your bankers" → `contractor.name`, and a conflicting `business.employees` vs
  `hr.total_employees` case). Neither was addressed: they are development-set findings left open and listed here.

## 7. Final verification (verified on the working tree; outputs in `benchmarks/final_verification_stabilization/`; the earlier `benchmarks/final_verification/` run predates the counting-question fix and the SPA/widget runs there were not repeated, since no browser code changed afterwards)

```bash
pip install -e ".[web,dev]" ruff mypy        # + a Chromium build; export FORMFILL_CHROMIUM=/path/to/chrome if Playwright's is unavailable
python -m pytest -q -p no:cacheprovider      # 480 passed, 2 xfailed (173.1 s)
ruff check .                                 # All checks passed
mypy                                         # Success: no issues found in 23 source files
python demo.py                               # Final verification: PASS (legacy PDF path)
python demo_web.py                           # NEEDS_REVIEW by design (2 REVIEW items), 9 verified_dom, submission not performed
python tools/evaluate_baseline.py --out-dir <new dir>                          # 195 q
python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir <new dir>   # 276 q
python tools/evaluate_spa.py --policy --out-dir <new dir>                      # 26 SPA fixtures
python tools/evaluate_widgets3d.py --out-dir <new dir>                         # widget fixtures
python tools/evaluate_semantic.py --split dev|seen|heldout --out-dir <new dir>
python tools/compare_runs.py <before>/baseline.json <after>/baseline.json --out <file>
```

The 2 xfails are the two pre-existing disputed-label cases (company vs subsidiary employees), unchanged.

| run | result |
|---|---|
| `benchmarks/rfi` / `benchmarks/heldout` (rerun on the final tree) | 106/108 correct, 1 unsafe (disputed label), coverage 56.2 % / 119 correct, 0 unsafe, coverage 43.8 % (identical to before the fix) |
| semantic dev / seen / held-out v2 (final tree) | 59/0 · 48/2 · 50/1 (correct/unsafe) |
| widget fixtures | 12/12 fill, 12/12 DOM read-back, 12/12 app state, conditional 3/3 (unchanged from Phase 3D) |
| SPA fixtures (policy mode) | discovery 82/82, fill 79/115, DOM read-back 76/115, app-committed 76/115, **submit events 0, submissions 0**, safe stops 12/12 (unchanged from 3D) |
| `tools/evaluate_baseline.py` submission cases | re-expressed as "ready for human review / left unsubmitted": 7/7 OK (their old CONFIRMED/UNCONFIRMED outcomes required a click) |

These are **local-fixture results only**. Real external portal results: **none**.

## 8. Outputs (confirmed by `tests/web/test_cli_report.py` and a real run)

`python -m formfill fill --source company.json --url <url|file.html> --out-dir DIR [--wizard] [--redact] [--strict]` writes to `DIR/`:

| file | meaning |
|---|---|
| `result.json` | full report: `status`, per-item `plan` (source, raw_value, answer, confidence, reason, alternatives, evidence), `outcome`, `observed`, `app_state`, `server_persistence`, `human_submission`, `not_asked`, `warnings`, `navigation`, `summary` |
| `filled.png` | full-page screenshot of the filled page (not written with `--redact`) |
| `trace.zip` | Playwright trace for `playwright show-trace` (not written with `--redact`) |

No HTML output file is generated: the form is filled in the live page. Per-question `outcome`: `needs_review` · `failed` · `unverified` ·
`verified_dom` · `verified_client_state` (only when a caller passes `state_reader`). `server_persistence` is always `not_checked`: nothing is submitted.
Run `status`: `FILLED` (all answered and read back) / `NEEDS_REVIEW` / `FAILED`; a walk that stops early or an unsettled page is never `FILLED`.
`--redact` replaces company values (raw, answer, observed, alternatives, values quoted in reasons) with `[redacted]` and skips screenshot and trace.
Other commands: `ask` (which source value answers this question; no browser) and `check-source`. Exit codes: 0 ran, 1 `--strict` and not ready, 2 usage, 3 source error, 4 browser error.

## 9. Known limitations and blockers

- **No real portal has been tested.** All browser evidence is from local fixtures written by the same engineer. Real-portal reliability is unknown.
- Client-side state verification needs a caller-supplied `state_reader`; without one only the DOM is checked. Server-side persistence is never verified.
- Page-side blur handlers, reveals later than ~150 ms after a field blur (default mode), Next buttons inside shadow roots/iframes, and non-English forms are unsupported or untested.
- A script-driven submission hidden behind a normal-looking "Next" button cannot be detected before the click (section 5.1).
- Test sets are **author-written** by the same engineer who wrote the code; none is independently validated. Held-out v2 has one author, was authored after the layer was designed, and is not clean after its first run; treat its first-run numbers as the honest estimate, and all
  figures as development evidence rather than proof of generalisation.
- Dates other than ISO, "£2.4m", "six" and similar are REVIEW by design (no unit/currency parsing).
- Embedding-based retrieval is untested.
- The disputed development label (company vs subsidiary employees) still produces 1 unsafe answer on `benchmarks/rfi`; "zero unsafe answers" is **not** claimed anywhere.
- Environment blocker: Playwright's own browser download is blocked here; not a project defect.

## 10. Key files

`formfill/web/`: `pipeline.py` (orchestration), `discover.py`, `understand.py`, `tokens.py`, `semantic.py` + `lexicon.json` (alignment), `retrieve.py` (scoring, caps,
context), `plan.py` (decision), `validate.py`, `execute.py` (Playwright), `steps.py` (wizard navigation), `result.py` (report), `source.py` (loading), `cli.py`.
Tests: `tests/web/` (browser tests marked `browser`; skipped when Chromium is unavailable). Tools: `tools/evaluate_*.py`, `tools/compare_runs.py`.
Historical results (`benchmarks/*/results`, `docs/PHASE*.md`) are preserved unchanged and describe the pre-completion state, including the removed submit path.
