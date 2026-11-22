from src.common.idempotency import build_idempotency_key, find_existing_prospect_keys, is_already_completed
from src.crm_verification.engine import verify_crm_records
from src.daily_reporting.engine import build_daily_report_metrics
from src.followup_engine.engine import build_eligible_followup_queue
from src.inbox_monitor.engine import classify_message
from src.prospect_research.engine import stage_verified_prospects
from src.weekly_review.engine import build_weekly_commercial_summary


def test_idempotency_and_dedup():
    k1 = build_idempotency_key("crm_verification", "2026-11-22", "srdayurveda@gmail.com")
    k2 = build_idempotency_key("crm_verification", "2026-11-22", "srdayurveda@gmail.com")
    assert k1 == k2
    assert is_already_completed([["Execution_ID", "Idempotency_Key", "x", "x", "x", "x", "Completed"], ["E1", k1, "", "", "", "", "Completed"]], k1)
    keys = find_existing_prospect_keys([["PM-B2B-001", "Art of Vedas", "", "", "", "", "", "info@artofvedas.com", "", "", "https://artofvedas.com"]])
    assert "art of vedas" in keys["companies"]
    assert "info@artofvedas.com" in keys["emails"]


def test_manufacturer_exclusion_and_stage_prospects():
    crm_rows = [["Lead_ID", "Company", "Email", "Website"], ["PM-B2B-001", "Existing Co", "a@existing.com", "https://existing.com"]]
    exc_rows = [["Exception_ID", "Company_ID", "Company_Name", "Legal_Entity", "Is_Manufacturer", "External_Procurement_Requirement", "Procurement_Evidence", "Proposed_Transaction_Nature", "Contract_Mfg_6Point_Check", "Written_Mgmt_Approval"]]
    res = stage_verified_prospects(
        [
            {"company": "ABC Ayurveda Own Brand Manufacturer", "email": "sales@abc.in", "website": "https://abc.in", "source_url": "https://abc.in/about", "buyer_category": "Own Brand Manufacturer"},
            {"company": "North India Wellness Pharmacy", "email": "desk@northpharmacy.in", "website": "https://northpharmacy.in", "source_url": "https://northpharmacy.in/contact", "buyer_category": "Pharmacy & Distributor"},
        ],
        crm_rows,
        exc_rows,
    )
    assert len(res["staged"]) == 1
    assert res["staged"][0]["company"] == "North India Wellness Pharmacy"
    assert len(res["skipped"]) == 1


def test_inbox_classifier_and_followup_safety():
    bounce = classify_message("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification (Failure)", "550 5.1.1 The email account that you tried to reach does not exist. booking@ayuja.mu")
    assert bounce["category"] == "hard_bounce"
    assert bounce["target_email"] == "booking@ayuja.mu"
    assert bounce["suppression_required"] == "true"

    crm = [["Lead_ID", "Company", "Email", "Email_Verification_Status", "Current_Status"], ["L1", "Bounced Co", "booking@ayuja.mu", "Bounced", "BOUNCED - SUPPRESSED"], ["L2", "Eligible Co", "buyer@validco.com", "Verified", "CONTACTED"]]
    sup = [["Suppression_ID", "Email_or_Domain"], ["SUP-013", "booking@ayuja.mu"]]
    fq = build_eligible_followup_queue(crm, sup, [], [], allow_external_dispatch=False)
    assert fq["eligible_count"] == 1
    assert fq["held_count"] == 1
    assert fq["external_dispatch_enabled"] is False


def test_crm_verification_daily_and_weekly_reports():
    crm = [["Lead_ID", "Company", "Country", "Business_Category", "Email", "Email_Verification_Status", "Website", "Priority_Tier", "Current_Status"], ["L1", "Clinic A", "India", "Clinic", "a@clinic.in", "Verified", "https://clinic.in", "Priority A", "Outreach Eligible"]]
    v = verify_crm_records(crm)
    assert v["total_rows"] == 1
    assert v["valid_count"] == 1

    d = build_daily_report_metrics(crm, [["ID", "Email"]], [["SKU", "Status"], ["S1", "DRAFT"]], [["CID", "Status"], ["E1", "Pending"]], {"eligible_count": 0}, [["ID", "K", "W", "S", "St", "Et", "Status"]])
    assert d["total_prospects"] == 1
    assert d["draft_price_skus"] == 1

    w = build_weekly_commercial_summary(crm, [["SKU", "Status"], ["S1", "DRAFT"]], [["CID", "Status"], ["E1", "Pending"]], [["EID"]])
    assert w["total_crm_prospects"] == 1
    assert w["draft_price_skus"] == 1
