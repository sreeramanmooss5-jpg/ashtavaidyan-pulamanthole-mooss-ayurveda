from typing import Any, Dict, List
from src.common.idempotency import normalize_key

BLOCKED_STATUS_TOKENS = (
    "suppressed",
    "bounced",
    "unsubscribed",
    "dnc",
    "declined",
    "excluded",
    "manufacturer",
)


def build_eligible_followup_queue(
    crm_rows: List[List[Any]],
    suppression_rows: List[List[Any]],
    replies_rows: List[List[Any]],
    exceptions_rows: List[List[Any]],
    allow_external_dispatch: bool = False,
) -> Dict[str, Any]:
    # Hard safety guard: external dispatch stays disabled unless explicitly approved & unlocked
    suppressed_targets = set()
    for r in suppression_rows[1:] if len(suppression_rows) > 1 else []:
        if len(r) > 1 and str(r[1]).strip():
            suppressed_targets.add(normalize_key(r[1]))

    replied_senders = set()
    for r in replies_rows[1:] if len(replies_rows) > 1 else []:
        for cell in r:
            s = normalize_key(cell)
            if "@" in s:
                replied_senders.add(s)

    approved_exceptions = set()
    for r in exceptions_rows[1:] if len(exceptions_rows) > 1 else []:
        if len(r) > 9 and str(r[9]).strip().lower() == "approved":
            approved_exceptions.add(normalize_key(r[2]))

    headers = crm_rows[0] if crm_rows else []
    idx = {h.strip(): i for i, h in enumerate(headers)}
    eligible: List[Dict[str, str]] = []
    held: List[Dict[str, str]] = []

    for row in crm_rows[1:] if len(crm_rows) > 1 else []:
        lead_id = str(row[idx["Lead_ID"]] if "Lead_ID" in idx and idx["Lead_ID"] < len(row) else "").strip()
        company = str(row[idx["Company"]] if "Company" in idx and idx["Company"] < len(row) else "").strip()
        email = str(row[idx["Email"]] if "Email" in idx and idx["Email"] < len(row) else "").strip().lower()
        ver_status = str(row[idx["Email_Verification_Status"]] if "Email_Verification_Status" in idx and idx["Email_Verification_Status"] < len(row) else "").strip().lower()
        status = str(row[idx["Current_Status"]] if "Current_Status" in idx and idx["Current_Status"] < len(row) else "").strip().lower()

        if not email or "@" not in email or email == "unknown":
            held.append({"lead_id": lead_id, "company": company, "reason": "Missing verified email address"})
            continue
        if email in suppressed_targets or any(tok in status for tok in BLOCKED_STATUS_TOKENS):
            held.append({"lead_id": lead_id, "company": company, "reason": "Suppressed / DNC / Bounced / Excluded"})
            continue
        if email in replied_senders:
            held.append({"lead_id": lead_id, "company": company, "reason": "Active or prior reply received — manual handling required"})
            continue
        if "manufacturer" in status and normalize_key(company) not in approved_exceptions:
            held.append({"lead_id": lead_id, "company": company, "reason": "Manufacturer exclusion MFE-001 without approved exception"})
            continue
        if "verified" not in ver_status or "bounced" in ver_status or "unverified" in ver_status:
            held.append({"lead_id": lead_id, "company": company, "reason": "Email verification status not verified"})
            continue

        eligible.append({
            "lead_id": lead_id,
            "company": company,
            "email": email,
            "dispatch_mode": "QUEUED_APPROVAL_REQUIRED" if not allow_external_dispatch else "QUEUED_APPROVAL_REQUIRED",
        })

    return {
        "eligible_count": len(eligible),
        "held_count": len(held),
        "eligible_queue": eligible,
        "held_sample": held[:10],
        "external_dispatch_enabled": False,
    }
