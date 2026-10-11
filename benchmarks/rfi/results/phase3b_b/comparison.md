# Run comparison

- before: commit `fed244ee001926bbd842e83f7c1f4eb0babeda38` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- after : commit `c918f1fe5a1968f2e3094918296c311a90c4deb8` pipeline_dirty=False, benchmark v1.0.0 `b5a81217376675b9`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 94 | 101 | +7 |
| correct answers | 92 | 99 | +7 |
| unsafe answers | 1 | 1 | +0 |
| fill failed | 1 | 1 | +0 |
| REVIEW | 85 | 78 | -7 |
| never asked | 13 | 13 | +0 |
| precision % | 97.9 | 98.0 | +0.1 |
| coverage % | 49.0 | 52.6 | +3.6 |
| review rate % | 44.3 | 40.6 | -3.7 |
| answerable recall % | 58.6 | 63.1 | +4.5 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 92 | 99 | +7 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 1 | 1 | +0 |
| expected_ANSWER__predicted_REVIEW | 53 | 46 | -7 |
| expected_ANSWER__not_asked | 11 | 11 | +0 |
| expected_REVIEW__predicted_REVIEW | 32 | 32 | +0 |
| expected_REVIEW__predicted_ANSWER | 1 | 1 | +0 |
| expected_REVIEW__not_asked | 2 | 2 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (7)

| case | question | expected | before | after |
|---|---|---|---|---|
| c03_qualifiers | Security contact email | 'security@acme.example' | REVIEW [missed_answer] | ANSWER 'security@acme.example' from security.contact.email [correct_answer] |
| c04_nested | Street | '12 MG Road' | REVIEW [missed_answer] | ANSWER '12 MG Road' from organization.profile.address.hq.street [correct_answer] |
| c04_nested | City | 'Bengaluru' | REVIEW [missed_answer] | ANSWER 'Bengaluru' from organization.profile.address.hq.city [correct_answer] |
| c04_nested | Street | 'PO Box 44' | REVIEW [missed_answer] | ANSWER 'PO Box 44' from organization.profile.address.billing.street [correct_answer] |
| c04_nested | Postal code | '400001' | REVIEW [missed_answer] | ANSWER '400001' from organization.profile.address.billing.postal_code [correct_answer] |
| c04_nested | CISO name | 'Priya Nair' | REVIEW [missed_answer] | ANSWER 'Priya Nair' from organization.leadership.1.name [correct_answer] |
| c04_nested | CEO email | 'ravi@acme.example' | REVIEW [missed_answer] | ANSWER 'ravi@acme.example' from organization.leadership.0.email [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 188 of 195.
