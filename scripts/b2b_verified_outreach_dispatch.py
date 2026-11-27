#!/usr/bin/env python3
"""Fail-closed B2B email dispatcher for verified SRD Ayurvedics prospects.

Default mode is a read-only plan. Live sending requires BOTH --live-send and the
B2B_ALLOW_VERIFIED_SEND=true kill switch. Inbox opt-outs, complaints and bounces
are persisted to the suppression sheet before any dispatch plan is built.
"""
import argparse
import base64
import datetime as dt
import imaplib
import os
import re
import smtplib
from email import message_from_bytes
from email.header import decode_header
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Set
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.common.gmail_client import GmailReadClient
from src.common.google_sheets import GoogleSheetsClient
from src.common.logging import get_logger, log_event
from src.inbox_monitor.engine import classify_message

EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
EMAIL_EXTRACT_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
BLOCKED_STATUS_TOKENS = ("bounce", "unsub", "suppress", "do not contact", "dnc", "complaint", "declined", "excluded", "dispatching")
QUALIFIED_STATUSES = {"qualified", "outreach eligible", "pending outreach"}
MAX_DAILY_SEND_LIMIT = 20
COOLDOWN_DAYS = 7
MAX_TOUCHES = 4
TZ = ZoneInfo("Asia/Kolkata")


def norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def header_index(headers: List[Any]) -> Dict[str, int]:
    return {str(h).strip(): i for i, h in enumerate(headers)}


def cell(row: List[Any], idx: Dict[str, int], key: str) -> str:
    pos = idx.get(key)
    return str(row[pos]).strip() if pos is not None and pos < len(row) else ""


def extract_sender_address(raw: str) -> str:
    match = re.search(r"<([^<>]+)>", raw or "")
    candidate = (match.group(1) if match else (raw or "")).strip().strip('"').lower()
    return candidate if EMAIL_RE.fullmatch(candidate) else ""


def is_human_reply_category(category: str) -> bool:
    """Return true only for inbound messages that require a human prospect handoff."""
    return category in {"reply", "procurement_request"}


def email_domain(address: str) -> str:
    return address.rsplit("@", 1)[1].lower() if "@" in address else ""


def parse_date(value: Any):
    raw = str(value or "").strip()
    for candidate in (raw[:10], raw):
        try:
            return dt.date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def suppression_keys(rows: List[List[Any]]) -> Set[str]:
    if not rows:
        return set()
    idx = header_index(rows[0])
    col = idx.get("Email_or_Domain", 1)
    return {norm(row[col]).strip(".") for row in rows[1:] if col < len(row) and norm(row[col])}


def _touch_count(notes: str, last_sent: str) -> int:
    found = re.findall(r"B2B_AUTOMATION_TOUCH=(\d+)", notes or "")
    return int(found[-1]) if found else (1 if last_sent else 0)


def build_dispatch_plan(
    crm_rows: List[List[Any]],
    suppression_rows: List[List[Any]],
    reply_rows: List[List[Any]],
    inbox_senders: Iterable[str],
    today: dt.date,
    daily_limit: int = 10,
) -> Dict[str, Any]:
    if not crm_rows:
        return {"eligible": [], "held": [{"reason": "CRM sheet is empty"}], "eligible_before_limit": 0}
    idx = header_index(crm_rows[0])
    required = {"Lead_ID", "Company", "Email", "Email_Verification_Status", "Current_Status"}
    missing = sorted(required - set(idx))
    if missing:
        return {"eligible": [], "held": [{"reason": "Missing required CRM columns", "columns": missing}], "eligible_before_limit": 0}

    suppressed = suppression_keys(suppression_rows)
    replied = {norm(x) for x in inbox_senders if norm(x)}
    for row in reply_rows[1:] if len(reply_rows) > 1 else []:
        for value in row:
            replied.update(x.lower() for x in EMAIL_EXTRACT_RE.findall(str(value)))
    configured_limit = max(0, min(int(daily_limit), MAX_DAILY_SEND_LIMIT))
    sent_today = sum(1 for row in crm_rows[1:] if parse_date(cell(row, idx, "Last_Email_Sent")) == today)
    limit = max(0, configured_limit - sent_today)
    eligible, held = [], []

    for row_number, row in enumerate(crm_rows[1:], start=2):
        lead_id, company = cell(row, idx, "Lead_ID"), cell(row, idx, "Company")
        address = cell(row, idx, "Email").lower()
        verification = norm(cell(row, idx, "Email_Verification_Status"))
        status = norm(cell(row, idx, "Current_Status"))
        last_sent = cell(row, idx, "Last_Email_Sent")
        follow_up = cell(row, idx, "Follow_Up_Date")
        notes = cell(row, idx, "Notes")
        reason, touch = "", 0

        if not lead_id or not company:
            reason = "Missing lead ID or company"
        elif not EMAIL_RE.fullmatch(address):
            reason = "Invalid email address"
        elif verification != "verified":
            reason = "Email verification status must be exactly Verified"
        elif address in suppressed or email_domain(address) in suppressed:
            reason = "Email or domain is suppressed"
        elif any(token in status for token in BLOCKED_STATUS_TOKENS):
            reason = "CRM status is blocked"
        elif address in replied:
            reason = "Reply received; route to human handling"
        elif status in QUALIFIED_STATUSES and not last_sent:
            touch = 1
        elif status == "contacted":
            due = parse_date(follow_up)
            sent_date = parse_date(last_sent)
            if not due or due > today:
                reason = "Follow-up is not due"
            elif not sent_date or (today - sent_date).days < COOLDOWN_DAYS:
                reason = "Seven-day cooldown has not elapsed"
            else:
                touch = _touch_count(notes, last_sent) + 1
                if touch > MAX_TOUCHES:
                    reason = "Maximum outreach touches reached"
        else:
            reason = "Lead is not in an outreach-eligible status"

        if reason:
            held.append({"row_number": row_number, "lead_id": lead_id, "reason": reason})
        else:
            campaign_name, routed_sender = resolve_campaign_sender(cell(row, idx, "Business_Category"), cell(row, idx, "Interested_Products"), notes)
            eligible.append({"row_number": row_number, "lead_id": lead_id, "company": company, "email": address, "touch": touch, "campaign": campaign_name, "sender": routed_sender})

    return {
        "eligible": eligible[:limit],
        "held": held,
        "eligible_before_limit": len(eligible),
        "daily_limit": limit,
        "configured_daily_limit": configured_limit,
        "sent_today_already": sent_today,
    }


def build_message(company: str, contact: str, category: str, country: str, products: str, touch: int, sender: str):
    greeting = contact if norm(contact) not in {"", "n/a", "na", "unknown"} else "Procurement Team"
    subject = "Wholesale and institutional supply enquiry | Pulamanthole Mooss" if touch == 1 else "Follow-up: Ayurveda wholesale and institutional supply"
    body = f"""Dear {greeting},

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals, Kerala, India.

We are contacting {company} ({category or 'buyer organisation'}, {country or 'your market'}) to understand whether our classical Kerala Ayurveda formulations may be relevant to your wholesale or institutional procurement requirements.

Areas of interest noted: {products or 'classical Ayurveda formulations'}. We can share the current catalogue, applicable trade terms and product-specific regulatory documentation for your review. Availability, pricing and export eligibility will be confirmed against your requirements.

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


def persist_inbox_suppressions(sheets, spreadsheet_id: str, suppression_rows: List[List[Any]], classified: List[Dict[str, str]], observed_at: str):
    """Append unsubscribe/complaint/hard-bounce records once; never silently discard opt-outs."""
    if not suppression_rows:
        raise RuntimeError("Suppression sheet is empty; refusing live dispatch.")
    headers = suppression_rows[0]
    idx = header_index(headers)
    target_col = idx.get("Email_or_Domain", 1)
    existing = suppression_keys(suppression_rows)
    additions = []
    for item in classified:
        if item.get("category") not in {"unsubscribe", "complaint", "hard_bounce"}:
            continue
        address = norm(item.get("target_email"))
        if not EMAIL_RE.fullmatch(address) or address in existing:
            continue
        row = [""] * len(headers)
        values = {
            "Suppression_ID": f"AUTO-{observed_at[:10]}-{len(additions)+1}",
            "Email_or_Domain": address,
            "Reason": item.get("category", "").upper(),
            "Source": "Gmail inbox monitor",
            "Date_Added": observed_at,
            "Status": "ACTIVE",
        }
        for key, value in values.items():
            if key in idx:
                row[idx[key]] = value
        if target_col < len(row):
            row[target_col] = address
        additions.append(row)
        existing.add(address)
    if additions:
        sheets.append_values(spreadsheet_id, "Suppression_&_DNC_List!A:H", additions)
    return len(additions)


def _reserve_row(sheets, spreadsheet_id: str, row_number: int, row: List[Any], idx: Dict[str, int], run_id: str):
    row[idx["Current_Status"]] = "DISPATCHING"
    notes_i = idx.get("Notes")
    if notes_i is not None:
        while len(row) <= notes_i:
            row.append("")
        row[notes_i] = (str(row[notes_i]) + f" | B2B_DISPATCH_LOCK={run_id}").strip(" |")
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



def _decode_mime_header(value: str) -> str:
    parts = []
    for chunk, enc in decode_header(value or ""):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _fetch_inbox_imap(email_addr: str, app_password: str, max_messages: int = 200) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mail:
        mail.login(email_addr, app_password)
        mail.select("INBOX", readonly=True)
        status, data = mail.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return items
        msg_nums = data[0].split()[-max_messages:]
        for num in reversed(msg_nums):
            st, msg_data = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE AUTO-SUBMITTED X-FAILED-RECIPIENTS)] BODY.PEEK[TEXT]<0.512>)")
            if st != "OK" or not msg_data:
                continue
            raw_bytes = b"".join(part[1] for part in msg_data if isinstance(part, tuple) and len(part) > 1)
            parsed = message_from_bytes(raw_bytes)
            from_hdr = _decode_mime_header(parsed.get("From", ""))
            subj_hdr = _decode_mime_header(parsed.get("Subject", ""))
            snippet = ""
            try:
                snippet = parsed.get_payload(decode=True).decode("utf-8", errors="replace") if not parsed.is_multipart() else ""
            except Exception:
                snippet = ""
            items.append({"from": from_hdr, "subject": subj_hdr, "snippet": snippet[:400]})
    return items


def _send_smtp(sender_email: str, app_password: str, msg: EmailMessage) -> str:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(msg)
    return msg.get("Message-ID") or f"smtp-{int(dt.datetime.now(TZ).timestamp())}"


def run(live_send: bool = False):
    logger = get_logger("srd.b2b.verified_dispatch", "Asia/Kolkata")
    if live_send and os.environ.get("B2B_ALLOW_VERIFIED_SEND", "").strip().lower() != "true":
        raise RuntimeError("Live dispatch blocked: B2B_ALLOW_VERIFIED_SEND is not true.")
    spreadsheet_id = os.environ.get("CRM_SPREADSHEET_ID", "").strip()
    service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    service_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
    send_refresh_token = os.environ.get("GMAIL_SEND_REFRESH_TOKEN", "").strip()
    app_pw_med = os.environ.get("GMAIL_APP_PASSWORD_MEDICINE", "").strip()
    app_pw_gaja = os.environ.get("GMAIL_APP_PASSWORD_GAJA", "").strip()
    sender = os.environ.get("GMAIL_SENDER_EMAIL", CHYAVANAPRASAM_B2B_SENDER).strip()
    has_oauth_read = all([client_id, client_secret, refresh_token])
    has_imap = bool(app_pw_med or app_pw_gaja)
    if not spreadsheet_id or not (service_json or service_b64) or not (has_oauth_read or has_imap):
        raise RuntimeError("Missing CRM or Gmail (App Password or OAuth) configuration; dispatcher fails closed.")
    if live_send and not (send_refresh_token or has_imap):
        raise RuntimeError("Live dispatch requires GMAIL_APP_PASSWORD_* or GMAIL_SEND_REFRESH_TOKEN.")

    daily_limit = max(0, min(int(os.environ.get("B2B_DAILY_SEND_LIMIT", "10")), MAX_DAILY_SEND_LIMIT))
    sheets = GoogleSheetsClient(service_json)
    crm = sheets.get_values(spreadsheet_id, "Global_Prospect_CRM!A1:AA2000")
    suppression = sheets.get_values(spreadsheet_id, "Suppression_&_DNC_List!A1:H500")
    replies = sheets.get_values(spreadsheet_id, "Inbox_Replies!A1:Z500")

    classified, inbox_senders = [], []
    if has_imap:
        for acct, pw in [(CHYAVANAPRASAM_B2B_SENDER, app_pw_med), (ELEPHANT_CARE_SENDER, app_pw_gaja)]:
            if not pw:
                continue
            for m in _fetch_inbox_imap(acct, pw):
                sender_address = extract_sender_address(m["from"])
                item = classify_message(m["from"], m["subject"], m["snippet"])
                if sender_address and sender_address not in {CHYAVANAPRASAM_B2B_SENDER, ELEPHANT_CARE_SENDER} and is_human_reply_category(item.get("category", "")):
                    inbox_senders.append(sender_address)
                if item.get("category") in {"unsubscribe", "complaint", "hard_bounce"}:
                    target = extract_sender_address(item.get("target_email", "")) or (item.get("target_email", "").lower() if EMAIL_RE.fullmatch(item.get("target_email", "").lower()) else "")
                    item["target_email"] = target
                classified.append(item)
    else:
        reader = GmailReadClient(client_id, client_secret, refresh_token)
        messages = reader.list_messages(query="in:inbox newer_than:90d", max_results=500)
        for message in messages:
            meta = reader.get_message_metadata(message["id"])
            headers = meta.get("headers", {})
            sender_address = extract_sender_address(headers.get("from", ""))
            item = classify_message(headers.get("from", ""), headers.get("subject", ""), meta.get("snippet", ""))
            if sender_address and sender_address != sender.lower() and is_human_reply_category(item.get("category", "")):
                inbox_senders.append(sender_address)
            if item.get("category") in {"unsubscribe", "complaint", "hard_bounce"}:
                target = extract_sender_address(item.get("target_email", "")) or (item.get("target_email", "").lower() if EMAIL_RE.fullmatch(item.get("target_email", "").lower()) else "")
                item["target_email"] = target
            classified.append(item)

    observed_at = dt.datetime.now(TZ).isoformat()
    added = 0
    if live_send:
        added = persist_inbox_suppressions(sheets, spreadsheet_id, suppression, classified, observed_at)
        suppression = sheets.get_values(spreadsheet_id, "Suppression_&_DNC_List!A1:H500")
    plan = build_dispatch_plan(crm, suppression, replies, inbox_senders, dt.datetime.now(TZ).date(), daily_limit)
    log_event(logger, "INFO", "dispatch_plan_built", live_send=live_send, eligible_before_limit=plan.get("eligible_before_limit", 0), selected=len(plan["eligible"]), held=len(plan["held"]), daily_limit=daily_limit, new_suppressions=added)

    if not live_send:
        log_event(logger, "INFO", "dry_run_complete", eligible_lead_ids=[x["lead_id"] for x in plan["eligible"]], held_count=len(plan["held"]), outbound_sent=0)
        return

    smtp_map = {}
    if app_pw_med:
        smtp_map[norm(CHYAVANAPRASAM_B2B_SENDER)] = app_pw_med
    if app_pw_gaja:
        smtp_map[norm(ELEPHANT_CARE_SENDER)] = app_pw_gaja

    gmail = None
    if not smtp_map:
        send_creds = Credentials(
            token=None, refresh_token=send_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id, client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        gmail = build("gmail", "v1", credentials=send_creds, cache_discovery=False)
        profile = gmail.users().getProfile(userId="me").execute()
        if norm(profile.get("emailAddress")) != norm(sender):
            raise RuntimeError("Authenticated Gmail sender does not match GMAIL_SENDER_EMAIL; refusing to send.")

    idx = header_index(crm[0] if crm else [])
    sent = 0
    for lead in plan["eligible"]:
        lead_sender = lead.get("sender") or sender
        if smtp_map:
            if norm(lead_sender) not in smtp_map:
                continue
        elif norm(lead_sender) != norm(sender):
            continue
        row = list(crm[lead["row_number"] - 1])
        while len(row) < len(crm[0]):
            row.append("")
        _reserve_row(sheets, spreadsheet_id, lead["row_number"], row, idx, os.environ.get("GITHUB_RUN_ID", "manual"))
        _, _, subject, body = build_campaign_message(
            lead["company"], cell(row, idx, "Contact_Person"), cell(row, idx, "Business_Category"),
            cell(row, idx, "Country"), cell(row, idx, "Interested_Products"), lead["touch"], lead["lead_id"], cell(row, idx, "Notes"),
        )
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = lead["email"]
        msg["From"] = lead_sender
        msg["Subject"] = subject
        msg["List-Unsubscribe"] = f"<mailto:{lead_sender}?subject=Unsubscribe>"
        try:
            if smtp_map:
                msg_id = _send_smtp(lead_sender, smtp_map[norm(lead_sender)], msg)
            else:
                raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
                response = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
                msg_id = response.get("id", "unknown")
            sent_at = dt.datetime.now(TZ)
            _finish_row(sheets, spreadsheet_id, lead["row_number"], row, idx, sent_at, lead["touch"], msg_id)
            log_event(logger, "INFO", "verified_email_sent", lead_id=lead["lead_id"], sender=lead_sender, recipient_domain=email_domain(lead["email"]), touch=lead["touch"], gmail_message_id=msg_id)
            sent += 1
        except Exception as exc:
            log_event(logger, "ERROR", "dispatch_failed_or_ambiguous", lead_id=lead["lead_id"], error=str(exc))
            raise
    log_event(logger, "INFO", "dispatch_run_complete", sent=sent, held=len(plan["held"]), outbound_sent=sent)




ELEPHANT_CARE_SENDER = "pulamantholemoossayurveda@gmail.com"
CHYAVANAPRASAM_B2B_SENDER = "pulamantholemooss@gmail.com"


def resolve_campaign_sender(category: str, products: str, notes: str) -> tuple[str, str]:
    """Route Elephant Care / Gaja Chikilsa prospects to pulamantholemoossayurveda@gmail.com
    and Chyavanaprasam / Medicine B2B prospects to pulamantholemooss@gmail.com."""
    blob = f"{norm(category)} {norm(products)} {norm(notes)}"
    if any(k in blob for k in ("elephant", "gaja chikilsa", "devaswom", "zoological", "wildlife")):
        return "ELEPHANT_CARE_B2B", ELEPHANT_CARE_SENDER
    return "CHYAVANAPRASAM_B2B", CHYAVANAPRASAM_B2B_SENDER


def build_campaign_message(
    company: str,
    contact: str,
    category: str,
    country: str,
    products: str,
    touch: int,
    lead_id: str = "",
    notes: str = "",
) -> tuple[str, str, str, str]:
    campaign, sender = resolve_campaign_sender(category, products, notes)
    greeting = contact if norm(contact) not in {"", "n/a", "na", "unknown", "administrator / devaswom office"} else "Team"
    tag = f" ({lead_id})" if lead_id else ""
    if campaign == "ELEPHANT_CARE_B2B":
        subject = (
            f"Institutional Ayurveda & Nutritional Rasayana Discussion | {company} & Pulamanthole Mooss{tag}"
            if touch == 1
            else f"Follow-up: Institutional Ayurveda & Elephant Care Discussion | Pulamanthole Mooss{tag}"
        )
        body = f"""Namaskaram,

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals, Pulamanthole, Malappuram, Kerala (GMP Cert No. 575 | Mfg. Lic. MFG/AYUR/KL/MAL-201).

We are reaching out to {company} ({category or 'institution'}, {country or 'India'}) in recognition of your stewardship and care of captive elephants.

Rooted in over 500 years of classical Kerala Ashtavaidya heritage, Ashtavaidyan Pulamanthole Mooss manufactures classical Ayurvedic formulations and institutional rasayana preparations—including our institutional Chyavanaprasam formulation—under strict GMP quality protocols for traditional seasonal rejuvenation and nutritional support.

We would welcome a brief institutional discussion with your administrative and veterinary leadership to understand your requirements and share further institutional details.

Warm regards,
Institutional & Gaja Chikilsa Desk
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals
Pulamanthole P.O., Malappuram, Kerala – 679323
Email: {ELEPHANT_CARE_SENDER}
Phone / Enquiries: +91 94465 67506 | +91 97780 04082
Websites: https://pulamantholemoosshospital.com | https://pulamantholemooss.com

To stop future institutional emails, reply with "Unsubscribe" or email {ELEPHANT_CARE_SENDER} with the subject "Unsubscribe".
"""
        return campaign, sender, subject, body

    subject = (
        f"Wholesale & Institutional Supply: Pulamanthole Mooss Chyavanaprasam & Classical Formulations{tag}"
        if touch == 1
        else f"Follow-up: Pulamanthole Mooss Chyavanaprasam & Classical Catalogue{tag}"
    )
    body = f"""Dear {greeting},

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals, Pulamanthole, Malappuram, Kerala.

Rooted in over 500 years of classical Kerala Ashtavaidya lineage, our GMP-certified pharmaceutical unit (GMP Cert No. 575 | Mfg. Lic. MFG/AYUR/KL/MAL-201) manufactures authentic classical Ayurvedic formulations—led by our classical Chyavanaprasam (Amalaki-based Rasayana Avaleha), alongside classical Kerams, Choornams, Arishtams, and Kashayams.

We are contacting {company} ({category or 'Ayurveda trade & healthcare organisation'}, {country or 'your market'}) to explore wholesale distribution or institutional supply synergies. Areas noted: {products or 'Chyavanaprasam & classical Ayurvedic formulations'}.

We would be pleased to share our verified product catalogue and discuss your procurement requirements. Commercial terms, pricing tiers, and destination regulatory documentation will be confirmed directly against your requirements.

Warm regards,
B2B & Institutional Trade Desk
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals
Pulamanthole P.O., Malappuram, Kerala – 679323
Email: {CHYAVANAPRASAM_B2B_SENDER}
Phone / Trade Enquiries: +91 94465 67506
Websites: https://pulamantholemooss.com | https://pulamantholemoosshospital.com

To stop future business emails, reply with "Unsubscribe" or email {CHYAVANAPRASAM_B2B_SENDER} with the subject "Unsubscribe".
"""
    return campaign, sender, subject, body


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-send", action="store_true", help="Enable outbound sending; requires the repository kill switch.")
    args = parser.parse_args()
    run(live_send=args.live_send)
