# Authoring notes

Method: for each of 14 organisations (SaaS security, hospital supplier, bank KYC, construction prequal, university grant,
insurance proposal, NGO due diligence, logistics carrier, retail vendor, government procurement, franchise supplier,
API platform, manufacturing quality, staffing agency) I wrote a form and a company JSON file of a different shape
(7 engineer-natural-style cases, rest form-aligned), then labelled each question by the spec's policy: ANSWER only with
one reading, a present value and a source path; otherwise REVIEW. Every question has a note; contestable labels are tagged.
Cases live in cases_a..d.py (helpers in hh.py), exposed through heldout_cases.py as CASES.

Coverage: scoped/time/geo/role qualifiers, related entities (parent, subsidiary, beneficial owner...), polarity wording,
nested/camelCase/list-of-objects data, missing/null/ambiguous values, option mapping and date/number constraints,
conditional and enable_when fields, wizard steps, one dynamic step (h09), hidden ABSENT controls, narratives, declarations,
varied controls and label styles.

Judgement calls / known deviations from the spec's targets: scored total is 272 (above the ~170 aim, above the 150 minimum);
ANSWER:REVIEW is about 76:24 rather than 60:40; only 4 hidden ABSENT controls exist; `bad_for` label style is not used.

Compliance: I worked only inside this folder. Paths opened outside it: none.
