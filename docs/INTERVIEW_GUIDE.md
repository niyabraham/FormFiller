# Interview guide

How to explain FormFiller accurately in an internship or placement interview. Everything here was checked against the source and the
documentation at `main` `873d1c9` (PR #28 merged); where a number comes from a document, the document is named. If the code and this
guide ever disagree, the code is right: open the file named next to the claim.

**Ground rules for the conversation.** It is a *tested prototype*: measured on local fixtures, on pre-written ground truth, and on ten
public demo and template forms. It has not been proven on real company RFI portals and it does not work on every website. Say what you
measured, on what, and what you did not measure. That honesty is the strongest thing about the project.

Contents: [30-second introduction](#1-the-30-second-introduction) / [2-minute explanation](#2-the-2-minute-technical-explanation) /
[architecture walkthrough](#3-architecture-walkthrough) / [15 likely questions](#4-fifteen-likely-technical-questions) /
[5 challenging questions](#5-five-challenging-questions) / [numbers](#6-numbers-to-know-and-how-to-state-them) /
[code map](#7-code-map-for-a-live-walkthrough).

## 1. The 30-second introduction

"FormFiller is a Python tool that fills in web-based vendor security questionnaires from a JSON file of facts about your company. For
every question it finds the matching fact, checks the value against the field, types it in with Playwright, and reads the page back to
confirm it landed. When it is not sure, it leaves the field empty and shows a person the evidence. It never submits a form by itself.
I built it to see how far a deterministic, explainable system can go before you need a model, and I measured it honestly, including the
cases where it was wrong."

## 2. The 2-minute technical explanation

"Questionnaires are the same few hundred questions over and over, and a wrong answer is worse than a blank one, so the design principle
is *abstain rather than guess*.

The flow is form first, then source, then answers, then browser. Playwright opens the page and discovers every visible control with its
label, section, type, options and constraints. The JSON source is flattened into facts, each with a dotted path such as
`business_continuity.rto_hours`. Each question is scored against every fact: the words of the question and of the fact's key are
normalised, with synonyms and domain terms like RTO and SOC 2 expanded, and the score is an F1 of how much of the key the question
explains and how much of the question the key explains, with a bonus when the form section names the fact's parent. Then a series of
*caps* push a score under the 0.6 answer threshold when something is off: a scope word the key lacks, a different time period, opposite
polarity, or a neighbouring concept. A planner then decides per question: `ANSWER` with a value, a source path and a confidence
category, or `REVIEW` with a reason and sometimes a proposal. Only that plan reaches the browser; the reasoning code never imports
Playwright.

After typing, the page is read back, and a field is `verified` only if the live control holds the value and the browser calls it valid.
A person reviews everything that was not answered on a local, token-protected page; their decisions are validated and go through the
same fill-and-verify path. Submission is never part of the default flow. I evaluated it on development and held-out benchmarks,
on ten public demo forms, and with regression probes, and I documented what is still wrong."

## 3. Architecture walkthrough

### 3.1 Modules and responsibilities

| Layer | Modules (`formfill/web/`) | Responsibility |
|---|---|---|
| Browser (reads/acts on the page) | `discover.py`, `execute.py`, `verify.py` | Find controls and tag them with `data-ff-id`; enter an answer with Playwright actions; read it back |
| Reasoning (no Playwright import) | `understand.py`, `tokens.py`, `retrieve.py`, `evidence.py`, `validate.py`, `plan.py`, `matching.py`, `semantic.py`, `llm.py` | Turn controls into questions, score facts, check claims, validate values, decide ANSWER or REVIEW |
| Orchestration and results | `pipeline.py`, `result.py`, `report.py`, `artifacts.py` | `run_form` / `run_url`, field states, overall status, `result.json`, audit report, safe file writing |
| Human review | `review.py`, `review_server.py` | `review.json`, local review page, decisions fed back as a planner |
| Multi-step and safety | `navigation.py`, `steps.py`, `guard.py`, `netpolicy.py`, `sharedworkers.py`, `progress.py` | Wizard state machine, Next/Back rules, network guard, resume file |

The one object that crosses from reasoning to browser is the `AnswerPlanItem` list. Full diagrams: [`ARCHITECTURE.md`](ARCHITECTURE.md).

### 3.2 End-to-end workflow

1. `run_form` discovers the controls (`discover`), only visible ones are asked.
2. `understand` makes a `Question` per control (cleaned text, expected answer type taken from the control, canonical tokens).
3. `plan.build_plan` produces an `AnswerPlanItem` per question (the decision cascade, below).
4. Only `ANSWER` items are entered (`verify.fill_one` -> `execute.fill_control`). A fill failure is recorded and the run continues.
5. Answering can reveal fields (a conditional question), so discovery repeats for up to `max_rounds` (3) rounds.
6. After a confirmation window (default 1000 ms, at most 10000) every control is read back (`verify.judge`).
7. `result.field_state` puts each question in exactly one state (`proposed`, `entered`, `verified`, `rejected`, `skipped`, `needs_review`) and `overall_status` derives `FILLED`, `NEEDS_REVIEW` or `FAILED`.
8. Artifacts are written; a person reviews; their decisions re-enter the same pipeline as a planner; a person submits in the portal.

### 3.3 How source facts are represented and retrieved

`retrieve.index_source` flattens the JSON into `Leaf` records: the dotted path, the value, the normalised words of the key (`leaf_tokens`)
and of its parents (`parent_tokens`), plus the time period the path names and, for list items, which item it belongs to. Nulls and empty
values are skipped and lists of scalars stay whole. Retrieval is *question-driven*: each question is scored against every leaf, so
the JSON is never mapped to the form field by field. The words come from `tokens.tokenize`: lower-case, split camelCase and snake_case,
drop stopwords and parenthetical hints (an acronym in brackets is kept), expand phrases and acronyms (RPO, RTO, BCP, SOC 2 ...), stem, expand synonyms.

### 3.4 Matching, confidence and abstention

For question words Q, key words L and parent-path words P:

```
precision = |Q & L| / |L|                 is the whole key explained by the question?
recall    = (|Q & L| + 0.5 * |(Q & P) - L|) / |Q|
score     = F1(precision, recall)  x 0.6 if the question has a scope word the key lacks  + 0.2 if the form section names a parent
```

Then caps that stay *below* the 0.6 answer threshold (`UNEXPLAINED_CAP` 0.5, `POLARITY_CAP` and `PERIOD_CAP` 0.3): a capped candidate stays
visible to the reviewer but cannot be auto-answered. `plan.plan_question` applies, in order: control disabled -> attestation wording ->
certification/compliance claim (answered only from a *stated status*) -> retrieval -> can this control take that value? -> another
entity's fact -> score below `MIN_CONFIDENCE` (0.6) -> placeholder value ("N/A", "TBD") -> a runner-up within `MIN_MARGIN` (0.15) holding a
different value -> validation against the control -> a contradiction elsewhere in the source -> `ANSWER`. Anything that fails is `REVIEW`
with a reason in plain English.

Confidence is a *category*, not a calibrated probability: `high` is an exact match or a stated status, `medium` a partial match above
the threshold, `low` is a proposal only (`matching.confidence_category`). Proposals come from a built-in lexical similarity search
(`semantic.py`: cosine over fixed-weight features, offline, deterministic; threshold 0.30) or an optional, off-by-default LLM that can
only choose among candidates the deterministic layer already allowed. Neither can enter a value.

### 3.5 How neighbouring-concept confusion is prevented

*The bug.* With no RPO fact in the source, "Recovery point objective (RPO) in hours" was answered `8`, the RTO value. The question and
`rto_hours` share *recovery*, *objective* and *hours* and differ by one word each; overlap plus the section bonus scored 0.87, over the
threshold, and nothing treated that word as a distinction. The same shape hit "encrypted in transit" against `data_at_rest`,
"authentication" against `authorization_method`, and retention against deletion.

*The fix (PR #27).* `retrieve.sibling_words`: after removing words the key explains and words that are not concepts, if exactly one
word is left on each side and at least one word is shared, the candidate is capped at 0.5 and its value is not offered as a proposal
either. It is structural: there is no list of concept pairs. What is *not* a swap: related word forms and abbreviations, acronym echoes,
units and "period"/"format", time words, question auxiliaries ("was", "when"), numbers, and a short `SAME_CONCEPT` list that exists
because each entry blocked a valid match. Two follow-ups: a key about a topic the question never names ("retention", "deletion") needs
*more than half* of the question explained, and a proposal is never a different kind of contact detail (phone for an e-mail question).

*Evidence and limits.* 130 regression tests (47 of the first 121 failed on the old code); 62 probes written for it went from 23 wrong
automatic answers to 0; no decision changed on the development or held-out benchmarks. But: the probes were written by the author, the
held-out set was used while refining the exclusions so it is not independent for this change, the guard only sees one-word swaps
(plus the topic rule), and it removed two plausible reviewer proposals and made one worse. It is a mitigation, not understanding.
Details: [`MATCHING.md`](MATCHING.md#neighbouring-concepts-rpo-is-not-rto).

### 3.6 Dynamic forms, SPAs, widgets and multi-page navigation

*Conditional fields:* answering one question can reveal another; discovery repeats for up to three rounds (the demo's Data Protection
Officer name appears only after the GDPR answer). *Widgets:* open shadow DOM, same-origin iframes, late-rendering pages, styled radios and
checkboxes (set through their own label, never forced), react-select-style dropdowns (read back from the displayed value), ARIA comboboxes;
file uploads, password fields, `contenteditable`, unknown ARIA widgets and signature canvases are *reported, never touched*
([`COMPATIBILITY.md`](COMPATIBILITY.md)). *Multi-step forms* are opt-in (`DiscoveryPolicy`): `navigation.py` is a state machine that settles,
fills, verifies, gates on unanswered required questions, presses one allow-listed Next, confirms the page really moved, and re-verifies. It
stops on `no_change`, `validation_error`, `redirected`, `required_unresolved`, `max_steps`, an unexpected dialog or a blocked network
request, and it never presses submit-type buttons. Walks run behind a network guard (`guard.py`, `netpolicy.py`) that blocks requests unless
an explicit `AllowRule` relays them; it is explicitly *not* absolute isolation ([`SECURITY_MODEL.md`](SECURITY_MODEL.md)).

### 3.7 Playwright automation and read-back verification

Entry uses Playwright actions on the control (fill, select an option, check a box, click the control's own label), never page scripts.
`verify.judge` then reads the live control back and compares with the planned answer using the control's own semantics; an item is
`verified` only when the value matches *and* the browser reports the control valid. If a text answer is gone on the same node after a UI
framework attached to it since the answer was typed, it is re-entered once and reported as such; a second loss is a failure
(`reenter_after_hydration`). A read-back proves the page holds the value, not that a server saved it, and the docs say so.

### 3.8 Human review and submission safety

The review page (`review_server.py`) listens on `127.0.0.1` only, refuses other bind addresses, checks the Host header, and requires a
random token (`secrets.token_urlsafe(24)`). A person can approve a proposal, type an answer, reject, or acknowledge a declaration; typed
values are validated against the control, and an attestation cannot be approved or edited by the page or the code behind it. The default
run never submits. `submit=True` is a caller-side opt-in that is *refused* (outcome `SKIPPED`) while a declaration is open, an answer
failed, a required question is in review, or an unsupported control has no explicit human decision; a multi-step walk never submits.

### 3.9 Testing strategy and evaluation

*Automated tests* (about 1,500, exact count in the README; `FORMFILL_REQUIRE_BROWSER=1` makes a missing browser an error): unit tests of
the reasoning layer, browser tests against local fixture pages (widgets, wizards, SPAs, network guard, resume), regression tests written
*first and seen failing* for the defects found in the later phases (the method is logged in [`PROGRESS.md`](PROGRESS.md); examples: `test_concept_confusion.py`, `test_one_word_labels.py`, `test_page_furniture.py`), and
`test_demo_rfi.py`, which pins every number the demo guide quotes. CI runs ruff, mypy and pip-audit, and the suite on Python 3.11 and 3.12.
*Evaluations* (separate sets, never combined): RFI development set and a second set (full pipeline in a browser), the `semantic` matching
sets (no browser), wizard/SPA/widget fixtures, ten public demo forms with ground truth written before the answers were seen, and the
neighbouring-concept probes. Metrics: *precision* = correct answers / answers entered; *coverage* = correct answers / questions that have a
correct answer; a *wrong answer* is an entered, wrong value; an *abstention* is correct when the source has no answer and a *missed answer*
when it did.

### 3.10 Limitations and future work

Limitations (full list in the README): not validated on real RFI portals; matching is conservative so coverage is about 56 % (development)
and 40 % (second set); wording-sensitive (`notify` vs `notification`); concept-confusion protection is a one-word-swap guard; one-page runs
are not network-guarded (RW-6); the network guard has documented gaps; unsupported controls are only reported; saving is not confirmed; the
review page is for one local reviewer. Future work: validate on permitted real portals with a test set written by someone else, a reviewed
final-step workflow, OS-level egress control, multi-reviewer review, and a committed probe set of confusable pairs.

## 4. Fifteen likely technical questions

**1. Why not just use an LLM?** Three reasons: a wrong answer in a security questionnaire is costly, so I needed every answer to be
explainable (a source path, a score, a reason), repeatable and cheap to test; the data is small and structured, so a lexical and
rule-based matcher goes a long way; and I wanted to measure what a deterministic baseline can do first. An optional LLM layer exists, off
by default, and can only re-rank candidates the deterministic layer allowed and propose; it has only been tested against a fake client.

**2. Why "form first, then source"?** The question drives the search: every question is scored against every fact, so the form decides
what is asked and the JSON is never forced onto the form field by field. A fact with no question is simply unused; a question with no
fact goes to review.

**3. How is a question matched to a fact?** Both are normalised to concept tokens (`tokenize`), then scored with an F1 of precision
(is the key explained by the question?) and recall (is the question explained by the key and its parent path?), with a section bonus and
penalties for missing scope words. Details in 3.4.

**4. What does your confidence mean? Is it calibrated?** It is a coarse category, not a probability: `high` (exact or stated status),
`medium` (partial match above the threshold) and `low` (proposal only). The thresholds (0.6, margin 0.15, proposal 0.30) were chosen on the
development benchmark; they are not calibrated on real portals, and the docs say so.

**5. How do you decide to abstain?** A cascade of checks, each ending in `REVIEW` with a reason: disabled control, attestation wording,
a certification claim without a stated status, a weak score, another entity's fact, a placeholder value, two plausible facts with
different values, a value the control cannot take, or a contradiction in the source. A capped candidate stays visible but is never entered.

**6. How did you fix RPO versus RTO, and how do you know it works?** See 3.5. In short: a structural guard for pairs of phrases that differ by one word,
plus a topic rule; 130 regression tests, 62 probes (23 wrong answers to 0), and no benchmark decision changed. And what I do *not* know:
the probes are mine, the held-out set influenced the exclusions, and a pair that differs in more than one word can still be confused.

**7. How do you handle dynamic and conditional fields?** After entering answers it discovers the form again, up to three rounds, and
fills newly revealed controls; in a wizard it does the same per step. Fields that appear long after an interaction can still be missed
(documented).

**8. How do you fill custom widgets such as styled radios or react-select?** By structure and always through Playwright actions: a
styled radio whose input is covered is set by clicking its own label and reading the state back; a react-select-style dropdown is
recognised by the class names of its displayed value and read back from what it displays. These were tested on few examples, and other
libraries are untested.

**9. What does "verified" mean, and why read back?** A `.fill()` call that returns is not evidence: pages clear, reformat or reject
values. `verified` means that after a confirmation window the live control held the planned value and the browser reported it valid. It
does not mean the server saved it.

**10. Why is the reasoning layer separate from Playwright?** So it can be tested fast and exhaustively without a browser (most
matching tests need none), and so a bug in matching cannot, by construction, touch a page: the only thing that crosses is the plan.

**11. How do multi-page forms work, and what stops a walk?** An opt-in state machine presses one recognised Next at a time and confirms
the page moved. It stops on a loop or no change, a validation error, a redirect, an unanswered required question, a dialog, the step
limit, or a blocked network request, and it never presses submit-type buttons. Network requests are blocked unless an explicit allow
rule relays them; that guard has documented gaps.

**12. How is human review designed, and why can't it submit?** The review page is local-only and token-protected; each card shows the
evidence, method, confidence and reason. Decisions are re-validated against the field when saved and when applied, and they run through
the same fill-and-verify path as automatic answers. There is deliberately no submit control: approving is not a signature.

**13. How do you test something like this?** In layers: pure unit tests for tokenisation, scoring, validation and planning; browser tests
on local fixture pages for each control pattern and for the guard; regression tests written first and seen failing for the defects found later; a
demo test file that pins the documented outputs; static checks (ruff, mypy, pip-audit) in CI. Evaluations are kept apart from tests.

**14. How do you evaluate matching quality?** Precision, coverage, wrong answers and abstentions on separate sets: a development set
(98.1 % precision, 55.7 % coverage), a second set (100 %, 40.1 %, no longer independent), matching sets with no browser, and ten public
forms with ground truth written before the answers were seen (100 % precision, 59 % coverage). I never merge them into one score.

**15. What did testing on real public forms find?** The first run measured 62 % precision and 59 % coverage with six wrong fills, from
two root causes (a one-word label answered from a longer key; a page's own search box treated as a question). After fixing those:
100 % precision, no wrong fills on the same forms. Five more mechanics problems were fixed; seven findings are documented and open,
including that a one-page run has no network guard. See [`REAL_WORLD_TESTING_REPORT.md`](../REAL_WORLD_TESTING_REPORT.md).

## 5. Five challenging questions

**1. "Your second benchmark was used while you refined the matcher. Why should I believe 100 % precision on it?"**
You should not read it as independent evidence, and the README says so. It was frozen before its first run, but since then it guided fixes,
including the exclusion rules of the RPO/RTO change, so it only shows that no decision changed. The independent evidence is thin: ten
public forms (a small sample, not company portals) with ground truth written before the answers were seen. The right next step is a test
set written by someone else, on permitted real portals.

**2. "Coverage is 40-56 %. Is that useful?"**
It is a deliberate trade-off. At the threshold I chose, 98 to 100 % of the answers it enters are right, and every unanswered question
arrives with a reason and evidence, so a person's time goes to the uncertain ones. Coverage is bounded by wording sensitivity (the
matcher compares words) and by the source data. Whether that is *useful* depends on the cost of a wrong answer against the cost of a
review, which I have not measured with real users. Lowering the threshold raises coverage and wrong answers together; I did not do that.

**3. "Isn't the one-word-swap guard just a heuristic hack? What about pairs it does not see?"**
Yes, it is a heuristic, and I say so. It is structural (no list of concept pairs) and the exclusions are principled word classes plus a
short list that exists because each entry blocked a valid match. It does not understand meaning: a pair that differs in two words, or a
pair I did not think of, can still be confused. Mitigations in place are that confusion is capped below the answer threshold, proposals
are never entered, and a human reviews. What I would do next is keep a probe set of confusable pairs in the repository and, if
measurement justified it, consider an embedding model for *flagging* near-pairs.

**4. "Would you point it at a real portal?"**
Not unattended. It has not been validated on real portals; a one-page run has no network guard (an open finding); the multi-step guard blocks
the channels I tested but is not absolute isolation and was measured on two Playwright versions only; it never submits by default and a
person reviews every uncertain answer. On a real portal I would use fictional or approved data, a multi-step walk with an explicit
allow-list policy, review everything, and submit myself.

**5. "What if the reviewer just approves everything, or the source data is stale?"**
Neither is solved by software. Some proposals are irrelevant (in the demo, three of six do not answer their question), so a careless
reviewer could approve a wrong one; the page shows the evidence and the reason precisely to make that harder, and typed values are
validated, but there is one local reviewer and no audit of who decided. Stale or wrong facts produce confidently wrong answers:
correctness is bounded by the source, and contradictions *within* the source are caught and sent to review, but a wrong fact stated once
is not. A reviewed final-step workflow and multi-reviewer audit trail are listed as future work.

## 6. Numbers to know, and how to state them

| Number | Say it as | Never say |
|---|---|---|
| Demo: 22 verified, 11 for review, 1 unsupported; after review 29 / 4 / 1 | "On this hand-written fixture" | "accuracy" |
| Development set: 98.1 % precision, 55.7 % coverage (192 questions, 1 disputed wrong answer) | "measured on my development set" | "accuracy on real forms" |
| Second set: 100 % precision, 40.1 % coverage (272 questions) | "no longer independent: it guided fixes, including the neighbouring-concept rules" | "held-out result" without the caveat |
| Ten public demo forms: 100 % precision (10 of 10), 59 % coverage (10 of 17) | "a small sample on public practice forms" | "works on real portals" |
| 62 probes: 23 wrong automatic answers to 0; 130 regression tests | "probes I wrote for this change; a regression check, not a benchmark" | "concept confusion is solved" |
| About 1,500 automated tests, ruff, mypy, pip-audit clean | "all pass in CI on Python 3.11 and 3.12" (see the README for the exact count) | "tested on every website" |

## 7. Code map for a live walkthrough

| To show | Open |
|---|---|
| The whole flow | `pipeline.py` (`run_form`) |
| How a fact is represented | `retrieve.py` (`Leaf`, `index_source`) |
| The score and its caps | `retrieve.py` (`assess_leaf`, `sibling_words`, the `*_CAP` constants) |
| The abstention cascade | `plan.py` (`plan_question`, `MIN_CONFIDENCE`, `MIN_MARGIN`) |
| Normalisation, acronyms, synonyms | `tokens.py` (`tokenize`) |
| Why "verified" means something | `verify.py` (`judge`), `execute.py` (`read_back`) |
| The review page and its protections | `review_server.py`, `review.py` |
| The submission gate | `pipeline.py` (search for `SKIPPED`), `tests/web/test_submit_gate.py` |
| The regression tests for RPO/RTO | `tests/web/test_concept_confusion.py` |
| The demo and its pinned outputs | `demo_web.py`, `docs/demo/`, `tests/web/test_demo_rfi.py` |
