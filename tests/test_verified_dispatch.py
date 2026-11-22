import datetime as dt

from scripts.b2b_verified_outreach_dispatch import (
    EMAIL_RE,
    build_dispatch_plan,
    extract_sender_address,
    persist_inbox_suppressions,
)

HEADERS = [
    "Lead_ID", "Company", "Email", "Email_Verification_Status", "Current_Status",
    "Last_Email_Sent", "Follow_Up_Date", "Notes",
]


def test_email_validation_and_sender_normalization():
    assert EMAIL_RE.fullmatch("buyer@example.co.in")
    assert not EMAIL_RE.fullmatch("buyer@example")
    assert extract_sender_address('Procurement <Buyer@Example.com>') == "buyer@example.com"


def test_only_exactly_verified_and_eligible_leads_are_selected():
    crm = [
        HEADERS,
        ["L1", "Qualified Buyer", "buyer@example.com", "Verified", "Outreach Eligible", "", "", ""],
        ["L2", "Unverified Buyer", "other@example.com", "Pending", "Outreach Eligible", "", "", ""],
        ["L3", "Suppressed Buyer", "stop@example.com", "Verified", "Outreach Eligible", "", "", ""],
        ["L4", "Reply Buyer", "reply@example.com", "Verified", "Outreach Eligible", "", "", ""],
    ]
    suppression = [["Suppression_ID", "Email_or_Domain"], ["S1", "stop@example.com"]]
    result = build_dispatch_plan(crm, suppression, [["Message"]], ["reply@example.com"], dt.date(2026, 11, 22), 10)
    assert [x["lead_id"] for x in result["eligible"]] == ["L1"]
    assert len(result["held"]) == 3


def test_domain_suppression_daily_cap_and_hard_maximum():
    crm = [HEADERS]
    for n in range(25):
        crm.append([f"L{n}", f"Buyer {n}", f"buyer{n}@example.com", "Verified", "Qualified", "", "", ""])
    suppression = [["Suppression_ID", "Email_or_Domain"], ["S1", "blocked.com"]]
    result = build_dispatch_plan(crm, suppression, [], [], dt.date(2026, 11, 22), 100)
    assert len(result["eligible"]) == 20
    assert result["daily_limit"] == 20


def test_followup_requires_due_date_cooldown_and_touch_cap():
    crm = [
        HEADERS,
        ["L1", "Due", "due@example.com", "Verified", "CONTACTED", "2026-11-01", "2026-11-08", "B2B_AUTOMATION_TOUCH=1"],
        ["L2", "Too Soon", "soon@example.com", "Verified", "CONTACTED", "2026-11-20", "2026-11-21", "B2B_AUTOMATION_TOUCH=1"],
        ["L3", "Too Many", "max@example.com", "Verified", "CONTACTED", "2026-11-01", "2026-11-08", "B2B_AUTOMATION_TOUCH=4"],
    ]
    result = build_dispatch_plan(crm, [["Suppression_ID", "Email_or_Domain"]], [], [], dt.date(2026, 11, 22), 10)
    assert [x["lead_id"] for x in result["eligible"]] == ["L1"]
    assert len(result["held"]) == 2


class FakeSheets:
    def __init__(self):
        self.appended = None

    def append_values(self, spreadsheet_id, range_name, values):
        self.appended = (spreadsheet_id, range_name, values)


def test_unsubscribe_complaint_and_bounce_are_persisted_once():
    sheets = FakeSheets()
    headers = ["Suppression_ID", "Email_or_Domain", "Reason", "Source", "Date_Added", "Status", "Extra", "Extra2"]
    classified = [
        {"category": "unsubscribe", "target_email": "stop@example.com"},
        {"category": "complaint", "target_email": "complaint@example.com"},
        {"category": "hard_bounce", "target_email": "bounce@example.com"},
    ]
    count = persist_inbox_suppressions(sheets, "sheet-1", [headers], classified, "2026-11-22T10:00:00+05:30")
    assert count == 3
    assert sheets.appended[1] == "Suppression_&_DNC_List!A:H"
    assert [row[1] for row in sheets.appended[2]] == ["stop@example.com", "complaint@example.com", "bounce@example.com"]
    count_again = persist_inbox_suppressions(sheets, "sheet-1", [headers, ["S1", "stop@example.com"]], classified[:1], "2026-11-22T10:00:00+05:30")
    assert count_again == 0
