# Run comparison

- before: commit `fed244ee001926bbd842e83f7c1f4eb0babeda38` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `c918f1fe5a1968f2e3094918296c311a90c4deb8` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 97 | 107 | +10 |
| correct answers | 97 | 107 | +10 |
| unsafe answers | 0 | 0 | +0 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 142 | 132 | -10 |
| never asked | 33 | 33 | +0 |
| precision % | 100.0 | 100.0 | +0.0 |
| coverage % | 35.7 | 39.3 | +3.6 |
| review rate % | 52.2 | 48.5 | -3.7 |
| answerable recall % | 47.3 | 52.2 | +4.9 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 97 | 107 | +10 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 85 | 75 | -10 |
| expected_ANSWER__not_asked | 23 | 23 | +0 |
| expected_REVIEW__predicted_REVIEW | 57 | 57 | +0 |
| expected_REVIEW__predicted_ANSWER | 0 | 0 | +0 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (10)

| case | question | expected | before | after |
|---|---|---|---|---|
| h06_insurance_proposal | 7. Number of staff in the Leeds office | 28 | REVIEW [missed_answer] | ANSWER 28 from Office locations.0.staff [correct_answer] |
| h08_logistics_carrier | Cargo insurance limit (USD) | 250000 | REVIEW [missed_answer] | ANSWER 250000 from carrier.insurance.cargo.limit [correct_answer] |
| h08_logistics_carrier | Number of dock doors at the Omaha terminal | 48 | REVIEW [missed_answer] | ANSWER 48 from carrier.terminals.0.doors [correct_answer] |
| h10_gov_procurement | Employers' liability insurance limit (GBP) | 10000000 | REVIEW [missed_answer] | ANSWER 10000000 from insurance.employers_liability.limit [correct_answer] |
| h10_gov_procurement | Public liability insurance expiry date | '2026-08-31' | REVIEW [missed_answer] | ANSWER '2026-08-31' from insurance.public_liability.expiry [correct_answer] |
| h11_franchise_supplier | Number of employees of the franchisee | 310 | REVIEW [missed_answer] | ANSWER 310 from franchisee.employees [correct_answer] |
| h11_franchise_supplier | Year the franchisor was founded | 2005 | REVIEW [missed_answer] | ANSWER 2005 from franchisor.year_founded [correct_answer] |
| h11_franchise_supplier | Number of employees at the San Antonio store | 42 | REVIEW [missed_answer] | ANSWER 42 from franchisee.locations.0.employees [correct_answer] |
| h11_franchise_supplier | Employees at store #131 | 38 | REVIEW [missed_answer] | ANSWER 38 from franchisee.locations.1.employees [correct_answer] |
| h14_staffing_agency | Staff at the Newark branch | 11 | REVIEW [missed_answer] | ANSWER 11 from Branch offices.0.staff [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 266 of 276.
