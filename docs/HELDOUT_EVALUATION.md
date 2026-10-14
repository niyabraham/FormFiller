# Held-out evaluation: Phase 2 (`78d7cab`) vs Phase 3A (`ee61e13`)

Status: committed. No matching, planning, validation or browser code was changed by this commit. The only tooling change is that
`tools/evaluate_baseline.py` can now measure another checkout (`FORMFILL_PIPELINE_ROOT`) against another benchmark (`--bench-dir`).

> **Going forward this dataset is development data.** It was held out only until its failure cards were read (the 6 unsafe answers and the miss
> analysis below were derived from it, and Phase 3B-A's fixes were designed from them). Numbers measured on it after this point must not be
> presented as held-out or generalisation evidence; a fresh, independently authored set is required for that.
> Independence caveats in section 2 (the first authoring agent was interrupted, so its compliance with the spec is unattested) still apply.

## 1. Benchmark: `heldout-1.0.0`

| | |
|---|---|
| Forms (cases) | 14, none shared with the 16 development cases |
| Scored questions | **272** (205 expect ANSWER, 67 expect REVIEW), plus 4 hidden ABSENT controls that must stay unasked |
| Source style | 7 engineer-natural, 7 form-aligned (158 / 114 scored questions) |
| Content digest | `0d275842d567c759`, recorded in `benchmarks/heldout/FROZEN.txt` before any pipeline ran on it |
| Split rule | whole forms, never individual questions; the development set (`benchmarks/rfi`, v1.0.0) is treated as inspected |

Coverage: ordinary/paraphrased, scoped (time, geography, role, status), related entities (parent, ultimate parent, subsidiary, beneficial owner,
franchisee, branch), polarity-sensitive wording (optional, NOT, lack, unsupported, refrain, excluding), nested JSON, snake_case/camelCase/space-keyed
data, lists of objects, missing/null/ambiguous values, option and date/number constraints, conditional and enable-when fields, 3 wizard forms plus one form with a dynamically created step, file/custom/shadow controls, narrative and declaration questions. Tag counts are in `truth.json`.

### Ground-truth methodology

1. **Author**: an agent given only a written spec (`authoring/AUTHORING_SPEC.md`) and the form renderer; instructed not to read any repository,
   pipeline code, benchmark, report or failure card. Answer key written from the correct answer, with a note on every question.
2. **Blind audit**: a second agent labelled all 272 questions from only the form questions and the source JSON (`audit/`). Agreement with the
   author on decision, value and path: **266 / 272**.
3. **Reconciliation before freezing** (`reconciliation.json`): on any ANSWER-vs-REVIEW disagreement the conservative label (REVIEW) wins. Two author
   ANSWERs were changed to REVIEW (`h03 k_adv`, `h05 csopt`); four other disagreements were already REVIEW or only differed in the cited path. This
   makes the benchmark stricter about auto-answering.
4. **Freeze**, then run both checkpoints once. Nothing was tuned afterwards.

### Independence: what is and is not established

- Established: the author did not have the failure cards or pipeline code *by instruction*; the key was cross-checked blind; no case id and no source JSON file is shared with dev (only generic key names such as `name`, `email`, `country`).
- **Not established**: the first authoring agent was interrupted by a rate limit before reporting, so it never attested to what it opened. The second
  agent that finished and validated the files attests only for itself. Compliance of the actual author is therefore unverified.
- 7 questions have exactly the same text as a development question (`Parent company name`, `Operating regions`, `Country`, `Contact email`,
  `Billing contact email`, `Number of employees` x2), and `h01 2.2 "Is MFA optional for administrator accounts?"` is a close variant of a dev failure. Both are
  expected topics (the brief asked for parent/subsidiary and polarity), and the agents share priors with me, so this proves neither leakage nor independence.
  Results excluding them are given in section 4.
- Same model family wrote the key, the audit and the pipeline tests: shared blind spots are possible.
- The mix is 75 % ANSWER / 25 % REVIEW, lighter on REVIEW than the dev set, so the count of "answered where REVIEW was expected" cases rests on few questions (67).

### Ground-truth defects found (documented, labels not changed)

- **Three numeric fixtures cannot hold their expected answer.** `Indirect cost rate (%)` = 52.5, `On-time delivery rate (%)` = 97.4, `Average markup (%)` = 24.5
  are `<input type="number">` with no `step`, so the browser's own default (step 1) rejects decimals. Both pipelines correctly REVIEW them. They count as missed
  answers in all headline figures. Excluding them, Phase 3A answerable recall is 49.0 % (99/202) instead of 48.3 %.
- **Six "accepted_wrong_value" validation rows are measurement artefacts.** They are the polarity-inversion questions whose key requires a logical inversion; the
  validator correctly maps `true` to `yes`, and the truth expects `no`. They are not validator bugs.
- 11 questions are tagged `contestable` by the author; 2 more were reconciled. Results excluding contestable/reconciled items are in section 4.

## 2. Runs

Both runs: same evaluator file, same frozen benchmark, clean detached worktrees of each commit (`pipeline_dirty=false`), thresholds MIN_CONFIDENCE 0.6 / MIN_MARGIN 0.15.

```
git worktree add --detach <dir>/phase2  78d7cab
git worktree add --detach <dir>/phase3a ee61e130951d452f106932832dfdba01ec2e1aaa
for v in phase2 phase3a; do
  FORMFILL_PIPELINE_ROOT=<dir>/$v python tools/evaluate_baseline.py \
      --bench-dir benchmarks/heldout --out-dir benchmarks/heldout/results/$v
done
python tools/compare_runs.py benchmarks/heldout/results/phase2/baseline.json benchmarks/heldout/results/phase3a/baseline.json
```

Each `results/<run>/baseline.json` records the evaluated commit, benchmark version and digest, thresholds, metric definitions and this command.

## 3. Comparable metrics (272 scored questions)

| Metric | Phase 2 | Phase 3A | Change |
|---|---|---|---|
| Auto-answered | 97 | 105 | +8 |
| Correct auto-answers | 87 | 99 | +12 |
| **Precision** (correct / auto-answered) | **89.7 %** (95 % CI 82.1–94.3) | **94.3 %** (88.1–97.4) | +4.6 |
| **Coverage** (auto-answered / 272) | 35.7 % | 38.6 % | +2.9 |
| **Unsafe answers** | **10** | **6** | −4 |
| of which wrong value, ANSWER expected | 6 | 3 | |
| of which ANSWER where REVIEW expected | 4 | 3 | |
| Fill failures (reported separately) | 0 | 0 | |
| Expected-ANSWER recall (correct / 205) | 42.4 % | 48.3 % | +5.9 |
| Correct REVIEW (of 67) | 53 | 54 | +1 |
| Missed answers (expected ANSWER, sent to REVIEW) | 89 | 80 | −9 |
| Never asked | 33 (12.1 %) | 33 (12.1 %) | 0 |
| Review rate | 52.2 % | 49.3 % | |

Confusion matrix (every scored question once):

| Expected | Predicted | Phase 2 | Phase 3A |
|---|---|---|---|
| ANSWER | ANSWER, correct | 87 | 99 |
| ANSWER | ANSWER, wrong value | 6 | 3 |
| ANSWER | ANSWER, fill failed | 0 | 0 |
| ANSWER | REVIEW | 89 | 80 |
| ANSWER | never asked | 23 | 23 |
| REVIEW | REVIEW | 53 | 54 |
| REVIEW | ANSWER | 4 | 3 |
| REVIEW | never asked | 10 | 10 |

Stages:

| Stage | Phase 2 | Phase 3A |
|---|---|---|
| Form discovery: found / not found | 260 / 12 | 260 / 12 (+2 labels misread) |
| Hidden wizard step never navigated | 20 | 20 |
| Retrieval: correct / weak-correct / ambiguous / none / spurious / incorrect top | 107 / 19 / 58 / 52 / 18 / 6 | 118 / 18 / 58 / 42 / 18 / 6 |
| Validation: rejected valid values | 10 | 10 |
| Browser execution: filled correctly / fill failures / read-back failures | 97 / 0 / 0 | 105 / 0 / 0 |
| Browser execution problems (disabled-then-enabled control never revisited) | 2 | 2 |

Failure cards (Phase 3A, 119): retrieval 61, form discovery 34, ambiguity 14, validation 8, browser execution 2 (Phase 2: 70 / 34 / 17 / 9 / 2 = 132).

By source style (answered / correct / unsafe, precision): Phase 3A engineer-natural 59 / 57 / 2, 96.6 %; form-aligned 46 / 42 / 4, 91.3 %.

### Changed outcomes Phase 2 → 3A

18 of 272 changed (`results/comparison_phase2_vs_phase3a.md`): **14 improved, 1 regressed, 3 changed without becoming correct.**
Four Phase 2 unsafe answers disappeared: "adverse media NOT performed" became a correct REVIEW, and three (a company registration number answered with a business
description, related-party transactions, "SCIM unsupported") became safe REVIEWs of questions that expected an answer, which is why they appear under
"changed without becoming correct". The 14 improvements add correct answers from the tokeniser and polarity work.
The single regression: `Companies House registration number` (correct in Phase 2) now goes to REVIEW because the generic guard counts "house" and
"registration" as unexplained words. Paired sign test, 14 improvements vs 1 regression: p ≈ 0.001 (outcomes within a form are not independent, so treat as indicative).

### The six unsafe answers (Phase 3A)

| # | Form | Question | Expected | Answered | Class |
|---|---|---|---|---|---|
| 1 | h02 hospital supplier | Sales headcount | 14 (`sales` key) | 86 (total `Number of employees`) | retrieval: unexplained modifier ("sales"), 1 of 2 words explained |
| 2 | h02 hospital supplier | Parent company name | REVIEW (contestable) | the literal string `None` | ambiguity/data quality: placeholder text taken as a value |
| 3 | h06 insurance | 10. Gross fees, two financial years ago (GBP) | REVIEW (only last year exists) | 6,840,000 ("last financial year") | retrieval: time scope not compared |
| 4 | h07 NGO | Does the organisation lack a whistleblower policy? | no | yes (read `whistleblower_policy: true` as "lack") | polarity: "lack" is not a negation marker |
| 5 | h08 logistics | Number of refrigerated trailers | 120 | 640 (all trailers) | retrieval: unexplained modifier ("refrigerated"), 1 of 2 words explained |
| 6 | h14 staffing | Number of recruiters who are certified | REVIEW (no certified count) | 31 (all recruiters) | retrieval: unexplained modifier ("certified") |

Phase 2's other four unsafe answers are listed in `results/phase2/baseline.json`. Failure cards with JSON, decisions and reasons: `results/phase3a/failures.md`.
None of the six is a parent/sibling confusion.

## 4. Sensitivity (nothing relabelled)

| Subset (Phase 3A) | Scored | Answered | Correct | Unsafe | Precision |
|---|---|---|---|---|---|
| All | 272 | 105 | 99 | 6 | 94.3 % |
| Excluding contestable and reconciled items | 260 | 104 | 99 | 5 | 95.2 % |
| Also excluding the 7 same-text-as-dev questions | 254 | 104 | 99 | 5 | 95.2 % |

## 5. Diagnostic: the generic coverage guard (analysis only, not a candidate)

To test the unproven claim from Phase 3A, the evaluator was run in-process on the clean `ee61e13` checkout with `MIN_EXPLAINED_FRACTION = 0`
(guard off; no file changed; `results/diagnostic_phase3a_without_generic_guard/`):

| | Guard on (Phase 3A) | Guard off |
|---|---|---|
| Correct | 99 | 100 |
| Unsafe | 6 | 8 |
| Precision | 94.3 % | 92.6 % |

The guard prevented two wrong answers (a registration number answered with a business-activity text; related-party transactions inverted) and cost
net one correct answer. Its benefit is now measured and positive, but it did not catch any of the four modifier cases above, because those are
two-word questions with exactly half the words explained and the rule only fires below half. This diagnostic must not be used to tune the held-out set.

## 6. Where the remaining misses are (Phase 3A, 80 missed answers)

| Retrieval state of the missed answer | Count |
|---|---|
| Ambiguous (top two candidates close, different values) | 37 |
| Right leaf scored under 0.6 | 17 |
| No candidate at all | 15 |
| Right leaf found, rejected later (validation / disabled control) | 7 |
| Wrong leaf on top | 4 |

41 of the 80 already had the expected leaf ranked first. Of the 37 ambiguous misses, **24 are the same leaf name under different parents**
(`parent.company_number` vs `supplier.company_number`, `Office locations.0.staff` vs `.1.staff`, `carrier.terminals.0.doors` vs `.1.doors`,
`org.ein` vs `affiliates.chapters.0.ein`), 14 of which already have the right candidate on top and are lost only to the margin rule; 13 are different
leaves (year-keyed values, `aggregate` vs `single project`, total vs sub-item).
Discovery costs 34 questions (20 hidden wizard steps never navigated, 12 not found, 2 label misreads); that is not a matching problem.

## 7. Decision gate

**Does Phase 3A generalise?** Partly.

- The direction and sign hold on forms nobody tuned against: precision +4.6 points, unsafe −4, correct answers +12, 14 improvements to 1 regression.
- The size does not fully hold. Development: precision 97.8 %, unsafe 1, coverage +5.7. Held-out: precision 94.3 %, unsafe 6, coverage +2.9.
  Held-out precision is also below the 98 % target and unsafe answers are not near zero; those targets are **not met**.
- Part of the development gain was fitted to its own examples: all six remaining unsafe answers are patterns the development set did not contain
  (modifiers outside the scope list, a time scope, a negation word outside the marker list, a placeholder string).

**Remaining failure classes (by weight):** retrieval ambiguity between same-named leaves (37 misses, mostly structural); low scores on a correctly ranked
leaf (17+); unexplained modifiers (4 of 6 unsafe); form discovery (34, mostly wizard steps); validation/option/number mapping (8); negation vocabulary (1 unsafe,
plus polarity-heavy questions where coverage is 17 %); placeholder strings (1 unsafe).

**Does the evidence support parent/sibling-aware scoring?** Yes for coverage, no as a safety fix.

- Supports it: 24 of 37 ambiguous misses are exactly same-leaf-different-parent, 14 with the right candidate already first. Related-entity questions have 13 %
  coverage (3 of 23 answered) with 100 % precision, so there is large safe headroom. This is the largest single class of lost answers.
- Does not support it as the next *safety* step: none of the six unsafe answers is a parent/sibling error. Proceeding with parent/sibling work alone would
  leave unsafe = 6 on this set.

**Recommendation (for your decision; nothing implemented):** do both in one stage, with the safety items first and measured separately.
1. A safety batch aimed at the observed unsafe causes: unexplained-modifier handling for two-word questions (the half-explained case), a time/period scope
   check, a wider negation vocabulary (`lack`, `refrain`, `no`-prefixed keys), and treating placeholder strings (`None`, `N/A`, `TBD`, empty-like) as missing values.
2. Parent/sibling-aware scoring for same-leaf-different-parent and list-of-objects discriminators, expected to recover up to ~24 answers.
3. Both must be designed against the development set plus synthetic cases only. **This held-out set has now been inspected** (failure cards read, causes
   analysed) and, per the protocol, should be treated as development data from here on; a fresh independently authored held-out set (ideally by a human or
   an author whose compliance can be attested) is needed before the next generalisation claim.

No AI, embeddings or RAG are indicated by these results: of the 80 missed answers, only a few look semantic (e.g. "refrigerated" vs a "reefer" key, "Companies
House" vs `company_number`), while the large classes (from the categories above and the cards I read) are structural and lexical. I did not hand-label all 80, so this is a judgement.

## 8. Files

New (uncommitted, branch `heldout-evaluation`, based on `ee61e13`): `benchmarks/heldout/**` (14 cases, authoring sources, audit, reconciliation, freeze record,
results for both runs plus the diagnostic and comparison), `tools/build_heldout.py`, `tests/evaluation/test_heldout.py` (checks the freeze digest, truth
consistency, regeneration, provenance and reconciliation of both runs). Changed: `tools/evaluate_baseline.py` (`FORMFILL_PIPELINE_ROOT`, `--bench-dir`).
No file under `formfill/` changed.
