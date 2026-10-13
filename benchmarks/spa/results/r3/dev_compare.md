# Run comparison

- before: commit `d3a132de393e51a457234757e686c16c190af94d` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `d3a132de393e51a457234757e686c16c190af94d` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 101 | 102 | +1 |
| correct answers | 99 | 100 | +1 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 78 | 78 | +0 |
| never asked | 13 | 12 | -1 |
| precision % | 98.0 | 98.0 | +0.0 |
| coverage % | 52.6 | 53.1 | +0.5 |
| review rate % | 40.6 | 40.6 | +0.0 |
| answerable recall % | 63.1 | 63.7 | +0.6 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 99 | 100 | +1 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 46 | 46 | +0 |
| expected_ANSWER__not_asked | 11 | 10 | -1 |
| expected_REVIEW__predicted_REVIEW | 32 | 32 | +0 |
| expected_REVIEW__predicted_ANSWER | 1 | 1 | +0 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (1)

| case | question | expected | before | after |
|---|---|---|---|---|
| c15_custom_widgets | Company website | 'https://acme.example' | not asked [not_asked] | ANSWER 'https://acme.example' from company_website [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 194 of 195.

