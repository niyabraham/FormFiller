# Remaining ambiguous missed answers (candidate run on c918f1f)


## rfi

| question | expected | top | runner-up |
|---|---|---|---|
| c06_ Number of countries you operate in | company.countries_of_operation | company.countries_of_operation (0.5) | company.country (0.5) |
| c07_ Billing email address | billing_email | billing_email (0.8) | address.billing (0.6667) |
| c07_ Do you have an account manager? | has_account_manager | account_manager (1.0) | has_account_manager (1.0) |
| c10_ Who is your Data Protection Officer? | privacy.dpo_name | privacy.dpo_email (0.6667) | privacy.dpo_name (0.6667) |
| c13_ E.1 Do you maintain a tested business continuity a | policies.bcp_dr.exists | incident.has_plan (0.25) | policies.bcp_dr.last_tested (0.2222) |
| c13_ G.2 Can you share your most recent SOC 2 Type II r | compliance.soc2.report_available_under_nda | compliance.soc2.report_available_under_nda (0.5) | compliance.soc2.type (0.3667) |
| c13_ J.1 Penetration testing frequency | pentest.frequency | access.access_reviews.frequency (0.5) | pentest.frequency (0.5) |
| c16_ Account manager name | account_manager | account_manager (0.8) | account_manager_assigned (0.6667) |

## heldout

| question | expected | top | runner-up |
|---|---|---|---|
| h01_ 2.5 SOC 2 report type | security.soc2.type | security.soc2.type (0.5) | security.soc2.report_period_end (0.4857) |
| h02_ Sales headcount | Number of sales representatives | Number of employees (0.5) | Number of sales representatives (0.5) |
| h04_ Single project bonding capacity ($) | Company Information.Bonding capacity (single project) | Company Information.Bonding capacity (aggregate) (0.8667) | Company Information.Bonding capacity (single project) (0.8667) |
| h04_ Aggregate bonding capacity ($) | Company Information.Bonding capacity (aggregate) | Company Information.Bonding capacity (aggregate) (1.0) | Company Information.Bonding capacity (single project) (1.0) |
| h06_ 6. Total headcount (all staff) | Total staff | Office locations.0.staff (1.0) | Office locations.1.staff (1.0) |
| h07_ Employer Identification Number (EIN) | org.ein | affiliates.chapters.0.ein (0.5) | org.ein (0.5) |
| h07_ Number of independent directors | people.independent_board_members | contact.executive_director (0.5) | people.independent_board_members (0.4) |
| h07_ Total revenue, most recent fiscal year (USD) | finance.total_revenue | finance.total_revenue (0.4444) | finance.fiscal_year_end (0.4444) |
| h07_ Percentage of revenue from government sources | finance.government_funding_pct | finance.total_revenue (0.3333) | finance.government_funding_pct (0.2857) |
| h07_ Were your financial statements audited by an indep | finance.audited | finance.audited (0.2857) | finance.audit_firm (0.25) |
| h07_ Name of auditor | finance.audit_firm | affiliates.chapters.0.name (0.6667) | org.name (0.6667) |
| h07_ Does the organisation lack a whistleblower policy? | governance.whistleblower_policy | finance.audit_firm (0.3) | governance.conflict_of_interest_policy (0.3) |
| h07_ Were there any related-party transactions last fis | governance.has_no_related_party_transactions | governance.has_no_related_party_transactions (0.5) | finance.fiscal_year_end (0.3636) |
| h08_ Number of refrigerated trailers | carrier.fleet.reeferTrailers | carrier.fleet.reeferTrailers (0.5) | carrier.fleet.trailers (0.5) |
| h10_ Immediate parent company name | parent.name | parent.company_number (0.5455) | parent.name (0.5455) |
| h10_ Immediate parent company registration number | parent.company_number | parent.company_number (0.5455) | supplier.company_number (0.44) |
| h11_ Name of franchise owner / principal | franchisee.owner | franchisee.name (0.4) | franchisee.owner (0.4) |
| h11_ Opening date of store 114 | franchisee.locations.0.opened | franchisee.locations.0.store_no (0.3333) | franchisee.locations.1.store_no (0.3333) |
| h12_ Can customers export their data without vendor ass | Product.Data export.self_service | Product.Customer count (0.2) | Product.Largest customer seats (0.1818) |
| h12_ Supported mobile platforms | Product.Mobile apps.ios | Product.Offline mode.supported (0.5) | Product.Languages supported (0.4) |
| h13_ Name of largest customer | plant.customers_top.0.name | plant.customers_top.0.name (0.6667) | plant.customers_top.1.name (0.6667) |
| h13_ Share of sales to the largest customer (%) | plant.customers_top.0.share_pct | plant.customers_top.0.share_pct (0.4286) | plant.customers_top.1.share_pct (0.4286) |
| h13_ Name of the owning entity | plant.owner.name | plant.customers_top.0.name (0.5) | plant.customers_top.1.name (0.5) |
| h14_ Total number of personnel | Headcount.Total internal staff | Branch offices.0.staff (1.0) | Branch offices.1.staff (1.0) |
| h14_ States where you hold staffing licences | Licensed states | Branch offices.0.state (0.3333) | Branch offices.1.state (0.3333) |
