"""Industry-specific rule packs. Classification Agent picks the right pack automatically."""
from dataclasses import dataclass, field


@dataclass
class RulePack:
    name: str
    display_name: str
    keywords: list[str]         # column name hints for auto-detection
    pii_fields: list[str]       # PII types expected in this dataset
    cleaning_steps: list[dict]  # ordered cleaning operations
    validation_checks: list[str]
    analytics_focus: list[str]
    compliance_notes: str = ""


CRM = RulePack(
    name="crm",
    display_name="Customer CRM Dataset",
    keywords=["customer", "client", "email", "phone", "address", "contact", "name", "lead"],
    pii_fields=["email", "phone", "national_id", "credit_card"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate customer records"},
        {"step": 2, "rule": "strip_whitespace",   "description": "Strip whitespace from all text fields"},
        {"step": 3, "rule": "normalize_case",     "description": "Normalize name casing to title case"},
        {"step": 4, "rule": "fill_missing_mode",  "description": "Fill missing categorical fields with mode"},
    ],
    validation_checks=["no_duplicates", "email_format", "phone_format"],
    analytics_focus=["dormant_accounts", "incomplete_profiles", "duplicate_customers", "contact_coverage"],
    compliance_notes="GDPR applies — contains PII. Mask before export.",
)

INVENTORY = RulePack(
    name="inventory",
    display_name="Inventory / Stock Dataset",
    keywords=["sku", "stock", "quantity", "product", "item", "warehouse", "barcode", "unit", "price", "bin"],
    pii_fields=[],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate SKU entries"},
        {"step": 2, "rule": "strip_whitespace",   "description": "Normalize product names"},
        {"step": 3, "rule": "fill_missing_mean",  "description": "Fill missing numeric quantities"},
        {"step": 4, "rule": "remove_empty_rows",  "description": "Remove completely empty rows"},
    ],
    validation_checks=["positive_quantities", "valid_skus", "price_consistency"],
    analytics_focus=["zero_stock", "overstock", "pricing_anomalies", "slow_moving_items"],
    compliance_notes="No significant PII. Standard data quality applies.",
)

FINANCE = RulePack(
    name="finance",
    display_name="Financial / Transaction Dataset",
    keywords=["transaction", "amount", "debit", "credit", "balance", "account", "invoice", "payment", "ledger"],
    pii_fields=["credit_card", "account_number", "national_id"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate transactions"},
        {"step": 2, "rule": "normalize_dates",    "description": "Standardize transaction date formats"},
        {"step": 3, "rule": "fill_missing_mean",  "description": "Fill missing amount fields"},
        {"step": 4, "rule": "strip_whitespace",   "description": "Clean reference fields"},
    ],
    validation_checks=["positive_amounts", "date_validity", "no_duplicate_invoices"],
    analytics_focus=["duplicate_invoices", "amount_anomalies", "payment_patterns", "overdue_accounts"],
    compliance_notes="Sensitive financial data. Mask account/card numbers before sharing.",
)

HR = RulePack(
    name="hr",
    display_name="HR / Employee Dataset",
    keywords=["employee", "staff", "department", "salary", "hire", "position", "manager", "headcount", "payroll"],
    pii_fields=["national_id", "email", "phone", "ssn"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate employee records"},
        {"step": 2, "rule": "normalize_case",     "description": "Normalize name and department casing"},
        {"step": 3, "rule": "fill_missing_mode",  "description": "Fill missing department values"},
        {"step": 4, "rule": "strip_whitespace",   "description": "Clean all text fields"},
    ],
    validation_checks=["unique_employee_ids", "valid_salary_range", "department_consistency"],
    analytics_focus=["salary_outliers", "department_headcount", "tenure_analysis", "missing_records"],
    compliance_notes="Highly sensitive. GDPR + local labor law compliance required.",
)

HEALTHCARE = RulePack(
    name="healthcare",
    display_name="Healthcare / Patient Dataset",
    keywords=["patient", "diagnosis", "medication", "doctor", "hospital", "medical", "record", "dob", "clinical"],
    pii_fields=["national_id", "email", "phone", "passport"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate patient records"},
        {"step": 2, "rule": "normalize_dates",    "description": "Standardize date of birth and visit dates"},
        {"step": 3, "rule": "strip_whitespace",   "description": "Clean medical record fields"},
        {"step": 4, "rule": "fill_missing_mode",  "description": "Fill missing categorical diagnosis fields"},
    ],
    validation_checks=["valid_patient_ids", "dob_validity", "no_duplicate_records"],
    analytics_focus=["missing_diagnoses", "age_distribution", "repeat_visits", "data_completeness"],
    compliance_notes="CRITICAL: HIPAA + health data regulations apply. Strict masking required.",
)

SALES = RulePack(
    name="sales",
    display_name="Sales / Orders Dataset",
    keywords=["order", "sale", "revenue", "rep", "region", "commission", "pipeline", "deal", "opportunity"],
    pii_fields=["email", "phone"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate orders"},
        {"step": 2, "rule": "normalize_dates",    "description": "Standardize order dates"},
        {"step": 3, "rule": "fill_missing_mean",  "description": "Fill missing revenue figures"},
        {"step": 4, "rule": "strip_whitespace",   "description": "Clean region and rep name fields"},
    ],
    validation_checks=["positive_revenue", "valid_dates", "region_consistency"],
    analytics_focus=["top_performers", "regional_variance", "seasonal_patterns", "at_risk_deals"],
    compliance_notes="May contain customer contact info. Minimal PII handling.",
)

HOSPITALITY = RulePack(
    name="hospitality",
    display_name="Hospitality / Reservations Dataset",
    keywords=["reservation", "booking", "room", "guest", "checkin", "checkout", "branch", "occupancy", "hotel"],
    pii_fields=["email", "phone", "national_id"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate bookings"},
        {"step": 2, "rule": "normalize_dates",    "description": "Standardize check-in/out dates"},
        {"step": 3, "rule": "fill_missing_mode",  "description": "Fill missing room type fields"},
        {"step": 4, "rule": "strip_whitespace",   "description": "Clean guest names and references"},
    ],
    validation_checks=["valid_dates", "no_overlapping_reservations", "branch_consistency"],
    analytics_focus=["occupancy_rates", "branch_performance", "seasonal_trends", "cancellation_rate"],
    compliance_notes="Guest data is PII. Apply GDPR / local privacy laws.",
)

SUPPLIER = RulePack(
    name="supplier",
    display_name="Supplier / Vendor Dataset",
    keywords=["supplier", "vendor", "purchase", "procurement", "contract", "delivery", "lead_time"],
    pii_fields=["email", "phone"],
    cleaning_steps=[
        {"step": 1, "rule": "remove_duplicates",  "description": "Remove duplicate supplier entries"},
        {"step": 2, "rule": "strip_whitespace",   "description": "Clean supplier names and contacts"},
        {"step": 3, "rule": "normalize_case",     "description": "Normalize supplier name casing"},
        {"step": 4, "rule": "fill_missing_mode",  "description": "Fill missing category fields"},
    ],
    validation_checks=["unique_supplier_ids", "contact_completeness"],
    analytics_focus=["cost_variance", "delivery_performance", "preferred_vs_others", "inactive_suppliers"],
    compliance_notes="Minimal PII. Standard business data.",
)

RULE_PACKS: dict[str, RulePack] = {
    "crm": CRM,
    "inventory": INVENTORY,
    "finance": FINANCE,
    "hr": HR,
    "healthcare": HEALTHCARE,
    "sales": SALES,
    "hospitality": HOSPITALITY,
    "supplier": SUPPLIER,
}


def get_rule_pack(dataset_type: str) -> RulePack | None:
    return RULE_PACKS.get((dataset_type or "").lower())
