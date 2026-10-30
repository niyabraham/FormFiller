# Answer matching: layers, evidence, and evaluation

The source JSON is the only knowledge base. A matching layer may find a fact; only a fact that states what the question asks
may become an answer, and anything uncertain goes to a person (REVIEW) with the reason and the candidates.

## Layers (in the order `plan.plan_question` applies them)

| # | layer | module | can it enter an answer? |
|---|---|---|---|
| 1 | exact and normalised token matching, with scope, period, polarity, entity-name, topic guards | `retrieve.py`, `tokens.py` | yes, above `MIN_CONFIDENCE` with a clear margin |
| 2 | deterministic domain terms and synonyms: SOC 2 / ISO 27001 / PCI DSS spellings, BCP, DRP, DR, RTO, RPO, pentest, vuln, 2FA, IR plan, "how often" = frequency | `tokens.py` | yes (through layer 1) |
| 3 | evidence validation: certification / compliance claims need a stated status; another entity's fact (subsidiary, affiliate, parent) is never the answer; contradictory facts send the question to review; a yes/no fact only answers a yes/no question | `evidence.py`, `retrieve.foreign_entity`, `plan.py` | it decides claims; otherwise it can only block |
| 4 | semantic similarity over key paths (built-in lexical backend; optional local embedding model) | `semantic.py` | **no**: proposals for a reviewer only |
| 5 | optional LLM reranking (Anthropic, explicitly configured) | `llm.py` | **no**: proposals for a reviewer only |
| 6 | confidence categories, calibrated on the development benchmark | `matching.py` | - |

Every plan item records its provenance: `method` (`deterministic`, `status_evidence`, `semantic`, `llm`, `human_approved`,
`human_edited`), `normalized_question`, `source` (the evidence id: the JSON path), `raw_value`, `confidence` and
`confidence_category`, `conflicts`, `validation`, `reason`, and `proposed_answer` for review items.

### Examples the layers must handle (each has a test in `tests/web/test_matching_layers.py`)

* "Do you maintain a documented incident response process?" retrieves `security.incident_response_plan` as a proposal for a
  reviewer (different wording; similarity is not proof), and "Do you have a documented incident response plan?" is answered.
* "Are you SOC 2 certified?" is never answered "Yes" because the source mentions SOC 2 controls or a readiness assessment.
* A subsidiary's certification is not attributed to the company; a question that names the subsidiary may use it.
* `password_min_length: 12` and `password_policy.min_length: 8`, or a "yes" next to a draft status: review, with both facts.
* No evidence: review, never a guess.
* "Are you GDPR compliant?" with only `regulations_in_scope: ["GDPR"]`: review; terminology is not compliance.

## Choosing the semantic backend

| option | install | licence | offline | latency | decision |
|---|---|---|---|---|---|
| built-in lexical (stems, trigrams, the domain-term tokenizer) | none | project | yes | under 1 ms per question | **default** |
| sentence-transformers with a local model | PyTorch + model, several hundred MB | Apache-2.0 (library); model-specific | yes, if the model is on disk | tens of ms on CPU | optional (`pip install .[semantic]`, `FORMFILL_EMBEDDING_MODEL=<local dir>`); never downloaded at run time |
| hosted embedding API | network and an API key | provider terms | no | network-bound | not used: it would send questionnaire text out |

The semantic layer only proposes, so a heavier model would raise reviewer convenience, not answer accuracy; the built-in
backend keeps FormFiller dependency-free and offline. The optional LLM layer (`pip install .[llm]`, `FORMFILL_LLM=anthropic`
plus `FORMFILL_LLM_ALLOW_EXTERNAL=1`) sends only the question and candidate key paths unless `FORMFILL_LLM_SEND_VALUES=1`, may
only choose among the candidates it is shown, and its choice is a proposal. It is tested with a fake client only.

## Evaluation

Two kinds of data, kept separate:

* **Full pipeline benchmarks** (browser; `tools/evaluate_baseline.py`): `benchmarks/rfi` (development) and `benchmarks/heldout`
  (frozen before its first run, but used to guide fixes since, so no longer independent).
* **Matching sets** (no browser; `tools/evaluate_matching.py`): `benchmarks/semantic/dev.json` (rules and thresholds were
  tuned here only) and `benchmarks/semantic/eval.json` (written before the layered matcher existed; sha256
  `77bb654a3a6b1804c903f9fed1f3b16b15a382d6250f3856fc4db0f4800b02cf`). Limitation: the same author wrote both, and the
  baseline's outcomes on the eval set were seen before the layers were implemented, so the eval set is not fully independent.

Precision = correct answers / answers entered; coverage = correct answers / questions that have a correct answer; unsafe = an
answer entered where review was expected; proposals = review items whose offered proposal was right.

| set | matcher | precision | coverage | unsafe | proposals right / offered |
|---|---|---|---|---|---|
| semantic dev (27) | deterministic (before) | 0.75 | 0.40 | 2 | - |
| semantic dev (27) | layered | 1.00 | 0.93 | 0 | 1 / 1 |
| semantic eval (30) | deterministic (before) | 0.78 | 0.41 | 2 | - |
| semantic eval (30) | layered | 1.00 | 0.71 | 0 | 4 / 4 |
| RFI dev benchmark (192, browser) | before -> layered | 98.0% -> 98.1% | 52.6% -> 55.2% | 1 -> 1 | - |
| held-out benchmark (272, browser) | before -> layered | 100% -> 100% | 39.3% -> 40.1% | 0 -> 0 | - |

On both browser benchmarks every changed decision went from a missed answer to a correct one; none regressed. The one unsafe
answer on the RFI dev benchmark is the known disputed label recorded before this work.

### Thresholds and calibration (development data only)

* Semantic proposal threshold 0.30: on the dev set, 0.33 was the lowest similarity of a right proposal and 0.25 the highest of a
  wrong one (`test_matching_layers`, `MatcherConfig`). Few points: a small, honest sample.
* The lexical backend uses fixed feature weights: with IDF, the same match scored 0.16 against a two-key source and 0.33
  against a seven-key one, so no threshold could mean the same thing everywhere.
* Confidence categories (RFI dev benchmark, recorded run): score 1.0 was right 56/56 (held-out 50/50), partial matches 43/45
  (held-out 57/57); both dev errors were partial. Finer bands did not differ. So: `high` = exact key match or a stated status,
  `medium` = partial match above the answer threshold, `low` = a proposal, never entered automatically.
* The topic guard (`tokens.TOPICS`) and the "same fact stored twice" rule for conflicts were added after a dev-benchmark run
  showed a penetration-test date answering a disaster-recovery question, and different facts that share words being treated
  as contradictions.

### Known gaps (found on the eval set, deliberately not tuned)

* "Is your subsidiary Acme Cloud GmbH SOC 2 Type II certified?" stays in review: the claim check also reads the company's own
  readiness assessment (in progress) instead of only the named subsidiary's status. Safe direction; not fixed, so the eval set
  stays untuned.
* Abbreviations not in the table and inflections ("enforce"/"enforced") only reach the semantic layer, so they become proposals
  rather than answers.
