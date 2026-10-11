# Candidate-ranking comparison
- before: `fed244ee001926bbd842e83f7c1f4eb0babeda38` dirty=False
- after : `c918f1fe5a1968f2e3094918296c311a90c4deb8` dirty=False
- questions compared: 276; top candidate changed: 3; same top, different runner-up: 6; same top and runner-up, score changed: 15; unchanged: 252

## Top candidate changed
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|
| h10_ Companies House registration number | parent.company_number (0.50) | supplier.company_number (0.50) | supplier.company_number (0.50) | parent.company_number (0.30) | REVIEW -> REVIEW | missed_answer -> missed_answer |
| h11_ Number of employees at the San Antonio store | franchisee.employees (0.40) | franchisee.locations.0.employees (0.67) | franchisee.locations.0.employees (0.40) | franchisee.locations.0.store_no (0.50) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h11_ Employees at store #131 | franchisee.employees (0.50) | franchisee.locations.1.employees (0.80) | franchisee.locations.0.employees (0.50) | franchisee.employees (0.50) | REVIEW -> ANSWER | missed_answer -> correct_answer |

## Same top candidate, different runner-up
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|
| h03_ Name of authorised signatory | authorised_signatories.0.name (0.80) | authorised_signatories.0.name (0.80) | beneficial_owners.0.name (0.50) | entity.registered_name (0.50) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h03_ Name of AML compliance officer | compliance.aml_officer.name (0.97) | compliance.aml_officer.name (0.97) | authorised_signatories.0.name (0.40) | entity.registered_name (0.33) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h05_ PI first name * | pi.first_name (0.91) | pi.first_name (0.91) | institution.name (0.50) | pi.last_name (0.50) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h05_ PI last name * | pi.last_name (0.91) | pi.last_name (0.91) | institution.name (0.50) | pi.first_name (0.50) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h06_ 7. Number of staff in the Leeds office | Office locations.0.staff (0.67) | Office locations.0.staff (0.91) | Office locations.1.staff (0.67) | Total staff (0.40) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h14_ Headquarters state | Headquarters.State (0.86) | Headquarters.State (0.86) | Branch offices.0.state (0.40) | Licensed states (0.30) | ANSWER -> ANSWER | correct_answer -> correct_answer |

## Same candidates, changed scores
| question | top before | top after | runner-up before | runner-up after | decision | outcome |
|---|---|---|---|---|---|---|
| h03_ Authorised signatory's email address | authorised_signatories.0.email (0.57) | authorised_signatories.0.email (0.57) | compliance.aml_officer.email (0.33) | compliance.aml_officer.email (0.20) | REVIEW -> REVIEW | missed_answer -> missed_answer |
| h03_ Entity contact email | contact.email (0.67) | contact.email (0.67) | authorised_signatories.0.email (0.50) | authorised_signatories.0.email (0.30) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h07_ Name of affiliated chapter or branch | affiliates.chapters.0.name (0.55) | affiliates.chapters.0.name (0.55) | org.name (0.40) | org.name (0.24) | REVIEW -> REVIEW | missed_answer -> missed_answer |
| h08_ Auto liability limit (USD) | carrier.insurance.autoLiability.limit (0.87) | carrier.insurance.autoLiability.limit (0.87) | carrier.insurance.cargo.limit (0.50) | carrier.insurance.cargo.limit (0.30) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h08_ Cargo insurance limit (USD) | carrier.insurance.cargo.limit (0.87) | carrier.insurance.cargo.limit (0.87) | carrier.insurance.autoLiability.limit (0.75) | carrier.insurance.autoLiability.limit (0.45) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h08_ Number of dock doors at the Omaha terminal | carrier.terminals.0.doors (0.50) | carrier.terminals.0.doors (0.77) | carrier.terminals.1.doors (0.50) | carrier.terminals.1.doors (0.30) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h10_ Supplier name | supplier.name (1.06) | supplier.name (1.06) | bid_contact.name (0.67) | bid_contact.name (0.40) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h10_ Employers' liability insurance limit (GBP) | insurance.employers_liability.limit (0.87) | insurance.employers_liability.limit (0.87) | insurance.public_liability.limit (0.77) | insurance.public_liability.limit (0.46) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h10_ Public liability insurance expiry date | insurance.public_liability.expiry (0.87) | insurance.public_liability.expiry (0.87) | insurance.employers_liability.expiry (0.77) | insurance.employers_liability.expiry (0.46) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h11_ Legal name of franchisee entity | franchisee.name (0.33) | franchisee.name (0.33) | franchisor.name (0.24) | franchisor.name (0.14) | REVIEW -> REVIEW | missed_answer -> missed_answer |
| h11_ Franchisor legal name | franchisor.name (0.40) | franchisor.name (0.40) | franchisee.name (0.30) | franchisee.name (0.18) | REVIEW -> REVIEW | missed_answer -> missed_answer |
| h11_ Number of employees of the franchisee | franchisee.employees (0.86) | franchisee.employees (0.86) | franchisee.locations.0.employees (0.86) | franchisee.locations.0.employees (0.51) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h11_ Year the franchisor was founded | franchisor.year_founded (0.77) | franchisor.year_founded (0.77) | franchisee.year_founded (0.67) | franchisee.year_founded (0.40) | REVIEW -> ANSWER | missed_answer -> correct_answer |
| h11_ Joint venture name | joint_venture.name (1.00) | joint_venture.name (1.00) | franchisee.name (0.50) | franchisee.name (0.30) | ANSWER -> ANSWER | correct_answer -> correct_answer |
| h14_ Staff at the Newark branch | Branch offices.0.staff (0.67) | Branch offices.0.staff (0.91) | Branch offices.1.staff (0.67) | Branch offices.1.staff (0.40) | REVIEW -> ANSWER | missed_answer -> correct_answer |
