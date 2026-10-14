# Run comparison

- before: commit `1d1dbd0487f62b0e19db236d45e057c8a876d3f8` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `1d1dbd0487f62b0e19db236d45e057c8a876d3f8` pipeline_dirty=True, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 107 | 107 | +0 |
| correct answers | 107 | 107 | +0 |
| unsafe answers | 0 | 0 | +0 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 133 | 133 | +0 |
| never asked | 32 | 32 | +0 |
| precision % | 100.0 | 100.0 | +0.0 |
| coverage % | 39.3 | 39.3 | +0.0 |
| review rate % | 48.9 | 48.9 | +0.0 |
| answerable recall % | 52.2 | 52.2 | +0.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 107 | 107 | +0 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 76 | 76 | +0 |
| expected_ANSWER__not_asked | 22 | 22 | +0 |
| expected_REVIEW__predicted_REVIEW | 57 | 57 | +0 |
| expected_REVIEW__predicted_ANSWER | 0 | 0 | +0 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (0)

_none_

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 276 of 276.
