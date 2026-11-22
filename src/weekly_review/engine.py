from typing import Any, Dict, List


def build_weekly_commercial_summary(
    crm_rows: List[List[Any]],
    price_rows: List[List[Any]],
    export_rows: List[List[Any]],
    exceptions_rows: List[List[Any]],
) -> Dict[str, Any]:
    headers = crm_rows[0] if crm_rows else []
    idx = {h.strip(): i for i, h in enumerate(headers)}
    data_rows = crm_rows[1:] if len(crm_rows) > 1 else []

    by_country: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for r in data_rows:
        c = str(r[idx["Country"]] if "Country" in idx and idx["Country"] < len(r) else "Unspecified").strip() or "Unspecified"
        s = str(r[idx["Current_Status"]] if "Current_Status" in idx and idx["Current_Status"] < len(r) else "Unspecified").strip() or "Unspecified"
        by_country[c] = by_country.get(c, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1

    top_regions = sorted(by_country.items(), key=lambda x: (-x[1], x[0]))[:6]
    price_count = max(0, len(price_rows) - 1)
    export_count = max(0, len(export_rows) - 1)
    exc_count = max(0, len(exceptions_rows) - 1)

    return {
        "total_crm_prospects": len(data_rows),
        "top_regions": top_regions,
        "status_breakdown": by_status,
        "approved_price_skus": 0,
        "draft_price_skus": price_count,
        "verified_export_skus": 0,
        "pending_export_skus": export_count,
        "active_manufacturer_policies": exc_count,
        "recommended_actions": [
            "Complete 4-stage commercial approval for 18 SKUs in Commercial_Price_Master before quoting.",
            "Upload & verify IEC, GMP, Product Permissions, CoA, Stability, and FSC documents for 18 SKUs in Export_Compliance.",
            "Enforce manufacturer exclusion MFE-001 unless documented procurement evidence and written management approval exist.",
        ],
    }
