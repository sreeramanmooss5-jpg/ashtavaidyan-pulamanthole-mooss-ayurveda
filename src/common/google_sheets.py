import json
import random
import time
from typing import Any, Dict, List

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsClient:
    def __init__(self, service_account_json: str, timeout_sec: int = 30, max_retries: int = 3, backoff_base_sec: float = 1.0):
        if not service_account_json or not service_account_json.strip():
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required for Google Sheets client.")
        info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self.max_retries = max_retries
        self.backoff_base_sec = backoff_base_sec
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _call_with_retry(self, fn):
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    sleep_sec = self.backoff_base_sec * (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(sleep_sec)
                    continue
                raise

    def get_values(self, spreadsheet_id: str, range_name: str) -> List[List[Any]]:
        def _op():
            resp = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
            return resp.get("values") or []

        return self._call_with_retry(_op)

    def batch_get(self, spreadsheet_id: str, ranges: List[str]) -> Dict[str, List[List[Any]]]:
        def _op():
            resp = (
                self._service.spreadsheets()
                .values()
                .batchGet(spreadsheetId=spreadsheet_id, ranges=ranges)
                .execute()
            )
            out: Dict[str, List[List[Any]]] = {}
            for vr in resp.get("valueRanges") or []:
                out[vr.get("range", "")] = vr.get("values") or []
            return out

        return self._call_with_retry(_op)

    def update_values(self, spreadsheet_id: str, range_name: str, values: List[List[Any]], value_input_option: str = "USER_ENTERED") -> Dict[str, Any]:
        def _op():
            return (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body={"values": values},
                )
                .execute()
            )

        return self._call_with_retry(_op)
