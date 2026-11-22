import base64
import random
import time
from typing import Any, Dict, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GMAIL_READONLY_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailReadClient:
    """Read-only Gmail OAuth client; outbound email sending is intentionally not supported here."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, max_retries: int = 3, backoff_base_sec: float = 1.0):
        if not client_id or not client_secret or not refresh_token:
            raise ValueError("GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN are required.")
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=GMAIL_READONLY_SCOPES,
        )
        self.max_retries = max_retries
        self.backoff_base_sec = backoff_base_sec
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _call_with_retry(self, fn):
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(self.backoff_base_sec * (2 ** attempt) + random.uniform(0.1, 0.4))
                    continue
                raise

    def list_messages(self, query: str = "", max_results: int = 50) -> List[Dict[str, str]]:
        def _op():
            resp = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            return resp.get("messages") or []

        return self._call_with_retry(_op)

    def get_message_metadata(self, message_id: str) -> Dict[str, Any]:
        def _op():
            msg = (
                self._service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date", "Auto-Submitted", "X-Failed-Recipients"],
                )
                .execute()
            )
            headers = {
                h.get("name", "").lower(): h.get("value", "")
                for h in (msg.get("payload") or {}).get("headers", [])
            }
            return {
                "id": msg.get("id", ""),
                "threadId": msg.get("threadId", ""),
                "snippet": msg.get("snippet", ""),
                "headers": headers,
            }

        return self._call_with_retry(_op)


def decode_base64url(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
