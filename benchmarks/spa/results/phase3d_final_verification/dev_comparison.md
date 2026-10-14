# Run comparison

- before: commit `1d1dbd0487f62b0e19db236d45e057c8a876d3f8` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `1d1dbd0487f62b0e19db236d45e057c8a876d3f8` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 102 | 102 | +0 |
| correct answers | 100 | 100 | +0 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 78 | 78 | +0 |
| never asked | 12 | 12 | +0 |
| precision % | 98.0 | 98.0 | +0.0 |
| coverage % | 53.1 | 53.1 | +0.0 |
| review rate % | 40.6 | 40.6 | +0.0 |
| answerable recall % | 63.7 | 63.7 | +0.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 100 | 100 | +0 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 46 | 46 | +0 |
| expected_ANSWER__not_asked | 10 | 10 | +0 |
| expected_REVIEW__predicted_REVIEW | 32 | 32 | +0 |
| expected_REVIEW__predicted_ANSWER | 1 | 1 | +0 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (0)

_none_

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 195 of 195.
