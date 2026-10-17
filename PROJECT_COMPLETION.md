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
| 4 | unsupported/ambiguous handled conservatively | **met, with known exceptions** | held-out v2: 1 unsafe of 105 (label defect); `seen`: 2 open; `benchmarks/rfi`: 1 disputed; v3: 4 found and fixed (6.4, 6.6, 9) |
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
unsafe**, so it is not shipped. An embedding provider was later evaluated once a local copy of the model was supplied: see 6.5. Result: **inconclusive, not shipped**.

### 6.2 Datasets (never compared as if equivalent)

| set | questions | role |
|---|---|---|
| `benchmarks/rfi` | 195 (browser) | Phase 2 development benchmark |
| `benchmarks/heldout` | 276 (browser) | earlier additional set, frozen 2026-10-10; its own docs call it development evidence |
| `benchmarks/semantic/dev.json` | 121 (no browser) | development for the semantic layer |
| `benchmarks/semantic/seen.json` | 141 | written first, but its baseline failures were read while writing the lexicon: **contaminated, treated as development** |
| `benchmarks/semantic/dev_defects.json` | 50 | development fixtures for the three safeguards in 6.6 (written after diagnosing v3, different domains and wording; safe to tune against) |
| `benchmarks/semantic/heldout_v3.json` | 122 | **fresh held-out v3**: six new domains, written and frozen (`FROZEN_v3.txt`, digest `7cba9bef43a3b84d`) before any embedding code existed; never used to choose a threshold or rule. Same author as the code, not independently annotated |
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

### 6.5 Local embedding experiment (all-MiniLM-L6-v2): inconclusive, not retained

**Setup (verified).** The model files were supplied by the user (nine small files in a ZIP, `model.safetensors` as four 7-Zip volumes) and loaded
from a local directory with `local_files_only=True`, offline flags set and sockets blocked (0 connection attempts); dimension 384.
**The weights' SHA-256 (`53aa5117...d9db`) was computed but NOT compared with the official Hugging Face value**, which could not be fetched. Provenance of the
weights is therefore unverified.

**Integration tried** (kept as `benchmarks/embedding_experiment/embedding_integration.patch`, not applied): an optional `TermProvider` that scored word pairs
by cosine similarity, vetoed scope/negation/period words, required a mutual-best link, applied a reduced weight, recorded evidence, and left every cap and the
ambiguity rule in force. Off unless `FORMFILL_EMBEDDING_MODEL` named a complete local directory; missing directory or packages fell back to the baseline
matcher (both fallbacks tested by hand). Optional extra: `sentence-transformers` (pulls `torch`).
**Threshold 0.60** was chosen on `dev` and `seen` only (the lowest value with no regression there).

| set | role | baseline correct / unsafe | embedding correct / unsafe |
|---|---|---|---|
| semantic dev (121) | tuning | 59 / 0 | 60 / 0 |
| semantic seen (141) | tuning | 48 / 2 | 49 / 1 |
| semantic held-out v2 (105) | evaluation (already tuned against earlier) | 50 / 1 | 50 / 1 |
| **semantic held-out v3 (122)** | fresh evaluation | 48 / 4 | 49 / 4 |
| `benchmarks/rfi` (195, browser) | fixed | 106 / 1 | 106 / 1 (+1 "data centers", **-1** "date of last penetration test" -> REVIEW) |
| `benchmarks/heldout` (276, browser) | fixed | 119 / 0 | 119 / 0 (+1 "expiration date", **-1** "stored outside the EU" -> REVIEW) |

Unsafe answers never increased on any set. Every gain was a spelling or morphology variant (employ~employee, requesting~requested, banker~bank, centers~centres,
expiration~expires), which a deterministic rule can cover; the two browser sets show a gain and a loss each. The hard categories did not move: v3's
conflicting-count and scope failures, and its 38 safe misses, were unchanged. **Decision: inconclusive, baseline kept**; the integration is not in the tree.
Runtime cost when it was on: a torch + model import of about a second and roughly 0.5 GB RAM per process, and a new heavy optional dependency.

**What fresh held-out v3 showed about the baseline** (diagnosed and fixed afterwards with separate development fixtures; see 6.6, which also says why v3 is no longer a clean estimate).
Baseline first run: 52 answered, 48 correct, **4 unsafe**, precision 92.3 %, coverage 55.8 % (`benchmarks/semantic/results/heldout_v3_baseline_first_run/`).
- "How many employees does the business have?" -> `parent_company.employees` and "Name of the company" -> `parent_company.name`, where a parent and a
  subsidiary both hold a value: **conflicting-value defect**, the ambiguity rule does not fire because the parent's key scores higher through the word "parent"
  in the path. This is the same family as the disputed company/subsidiary label, and it is real.
- "Total workforce including seasonal workers" -> `people.seasonal_workers`: a subset answers a total question (scope defect).
- "Are your accounts audited?" -> `governance.audit_required`: "audited" matched "audit_required", a different fact (stem-level defect).
- Not wrong but missed (safe): bankers, "annual turnover", "registered ...", "how many staff ..." and many counting paraphrases.
- Correct handling worth noting: both bare "City" / "Postcode" questions with two address blocks went to REVIEW; scope-by-section ("City" under "Trading address")
  was answered correctly; period constraints (previous year, two years ago, 2023) were REVIEW unless the key named the period.

### 6.6 Three safeguards added after held-out v3 (matcher changed after the embedding experiment)

v3 exposed four unsafe answers. Root causes and the **class-level** rules that fix them (no field name and no question is special-cased; fixtures in
`dev_defects.json`, tests in `tests/web/test_safeguards.py`, 34 tests, 8 of which fail on the pre-fix source and 26 are positive controls):

1. **Entity qualifier** (parent company employees / parent company name). The word "company" in a generic question earned path credit from `parent_company`,
   and nothing held a key's *own* entity word against it. Now a key whose path names another legal entity that the question does not name (`parent`,
   `subsidiary`, `affiliate`, `holding`, `ultimate`, `sister`, or the modifier of any `<modifier>_company/_entity/_firm` segment) can never be the answer
   to a generic question (score capped to REVIEW). It still counts as a *rival* for the ambiguity rule when the best answer does not explain more of the
   question than it does: a plain `org.founded` and a differing `parent.founded` stay ambiguous for "Year founded", while "Name of the operating company" still reads
   `operating_company.name`. (A first version removed the rival entirely and created three new unsafe answers on older sets; caught by the per-question comparison.)
2. **Composite population** ("Total workforce including seasonal workers" read the seasonal-workers key). `including / excluding / inclusive / combined / plus` were
   not scope words. They now have to be carried by the key itself (`total_including_contractors`), else REVIEW.
3. **Modality** ("Are your accounts audited?" read `audit_required`). `required` and `mandatory` are stopwords, so `audit_required` tokenised as `audit` and
   the stem link `audited ~ audit` looked perfect. The raw words of the question and the key path now carry a modality (obligation / plan / request): a key that
   narrows by one the question does not name, or a question that insists on one the key lacks, is capped. Soft verbs ("enforce", "enforced") satisfy the other
   side's obligation but never create a mismatch (two earlier correct answers, "Do you enforce MFA?" and "required for all users" vs `enforced_for_all_users`,
   were lost by a stricter first version and restored).

| set | role | before: correct / unsafe | after: correct / unsafe | per-question changes |
|---|---|---|---|---|
| semantic dev (121) | development | 59 / 0 | 59 / 0 | none |
| semantic seen (141) | development | 48 / 2 | 48 / 2 | none |
| semantic held-out v2 (105) | evaluation (tuned against earlier) | 50 / 1 | 50 / 1 | none |
| **held-out v3 (122), frozen, digest unchanged** | evaluation | 48 / **4** | 48 / **0** | 4 unsafe -> REVIEW, no correct lost |
| `dev_defects` (50) | development | 28 / 6 | 28 / 0 | 6 unsafe -> REVIEW, no correct lost |
| `benchmarks/rfi` (195, browser) | fixed | 106 / 1 | 106 / 1 | none (195 of 195 outcomes identical) |
| `benchmarks/heldout` (276, browser) | fixed | 119 / 0 | 119 / 0 | none (276 of 276 identical) |
| SPA fixtures (26) / widgets (12) | local fixtures | fill 79/115, 12/12 | fill 79/115, 12/12 | none |

**How to read this honestly.** v3's 0 unsafe is **not** a fair held-out estimate any more: the rules were designed from diagnosing v3's failures, then tested on
separate development fixtures and re-checked on every other set. It shows the four known defects are closed and nothing else moved; it does not show
that the next unseen source is free of the same classes. The class lists are finite: entity words outside `ENTITY_QUALIFIERS` and the `<modifier> <noun>` shape,
composite words outside `COMPOSITE_MARKERS`, and modality words outside `_MODALITY` / `_SOFT_OBLIGATION` are not covered. A generic question against a source whose
*only* entity-qualified key holds the answer (e.g. everything under `subsidiary.`) now goes to REVIEW; that is deliberate and costs an answer.
Coverage did not change on any set (no unnecessary new REVIEW on the evaluated sets), but the rules can only add REVIEWs, so on other sources they may.

## 7. Final verification (verified on the working tree; outputs in `benchmarks/final_verification_safeguards/`; the earlier `final_verification/` and `final_verification_stabilization/` directories are historical records of earlier states of the code)

```bash
pip install -e ".[web,dev]" ruff mypy        # + a Chromium build; export FORMFILL_CHROMIUM=/path/to/chrome if Playwright's is unavailable
python -m pytest -q -p no:cacheprovider      # 514 passed, 2 xfailed (182.0 s)
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
| widget fixtures | 12/12 fill, 12/12 DOM read-back, 12/12 app state, conditional 3/3 (rerun on the final tree, unchanged) |
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
- **One browser test is timing-sensitive.** `tests/web/test_spa_browser.py::test_document_navigation_stops_and_loss_is_reported` failed once in a full run during closeout (passed 3/3 in isolation and in a second full run: 514 passed, 2 xfailed). The cause was not diagnosed; rerun it before treating a single failure as a regression.
- Client-side state verification needs a caller-supplied `state_reader`; without one only the DOM is checked. Server-side persistence is never verified.
- Page-side blur handlers, reveals later than ~150 ms after a field blur (default mode), Next buttons inside shadow roots/iframes, and non-English forms are unsupported or untested.
- A script-driven submission hidden behind a normal-looking "Next" button cannot be detected before the click (section 5.1).
- Test sets are **author-written** by the same engineer who wrote the code; none is independently validated. Held-out v2 has one author, was authored after the layer was designed, and is not clean after its first run; treat its first-run numbers as the honest estimate, and all
  figures as development evidence rather than proof of generalisation.
- Dates other than ISO, "£2.4m", "six" and similar are REVIEW by design (no unit/currency parsing).
- Embedding-based retrieval was evaluated (6.5) and **not adopted**: the effect was too small and mixed to justify the dependency. The model's checksum has **not** been verified against Hugging Face (not reachable from the sandbox).
- The disputed development label (company vs subsidiary employees) still produces 1 unsafe answer on `benchmarks/rfi`; "zero unsafe answers" is **not** claimed anywhere.
- Environment blocker: Playwright's own browser download is blocked here; not a project defect.

## 10. Key files

`formfill/web/`: `pipeline.py` (orchestration), `discover.py`, `understand.py`, `tokens.py`, `semantic.py` + `lexicon.json` (alignment), `retrieve.py` (scoring, caps,
context), `plan.py` (decision), `validate.py`, `execute.py` (Playwright), `steps.py` (wizard navigation), `result.py` (report), `source.py` (loading), `cli.py`.
Tests: `tests/web/` (browser tests marked `browser`; skipped when Chromium is unavailable). Tools: `tools/evaluate_*.py`, `tools/compare_runs.py`.
Historical results (`benchmarks/*/results`, `docs/PHASE*.md`) are preserved unchanged and describe the pre-completion state, including the removed submit path.
