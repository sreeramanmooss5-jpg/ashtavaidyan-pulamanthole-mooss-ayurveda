import argparse
import json
import sys
from typing import Any, List

from src.common.config import load_config
from src.common.gmail_client import GmailReadClient
from src.common.google_sheets import GoogleSheetsClient
from src.common.idempotency import build_idempotency_key
from src.common.logging import get_logger, log_event
from src.crm_verification.engine import verify_crm_records
from src.daily_reporting.engine import build_daily_report_metrics
from src.followup_engine.engine import build_eligible_followup_queue
from src.inbox_monitor.engine import classify_message, summarize_classifications
from src.prospect_research.engine import stage_verified_prospects
from src.weekly_review.engine import build_weekly_commercial_summary


def _require_secret(name: str, val: str, logger) -> bool:
    if not val:
        log_event(logger, "ERROR", "missing_required_secret", secret_name=name)
        return False
    return True


def run_workflow(workflow_key: str, dry_run: bool = False) -> int:
    cfg = load_config(dry_run=dry_run)
    logger = get_logger(f"srd.b2b.{workflow_key}", cfg.timezone)

    if not _require_secret("CRM_SPREADSHEET_ID", cfg.crm_spreadsheet_id, logger):
        return 1

    sheets = None
    if cfg.google_service_account_json:
        try:
            sheets = GoogleSheetsClient(
                cfg.google_service_account_json,
                timeout_sec=cfg.api_timeout_sec,
                max_retries=cfg.max_retries,
                backoff_base_sec=cfg.backoff_base_sec,
            )
        except Exception as exc:
            log_event(logger, "ERROR", "sheets_init_failed", error=str(exc))
            return 1
    elif workflow_key in ("crm_verification", "followup_eligibility", "daily_report", "weekly_review"):
        log_event(logger, "ERROR", "missing_required_secret", secret_name="GOOGLE_SERVICE_ACCOUNT_JSON")
        return 1

    idem_key = build_idempotency_key(workflow_key, "2026-11-22", cfg.sender_email)
    log_event(logger, "INFO", "workflow_start", workflow=workflow_key, idempotency_key=idem_key, dry_run=cfg.dry_run)

    summary: Any = {}
    if workflow_key == "prospect_research":
        crm_rows = sheets.get_values(cfg.crm_spreadsheet_id, "Global_Prospect_CRM!A1:U120") if sheets else []
        exc_rows = sheets.get_values(cfg.crm_spreadsheet_id, "Manufacturer_Exceptions!A1:S10") if sheets else []
        res = stage_verified_prospects([], crm_rows, exc_rows)
        summary = {"existing_crm_rows": max(0, len(crm_rows) - 1), "staged_count": len(res["staged"]), "skipped_count": len(res["skipped"])}

    elif workflow_key == "crm_verification":
        crm_rows = sheets.get_values(cfg.crm_spreadsheet_id, "Global_Prospect_CRM!A1:U120")
        summary = verify_crm_records(crm_rows)

    elif workflow_key == "inbox_monitor":
        if not (cfg.gmail_client_id and cfg.gmail_client_secret and cfg.gmail_refresh_token):
            log_event(logger, "ERROR", "missing_gmail_oauth_secrets")
            return 1
        gmail = GmailReadClient(cfg.gmail_client_id, cfg.gmail_client_secret, cfg.gmail_refresh_token, cfg.max_retries, cfg.backoff_base_sec)
        msgs = gmail.list_messages(query="newer_than:3d", max_results=25)
        classified = []
        for m in msgs[:25]:
            meta = gmail.get_message_metadata(m["id"])
            h = meta.get("headers", {})
            classified.append(classify_message(h.get("from", ""), h.get("subject", ""), meta.get("snippet", "")))
        summary = {"messages_inspected": len(classified), "counts": summarize_classifications(classified), "outbound_sent": 0}

    elif workflow_key == "followup_eligibility":
        data = sheets.batch_get(cfg.crm_spreadsheet_id, [
            "Global_Prospect_CRM!A1:U120",
            "Suppression_&_DNC_List!A1:H25",
            "Inbox_Replies!A1:Z25",
            "Manufacturer_Exceptions!A1:S10",
        ])
        crm_rows = data.get("Global_Prospect_CRM!A1:U120", [])
        sup_rows = data.get("Suppression_&_DNC_List!A1:H25", [])
        rep_rows = data.get("Inbox_Replies!A1:Z25", [])
        exc_rows = data.get("Manufacturer_Exceptions!A1:S10", [])
        summary = build_eligible_followup_queue(crm_rows, sup_rows, rep_rows, exc_rows, allow_external_dispatch=False)

    elif workflow_key == "daily_report":
        data = sheets.batch_get(cfg.crm_spreadsheet_id, [
            "Global_Prospect_CRM!A1:U120",
            "Suppression_&_DNC_List!A1:H25",
            "Commercial_Price_Master!A1:AJ25",
            "Export_Compliance!A1:V25",
            "Followup_Queue!A1:P15",
            "Automation_Execution_Logs!A1:O35",
        ])
        crm_rows = data.get("Global_Prospect_CRM!A1:U120", [])
        sup_rows = data.get("Suppression_&_DNC_List!A1:H25", [])
        price_rows = data.get("Commercial_Price_Master!A1:AJ25", [])
        export_rows = data.get("Export_Compliance!A1:V25", [])
        log_rows = data.get("Automation_Execution_Logs!A1:O35", [])
        fu_sum = build_eligible_followup_queue(crm_rows, sup_rows, [], [], allow_external_dispatch=False)
        summary = build_daily_report_metrics(crm_rows, sup_rows, price_rows, export_rows, fu_sum, log_rows)

    elif workflow_key == "weekly_review":
        data = sheets.batch_get(cfg.crm_spreadsheet_id, [
            "Global_Prospect_CRM!A1:U120",
            "Commercial_Price_Master!A1:AJ25",
            "Export_Compliance!A1:V25",
            "Manufacturer_Exceptions!A1:S10",
        ])
        summary = build_weekly_commercial_summary(
            data.get("Global_Prospect_CRM!A1:U120", []),
            data.get("Commercial_Price_Master!A1:AJ25", []),
            data.get("Export_Compliance!A1:V25", []),
            data.get("Manufacturer_Exceptions!A1:S10", []),
        )
    else:
        log_event(logger, "ERROR", "unknown_workflow", workflow=workflow_key)
        return 1

    log_event(logger, "INFO", "workflow_complete", workflow=workflow_key, idempotency_key=idem_key, summary=summary)
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SRD Ayurvedics B2B Autonomous Execution Engine")
    parser.add_argument("--workflow", required=True, choices=["prospect_research", "crm_verification", "inbox_monitor", "followup_eligibility", "daily_report", "weekly_review"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run_workflow(args.workflow, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
