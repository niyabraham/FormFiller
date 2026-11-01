# Iteration 2 (review follow-up), 2026-11-01

Additional iteration on top of `../2026-11-01_neighbouring_concept_guard/`, which is kept unchanged (its `after/` is iteration 1). The baseline
for both is the pristine b354d58 export in that folder's `before/`.

Changes in this iteration: a key about a topic the question never names needs more than half the question explained (fixes the last wrong
answer, probe del-2, and its mirror image); proposals must be the kind of contact detail asked for; "format" is a how-written word.

| | iteration 1 | iteration 2 |
|---|---|---|
| probes with a wrong automatic answer (62) | 1 (del-2) | 0 |
| dev: auto-answered / correct / wrong | 107 / 105 / 1 | 107 / 105 / 1 |
| held-out: auto-answered / correct / wrong | 109 / 109 / 0 | 109 / 109 / 0 |
| real-world replay: answered fields | 29 | 29 |
| real-world replay: changed reviewer proposals (vs baseline) | 11 | 11 (different members; one email-for-phone proposal removed, "Contact Email" no longer gets a phone) |

Reviewer proposals are advisory (REVIEW, never filled); their quality is not fill precision.

**The held-out set was used during refinement** (here as in iteration 1: the "format" exclusion was found by comparing per-question
changes), so held-out numbers are not an untouched, independent evaluation of this change; they show that no decision changed. The 62
probes were written for this change and are not a benchmark either: they show the guard handles the pairs we thought of, not that
other pairs are safe. Remaining limitations are listed in `docs/MATCHING.md` (Known gaps).
