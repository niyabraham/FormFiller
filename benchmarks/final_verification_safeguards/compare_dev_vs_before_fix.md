# Run comparison

- before: commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `bea0b206c5742579b5a0b865262de0febc8cd98e` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 108 | 108 | +0 |
| correct answers | 106 | 106 | +0 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 72 | 72 | +0 |
| never asked | 12 | 12 | +0 |
| precision % | 98.1 | 98.1 | +0.0 |
| coverage % | 56.2 | 56.2 | +0.0 |
| review rate % | 37.5 | 37.5 | +0.0 |
| answerable recall % | 67.5 | 67.5 | +0.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 106 | 106 | +0 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 40 | 40 | +0 |
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
