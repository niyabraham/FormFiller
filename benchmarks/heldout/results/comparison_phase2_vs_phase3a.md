# Run comparison

- before: commit `78d7cab4906d9d922ca1e49108281499c7be2d5c` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `ee61e130951d452f106932832dfdba01ec2e1aaa` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 97 | 105 | +8 |
| correct answers | 87 | 99 | +12 |
| unsafe answers | 10 | 6 | -4 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 142 | 134 | -8 |
| never asked | 33 | 33 | +0 |
| precision % | 89.7 | 94.3 | +4.6 |
| coverage % | 35.7 | 38.6 | +2.9 |
| review rate % | 52.2 | 49.3 | -2.9 |
| answerable recall % | 42.4 | 48.3 | +5.9 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 87 | 99 | +12 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 6 | 3 | -3 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 89 | 80 | -9 |
| expected_ANSWER__not_asked | 23 | 23 | +0 |
| expected_REVIEW__predicted_REVIEW | 53 | 54 | +1 |
| expected_REVIEW__predicted_ANSWER | 4 | 3 | -1 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (1)

| case | question | expected | before | after |
|---|---|---|---|---|
| h10_gov_procurement | Companies House registration number | '07894213' | ANSWER '07894213' from supplier.company_number [correct_answer] | REVIEW [missed_answer] |

## Improvements: previously not correct, now correct (14)

| case | question | expected | before | after |
|---|---|---|---|---|
| h01_saas_security | 1.2 Total number of employees | 412 | REVIEW [missed_answer] | ANSWER 412 from headcount.total [correct_answer] |
| h01_saas_security | 1.3 Customer support personnel (headcount) | 57 | REVIEW [missed_answer] | ANSWER 57 from headcount.support [correct_answer] |
| h01_saas_security | 2.6 Security contact email (CISO) | 'ciso@brightloop.io' | REVIEW [missed_answer] | ANSWER 'ciso@brightloop.io' from security.ciso_email [correct_answer] |
| h03_bank_kyc | Is adverse media screening NOT performed on counterparties? | REVIEW | ANSWER 'yes' from compliance.adverse_media_screening [unsafe_answer] | REVIEW [correct_review] |
| h04_construction_prequal | State of licensure | 'FL' | REVIEW [missed_answer] | ANSWER 'FL' from Company Information.License state [correct_answer] |
| h05_university_grant | Total budget requested (USD) | 742500 | REVIEW [missed_answer] | ANSWER 742500 from project.requested_budget.total [correct_answer] |
| h05_university_grant | State of applicant institution | 'OR' | REVIEW [missed_answer] | ANSWER 'OR' from institution.state [correct_answer] |
| h06_insurance_proposal | 4. Number of partners / members | 6 | REVIEW [missed_answer] | ANSWER 6 from Number of partners [correct_answer] |
| h07_ngo_due_diligence | Number of full-time staff | 22 | REVIEW [missed_answer] | ANSWER 22 from people.staff_full_time [correct_answer] |
| h07_ngo_due_diligence | Number of part-time staff | 5 | REVIEW [missed_answer] | ANSWER 5 from people.staff_part_time [correct_answer] |
| h12_api_platform | Does the product support single sign-on? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from Product.Supports SSO [correct_answer] |
| h13_manufacturing_quality | Total employees (headcount) | 520 | REVIEW [missed_answer] | ANSWER 520 from plant.employees.total [correct_answer] |
| h13_manufacturing_quality | Defect rate last year (PPM) | 38 | REVIEW [missed_answer] | ANSWER 38 from plant.ppm_last_year [correct_answer] |
| h14_staffing_agency | Headquarters state | 'PA' | REVIEW [missed_answer] | ANSWER 'PA' from Headquarters.State [correct_answer] |

## Other changed outcomes (3)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

| case | question | expected | before | after |
|---|---|---|---|---|
| h03_bank_kyc | Company registration number (UEN) | '201934118K' | ANSWER 'Dry bulk commodity trading' from entity.business_activity [wrong_answer] | REVIEW [missed_answer] |
| h07_ngo_due_diligence | Were there any related-party transactions last fiscal year? | 'no' | ANSWER 'yes' from governance.has_no_related_party_transactions [wrong_answer] | REVIEW [missed_answer] |
| h12_api_platform | Is SCIM provisioning unsupported? | 'yes' | ANSWER 'no' from Product.Supports SCIM provisioning [wrong_answer] | REVIEW [missed_answer] |

Unchanged outcomes: 258 of 276.
