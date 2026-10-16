# Run comparison

- before: commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=True, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 102 | 108 | +6 |
| correct answers | 100 | 106 | +6 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 78 | 72 | -6 |
| never asked | 12 | 12 | +0 |
| precision % | 98.0 | 98.1 | +0.1 |
| coverage % | 53.1 | 56.2 | +3.1 |
| review rate % | 40.6 | 37.5 | -3.1 |
| answerable recall % | 63.7 | 67.5 | +3.8 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 100 | 106 | +6 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 46 | 40 | -6 |
| expected_ANSWER__not_asked | 10 | 10 | +0 |
| expected_REVIEW__predicted_REVIEW | 32 | 32 | +0 |
| expected_REVIEW__predicted_ANSWER | 1 | 1 | +0 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (6)

| case | question | expected | before | after |
|---|---|---|---|---|
| c03_qualifiers | How many customers do you have? | 1800 | REVIEW [missed_answer] | ANSWER 1800 from customers.total [correct_answer] |
| c05_boolean | Do you use sub-processors? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from security.uses_subprocessors [correct_answer] |
| c05_boolean | Are penetration tests performed at least annually? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from security.pen_test_annual [correct_answer] |
| c13_realistic_security | A.2 When was the information security policy last reviewed? | '2026-01-15' | REVIEW [missed_answer] | ANSWER '2026-01-15' from policies.infosec_policy.last_reviewed [correct_answer] |
| c13_realistic_security | C.3 Do you support single sign-on (SSO)? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from access.sso.enabled [correct_answer] |
| c13_realistic_security | G.3 Are you ISO 27001 certified? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from compliance.iso27001.certified [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 189 of 195.
