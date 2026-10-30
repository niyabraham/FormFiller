"""Generate benchmarks/realworld/truth/<form>.<source>.json from one compact spec. Written from the question lists
(questions.json: metadata only, no answers) and the two source files, BEFORE any result.json was opened.

Policy: expect an answer only when the source states exactly what is asked. Inference (years in business from a founding date),
ambiguity (billing vs mailing address; several distinct e-mail addresses; two employee counts), attestations, and personal
questions on non-company forms are expected to stay in review."""
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

A = "answer"
R = "review"
FULL_NAME = "Brightloop Software Inc."

# (label, expect, accept, why, chrome)
def r(label, why, chrome=False):
    return (label, R, [], why, chrome)

def a(label, accept, why):
    return (label, A, accept, why, False)

SPEC = {
    "full": {
        "opnform_vendor": [
            a("Company Name", [FULL_NAME], "company.legal_name"),
            r("Contact Person", "the source holds no person's name"),
            r("Email", "only security.ciso_email (a CISO mailbox), not a general contact address"),
            r("123-456-7890", "phone: only security.incident_contact_phone (an incident line), not a general number"),
            r("Address", "no street address in the source"),
            a("City", ["Austin"], "company.hq.city"),
            a("State", ["TX"], "company.hq.state"),
            r("Zip Code", "not in the source"),
            a("Country", ["US", "United States"], "company.hq.country"),
            a("Website", ["https://www.brightloop.io"], "company.website"),
            r("Additional Information", "free text, nothing to state"),
        ],
        "opnform_credit": [
            a("Business Name", [FULL_NAME], "company.legal_name"),
            r("Business Address", "no street address in the source"),
            r("Contact Person", "the source holds no person's name"),
            r("Contact Email", "only a CISO mailbox"),
            r("123-456-7890", "phone: only an incident line"),
            r("Years in Business", "would be derived from company.founded: an inference, not a stated fact"),
            r("Annual Revenue", "not in the source"),
            r("Business Description", "not in the source"),
            r("Agree to Terms and Conditions", "attestation: never answered from data"),
        ],
        "opnform_scholarship": [
            r("Full Name", "personal question; the source is a company profile"),
            r("Email", "personal question"),
            r("123-456-7890", "personal question"),
            r("Current School/University", "personal question"),
            r("GPA", "personal question"),
            r("Major/Area of Study", "personal question"),
            r("Why do you deserve this scholarship?", "personal narrative"),
            r("Agree to Terms and Conditions", "attestation: never answered from data"),
        ],
        "formbuilder123_vendor": [
            r("Search Templates...", "site search box, not part of the questionnaire", chrome=True),
            a("Your company's legal name", [FULL_NAME], "company.legal_name"),
            r("c_0000000a", "business type (manufacturer / distributor / service provider): not stated in the source"),
            r("What kind of products / services does your company offer?", "not in the source"),
            a("Company website", ["https://www.brightloop.io"], "company.website"),
            r("Street Address", "no street address in the source"),
            r("Street Address Line 2", "no street address in the source"),
            a("City", ["Austin"], "company.hq.city"),
            a("Region", ["TX", "Texas"], "company.hq.state"),
            r("Postal / Zip Code", "not in the source"),
            a("Country", ["US", "United States"], "company.hq.country"),
            r("Please provide information on the following: company founding year, company size, company audience, geographical target.",
              "composite narrative (founding year, size, audience, target): audience and target are not in the source"),
            r("First", "no contact person's name"),
            r("Last", "no contact person's name"),
            r("Contact email", "only a CISO mailbox"),
            r("Contact phone Format 3 3 4", "only an incident line"),
        ],
        "surveyjs_wizard": [
            r("Type to filter the list...", "documentation site's demo filter, not part of the form", chrome=True),
            r("Full name", "a person's name; the source holds none"),
        ],
        "surveyjs_conditional": [
            r("Type to filter the list...", "documentation site's demo filter", chrome=True),
            r("On a scale from 0 to 10, how likely are you to recommend us to a friend or colleague?", "opinion question"),
        ],
        "surveyjs_dropdown": [
            r("Type to filter the list...", "documentation site's demo filter", chrome=True),
            r("Which is the brand of your car?", "not in the source"),
        ],
        "formio_wizard": [
            r("Textfield on page 1", "demo field, no matching fact"),
            r("Number Field * , numeric only,", "demo field, no matching fact"),
        ],
        "demoqa_practice": [
            r("First Name", "a student's first name; no person's name in the source"),
            r("Last Name", "a student's last name; no person's name in the source"),
            r("name@example.com", "personal e-mail; only a CISO mailbox in the source"),
            r("gender", "personal"),
            r("Mobile Number", "personal"),
            r("dateOfBirthInput", "personal"),
            r("subjectsInput", "personal"),
            r("Sports", "personal"),
            r("Reading", "personal"),
            r("Music", "personal"),
            r("Current Address", "no street address in the source"),
            r("react-select-3-input", "state/city dropdown of a student's address; label unknown, no matching fact"),
        ],
        "selenium_webform": [
            r("Text input", "generic demo field, no matching fact"),
            r("Textarea", "generic demo field"),
            r("Readonly input", "read-only field"),
            r("Dropdown (select)", "generic demo field"),
            r("Dropdown (datalist)", "generic demo field"),
            r("my-check", "generic demo field"),
            r("my-radio", "generic demo field"),
            r("Color picker", "generic demo field"),
            r("Date picker", "generic demo field; no fact is 'the date'"),
            r("Example range", "generic demo field"),
        ],
    },
    "tricky": {
        "opnform_vendor": [
            a("Company Name", ["Acme Corp"], "company.name (NOT subsidiary.name 'Acme Labs')"),
            r("Contact Person", "applicant.name and account_manager are both people: ambiguous"),
            r("Email", "ops@acme.example and jane@acme.example: several distinct addresses, form does not say whose"),
            r("123-456-7890", "no phone in the source"),
            r("Address", "address.billing vs address.mailing: ambiguous"),
            r("City", "addresses are free strings; no separate city fact"),
            r("State", "not in the source"),
            r("Zip Code", "not in the source"),
            r("Country", "not in the source"),
            r("Website", "not in the source"),
            r("Additional Information", "free text"),
        ],
        "opnform_credit": [
            a("Business Name", ["Acme Corp"], "company.name (NOT subsidiary.name)"),
            r("Business Address", "address.billing vs address.mailing: ambiguous"),
            r("Contact Person", "applicant.name vs account_manager: ambiguous"),
            a("Contact Email", ["ops@acme.example"], "contact_email (exact key); company.email agrees"),
            r("123-456-7890", "no phone in the source"),
            r("Years in Business", "not in the source"),
            r("Annual Revenue", "revenue.2023 vs revenue.2024: period not stated by the form"),
            r("Business Description", "not in the source"),
            r("Agree to Terms and Conditions", "attestation: never answered from data"),
        ],
        "opnform_scholarship": [
            a("Full Name", ["Jane Doe"], "applicant.name states the applicant's name"),
            r("Email", "ops@acme.example and jane@acme.example: several distinct addresses"),
            r("123-456-7890", "no phone in the source"),
            r("Current School/University", "personal question"),
            r("GPA", "personal question"),
            r("Major/Area of Study", "personal question"),
            r("Why do you deserve this scholarship?", "personal narrative"),
            r("Agree to Terms and Conditions", "attestation: never answered from data"),
        ],
        "formbuilder123_vendor": [
            r("Search Templates...", "site search box, not part of the questionnaire", chrome=True),
            a("Your company's legal name", ["Acme Corp"], "company.name (NOT subsidiary.name)"),
            r("c_0000000a", "business type: not stated in the source"),
            r("What kind of products / services does your company offer?", "not in the source"),
            r("Company website", "not in the source"),
            r("Street Address", "address.billing vs address.mailing: ambiguous"),
            r("Street Address Line 2", "not in the source"),
            r("City", "addresses are free strings; no separate city fact"),
            r("Region", "not in the source"),
            r("Postal / Zip Code", "not in the source"),
            r("Country", "not in the source"),
            r("Please provide information on the following: company founding year, company size, company audience, geographical target.",
              "composite narrative: founding year and audience are not in the source"),
            r("First", "contact person ambiguous (applicant vs account manager)"),
            r("Last", "contact person ambiguous (applicant vs account manager)"),
            a("Contact email", ["ops@acme.example"], "contact_email (exact key); company.email agrees"),
            r("Contact phone Format 3 3 4", "no phone in the source"),
        ],
        "surveyjs_wizard": [
            r("Type to filter the list...", "documentation site's demo filter", chrome=True),
            r("Full name", "applicant.name vs account_manager vs company: a person's name but which one is not stated by the form"),
        ],
        "surveyjs_conditional": [
            r("Type to filter the list...", "documentation site's demo filter", chrome=True),
            r("On a scale from 0 to 10, how likely are you to recommend us to a friend or colleague?", "opinion question"),
        ],
        "surveyjs_dropdown": [
            r("Type to filter the list...", "documentation site's demo filter", chrome=True),
            r("Which is the brand of your car?", "not in the source"),
        ],
        "formio_wizard": [
            r("Textfield on page 1", "demo field, no matching fact"),
            r("Number Field * , numeric only,", "demo field; the source has several numbers but none is 'a number field'"),
        ],
        "demoqa_practice": [
            r("First Name", "applicant.name vs account_manager: ambiguous, and the form is for a student"),
            r("Last Name", "applicant.name vs account_manager: ambiguous"),
            r("name@example.com", "several distinct e-mail addresses"),
            r("gender", "personal"),
            r("Mobile Number", "no phone in the source"),
            r("dateOfBirthInput", "personal"),
            r("subjectsInput", "personal"),
            r("Sports", "personal"),
            r("Reading", "personal"),
            r("Music", "personal"),
            r("Current Address", "address.billing vs address.mailing: ambiguous"),
            r("react-select-3-input", "label unknown, no matching fact"),
        ],
        "selenium_webform": [
            r("Text input", "generic demo field"),
            r("Textarea", "generic demo field"),
            r("Readonly input", "read-only field"),
            r("Dropdown (select)", "generic demo field"),
            r("Dropdown (datalist)", "generic demo field"),
            r("my-check", "generic demo field"),
            r("my-radio", "generic demo field"),
            r("Color picker", "generic demo field"),
            r("Date picker", "generic demo field"),
            r("Example range", "generic demo field"),
        ],
    },
}

# supplemental runs (same questions as a main form, or extra generic demo fields): written from their question lists only
for _s in SPEC:
    SPEC[_s]["opnform_scholarship_back"] = SPEC[_s]["opnform_scholarship"]
    SPEC[_s]["surveyjs_wizard_nobanner"] = SPEC[_s]["surveyjs_wizard"]
    SPEC[_s]["formio_wizard_advance"] = SPEC[_s]["formio_wizard"]
    SPEC[_s]["formio_wizard_rules"] = SPEC[_s]["formio_wizard"] + [
        r("Textfield on Page 2", "demo field, no matching fact"),
        r("Customer", "demo select of the Form.io demo customers"),
        r("autocomplete", "demo field"),
        r("FieldSet Label Textfield", "demo field"),
    ]

n = 0
for source, forms in SPEC.items():
    for form, rows in forms.items():
        doc = {"form": form, "source": source, "policy": "answer only when the source states exactly what is asked; see make_truth.py header in the report",
               "questions": [{"match": m, "expect": e, "accept": acc, "why": why, **({"chrome": True} if chrome else {})} for m, e, acc, why, chrome in rows]}
        (out / f"{form}.{source}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        n += 1
print(n, "truth files written")
exp = {s: sum(1 for rows in f.values() for x in rows if x[1] == A) for s, f in SPEC.items()}
print("expected-answerable questions:", exp)
