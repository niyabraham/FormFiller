# FormFill PoC

A minimal proof of concept for **automatically filling a form using structured source data**.

The PoC demonstrates the core idea:

```text
Source Data (JSON) + Form Template (PDF)
                    ↓
              Field Matching
                    ↓
          Validation / Transformation
                    ↓
                Form Filling
                    ↓
                Verification
                    ↓
              Completed PDF
```

The system fills fields when a reliable source value can be identified. If a required field cannot be matched, it **does not guess**. Instead, it marks the field for human review.

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

## 8. Project Structure

```text
formfill-poc/
│
├── formfill/
│   ├── source.py       # Load and flatten source JSON
│   ├── form.py         # Read fields from the PDF form
│   ├── matcher.py      # Match source data to form fields
│   ├── validator.py    # Validate and transform matched values
│   ├── filler.py       # Write values into the PDF
│   └── verifier.py     # Verify the generated PDF
│
├── examples/
│   ├── source.json     # Example source data
│   └── form.pdf        # Example fillable PDF
│
├── tests/
│   ├── test_source.py
│   ├── test_form.py
│   ├── test_matcher.py
│   ├── test_validator.py
│   ├── test_filler.py
│   ├── test_verifier.py
│   └── test_end_to_end.py
│
├── output/             # Generated demo output
│
├── demo.py             # Runs the complete PoC
├── pyproject.toml
└── README.md
```

---

## 9. Running the PoC

Install the project dependencies and run:

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

---

## 10. Running Tests

Run:

```bash
pytest -v
```

The current PoC contains tests for:

* Source loading
* Form field extraction
* Matching
* Validation
* PDF filling
* Verification
* End-to-end behavior

---

## 11. Current Limitations

This is an **initial PoC**, not the final production system.

The current implementation supports only:

```text
JSON → Fillable AcroForm PDF
```

The following are intentionally **not implemented yet**:

* LLM-based matching
* Embedding-based retrieval
* VLM-based form understanding
* OCR / scanned forms
* RAG
* DOCX forms
* XLSX forms
* HTML forms
* Complex tables and repeating sections
* Advanced conditional fields
* Large-scale production deployment

These can be added in later stages once the basic workflow is established.

---

## 12. Future Direction

The current deterministic PoC provides the foundation for an AI-assisted version.

The intended future flow is:

```text
Multiple Source Formats
(JSON / CSV / XLSX / ...)
              │
              ▼
        Source Data
              │
              ▼
     Candidate Retrieval
              │
       ┌──────┴──────┐
       │             │
 Exact/Alias    AI-assisted
   Matching      Matching
       │             │
       └──────┬──────┘
              ▼
           Mapping
              │
              ▼
        Validation
              │
              ▼
          Rendering
              │
              ▼
         Verification
              │
       ┌──────┴──────┐
       │             │
      PASS          REVIEW
       │             │
       ▼             ▼
 Completed       Human Input
   Form              │
                     ▼
                Re-process
```

AI can later be introduced specifically where semantic ambiguity exists, while validation, rendering, and verification remain deterministic.

---

## 13. Core Principle

The most important principle demonstrated by this PoC is:

> **Fill what can be reliably determined. Do not guess what cannot.**

The PoC therefore separates:

```text
Matching
    ↓
Validation
    ↓
Filling
    ↓
Verification
```

and uses human review when the system cannot confidently determine a value.

This provides a simple foundation for gradually introducing more advanced AI capabilities without making the entire form-filling process dependent on AI-generated decisions.
