#!/usr/bin/env python3
"""
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics)
Complete Zero-Touch Daily B2B Email Outreach, Warm Reply Auto-Responder, 6-Touch Follow-Up & CRM Sync Engine
Sender: srdayurveda@gmail.com | CRM Sheet ID: 1mHdueoG3_cridg1YxML19CvB6QqE4Y5yjnxDa27QIRc
"""

import os
import datetime
import base64
import smtplib
import imaplib
import email as py_email
from email.message import EmailMessage

CRM_SPREADSHEET_ID = os.environ.get("CRM_SPREADSHEET_ID", "1mHdueoG3_cridg1YxML19CvB6QqE4Y5yjnxDa27QIRc")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "srdayurveda@gmail.com")
DAILY_BATCH_LIMIT = int(os.environ.get("DAILY_BATCH_LIMIT", "40"))

CATALOGUE_SUMMARY = """
CORE CLASSICAL FORMULARY & INDICATIVE MRP / MOQ SCHEDULE (SRD Ayurvedics | GMP Cert No. 575 | Lic: MFG/AYUR/KL/MAL-201 | e-Aushadhi: KlMa00405):
- PM-MED-01 | Agnimukhee Choornam (50g / Bulk 500g) — MRP ₹105 | MOQ: 100 units
- PM-MED-02 | Chemparathyadi Keram (200ml Retail / 1L & 5L Bulk) — MRP ₹260 | MOQ: 50 units
- PM-MED-03 | Chyavanaprasam (200g / 500g Classical Rasayana) — MRP ₹230 | MOQ: 100 units
- PM-MED-04 | Dasamoolarishtam (450ml) — MRP ₹150 | MOQ: 50 units
- PM-MED-05 | Dhathri Gulika (100 Tablets) — MRP ₹565 | MOQ: 100 units
- PM-MED-06 | Dhanwantharam Avarti 101 (50ml High-Potency 101x Oil) — MRP ₹480 | MOQ: 50 units
- PM-MED-07 | Neelibhrungadi Keram (200ml Retail / 1L & 5L Bulk) — MRP ₹320 | MOQ: 50 units
- PM-MED-08 | Soma Gritham (150g Medicated Ghee) — MRP ₹390 | MOQ: 50 units
- PM-MED-09 | Brahmee Kalyanaka Gritham (150g Medicated Ghee) — MRP ₹420 | MOQ: 50 units
- PM-MED-10 | Lathakaraskaradi Keram (200ml / 1L Bulk) — MRP ₹280 | MOQ: 50 units
- PM-MED-11 | Thambooladi Kerathilam (200ml / 1L Bulk) — MRP ₹230 | MOQ: 50 units
- PM-MED-12 | Musthavilamgadhi Kashayam (450ml) — MRP ₹180 | MOQ: 50 units
- PM-MED-13 | Sindhuvaram Kerathailam (200ml) — MRP ₹230 | MOQ: 50 units
- PM-MED-14 | Chandrodhyam Choornam (50g) — MRP ₹160 | MOQ: 100 units
- PM-MED-15 | Pulamanthole Mooss Facial Powder (20g) — MRP ₹180 | MOQ: 100 units
- PM-MED-16 | SRD Tooth Powder (50g) — MRP ₹90 | MOQ: 100 units
- PM-MED-17 | Nisamalakadi Choornam (50g) — MRP ₹80 | MOQ: 100 units
- PM-MED-18 | Saptachchadhabhayam Kashayam (450ml) — MRP ₹175 | MOQ: 50 units
*(Plus 300+ classical Panchakarma Thailams, Kashayams, Arishtams, and Choornams in retail & 1L/5L institutional formats.)*
"""


def get_google_services():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not os.environ.get("GMAIL_REFRESH_TOKEN"):
        return None, None

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


def send_email_zero_touch(gmail, recipient, subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = recipient
    msg["From"] = f"Srd Ayurveda <{SENDER_EMAIL}>"
    msg["Subject"] = subject

    if gmail is not None:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"], sent.get("threadId", sent["id"])
    elif os.environ.get("GMAIL_APP_PASSWORD"):
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SENDER_EMAIL, os.environ["GMAIL_APP_PASSWORD"])
            smtp.send_message(msg)
        return f"smtp-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}", "smtp-thread"
    else:
        raise RuntimeError("Neither GMAIL_REFRESH_TOKEN nor GMAIL_APP_PASSWORD is set in GitHub Secrets.")


def build_touch_body(touch_num, company, contact_person, category, country, products):
    greeting_name = contact_person if contact_person and contact_person != "N/A" else f"{company} Procurement Team"
    product_list = products if products and products != "N/A" else (
        "Dhanwantharam Avarti 101, Chemparathyadi Keram, Neelibhrungadi Keram, "
        "Chyavanaprasam, Dasamoolarishtam, and Agnimukhee Choornam"
    )
    if touch_num == 1:
        intro = f"We are writing to introduce our 500+ year classical Kerala Ashtavaidya clinical heritage and GMP-certified pharmaceutical manufacturing facility (SRD Ayurvedics | GMP Cert No. 575 | License: MFG/AYUR/KL/MAL-201)."
        cta = "Would you be open to reviewing our 2026–2027 wholesale catalogue and trade pricing schedule?"
    elif touch_num == 2:
        intro = f"Following up on my previous note regarding direct institutional and wholesale supply of our classical Kerala Ashtavaidya formulations for {company}."
        cta = "Below is our core 18-SKU formulary and MOQ schedule for your review. Shall I share our regional distributor/institutional net margin tiers?"
    elif touch_num == 3:
        intro = f"I wanted to share our laboratory quality & regulatory compliance highlights for {company} ({country}). Every batch is screened for heavy metals, microbial parameters, and accompanied by full GMP Certificates of Analysis (CoA)."
        cta = "Would next Tuesday suit for a brief 10-minute introductory call, or would you prefer to review our proforma price list by email?"
    else:
        intro = f"We are finalizing our regional stockist and institutional clinic allocations for {country} this quarter and would be honoured to include {company}."
        cta = "Please confirm your shipping address if you would like us to dispatch a complimentary clinical evaluation sample kit."

    extra_cat = f"\n{CATALOGUE_SUMMARY}\n" if touch_num >= 2 else ""
    return f"""Dear {greeting_name},

Greetings from Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics), Pulamanthole, Kerala, India.

{intro}

To support {company} ({category}), we offer direct supply of:
- Featured Formulations: {product_list}
- Full batch Certificates of Analysis (CoA), heavy-metal & microbial screening, and complete GMP export/wholesale documentation.{extra_cat}
{cta} Please reply directly to this email or contact our wholesale desk at +91 9446567506 (Hospital Hotline: +91 9778004082).

Warm regards,

Dr. Sreeraman Mooss
Director & Physician
Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital & Pharmaceuticals (SRD Ayurvedics)
Pulamanthole, Malappuram, Kerala 679323, India
Wholesale & Export Desk: +91 9446567506 | Hospital Hotline: +91 9778004082
Website: https://pulamantholemooss.com

If you prefer not to receive future wholesale updates, please reply with "Unsubscribe"."""


def check_bounces_and_auto_reply(gmail):
    if gmail is None:
        return set(), {}, set()
    res = gmail.users().messages().list(userId="me", q="in:inbox newer_than:2d", maxResults=50).execute()
    messages = res.get("messages", [])
    bounced_emails = set()
    replied_map = {}
    unsubscribed_emails = set()

    for m in messages:
        msg = gmail.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("from", "").lower()
        subj = headers.get("subject", "")
        snippet = msg.get("snippet", "")
        if "mailer-daemon" in sender or "delivery status notification" in subj.lower():
            for token in snippet.replace("<", " ").replace(">", " ").split():
                if "@" in token and "." in token:
                    bounced_emails.add(token.strip(".,;\"'").lower())
        elif "srdayurveda@gmail.com" not in sender and "google" not in sender and "noreply" not in sender and "no-reply" not in sender:
            addr = sender.split("<")[1].split(">")[0].strip().lower() if "<" in sender and ">" in sender else sender.strip().lower()
            if "unsubscribe" in snippet.lower() or "remove" in snippet.lower():
                unsubscribed_emails.add(addr)
            else:
                replied_map[addr] = (m["id"], subj, snippet)
    return bounced_emails, replied_map, unsubscribed_emails


def run_daily_outreach():
    gmail, sheets = get_google_services()
    if gmail is None or sheets is None:
        print("Notice: Configure GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in GitHub Repository Secrets for cloud execution.")
        return

    bounced_set, replied_map, unsub_set = check_bounces_and_auto_reply(gmail)

    dnc_res = sheets.spreadsheets().values().get(
        spreadsheetId=CRM_SPREADSHEET_ID, range="Suppression_&_DNC_List!A2:H500"
    ).execute()
    suppressed = {row[1].strip().lower() for row in dnc_res.get("values", []) if len(row) > 1 and row[1]}
    suppressed.update(bounced_set)
    suppressed.update(unsub_set)

    crm_res = sheets.spreadsheets().values().get(
        spreadsheetId=CRM_SPREADSHEET_ID, range="Global_Prospect_CRM!A1:AA2000"
    ).execute()
    rows = crm_res.get("values", [])
    if not rows:
        return

    headers = rows[0]
    idx = {h: i for i, h in enumerate(headers)}
    today_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_date = datetime.date.today()

    sent_count = 0
    for row in rows[1:]:
        while len(row) < len(headers):
            row.append("")
        email_addr = row[idx["Email"]].strip()
        if not email_addr or "@" not in email_addr:
            continue
        em_low = email_addr.lower()
        company = row[idx["Company"]].strip()
        contact = row[idx["Contact_Person"]].strip()
        cat = row[idx["Business_Category"]].strip()
        country = row[idx["Country"]].strip()
        products = row[idx["Interested_Products"]].strip()
        status = row[idx["Current_Status"]].strip()
        fu_date_str = str(row[idx["Follow_Up_Date"]]).strip()[:10]
        notes_str = str(row[idx["Notes"]])

        if em_low in bounced_set and status != "BOUNCED":
            row[idx["Current_Status"]] = "BOUNCED"
            row[idx["Follow_Up_Date"]] = "SUPPRESSED (Bounce)"
            continue
        if em_low in unsub_set and status != "UNSUBSCRIBED":
            row[idx["Current_Status"]] = "UNSUBSCRIBED"
            row[idx["Follow_Up_Date"]] = "SUPPRESSED (Unsubscribed)"
            continue
        if em_low in suppressed:
            continue

        # Automatic Warm Reply Catalogue Responder
        if em_low in replied_map and status not in ("REPLIED", "QUOTATION / CATALOGUE SENT"):
            in_mid, in_subj, in_snip = replied_map[em_low]
            row[idx["Current_Status"]] = "QUOTATION / CATALOGUE SENT"
            reply_subj = f"Re: {in_subj}" if not in_subj.lower().startswith("re:") else in_subj
            reply_body = build_touch_body(2, company, contact, cat, country, products)
            out_mid, _ = send_email_zero_touch(gmail, email_addr, reply_subj, reply_body)
            row[idx["Last_Email_Sent"]] = today_iso
            row[idx["Last_Reply_Received"]] = f"Auto-Catalogue Sent (Msg ID: {out_mid}) in reply to {in_mid}"
            row[idx["Follow_Up_Date"]] = (today_date + datetime.timedelta(days=5)).isoformat()
            sent_count += 1
            continue

        if sent_count >= DAILY_BATCH_LIMIT:
            continue

        # 1. Initial Outreach for QUALIFIED / Pending Outreach rows
        if status == "QUALIFIED" or "Pending" in str(row[idx["Last_Email_Sent"]]):
            subj = f"500-year Ashtavaidya Kerala Ayurveda heritage for {company}"
            body = build_touch_body(1, company, contact, cat, country, products)
            mid, _ = send_email_zero_touch(gmail, email_addr, subj, body)
            row[idx["Last_Email_Sent"]] = today_iso
            row[idx["Current_Status"]] = "CONTACTED"
            row[idx["Follow_Up_Date"]] = (today_date + datetime.timedelta(days=4)).isoformat()
            row[idx["Notes"]] = f"{notes_str} | Touch-1 Auto-Sent {today_iso} (Msg ID: {mid})"
            sent_count += 1

        # 2. Multi-Touch Follow-Up Cadence (Day 4, Day 9, Day 16, Day 25)
        elif status == "CONTACTED" and fu_date_str and len(fu_date_str) == 10 and fu_date_str <= today_date.isoformat():
            touch_num = 2 if "Touch-2" not in notes_str else (3 if "Touch-3" not in notes_str else 4)
            subj = f"Re: 500-year Ashtavaidya Kerala Ayurveda heritage for {company}"
            body = build_touch_body(touch_num, company, contact, cat, country, products)
            mid, _ = send_email_zero_touch(gmail, email_addr, subj, body)
            row[idx["Last_Email_Sent"]] = today_iso
            next_gap = 5 if touch_num == 2 else (7 if touch_num == 3 else 9)
            row[idx["Follow_Up_Date"]] = (today_date + datetime.timedelta(days=next_gap)).isoformat()
            row[idx["Notes"]] = f"{notes_str} | Touch-{touch_num} Auto-Sent {today_iso} (Msg ID: {mid})"
            sent_count += 1

    sheets.spreadsheets().values().update(
        spreadsheetId=CRM_SPREADSHEET_ID,
        range=f"Global_Prospect_CRM!A1:AA{len(rows)}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    print(f"Completed zero-touch daily outreach run: {sent_count} real emails sent via {SENDER_EMAIL}.")


if __name__ == "__main__":
    run_daily_outreach()
