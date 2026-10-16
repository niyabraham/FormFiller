# Semantic retrieval benchmark

Pure retrieval + safety cases (no browser): each question is run through `understand_control -> index_source -> plan_question`,
the same code the pipeline uses. `expect` is either the source path that must answer it or `REVIEW` (a person must decide).

| file | role | questions | notes |
|---|---|---|---|
| `dev.json` | development | 121 | written alongside the semantic layer, used to tune it |
| `seen.json` | development (second) | 141 | written before the layer but its baseline failures were read while writing the lexicon, so it is NOT held out |
| `heldout.json` | held-out v2 | 105 | written afterwards in new domains/key styles, digest frozen in `FROZEN.txt` before its first run. Same author as the implementation, no independent annotator |

Categories: exact, paraphrase, nested, scope (period/population/future), negation, unsupported, similar_different, ambiguous,
compound, missing, conflicting, option_mismatch, type. Every question lands in exactly one outcome: correct, wrong_answer (unsafe),
unsafe_answer (answered a must-review question; unsafe), missed (safe REVIEW), correct_review.

Known label defect (held-out v2, left as frozen): `City` in `v02_pharma_cro` is expected REVIEW but that source has a single city
key, so answering `hq.city` is arguably right. Reported as unsafe in the raw numbers.
