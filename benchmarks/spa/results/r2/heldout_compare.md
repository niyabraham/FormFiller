# Run comparison

- before: commit `d3a132de393e51a457234757e686c16c190af94d` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `d3a132de393e51a457234757e686c16c190af94d` pipeline_dirty=True, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 107 | 107 | +0 |
| correct answers | 107 | 107 | +0 |
| unsafe answers | 0 | 0 | +0 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 132 | 133 | +1 |
| never asked | 33 | 32 | -1 |
| precision % | 100.0 | 100.0 | +0.0 |
| coverage % | 39.3 | 39.3 | +0.0 |
| review rate % | 48.5 | 48.9 | +0.4 |
| answerable recall % | 52.2 | 52.2 | +0.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 107 | 107 | +0 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 75 | 76 | +1 |
| expected_ANSWER__not_asked | 23 | 22 | -1 |
| expected_REVIEW__predicted_REVIEW | 57 | 57 | +0 |
| expected_REVIEW__predicted_ANSWER | 0 | 0 | +0 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (0)

_none_

## Other changed outcomes (1)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

| case | question | expected | before | after |
|---|---|---|---|---|
| h13_manufacturing_quality | Plant legal name | 'Zeller Precision Castings GmbH' | not asked [not_asked] | REVIEW [missed_answer] |

Unchanged outcomes: 275 of 276.

