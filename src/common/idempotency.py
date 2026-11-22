import hashlib
import json
from typing import Any, Dict, Iterable, List, Set


def build_idempotency_key(workflow_name: str, run_date_ist: str, scope: str = "") -> str:
    raw = f"{workflow_name}|{run_date_ist}|{scope}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"{workflow_name}-{run_date_ist}-{digest}"


def is_already_completed(log_rows: Iterable[List[Any]], idempotency_key: str) -> bool:
    for row in log_rows:
        if len(row) > 1 and str(row[1]).strip() == idempotency_key:
            status = str(row[6]).strip().lower() if len(row) > 6 else ""
            if status in ("completed", "success", "verified"):
                return True
    return False


def normalize_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def extract_domain(url_or_email: Any) -> str:
    text = str(url_or_email or "").strip().lower()
    if "@" in text and "://" not in text:
        return text.split("@", 1)[1].strip("/")
    text = text.replace("https://", "").replace("http://", "").replace("www.", "")
    return text.split("/", 1)[0].strip()


def find_existing_prospect_keys(crm_rows: Iterable[List[Any]]) -> Dict[str, Set[str]]:
    companies: Set[str] = set()
    emails: Set[str] = set()
    domains: Set[str] = set()
    for row in crm_rows:
        if not row:
            continue
        comp = normalize_key(row[1] if len(row) > 1 else "")
        em = normalize_key(row[7] if len(row) > 7 else "")
        web = extract_domain(row[10] if len(row) > 10 else "")
        if comp:
            companies.add(comp)
        if em and "@" in em:
            emails.add(em)
            domains.add(extract_domain(em))
        if web:
            domains.add(web)
    return {"companies": companies, "emails": emails, "domains": domains}
