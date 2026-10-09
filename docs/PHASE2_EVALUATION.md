# Phase 2 — Where the deterministic baseline fails

Baseline under test: commit `fe54f34` (pipeline unchanged). Thresholds: `MIN_CONFIDENCE=0.6`, `MIN_MARGIN=0.15`.
No LLM, embeddings, RAG, vector DB or browser agent was added. No third-party portal was contacted.

Reproduce:

```
python tools/build_benchmark.py          # regenerate benchmarks/rfi/
python tools/evaluate_baseline.py        # writes results/baseline.json + failures.md
pytest tests/evaluation                  # truth-file integrity + harness smoke tests
```

## 1. Benchmark description

16 extraction cases and 7 submission scenarios, all local HTML + JSON, generated from one declarative source
(`tools/benchmark_cases.py`, `tools/benchmark_render.py`). Each question has explicit ground truth: expected
ANSWER (value + source JSON path) or expected REVIEW, written from the correct answer, never from pipeline output.
The evaluator checks the end state by reading the DOM itself; it does not trust the pipeline's own read-back.

Categories covered: easy; paraphrase/synonym (employees/staff/workforce/personnel/headcount); qualifiers
(full-time, contractors, active customers, production employees, security contact); nested JSON; boolean wording
(SSO etc.); option mapping (United States vs US); missing values; ambiguous values (250 vs 80); narrative;
conditional (GDPR → DPO); multi-step/dynamic reveal; validation; label styles; custom widgets; dynamic inputs;
and one 24-question SIG/CAIQ-style security questionnaire modelled on published vendor-questionnaire patterns
(ID-prefixed labels, Yes/No/NA, section grouping). Research used secondary public write-ups only
(Sprinto, Wolfia, RocketDocs CAIQ guide, Formaloo); no live portal was inspected or automated.

Two source-JSON styles are used and reported separately: *form-aligned* (keys resemble form wording) and
*engineer-natural* (keys as a developer would name them).

## 2. Number of questions / cases

| | |
|---|---|
| Cases | 23 (16 extraction, 7 submission) |
| Questions in files | 213 |
| Extraction questions scored | **192** (157 expected ANSWER, 35 expected REVIEW) |
| Form-aligned / engineer-natural | 93 / 99 |

## 3. Baseline results

| Metric | Value |
|---|---|
| Auto-answered | 82 |
| Correct auto-answers | 76 |
| **Auto-answer precision** | **92.7 %** (Wilson 95 % ≈ 85–97 %) |
| **Coverage** (auto-answered / all) | **42.7 %** |
| **Review rate** | **50.0 %** |
| **Unsafe answers** (wrong value or answer where REVIEW expected) | **5** |
| Not surfaced (never discovered/asked) | 7.3 % (14) |
| Answerable recall (correct / expected ANSWER) | 48.4 % (76/157) |
| Correct REVIEW | 29 of 35 expected |

Trade-off, stated plainly: the system is cautious. It buys ~93 % precision with ~43 % coverage, and the 5 wrong
answers are not removable by a confidence threshold (see §13).

By source style: form-aligned precision 93.3 / coverage 48.4 / 2 unsafe; engineer-natural 91.9 / 37.4 / 3 unsafe.

Per case (questions · auto-answered · correct · unsafe):

| Case | Q | Ans | OK | Unsafe | Coverage |
|---|---|---|---|---|---|
| c01 easy exact | 12 | 11 | 11 | 0 | 91.7 % |
| c02 paraphrase | 14 | 9 | 9 | 0 | 64.3 % |
| c03 qualifiers | 12 | 7 | 6 | 1 | 58.3 % |
| c04 nested | 10 | 4 | 4 | 0 | 40.0 % |
| c05 boolean | 14 | 4 | 3 | 1 | 28.6 % |
| c06 option mapping | 13 | 5 | 5 | 0 | 38.5 % |
| c07 ambiguity | 15 | 6 | 5 | 1 | 40.0 % |
| c08 missing | 13 | 6 | 4 | 2 | 46.2 % |
| c09 narrative | 10 | 3 | 3 | 0 | 30.0 % |
| c10 conditional | 10 | 5 | 5 | 0 | 50.0 % |
| c11 multistep | 7 | 2 | 2 | 0 | 28.6 % |
| c12 validation | 13 | 3 | 3 | 0 | 23.1 % |
| c13 realistic security | 24 | 4 | 4 | 0 | 16.7 % |
| c14 label styles | 12 | 8 | 8 | 0 | 66.7 % |
| c15 custom widgets | 7 | 1 | 1 | 0 | 14.3 % |
| c16 dynamic inputs | 6 | 4 | 3 | 0 | 66.7 % |

Stage metrics:

| Stage | Result |
|---|---|
| Discovery | 183/192 found; 9 missed (5 custom widgets, 2 dynamic step-3 controls, 2 file uploads); 0 wrong kind; 6 wrong labels |
| Retrieval | correct 89 · weak-correct (right leaf, score < 0.6) 25 · ambiguous 22 · none 23 · incorrect top 7 · spurious 17 |
| Planning | correct ANSWER 76 · correct REVIEW 29 · missed answer 67 · unsafe ANSWER 4 · wrong ANSWER 1 |
| Validation | accepted-correct 141 · rejected-valid 7 · rejected-invalid 9 · accepted-wrong-value 1 · accepted-invalid 0 |
| Browser | correctly filled 80 · fill failure 1 · read-back false alarm 1 |
| Submission | 7/7 scenarios behaved as expected |

## 4. Successful cases

- Exact/near-exact labels: c01 100 % precision, 91.7 % coverage; "control" questions 94 %.
- Correct REVIEW on missing data (fax, absent fields), on disclosure/composition narratives, and on all 8
  deliberately invalid source values (0 auto-answered).
- Hidden-must-stay-hidden: 3/3 conditional fields stayed untouched.
- Attestation checkboxes never ticked; required-missing → NEEDS_REVIEW; server-reject → UNCONFIRMED (not success);
  delayed and navigate-away confirmations detected.
- Dedicated `ANSWER`s in the realistic questionnaire were all correct (4/4), just few.

## 5. Failure cases (taxonomy)

88 failure cards, each classified by a fixed decision procedure in `classify()`:

| Class | Count |
|---|---|
| retrieval problem | 50 |
| form discovery problem | 17 |
| ambiguity problem | 12 |
| validation problem | 5 |
| browser execution problem | 2 |
| question understanding problem | 1 |
| submission/verification problem | 1 |

Full cards for all 88: `benchmarks/rfi/results/failures.md`. Significant ones are quoted below (§6–§12, §14).

**Why 88 cards when the matrix shows 87 unsuccessful outcomes.** The confusion matrix has 192 − 76 correct ANSWER − 29
correct REVIEW = 87 unsuccessful scored outcomes. The 88th card is a *correct* answer: `c16_dynamic_inputs:mobile_phone`
(masked phone input). The form holds the expected value, but the pipeline's own read-back check disagreed and reported
FAILED, so it is classed as a submission/verification problem even though the outcome is a success. There is no
duplicate and no unscored control: 88 = 87 + 1. This is recorded in `baseline.json` → `failure_accounting` and in the
`failures.md` header.

**Why 58 reviewed, and the 62 retrieval + ambiguity cards.** Retrieval (50) + ambiguity (12) = 62 cards:
56 missed answers (45 + 11), 2 cascade cases never asked because their trigger question was not answered, and
4 unsafe answers (3 + 1). The manual root-cause labelling covered the 56 missed answers plus the 2 cascades = 58. The
4 unsafe answers were not part of that labelling; they are audited individually in §8 and the addendum. The 58 split:

Manual root-cause labelling of the 58 (my judgement, not automated; 30 + 21 + 5 + 2 = 58):

| Root cause | Count |
|---|---|
| Lexical/tokenisation — deterministic fix | 30 |
| Scoring/structure — deterministic fix | 21 |
| Genuinely semantic | 5 |
| Cascade from another failure (never asked) | 2 |

In 25 retrieval misses the correct leaf was already ranked first but scored < 0.6.

## 6. Ambiguous cases

Of 16 ambiguity-tagged items: 6 answered (5 correct, 1 unsafe), 10 REVIEW (7 correct). Hierarchical duplicates
(`company.employees` 250 vs `subsidiary.employees` 80) usually trigger the margin rule correctly.

```
FORM QUESTION:   [c07] How many employees does the organization have?
JSON:            company.employees = 250 (0.857); subsidiary.employees = 80
CURRENT DECISION: ANSWER 250
EXPECTED:        REVIEW
WHY IT FAILED:   near-tie not recognised as ambiguous (follows the brief's own example; arguably debatable)
CLASS:           ambiguity problem
FUTURE SOLUTION: Deterministic: penalise when a sibling object has the same leaf; require explicit scope word.
```

## 7. Missing-data cases

12 missing-tagged items: 9 REVIEW (correct), 3 answered wrongly (all "parent/other entity" lookalikes, §8).
Absent values were never invented. Fax and similar absent fields: correct REVIEW.

## 8. False-positive matches (unsafe answers)

Five items, all classified; none is a confidence-threshold artefact (§13).

```
FORM QUESTION:   Number of production employees
JSON:            workforce.employees = 250
CURRENT DECISION: ANSWER 250 (0.667)
EXPECTED:        REVIEW
WHY IT FAILED:   'production' is not a listed qualifier and is silently ignored
CLASS:           retrieval problem
FUTURE SOLUTION: Unmatched-token penalty: unexplained content words in the question cap confidence.
```

```
FORM QUESTION:   Parent company name  /  Website of parent company
JSON:            company.name, company.website
CURRENT DECISION: ANSWER "Acme Corp" / "https://acme.example" (0.667)
EXPECTED:        REVIEW
WHY IT FAILED:   'parent' not explained by key or its parents
CLASS:           retrieval problem
FUTURE SOLUTION: Same unmatched-token penalty; extend qualifier list is brittle, penalty is general.
```

```
FORM QUESTION:   Is MFA optional?
JSON:            security.mfa_required = true
CURRENT DECISION: ANSWER "yes" (confidence 1.0)
EXPECTED:        "no"
WHY IT FAILED:   "optional" is a stopword; negation/polarity discarded
CLASS:           question understanding problem
FUTURE SOLUTION: Polarity guard: negating/modal words in the question or key force REVIEW. Deterministic.
```

## 9. False-negative matches (missed answers)

67 answerable questions went to REVIEW or were not surfaced. Dominant causes (all observed in code):
`full_time_employees` defeats the `full[-_ ]time` phrase rule; stemmer maps `processes→processe`; "state" and
"total" are stopwords so `State` and `customers.total` are invisible; parenthetical acronyms "(MFA)/(SSO)" are
dropped; boolean leaves like `exists`/`enabled` carry no meaning without parent weighting; digit-only keys are
treated as list indices; the section bonus is binary so hq/billing items tie.

```
FORM QUESTION:   [c13] C.3 Do you support single sign-on (SSO)?
JSON:            expected access.sso.enabled; top candidate = incident.breach_last_3_years = false (0.22)
CURRENT DECISION: REVIEW (best candidate too weak)
EXPECTED:        ANSWER "yes" from access.sso.enabled
WHY IT FAILED:   acronym in parentheses discarded; generic leaf `enabled` carries no meaning without its parent `sso`
CLASS:           retrieval problem
FUTURE SOLUTION: Keep parenthetical acronyms; weight parent path for generic boolean leaves. Deterministic.
```

Only 5 of 157 answerable items looked genuinely semantic (SLA ≈ uptime availability; "stored exclusively in the
EU" ≈ `data_resident_in_eu`; SOC 2 Type II derived from `soc2_type`; "summary of infosec program" ≈
`security.overview`; "Data Protection Officer" ≈ `dpo_name`).

## 10. Narrative-question behaviour

11 items: precision 100 %, coverage 36.4 %. Composition/disclosure questions ("describe how…") go to REVIEW,
correctly. A dedicated single text leaf is answered only if token overlap clears 0.6. No narrative was ever
synthesised. This is the safe behaviour; generating prose is a separate, later problem.

## 11. Conditional-form behaviour

Hidden fields stayed hidden (3/3). Revealed fields are handled when the trigger resolves. Two cascade failures:
PCI level and DPO phone were never revealed because the trigger answers scored weakly. Wizard step 2 (hidden in
the DOM) is never navigated; dynamically injected step-3 controls were missed (2).

```
FORM QUESTION:   [c16] Account manager name
CURRENT DECISION: REVIEW (control is disabled)
EXPECTED:        'Ravi Menon'
WHY IT FAILED:   disabled at discovery, enabled by a later answer; never revisited
CLASS:           browser execution problem
FUTURE SOLUTION: Re-scan disabled/hidden controls after each fill round. Deterministic.
```

## 12. Browser-execution failures

Only 2 of 192, plus 9 discovery misses and the verification issue:

| Item | Class | Fix |
|---|---|---|
| Read-only date picker: fill failure | browser | per-widget driver / detect readonly |
| Masked phone: read-back differs ("5550001234" vs "555-000-1234"), pipeline reports FAILED while DOM is right | submission/verification | compare via control's normalisation |
| Custom radios/combobox/switch/editable, shadow DOM (5) | discovery | ARIA-role discovery, shadow piercing |
| File inputs (2) | discovery | surface as REVIEW instead of skipping |
| Wizard hidden step | discovery | step navigation |
| Options loaded late (async) | discovery | re-read options before validation |

Validation (5): "United States"→`US`, 250→`51-250`, "Software as a Service"→`saas`, and "14 March 2009" rejected by
the ISO-only date policy. All rejections were safe (REVIEW); none accepted invalid input. Fix: deterministic
option-mapping layer.

## 13. Overall metrics and what thresholds do

| Threshold | Answered | Correct | Unsafe |
|---|---|---|---|
| ≥0.6 (current) | 82 | 76 | 5 |
| ≥0.7 | 61 | 58 | 2 |
| ≥0.8 | 57 | 54 | 2 |
| ≥0.9 | 46 | 45 | 1 |

Raising the threshold loses ~44 % of correct answers to remove 4 of 5 unsafe ones, and the last (MFA optional)
survives at confidence 1.0. Confidence is a measure of token overlap, not of correctness; it is not calibrated for
polarity or unexplained words. Failure classes are in §5.

## 14. Main failure patterns

1. **Lexical normalisation, not semantics** (30 + part of 21): stemmer, snake_case phrases, stopword collisions,
   acronyms. Cheap and deterministic.
2. **Scoring has no "unexplained words" term**: the source of 4 of 5 unsafe answers.
3. **Polarity is invisible**: negation/modals dropped.
4. **Structure unused**: parent-path meaning, type compatibility, sibling duplicates.
5. **No value normalisation**: option mapping, numeric bands, natural-language dates.
6. **Browser coverage gaps**: custom widgets, shadow DOM, wizards, disabled-then-enabled controls.
7. **Cascades**: one weak trigger hides downstream conditional questions.

## Is deterministic matching enough?

| Capability | Verdict from the measurements |
|---|---|
| Exact | Yes. 100 % precision, ~92 % coverage on easy/control. |
| Aliases | Mostly, after tokeniser/acronym fixes; failures were lexical. |
| Paraphrases | Not yet (60 % coverage), but most misses are lexical; a minority (~3 % of answerable) is truly semantic. |
| Qualified questions | Precise only for listed qualifiers; fails open on unlisted ones. Needs an unmatched-token penalty, not AI. |
| Nested JSON | Weak today (40 %) because parent path is under-used. Deterministic fix. |
| Ambiguous | Margin rule works in most cases; sibling-scope penalty needed. |
| Narrative | Correctly refused; synthesis is out of scope and not needed to be safe. |

## Recommendation for Phase 3

**Do not add AI yet. Harden the deterministic layer, re-measure, then decide on the residual.**

Phase 3a (deterministic):
- Tokeniser: stemmer fix, snake_case compound phrases, stopword collisions (`state`, `total`, `optional`),
  parenthetical acronyms, spelling variants and abbreviations.
- Scoring: parent-path meaning for generic booleans, discriminators in lists of objects, graded section evidence,
  type-compatibility tie-break, specificity weighting, **unmatched-question-token penalty**, **polarity guard**.
- Normalisation: option mapping, numeric bands, unambiguous natural-language dates, list→count.
- Browser: wizard navigation, ARIA widgets, shadow DOM, file inputs surfaced as REVIEW, re-check disabled
  controls, late options, mask-aware verification.
- Build a **held-out** benchmark before tuning, so gains are not overfitting to this set.
- Targets: unsafe = 0 and precision ≥ 98 % on both sets; improvement metric is answerable recall.

Phase 3b (only if recall stays materially short): the residual semantic items (~5/157 here) justify, in order,
embeddings as a candidate re-ranker, or LLM selection limited to ≤5 candidates whose output is re-validated by the
existing deterministic gate. No LLM question-understanding and no RAG: nothing measured requires them. The
deterministic gate stays the decision-maker; NEVER GUESS is unchanged.

## Addendum — metric reconciliation and ground-truth audit (post-review)

Evaluated commit `fe54f34` (pipeline unchanged; `pipeline_dirty=false`), benchmark v1.0.0 (split `dev`),
MIN_CONFIDENCE 0.6, MIN_MARGIN 0.15. Reproduce: `python tools/build_benchmark.py && python tools/evaluate_baseline.py`.
Provenance and metric definitions are stored in `benchmarks/rfi/results/baseline.json` under `run`, and in the
header of `failures.md`.

**Confusion matrix (N = 192, every question exactly once; the evaluator asserts the partition):**

| Expected | Predicted | Count |
|---|---|---|
| ANSWER | ANSWER, correct value in the form | 76 |
| ANSWER | ANSWER, wrong value | 1 |
| ANSWER | ANSWER, but fill failed | 1 |
| ANSWER | REVIEW | 67 |
| ANSWER | never asked (not discovered / unrevealed step) | 12 |
| REVIEW | REVIEW | 29 |
| REVIEW | ANSWER | 4 |
| REVIEW | never asked | 2 |
| **Total** | | **192** |

Three ABSENT controls (hidden fields that must stay unasked) are outside the 192; all stayed unasked.
213 total questions = 192 + 3 ABSENT + 18 in the 7 submission scenarios.

**Why the numbers looked inconsistent (they were not wrong, just under-reported):**
- 82 answered − 76 correct = 6 not-correct: 1 wrong value + 4 answered-where-REVIEW-expected = **5 unsafe**, plus
  **1 fill failure** (read-only date picker). The fill failure decided ANSWER but no wrong value reached the form, so
  it is counted as not-correct and not unsafe. 76 + 5 + 1 = 82.
- 82 ANSWER + 96 REVIEW = 178. The other **14 were never asked** (12 expected ANSWER, 2 expected REVIEW):
  undiscovered custom widgets, file inputs, the dynamic step and cascades. 82 + 96 + 14 = 192. 96 REVIEW = 67 missed + 29 correct.

**Definitions:** precision = correct / auto-answered = 76/82 = 92.7 %; coverage = auto-answered / N = 82/192 = 42.7 %;
review rate = REVIEW / N = 96/192 = 50.0 %; not-surfaced = 14/192 = 7.3 %; answerable recall = 76/157 = 48.4 %.
Denominator N counts every scored question including those never surfaced. I found no calculation error; all
headline figures are unchanged. Only the reporting changed (explicit partition, fill-failed bucket, recorded definitions).

**Ground-truth audit of the five unsafe answers plus the disputed one:**

| # | Question | Relevant JSON | Expected | Current | Unambiguous? |
|---|---|---|---|---|---|
| 1 | Number of production employees | `workforce.employees`=250, `full_time_employees`=210, `contractors`=40, `interns`=5 | REVIEW | ANSWER 250 | Yes. No production scope exists; 250 is the total. |
| 2 | Is MFA optional? | `security.mfa_required`=true, `mfa_enforced_admins`=true | "no" | ANSWER "yes" (1.0) | **Disputed label.** "required" has no stated scope, so REVIEW is also defensible. Answering "yes" is wrong under either label. |
| 3 | How many employees does the organization have? | `company.employees`=250, `subsidiary.employees`=80 | REVIEW | ANSWER 250 | **Disputed label.** 250 (filing entity) is a reasonable reading; REVIEW follows the brief's spec and is conservative. |
| 4 | Parent company name | `company.name`="Acme Corp"; no parent key | REVIEW | ANSWER "Acme Corp" | Yes. Acme Corp is the company, not its parent. |
| 5 | Website of parent company | `company.website`; no parent key | REVIEW | ANSWER company.website | Yes. Same reasoning. |

No label was changed to force an answer. Items 2 and 3 now carry a `disputed` tag and a note in the truth files.
Sensitivity: excluding both disputed items, N=190, answered 80, correct 76, unsafe 3, precision 95.0 %.
If item 3 were relabelled ANSWER 250: answered 82, correct 77, unsafe 4, precision 93.9 %. The unsafe count stays between
3 and 5, and the three unambiguous unsafe answers (1, 4, 5) all share one cause: an unexplained qualifier.

**Held-out protocol:** `benchmarks/rfi/` is now the labelled development set. A separate held-out benchmark, split by
independent form, is proposed in `docs/HELDOUT_BENCHMARK_PROPOSAL.md` (not built, not run).

## Caveats

- The benchmark was authored by the same team and is adversarial by design; coverage is not a production estimate.
- Small sample: 82 auto-answers, precision interval ≈ 85–97 %.
- Root-cause split (30/21/5/2) is a manual judgement.
- The c07 "organization employees" truth follows the brief's example and is debatable.
- Engineer-natural vs form-aligned sources give different results; real data will be somewhere between.
- c14 uses opaque control names by design (two semantic-name items added for fairness).
- Research references are secondary articles; real portals were not inspected.
