# Run comparison

- before: commit `ee61e130951d452f106932832dfdba01ec2e1aaa` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `500e9119797e4a4a3dc109d801182d92b38af962` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 93 | 94 | +1 |
| correct answers | 91 | 92 | +1 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 86 | 85 | -1 |
| never asked | 13 | 13 | +0 |
| precision % | 97.8 | 97.9 | +0.1 |
| coverage % | 48.4 | 49.0 | +0.6 |
| review rate % | 44.8 | 44.3 | -0.5 |
| answerable recall % | 58.0 | 58.6 | +0.6 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 91 | 92 | +1 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 54 | 53 | -1 |
| expected_ANSWER__not_asked | 11 | 11 | +0 |
| expected_REVIEW__predicted_REVIEW | 32 | 32 | +0 |
| expected_REVIEW__predicted_ANSWER | 1 | 1 | +0 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (1)

| case | question | expected | before | after |
|---|---|---|---|---|
| c07_ambiguity | Revenue for 2024 | 12000000 | REVIEW [missed_answer] | ANSWER 12000000 from revenue.2024 [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 194 of 195.
