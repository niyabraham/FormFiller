# FormFill PoC

A proof of concept for **automatically filling forms using structured source data**, with abstain-first policy: never guess, always REVIEW when uncertain.

Supports two form types:

1. **Legacy PDF AcroForms** — direct field matching and filling
2. **Web RFI Forms** — form-first discovery, English question understanding, JSON retrieval with confidence, and structured per-question provenance

The system fills fields when a reliable source value can be identified. If a required field cannot be matched with confidence, it **does not guess**. Instead, it marks the field for human review.

## Quick Start

**For web forms:**
```bash
pip install -e ".[web]"
python demo_web.py
```

**For legacy PDF forms:**
```bash
pip install -e "."
python demo.py
```

---

## 1. What This PoC Demonstrates

The current PoC takes:

* **Source data** in JSON format
* **A fillable PDF form** (AcroForm)

and produces:

* A partially or completely filled PDF
* A mapping and verification report
* A review requirement for fields that could not be reliably filled

### Example

Given this source data:

```json
{
  "applicant": {
    "full_name": "Jane Doe",
    "date_of_birth": "1998-04-15",
    "email": "jane@example.com"
  }
}
```

and a form containing:

```text
Name:          [____________]
Date of Birth: [____________]
Email:         [____________]
Gender:        [____________]
```

the system produces:

```text
Name          → Jane Doe
Date of Birth → 15/04/1998
Email         → jane@example.com
Gender        → REVIEW REQUIRED
```

The system does not invent a value for `Gender` because it is not present in the source data.

---

## 2. PoC Flow

The complete flow is:

```text
                 ┌─────────────────┐
                 │   Source JSON   │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Load Source Data│
                 └────────┬────────┘
                          │
                          │
                 ┌────────▼────────┐
                 │   Form Template │
                 │      (PDF)      │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Read Form Fields│
                 └────────┬────────┘
                          │
             ┌────────────▼────────────┐
             │      Field Matching     │
             │                         │
             │  Exact match            │
             │  Alias match            │
             └────────────┬────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Validation   │
                 │  & Transformation
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │   Fill the PDF  │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Verification │
                 └────────┬────────┘
                          │
                 ┌────────┴────────┐
                 │                 │
              PASS              REVIEW
                 │                 │
                 ▼                 ▼
          Completed PDF      Human provides
                              missing value
                                   │
                                   ▼
                            Re-fill & Verify
```

---

## 3. Current Scope

### Inputs

| Input                 | Current support |
| --------------------- | --------------- |
| JSON source data      | Yes             |
| Fillable AcroForm PDF | Yes             |

### Processing

| Capability                 | Current PoC |
| -------------------------- | ----------- |
| Source data loading        | Yes         |
| PDF field discovery        | Yes         |
| Exact field matching       | Yes         |
| Simple alias matching      | Yes         |
| Date transformation        | Yes         |
| Basic option validation    | Yes         |
| PDF filling                | Yes         |
| Output verification        | Yes         |
| Unresolved-field detection | Yes         |
| Human-review simulation    | Yes         |

### Outputs

The demo generates:

```text
output/
├── filled_form.pdf
├── report.json
└── filled_form_final.pdf
```

`filled_form_final.pdf` is produced after the unresolved field is manually resolved in the demo.

---

## 4. Matching Strategy

The current PoC intentionally uses simple deterministic matching.

### Exact matching

If a form field and source field correspond directly, they are matched.

Example:

```text
email → email
```

### Alias matching

Common alternative names can also be recognized.

Example:

```text
Form field: Name

Possible source fields:
- name
- full_name
- applicant_name
```

If no reliable match is found:

```text
Form field → REVIEW
```

The system does not generate or guess a value.

---

## 5. Validation and Transformation

After a source value is matched, the PoC performs basic validation and transformation before filling the form.

For example:

```text
Source:
1998-04-15

Form format:
DD/MM/YYYY

Result:
15/04/1998
```

Only simple validation required by the current example is implemented.

---

## 6. Verification

The generated PDF is reopened and checked after filling.

The verification step confirms that:

* Expected fields exist
* Filled values match the approved mappings
* Required fields were handled
* Unresolved fields were not accidentally populated with template defaults

This is important because successfully generating a PDF does not necessarily mean that the correct values were written to it.

---

## 7. Human Review

If the system cannot find a reliable source value, it marks the field for review.

For example:

```text
Gender → REVIEW
```

The current demo simulates a human providing:

```text
Gender → Female
```

The form is then regenerated and verified again.

Final result:

```text
Final verification: PASS
```

---

## 8. Web Form Pipeline (New)

For web-based RFI forms, the system follows a **form-first** approach:

```text
Live Web Form (opened in browser)
        ↓
   Discovery (find all controls via DOM + accessibility tree)
        ↓
   Question Understanding (what is being asked)
        ↓
   JSON Retrieval (score every source value against the question)
        ↓
   Answer Planning (ANSWER or REVIEW, with confidence and provenance)
        ↓
   Validation (deterministic type/constraint checks before browser touch)
        ↓
   Browser Filling (Playwright + data-ff-id tagging)
        ↓
   Read-Back Verification (confirm filled state matches intent)
        ↓
   Optional Submission (with required-item gate)
        ↓
   Structured Result JSON (per-question status, confidence, source, alternatives)
```

Key design: **Question drives retrieval**, not field names. Confidence scoring and ambiguity detection happen before any browser interaction.

**Run the web demo:**
```bash
python demo_web.py
```

This generates:
- `result.json` — structured record with per-question answers, confidence, and provenance
- `filled.png` — screenshot before submission
- `trace.zip` — Playwright trace for debugging

## 9. Project Structure

```text
formfill-poc/
│
├── formfill/
│   ├── source.py               # Load and flatten source JSON
│   ├── form.py                 # Read fields from the PDF form
│   ├── matcher.py              # Match source data to form fields
│   ├── validator.py            # Validate and transform matched values
│   ├── filler.py               # Write values into the PDF
│   ├── verifier.py             # Verify the generated PDF
│   │
│   └── web/                    # Web form pipeline (new)
│       ├── models.py           # Data models (Control, Question, AnswerPlanItem, RunResult)
│       ├── discover.py         # Extract controls from live DOM
│       ├── understand.py       # Turn control into question
│       ├── tokens.py           # Deterministic tokenization for matching
│       ├── retrieve.py         # Question-driven JSON retrieval with scoring
│       ├── validate.py         # Deterministic validation before browser touch
│       ├── plan.py             # Answer planning (ANSWER or REVIEW policy)
│       ├── execute.py          # Browser filling and read-back via Playwright
│       ├── result.py           # Structured result JSON output
│       └── pipeline.py         # Orchestration (discovery → understand → retrieve → plan → fill → verify)
│
├── examples/
│   ├── source.json             # Example source data (legacy)
│   ├── form.pdf                # Example fillable PDF
│   │
│   └── web/
│       ├── rfi_form.html       # Example RFI web form
│       └── rfi_source.json     # Example JSON source for RFI
│
├── tests/
│   ├── test_source.py          # Legacy PDF tests
│   ├── test_form.py
│   ├── test_matcher.py
│   ├── test_validator.py
│   ├── test_filler.py
│   ├── test_verifier.py
│   ├── test_end_to_end.py
│   │
│   ├── web/                    # Web form tests
│   │   ├── test_retrieve_plan.py    # Retrieval + planning policy (16 tests)
│   │   ├── test_validate_result.py  # Validation + result status (16 tests)
│   │   ├── test_browser.py          # End-to-end browser integration (16 tests)
│   │   └── fixtures/                # Test HTML forms
│   │       ├── rfi_basic.html
│   │       ├── rfi_conditional.html
│   │       ├── rfi_widgets.html
│   │       └── rfi_strict.html
│   │
│   └── conftest.py
│
├── docs/                       # Research and design documentation
│   ├── TECH_STACK_COMPARISON.md    # Browser automation + testing tool comparison
│   ├── OUTPUT_DESIGN.md            # Result format justification and schema
│   └── GITHUB_LANDSCAPE.md         # Survey of existing form-filling projects
│
├── output/                     # Generated demo output (PDF and web)
│
├── demo.py                     # Legacy PDF demo
├── demo_web.py                 # Web form demo
├── pyproject.toml
└── README.md
```

---

## 10. Running the PoC

### Legacy PDF Forms

```bash
python demo.py
```

The demo will:

1. Load the example JSON.
2. Read the PDF form fields.
3. Match source values to form fields.
4. Validate and transform values.
5. Generate a filled PDF.
6. Verify the generated PDF.
7. Identify unresolved fields.
8. Simulate human review.
9. Re-generate the form.
10. Perform final verification.

A successful run ends with:

```text
Final verification: PASS
```

### Web RFI Forms

```bash
python demo_web.py
```

The demo will:

1. Load the example RFI form and JSON source.
2. Discover all form controls via DOM analysis.
3. Extract questions from control labels/context.
4. Score source values against each question.
5. Generate an answer plan (ANSWER or REVIEW per question).
6. Fill the form via Playwright browser.
7. Read back and verify filled state.
8. (Optionally) submit if all required items are resolved.
9. Output structured result JSON with per-question provenance.

A successful run prints a table showing:
- Question text
- Status (ANSWER or REVIEW)
- Answer value
- Source path and confidence score

---

## 11. Running Tests

Run all tests:
```bash
pytest -v
```

Run only web tests:
```bash
pytest tests/web/ -v
```

Run only legacy PDF tests:
```bash
pytest tests/test_*.py -v
```

The test suite covers:

**Legacy (23 tests):**
* Source loading and flattening
* Form field extraction
* Field matching (exact and alias)
* Validation and transformation
* PDF filling
* Verification
* End-to-end behavior

**Web (48 tests):**
* Form discovery (labels, constraints, options, iframes, shadow DOM)
* Tokenization and token normalization
* Question-driven retrieval with scoring
* Retrieval ambiguity and scope-word disambiguation
* Answer planning policy (disabled/no-source/weak/ambiguous/validation/attestation)
* Type validation (number, date, email, url, choice, checkbox, textarea)
* Result status matrix
* Browser integration (fill, read-back, verify, conditional fields)
* Submission paths (confirmed/unconfirmed/blocked/skipped)
* Template defaults and prefill warnings
* Multi-value controls (multiselect, checkbox_group)
* iframes and cross-frame fills

All 71 tests pass.

---

## 12. Current Scope

**Implemented:**
- JSON source data loading and indexing
- PDF form field discovery and extraction
- Web form discovery via DOM + accessibility tree
- Deterministic matching and retrieval (no LLM)
- Validation and transformation
- Confidence scoring with ambiguity detection
- Attestation/consent detection (never auto-filled)
- Form filling (PDF via reportlab, web via Playwright)
- Verification and read-back
- Structured result JSON with per-question provenance
- Optional submission with required-item gate

**Intentionally not implemented (deferred to later):**
- LLM-based semantic matching (only for tie-breaking with structured output, if needed)
- Embeddings/vector similarity (only if synonym table grows unmanageable)
- VLM-based form understanding (only for canvas/image-only labels)
- Vision-language agent loops
- OCR / scanned forms
- RAG over knowledge bases
- DOCX forms
- XLSX forms
- Multi-page RFIs or complex workflows
- Database persistence
- Review UI
- Production-scale deployment

---

## 14. Future Direction

The deterministic, abstain-first foundation supports gradual introduction of AI where justified:

### For Web Forms

1. **Phase 1 (current)**: Deterministic token-based retrieval + rule-based planning. Scale to real RFIs; observe recall failures on synonym table.

2. **Phase 2 (triggered by data)**: Add embeddings-based semantic matching for question-to-source mapping when synonyms table grows unmanageable.

3. **Phase 3 (optional)**: LLM-structured selection among top-5 candidates (not free-form generation), with re-validation of choice against constraints.

4. **Phase 4 (if needed)**: Vision-language agent only for non-semantic widgets (canvas labels, image-only fields) — never for fields that could be matched deterministically.

### Per-Stage Gating

Each stage from discovery through submission can accept LLM assistance, but only **downstream of deterministic stages**:

```text
Form Discovery (DOM)           ← deterministic
        ↓
Question Understanding         ← rule-based
        ↓
Retrieval Scoring             ← token-based, or +embeddings if needed
        ↓
Candidate Selection           ← rule or LLM (only among ≤5 candidates, re-validated)
        ↓
Validation (type/constraint)  ← always deterministic
        ↓
Browser Execution             ← always Playwright
        ↓
Verification                  ← always deterministic
```

### For PDF Forms

The legacy PDF pipeline remains unchanged; future versions can add:
- Support for more complex form types (multi-page, repeating sections)
- Database persistence for tracking approval workflows

---

## 15. Core Principle

The most important principle demonstrated by this PoC is:

> **Fill what can be reliably determined. Do not guess what cannot.**

### Key Rules

1. **Abstain-first**: When uncertain, mark for REVIEW, never fill with a guess or a default.
2. **Confidence with provenance**: Every answer includes source path, confidence score, and list of alternatives considered.
3. **Deterministic before AI**: Matching, validation, and verification use only deterministic rules. AI is reserved for high-confidence tie-breaking among candidates, or for non-semantic widgets.
4. **Verification always**: After filling (browser or PDF), read back and confirm the actual state matches intent.
5. **Legal safety**: Consent/attestation checkboxes are never auto-filled, even when the source says true.

This provides a foundation for introducing AI capabilities without making the entire system dependent on AI correctness, and enables human oversight at critical decision points.

---

## 15b. Phase 2 — Baseline Evaluation

A local benchmark (`benchmarks/rfi/`, 23 cases, 213 questions, explicit ground truth) measures where the
deterministic pipeline fails. No AI components were added.

```
python tools/build_benchmark.py     # regenerate fixtures
python tools/evaluate_baseline.py   # run + write benchmarks/rfi/results/
pytest tests/evaluation
```

Results and recommendation: `docs/PHASE2_EVALUATION.md`.

## 16. Documentation

See `docs/` for detailed research and design:

- **TECH_STACK_COMPARISON.md** — Why Playwright, not Selenium/Cypress/Puppeteer; why no LLM in MVP; testing strategy.
- **OUTPUT_DESIGN.md** — Why result.json is the primary output (not "the filled form"); schema with per-question provenance; status vocabulary.
- **GITHUB_LANDSCAPE.md** — Comparison of 8 OSS projects (Browser Use, Skyvern, Stagehand, LaVague, etc.). Finding: no project covers full pipeline (form analysis → JSON retrieval → answer plan → fill → verify).
