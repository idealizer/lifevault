"""Gmail readonly connector. OAuth tokens stay in local SQLite."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import datetime, timezone

from app.connectors.base import ConnectorError, MailHeader
from app.textutil import html_to_text, normalize_ws

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _google():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    return Request, Credentials, build


def credentials_from_secret(secret: dict):
    _Request, Credentials, _build = _google()
    token = secret.get("token") or {}
    creds = Credentials.from_authorized_user_info(token, SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(_Request())
        except Exception as exc:
            raise ConnectorError("Gmail authorization expired. Connect the mailbox again.") from exc
    if not creds.valid:
        raise ConnectorError("Gmail authorization expired. Connect the mailbox again.")
    return creds


def secret_from_credentials(creds) -> dict:
    return {"token": json.loads(creds.to_json())}


def build_service(creds):
    _Request, _Credentials, build = _google()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def profile_email(creds) -> str:
    service = build_service(creds)
    profile = service.users().getProfile(userId="me").execute()
    return str(profile.get("emailAddress") or "Gmail")


class GmailConnector:
    def __init__(self, secret: dict) -> None:
        self.secret = secret
        self.creds = credentials_from_secret(secret)
        self.secret = secret_from_credentials(self.creds)
        self.service = build_service(self.creds)

    def iter_headers(self, since_ymd: str, limit: int) -> Iterator[MailHeader]:
        query = f"after:{since_ymd.replace('-', '/')}"
        page_token = None
        seen = 0
        while True:
            remaining = max(limit - seen, 0) if limit else 100
            if limit and remaining <= 0:
                return
            page_size = min(100, remaining) if limit else 100
            try:
                response = (
                    self.service.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=page_size, pageToken=page_token)
                    .execute()
                )
            except Exception as exc:
                raise ConnectorError("Could not list Gmail messages.") from exc
            ids = [item["id"] for item in response.get("messages", []) if item.get("id")]
            for group in _chunks(ids, 50):
                for message in _metadata_batch(self.service, group):
                    yield _header_from_gmail(message)
                    seen += 1
                    if limit and seen >= limit:
                        return
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def fetch_body(self, external_id: str) -> str:
        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=external_id, format="full")
                .execute()
            )
        except Exception as exc:
            raise ConnectorError("Could not read a Gmail message.") from exc
        return _body_from_payload(message.get("payload") or {})

    def close(self) -> None:
        return None


def _chunks(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _metadata_batch(service, ids: list[str]) -> list[dict]:
    found: list[dict] = []

    def callback(_request_id, response, exception) -> None:
        if exception is None and response:
            found.append(response)

    batch = service.new_batch_http_request(callback=callback)
    for message_id in ids:
        batch.add(
            service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
        )
    batch.execute()
    return found


def _header_from_gmail(message: dict) -> MailHeader:
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in (message.get("payload") or {}).get("headers", [])
    }
    message_date = headers.get("date") or ""
    internal = message.get("internalDate")
    if internal:
        message_date = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).isoformat()
    return MailHeader(
        external_id=str(message.get("id") or ""),
        message_date=message_date,
        from_addr=headers.get("from") or "",
        subject=headers.get("subject") or "",
        snippet=normalize_ws(message.get("snippet") or "")[:1000],
    )


def _decode_b64(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode())
    return raw.decode("utf-8", errors="replace")


def _body_from_payload(payload: dict) -> str:
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        filename = part.get("filename") or ""
        if filename:
            return
        mime = part.get("mimeType") or ""
        data = (part.get("body") or {}).get("data") or ""
        if mime == "text/plain" and data:
            plain.append(_decode_b64(data))
        elif mime == "text/html" and data:
            html_parts.append(_decode_b64(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if any(part.strip() for part in plain):
        return normalize_ws("\n".join(plain))[:200000]
    return normalize_ws(html_to_text("\n".join(html_parts)))[:200000]
