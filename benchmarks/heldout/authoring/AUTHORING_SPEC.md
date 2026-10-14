# Held-out benchmark authoring spec

You are an independent author. A deterministic system fills web RFI / vendor-questionnaire forms from a JSON source.
Your job: write NEW forms, their JSON source data, and the CORRECT answer key. You are NOT evaluating or improving the
system, and you must not know how it works.

## Hard rules (independence)
* Work ONLY inside this directory. Do NOT read, list or search any other path (no repository, no other benchmarks, no
  reports, no result files, no pipeline code). Python stdlib only. At the end, state in AUTHORING_NOTES.md that you
  complied, listing every path you opened outside this directory (it should be none).
* Do not try to find out what the system gets wrong. Write the forms a careful RFI author and a careful data owner would
  actually write. Do not tune forms toward any hypothesised weakness.
* The ground truth is what a careful human would enter, NEVER what software might do.

## Deliverable
`heldout_cases.py` defining `CASES`: a list of dicts, each with
`id` ("h01_xxx", unique), `description`, `source` (JSON-able dict = the company's data), `source_style`
("form-aligned" = keys resemble form wording, or "engineer-natural" = keys as a developer would name them, snake_case,
nested, lists of objects), `qs` (list of Q built with `A`/`R`/`H` from `benchmark_render.py`; read that file's `Q`
dataclass for the options: kind, options, section, when, enable_when, step, style, attrs, tags, trap, note,
invalid_source), optional `submit` and `dynamic_steps`.
Run `python check.py` until it prints OK. Also write `AUTHORING_NOTES.md` (methodology, intent of each case, any
judgement calls, compliance statement).

## Size and mix
* >= 12 cases (aim 14) and >= 150 scored questions (ANSWER + REVIEW; hidden ABSENT controls are extra, not scored).
  Aim for ~170 scored. 8-16 questions per case.
* Each case: a different organisation, industry and vocabulary (SaaS vendor security review, hospital supplier onboarding,
  bank KYC, construction subcontractor prequalification, university grant application, insurance proposal, NGO due
  diligence, logistics carrier onboarding, retailer vendor registration, government procurement...). Different JSON
  shape per case. Do not copy one case's wording into another.
* Roughly 60% of the questions should have a correct ANSWER, 40% a correct REVIEW (data absent, scope not supported,
  ambiguous, unmappable, narrative/composition, declarations).
* At least 4 cases with engineer-natural JSON, at least 4 form-aligned, the rest mixed.

## Must be covered (spread across cases, with several questions each)
1. Ordinary exact-ish questions, and paraphrases/synonyms (staff, personnel, headcount, workforce, people, FTEs...).
2. Scoped questions where the scope is or is NOT in the data (e.g. "number of part-time nurses" when only a total headcount
   exists -> REVIEW; when a `part_time_nurses` key exists -> ANSWER). Qualifiers of every kind: time, geography, role,
   status, entity.
3. Related entities: parent / subsidiary / affiliate / branch / group / franchisee / joint venture / beneficial owner /
   authorised signatory vs the company itself; the JSON sometimes has them, sometimes not, sometimes has both an entity
   and a related entity for the same field (then an unscoped question is genuinely ambiguous -> REVIEW).
4. Negative and polarity-sensitive wording: optional/required, enabled/disabled, supported/unsupported, applicable/not
   applicable, "Is X NOT performed", "Do you refrain from...", "without", "excluding", "other than". JSON booleans may be
   named with the same polarity, the opposite polarity, or neutrally. Label ANSWER only if the correct value is
   unambiguous from the data (including a plain logical inversion a careful person would make with confidence);
   otherwise REVIEW.
5. Nested JSON, snake_case/camelCase keys, lists of objects (e.g. `offices: [{city, headcount}]`), keys named only
   `enabled`/`exists`/`count`/`total`/`value` under a meaningful parent.
6. Missing values (key absent, null, empty string) and ambiguous values (two different values plausible).
7. Choice controls whose option labels/values differ from the JSON text ("United States" vs value "US", employee count vs
   bands "51-250", "Yes/No/N/A", state names vs codes, currencies, month names) and date/number constraints
   (min/max/maxlength/pattern attrs; a date given as "14 March 2009" or "03/14/2009" in JSON for an ISO date input;
   a value that violates a constraint -> REVIEW with `invalid_source`).
8. Conditional fields (`when`), enabled-after-answer fields (`enable_when`), one multi-step wizard (`step`), at least one
   dynamically created step (`dynamic_steps`), plus hidden-must-stay-hidden ABSENT controls.
9. Diverse controls and label styles: text, number, date, email, url, tel, textarea, select, multiselect, radio,
   checkbox, checkbox_group, file, a few `custom_*`/`shadow_text`, and label styles (label_for, wrap, aria_label,
   aria_labelledby, placeholder, div_label, table, bad_for). Question text should include numbering prefixes, trailing
   asterisks, "(optional)" / "(required)", help-text style hints, acronyms in parentheses, in some forms.
10. Narrative questions (textarea): REVIEW unless the JSON has a ready-made text field that fully answers it.
11. Declarations/attestations/consents: REVIEW.

## Labelling policy (apply strictly)
* ANSWER only if (a) exactly one reasonable reading of the question exists, (b) the JSON contains the value (or a plain,
  confident derivation such as a boolean inversion or mapping a value to the matching option), and (c) you can name
  the JSON path (`source`, dotted, list indices as digits). For derivations, `source` is the leaf the value comes from.
* REVIEW whenever the data is absent, the scope asked for is not in the data, two different values are plausible, or a
  careful human would stop and ask. When in doubt, REVIEW. Do not force an ANSWER the JSON cannot justify.
* `answer` = what the control must hold afterwards. text/textarea/tel/email/url: the string exactly as in the JSON.
  number: the number. date: "YYYY-MM-DD". select/radio: the option VALUE. multiselect/checkbox_group: list of option
  values. checkbox: True/False. (Only choice controls may transform the JSON value; check.py enforces this.)
* `note` on EVERY question: why this is the correct outcome. Mark labels you consider contestable with tag "contestable".
* Tag each question (tags=[...]) with the hazards it exercises, e.g. "scoped", "related_entity", "polarity", "nested",
  "snake_case", "missing", "ambiguous", "option_mapping", "date_constraint", "conditional", "multistep", "custom_widget",
  "narrative", "paraphrase", "realistic", "distractor". Include plausible distractor keys in the JSON (similar names that
  answer a DIFFERENT question) as real data owners' files do.
* Control `name`s: unique within a case. Use a mix of meaningful names and opaque ones (q17, fld_a4).
