# SRD Ayurvedics Autonomous B2B Execution Engine (Stage 6)

- **Repository:** `sreeramanmooss5-jpg/ashtavaidyan-pulamanthole-mooss-ayurveda` (branch `main`)
- **CRM Spreadsheet:** `1mHdueoG3_cridg1YxML19CvB6QqE4Y5yjnxDa27QIRc`
- **Sender / Inbox:** `srdayurveda@gmail.com`

## Architecture & Controls
- `src/common/`: `config.py`, `google_sheets.py`, `gmail_client.py`, `logging.py`, `idempotency.py`
- `src/prospect_research/`, `src/crm_verification/`, `src/inbox_monitor/`, `src/followup_engine/`, `src/daily_reporting/`, `src/weekly_review/`, and `src/runner.py`
- Enforces least-privilege permissions, retry/backoff, idempotency keys, manufacturer exclusion (`MFE-001`), bounce/DNC/unsubscribe/reply suppression, `DRAFT` pricing hold (`18` SKUs), export verification hold (`18` SKUs), and zero external email sending without explicit approval.
