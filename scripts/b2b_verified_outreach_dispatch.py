#!/usr/bin/env python3
"""Guarded B2B email dispatch for verified, qualified SRD Ayurvedics prospects.

The dispatcher deliberately fails closed: only explicitly verified email addresses
on qualified CRM rows can be contacted. Every send is reserved in the CRM first.
A crash after reservation leaves the row in DISPATCHING for manual reconciliation,
rather than risking a duplicate send.
"""
import base64
import datetime as dt
import json
import os
import re
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Set
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.common.gmail_client import GmailReadClient
from src.common.google_sheets import GoogleSheetsClient
from src.common.logging import get_logger, log_event

EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
BLOCKED = ("bounce", "unsub", "suppress", "do not contact", "dnc", "complaint", "declined", "excluded", "dispatched", "dispatching")
QUALIFIED_STATUSES = {"qualified", "outreach eligible", "pending outreach"}
MAX_DAILY_SEND_LIMIT = 20
COOLDOWN_DAYS = 7
MAX_TOUCHES = 4


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _date(value: Any):
    raw = str(value or "").strip()[:10]
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _header_index(headers: List[Any]) -> Dict[str, int]:
    return {str(h).strip(): i for i, h in enumerate(headers)}


def _cell(row: List[Any], idx: Dict[str, int], key: str) -> str:
    pos = idx.get(key)
    return str(row[pos]).strip() if pos is not None and pos < len(row) else ""


def _email_domain(value: str) -> str:
    return value.rsplit("@", 1)[1].lower() if "@" in value else ""


def _suppression_keys(rows: List[List[Any]]) -> Set[str]:
    if not rows:
        return set()
    headers = _header_index(rows[0])
    col = headers.get("Email_or_Domain", 1)
    result = set()
    for row in rows[1:]:
        if col < len(row):
            key = _norm(row[col]).strip(".")
            if key:
                result.add(key)
    return result


def _reply_senders(rows: List[List[Any]]) -> Set[str]:
    found = set()
    for row in rows[1:] if len(rows) > 1 else []:
        for value in row:
            text = _norm(value)
            found.update(x.lower() for x in re.findall(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", text, re.I))
    return found


def _touch_count(notes: str, last_sent: str) -> int:
    matches = re.findall(r"B2B_AUTOMATION_TOUCH=(\\d+)", notes or "")
    if matches:
        return int(matches[-1])
    return 1 if last_sent else 0


def build_dispatch_plan(
    crm_rows: List[List[Any]],
    suppression_rows: List[List[Any]],
    reply_rows: List[List[Any]],
    inbox_senders: Iterable[str],
    today: dt.date,
    daily_limit: int = 10,
) -> Dict[str, Any]:
    if not crm_rows:
        return {"eligible": [], "held": [{"reason": "CRM sheet is empty"}]}
    idx = _header_index(crm_rows[0])
    required = {"Lead_ID", "Company", "Email", "Email_Verification_Status", "Current_Status"}
    missing = sorted(required - set(idx))
    if missing:
        return {"eligible": [], "held": [{"reason": "Missing required CRM columns", "columns": missing}]}

    suppressed = _suppression_keys(suppression_rows)
    replied = _reply_senders(reply_rows) | {_norm(x) for x in inbox_senders if _norm(x)}
    limit = max(0, min(int(daily_limit), MAX_DAILY_SEND_LIMIT))
    eligible, held = [], []

    for row_number, row in enumerate(crm_rows[1:], start=2):
        lead_id = _cell(row, idx, "Lead_ID")
        company = _cell(row, idx, "Company")
        email = _cell(row, idx, "Email").lower()
        verification = _norm(_cell(row, idx, "Email_Verification_Status"))
        status = _norm(_cell(row, idx, "Current_Status"))
        last_sent = _cell(row, idx, "Last_Email_Sent")
        follow_up = _cell(row, idx, "Follow_Up_Date")
        notes = _cell(row, idx, "Notes")

        reason = ""
        if not lead_id or not company:
            reason = "Missing lead ID or company"
        elif not EMAIL_RE.fullmatch(email):
            reason = "Invalid email address"
        elif verification != "verified":
            reason = "Email verification status must be exactly Verified"
        elif email in suppressed or _email_domain(email) in suppressed:
            reason = "Email or domain is on the suppression list"
        elif any(token in status for token in BLOCKED):
            reason = "CRM status is blocked"
        elif email in replied:
            reason = "A reply exists; route to human sales handling"
        elif status == "dispatching":
            reason = "Previous dispatch reservation requires reconciliation"
        elif status in QUALIFIED_STATUSES and not last_sent:
            touch = 1
        elif status == "contacted":
            due = _date(follow_up)
            if not due or due > today:
                reason = "Follow-up is not due"
            elif (today - (_date(last_sent) or today)).days < COOLDOWN_DAYS:
                reason = "Seven-day recipient cooldown has not elapsed"
            else:
                touch = _touch_count(notes, last_sent) + 1
                if touch > MAX_TOUCHES:
                    reason = "Maximum outreach touches reached"
        else:
            reason = "Lead is not in an outreach-eligible CRM status"

        if reason:
            held.append({"row_number": row_number, "lead_id": lead_id, "reason": reason})
            continue

        eligible.append({
            "row_number": row_number,
            "lead_id": lead_id,
            "company": company,
            "email": email,
            "touch": touch,
        })

    return {"eligible": eligible[:limit], "held": held, "eligible_before_limit": len(eligible), "daily_limit": limit}


def build_message(company: str, contact: str, category: str, country: str, products: str, touch: int, sender: str) -> tuple[str, str]:
    greeting = contact if contact and _norm(contact) not in {"n/a", "na", "unknown"} else "Procurement Team"
    product_line = products or "classical Kerala Ayurveda formulations for wholesale and institutional supply"
    if touch == 1:
        subject = "Wholesale and institutional supply enquiry | Pulamanthole Mooss"
        opening = "I am reaching out to introduce our classical Kerala Ayurveda formulations and explore whether they may be relevant to your wholesale or institutional procurement requirements."
    else:
        subject = "Follow-up: Ayurveda wholesale and institutional supply"
        opening = "I am following up once on my earlier note about wholesale and institutional supply. If this is not relevant, no response is needed."
    body = f"""Dear {greeting},

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals, Kerala, India.

{opening}

We would be glad to understand your requirements at {company} ({category or 'buyer organisation'}, {country or 'your market'}). Areas of interest noted: {product_line}.

If relevant, we can share the current product catalogue, applicable trade terms, and product-specific regulatory documentation for your review. Product availability, pricing and export eligibility will be confirmed against your requirements.

Please reply if you would like the catalogue or a discussion with our wholesale desk.

Regards,
B2B Sales Team
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals
Pulamanthole, Kerala, India
Wholesale Desk: +91 9446567506
https://pulamantholemooss.com

To stop future business emails, reply with "Unsubscribe" or email {sender} with the subject "Unsubscribe".
"""
    return subject, body


def _reserve_row(sheets, spreadsheet_id: str, row_number: int, row: List[Any], idx: Dict[str, int], run_id: str):
    status_i = idx["Current_Status"]
    notes_i = idx.get("Notes")
    row[status_i] = "DISPATCHING"
    if notes_i is not None:
        old = str(row[notes_i]) if notes_i < len(row) else ""
        while len(row) <= notes_i:
            row.append("")
        row[notes_i] = (old + f" | B2B_DISPATCH_LOCK={run_id}").strip(" |")
    sheets.update_values(spreadsheet_id, f"Global_Prospect_CRM!A{row_number}:AA{row_number}", [row])


def _finish_row(sheets, spreadsheet_id: str, row_number: int, row: List[Any], idx: Dict[str, int], sent_at: dt.datetime, touch: int, message_id: str):
    def set_cell(name: str, value: str):
        pos = idx.get(name)
        if pos is not None:
            while len(row) <= pos:
                row.append("")
            row[pos] = value
    set_cell("Current_Status", "CONTACTED")
    set_cell("Last_Email_Sent", sent_at.isoformat())
    set_cell("Follow_Up_Date", (sent_at.date() + dt.timedelta(days=7 if touch == 1 else 10)).isoformat())
    note_i = idx.get("Notes")
    if note_i is not None:
        while len(row) <= note_i:
            row.append("")
        row[note_i] = (str(row[note_i]) + f" | B2B_AUTOMATION_TOUCH={touch} | GmailMessageId={message_id}").strip(" |")
    sheets.update_values(spreadsheet_id, f"Global_Prospect_CRM!A{row_number}:AA{row_number}", [row])


def run():
    logger = get_logger("srd.b2b.verified_dispatch", "Asia/Kolkata")
    if os.environ.get("B2B_ALLOW_VERIFIED_SEND", "").strip().lower() != "true":
        log_event(logger, "ERROR", "dispatch_kill_switch_off")
        raise RuntimeError("Set B2B_ALLOW_VERIFIED_SEND=true only after validating the Gmail send scope and CRM data.")
    spreadsheet_id = os.environ.get("CRM_SPREADSHEET_ID", "").strip()
    service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
    sender = os.environ.get("GMAIL_SENDER_EMAIL", "srdayurveda@gmail.com").strip()
    if not all([spreadsheet_id, service_json, client_id, client_secret, refresh_token]):
        raise RuntimeError("Missing CRM or Google OAuth secrets; dispatcher fails closed.")

    limit = min(int(os.environ.get("B2B_DAILY_SEND_LIMIT", "10")), MAX_DAILY_SEND_LIMIT)
    sheets = GoogleSheetsClient(service_json)
    crm = sheets.get_values(spreadsheet_id, "Global_Prospect_CRM!A1:AA2000")
    suppression = sheets.get_values(spreadsheet_id, "Suppression_&_DNC_List!A1:H500")
    replies = sheets.get_values(spreadsheet_id, "Inbox_Replies!A1:Z500")

    reader = GmailReadClient(client_id, client_secret, refresh_token)
    inbox = reader.list_messages(query="in:inbox newer_than:90d", max_results=500)
    inbox_senders = []
    for item in inbox:
        meta = reader.get_message_metadata(item["id"])
        from_header = meta.get("headers", {}).get("from", "")
        match = re.search(r"<([^>]+)>", from_header)
        address = (match.group(1) if match else from_header).strip().lower()
        if address and address != sender.lower() and "@" in address:
            inbox_senders.append(address)

    today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()
    plan = build_dispatch_plan(crm, suppression, replies, inbox_senders, today, limit)
    idx = _header_index(crm[0] if crm else [])
    send_creds = Credentials(
        token=None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    gmail = build("gmail", "v1", credentials=send_creds, cache_discovery=False)
    log_event(logger, "INFO", "dispatch_plan_built", eligible_before_limit=plan.get("eligible_before_limit", 0), selected=len(plan["eligible"]), held=len(plan["held"]), daily_limit=limit)

    sent = 0
    for lead in plan["eligible"]:
        row = list(crm[lead["row_number"] - 1])
        while len(row) < len(crm[0]):
            row.append("")
        run_id = os.environ.get("GITHUB_RUN_ID", "manual")
        _reserve_row(sheets, spreadsheet_id, lead["row_number"], row, idx, run_id)

        contact = _cell(row, idx, "Contact_Person")
        category = _cell(row, idx, "Business_Category")
        country = _cell(row, idx, "Country")
        products = _cell(row, idx, "Interested_Products")
        subject, body = build_message(lead["company"], contact, category, country, products, lead["touch"], sender)
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = lead["email"]
        msg["From"] = sender
        msg["Subject"] = subject
        msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=Unsubscribe>"

        try:
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            response = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
            sent_at = dt.datetime.now(ZoneInfo("Asia/Kolkata"))
            _finish_row(sheets, spreadsheet_id, lead["row_number"], row, idx, sent_at, lead["touch"], response.get("id", "unknown"))
            log_event(logger, "INFO", "verified_email_sent", lead_id=lead["lead_id"], recipient_domain=_email_domain(lead["email"]), touch=lead["touch"], gmail_message_id=response.get("id", ""))
            sent += 1
        except Exception as exc:
            # Keep DISPATCHING lock: never retry blindly after an ambiguous send outcome.
            log_event(logger, "ERROR", "dispatch_failed_or_ambiguous", lead_id=lead["lead_id"], error=str(exc))
            raise

    log_event(logger, "INFO", "dispatch_run_complete", sent=sent, held=len(plan["held"]), remaining_eligible=max(0, plan.get("eligible_before_limit", 0)-sent))


if __name__ == "__main__":
    run()
