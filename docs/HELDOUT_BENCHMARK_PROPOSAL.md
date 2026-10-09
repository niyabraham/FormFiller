# Held-out benchmark proposal (not yet built)

**Status: proposal only.** Nothing here has been authored, run or inspected.

## Why

`benchmarks/rfi/` (v1.0.0, split `dev`) is the **development set**: its 88 failures have been read, classified and
used to write Phase 3 priorities. Any number measured on it after tuning is optimistic. Phase 3 changes must be
judged on forms nobody has looked at.

## Split rule

Split by **independent form/case**, never by question. Questions inside a form share vocabulary, source JSON and
section structure, so a question-level split would leak.

- The held-out set consists of whole new forms, each with its own source JSON, authored without opening the dev
  failure cards.
- A form is held-out only if no dev form shares its source JSON, label wording or fixture template.
- Same category coverage as dev (easy, paraphrase, qualifiers, nested, boolean, option mapping, missing, ambiguity,
  narrative, conditional, multi-step, custom widgets, realistic questionnaire) so per-category comparisons are fair.

## Size and composition

- ≥ 12 forms and ≥ 150 scored questions, ~half engineer-natural source JSON, ~half form-aligned.
- At least 3 forms modelled on public questionnaire structure (SIG/CAIQ-style, vendor onboarding, supplier
  due-diligence), authored by someone who has not seen the dev failures (a second engineer, or the guide).
- Truth written first, from the correct answer, with the same ANSWER / REVIEW / ABSENT scheme plus an explicit
  `disputed` flag for labels a reviewer could contest; disputed items are reported with and without.
- Keep the label audit rule: use REVIEW whenever the JSON cannot justify a single answer.

## Protocol

1. Author and freeze it (`benchmark_version` 1.0.0, `split: heldout`), commit digest recorded.
2. Run the **unchanged** Phase 2 baseline on it once, and record the result. That is the honest baseline.
3. Develop Phase 3 against `dev` only. Do not read held-out failure cards while developing.
4. Run held-out at most once per Phase 3 milestone; log each run. A large dev-to-held-out gap means overfitting.
5. If held-out failures are inspected for tuning, that form joins `dev` and a fresh held-out form is added.

## Reporting

Per split: scored N, precision, coverage, review rate, unsafe count, answerable recall, plus the confusion matrix.
Acceptance for Phase 3: **zero unsafe answers and precision ≥ 98 % on held-out**, with recall as the improvement metric.
