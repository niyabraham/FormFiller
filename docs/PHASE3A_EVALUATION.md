# Phase 3A — deterministic retrieval hardening

Branch `phase3a-retrieval-hardening`, based on `78d7cab` (Phase 2). Not committed. No LLM, embeddings, RAG or vector DB.
The Phase 2 record (`benchmarks/rfi/results/baseline.json`, `failures.md`, `docs/PHASE2_EVALUATION.md`) is untouched; Phase 3A
results are in `benchmarks/rfi/results/phase3a/` (`baseline.json`, `failures.md`, `comparison.md`).

Reproduce: `python tools/evaluate_baseline.py --out-dir benchmarks/rfi/results/phase3a` then
`python tools/compare_runs.py benchmarks/rfi/results/baseline.json benchmarks/rfi/results/phase3a/baseline.json`.
The evaluator refuses to overwrite the frozen Phase 2 results when the pipeline is modified. Ground truth is unchanged
(same benchmark v1.0.0, same content digest in both runs); the comparison tool refuses to compare runs whose truth differs.

## What changed (design decisions)

| Area | Change | Why |
|---|---|---|
| Scope words | `QUALIFIERS` extended with entity/population words (`parent`, `subsidiary`, `affiliate`, `holding`, `ultimate`, `sister`, `production`, `domestic`, `foreign`, `international`, `global`, `regional`). A missing scope word now **caps** the score at 0.5 after the section bonus, instead of ×0.6 before it. | The bonus used to lift a penalised score back over 0.6 ("Parent company name" in a "Company" section). The cap is below `MIN_CONFIDENCE` (asserted by a test). |
| Generic coverage guard | If more than half of the question's words are explained by neither the key nor its path, score capped at 0.5. "total" and the self-reference word "company" are exempt. | Handles unknown scope words that no list contains. Deliberately weak (strictly more than half) because a stricter version broke the guide's own `full_time` example. |
| Polarity | New `NEGATORS` (`not`, `non`, `optional`, `disabled`, `disable`, `without`, `unsupported`, `never`, `inapplicable`). The question and the key path must carry the **same** markers, otherwise the score is capped at 0.3. Nothing is inverted; uncertain cases go to REVIEW. | "Is MFA optional?" read `mfa_required` and answered yes at confidence 1.0. `no` is not a negator ("Registration No."). |
| Reviewer visibility | `Candidate.flags` records why a score was capped; the REVIEW reason and alternatives show it. | A capped candidate is still shown to the human. |
| Tokeniser | `_` normalised before phrase matching (`full_time_employees` now works); `total`, `state`, `optional` are no longer stopwords (`state` as an imperative verb is still dropped by context); parenthetical acronyms kept (`(MFA)`, `(USD)`), format hints still dropped; spelled-out MFA/SSO/DPO/CISO/PII meet their short forms; `hq`→headquarter; `supported`/`encrypted` inflections; stemmer fixed for `-sses/-xes/-ches/-shes` (`processes`). | Each was a demonstrated Phase 2 miss. Stopwords were not disabled wholesale. |
| Question text | Leading enumerators (`C.3`, `1.2.1.`) and `optional`/`required` decorations (`Phone - optional`) are stripped for matching only; the displayed question text is unchanged. `Q3 revenue` and `SOC 2` are untouched. | They produced junk tokens. |

Not done (out of scope for 3A): parent/sibling scoring, option/date mapping, browser changes, confidence recalibration.

## Results on the development benchmark (192 scored questions)

| Metric | Phase 2 | Phase 3A | Change |
|---|---|---|---|
| Auto-answered | 82 | 93 | +11 |
| Correct | 76 | 91 | +15 |
| **Precision** | 92.7 % | **97.8 %** | +5.1 |
| **Coverage** | 42.7 % | **48.4 %** | +5.7 |
| Review rate | 50.0 % | 44.8 % | −5.2 |
| Answerable recall | 48.4 % | 58.0 % | +9.6 |
| **Unsafe answers** | 5 | **1** | −4 |
| Fill failures | 1 | 1 | 0 |
| Never asked | 14 | 13 | −1 |

Unsafe = 1 is not zero, and zero is not claimed. The remaining one is "How many employees does the organization have?"
→ 250 (`company.employees`, with `subsidiary.employees` = 80 present), a disputed label that needs sibling/parent scoring. Excluding the
two disputed items, unsafe = 0, precision 98.9 % (N = 190), but that is a sensitivity figure, not the headline.

Confusion matrix (every question once): correct ANSWER 91 · wrong ANSWER 0 · ANSWER but fill failed 1 · expected ANSWER → REVIEW **54**
(was 67) · expected ANSWER, never asked 11 · correct REVIEW 32 (was 29) · expected REVIEW → ANSWER **1** (was 4) · expected REVIEW, never asked 2.

By source style: form-aligned precision 98.0 / coverage 53.8 / 0 unsafe; engineer-natural 97.7 / 43.4 / 1 unsafe.
Confidence ≥ 0.9 now gives 51 answers, 51 correct, 0 unsafe (Phase 2 at the same cut: 46, 45, 1).

### Every changed outcome (19 of 195; full table in `phase3a/comparison.md`)

- **Regressions (previously correct, now not): 0.**
- **Unsafe → correct REVIEW (3):** production employees; parent company name; website of parent company.
- **Wrong → REVIEW (1):** "Is MFA optional?" was answered `yes` (wrong); it is now REVIEW. The truth says `no` (disputed label), so it is counted as a
  missed answer, not as a success.
- **REVIEW/not asked → correct ANSWER (15):** headquarters city (`hq`), full-time employees (snake_case), Do you support SSO?, Is data encrypted at rest?,
  Do you encrypt data in transit?, Single sign-on is supported, State (no longer a stopword), Cyber insurance coverage amount (USD) (acronym kept),
  Does your company process payment card data? (stemmer), PCI DSS compliance level (cascade: its trigger now answers), MFA for administrator accounts,
  incident-response point of contact, security-awareness training completion rate, background checks on employees, date of last penetration test (enumerator stripped).
- 176 outcomes unchanged.

### Retrieval vs browser execution (kept separate)

| Stage | Phase 2 | Phase 3A |
|---|---|---|
| Retrieval: correct top | 89 | 102 |
| Retrieval: right leaf but score < 0.6 | 25 | 17 |
| Retrieval: incorrect top | 7 | 3 |
| Retrieval: ambiguous / none / spurious | 22 / 23 / 17 | 23 / 23 / 15 |
| Browser: filled correctly | 80 | 91 |
| Browser: fill failure / read-back false alarm | 1 / 1 | 1 / 1 |
| Discovery: found / missed | 183 / 9 | 183 / 9 |

The browser column rose only because more questions reached it; execution code is unchanged.

### Remaining failures (70 cards = 69 unsuccessful outcomes + 1 correct answer whose verification disagreed)

retrieval 32 · form discovery 17 · ambiguity 12 · validation 5 · browser execution 2 · question understanding 1 · submission/verification 1.
Unchanged by design: discovery (custom widgets, wizard steps, file inputs), option/date/band mapping, sibling ambiguity, masked-input verification.

## Findings that need your attention

1. **The benchmark did not catch a regression; the demo did.** My first coverage guard (≥ half unexplained) capped "Does GDPR apply to your organization?" in `demo_web.py`
   (9 answers → 7: the conditional "DPO name" was then never revealed), while the benchmark showed 0 regressions. Cause: a self-reference word ("organization" → `company`) counted as unexplained. Fixed by exempting
   self-reference words and tightening the rule to strictly more than half; a regression test now covers it. The dev benchmark under-represents this kind of question,
   which is a reason to build the held-out set before more tuning.
2. **Ablation of the generic coverage guard:** disabling it gives 93 correct / 1 unsafe (vs 91 / 1), i.e. on the dev set it costs 2 correct answers and prevents 0 unsafe
   answers, because the scope-word list already catches every dev unsafe case. Its value is for scope words nobody listed, which this set cannot measure. I kept it
   (safety priority) but it should be judged on the held-out set and removed if it only costs coverage. (Measured by running the evaluator with
   `MIN_EXPLAINED_FRACTION = 0`; not stored as a result file.)
3. **Dev-set caveat:** the failures were inspected before these fixes, so the improvement is on the set that motivated them. Treat 97.8 % / 48.4 % as development numbers, not expected production performance.
4. Polarity is conservative: "Is MFA required for non-administrators?" now goes to REVIEW (a `non` the key lacks). That is the intended cost.

## Tests

`tests/web/test_phase3a_hardening.py`: 66 tests (65 pass, 1 strict xfail). Each of the five Phase 2 unsafe answers has one: three explicit REVIEW tests for the
scope cases (each also with a positive twin where the source has the right key, and a similar-but-wrong rejection), the MFA case (answered only from an `optional` flag),
and the organization-employees case as `xfail(strict=True)` so it will flag itself if a later change fixes it. Also: required/optional, enabled/disabled, applicable/not applicable,
support/not support pairs (12 parametrised), snake_case, total/state/optional, acronyms, stemming, enumerators, and the ordinary questions that must keep working.
REVIEW is never accepted where an ANSWER is expected: positive tests assert the value.
`tests/evaluation` regression ceiling lowered from 5 to 1 unsafe answers.

Results: 167 passed, 1 xfailed (was 102 passed). Both demos run (`demo_web.py`: 9 ANSWER / 2 REVIEW, identical to the run at `78d7cab`; `demo.py`: verification PASS).
Ruff is clean on every new file and on the lines I changed. Seven style findings remain in untouched Phase 1 code (`discover`, `execute`, `pipeline`, `plan` line 50, `result`, `validate`); I fixed one more in `understand.py` that `--fix` could apply.

## Recommended next batch (3B)

1. Build the held-out benchmark (`docs/HELDOUT_BENCHMARK_PROPOSAL.md`) and run the Phase 3A code on it once, before any further tuning.
2. Parent/sibling scoring: the one remaining unsafe answer, plus hierarchical keys (`access.sso.enabled`) and sibling-duplicate detection. This is where most of the remaining 32 retrieval and 12 ambiguity failures sit (17 of the 54 remaining missed answers already rank the right leaf first but score it under 0.6).
3. Deterministic option/number-band/date mapping (the 5 validation failures).
4. Only then browser work (custom widgets, wizard navigation, disabled-then-enabled controls).
