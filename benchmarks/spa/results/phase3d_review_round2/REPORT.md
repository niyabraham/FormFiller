# Phase 3D review round 2 - report (uncommitted, branch phase3d-widget-commitment, HEAD 1d1dbd0)

## Commands run (fresh, in this order; full console output in `commands_and_output.log`)
    python -m pytest -q --no-header -p no:cacheprovider        -> 415 passed, 2 xfailed in 149.4 s   (round 1: 398 passed; +17 tests)
    python demo.py                                              -> Final verification: PASS
    python demo_web.py   (this tree vs clean 3C worktree)       -> identical apart from ids/timestamps
    python tools/evaluate_widgets3d.py --out-dir <R>/widgets_after
    FORMFILL_PIPELINE_ROOT=<3C worktree> python tools/evaluate_widgets3d.py --out-dir <R>/widgets_before_3c
    python tools/evaluate_spa.py --policy --out-dir <R>/spa_after      (and the same on the 3C worktree -> spa_before_3c)
    python tools/evaluate_baseline.py --out-dir <R>/dev_after          (and 3C -> dev_before)
    python tools/evaluate_baseline.py --bench-dir benchmarks/heldout --out-dir <R>/heldout_after  (and 3C -> heldout_before)
    python tools/compare_runs.py <before> <after> --out <R>/{dev,heldout}_comparison.md
The widget evaluations were run twice: the first pass exposed two errors of mine (a ground-truth side-effect entry for a fixture without counters, and a
3C-incompatible import in the evaluator); both were fixed and the widget runs repeated. Reported widget results are the second pass. pytest ran before
those two evaluator/ground-truth fixes (neither is exercised by the tests); `formfill/` was unchanged between them (same v2 hash in every output).

## Results (generic local fixtures; no claim about real portals)
Widget fixtures, 12 expected fields (fill / DOM read-back / app state reported separately):
| run | fill ok | DOM read-back | app state | conditional found+filled | side-effect mismatches |
| 3C | 7/12 | 7/12 | 4/12 | 2/3 | none |
| round 2 | 12/12 | 12/12 | 12/12 | 3/3 | none |
Unsettled reporting: churn fixture flagged (round 2); all other fixtures not flagged. (3C has no such report; its "mismatch" on churn is expected.)
SPA 26 fixtures (policy mode): summary identical to 3C; per-fixture records identical except settle-wait ms jitter. submit events 0, submission attempts 0.
Dev: 195/195 outcomes unchanged (the disputed unsafe answer remains: unsafe 1 -> 1). Held-out: 276/276 unchanged (unsafe 0 -> 0).
## Not claimed
App-state commitment is measured only where a fixture exposes it; DOM read-back is not proof. Round-1 outputs in `../phase3d/` are preserved untouched.
