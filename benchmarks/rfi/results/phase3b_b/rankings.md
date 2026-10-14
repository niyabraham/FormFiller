# Candidate-ranking comparison
- before: `fed244ee001926bbd842e83f7c1f4eb0babeda38` dirty=False
- after : `c918f1fe5a1968f2e3094918296c311a90c4deb8` dirty=False
- questions compared: 195; top candidate changed: 3; same top, different runner-up: 0; same top and runner-up, score changed: 7; unchanged: 185

## Top candidate changed
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|
| c04_ Street | organization.profile.address.billing.street (1.20) | organization.profile.address.hq.street (1.20) | organization.profile.address.hq.street (1.20) | organization.profile.address.billing.street (0.72) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c04_ City | organization.profile.address.billing.city (1.20) | organization.profile.address.hq.city (1.20) | organization.profile.address.hq.city (1.20) | organization.profile.address.billing.city (0.72) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c04_ CISO name | organization.leadership.0.name (0.87) | organization.leadership.1.name (1.20) | organization.leadership.1.name (0.87) | organization.leadership.0.name (0.52) | REVIEW -> ANSWER | missed_answer -> correct_answer |

## Same top candidate, different runner-up
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|

## Same candidates, changed scores
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|
| c03_ Security contact email | security.contact.email (0.80) | security.contact.email (0.80) | contacts.billing.email (0.67) | contacts.billing.email (0.40) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c03_ Billing contact email | contacts.billing.email (0.80) | contacts.billing.email (0.80) | contacts.general.email (0.40) | contacts.general.email (0.24) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| c04_ Street | organization.profile.address.billing.street (1.20) | organization.profile.address.billing.street (1.20) | organization.profile.address.hq.street (1.20) | organization.profile.address.hq.street (0.72) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c04_ Postal code | organization.profile.address.billing.postal_code (1.20) | organization.profile.address.billing.postal_code (1.20) | organization.profile.address.hq.postal_code (1.20) | organization.profile.address.hq.postal_code (0.72) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c04_ CEO email | organization.leadership.0.email (0.87) | organization.leadership.0.email (1.20) | organization.leadership.1.email (0.87) | organization.leadership.1.email (0.52) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| c07_ How many employees does the subsidiary have? | subsidiary.employees (0.86) | subsidiary.employees (0.86) | company.employees (0.40) | company.employees (0.24) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| c07_ Name | applicant.name (1.20) | applicant.name (1.20) | company.name (1.00) | company.name (0.60) | ANSWER -> ANSWER | correct_answer -> correct_answer |
