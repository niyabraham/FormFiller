# Implementation progress (working file)

Branch `feature/rfi-completion`, started from `183222e`. This file tracks the eight-requirement completion effort so work can
resume after an interruption. Status words: TODO, IN PROGRESS, DONE (implemented + tested), PARTIAL (see note).

Baseline before any change (Windows 11, Python 3.12.8, Playwright 1.64.1, Chromium 156): **1123 passed, 2 xfailed, 0 skipped
in 533.6 s**.

## Plan and dependencies

| # | Area | Modules | Status |
|---|---|---|---|
| A1 | Network policy + mediated relay (allow-listed requests replayed by Playwright while the browser stays offline) | `netpolicy.py`, `guard.py` | DONE |
| A2 | Navigation state machine (snapshots, transition classification, loop/no-change/validation-error/redirect detection, required-field gate, Back re-verification, policy-permitted form navigation) | `navigation.py`, `steps.py` | DONE |
| A3 | Wizard fixtures: client-side 4 sections; server-backed SPA (sections fetched, autosave); server-rendered form-post wizard (plain + PRG) | `benchmarks/wizards/` | DONE |
| E1 | Field states (proposed/entered/verified/rejected/skipped/needs_review) + questionnaire review summary | `result.py`, `verify.py` | DONE |
| G1 | Versioned progress file, atomic + restrictive writes, resume with reconciliation and re-verification | `progress.py`, `artifacts.py` | DONE |
| G2 | Audit report (Markdown, optional redaction) | `report.py` | DONE |
| C1 | Layered matcher: domain terms, entity scope, topic guard, evidence checks (claims, conflicts), semantic proposals, optional LLM proposals, calibrated categories, provenance | `tokens.py`, `retrieve.py`, `evidence.py`, `semantic.py`, `matching.py`, `llm.py`, `plan.py` | DONE |
| C2 | Matching evaluation + semantic dev/eval sets (eval written and hashed before tuning) | `tools/evaluate_matching.py`, `benchmarks/semantic/` | DONE |
| F1 | Review workflow + local-only token-protected review UI | `review.py`, `review_server.py` | DONE |
| B1 | Network guard: download gate, WebTransport fence, cross-origin iframe and relay-redirect tests, security model doc | `guard.py`, `sharedworkers.py`, `docs/SECURITY_MODEL.md` | DONE |
| D1 | Compatibility fixtures + matrix (fixtures and real pages kept apart) | `tests/web/fixtures/compat/`, `docs/COMPATIBILITY.md` | DONE |
| H1 | CI: strict browser mode, lint, types, dependency audit, launch check, summaries, separate matching and wizard reports | workflow, conftest, pyproject, `tools/evaluate_wizards.py` | DONE (not yet run on GitHub) |
| G3 | Traces opt-in and scrubbed of cookies; proposals marked in the audit report; artifact names git-ignored | `artifacts.py`, `pipeline.py`, `report.py`, `.gitignore` | DONE |
| Docs | README, OUTPUT_DESIGN, MATCHING, SECURITY_MODEL, COMPATIBILITY | `docs/` | DONE |

## Key design decisions

- Network-dependent navigation: the browser context stays offline for the whole walk. A request that matches an explicit
  `AllowRule` is replayed by Playwright's own request client (`route.fetch`) and handed back with `route.fulfill`, one redirect
  hop at a time, each hop re-checked. Requests carrying a value FormFiller entered are blocked unless the rule says
  `answer_data=True`. WebSockets, SharedWorkers, WebRTC and everything else outside HTTP stay blocked in every mode.
- Semantic and LLM layers only PROPOSE (REVIEW with `proposed_answer`); they never enter an answer automatically.
- Certification/compliance claims are decided by stated status evidence only.

## Measurements so far

Matching (no browser), `tools/evaluate_matching.py`; eval set sha256 `77bb654a3a6b1804c903f9fed1f3b16b15a382d6250f3856fc4db0f4800b02cf`:

| set | matcher | precision | coverage | unsafe | proposals right |
|---|---|---|---|---|---|
| semantic dev | before | 0.75 | 0.40 | 2 | - |
| semantic dev | layered | 1.0 | 0.933 | 0 | 1/1 |
| semantic eval | before | 0.778 | 0.412 | 2 | - |
| semantic eval | layered | 1.0 | 0.706 | 0 | 4/4 |

Full pipeline (browser), `tools/evaluate_baseline.py`: RFI dev 99 -> 104 correct, unsafe 1 -> 1 (the known disputed label),
precision 98.0% -> 98.1%, coverage 52.6% -> 55.2%; held-out 107 -> 109 correct, unsafe 0, precision 100%, coverage 39.3% -> 40.1%.
Every changed decision went from a missed answer to a correct one.

Wizard navigation and safety (`tools/evaluate_wizards.py`, 16 scenarios, scenarios sha256
`7ecd18a66a31b209116854100997e1eca0b75c262f96c8aefafcdc4d66fe0b97`): 16/16 expected outcomes, 0 final submissions, 0 requests
reaching the server without a relay record, 0 answers sent without an `answer_data` rule. The first run reported 4 "unrecorded"
requests: the server-backed fixture's own start-up fetch, which arrives after `page.goto` returns; the tool now waits for network
idle before the walk, and the security model records that pre-walk traffic is outside the guard.

SPA fixtures (`tools/evaluate_spa.py --policy`) and widget fixtures unchanged by this work (11/12 safe stops, 0 submissions;
12/12 widgets).

## Findings during the work (each fixed, with a test)

- `<a download>` requests bypass routing and offline emulation: now failed by browser-level DevTools interception (DownloadGate).
- Detaching a page's DevTools session reset offline emulation: sessions are cached and never detached.
- Playwright traces store the portal's session cookies (14 copies in one probe): traces are opt-in and scrubbed.
- The audit report showed a semantic proposal in the answer column: now "proposed, not entered: ...".

## Log

- Repository inspected; baseline recorded.
- A, E, G implemented; full suite after them: 1182 passed, 2 xfailed.
- C implemented and evaluated (above); F implemented with UI tests.
- B, D, H implemented; full suite before the final changes: 1243 passed, 2 xfailed, 0 failed.
- Real page: Selenium's public test form re-run without submitting (same outcome as the owner's earlier run).
- Trace finding fixed (opt-in, scrubbed), proposal label fixed, `.gitattributes` keeps the hashed benchmark files byte-identical.
- Final runs (29 Oct 2026):
  - Windows 11, Python 3.12.8, Playwright 1.64.1, Chromium 156, `FORMFILL_REQUIRE_BROWSER=1`: **1258 passed, 2 xfailed, 0 failed,
    0 skipped** (JUnit: 1260 tests; its 2 "skipped" are the two strict xfails), 905 s while other runs shared the machine.
  - Linux (Ubuntu 24.04, WSL), Python 3.11.15, Playwright 1.64.1, Chromium 156, strict: 1252 passed, 2 xfailed, 0 failed,
    0 skipped, 639 s; wizard benchmark 16/16 with 0 violations; matching evaluation identical to Windows. (Snapshot taken before
    the last six tests; the changed test files were re-run afterwards: 42 passed.)
  - Playwright 1.48.0, Chromium 130, Linux: network guard, extra guard, wizard, policy, progress and review tests: 197 passed,
    1 failed. The failure was the review page test: Playwright 1.48's `wait_for_function` evaluates its predicate with `eval`,
    which the review page's Content-Security-Policy blocks (the page doing its job). The test now waits with locators (same
    case-sensitive text check); the changed test files then passed on 1.48.0 (42 passed) and 1.64.1 (42 passed).
  - ruff (rules in pyproject.toml): no findings; mypy: no issues in 33 files; pip-audit of the declared dependencies (core, dev
    and the `llm` extra; the `semantic` extra was not audited because it pulls in PyTorch): no known vulnerabilities.

## Real-world compatibility testing (30 Oct 2026)

Full report: `REAL_WORLD_TESTING_REPORT.md`. Harness: `tools/evaluate_realworld.py`; forms, ground truth and a result snapshot:
`benchmarks/realworld/`. Branch `test/real-world-compat`, code under test `main` at `bc193c3`. No implementation file changed.

Note: `IMPLEMENTATION_PROGRESS.md`, `source_full.json` and `source_tricky.json` do not exist in this repository. With approval, existing
fictional sources were used ("full" = heldout `h01_saas_security`, "tricky" = rfi `c07_ambiguity`), and progress is recorded here.

| item | status |
|---|---|
| 10 public demo/template forms x 2 sources (+4 supplemental variants), 28 runs, never submitted | DONE |
| Safety: 0 submit events, 0 final-action clicks, 0 walk requests completed outside one explicit read-only rule | DONE (all 28 runs) |
| Precision 62% (10/16), coverage 59% (10/17) on the 10 main forms; 6 wrong fills from 2 root causes | MEASURED |
| What-if for the main matching bug (rule A): precision 62% -> 77%, benchmarks -4 answers of 213 | MEASURED, not implemented |
| Fixes RW-1 to RW-9 (see the report's section 11) | NOT STARTED, awaiting approval |
| Custom dropdown / date-picker / conditional *filling* | NOT ASSESSED: no matching facts in the approved sources; needs a mechanics-only probe source (approval) |
| A real multi-page company questionnaire (needs a portal you are allowed to test) | NOT DONE |

Remaining work, in order: approve and implement RW-1 and RW-2 (each starts with a failing test from the reproduction in the
report); decide on RW-5 (tolerate-list) and RW-6 (guard for single-page runs); measure RW-3 on the benchmarks before changing the
veto; re-run `tools/evaluate_realworld.py` after each fix and compare with `benchmarks/realworld/results/2026-10-30/`.
