from typing import Any, Dict, List
from src.common.idempotency import extract_domain, normalize_key

REQUIRED_PROSPECT_FIELDS = ("Lead_ID", "Company", "Country", "Business_Category", "Current_Status")


def verify_crm_records(crm_rows: List[List[Any]]) -> Dict[str, Any]:
    if not crm_rows or len(crm_rows) < 2:
        return {"total_rows": 0, "valid_count": 0, "invalid_rows": [], "duplicate_groups": []}

    headers = crm_rows[0]
    idx = {h.strip(): i for i, h in enumerate(headers)}
    valid_count = 0
    invalid_rows: List[Dict[str, Any]] = []
    seen_company: Dict[str, List[str]] = {}
    seen_email: Dict[str, List[str]] = {}

    for r_num, row in enumerate(crm_rows[1:], start=2):
        lead_id = str(row[idx["Lead_ID"]] if "Lead_ID" in idx and idx["Lead_ID"] < len(row) else "").strip()
        company = str(row[idx["Company"]] if "Company" in idx and idx["Company"] < len(row) else "").strip()
        country = str(row[idx["Country"]] if "Country" in idx and idx["Country"] < len(row) else "").strip()
        category = str(row[idx["Business_Category"]] if "Business_Category" in idx and idx["Business_Category"] < len(row) else "").strip()
        email = str(row[idx["Email"]] if "Email" in idx and idx["Email"] < len(row) else "").strip().lower()
        status = str(row[idx["Current_Status"]] if "Current_Status" in idx and idx["Current_Status"] < len(row) else "").strip()

        missing = [f for f, v in [("Lead_ID", lead_id), ("Company", company), ("Country", country), ("Business_Category", category), ("Current_Status", status)] if not v]
        if missing:
            invalid_rows.append({"row_number": r_num, "lead_id": lead_id, "missing": missing})
        else:
            valid_count += 1

        c_key = normalize_key(company)
        if c_key:
            seen_company.setdefault(c_key, []).append(lead_id or f"Row-{r_num}")
        if email and "@" in email and email != "unknown":
            seen_email.setdefault(email, []).append(lead_id or f"Row-{r_num}")

    dup_companies = {k: v for k, v in seen_company.items() if len(v) > 1}
    dup_emails = {k: v for k, v in seen_email.items() if len(v) > 1}

    return {
        "total_rows": len(crm_rows) - 1,
        "valid_count": valid_count,
        "invalid_rows": invalid_rows,
        "duplicate_companies": dup_companies,
        "duplicate_emails": dup_emails,
        "domains_indexed": len({extract_domain(str(r[idx["Website"]])) for r in crm_rows[1:] if "Website" in idx and idx["Website"] < len(r) and str(r[idx["Website"]]).strip()}),
    }
