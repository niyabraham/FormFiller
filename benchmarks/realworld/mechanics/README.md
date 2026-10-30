# Mechanics-only test data (NOT company data, NOT used for matching metrics)

`source_mechanics.json` holds fictional values keyed to the **question wording of specific public demo forms**
(a car-brand dropdown, a 0-10 rating, a student registration form, Selenium's practice page). It exists to answer one question:
*can FormFiller operate custom dropdowns, custom radio groups, date pickers, tag inputs, dependent selects and conditionally
revealed questions, and does the page really end up holding the value?*

Because every key repeats the form's own wording, matching is trivially exact. These runs therefore say **nothing** about
answer-matching precision or coverage and are never added to those numbers. Run them with
`python tools/evaluate_realworld.py run --mechanics --out-dir output/realworld-mechanics` (and `score --mechanics`); results are kept
in `benchmarks/realworld/results/mechanics-*/`.

Nothing is submitted; the same guard, harness and safety stops apply as for the main evaluation.
