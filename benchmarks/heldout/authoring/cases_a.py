from hh import *

# ---------------------------------------------------------------- h01
c1_src = {
 "company": {"legal_name": "Brightloop Software Inc.", "founded": "2014-06-02",
  "hq": {"city": "Austin", "state": "TX", "country": "US"}, "website": "https://www.brightloop.io",
  "parent_company": {"name": "Halvorsen Holdings Ltd", "country": "GB"}},
 "headcount": {"total": 412, "engineering": 168, "support": 57, "contractors": 31},
 "security": {"mfa": {"enforced_for_admins": True, "enforced_for_all_users": False},
  "encryption": {"at_rest": "AES-256", "in_transit": "TLS 1.2+"},
  "pen_test": {"last_date": "2026-02-17", "vendor": "Cobalt Labs"},
  "soc2": {"type": "Type II", "report_period_end": "2025-12-31"},
  "ciso_email": "ciso@brightloop.io", "incident_contact_phone": "+1 512 555 0147",
  "data_residency_regions": ["us-east", "eu-west"], "subprocessors_count": 19}}
c1 = dict(id="h01_saas_security", description="SaaS vendor security review; engineer-natural nested JSON", source=c1_src,
 source_style="engineer-natural", qs=[
 a("vendor_name", "1.1 Legal name of vendor *", "Brightloop Software Inc.", "company.legal_name", "Direct match.", "nested realistic", required=True, section="1. Company"),
 a("q2", "1.2 Total number of employees", 412, "headcount.total", "Total headcount; contractors are a separate distractor key.", "nested paraphrase distractor", kind="number"),
 a("q3", "1.3 Customer support personnel (headcount)", 57, "headcount.support", "Role-scoped; support key exists.", "scoped paraphrase", kind="number"),
 r("q4", "1.4 Number of part-time employees", "Only total/role headcounts exist; no part-time split.", "scoped missing", kind="number"),
 r("q5", "1.5 Number of employees located in EMEA", "No geographic headcount in data.", "scoped missing", kind="number"),
 a("parent", "1.6 Name of parent company", "Halvorsen Holdings Ltd", "company.parent_company.name", "Related entity explicitly stored under parent_company.", "related_entity nested"),
 a("mfa_all", "2.1 Is multi-factor authentication required for all users?", "no", "security.mfa.enforced_for_all_users", "Boolean False means not required for all users.", "polarity nested", kind="radio", options=YN, section="2. Security"),
 a("mfa_opt", "2.2 Is MFA optional for administrator accounts?", "no", "security.mfa.enforced_for_admins", "Enforced for admins is True, so optional is No (plain inversion).", "polarity contestable", kind="radio", options=YN),
 a("pentest", "2.3 Date of most recent penetration test", "2026-02-17", "security.pen_test.last_date", "ISO date direct.", "nested", kind="date", style="wrap"),
 a("enc", "2.4 Encryption standard for data at rest", "aes256", "security.encryption.at_rest", "Option label AES-256 maps to value aes256.", "option_mapping", kind="select", options=[("aes128", "AES-128"), ("aes256", "AES-256"), ("none", "None")]),
 a("soc", "2.5 SOC 2 report type", "t2", "security.soc2.type", "Type II maps to t2.", "option_mapping", kind="radio", options=[("t1", "Type I"), ("t2", "Type II")]),
 a("ciso", "2.6 Security contact email (CISO)", "ciso@brightloop.io", "security.ciso_email", "Direct.", "paraphrase", kind="email", style="aria_label"),
 r("iso27001", "2.7 Do you hold ISO 27001 certification?", "No certification information in data.", "missing", kind="radio", options=YNN),
 h("iso_exp", "ISO 27001 certificate expiry", "Hidden until ISO answered yes; data has none.", when=("iso27001", "yes"), kind="date"),
 r("ir", "2.8 Describe your incident response process", "Narrative; nothing in data.", "narrative", kind="textarea"),
 r("sub", "2.9 Number of sub-processors in the EU", "Only a global sub-processor count (19) exists; EU scope absent.", "scoped distractor", kind="number"),
])

# ---------------------------------------------------------------- h02
c2_src = {"Supplier legal name": "Meridian Surgical Supplies LLC", "Trading name": "Meridian MedSupply",
 "Tax identification number (EIN)": "84-2917736", "Year established": 2003, "Number of employees": 86,
 "Number of sales representatives": 14, "Primary contact name": "Dolores Haines",
 "Primary contact email": "dhaines@meridianmed.com", "Primary contact phone": "312-555-0188",
 "Company registered state": "Illinois", "Is the company FDA registered?": "Yes",
 "FDA establishment registration number": "3014482291", "Is the company a minority-owned business?": "No",
 "Product liability insurance coverage (USD)": 5000000, "Insurance expiry date": "2027-04-30",
 "Number of warehouses": 3, "Distributor of record for": ["Orthopedic implants", "Wound care"],
 "Parent company": "None", "Subsidiaries": None}
c2 = dict(id="h02_hospital_supplier", description="Hospital supplier onboarding; form-aligned flat keys", source=c2_src,
 source_style="form-aligned", qs=[
 a("legal", "Supplier legal name", "Meridian Surgical Supplies LLC", "Supplier legal name", "Exact key.", "realistic", required=True, section="Supplier"),
 a("dba", "Trading name / DBA (optional)", "Meridian MedSupply", "Trading name", "Synonym DBA.", "paraphrase", style="placeholder"),
 a("ein", "Federal Tax ID (EIN)", "84-2917736", "Tax identification number (EIN)", "Acronym match; pattern satisfied.", "paraphrase", attrs={"pattern": r"\d{2}-\d{7}"}),
 a("est", "Year established", 2003, "Year established", "Direct.", "", kind="number", attrs={"min": "1800", "max": "2026"}),
 a("staff", "Number of staff", 86, "Number of employees", "Staff = employees.", "paraphrase", kind="number"),
 a("reps", "Sales headcount", 14, "Number of sales representatives", "Sales headcount = sales representatives.", "paraphrase", kind="number"),
 a("state", "Registered state", "IL", "Company registered state", "State name to code option.", "option_mapping", kind="select", options=[("IL", "Illinois"), ("IN", "Indiana"), ("WI", "Wisconsin")]),
 a("fda", "Is your company registered with the FDA?", "yes", "Is the company FDA registered?", "Yes.", "", kind="radio", options=YNN),
 a("fdanum", "FDA establishment registration number", "3014482291", "FDA establishment registration number", "Shown after FDA=yes.", "conditional", when=("fda", "yes")),
 a("mino", "Minority-owned business?", "no", "Is the company a minority-owned business?", "No.", "", kind="radio", options=YN, style="div_label"),
 a("pli", "Product liability insurance limit (USD)", 5000000, "Product liability insurance coverage (USD)", "Direct.", "paraphrase", kind="number"),
 a("exp", "Insurance expiry date", "2027-04-30", "Insurance expiry date", "ISO.", "", kind="date"),
 a("cats", "Product categories you distribute", ["ortho", "wound"], "Distributor of record for", "Labels map to values.", "option_mapping", kind="checkbox_group", options=[("ortho", "Orthopedic implants"), ("wound", "Wound care"), ("cardio", "Cardiology devices"), ("dx", "Diagnostics")]),
 r("parent", "Parent company name", "Data value is the placeholder 'None'; unclear if intended answer or no data.", "ambiguous contestable"),
 r("subs", "Subsidiaries", "Null.", "missing"),
 r("rns", "Number of employees holding a clinical licence", "Only total and sales headcounts exist; credential-scoped count absent.", "scoped distractor", kind="number"),
 r("excl", "We certify that we are not excluded from federal healthcare programs", "Attestation.", "declaration", kind="checkbox"),
])
