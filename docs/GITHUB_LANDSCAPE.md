# GitHub / OSS landscape: JSON -> RFI web form

Method: WebFetch of each GitHub repo page (README + sidebar). `gh api` was blocked in this session and robots.txt blocked /commits pages, so LAST-COMMIT DATES ARE UNVERIFIED for all repos. Stars and license are as shown on the repo page on 2026-10-06. Features not stated on the repo page are marked UNVERIFIED.

## Bottom line
No project found covers the full pipeline (web RFI -> analyse questions -> retrieve JSON values -> answer-or-REVIEW plan -> validate -> browser fill -> verify -> structured result). Two families exist and do not meet:
1. Browser agents (browser-use, Skyvern, Stagehand, LaVague, playwright-mcp) fill forms from a natural-language prompt. They have no per-question retrieval from a JSON source, no abstain/REVIEW policy, no verify step, and no per-field result schema. Results are task-level.
2. Questionnaire responders (rfp-autopilot, security-questionnaire-responder) have retrieval, confidence, citations and a REVIEW flag. They work on Excel/YAML, not web forms.
Closest single item: Form-Flow-AI (field detection + profile data + filled/unfilled result), but it is a small hobby project, so treat it as a reference only.

## Browser agent frameworks

### browser-use/browser-use  https://github.com/browser-use/browser-use
- License: MIT. ~116.7k stars. Last commit UNVERIFIED (10,299 commits).
- Solves: LLM agent that drives a browser to complete a natural-language task.
- Architecture: Python agent loop (observe -> LLM -> action); custom tool registry; also hosted cloud and CLI.
- Browser: Playwright / Chrome (CDP); can use real Chrome profiles.
- AI: pluggable (OpenAI, Anthropic, own BU model).
- Page understanding: DOM-derived element list plus screenshots.
- Input: task prompt string. Output: agent history, ActionResult objects; typed output is possible via custom tools (details UNVERIFIED).
- Learn: action loop, custom tools, DOM-indexed elements.
- Don't copy: free-form agent deciding what to type. It has no abstain policy, so it will guess.
- Relevance: candidate for the fill step only, if driven with a pre-computed plan.

### Skyvern-AI/skyvern  https://github.com/Skyvern-AI/skyvern
- License: AGPL-3.0 (README: AGPL, except anti-bot features in the managed cloud). Non-trivial: network-use copyleft. Avoid embedding or modifying in a product without legal review.
- ~23.1k stars. Last commit UNVERIFIED (6,802 commits).
- Solves: workflow automation with vision-LLM agents; explicitly strong on form filling.
- Architecture: multi-agent (planner/actor/validator style, per README "swarm"), workflow orchestration. Playwright, CDP.
- AI: vision LLMs (OpenAI, Anthropic, Gemini, Bedrock, Azure, Ollama, OpenRouter).
- Page understanding: screenshot plus DOM, vision-first.
- Input: natural-language prompt (data passed inside the prompt). Output: structured extraction via `data_extraction_schema` (JSON schema).
- Learn: validation step after actions; workflow blocks; JSON-schema outputs.
- Don't copy: the AGPL code; prompt-stuffed data (the model chooses values).
- Relevance: design inspiration only.

### browserbase/stagehand  https://github.com/browserbase/stagehand
- License: MIT. ~25.5k stars. Last commit UNVERIFIED (1,546 commits). TS, Python, Go SDKs.
- Primitives: act(), extract() (Zod/Pydantic schemas), observe() (returns candidate selectors/actions without executing), agent.
- Page understanding: hybrid DOM + accessibility-tree trimming. Caching and self-healing.
- Input: natural-language instructions. Output: schema-validated objects from extract().
- Learn: observe-then-act separation (matches "plan, then execute"); schema-typed extraction; caching of resolved actions.
- Don't copy: treating act() as the whole workflow.
- Relevance: most architecturally aligned for the "analyse form" (extract field schema) and "fill" (act with explicit value) steps.

### lavague-ai/lavague  https://github.com/lavague-ai/lavague
- License: Apache-2.0. ~6.4k stars. Last commit and maintenance status UNVERIFIED (716 commits, 95 open issues). Fetch summary called it active; I did not confirm it. Check before depending on it.
- Architecture: World Model (objective + page -> instruction) and Action Engine (instruction + HTML chunks -> generated Selenium/Playwright code).
- AI: configurable LLM, default GPT-4o. Page understanding: raw HTML chunks, RAG-style.
- Output: generated code, Gradio demo, QA (Gherkin) mode.
- Learn: separating planning from code-gen.
- Don't copy: executing LLM-generated code against forms.
- Relevance: low.

### microsoft/playwright-mcp  https://github.com/microsoft/playwright-mcp
- License: Apache-2.0. ~36.8k stars. Last commit UNVERIFIED (579 commits).
- Exposes Playwright to an MCP client. Page understanding: accessibility-tree snapshots (browser_snapshot), no vision needed. Optional pixel mode via `--caps=vision`.
- Tools: browser_fill_form (multi-field), browser_click, browser_type, browser_navigate, browser_find, etc. Output: structured text snapshots, not a result schema.
- Learn: a11y snapshot with element refs is a good, cheap form-analysis input; batched fill_form call.
- Don't copy: leaving the LLM to drive the whole session.
- Relevance: strong as a tool layer or as a reference for ARIA-based extraction. Plain Playwright gives the same ARIA snapshot without an LLM in the loop.

## Benchmarks / environments (not products)

### ServiceNow/BrowserGym  https://github.com/ServiceNow/BrowserGym
- Apache-2.0 (from page footer; LICENSE file not opened). ~1.3k stars. Last commit UNVERIFIED.
- Gym environment over Playwright/Chromium; observations DOM, AXTree, screenshot; agent-defined action space; bundles MiniWoB, WebArena, WorkArena, etc.
- Learn: observation-space design (DOM+AXTree+screenshot in one dict); element-id (bid) annotation.
- Relevance: use for evaluation ideas only. Not a form-filler.

### web-arena-x/webarena  https://github.com/web-arena-x/webarena
- Apache-2.0. ~1.6k stars. Last commit UNVERIFIED.
- Self-hosted sites, 812 tasks, JSON task configs, a11y-tree/HTML observations, ID-based actions, HTML trajectory reports; evaluation by checking final state/answer.
- Learn: evaluating by programmatic end-state checks and JSON task configs.
- Relevance: concept for a test harness (verify by DOM state). Tasks are not RFI forms.

### Farama-Foundation/miniwob-plusplus  https://github.com/Farama-Foundation/miniwob-plusplus
- MIT. ~401 stars. Described as maintenance mode. Last commit UNVERIFIED.
- 100+ small synthetic web tasks, Selenium, Gymnasium API; includes form/utterance-to-field tasks.
- Relevance: tiny synthetic tests; not useful beyond unit-test fixtures.

## Questionnaire / form-specific OSS (all small, hobby-scale)

### richsudaniman/rfp-autopilot  https://github.com/richsudaniman/rfp-autopilot
- License: NOT SPECIFIED (no license seen), so do not copy code. 0 stars, 13 commits.
- Pipeline: retrieve (TF-IDF word + char n-grams, acronym expansion) -> threshold validate -> LLM draft. Score <0.48: skip, no draft, "Needs SME review"; 0.48-0.65: flagged; >=0.65: high. Model told to return `INSUFFICIENT_CONTEXT` when the approved answers don't address the question. Every answer gets source IDs.
- Input/output: .xlsx in, same .xlsx out with answer/confidence/source/status colours. No web forms.
- Learn: retrieval-gated abstention BEFORE the LLM, and an explicit insufficient-context sentinel. This is the "answer or REVIEW, never guess" pattern.
- Don't copy: thresholds (tuned on one sample), the library (not a JSON source).

### anthonyonazure/security-questionnaire-responder  https://github.com/anthonyonazure/security-questionnaire-responder
- License: MIT. 2 stars, 3 commits.
- LangGraph; parallel per-question: retrieve KB entries -> answer with cited KB entries -> confidence; <0.7 -> flagged for human. Output YAML (canonical), JSON, XLSX. No web forms.
- Learn: canonical structured result with citations plus confidence per item.

### atharvakarval-dev/Form-Flow-AI  https://github.com/atharvakarval-dev/Form-Flow-AI
- License: MIT. 21 stars, 230 commits. README claims (95% accuracy, 111 tests) are unverified marketing.
- FastAPI + Playwright; field detection from HTML elements incl. shadow DOM; LLM maps question text to a profile key (e.g. "How long have you lived here?" -> years_at_address); custom Google Forms/Typeform extractors; returns a MagicFillResult with filled vs unfilled fields.
- Learn: question-text -> data-key mapping step; filled/unfilled result.
- Don't copy: voice, CAPTCHA, human-mimic typing features.
- Relevance: closest in shape to the full pipeline, but I did not read its code; UNVERIFIED whether it abstains, validates or verifies after fill.

Other: GitHub topics pages `security-questionnaire`, `rfp-automation`, `automation-form-filling` exist (https://github.com/topics/security-questionnaire). I only saw the topic listings and did not review repos beyond those above. salmandigitalsolutions/security-questionnaire-responder appeared in results; NOT reviewed.

## Commercial approaches (vendor marketing pages and third-party reviews; NOT independently verified)
- Conveyor: scores answer confidence and separates "needs review" from "good to go"; answers cited to source docs from an approved knowledge base; auto-tags reviewers; browser extension auto-completes portal questionnaires (conveyor.com product page). Method for unanswerable questions is not stated.
- Vanta (via third-party review): AI drafts from security docs and past questionnaires, knowledge base with source citations, approval workflows with role permissions, audit trails. Reviewer advice: check that drafts trace to sources.
- Drata, Secureframe: described as similar (third-party review only).
- Loopio, Responsive/RFPIO, SafeBase: UNVERIFIED (no page read this session).
- Common pattern: approved-source grounding, per-answer citation, confidence tiers driving a human review queue, approval workflow, audit trail. Portal/browser filling is an add-on (extension) on top of the drafting engine, i.e. answer first, fill second.

## Gaps nobody covers (what the project must build)
1. Form-first analysis producing a typed question schema (id, label, type, options, required, constraints) from the DOM/ARIA.
2. JSON-source retrieval keyed per question, with path-level provenance.
3. Answer plan with explicit ANSWER/REVIEW states and an option-set check (value must be a valid option).
4. Post-fill read-back verification of the DOM against the plan.
5. Per-question structured result.

## Suggested reuse
Playwright (ARIA snapshot) or Stagehand-style observe/extract for step 1; rfp-autopilot's gate-before-LLM and sentinel idea for abstention; security-questionnaire-responder's result shape; playwright-mcp fill_form-style batched fill. Avoid Skyvern code (AGPL).

---
*Provenance of this file: compiled by a research sub-task that read each repository's GitHub page/README on 2026-10-06. Stars/licences are as displayed on those pages; last-commit dates and several feature claims are explicitly marked UNVERIFIED. Re-check licences from each repo's LICENSE file before any reuse; do not treat star counts as quality evidence.*
