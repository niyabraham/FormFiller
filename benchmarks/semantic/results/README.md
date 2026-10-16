# Semantic benchmark results

| directory | what it is |
|---|---|
| `before_semantic_layer/` | the three splits evaluated on the untouched `main` commit (4ffe03b) with the same evaluator |
| `heldout_v2_first_run/` | held-out v2 on the FIRST run of the new code, before any defect it exposed was fixed (3 unsafe: a missing polarity word, a mislabelled question, a subset-population miss) |
| `../../final_verification/semantic/` | all splits on the final code (held-out v2 is no longer clean after the polarity fix; its first-run record is the honest held-out number) |

Reproduce: `python tools/evaluate_semantic.py --split dev|seen|heldout --out-dir <new dir>`.
