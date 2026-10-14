# Blind labelling task

A deterministic system fills web RFI / vendor-questionnaire forms from a JSON source. For each question in
`audit_input.json` decide what a careful human should do, using ONLY that case's `source_json`.

Rules:
* Work only in this folder. Do not read any other path on the machine.
* Do not guess what any software would do; decide what is correct.
* decision = "ANSWER" only if (a) exactly one reasonable reading of the question exists, (b) the JSON contains the value (or a plain,
  confident derivation: a boolean inversion, or mapping the value to the matching option), and (c) you can name the dotted JSON path
  (list indices as digits). Otherwise decision = "REVIEW" (data absent/null/empty, requested scope not in the data, two different values
  plausible, unmappable option, narrative that needs composing, declaration/consent, constraint violated, or a careful human would ask).
  When in doubt choose REVIEW. Do not force an ANSWER the JSON cannot justify.
* For ANSWER give `value` = what the control must hold: text/textarea/tel/email/url -> the string as in the JSON; number -> number;
  date -> "YYYY-MM-DD"; select/radio -> the option VALUE; multiselect/checkbox_group -> list of option values; checkbox -> true/false.
  and `path`.
* Add a short `why` (one sentence) for every question.

Output: write `audit_labels.json` = {"labels":[{"case":..., "control":..., "decision":..., "value":..., "path":..., "why":...}, ...]}
covering EVERY question in audit_input.json exactly once (use a script to generate/validate the file if you like). Final reply: the count
labelled, count ANSWER vs REVIEW, and a statement of any path opened outside this folder (should be none).
