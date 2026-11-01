# Neighbouring-concept guard: before / after (2026-11-01)

Same evaluations (`tools/evaluate_baseline.py` on `benchmarks/rfi` and `benchmarks/heldout`, `evaluate_matching.py`, `evaluate_spa.py`,
`evaluate_wizards.py`, `evaluate_widgets3d.py`), run from a pristine export of commit b354d58 (`before/`) and from the working tree with the
guard (`after/`). Historical results elsewhere under `benchmarks/*/results/` are untouched.

| set | auto-answered | correct | wrong | precision | coverage |
|---|---|---|---|---|---|
| dev (rfi) before / after | 107 / 107 | 105 / 105 | 1 / 1 | 98.1 % / 98.1 % | 55.7 % / 55.7 % |
| held-out before / after | 109 / 109 | 109 / 109 | 0 / 0 | 100 % / 100 % | 40.1 % / 40.1 % |

No decision changed on either set (per-question comparison of `baseline.json`). An earlier iteration of the guard lost 1 dev and 4 held-out
correct answers; those five paraphrases ("was", "dept"/"department", "currently"/"active", "run"/"performed", "limit"/"coverage") were
found through this comparison and excluded by the rules documented in docs/MATCHING.md. Because that involved the held-out set, held-out is
no longer an untouched check for this change.

`realworld_replay.json`: offline re-planning of the 32 recorded real-world control sets: 29 answered before and after; 11 review items
changed their *proposal* only (nothing was answered differently). `probes.txt`: 62 related-concept probes (not part of the benchmark
sets; written for this change).

**The held-out set was used during refinement.** Rules in this change were adjusted after comparing per-question decisions on
`benchmarks/heldout` (see above), so held-out numbers here are NOT an untouched, independent evaluation of this change. They show that no
decision changed, not that the rules generalise to unseen forms. Reproduce: `tools/evaluate_baseline.py` (dev) and
`tools/evaluate_baseline.py --bench-dir benchmarks/heldout` (held-out) from a pristine checkout of b354d58 and from this branch.
