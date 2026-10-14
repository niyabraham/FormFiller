# Run comparison

- before: commit `ee61e130951d452f106932832dfdba01ec2e1aaa` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `500e9119797e4a4a3dc109d801182d92b38af962` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 105 | 97 | -8 |
| correct answers | 99 | 97 | -2 |
| unsafe answers | 6 | 0 | -6 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 134 | 142 | +8 |
| never asked | 33 | 33 | +0 |
| precision % | 94.3 | 100.0 | +5.7 |
| coverage % | 38.6 | 35.7 | -2.9 |
| review rate % | 49.3 | 52.2 | +2.9 |
| answerable recall % | 48.3 | 47.3 | -1.0 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 99 | 97 | -2 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 3 | 0 | -3 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 80 | 85 | +5 |
| expected_ANSWER__not_asked | 23 | 23 | +0 |
| expected_REVIEW__predicted_REVIEW | 54 | 57 | +3 |
| expected_REVIEW__predicted_ANSWER | 3 | 0 | -3 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (2)

| case | question | expected | before | after |
|---|---|---|---|---|
| h06_insurance_proposal | 4. Number of partners / members | 6 | ANSWER 6 from Number of partners [correct_answer] | REVIEW [missed_answer] |
| h09_retail_vendor | Number of SKUs offered | 64 | ANSWER 64 from Number of SKUs [correct_answer] | REVIEW [missed_answer] |

## Improvements: previously not correct, now correct (3)

| case | question | expected | before | after |
|---|---|---|---|---|
| h02_hospital_supplier | Parent company name | REVIEW | ANSWER 'None' from Parent company [unsafe_answer] | REVIEW [correct_review] |
| h06_insurance_proposal | 10. Gross fees, two financial years ago (GBP) | REVIEW | ANSWER 6840000 from Gross fees last financial year [unsafe_answer] | REVIEW [correct_review] |
| h14_staffing_agency | Number of recruiters who are certified | REVIEW | ANSWER 31 from Headcount.Recruiters [unsafe_answer] | REVIEW [correct_review] |

## Other changed outcomes (3)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

| case | question | expected | before | after |
|---|---|---|---|---|
| h02_hospital_supplier | Sales headcount | 14 | ANSWER 86 from Number of employees [wrong_answer] | REVIEW [missed_answer] |
| h07_ngo_due_diligence | Does the organisation lack a whistleblower policy? | 'no' | ANSWER 'yes' from governance.whistleblower_policy [wrong_answer] | REVIEW [missed_answer] |
| h08_logistics_carrier | Number of refrigerated trailers | 120 | ANSWER 640 from carrier.fleet.trailers [wrong_answer] | REVIEW [missed_answer] |

Unchanged outcomes: 268 of 276.
