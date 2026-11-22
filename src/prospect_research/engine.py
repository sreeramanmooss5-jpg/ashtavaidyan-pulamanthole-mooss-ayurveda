from typing import Any, Dict, List
from src.common.idempotency import extract_domain, find_existing_prospect_keys, normalize_key

MANUFACTURER_KEYWORDS = (
    "manufacturer",
    "manufacturing",
    "own brand",
    "own-brand",
    "gmp factory",
    "formulator",
)


def is_excluded_manufacturer(candidate: Dict[str, Any], exceptions_rows: List[List[Any]]) -> bool:
    category_text = f"{candidate.get('buyer_category', '')} {candidate.get('notes', '')}".lower()
    company_norm = normalize_key(candidate.get("company", ""))
    has_keyword = any(k in category_text for k in MANUFACTURER_KEYWORDS)
    if not has_keyword:
        return False
    for row in exceptions_rows[1:]:
        if len(row) > 9:
            exc_comp = normalize_key(row[2])
            written_approval = str(row[9]).strip().lower()
            has_ext_proc = "independent" in str(row[6]).strip().lower() or "external" in str(row[5]).strip().lower()
            if exc_comp and exc_comp in company_norm and written_approval == "approved" and has_ext_proc:
                return False
    return True


def stage_verified_prospects(
    candidates: List[Dict[str, Any]],
    existing_crm_rows: List[List[Any]],
    exceptions_rows: List[List[Any]],
) -> Dict[str, Any]:
    keys = find_existing_prospect_keys(existing_crm_rows[1:] if len(existing_crm_rows) > 1 else [])
    staged: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for cand in candidates:
        comp = str(cand.get("company", "")).strip()
        email = str(cand.get("email", "")).strip()
        website = str(cand.get("website", "")).strip()
        source_url = str(cand.get("source_url", "")).strip()

        if not comp or not website or not source_url:
            skipped.append({"company": comp or "UNKNOWN", "reason": "Missing verified company, official website, or source_url"})
            continue

        if is_excluded_manufacturer(cand, exceptions_rows):
            skipped.append({"company": comp, "reason": "Excluded per manufacturer exclusion policy MFE-001"})
            continue

        c_norm = normalize_key(comp)
        e_norm = normalize_key(email)
        d_norm = extract_domain(website) or extract_domain(email)

        if c_norm in keys["companies"] or (e_norm and e_norm in keys["emails"]) or (d_norm and d_norm in keys["domains"]):
            skipped.append({"company": comp, "reason": "Duplicate prospect already present in Global_Prospect_CRM"})
            continue

        keys["companies"].add(c_norm)
        if e_norm:
            keys["emails"].add(e_norm)
        if d_norm:
            keys["domains"].add(d_norm)

        staged.append({
            **cand,
            "stage_status": "Pending Approval",
            "approval_status": "Pending",
        })

    return {"staged": staged, "skipped": skipped}
