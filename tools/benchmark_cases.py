"""Case definitions for the Phase 2 RFI benchmark (see docs/PHASE2_EVALUATION.md).

Ground-truth rules
* `A(...)`  the correct outcome is an automatic ANSWER with this value/source.
* `R(...)`  the correct outcome is REVIEW (value absent, ambiguous, needs
            judgement/composition, or the source value is unusable).
* `H(...)`  control exists but must stay hidden/unasked for this source.
Truth is the correct answer to the question, NOT what the baseline does.
Where the right call is debatable the `note` says why and which way it was decided.

Question wording is modelled on public security-questionnaire patterns
(CAIQ-style Yes/No/NA, SIG-style domain sections with ID-prefixed labels,
"describe your process" narratives, compound yes/no + detail questions,
vendor-onboarding company details); no third-party portal is contacted.
"""

from __future__ import annotations

from benchmark_render import YN, A, H, R

COUNTRY_OPTS = [("India", "India"), ("Canada", "Canada"), ("United States", "United States")]
YNNA = [("yes", "Yes"), ("no", "No"), ("na", "N/A")]


def case(case_id, description, source_style, source, qs, **kw):
    return {"id": case_id, "description": description, "source_style": source_style, "source": source, "qs": qs, **kw}


# ------------------------------------------------------------------ c01 easy
def c01_easy_exact():
    src = {
        "company_name": "Acme Corp", "website": "https://acme.example", "employees": 250, "founded": "2009-03-14",
        "country": "India", "contact_email": "ops@acme.example", "phone": "+91 80 5550 1234", "sso_supported": True,
        "newsletter_opt_in": True, "plan_tier": "Enterprise", "description": "B2B logistics software",
    }
    t = ["easy"]
    qs = [
        A("company_name", "Company name", "text", "Acme Corp", "company_name", required=True, tags=t + ["text"]),
        A("website", "Website", "url", "https://acme.example", "website", tags=t + ["url"]),
        A("employees", "Number of employees", "number", 250, "employees", tags=t + ["number"]),
        A("founded", "Founded", "date", "2009-03-14", "founded", tags=t + ["date"]),
        A("country", "Country", "select", "India", "country", options=COUNTRY_OPTS, tags=t + ["dropdown"]),
        A("contact_email", "Contact email", "email", "ops@acme.example", "contact_email", tags=t + ["email"]),
        A("phone", "Phone", "tel", "+91 80 5550 1234", "phone", tags=t + ["phone"]),
        A("sso_supported", "SSO supported", "radio", "yes", "sso_supported", options=YN, tags=t + ["boolean", "radio"]),
        A("newsletter_opt_in", "Newsletter opt in", "checkbox", True, "newsletter_opt_in", tags=t + ["checkbox"]),
        A("plan_tier", "Plan tier", "select", "Enterprise", "plan_tier",
          options=[("Starter", "Starter"), ("Business", "Business"), ("Enterprise", "Enterprise")], tags=t + ["dropdown"]),
        A("description", "Description", "textarea", "B2B logistics software", "description", tags=t + ["narrative"]),
        R("fax", "Fax", "text", tags=["easy", "missing"], note="no fax value anywhere in the source"),
    ]
    return case("c01_easy_exact", "Label wording equals the JSON key. Every deterministic matcher should pass.",
                "form-aligned", src, qs)


# ------------------------------------------------------------- c02 paraphrase
def c02_paraphrase():
    src = {"company": {
        "workforce_size": 250, "hq_city": "Bengaluru", "year_established": 2009, "annual_revenue_usd": 12000000,
        "legal_name": "Acme Corporation Pvt Ltd", "trading_name": "Acme", "main_phone": "+91 80 5550 1234",
        "support_email": "help@acme.example", "uptime_sla_percent": 99.9, "data_centres": 3}}
    t = ["paraphrase"]
    qs = [
        A("w1", "How many employees are currently employed by your organization?", "number", 250, "company.workforce_size",
          tags=t + ["synonym", "spec_example"], note="the guide's own paraphrase example"),
        A("w2", "What is the size of your workforce?", "number", 250, "company.workforce_size", tags=t + ["synonym"]),
        A("w3", "Total staff headcount", "number", 250, "company.workforce_size", tags=t + ["synonym"]),
        A("w4", "Number of personnel", "number", 250, "company.workforce_size", tags=t + ["synonym"]),
        A("hq", "In which city is your headquarters located?", "text", "Bengaluru", "company.hq_city", tags=t),
        A("est", "In what year was your company established?", "number", 2009, "company.year_established",
          attrs={"min": 1800, "max": 2100}, tags=t),
        A("rev", "What was your annual revenue?", "number", 12000000, "company.annual_revenue_usd",
          attrs={"step": "any"}, tags=t),
        A("legal", "Registered legal entity name", "text", "Acme Corporation Pvt Ltd", "company.legal_name", tags=t),
        A("dba", "Company trading name / DBA", "text", "Acme", "company.trading_name", tags=t),
        A("tel", "Main telephone number", "tel", "+91 80 5550 1234", "company.main_phone", tags=t),
        A("supp", "Customer support contact e-mail", "email", "help@acme.example", "company.support_email", tags=t),
        A("sla", "Guaranteed availability (SLA %)", "number", 99.9, "company.uptime_sla_percent",
          attrs={"step": "any"}, tags=t + ["synonym"], note="availability = uptime"),
        A("dc1", "Number of data centres", "number", 3, "company.data_centres", tags=t),
        A("dc2", "How many data centers do you operate?", "number", 3, "company.data_centres", tags=t + ["spelling"],
          note="US spelling of 'centres'"),
    ]
    return case("c02_paraphrase", "Same facts asked in different words; keys are not worded like the questions.",
                "engineer-natural", src, qs)


# -------------------------------------------------------------- c03 qualifiers
def c03_qualifiers():
    src = {
        "workforce": {"employees": 250, "full_time_employees": 210, "contractors": 40, "interns": 5},
        "customers": {"total": 1800, "enterprise": 120},
        "security": {"contact": {"name": "Priya Nair", "email": "security@acme.example"}},
        "contacts": {"billing": {"email": "billing@acme.example"}, "general": {"email": "info@acme.example"}},
    }
    t = ["qualifier"]
    qs = [
        A("ft", "Number of full-time employees", "number", 210, "workforce.full_time_employees", tags=t),
        A("ctr", "Number of contractors", "number", 40, "workforce.contractors", tags=t),
        A("tot", "How many employees do you have in total?", "number", 250, "workforce.employees", tags=t),
        R("pt", "Number of part-time employees", "number", tags=t + ["missing"],
          note="only full-time and total exist; part-time is not derivable"),
        R("prod", "Number of production employees", "number", tags=t + ["missing", "unlisted_qualifier"],
          note="'production' scope is absent from the source; the total is a different answer"),
        R("act", "Number of active customers", "number", tags=t + ["missing"],
          note="source has total and enterprise customers, not active ones"),
        A("cust", "How many customers do you have?", "number", 1800, "customers.total", tags=t,
          note="key is literally 'total'"),
        A("ent", "Number of enterprise customers", "number", 120, "customers.enterprise", tags=t),
        A("scn", "Security contact name", "text", "Priya Nair", "security.contact.name", tags=t),
        A("sce", "Security contact email", "email", "security@acme.example", "security.contact.email", tags=t + ["contacts"],
          note="three emails exist but only one is a security contact: answerable"),
        A("bce", "Billing contact email", "email", "billing@acme.example", "contacts.billing.email", tags=t + ["contacts"]),
        A("int", "Number of interns", "number", 5, "workforce.interns", tags=t),
    ]
    return case("c03_qualifiers", "Sibling values that differ only by a scope word. Related values must not be confused.",
                "form-aligned", src, qs)


# ----------------------------------------------------------------- c04 nested
def c04_nested():
    src = {
        "organization": {
            "profile": {
                "names": {"legal": "Acme Corporation Pvt Ltd", "brand": "Acme"},
                "address": {"hq": {"street": "12 MG Road", "city": "Bengaluru", "postal_code": "560001"},
                            "billing": {"street": "PO Box 44", "city": "Mumbai", "postal_code": "400001"}},
            },
            "leadership": [
                {"role": "CEO", "name": "Ravi Menon", "email": "ravi@acme.example"},
                {"role": "CISO", "name": "Priya Nair", "email": "priya@acme.example"},
            ],
        },
        "compliance": {"certifications": ["ISO 27001", "SOC 2"], "audits": {"last_soc2_date": "2025-11-30"}},
    }
    t = ["nested"]
    cert_opts = [("iso27001", "ISO 27001"), ("soc2", "SOC 2"), ("pci", "PCI DSS"), ("hipaa", "HIPAA")]
    qs = [
        A("hq_street", "Street", "text", "12 MG Road", "organization.profile.address.hq.street", section="Headquarters address",
          tags=t + ["section"]),
        A("hq_city", "City", "text", "Bengaluru", "organization.profile.address.hq.city", section="Headquarters address",
          tags=t + ["section"]),
        A("bill_street", "Street", "text", "PO Box 44", "organization.profile.address.billing.street", section="Billing address",
          tags=t + ["section"]),
        A("bill_pc", "Postal code", "text", "400001", "organization.profile.address.billing.postal_code",
          section="Billing address", tags=t + ["section"]),
        A("legal", "Legal name of the company", "text", "Acme Corporation Pvt Ltd", "organization.profile.names.legal",
          section="Company", tags=t),
        A("brand", "Brand name", "text", "Acme", "organization.profile.names.brand", section="Company", tags=t),
        A("ciso", "CISO name", "text", "Priya Nair", "organization.leadership.1.name", section="Leadership",
          tags=t + ["list_by_value"], note="role is a VALUE inside a list of objects, not a key"),
        A("ceo", "CEO email", "email", "ravi@acme.example", "organization.leadership.0.email", section="Leadership",
          tags=t + ["list_by_value"]),
        A("soc_date", "Date of last SOC 2 audit", "date", "2025-11-30", "compliance.audits.last_soc2_date",
          section="Compliance", tags=t + ["tokenisation"], note="'SOC 2' vs 'soc2'"),
        A("certs", "Which certifications do you hold?", "checkbox_group", ["iso27001", "soc2"], "compliance.certifications",
          options=cert_opts, section="Compliance", tags=t + ["multi_value"]),
    ]
    return case("c04_nested", "Deep paths, repeated sub-objects (hq/billing), lists of objects, section headings.",
                "engineer-natural", src, qs)


# ---------------------------------------------------------------- c05 boolean
def c05_boolean():
    src = {"security": {
        "sso_supported": True, "mfa_required": True, "mfa_enforced_admins": True, "encryption_at_rest": True,
        "encryption_in_transit": True, "pen_test_annual": True, "data_resident_in_eu": False, "uses_subprocessors": True,
        "has_cyber_insurance": False},
        "privacy": {"gdpr_applicable": True}}
    t = ["boolean_wording"]
    qs = [
        A("sso1", "Do you support SSO?", "radio", "yes", "security.sso_supported", options=YN, tags=t),
        A("sso2", "Is SSO supported?", "radio", "yes", "security.sso_supported", options=YN, tags=t),
        A("sso3", "Does your platform provide SSO?", "radio", "yes", "security.sso_supported", options=YN, tags=t),
        A("mfa1", "Is multi-factor authentication (MFA) required for all users?", "radio", "yes", "security.mfa_required",
          options=YN, tags=t + ["acronym_in_parens"]),
        A("mfa2", "Is MFA enforced for administrators?", "radio", "yes", "security.mfa_enforced_admins", options=YN, tags=t),
        A("mfa3", "Is MFA optional?", "radio", "no", "security.mfa_required", options=YN, tags=t + ["negation", "disputed"], trap="negation",
          note="DISPUTED label: polarity is inverted (source says MFA is required, so 'optional' is NO), but 'required' "
               "has no stated scope (cf. mfa_enforced_admins). Answering 'yes' is wrong under either label; REVIEW would also be acceptable"),
        A("enc1", "Is data encrypted at rest?", "radio", "yes", "security.encryption_at_rest", options=YN, tags=t + ["morphology"]),
        A("enc2", "Do you encrypt data in transit?", "radio", "yes", "security.encryption_in_transit", options=YN,
          tags=t + ["morphology"]),
        A("ins", "Do you have cyber insurance?", "radio", "no", "security.has_cyber_insurance", options=YN, tags=t),
        A("eu", "Is customer data stored exclusively in the EU?", "radio", "no", "security.data_resident_in_eu", options=YN,
          tags=t),
        A("gdpr", "Does GDPR apply to your organization?", "radio", "yes", "privacy.gdpr_applicable", options=YN, tags=t),
        A("sub", "Do you use sub-processors?", "radio", "yes", "security.uses_subprocessors", options=YN, tags=t + ["morphology"]),
        A("pen", "Are penetration tests performed at least annually?", "select", "yes", "security.pen_test_annual",
          options=YNNA, tags=t + ["yes_no_na"]),
        A("sso4", "Single sign-on is supported", "checkbox", True, "security.sso_supported", tags=t + ["checkbox", "synonym"],
          note="spelled-out form of the SSO acronym"),
    ]
    return case("c05_boolean", "Yes/No questions worded many ways, plus a negation trap and CAIQ-style Yes/No/NA.",
                "form-aligned", src, qs)


# ----------------------------------------------------------- c06 option mapping
def c06_option_mapping():
    src = {"company": {
        "country": "United States", "employees": 250, "industry": "Software as a Service", "state": "California",
        "currency": "USD", "business_type": "Private limited company", "regions": ["North America", "Europe"],
        "timezone": "Asia/Kolkata", "language": "English", "countries_of_operation": ["India", "Singapore"]}}
    t = ["option_mapping"]
    qs = [
        A("c1", "Country", "select", "US", "company.country",
          options=[("US", "US"), ("GB", "United Kingdom"), ("CA", "Canada")], tags=t,
          note="the guide's example: 'United States' -> option 'US'"),
        A("c2", "Country of registration", "select", "US", "company.country",
          options=[("US", "United States of America"), ("GB", "United Kingdom")], tags=t),
        A("c3", "Country (exact option text)", "select", "United States", "company.country",
          options=[("United States", "United States"), ("India", "India")], tags=t + ["control"]),
        A("band", "Number of employees (band)", "select", "51-250", "company.employees",
          options=[("1-50", "1-50"), ("51-250", "51-250"), ("251-1000", "251-1000"), ("1000+", "1000+")],
          tags=t + ["derivation"], note="250 falls in the 51-250 band; a deterministic range check, not a guess"),
        A("ind", "Industry", "select", "saas", "company.industry",
          options=[("saas", "SaaS / Software"), ("fin", "Financial services"), ("health", "Healthcare")], tags=t),
        A("btype", "Business type", "select", "pvt", "company.business_type",
          options=[("pvt", "Private limited company"), ("pub", "Public limited company"), ("llp", "LLP")],
          tags=t + ["control"]),
        A("cur", "Reporting currency", "radio", "USD", "company.currency",
          options=[("USD", "USD"), ("EUR", "EUR"), ("INR", "INR")], tags=t + ["control"]),
        A("reg", "Operating regions", "checkbox_group", ["na", "eu"], "company.regions",
          options=[("na", "North America"), ("eu", "Europe"), ("apac", "Asia Pacific")], tags=t + ["multi_value", "control"]),
        R("reg2", "Countries where you operate", "checkbox_group", tags=t + ["multi_value"],
          options=[("India", "India"), ("United States", "United States"), ("Germany", "Germany")],
          note="source holds regions, form wants countries: 'North America' cannot be mapped to a listed country"),
        A("state", "State", "select", "CA", "company.state",
          options=[("CA", "California"), ("NY", "New York")], tags=t),
        R("lang", "Language", "select", tags=t + ["ambiguous"],
          options=[("en-US", "English (US)"), ("en-GB", "English (UK)")],
          note="'English' fits two options"),
        A("tz", "Timezone", "select", "Asia/Kolkata", "company.timezone",
          options=[("Asia/Kolkata", "(UTC+05:30) India Standard Time"), ("Europe/London", "(UTC+00:00) London")],
          tags=t + ["control"]),
        A("ncountries", "Number of countries you operate in", "number", 2, "company.countries_of_operation",
          tags=["derivation"], note="count of a list in the source"),
    ]
    return case("c06_option_mapping", "Source value must be mapped onto the form's own option list.",
                "engineer-natural", src, qs)


# -------------------------------------------------------------- c07 ambiguity
def c07_ambiguity():
    src = {
        "company": {"employees": 250, "name": "Acme Corp", "email": "ops@acme.example"},
        "subsidiary": {"employees": 80, "name": "Acme Labs"},
        "applicant": {"name": "Jane Doe", "email": "jane@acme.example"},
        "revenue": {"2023": 9000000, "2024": 12000000},
        "address": {"billing": "PO Box 44, Mumbai", "mailing": "12 MG Road, Bengaluru"},
        "contact_email": "ops@acme.example", "billing_email": "ops@acme.example",
        "tax": {"gst_number": "29ABCDE1234F1Z5", "pan": "ABCDE1234F"},
        "account_manager": "Ravi Menon", "has_account_manager": True,
    }
    t = ["ambiguous"]
    qs = [
        R("e1", "How many employees does the organization have?", "number", tags=t + ["spec_example", "disputed"],
          note="spec: company.employees (250) vs subsidiary.employees (80). 'the organization' may or may not include "
               "the subsidiary; the guide's rule is REVIEW unless evidence disambiguates. DISPUTED label: a reader could "
               "reasonably say 250 (the filing entity); REVIEW follows the spec and is the conservative reading"),
        R("e2", "How many employees?", "number", tags=t),
        A("e3", "How many employees does the subsidiary have?", "number", 80, "subsidiary.employees", tags=t + ["control"]),
        R("n1", "Name", "text", tags=t, note="company, subsidiary and applicant names all exist"),
        A("n2", "Name", "text", "Jane Doe", "applicant.name", section="Applicant", tags=t + ["section"]),
        R("m1", "Email", "email", section="General questions", tags=t,
          note="a neutral heading follows the Applicant block, so no section evidence applies"),
        R("r1", "Revenue", "number", tags=t, note="2023 and 2024 values; year not stated"),
        A("r2", "Revenue for 2024", "number", 12000000, "revenue.2024", attrs={"step": "any"}, tags=t + ["numeric_key"]),
        R("a1", "Address", "textarea", tags=t, note="billing and mailing both exist"),
        A("a2", "Mailing address", "textarea", "12 MG Road, Bengaluru", "address.mailing", tags=t + ["control"]),
        A("b1", "Billing email address", "email", "ops@acme.example", "billing_email", tags=t + ["control"]),
        R("t1", "Tax registration number", "text", tags=t, note="GST number and PAN are different registrations"),
        A("t2", "GST number", "text", "29ABCDE1234F1Z5", "tax.gst_number", tags=t + ["control"]),
        A("am", "Do you have an account manager?", "radio", "yes", "has_account_manager", options=YN, tags=t + ["type_tie"],
          note="a boolean flag and a name share the same words; a yes/no question can only be answered by the flag"),
        A("c1", "Company email address", "email", "ops@acme.example", "company.email", tags=t + ["same_value_two_paths"],
          note="company.email and contact_email hold the same value"),
    ]
    return case("c07_ambiguity", "Two or more plausible values. The safe outcome is REVIEW unless the question disambiguates.",
                "engineer-natural", src, qs)


# --------------------------------------------------------- c08 missing / traps
def c08_missing():
    src = {
        "company": {"name": "Acme Corp", "employees": 250, "registration_number": "U72900KA2009PTC123456",
                    "countries": ["India", "Singapore"], "website": "https://acme.example", "phone": "+91 80 5550 1234"},
        "certifications": {"iso_27001": True, "soc2_type": "Type II"},
        "security": {"contact_email": "security@acme.example", "incident_contact_phone": "+91 80 5550 9999"},
        "insurance": {"provider": "Beazley", "coverage_usd": 5000000},
    }
    t = ["missing"]
    yn = YN
    qs = [
        R("vat", "VAT / Tax ID", "text", tags=t, note="only a company registration number exists"),
        A("regno", "Registration number", "text", "U72900KA2009PTC123456", "company.registration_number", tags=["control"]),
        R("pci", "Do you hold PCI DSS certification?", "radio", options=yn, tags=t),
        A("soc2", "Do you hold SOC 2 Type II certification?", "radio", "yes", "certifications.soc2_type", options=yn,
          tags=["derivation"], note="soc2_type = 'Type II' states which SOC 2 report they hold"),
        A("irphone", "Incident response contact phone", "tel", "+91 80 5550 9999", "security.incident_contact_phone", tags=["control"]),
        R("iremail", "Incident response contact email", "email", tags=t + ["false_positive_risk"],
          note="the source has a security contact email, not an incident-response one: a different role"),
        A("insprov", "Cyber insurance provider", "text", "Beazley", "insurance.provider", tags=["control"]),
        A("inscov", "Cyber insurance coverage amount (USD)", "number", 5000000, "insurance.coverage_usd", tags=["paraphrase"]),
        R("pentest", "Date of last penetration test", "date", tags=t),
        R("auditor", "Name of external auditor", "text", tags=t),
        R("parent", "Parent company name", "text", tags=t + ["false_positive_risk"],
          note="Acme Corp is the company itself, not its parent"),
        A("coname", "Company name", "text", "Acme Corp", "company.name", tags=["control"]),
        R("parentweb", "Website of parent company", "url", tags=t + ["false_positive_risk"],
          note="company.website belongs to the company, not the parent"),
    ]
    return case("c08_missing", "Answer not in the source, plus near-miss keys that tempt a false positive.",
                "engineer-natural", src, qs)


# ------------------------------------------------------------------ c09 narrative
def c09_narrative():
    src = {
        "incident_response": {
            "process": "Incidents are triaged by the on-call security engineer within 15 minutes, escalated to the CISO for "
                       "severity 1, and customers are notified within 72 hours.",
            "contact": "soc@acme.example", "sla_hours": 72, "last_test_date": "2025-09-12"},
        "security": {"overview": "ISO 27001 certified ISMS; annual third-party penetration tests; SSO and MFA enforced.",
                     "encryption": {"at_rest": "AES-256", "in_transit": "TLS 1.2+"}},
        "company": {"description": "Acme builds logistics software for mid-size manufacturers."},
    }
    t = ["narrative"]
    qs = [
        A("n1", "Describe your incident response process.", "textarea", src["incident_response"]["process"],
          "incident_response.process", tags=t + ["direct_text"]),
        A("n2", "Provide a summary of your information security program.", "textarea", src["security"]["overview"],
          "security.overview", tags=t + ["direct_text"], note="one dedicated overview field exists"),
        R("n3", "Describe your encryption practices.", "textarea", tags=t + ["composition"],
          note="would need composing at-rest and in-transit values into prose; policy forbids composing"),
        A("n4", "What encryption standard do you use for data at rest?", "text", "AES-256", "security.encryption.at_rest",
          tags=t + ["short_text"]),
        A("n5", "Briefly describe your company.", "textarea", src["company"]["description"], "company.description",
          tags=t + ["direct_text"]),
        R("n6", "Describe how you handle vendor risk management.", "textarea", tags=t + ["missing"]),
        A("n7", "Who is your incident response point of contact?", "text", "soc@acme.example", "incident_response.contact", tags=t),
        A("n8", "What is your incident notification SLA (hours)?", "number", 72, "incident_response.sla_hours", tags=t),
        A("n9", "Date of last incident response test", "date", "2025-09-12", "incident_response.last_test_date", tags=t),
        R("n10", "Describe your incident response process and your breach notification timeline.", "textarea",
          tags=t + ["compound", "composition"], trap="compound",
          note="two asks; would need composing the process text and the 72-hour SLA"),
    ]
    return case("c09_narrative", "Free-text questions: direct answer present, composition required, or nothing relevant.",
                "engineer-natural", src, qs)


# ------------------------------------------------------------- c10 conditional
def c10_conditional():
    src = {
        "privacy": {"gdpr_applicable": True, "dpo_name": "A. Rao", "dpo_email": "dpo@acme.example", "dpo_phone": "+91 80 5550 7777"},
        "payments": {"processes_card_data": True, "pci_level": "Level 2"},
        "security": {"has_ciso": True, "ciso_name": "Priya Nair"},
        "company": {"subsidiaries_exist": False},
    }
    t = ["conditional"]
    lv = [(f"level{i}", f"Level {i}") for i in range(1, 5)]
    qs = [
        A("gdpr", "GDPR applicable", "radio", "yes", "privacy.gdpr_applicable", options=YN, tags=["conditional_trigger"]),
        A("dpo", "Who is your Data Protection Officer?", "text", "A. Rao", "privacy.dpo_name", when=("gdpr", "yes"),
          tags=t, note="the guide's conditional example"),
        A("dpo_email", "DPO email", "email", "dpo@acme.example", "privacy.dpo_email", when=("gdpr", "yes"), tags=t),
        H("gdpr_reason", "Reason GDPR does not apply", "textarea", when=("gdpr", "no"), tags=t + ["stays_hidden"]),
        A("card", "Does your company process payment card data?", "radio", "yes", "payments.processes_card_data",
          options=YN, tags=["conditional_trigger"]),
        A("pci", "PCI DSS compliance level", "select", "level2", "payments.pci_level", options=lv, when=("card", "yes"), tags=t),
        H("qsa", "Name of your Qualified Security Assessor", "text", when=("pci", "level1"), tags=t + ["stays_hidden", "two_level"]),
        A("ciso", "Do you have a designated CISO?", "radio", "yes", "security.has_ciso", options=YN,
          tags=["conditional_trigger"]),
        A("ciso_name", "CISO name", "text", "Priya Nair", "security.ciso_name", when=("ciso", "yes"), tags=t),
        A("subs", "Do you have subsidiaries?", "radio", "no", "company.subsidiaries_exist", options=YN, tags=["conditional_trigger"]),
        H("sub_list", "List your subsidiaries", "textarea", when=("subs", "yes"), tags=t + ["stays_hidden"]),
        A("gdpr2", "Is your organization subject to the EU General Data Protection Regulation (GDPR)?", "radio", "yes",
          "privacy.gdpr_applicable", options=YN, tags=["conditional_trigger", "boolean_wording"]),
        A("dpo_phone", "DPO contact phone", "tel", "+91 80 5550 7777", "privacy.dpo_phone", when=("gdpr2", "yes"),
          tags=t + ["cascade"], note="revealed only if the paraphrased trigger above is answered"),
    ]
    return case("c10_conditional", "Fields revealed by earlier answers, two-level chains, hidden-must-stay-hidden, "
                "and a conditional whose trigger is worded as a paraphrase.", "form-aligned", src, qs)


# -------------------------------------------------------------- c11 multistep
def c11_multistep():
    src = {"company_name": "Acme Corp", "website": "https://acme.example", "employees": 250, "country": "India",
           "contact_email": "ops@acme.example", "sso_supported": True, "gdpr_applicable": True}
    t = ["multistep"]
    qs = [
        A("company_name", "Company name", "text", "Acme Corp", "company_name", step=1, tags=["control"]),
        A("website", "Website", "url", "https://acme.example", "website", step=1, tags=["control"]),
        A("employees", "Number of employees", "number", 250, "employees", step=2, tags=t + ["hidden_in_dom"],
          note="step panel is in the DOM but hidden until Next is clicked"),
        A("country", "Country", "select", "India", "country", step=2, options=COUNTRY_OPTS, tags=t + ["hidden_in_dom"]),
        A("contact_email", "Contact email", "email", "ops@acme.example", "contact_email", step=2, tags=t + ["hidden_in_dom"]),
        A("sso_supported", "SSO supported", "radio", "yes", "sso_supported", step=3, options=YN, tags=t + ["not_in_dom"],
          note="step 3 does not exist in the DOM until Next is clicked twice"),
        A("gdpr_applicable", "GDPR applicable", "radio", "yes", "gdpr_applicable", step=3, options=YN, tags=t + ["not_in_dom"]),
    ]
    return case("c11_multistep", "Three-step wizard: step 2 hidden in the DOM, step 3 rendered only after Next.",
                "form-aligned", src, qs, dynamic_steps={3})


# ------------------------------------------------------------- c12 validation
def c12_validation():
    src = {"company": {
        "employees": "about 200", "founded": "14 March 2009", "incorporated": "03/04/2009", "website": "acme.com",
        "contact_email": "ops [at] acme.example", "registration_code": "abc-12",
        "legal_name": "Acme Corporation International Holdings Limited", "revenue_growth_percent": 140, "tier": "Atlantis",
        "phone": "080-5550-1234", "stock_ticker": "ACME", "staff_count": "1,200", "average_rating": "4.5"}}
    t = ["validation"]
    qs = [
        R("emp", "Number of employees", "number", tags=t + ["invalid_source"], invalid_source="company.employees",
          note="'about 200' is not a number"),
        A("fd", "Founded", "date", "2009-03-14", "company.founded", tags=t + ["transformation"],
          note="'14 March 2009' is an unambiguous date, convertible without guessing"),
        R("inc", "Incorporated", "date", tags=t + ["ambiguous_format"], invalid_source="company.incorporated",
          note="03/04/2009 is 3 April or 4 March: ambiguous, REVIEW"),
        R("web", "Website", "url", tags=t + ["invalid_source"], invalid_source="company.website",
          note="no scheme: https vs http is not known"),
        R("mail", "Contact email", "email", tags=t + ["invalid_source"], invalid_source="company.contact_email"),
        R("regcode", "Registration code", "text", attrs={"pattern": "[A-Z]{3}-[0-9]{4}"}, tags=t + ["invalid_source"],
          invalid_source="company.registration_code"),
        R("legal", "Legal name", "text", attrs={"maxlength": 30}, tags=t + ["invalid_source"],
          invalid_source="company.legal_name", note="48 chars into a 30-char field; never truncate"),
        R("growth", "Revenue growth (%)", "number", attrs={"min": 0, "max": 100}, tags=t + ["invalid_source"],
          invalid_source="company.revenue_growth_percent"),
        R("tier", "Tier", "select", options=[("Starter", "Starter"), ("Business", "Business"), ("Enterprise", "Enterprise")],
          tags=t + ["invalid_source"], invalid_source="company.tier"),
        R("phone", "Phone", "tel", attrs={"pattern": r"\+?[0-9 ]{8,15}"}, tags=t + ["invalid_source"],
          invalid_source="company.phone", note="hyphens violate the field pattern; do not reformat silently"),
        A("ticker", "Stock ticker", "text", "ACME", "company.stock_ticker", attrs={"maxlength": 4}, tags=t + ["boundary"]),
        A("staff", "Staff count", "number", 1200, "company.staff_count", tags=t + ["transformation"],
          note="'1,200' parses to 1200"),
        A("rating", "Average rating", "number", 4.5, "company.average_rating", attrs={"step": "0.1"}, tags=t + ["transformation"]),
    ]
    return case("c12_validation", "Source values that violate (or can be coerced into) the control's constraints.",
                "form-aligned", src, qs)


# ------------------------------------------------------- c13 realistic SIG-style
def c13_realistic_security():
    src = {
        "policies": {"infosec_policy": {"exists": True, "last_reviewed": "2026-01-15"},
                     "bcp_dr": {"exists": True, "last_tested": "2025-10-02"},
                     "security_awareness_training": {"frequency": "annual", "completion_rate_percent": 98}},
        "access": {"mfa": {"remote_access": True, "admin_accounts": True},
                   "sso": {"enabled": True, "protocols": ["SAML", "OIDC"]},
                   "access_reviews": {"frequency": "quarterly"}},
        "encryption": {"at_rest": {"enabled": True, "algorithm": "AES-256"},
                       "in_transit": {"enabled": True, "protocol": "TLS 1.2+"}},
        "incident": {"has_plan": True, "breach_last_3_years": False, "contact": "soc@acme.example"},
        "vendor_management": {"subprocessors_list_url": "https://acme.example/subprocessors"},
        "compliance": {"soc2": {"type": "II", "report_available_under_nda": True},
                       "iso27001": {"certified": True, "expiry": "2027-06-30"}},
        "pentest": {"frequency": "annual", "last_date": "2025-11-10"},
        "hr": {"background_checks": True},
    }
    t = ["realistic"]
    freq = [("monthly", "Monthly"), ("quarterly", "Quarterly"), ("annual", "Annually"), ("never", "Never")]
    qs = [
        A("A1", "A.1 Do you have a documented information security policy?", "radio", "yes", "policies.infosec_policy.exists",
          options=YNNA, section="A. Risk governance", tags=t + ["yes_no_na", "bool_in_parent"]),
        A("A2", "A.2 When was the information security policy last reviewed?", "date", "2026-01-15",
          "policies.infosec_policy.last_reviewed", section="A. Risk governance", tags=t),
        A("B1", "B.1 Do you encrypt data at rest?", "radio", "yes", "encryption.at_rest.enabled", options=YNNA,
          section="B. Data encryption", tags=t + ["yes_no_na", "bool_in_parent"]),
        A("B2", "B.2 What encryption algorithm is used for data at rest?", "text", "AES-256", "encryption.at_rest.algorithm",
          section="B. Data encryption", tags=t),
        A("B3", "B.3 Do you encrypt data in transit?", "radio", "yes", "encryption.in_transit.enabled", options=YNNA,
          section="B. Data encryption", tags=t + ["yes_no_na", "bool_in_parent"]),
        A("C1", "C.1 Is multi-factor authentication (MFA) used for remote access?", "radio", "yes", "access.mfa.remote_access",
          options=YNNA, section="C. Identity and access", tags=t + ["yes_no_na", "acronym_in_parens"]),
        A("C2", "C.2 Is MFA enforced for administrator accounts?", "radio", "yes", "access.mfa.admin_accounts", options=YNNA,
          section="C. Identity and access", tags=t + ["yes_no_na"]),
        A("C3", "C.3 Do you support single sign-on (SSO)?", "radio", "yes", "access.sso.enabled", options=YNNA,
          section="C. Identity and access", tags=t + ["yes_no_na", "bool_in_parent", "acronym_in_parens"]),
        A("C4", "C.4 How often are user access reviews performed?", "select", "quarterly", "access.access_reviews.frequency",
          options=freq, section="C. Identity and access", tags=t),
        A("D1", "D.1 Do you have an incident response plan?", "radio", "yes", "incident.has_plan", options=YNNA,
          section="D. Incident management", tags=t + ["yes_no_na"]),
        A("D2", "D.2 Have you experienced a data breach in the last three years?", "radio", "no", "incident.breach_last_3_years",
          options=YNNA, section="D. Incident management", tags=t + ["yes_no_na", "number_word"]),
        A("D3", "D.3 Who is your incident response point of contact?", "text", "soc@acme.example", "incident.contact",
          section="D. Incident management", tags=t),
        A("E1", "E.1 Do you maintain a tested business continuity and disaster recovery plan?", "radio", "yes",
          "policies.bcp_dr.exists", options=YNNA, section="E. Business continuity", tags=t + ["yes_no_na", "bool_in_parent"]),
        A("E2", "E.2 Date of last disaster recovery test", "date", "2025-10-02", "policies.bcp_dr.last_tested",
          section="E. Business continuity", tags=t),
        R("F1", "F.1 Do all employees complete security awareness training annually?", "radio", options=YNNA,
          section="F. People", tags=t + ["judgement"],
          note="frequency is annual but completion is 98%: 'all' needs a human decision"),
        A("F2", "F.2 Security awareness training completion rate (%)", "number", 98,
          "policies.security_awareness_training.completion_rate_percent", section="F. People", tags=t),
        A("G1", "G.1 Do you perform background checks on employees?", "radio", "yes", "hr.background_checks", options=YNNA,
          section="G. Compliance", tags=t + ["yes_no_na"]),
        A("G2", "G.2 Can you share your most recent SOC 2 Type II report under NDA?", "radio", "yes",
          "compliance.soc2.report_available_under_nda", options=YNNA, section="G. Compliance", tags=t + ["yes_no_na"]),
        A("G3", "G.3 Are you ISO 27001 certified?", "radio", "yes", "compliance.iso27001.certified", options=YNNA,
          section="G. Compliance", tags=t + ["yes_no_na", "bool_in_parent"]),
        A("G4", "G.4 ISO 27001 certificate expiry date", "date", "2027-06-30", "compliance.iso27001.expiry",
          section="G. Compliance", tags=t),
        A("H1", "H.1 Link to your sub-processor list", "url", "https://acme.example/subprocessors",
          "vendor_management.subprocessors_list_url", section="H. Vendor management", tags=t),
        A("J1", "J.1 Penetration testing frequency", "select", "annual", "pentest.frequency",
          options=[("quarterly", "Quarterly"), ("semiannual", "Semi-annual"), ("annual", "Annual"), ("none", "None")],
          section="J. Vulnerability management", tags=t),
        A("J2", "J.2 Date of last penetration test", "date", "2025-11-10", "pentest.last_date",
          section="J. Vulnerability management", tags=t),
        R("J3", "J.3 Upload your most recent penetration test report", "file", section="J. Vulnerability management",
          tags=t + ["file_upload"], note="a document must be attached by a person; it should still be surfaced for review"),
    ]
    return case("c13_realistic_security", "SIG/CAIQ-style page: ID-prefixed labels, domain sections, Yes/No/NA, engineer-style "
                "nested source whose booleans are named `exists`/`enabled`.", "engineer-natural", src, qs)


# -------------------------------------------------------- c14 label styles (native)
def c14_label_styles():
    src = {"company_name": "Acme Corp", "website": "https://acme.example", "employees": 250, "contact_email": "ops@acme.example",
           "country": "India", "industry": "Software", "phone": "+91 80 5550 1234", "founded": "2009-03-14",
           "legal_name": "Acme Corporation Pvt Ltd", "city": "Bengaluru"}
    t = ["label_style"]
    mk = lambda *a, **k: A(*a, tags=t + k.pop("extra", []), **k)
    qs = [
        mk("s1", "Company name", "text", "Acme Corp", "company_name", style="label_for"),
        mk("s2", "Website", "url", "https://acme.example", "website", style="wrap"),
        mk("s3", "Number of employees", "number", 250, "employees", style="aria_label"),
        mk("s4", "Contact email", "email", "ops@acme.example", "contact_email", style="aria_labelledby"),
        mk("s5", "Phone", "tel", "+91 80 5550 1234", "phone", style="placeholder", extra=["placeholder_only"]),
        mk("s6", "Date founded", "date", "2009-03-14", "founded", style="div_label", extra=["div_label"]),
        mk("s7", "Legal name", "text", "Acme Corporation Pvt Ltd", "legal_name", style="table", extra=["table_layout"]),
        mk("s8", "City", "text", "Bengaluru", "city", style="bad_for", extra=["broken_label_for"]),
        mk("s9", "1. Industry (required) *", "text", "Software", "industry", style="label_for", extra=["numbered_label"]),
        mk("s10", "Country", "select", "India", "country", style="div_label", options=COUNTRY_OPTS, extra=["div_label"]),
        # same weak label patterns, but the input *name* happens to be meaningful (a common real-world situation)
        mk("website_url", "Company website", "url", "https://acme.example", "website", style="div_label",
           extra=["div_label", "semantic_name"], note="label unreadable; the input name 'website_url' rescues retrieval"),
        mk("employee_count", "How many people work for you?", "number", 250, "employees", style="table",
           extra=["table_layout", "semantic_name"], note="label unreadable; name fallback answers via a different wording"),
    ]
    return case("c14_label_styles", "The same easy facts, but each label is attached to its control a different way.",
                "form-aligned", src, qs)


# ------------------------------------------------------ c15 custom widgets
def c15_custom_widgets():
    src = {"sso_supported": True, "country": "India", "newsletter_opt_in": True, "description": "B2B logistics software",
           "company_name": "Acme Corp", "company_website": "https://acme.example"}
    t = ["custom_widget"]
    qs = [
        A("w_name", "Company name", "text", "Acme Corp", "company_name", tags=["control"]),
        A("w_sso", "Do you support SSO?", "custom_radio", "yes", "sso_supported", options=YN, tags=t + ["aria_radio"]),
        A("w_country", "Country", "custom_combobox", "India", "country", tags=t + ["aria_combobox"]),
        A("w_news", "Newsletter opt in", "custom_switch", True, "newsletter_opt_in", tags=t + ["aria_switch"]),
        A("w_desc", "Describe your business", "custom_editable", "B2B logistics software", "description",
          tags=t + ["contenteditable"]),
        A("w_shadow", "Company website", "shadow_text", "https://acme.example", "company_website", tags=t + ["shadow_dom"]),
        R("w_file", "Upload your SOC 2 report", "file", tags=["file_upload"], note="document upload: a person must attach it"),
    ]
    return case("c15_custom_widgets", "Controls that are not native inputs (ARIA widgets, contenteditable, open shadow DOM, file upload).",
                "form-aligned", src, qs)


# ------------------------------------------------------- c16 dynamic inputs (browser layer)
def c16_dynamic_inputs():
    src = {"company_name": "Acme Corp", "start_date": "2026-01-15", "mobile_phone": "5550001234", "region": "EMEA",
           "account_manager_assigned": True, "account_manager": "Ravi Menon"}
    t = ["browser_execution"]
    qs = [
        A("company_name", "Company name", "text", "Acme Corp", "company_name", tags=["control"]),
        A("start_date", "Contract start date", "text", "2026-01-15", "start_date", attrs={"readonly": True},
          tags=t + ["readonly_datepicker"], note="read-only box filled by a date-picker popup in real portals"),
        A("mobile_phone", "Mobile phone", "tel", "555-000-1234", "mobile_phone", attrs={"data-mask": "phone"},
          tags=t + ["masked_input"], note="the page's input mask rewrites 5550001234 to 555-000-1234; the form should hold the masked value"),
        A("region", "Region", "select", "EMEA", "region", options=[("EMEA", "EMEA"), ("APAC", "APAC")],
          attrs={"data-async": True}, tags=t + ["async_options"], note="options are inserted ~600 ms after load"),
        A("has_am", "Account manager assigned", "radio", "yes", "account_manager_assigned", options=YN, tags=["conditional_trigger"]),
        A("account_manager", "Account manager name", "text", "Ravi Menon", "account_manager", enable_when=("has_am", "yes"),
          tags=t + ["enabled_later"], note="control is disabled until the previous answer is given"),
    ]
    return case("c16_dynamic_inputs", "Native inputs that behave dynamically: read-only picker, input mask, late options, enabled-by-answer.",
                "form-aligned", src, qs)


ALL_CASES = [c01_easy_exact, c02_paraphrase, c03_qualifiers, c04_nested, c05_boolean, c06_option_mapping, c07_ambiguity,
             c08_missing, c09_narrative, c10_conditional, c11_multistep, c12_validation, c13_realistic_security,
             c14_label_styles, c15_custom_widgets, c16_dynamic_inputs]


# ---------------------------------------------------------- submission scenarios
OK_TEXT = "Thank you, your response was received"


def submission_scenarios():
    base_src = {"company_name": "Acme Corp", "contact_email": "ops@acme.example", "employees": 250}

    def base(extra=()):
        return [A("company_name", "Company name", "text", "Acme Corp", "company_name", required=True, tags=["control"]),
                A("contact_email", "Contact email", "email", "ops@acme.example", "contact_email", required=True, tags=["control"]),
                *extra]

    return [
        {"id": "sub_ok", "description": "all required answered, in-page success message", "source": base_src,
         "qs": base([A("employees", "Number of employees", "number", 250, "employees", tags=["control"])]),
         "submit": "success", "success_text": OK_TEXT, "expected_outcome": "CONFIRMED", "expected_status": "SUBMITTED"},
        {"id": "sub_required_missing", "description": "a required question has no source value", "source": base_src,
         "qs": base([R("tax_id", "Tax ID", "text", required=True, tags=["missing"])]),
         "submit": "success", "success_text": OK_TEXT, "expected_outcome": "SKIPPED", "expected_status": "NEEDS_REVIEW"},
        {"id": "sub_attestation_required", "description": "required attestation checkbox must never be auto-ticked",
         "source": {**base_src, "answers_accurate": True},
         "qs": base([R("attest", "I confirm the answers are accurate", "checkbox", required=True, tags=["attestation"])]),
         "submit": "success", "success_text": OK_TEXT, "expected_outcome": "SKIPPED", "expected_status": "NEEDS_REVIEW"},
        {"id": "sub_server_reject", "description": "portal rejects the submission with an error message", "source": base_src,
         "qs": base(), "submit": "reject", "success_text": OK_TEXT, "expected_outcome": "UNCONFIRMED",
         "expected_status": "SUBMITTED_UNCONFIRMED",
         "note": "the correct behaviour is to NOT report success; the page's error text is not read"},
        {"id": "sub_delayed_confirmation", "description": "success message appears after ~1.2 s", "source": base_src,
         "qs": base(), "submit": "delay", "success_text": OK_TEXT, "expected_outcome": "CONFIRMED", "expected_status": "SUBMITTED"},
        {"id": "sub_navigates_away", "description": "submit navigates to a separate confirmation page", "source": base_src,
         "qs": base(), "submit": "navigate", "success_text": OK_TEXT, "expected_outcome": "CONFIRMED", "expected_status": "SUBMITTED"},
        {"id": "sub_optional_unresolved", "description": "optional question unresolved; required ones answered",
         "source": base_src, "qs": base([R("fax", "Fax", "text", tags=["missing"])]), "submit": "success",
         "success_text": OK_TEXT, "expected_outcome": "CONFIRMED", "expected_status": "SUBMITTED"},
    ]
