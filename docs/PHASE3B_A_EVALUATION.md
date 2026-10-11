# Phase 3B-A — deterministic safety hardening

Branch `heldout-evaluation`. Implementation commit: `500e9119797e4a4a3dc109d801182d92b38af962` (base `ee61e13`; `78d7cab` and `ee61e13` are unchanged).
No AI, embeddings, RAG or vector DB; no parent/sibling scoring, no browser change, no ground-truth change, no historical result file modified.

**Provenance.** Both result sets in this directory were produced by rerunning the evaluator against the committed implementation: `evaluated_commit = 500e911…`,
`pipeline_dirty = false`, benchmark digests `b5a81217376675b9` (development set v1.0.0) and `0d275842d567c759` (additional set). An earlier run of the same code from the
uncommitted tree gave identical numbers. The Phase 3A reference for the development set was rerun from a clean `ee61e13` checkout
(`benchmarks/rfi/results/phase3b_a/reference_phase3a_clean/`) because the stored `benchmarks/rfi/results/phase3a/baseline.json` records `78d7cab`/dirty (it was produced before that commit existed;
left unchanged). The additional-set reference is the stored clean `benchmarks/heldout/results/phase3a/`.

**Data status.** `benchmarks/rfi` is development data. `benchmarks/heldout` was inspected (its failure cards motivated these four fixes) and is **development data too**; it is not a held-out set and
its 3B-A numbers are not generalisation evidence. A fresh, independently authored set is still required.

Reproduce: `python tools/evaluate_baseline.py --out-dir benchmarks/rfi/results/phase3b_a` and
`python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir benchmarks/heldout/results/phase3b_a`
(Phase 3A dev reference: `FORMFILL_PIPELINE_ROOT=<clean ee61e13 checkout> python tools/evaluate_baseline.py --out-dir …/reference_phase3a_clean`).

## Changes (`formfill/web/`, +105/−10)

| Pattern | Change | Condition for REVIEW |
|---|---|---|
| Missing critical modifier | counting questions (`how many`, `number of`, `no. of`, `headcount`) are capped at 0.5 when **at most half** their words are explained (Phase 3A: fewer than half, any question). A generic noun a parent leaves implicit (`employee`) is not held against a key (`company.full_time` still answers "full-time employees"). | an unexplained modifier ("sales", "refrigerated", "certified") on a count |
| Temporal scope | `tokens.period_markers`: `last/previous/prior year`, `N years ago`, `current/this/next year`, calendar years, from the question and from the key path (year-keyed dict keys included). Capped at 0.3 when the two differ, or when the question names a period other than last/current and the key names none. "Last name" and "the last 5 years" (a window) are not periods. | different period, or an unsupported non-default period |
| Negation | `lack`, `lacking`, `absence`, `absent` added to `NEGATORS`. Same mechanism as 3A: both sides must carry the same marker; nothing is inverted. | question negated, key not (or the reverse) |
| Placeholder | `validate.is_placeholder` (`None`, `N/A`, `TBD`, `TBA`, `TBC`, `unknown`, `null`, `nil`, `-`, `--`, `—`, `not applicable`, …; whole string only; bare `NA` excluded). `plan` returns REVIEW with a reason unless the control has an option with that text. | top candidate's value is a placeholder |

The generic coverage guard is unchanged (`MIN_EXPLAINED_FRACTION = 0.5`); the new counting threshold is a separate constant (`COUNT_MIN_EXPLAINED_FRACTION`) so each can be ablated.

**A first version was too broad and was narrowed.** Applying "at most half explained" to *every* question moved 12 correct dev answers to REVIEW (`Reporting currency`,
`Operating regions`, `Which certifications do you hold?`, `Date of last penetration test`, …) for 4 prevented unsafe answers. It is now limited to counting questions,
where a narrower population is a different number; the dev set then loses nothing. This is recorded in `TestStrictnessIsLimitedToCounts`.

## Results

| | Dev benchmark (192) | | Additional set (272, now dev data) | |
|---|---|---|---|---|
| | 3A | 3B-A | 3A | 3B-A |
| Auto-answered | 93 | 94 | 105 | 97 |
| Correct | 91 | 92 | 99 | 97 |
| **Unsafe** | 1 | **1** | 6 | **0** |
| Precision | 97.8 % | 97.9 % | 94.3 % | **100.0 %** |
| Coverage | 48.4 % | 49.0 % | 38.6 % | 35.7 % |
| Answerable recall | 58.0 % | 58.6 % | 48.3 % | 47.3 % |

The 0 on the additional set is a measurement on data used to design the fixes (4 patterns derived from it); it is **not** evidence of zero unsafe answers in general.
The dev set still has its 1 unsafe answer (the disputed `How many employees does the organization have?`, a parent/sibling case, out of scope here).

### The six cases (additional set)

| # | Question | Phase 3A | 3B-A | Outcome |
|---|---|---|---|---|
| 1 | Sales headcount | 86 (total) | REVIEW | unsafe → missed answer (truth: 14 from `Number of sales representatives`; no shared word, needs a synonym) |
| 2 | Parent company name | `None` | REVIEW | unsafe → correct REVIEW |
| 3 | Gross fees, two financial years ago | 6,840,000 | REVIEW | unsafe → correct REVIEW |
| 4 | Does the organisation lack a whistleblower policy? | yes | REVIEW | unsafe → missed answer (truth `no`; not inverted by design) |
| 5 | Number of refrigerated trailers | 640 | REVIEW | unsafe → missed answer (truth 120 from `reeferTrailers`; "refrigerated" ≠ "reefer") |
| 6 | Number of recruiters who are certified | 31 | REVIEW | unsafe → correct REVIEW |

### New regressions and correct answers moved to REVIEW

- Dev benchmark: **0 regressions**, 1 improvement (`Revenue for 2024`: the period rule disqualifies `revenue.2023`, so the margin rule no longer blocks `revenue.2024`).
- Additional set: **2 regressions**, both correct counting answers now REVIEW: `4. Number of partners / members` (key `Number of partners`; "members" is a slash alternative) and
  `Number of SKUs offered` (key `Number of SKUs`; "offered" is filler). I did not special-case them: they are the measured price of the counting rule (3 unsafe prevented, 2 correct lost).
  Candidate refinements for review: treat slash/`or` alternatives as needing only one explained word; a short filler-participle list (`offered`, `provided`, `held`).

### Each rule alone (rule disabled, everything else on; analysis only, rerun in-process on `500e911`, nothing stored in the repo)

| Disabled | Dev correct / unsafe | Additional correct / unsafe | Reading |
|---|---|---|---|
| none (3B-A) | 92 / 1 | 97 / 0 | |
| counting-modifier rule | 92 / 1 | 99 / **3** | prevents #1, #5, #6; costs 2 correct |
| period rule | 91 / 1 | 97 / **1** | prevents #3; gains 1 dev correct |
| `lack` negation | 92 / 1 | 97 / **1** | prevents #4 |
| placeholder rule | 92 / 1 | 97 / **1** | prevents #2 |
| **generic guard (3A, kept)** | 94 / 1 | 98 / **2** | prevents 2 unsafe on the additional set, costs 2 dev correct and 1 additional correct net |

The generic guard is kept as instructed; on the evidence here it prevents 2 unsafe answers on the additional set and none on dev, at a cost of 2 and 1 correct answers.

## Tests and lint

`tests/web/test_phase3b_safety.py`: 90 tests (negative and positive twins for each pattern, count wordings, "last name", windows, `NA`/`Nonesuch Ltd`, a dropdown that offers "None",
`0`/`False` are not placeholders, `full_time` still answers). Whole suite: **278 passed, 1 xfailed** (Phase 3A: 188 + 1 xfailed with the held-out tests; the one xfail is the disputed organisation-employees case).
Both demos unchanged (`demo_web.py` output identical to `ee61e13`; `demo.py` PASS).
Ruff: no new findings. On the changed and added files, 2 findings remain, both on lines this batch did not touch (`plan.py:57` `dict()` call, `validate.py:146` `isinstance` merge; both present at `ee61e13`); 7 more remain in untouched Phase 1 modules and `tests/web/test_retrieve_plan.py`.

## Known gaps (not addressed, not hidden)

- A question without a period against a key that names an old period (`Gross fees` vs `gross_fees_two_years_ago`) is not capped (no observed case).
- Time windows ("last 5 years" vs "last 3 years") are not compared.
- Negation by `no`-prefixed keys and `refrain` are not covered.
- The strict rule applies only to questions worded as counts; a count on a bare label (`Trailers (reefer)`) is not covered.
- Synonym gaps (`sales representatives`, `reefer`) remain missed answers.
