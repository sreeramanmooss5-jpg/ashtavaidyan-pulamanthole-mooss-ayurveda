#!/usr/bin/env python3
"""
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics)
Daily Automated B2B Email Outreach, Follow-Up & CRM Sync Engine
Sender: srdayurveda@gmail.com | CRM Sheet ID: 1mHdueoG3_cridg1YxML19CvB6QqE4Y5yjnxDa27QIRc
"""

import os
import datetime
import base64
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CRM_SPREADSHEET_ID = os.environ.get("CRM_SPREADSHEET_ID", "1mHdueoG3_cridg1YxML19CvB6QqE4Y5yjnxDa27QIRc")
SENDER_EMAIL = "srdayurveda@gmail.com"
DAILY_BATCH_LIMIT = int(os.environ.get("DAILY_BATCH_LIMIT", "40"))


def get_services():
    creds = Credentials(
        None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    )
    gmail = build("gmail", "v1", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    return gmail, sheets


def check_bounces_and_replies(gmail, sheets):
    """Scans recent inbox messages for bounces or prospect replies and updates Suppression_&_DNC_List."""
    res = gmail.users().messages().list(userId="me", q="in:inbox newer_than:2d", maxResults=50).execute()
    messages = res.get("messages", [])
    bounced_emails = set()
    replied_emails = set()

    for m in messages:
        msg = gmail.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("from", "").lower()
        snippet = msg.get("snippet", "")
        if "mailer-daemon" in sender or "delivery status notification" in headers.get("subject", "").lower():
            for token in snippet.replace("<", " ").replace(">", " ").split():
                if "@" in token and "." in token:
                    bounced_emails.add(token.strip(".,;\"'").lower())
        elif "srdayurveda@gmail.com" not in sender and "google" not in sender:
            if "<" in sender and ">" in sender:
                replied_emails.add(sender.split("<")[1].split(">")[0].strip().lower())
            else:
                replied_emails.add(sender.strip().lower())
    return bounced_emails, replied_emails


def build_email_body(company, contact_person, category, products):
    greeting_name = contact_person if contact_person and contact_person != "N/A" else f"{company} Procurement Team"
    product_list = products if products and products != "N/A" else (
        "Dhanwantharam Avarti 101, Chemparathyadi Keram, Neelibhrungadi Keram, "
        "Chyavanaprasam, Dasamoolarishtam, and Agnimukhee Choornam"
    )
    return f"""Dear {greeting_name},

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics), Pulamanthole, Kerala, India.

With over 500 years of classical Kerala Ashtavaidya clinical heritage and a GMP-certified pharmaceutical manufacturing facility (GMP Cert No. 575 | License: MFG/AYUR/KL/MAL-201), we manufacture authentic classical Kerala formulations used in our inpatient hospital and partner clinics worldwide.

To support {company} ({category}), we offer direct institutional and wholesale supply of:
- Featured Formulations: {product_list}
- Full batch Certificates of Analysis (CoA), heavy-metal & microbial screening, and complete GMP export/wholesale documentation.

Would you be open to reviewing our wholesale catalogue and pricing tiers? Please reply directly to this email or contact our wholesale desk at +91 9446567506 (Hospital Hotline: +91 9778004082).

Warm regards,

Dr. Sreeraman Mooss
Director & Physician
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics)
Pulamanthole, Malappuram, Kerala 679323, India
Wholesale & Export Desk: +91 9446567506 | Hospital Hotline: +91 9778004082
Website: https://pulamantholemooss.com

If you prefer not to receive future wholesale updates, please reply with "Unsubscribe"."""


def send_gmail_message(gmail, recipient, subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = recipient
    msg["From"] = f"Srd Ayurveda <{SENDER_EMAIL}>"
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent["id"], sent.get("threadId", sent["id"])


def run_daily_outreach():
    gmail, sheets = get_services()
    bounced_set, replied_set = check_bounces_and_replies(gmail, sheets)

    dnc_res = sheets.spreadsheets().values().get(
        spreadsheetId=CRM_SPREADSHEET_ID, range="Suppression_&_DNC_List!A2:H500"
    ).execute()
    suppressed = {row[1].strip().lower() for row in dnc_res.get("values", []) if len(row) > 1 and row[1]}
    suppressed.update(bounced_set)

    crm_res = sheets.spreadsheets().values().get(
        spreadsheetId=CRM_SPREADSHEET_ID, range="Global_Prospect_CRM!A1:AA500"
    ).execute()
    rows = crm_res.get("values", [])
    if not rows:
        return

    headers = rows[0]
    idx = {h: i for i, h in enumerate(headers)}
    today_iso = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    today_date = datetime.date.today()
    next_fu = (today_date + datetime.timedelta(days=4)).isoformat()

    sent_count = 0
    for r_num, row in enumerate(rows[1:], start=2):
        if sent_count >= DAILY_BATCH_LIMIT:
            break
        while len(row) < len(headers):
            row.append("")

        email = row[idx["Email"]].strip()
        status = row[idx["Current_Status"]].strip()
        company = row[idx["Company"]].strip()
        contact = row[idx["Contact_Person"]].strip()
        cat = row[idx["Business_Category"]].strip()
        products = row[idx["Interested_Products"]].strip()
        fu_date_str = str(row[idx["Follow_Up_Date"]]).strip()[:10]

        if not email or "@" not in email or email.lower() in suppressed:
            continue

        if email.lower() in replied_set:
            row[idx["Current_Status"]] = "REPLIED"
            row[idx["Last_Reply_Received"]] = f"Replied ({today_date.isoformat()})"
            continue

        # 1. Initial Outreach for QUALIFIED / Pending Outreach leads
        if status == "QUALIFIED" or "Pending" in str(row[idx["Last_Email_Sent"]]):
            subject = f"500-year Ashtavaidya Kerala Ayurveda heritage for {company}"
            body = build_email_body(company, contact, cat, products)
            msg_id, _ = send_gmail_message(gmail, email, subject, body)
            row[idx["Last_Email_Sent"]] = today_iso
            row[idx["Current_Status"]] = "CONTACTED"
            row[idx["Follow_Up_Date"]] = next_fu
            row[idx["Notes"]] = f"{row[idx['Notes']]} | Auto-Sent {today_iso} (Msg ID: {msg_id})"
            sent_count += 1

        # 2. Scheduled Follow-Up (Day 4 / Day 9 / Day 16 / Day 25)
        elif status == "CONTACTED" and fu_date_str and fu_date_str <= today_date.isoformat():
            subject = f"Re: 500-year Ashtavaidya Kerala Ayurveda heritage for {company}"
            body = build_email_body(company, contact, cat, products)
            msg_id, _ = send_gmail_message(gmail, email, subject, body)
            row[idx["Last_Email_Sent"]] = today_iso
            row[idx["Follow_Up_Date"]] = (today_date + datetime.timedelta(days=5)).isoformat()
            row[idx["Notes"]] = f"{row[idx['Notes']]} | Auto-FollowUp {today_iso} (Msg ID: {msg_id})"
            sent_count += 1

    sheets.spreadsheets().values().update(
        spreadsheetId=CRM_SPREADSHEET_ID,
        range=f"Global_Prospect_CRM!A1:AA{len(rows)}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    print(f"Completed daily outreach run: {sent_count} real emails sent via {SENDER_EMAIL}.")


if __name__ == "__main__":
    run_daily_outreach()
