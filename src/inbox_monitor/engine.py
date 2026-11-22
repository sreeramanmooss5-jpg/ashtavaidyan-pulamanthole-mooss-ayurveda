import re
from typing import Dict, List

HARD_BOUNCE_PATTERNS = (
    "550 ",
    "550-",
    "554 ",
    "5.1.1",
    "5.7.13",
    "user unknown",
    "address does not exist",
    "recipient address rejected",
    "domain not found",
    "nxdomain",
    "undeliverable",
)

TEMP_DELAY_PATTERNS = (
    "421 ",
    "450 ",
    "451 ",
    "452 ",
    "temporary failure",
    "try again later",
    "delivery status notification (delay)",
    "delayed",
)

UNSUBSCRIBE_PATTERNS = (
    "unsubscribe",
    "remove me",
    "opt out",
    "opt-out",
    "stop emailing",
)

COMPLAINT_PATTERNS = (
    "spam",
    "harassment",
    "abuse",
    "complaint",
    "do not contact",
    "dnc",
)

PROCUREMENT_PATTERNS = (
    "quotation",
    "quote",
    "moq",
    "wholesale",
    "bulk",
    "purchase order",
    "proforma",
    "price list",
    "distributor",
    "stockist",
)


def classify_message(sender: str, subject: str, snippet: str) -> Dict[str, str]:
    s_low = (sender or "").lower()
    sub_low = (subject or "").lower()
    snip_low = (snippet or "").lower()
    combined = f"{sub_low} {snip_low}"

    if "mailer-daemon" in s_low or "postmaster" in s_low or "delivery status notification" in sub_low:
        if any(p in combined for p in HARD_BOUNCE_PATTERNS):
            emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", f"{subject} {snippet}")
            filtered = [e.lower() for e in emails if not e.lower().endswith("@srdayurveda.com") and "mailer-daemon" not in e.lower()]
            return {
                "category": "hard_bounce",
                "target_email": filtered[0] if filtered else "",
                "suppression_required": "true",
            }
        if any(p in combined for p in TEMP_DELAY_PATTERNS):
            return {"category": "temp_delay", "target_email": "", "suppression_required": "false"}

    if any(p in combined for p in UNSUBSCRIBE_PATTERNS):
        return {"category": "unsubscribe", "target_email": sender.lower(), "suppression_required": "true"}

    if any(p in combined for p in COMPLAINT_PATTERNS):
        return {"category": "complaint", "target_email": sender.lower(), "suppression_required": "true"}

    if any(p in combined for p in PROCUREMENT_PATTERNS):
        return {"category": "procurement_request", "target_email": sender.lower(), "suppression_required": "false"}

    if "re:" in sub_low or "reply" in combined:
        return {"category": "reply", "target_email": sender.lower(), "suppression_required": "false"}

    return {"category": "buyer_enquiry", "target_email": sender.lower(), "suppression_required": "false"}


def summarize_classifications(items: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        cat = item.get("category", "buyer_enquiry")
        counts[cat] = counts.get(cat, 0) + 1
    return counts
