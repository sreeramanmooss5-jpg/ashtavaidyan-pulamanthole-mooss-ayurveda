import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    crm_spreadsheet_id: str
    sender_email: str
    timezone: str = "Asia/Kolkata"
    dry_run: bool = False
    allow_external_send: bool = False
    api_timeout_sec: int = 30
    max_retries: int = 3
    backoff_base_sec: float = 1.0
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    google_service_account_json: str = ""


def load_config(dry_run: bool = False) -> EngineConfig:
    env_dry = os.environ.get("B2B_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    env_send = os.environ.get("B2B_ALLOW_EXTERNAL_SEND", "").strip().lower() in ("1", "true", "yes")
    return EngineConfig(
        crm_spreadsheet_id=os.environ.get("CRM_SPREADSHEET_ID", "").strip(),
        sender_email=os.environ.get("GMAIL_SENDER_EMAIL", "srdayurveda@gmail.com").strip(),
        timezone=os.environ.get("TZ", "Asia/Kolkata").strip() or "Asia/Kolkata",
        dry_run=dry_run or env_dry,
        allow_external_send=False if not env_send else False,  # Hard safety lock: external sending disabled by default
        api_timeout_sec=int(os.environ.get("API_TIMEOUT_SEC", "30")),
        max_retries=int(os.environ.get("API_MAX_RETRIES", "3")),
        backoff_base_sec=float(os.environ.get("API_BACKOFF_BASE_SEC", "1.0")),
        gmail_client_id=os.environ.get("GMAIL_CLIENT_ID", "").strip(),
        gmail_client_secret=os.environ.get("GMAIL_CLIENT_SECRET", "").strip(),
        gmail_refresh_token=os.environ.get("GMAIL_REFRESH_TOKEN", "").strip(),
        google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
    )
