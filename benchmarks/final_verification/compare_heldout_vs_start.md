# Run comparison

- before: commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=False, benchmark vheldout-1.0.0 `0d275842d567c759`
- after : commit `4ffe03be74634932215fc4e3edb876beb33fd7ac` pipeline_dirty=True, benchmark vheldout-1.0.0 `0d275842d567c759`
- thresholds before {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}, after {'MIN_CONFIDENCE': 0.6, 'MIN_MARGIN': 0.15}

| metric | before | after | delta |
|---|---|---|---|
| auto-answered | 107 | 119 | +12 |
| correct answers | 107 | 119 | +12 |
| unsafe answers | 0 | 0 | +0 |
| fill failed | 0 | 0 | +0 |
| REVIEW | 133 | 122 | -11 |
| never asked | 32 | 31 | -1 |
| precision % | 100.0 | 100.0 | +0.0 |
| coverage % | 39.3 | 43.8 | +4.5 |
| review rate % | 48.9 | 44.9 | -4.0 |
| answerable recall % | 52.2 | 58.0 | +5.8 |

## Confusion matrix

| cell | before | after | delta |
|---|---|---|---|
| expected_ANSWER__predicted_ANSWER__correct | 107 | 119 | +12 |
| expected_ANSWER__predicted_ANSWER__incorrect_value | 0 | 0 | +0 |
| expected_ANSWER__predicted_ANSWER__fill_failed | 0 | 0 | +0 |
| expected_ANSWER__predicted_REVIEW | 76 | 65 | -11 |
| expected_ANSWER__not_asked | 22 | 21 | -1 |
| expected_REVIEW__predicted_REVIEW | 57 | 57 | +0 |
| expected_REVIEW__predicted_ANSWER | 0 | 0 | +0 |
| expected_REVIEW__not_asked | 10 | 10 | +0 |

## Regressions: previously correct, now not (0)

_none_

## Improvements: previously not correct, now correct (12)

| case | question | expected | before | after |
|---|---|---|---|---|
| h01_saas_security | 2.3 Date of most recent penetration test | '2026-02-17' | REVIEW [missed_answer] | ANSWER '2026-02-17' from security.pen_test.last_date [correct_answer] |
| h02_hospital_supplier | Federal Tax ID (EIN) | '84-2917736' | REVIEW [missed_answer] | ANSWER '84-2917736' from Tax identification number (EIN) [correct_answer] |
| h03_bank_kyc | Authorised signatory's email address | 'meilin@kestrelmaritime.sg' | REVIEW [missed_answer] | ANSWER 'meilin@kestrelmaritime.sg' from authorised_signatories.0.email [correct_answer] |
| h03_bank_kyc | Is any beneficial owner a politically exposed person (PEP)? | 'no' | REVIEW [missed_answer] | ANSWER 'no' from beneficial_owners.0.pep [correct_answer] |
| h07_ngo_due_diligence | Name of affiliated chapter or branch | 'Riverbend Ohio' | REVIEW [missed_answer] | ANSWER 'Riverbend Ohio' from affiliates.chapters.0.name [correct_answer] |
| h08_logistics_carrier | USDOT Number | '2847731' | REVIEW [missed_answer] | ANSWER '2847731' from carrier.dotNumber [correct_answer] |
| h08_logistics_carrier | Does your fleet use electronic logging devices (ELD)? | 'yes' | REVIEW [missed_answer] | ANSWER 'yes' from carrier.eld.enabled [correct_answer] |
| h08_logistics_carrier | ELD provider | 'Samsara' | not asked [not_asked] | ANSWER 'Samsara' from carrier.eld.provider [correct_answer] |
| h08_logistics_carrier | Do you also hold freight broker authority? | 'no' | REVIEW [missed_answer] | ANSWER 'no' from carrier.brokerAuthority [correct_answer] |
| h09_retail_vendor | D-U-N-S Number | '117384920' | REVIEW [missed_answer] | ANSWER '117384920' from DUNS Number [correct_answer] |
| h10_gov_procurement | Number of employees | 64 | REVIEW [missed_answer] | ANSWER 64 from employees.count [correct_answer] |
| h11_franchise_supplier | States in which the franchisor operates | ['TX', 'OK', 'LA'] | REVIEW [missed_answer] | ANSWER ['TX', 'OK', 'LA'] from franchisor.states_operating [correct_answer] |

## Other changed outcomes (0)

Neither side is correct (e.g. one unsafe answer replaced by another, or a reason changed).

_none_

Unchanged outcomes: 264 of 276.
