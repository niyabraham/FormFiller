# Run comparison

- before: commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=True, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `bea0b206c5742579b5a0b865262de0febc8cd98e` pipeline_dirty=True, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 119 | 119 | +0 |
| correct answers | 119 | 119 | +0 |
| unsafe answers | 0 | 0 | +0 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 122 | 122 | +0 |
| never asked | 31 | 31 | +0 |
| precision % | 100.0 | 100.0 | +0.0 |
| coverage % | 43.8 | 43.8 | +0.0 |
| review rate % | 44.9 | 44.9 | +0.0 |
| answerable recall % | 58.0 | 58.0 | +0.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 119 | 119 | +0 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 65 | 65 | +0 |
| expected_ANSWER__not_asked | 21 | 21 | +0 |
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
