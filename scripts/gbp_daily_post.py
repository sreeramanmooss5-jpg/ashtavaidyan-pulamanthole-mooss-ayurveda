import csv
import io
import os
import re
from datetime import datetime, timezone, timedelta
import requests

SHEET_ID = os.getenv("SHEET_ID", "1xxQceSoW2QQkcjfKdAFGH9eY6hbGnXyYNs8X1bqo2e4")
SHEET_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
    "?tqx=out:csv&sheet=Master_Consolidated_Calendar"
)
GBP_CLIENT_ID = os.environ["GBP_CLIENT_ID"]
GBP_CLIENT_SECRET = os.environ["GBP_CLIENT_SECRET"]
GBP_REFRESH_TOKEN = os.environ["GBP_REFRESH_TOKEN"]
IST = timezone(timedelta(hours=5, minutes=30))


def get_access_token() -> str:
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GBP_CLIENT_ID,
            "client_secret": GBP_CLIENT_SECRET,
            "refresh_token": GBP_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_todays_rows(today_str: str, today_alt: str) -> list[dict]:
    resp = requests.get(SHEET_CSV_URL, timeout=30)
    resp.raise_for_status()
    rows = list(csv.reader(io.StringIO(resp.text)))
    header_idx = next(
        (i for i, r in enumerate(rows) if r and r[0].strip().lower() == "date"),
        None,
    )
    if header_idx is None:
        return []
    headers = [h.strip() for h in rows[header_idx]]
    matched = []
    for r in rows[header_idx + 1 :]:
        if not r or len(r) < 3:
            continue
        rec = dict(zip(headers, r))
        date_val = rec.get("Date", "")
        status_val = rec.get("Status", "").upper()
        if "SKIPPED_DUPLICATE" in status_val or "MISSING" in status_val:
            continue
        if today_str in date_val or today_alt in date_val:
            matched.append(rec)
    return matched


def extract_drive_image_url(row: dict) -> str | None:
    for key in ("Instagram", "Caption", "Description"):
        m = re.search(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)", row.get(key, ""))
        if m:
            return f"https://lh3.googleusercontent.com/d/{m.group(1)}"
    return None


def list_gbp_locations(headers: dict) -> list[dict]:
    acc_resp = requests.get(
        "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
        headers=headers,
        timeout=30,
    )
    acc_resp.raise_for_status()
    locations = []
    for acc in acc_resp.json().get("accounts", []):
        acc_name = acc["name"]
        loc_resp = requests.get(
            f"https://mybusinessbusinessinformation.googleapis.com/v1/{acc_name}/locations",
            headers=headers,
            params={"readMask": "name,title,storeCode"},
            timeout=30,
        )
        if not loc_resp.ok:
            continue
        for loc in loc_resp.json().get("locations", []):
            title = (loc.get("title") or "").lower()
            if any(w in title for w in ("temple", "dhanwanthari", "rudhra")):
                continue
            loc["full_name"] = f"{acc_name}/{loc['name']}"
            locations.append(loc)
    return locations


def get_existing_post_summaries(full_loc_name: str, headers: dict) -> list[str]:
    resp = requests.get(
        f"https://mybusiness.googleapis.com/v4/{full_loc_name}/localPosts",
        headers=headers,
        params={"pageSize": 15},
        timeout=30,
    )
    if not resp.ok:
        return []
    return [(p.get("summary") or "")[:80] for p in resp.json().get("localPosts", [])]


def publish_local_post(full_loc_name: str, summary: str, cta_type: str, cta_url: str, image_url: str | None, headers: dict):
    payload = {
        "languageCode": "en",
        "topicType": "STANDARD",
        "summary": summary[:1500],
        "callToAction": {"actionType": cta_type, "url": cta_url},
    }
    if image_url:
        payload["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": image_url}]
    resp = requests.post(
        f"https://mybusiness.googleapis.com/v4/{full_loc_name}/localPosts",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    now_ist = datetime.now(IST)
    today_iso = now_ist.strftime("%Y-%m-%d")
    today_human = now_ist.strftime("%b %-d, %Y")
    rows = fetch_todays_rows(today_iso, today_human)
    if not rows:
        print(f"No GBP posts scheduled for {today_iso} / {today_human}.")
        return
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    locations = list_gbp_locations(headers)
    print(f"Found {len(locations)} non-temple GBP locations.")
    for row in rows:
        category = (row.get("Category") or "").lower()
        is_pharmacy = "pharmacy" in category
        cta_type = "ORDER" if is_pharmacy else "BOOK"
        cta_url = "https://www.pulamantholemooss.com" if is_pharmacy else "https://www.pulamantholemoosshospital.com"
        phone = "9446567506" if is_pharmacy else "+91 97780 04082"
        accred = (
            "GMP-Certified Ayurvedic Medicine Manufacturing (GMP Cert No. 575 | Mfg. Lic. MFG/AYUR/KL/MAL-201)"
            if is_pharmacy
            else "ROHINI Registration Certified Hospital | Ashtavaidyan Pulamanthole Mooss Ayurveda Hospital"
        )
        base_text = row.get("Caption") or row.get("Description") or row.get("Instagram") or ""
        summary = f"{base_text}\n\n{accred}\nCall/WhatsApp: {phone}\n{cta_url}".strip()
        image_url = extract_drive_image_url(row)
        for loc in locations:
            loc_title = (loc.get("title") or "").lower()
            if is_pharmacy and "hospital" in loc_title and "pharmacy" not in loc_title:
                continue
            existing = get_existing_post_summaries(loc["full_name"], headers)
            if summary[:80] in existing:
                print(f"Skipping duplicate for {loc.get('title')}")
                continue
            res = publish_local_post(loc["full_name"], summary, cta_type, cta_url, image_url, headers)
            print(f"Published to {loc.get('title')}: {res.get('name')}")


if __name__ == "__main__":
    main()
