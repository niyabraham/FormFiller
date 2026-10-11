# Phase 3B-B — parent/sibling-aware JSON retrieval

Branch `phase3b-parent-sibling-scoring`, created from `fed244e` (Phase 3B-A evaluation). Implementation commit: `c918f1fe5a1968f2e3094918296c311a90c4deb8`. `main` (`78d7cab`), `phase3a-retrieval-hardening` (`ee61e13`) and the earlier commits are untouched.
No LLM, embeddings, RAG, vector DB or browser change. No historical result file or ground truth was modified; all output is in new `results/phase3b_b/` directories.

**Provenance.** Baseline: `fed244e`, `pipeline_dirty = false` (`baseline_fed244e/`). Candidate: both sets were rerun against the committed code `c918f1f`, recorded as `evaluated_commit = c918f1f…`, `pipeline_dirty = false`
(`candidate/`); the numbers equal those of the earlier run from the uncommitted tree. The single-rule ablations below were run in-process on that identical code before it was committed and are not stored in the repository.
Reproduce: `python tools/evaluate_baseline.py --out-dir benchmarks/rfi/results/phase3b_b/candidate` and `python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir benchmarks/heldout/results/phase3b_b/candidate`;
comparisons: `tools/compare_runs.py` and `tools/compare_rankings.py` on `baseline_fed244e/baseline.json` vs `candidate/baseline.json`.
**Data status.** `benchmarks/rfi` (v1.0.0, `b5a81217376675b9`) and `benchmarks/heldout` (`heldout-1.0.0`, `0d275842d567c759`) are both *development data*: the additional set's failures were inspected and these rules were designed
while looking at both. None of the numbers below is independent validation.

## What was inspected first

`index_source` flattened JSON and kept only the *names* of parents (list indices and year-like keys dropped from the tokens), so `terminals.0.doors` and `terminals.1.doors`, or `franchisor.year_founded` and `franchisee.year_founded`,
differed only through a 0.5 weight on parent words and a +0.2 section bonus. Of the 85 additional-set and 53 dev-set missed answers at `fed244e`, 39 and 15 were `ambiguous` (top two within the 0.15 margin with different values).
Same field name under different parents / list items accounted for most of those that are structural: addresses (hq/billing), leaders (CEO/CISO), terminals, stores, insurance lines, franchisor/franchisee.

## Design: context is evidence that the question names an entity, never a default

| Rule | Evidence | Effect |
|---|---|---|
| Path | the question **or its form section** names a parent token that only one candidate with the same field name has (`franchisor`, `cargo`, `billing`) | the other candidates' scores are multiplied by 0.6 |
| Item | the question contains the complete literal value of a sibling field of one list item (`Omaha`, `CEO`, `store 114`); string values only, 1-4 distinctive words | those words count as explained (one unit of credit per cited value); items without it are multiplied by 0.6 |
| Ancestor | the question names an entity (every part of its path is named) and the rival is the same field in a collection under it (`franchisee.employees` vs `franchisee.locations.N.employees`) | the deeper rival is multiplied by 0.6 |
| Count re-check | a counting question whose candidate was picked by context is re-checked with entity words not allowed to dilute an unexplained modifier | cap 0.5 (no laundering of "refrigerated trailers of the franchisor") |

Rules that were deliberately **not** made: no preference for the filer's own entity (`company`/`org`/`supplier`) when none is named, no preference for the nearest, shallowest, first or highest-scoring parent, no use of list position.
`company`/`organisation` is self-reference and never counts as a named entity. When no entity is named, or several are, nothing changes and the question stays REVIEW. A named candidate keeps its score (rivals are lowered, nothing is raised
except the literal-value credit), so a weak winner stays under 0.6. Winners record `evidence` in the plan item (and in `alternatives`); penalised rivals record a `context:` flag.
The Phase 3B-A rules (qualifiers, period, negation, placeholders, counting modifier) and the generic guard are unchanged and still run first.

One design iteration is worth recording: a blanket tightening of the counting rule (entity words may not dilute a modifier) lost two correct answers (`Customer support personnel (headcount)`, `Number of direct production workers`).
It was replaced by the narrow re-check above, which applies only when context chose the candidate.

## Tests

`tests/web/test_phase3b_parent_sibling.py` (47 tests incl. 1 strict xfail): franchisor/franchisee, company/parent company/subsidiary, departments, insurance lines sharing a word, cargo vs auto liability, a later key winning over an earlier one;
section evidence (hq/billing, a neutral section, label vs heading); sibling values (terminals, leaders by role, stores by number and city, no match, nobody has that role, both items named, `York` vs `New York`, numeric values unused, single item, totals stay ambiguous);
ancestor evidence; every 3B-A rule inside these contexts (qualifier, counting modifier, period, negation, placeholder); and "context only lowers rivals" (winner score unchanged, rival lower, reasons recorded, plan exposes evidence).
Ambiguous cases assert REVIEW with no answer. Known costs are tests too. Suite: **324 passed, 2 xfailed** (3B-A: 278 + 1). Both demos unchanged (`demo.py` PASS; `demo_web.py` output identical to `ee61e13`).
Ruff: no new findings; 9 pre-existing remain in the whole tree.

## Results

| | Dev (192) | | Additional set (272; dev data) | |
|---|---|---|---|---|
| | `fed244e` | candidate | `fed244e` | candidate |
| Auto-answered | 94 | 101 | 97 | 107 |
| Correct | 92 | **99** | 97 | **107** |
| Unsafe | 1 | **1** | 0 | **0** |
| Precision | 97.9 % | 98.0 % | 100 % | 100 % |
| Coverage | 49.0 % | **52.6 %** | 35.7 % | **39.3 %** |
| Missed answers | 53 | 46 | 85 | 75 |
| Missed, retrieval state `ambiguous` | 15 | 8 | 39 | 25 |

- **Correct answers moved to REVIEW: 0 on both sets. New regressions: 0. Unsafe answers introduced: 0.**
- **Previously unsafe answers fixed: 0** — Phase 3B-A had already removed the additional set's six; this batch targets coverage. The dev set's one unsafe answer (`How many employees does the organization have?` -> 250 while `subsidiary.employees` exists) is **unchanged and remains**:
  the question names no entity, and by design hierarchy does not decide it (strict xfail kept). A true zero is not claimed.
- Improvements, all on previously REVIEW: dev 7 (`Security contact email`; hq and billing `Street`/`City`/`Postal code` via form sections; `CISO name`, `CEO email` via role values); additional 10 (`Leeds office`, `Cargo insurance limit`, `Omaha terminal`, `Employers' liability`, `Public liability expiry`,
  `employees of the franchisee`, `franchisor year`, `San Antonio store`, `store #131`, `Newark branch`). Full tables: `comparison.md`, ranking changes: `rankings.md` in each `phase3b_b/` directory.

### Candidate-ranking changes
Dev: top candidate changed on 3 questions (hq/billing street and city, CISO name), 7 scores changed, 185 unchanged. Additional: top changed on 3, runner-up changed on 6, scores on 15, 252 unchanged.
In every changed case the new top is the one the question or section names, and the old top was lowered (e.g. billing 1.20 -> 0.72). One additional-set ranking changed without changing the outcome (`Companies House registration number`: the supplier form section now ranks `supplier.company_number`
first, still 0.50 < 0.6, so REVIEW).

### Each rule alone (disabled, everything else on; analysis only, in-process, not stored)

| Disabled | Dev correct / unsafe | Additional correct / unsafe | Reading |
|---|---|---|---|
| none (candidate) | 99 / 1 | 107 / 0 | |
| path evidence | 94 / 1 | 103 / 0 | carries 5 dev and 4 additional gains |
| sibling-value credit | 99 / 1 | 104 / 0 | carries 3 additional gains |
| ancestor evidence | 99 / 1 | 106 / 0 | 1 additional gain |
| item penalty | 99 / 1 | 107 / 0 | **no measurable effect here**: the credit already separates items; kept for the synthetic cases (`York`), but unproven on the benchmarks |
| count re-check | 99 / 1 | 107 / 0 | **no measurable effect here**: a safeguard exercised only by tests |
| all context off | 92 / 1 | 97 / 0 | = baseline |
| generic guard (3A, unchanged) | 101 / 1 | 108 / **2** | same trade-off as before: costs 2 / 1 correct answers, prevents 2 unsafe answers on the additional set |

### Remaining ambiguous cases (`remaining_ambiguous_both_sets.md`)
Dev 8, additional 25. By kind: no entity named (`Employer Identification Number`, `Name of auditor`; hierarchy intentionally does not decide; the benchmarks label the filer's own entity as the answer in some forms and as REVIEW in others, which is why a default was not built);
different leaf under one parent (`Immediate parent company name`: `name` vs `company_number`; `dpo_name` vs `dpo_email`; `aggregate` vs `single project`); list items with no cited value (`largest customer`, totals vs branches); same-leaf choices decided by wording
rather than hierarchy (`Name of the owning entity`); and several that are really weak scores or synonyms (`Sales headcount`, `refrigerated`/`reefer`).

## Limitations
- Evidence is lexical: a parent or sibling word must appear in the question or form section after tokenising. `Opening date of store 114` still fails because `opening` and `opened` are not matched (tokeniser, not in scope).
- Sibling values are strings of up to four distinctive words; numbers (`store_no: 114` as an integer), 2-letter codes and booleans are not used. Both-items-named questions stay REVIEW.
- Ancestor evidence needs every part of the winner's path named and a strict path-prefix relation; it will not choose between unrelated entities.
- Section tokens count as evidence; a misleading heading could single out the wrong parent. The question's own words outrank it only through the Phase 3A score (`Billing street` under a Headquarters heading answers billing; this is documented, not hidden).
- The counting re-check makes natural phrasings such as `How many employees work in the sales department?` REVIEW when context had to choose (filler verbs cannot be told from modifiers without a word list); the plain wording answers.
- The pre-existing 3B-A gap remains: with a *single* parent, entity words dilute a counting modifier (`Number of refrigerated trailers of the franchisor` answers `franchisor.trailers` if that is the only candidate).
- No held-out claim: both sets are development data.

## Later stage: scoping SPA-specific browser testing (not implemented)
Goal: a separate benchmark of *behaviour*, not matching, measured with the same evaluator so results are comparable.
1. **Fixtures first (no live third-party sites).** Local pages that reproduce SPA mechanics: client-side routing/wizards where the form is not in the initial DOM; steps revealed only after valid input; controls rendered after async fetch; virtualised or lazily mounted lists; framework-controlled inputs
   (React/Vue/Angular change detection needs real input events, masked fields, debounced validation); custom widgets (comboboxes, date pickers, chips, toggles that are not native inputs); shadow DOM and same-origin iframes; autosave/draft banners; route changes that discard values.
2. **Metrics separate from retrieval:** discovery recall per step, controls found only after a navigation, fill success vs read-back verification, value lost after route change, validation messages surfaced, and number of unsafe interactions (a click that submits or navigates unintentionally must be 0).
3. **Safety rules to keep:** never click submit/next unless the run mode says so, no production portals or third-party sites, attestation controls always REVIEW, disabled-then-enabled controls revisited only after their trigger is answered, stop and report on unexpected navigation or modals.
4. **Staging:** (a) wait/stability primitives and DOM-settle detection with fixtures; (b) wizard step discovery (20 of 34 discovery failures in the additional set are hidden wizard steps); (c) custom widget adapters with read-back; (d) shadow DOM/iframes; (e) a held-out set of fixtures authored independently before any tuning.
5. **Exit criteria:** discovery misses on wizard fixtures below an agreed bound, zero unsafe interactions, read-back agreement on every filled field, and no change to retrieval metrics (browser work must not alter the AnswerPlan).
