from typing import Any, Dict, List


def build_daily_report_metrics(
    crm_rows: List[List[Any]],
    suppression_rows: List[List[Any]],
    price_rows: List[List[Any]],
    export_rows: List[List[Any]],
    followup_summary: Dict[str, Any],
    execution_log_rows: List[List[Any]],
) -> Dict[str, Any]:
    headers = crm_rows[0] if crm_rows else []
    idx = {h.strip(): i for i, h in enumerate(headers)}
    data_rows = crm_rows[1:] if len(crm_rows) > 1 else []

    tier_a = 0
    tier_b = 0
    qualified_count = 0
    verified_emails = 0

    for r in data_rows:
        tier = str(r[idx["Priority_Tier"]] if "Priority_Tier" in idx and idx["Priority_Tier"] < len(r) else "").strip()
        st = str(r[idx["Current_Status"]] if "Current_Status" in idx and idx["Current_Status"] < len(r) else "").strip().lower()
        ev = str(r[idx["Email_Verification_Status"]] if "Email_Verification_Status" in idx and idx["Email_Verification_Status"] < len(r) else "").strip().lower()
        if "Priority A" in tier:
            tier_a += 1
        elif "Priority B" in tier:
            tier_b += 1
        if "qualified" in st or "outreach eligible" in st:
            qualified_count += 1
        if ev.startswith("verified"):
            verified_emails += 1

    price_data = price_rows[1:] if len(price_rows) > 1 else []
    draft_skus = sum(1 for r in price_data if "draft" in " ".join(str(c).lower() for c in r))

    export_data = export_rows[1:] if len(export_rows) > 1 else []
    pending_export_skus = sum(1 for r in export_data if "pending" in " ".join(str(c).lower() for c in r))

    failed_runs = sum(
        1 for r in (execution_log_rows[1:] if len(execution_log_rows) > 1 else [])
        if len(r) > 6 and any(k in str(r[6]).lower() for k in ("fail", "error", "blocked"))
    )

    return {
        "total_prospects": len(data_rows),
        "qualified_or_eligible_buyers": qualified_count,
        "priority_a": tier_a,
        "priority_b": tier_b,
        "verified_email_records": verified_emails,
        "suppression_count": max(0, len(suppression_rows) - 1),
        "eligible_followups": followup_summary.get("eligible_count", 0),
        "draft_price_skus": draft_skus,
        "total_price_skus": len(price_data),
        "pending_export_skus": pending_export_skus,
        "total_export_skus": len(export_data),
        "failed_or_blocked_log_entries": failed_runs,
        "pending_human_approvals": 4,
    }
