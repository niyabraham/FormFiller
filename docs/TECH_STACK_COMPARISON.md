# Technology comparison

Evidence tags: **(V)** read in official docs/repo this session · **(E)** observed by running code in this repo's sandbox · **(K)** general knowledge, *not* re-verified this session · **MVP** needed now · **LATER** justified only by a named trigger.

## 1. Browser automation, for *this* project

Project needs: Python library; open a JS-rendered form; discover controls; fill text/select/radio/checkbox/date; handle iframes, conditional fields, multi-step; read back state; screenshots + trace for audit/debugging; run headless in CI.

| | Playwright (Python) | Selenium | Cypress | WebdriverIO | Robot Framework + Browser | Puppeteer |
|---|---|---|---|---|---|---|
| Language fit | Python API, sync + async (V) | Python bindings (K) | **JavaScript only**, "the only language we'll ever support" (V) | Node.js, JS/TS (V) | keyword syntax; library callable from Python (V) | JavaScript (V) |
| Engine | own driver; Chromium, Firefox, WebKit (V: `--browser chromium/firefox/webkit`) | W3C WebDriver; Chrome, Edge, Firefox, Safari (V) | in-browser runner | WebDriver / BiDi (V, partly) | **Playwright** underneath (V) | CDP + WebDriver BiDi; Chrome, Firefox (V) |
| Auto-waiting / actionability | built in (V) | explicit waits you write (V: "Waiting Strategies") | built in | partial (K) | inherits Playwright (V) | manual-ish (K) |
| Label/role-based locators | `get_by_label`, `get_by_role` preferred (V) | By.ID/CSS/XPath; no first-class label locator (K) | via testing-library plugin (K) | selectors + plugins (K) | via Browser library (V) | CSS/XPath/aria selectors (K) |
| iframes | `frame_locator`, `page.frames` (V, used in tests E) | switch_to.frame (K) | same-origin native; dedicated switch command "under development" (V) | switchFrame (K) | supported (K) | frames API (K) |
| Shadow DOM | CSS pierces open shadow roots (V) | needs JS/helpers (K) | `includeShadowDom` (K) | deep selectors (K) | inherits Playwright | pierce selectors (K) |
| Multi-origin / tabs | yes (K) | yes (K) | single superdomain per test; `cy.origin` (V) | yes (K) | yes | yes |
| Accessibility tree | `aria_snapshot()` YAML (V, E) | none built in (K) | none built in (K) | none (K) | via Playwright | accessibility snapshot (K) |
| Trace / debug | **Trace Viewer**: actions, screenshots, DOM snapshots, network; `context.tracing`, `show-trace` (V) | logs/screenshots; no equivalent built-in viewer (K) | time-travel runner (K) | reporters/screenshots (K) | Playwright traces | screenshots/tracing API (K) |
| Test runner | `pytest-playwright`: fixtures `page/context/browser`, `--tracing retain-on-failure`, `--screenshot`, `--video`, xdist (V) | pytest + own fixtures | built in | built in | built in | none |
| Fit for "drive third-party sites as a library" | yes | yes | **no**: "not a general automation tool… unsuitable for scripting third-party sites" (V) | test framework (V) | adds a DSL we do not need | JS, would force a Node service |
| Verdict | **Adopt** | Viable fallback; more code for the same result | Reject | Reject (language) | Reject (extra layer) | Reject (language) |

**Recommendation: Playwright for Python + Chromium.** (Current PyPI release 1.63.0 (E).) Reasons: it is the only option that is Python-native *and* gives auto-waiting, user-facing locators, iframe/shadow-DOM handling and a trace viewer without extra code. It is also the engine under Robot Framework Browser, Stagehand, Browser Use, Skyvern and Playwright-MCP (V, `GITHUB_LANDSCAPE.md`), so the ecosystem of AI-browser tools stays compatible with it. Guide's earlier "Playwright + Chromium" instinct is confirmed. If we do not use it, we write our own waits and tracing. Selenium would be justified only if a customer mandated Safari/IE or an existing Selenium Grid.

Chromium only for MVP; Firefox/WebKit are one flag away (V) if a portal behaves differently.

### Evidence from this sandbox (E)
`locator.aria_snapshot()` on `<label>Name</label><input required maxlength=40>` returned `textbox "Name"` — **no `required`, no `maxlength`**; the DOM returned `required=True, maxLength=40, validity.valueMissing=True`. Hence discovery uses DOM extraction (with accessible-name rules) and treats ARIA as a naming/semantic aid, not the source of truth.

## 2. AI-browser frameworks: adopt, partly use, study, or avoid?

| Project | Licence (V) | Decision for MVP | Why | What would change it |
|---|---|---|---|---|
| Browser Use | MIT | **Study; maybe later as a *fallback executor*** | free-form agent chooses what to type → can guess; no abstain/provenance | We hit custom widgets Playwright locators cannot drive; use only to *execute a value we already decided* |
| Stagehand | MIT | **Study (closest design)** | `observe()` returns candidate actions without executing, `extract()` is schema-typed — same plan/execute split we want | If hand-written discovery proves too brittle across portals, its DOM+a11y trimming is the thing to borrow |
| Skyvern | **AGPL-3.0** | **Avoid code; design reference only** | network-copyleft; vision-first agent; data is prompt-stuffed so the model picks values | Legal sign-off + proof that vision is required |
| LaVague | Apache-2.0 | Avoid | executes LLM-generated code against the form; maintenance unverified | — |
| Playwright MCP | Apache-2.0 | Study | a11y-snapshot-with-refs idea; plain Playwright gives the same snapshot without an LLM in the loop | If we expose the browser to an LLM agent later |
| BrowserGym / WebArena / MiniWoB++ | Apache-2.0 / Apache-2.0 / MIT | **Test-design inspiration only** | benchmarks of agents, not form fillers | — |

## 3. Testing tools

| Layer | Tool | MVP? | Why / why not |
|---|---|---|---|
| unit (retrieval, plan, validation, result) | **pytest** | MVP | pure functions, no browser; 32 tests |
| browser integration | **pytest + Playwright sync API + local HTML fixtures** | MVP | 16 tests on `file://` pages, deterministic, no network (E) |
| failure simulation | fixtures that mutate the DOM mid-run; `page.route()` for network faults (K) | MVP (DOM) / LATER (network) | route interception needs an HTTP page, not `file://` |
| plugin | `pytest-playwright` (fixtures, `--tracing retain-on-failure`, xdist) (V) | LATER | our own 20-line `conftest.py` fixture is enough; adopt the plugin when we want trace-on-failure in CI and parallelism |
| Cypress / WebdriverIO / Robot | — | No | wrong language or extra layer (see §1) |
| benchmark-style suites | MiniWoB++/WebArena **ideas**: tiny controllable pages, programmatic success check on end-state | MVP (idea) | our fixtures follow this pattern; we do not import their environments |

## 4. Per-stage technology table

| # | Stage | Options | MVP choice | Needed now? | Trigger to go further |
|---|---|---|---|---|---|
| 1 | Browser/page access | Playwright, Selenium, agent frameworks | Playwright + Chromium, caller owns `Page` (login/nav) | **yes** | auth flows → storage-state reuse (V in Robot docs, K in Playwright) |
| 2 | Form/field discovery | DOM extraction; ARIA snapshot; screenshot+VLM | **DOM extractor** (`discover.py`) with accessible-name rules | **yes** | VLM only for canvas/image-only labels/non-semantic widgets |
| 3 | Question extraction | label / aria-labelledby / aria-label / legend / placeholder fallbacks | in extractor | **yes** | page-specific adapters (Google Forms, Typeform) if needed |
| 4 | Question understanding | rules+aliases → classifier → embeddings → LLM structured output | rules/tokens (`understand.py`) | **yes (rules)** | semantic_type needed by downstream logic or retrieval recall too low |
| 5 | JSON validation (source) | none, jsonschema, Pydantic | none (source is trusted JSON) | no | when source schema is contractual → jsonschema |
| 6 | JSON normalisation | flatten to leaves, keep scalar lists | `index_source` | **yes** | unit/currency parsing ("$1.2M") |
| 7 | Question→JSON retrieval | exact; aliases; BM25; embeddings; hybrid | token precision/recall + qualifiers + section bonus | **yes** | measured recall failures on real RFIs |
| 8 | Semantic matching | embeddings (e.g. sentence-transformers, K), LLM | **not used** | no | synonyms table grows unmanageable |
| 9 | Answer selection | threshold+margin rule; LLM picks among ≤5 candidates | rule (`plan.py`) | **yes** | ambiguous/near-tie rate too high → LLM-select with structured output, then re-validate |
| 10 | Validation/transformation | dataclasses+functions; Pydantic; jsonschema | functions (`validate.py`) | **yes** | Pydantic when LLM outputs/API payloads must be parsed |
| 11 | Browser filling | Playwright `fill/select_option/check/set_checked` | as is (`execute.py`) | **yes** | custom widgets → per-widget drivers, then agent fallback |
| 12 | Pre-submit verification | DOM read-back + `checkValidity()` | yes | **yes** | — |
| 13 | Submission | click + wait + success signal | opt-in, refused if required REVIEW | **yes (opt-in)** | per-portal success rules |
| 14 | Post-submit verification | success text / URL change / ID | text + URL | **yes (basic)** | confirmation-ID extraction, email receipt |
| 15 | Human review | file/CLI → web UI | `review_items` in JSON | **yes (data only)** | review UI + resubmit loop |
| 16 | Logging/audit | structured JSON + trace | `result.json`, `trace.zip` | **yes** | append-only store |
| 17 | Structured outputs | dataclasses → JSON | `to_json()` | **yes** | publish JSON Schema for consumers |
| 18 | API/backend | FastAPI etc. | none | no | when another system must trigger runs |
| 19 | Persistence | files → SQLite/Postgres | none | no | review UI / multi-user |
| 20 | Observability | trace viewer, logs; later OpenTelemetry/metrics | trace viewer | **yes (trace)** | production runs at volume |

## 5. Validation stack (smallest sufficient)

| Option | Strength | Cost here | Verdict |
|---|---|---|---|
| plain dataclasses + functions | zero dependency; constraints already live on `Control` | hand-written checks | **MVP** (what we built) |
| Pydantic v2 | typed parsing, good for LLM structured outputs/API (K) | new dependency, models duplicate `Control` | **LATER**: when an LLM or API boundary appears |
| jsonschema | validates JSON against a published schema (K) | useful for *contracts*, not per-field business rules | **LATER**: for the source contract or for publishing the result schema |
| dateparser / dateutil | free-form dates (K) | would accept ambiguous `03/04/2026` — dangerous | **No**: ISO-only, else REVIEW |

## 6. Retrieval ladder and RAG

| Level | Method | Used now | Notes |
|---|---|---|---|
| 1 | exact key match | yes (part of score) | |
| 2 | alias/rule normalisation | **yes** | `tokens.py` |
| 3 | embeddings similarity | no | add when synonyms cannot be enumerated |
| 4 | hybrid (lexical + embeddings) | no | |
| 5 | LLM chooses among retrieved candidates | no | only among ≤5 candidates, structured output, result re-validated, path must be one of the candidates |

Terms: **JSON field retrieval** = finding which leaf answers a question (what we do). **Semantic search** = ranking by meaning. **Embeddings** = vectors enabling semantic search. **Vector database** = storage/ANN index for many vectors. **RAG** = retrieving *text passages* to put into an LLM prompt so it *composes* an answer. **Knowledge-base retrieval** = RAG over a curated Q&A/document library.

**Do we need RAG? No, not for this requirement.** The source is structured JSON of modest size; the answer is a *value that already exists*, not text to be composed. A vector database is unnecessary at this scale (thousands of leaves can be ranked in memory (K)). RAG becomes justified if (a) the source grows long unstructured policy text from which narrative answers must be composed, or (b) a library of past answers is added (the Loopio/Conveyor-style knowledge base, `GITHUB_LANDSCAPE.md`). Without RAG, narrative questions ("Describe your incident response process") simply go to REVIEW — which is the safe behaviour.
