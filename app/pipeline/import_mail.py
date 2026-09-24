"""Parse a CSV or JSON mailbox export into message records."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime

_FIELDS = {
    "sender": "sender",
    "from": "sender",
    "from_addr": "sender",
    "recipient": "recipient",
    "to": "recipient",
    "senddate": "senddate",
    "sent": "senddate",
    "date": "senddate",
    "sent_at": "senddate",
    "subject": "subject",
    "message": "message",
    "body": "message",
    "text": "message",
}


class ImportError(Exception):
    """User-facing import error. Do not include message bodies."""


def parse_mail_file(filename: str, raw: bytes) -> list[dict]:
    if len(raw) > 20_000_000:
        raise ImportError("The file is larger than 20 MB.")
    name = (filename or "").lower()
    text = raw.decode("utf-8-sig", errors="replace")
    if name.endswith(".json") or text.lstrip()[:1] in "[{":
        rows = _rows_from_json(text)
    else:
        rows = _rows_from_csv(text)
    records = []
    for row in rows:
        record = _record(row)
        if record:
            records.append(record)
    if not records:
        raise ImportError("No messages found. Use sender, recipient, senddate, subject, and message.")
    if len(records) > 20000:
        raise ImportError("A file can contain at most 20,000 messages.")
    return records


def _rows_from_json(text: str) -> list:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportError("That file is not valid JSON.") from exc
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("messages", "emails", "items", "mail"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
        if any(key in payload for key in ("sender", "from", "subject", "message", "body")):
            return [payload]
    raise ImportError("JSON must be a list of messages, or an object with a messages list.")


def _rows_from_csv(text: str) -> list[dict]:
    sample = text.lstrip()
    if not sample:
        raise ImportError("The CSV file is empty.")
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ImportError("The CSV file needs a header row.")
        return list(reader)
    except csv.Error as exc:
        raise ImportError("Could not read that CSV file.") from exc


def _record(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    mapped = {canonical: "" for canonical in ("sender", "recipient", "senddate", "subject", "message")}
    for key, value in row.items():
        canonical = _FIELDS.get(str(key or "").strip().lower().replace(" ", ""))
        if canonical and value is not None:
            mapped[canonical] = str(value).strip()
    if not mapped["subject"] and not mapped["message"]:
        return None
    sender = mapped["sender"][:300]
    recipient = mapped["recipient"][:300]
    senddate = _date(mapped["senddate"])
    subject = mapped["subject"][:500]
    message = mapped["message"][:100000]
    identity = "|".join([sender, recipient, senddate, subject, message[:200]])
    return {
        "external_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
        "sender": sender,
        "recipient": recipient,
        "senddate": senddate,
        "subject": subject,
        "message": message,
    }


def _date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19], fmt).isoformat()
        except ValueError:
            continue
    return text[:40]
