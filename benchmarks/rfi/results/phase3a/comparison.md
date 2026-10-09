# Run comparison

- before: commit `fe54f3486249f4df7e685163240e8530e5c018f7` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `78d7cab4906d9d922ca1e49108281499c7be2d5c` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 82 | 93 | +11 |
| correct answers | 76 | 91 | +15 |
| unsafe answers | 5 | 1 | -4 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 96 | 86 | -10 |
| never asked | 14 | 13 | -1 |
| precision % | 92.7 | 97.8 | +5.1 |
| coverage % | 42.7 | 48.4 | +5.7 |
| review rate % | 50.0 | 44.8 | -5.2 |
| answerable recall % | 48.4 | 58.0 | +9.6 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 76 | 91 | +15 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 1 | 0 | -1 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 67 | 54 | -13 |
| expected_ANSWER__not_asked | 12 | 11 | -1 |
| expected_REVIEW__predicted_REVIEW | 29 | 32 | +3 |
| expected_REVIEW__predicted_ANSWER | 4 | 1 | -3 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (18)

| case | question | expected | before | after |
|---|---|---|---|---|
| c02_paraphrase | In which city is your headquarters located? | 'Bengaluru' | REVIEW [missed_answer] | ANSWER 'Bengaluru' from company.hq_city [correct_answer] |
| c03_qualifiers | Number of full-time employees | 210 | REVIEW [missed_answer] | ANSWER 210 from workforce.full_time_employees [correct_answer] |
| c03_qualifiers | Number of production employees | REVIEW | ANSWER 250 from workforce.employees [unsafe_answer] | REVIEW [correct_review] |
| c05_boolean | Do you support SSO? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from security.sso_supported [correct_answer] |
| c05_boolean | Is data encrypted at rest? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from security.encryption_at_rest [correct_answer] |
| c05_boolean | Do you encrypt data in transit? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from security.encryption_in_transit [correct_answer] |
| c05_boolean | Single sign-on is supported | True | REVIEW [missed_answer] | ANSWER True from security.sso_supported [correct_answer] |
| c06_option_mapping | State | 'CA' | REVIEW [missed_answer] | ANSWER 'CA' from company.state [correct_answer] |
| c08_missing | Cyber insurance coverage amount (USD) | 5000000 | REVIEW [missed_answer] | ANSWER 5000000 from insurance.coverage_usd [correct_answer] |
| c08_missing | Parent company name | REVIEW | ANSWER 'Acme Corp' from company.name [unsafe_answer] | REVIEW [correct_review] |
| c08_missing | Website of parent company | REVIEW | ANSWER 'https://acme.example' from company.website [unsafe_answer] | REVIEW [correct_review] |
| c10_conditional | Does your company process payment card data? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from payments.processes_card_data [correct_answer] |
| c10_conditional | PCI DSS compliance level | 'level2' | not asked [not_asked] | ANSWER 'level2' from payments.pci_level [correct_answer] |
| c13_realistic_security | C.2 Is MFA enforced for administrator accounts? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from access.mfa.admin_accounts [correct_answer] |
| c13_realistic_security | D.3 Who is your incident response point of contact? | 'soc@acme.example' | REVIEW [missed_answer] | ANSWER 'soc@acme.example' from incident.contact [correct_answer] |
| c13_realistic_security | F.2 Security awareness training completion rate (%) | 98 | REVIEW [missed_answer] | ANSWER 98 from policies.security_awareness_training.completion_rate_percent [correct_answer] |
| c13_realistic_security | G.1 Do you perform background checks on employees? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from hr.background_checks [correct_answer] |
| c13_realistic_security | J.2 Date of last penetration test | '2025-11-10' | REVIEW [missed_answer] | ANSWER '2025-11-10' from pentest.last_date [correct_answer] |

## Other changed outcomes (1)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

| case | question | expected | before | after |
|---|---|---|---|---|
| c05_boolean | Is MFA optional? | 'no' | ANSWER 'yes' from security.mfa_required [wrong_answer] | REVIEW [missed_answer] |

Unchanged outcomes: 176 of 195.
