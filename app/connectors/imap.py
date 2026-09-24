"""Generic IMAP connector. Passwords stay in local SQLite."""

from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Iterator
from email import policy

from app.connectors.base import ConnectorError, MailHeader
from app.textutil import html_to_text, normalize_ws

_UID_RE = re.compile(rb"UID (\d+)")


def check_login(host: str, port: int, user: str, password: str, mailbox: str = "INBOX") -> None:
    client = imaplib.IMAP4_SSL(host, port, timeout=30)
    try:
        try:
            client.login(user, password)
        except imaplib.IMAP4.error as exc:
            raise ConnectorError("IMAP login failed. Check the host, username, and app password.") from exc
        typ, _data = client.select(mailbox, readonly=True)
        if typ != "OK":
            raise ConnectorError("Could not open that mailbox.")
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def _raw_from_fetch(data) -> bytes:
    if not data or data[0] is None:
        return b""
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return b""


def _part_text(part) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except Exception:
        pass
    payload = part.get_payload(decode=True) or b""
    if isinstance(payload, str):
        return payload
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def body_from_raw(raw: bytes) -> str:
    if not raw:
        return ""
    message = email.message_from_bytes(raw, policy=policy.default)
    plain: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition.lower():
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain.append(_part_text(part))
            elif ctype == "text/html":
                html_parts.append(_part_text(part))
    else:
        ctype = message.get_content_type()
        text = _part_text(message)
        if ctype == "text/html":
            html_parts.append(text)
        else:
            plain.append(text)
    if any(part.strip() for part in plain):
        return normalize_ws("\n".join(plain))
    return normalize_ws(html_to_text("\n".join(html_parts)))


class ImapConnector:
    def __init__(self, host: str, port: int, user: str, password: str, mailbox: str = "INBOX") -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.mailbox = mailbox or "INBOX"
        self._conn: imaplib.IMAP4_SSL | None = None

    def open(self) -> "ImapConnector":
        self._conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=60)
        try:
            self._conn.login(self.user, self.password)
        except imaplib.IMAP4.error as exc:
            self.close()
            raise ConnectorError("IMAP login failed. Check the host, username, and app password.") from exc
        typ, _data = self._conn.select(self.mailbox, readonly=True)
        if typ != "OK":
            self.close()
            raise ConnectorError("Could not open that mailbox.")
        return self

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.logout()
        except imaplib.IMAP4.error:
            pass
        self._conn = None

    def iter_headers(self, since_ymd: str, limit: int) -> Iterator[MailHeader]:
        assert self._conn is not None
        day, month, year = _imap_since(since_ymd)
        typ, data = self._conn.uid("SEARCH", None, f"(SINCE {day}-{month}-{year})")
        if typ != "OK" or not data or not data[0]:
            return
        uids = data[0].split()
        if limit and len(uids) > limit:
            uids = uids[-limit:]
        for group in _chunks(uids, 40):
            id_list = b",".join(group)
            typ, fetched = self._conn.uid(
                "FETCH",
                id_list,
                "(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.1000>)",
            )
            if typ != "OK":
                continue
            yield from _headers_from_fetch(fetched or [])

    def fetch_body(self, external_id: str) -> str:
        assert self._conn is not None
        typ, data = self._conn.uid("FETCH", external_id, "(BODY.PEEK[])")
        if typ != "OK":
            return ""
        return body_from_raw(_raw_from_fetch(data))


def _imap_since(since_ymd: str) -> tuple[str, str, str]:
    year, month, day = since_ymd.split("-")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return day, months[int(month) - 1], year


def _chunks(items: list[bytes], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _headers_from_fetch(data) -> Iterator[MailHeader]:
    current_uid: bytes | None = None
    blobs: list[bytes] = []

    def emit() -> MailHeader | None:
        if not current_uid:
            return None
        header_blob = b""
        text_blob = b""
        for blob in blobs:
            lowered = blob.lower()
            if b"from:" in lowered[:80] or b"\nsubject:" in lowered or b"\nfrom:" in lowered or lowered.startswith(b"subject:"):
                header_blob += blob
            else:
                text_blob += blob
        message = email.message_from_bytes(header_blob + b"\r\n\r\n", policy=policy.default)
        snippet = text_blob.decode("utf-8", errors="replace")
        return MailHeader(
            external_id=current_uid.decode(),
            message_date=str(message.get("date") or ""),
            from_addr=str(message.get("from") or ""),
            subject=str(message.get("subject") or ""),
            snippet=normalize_ws(snippet)[:1000],
        )

    for item in data:
        if isinstance(item, tuple):
            meta = item[0] if item else b""
            if isinstance(meta, str):
                meta = meta.encode()
            match = _UID_RE.search(meta or b"")
            if match and current_uid and match.group(1) != current_uid:
                header = emit()
                blobs = []
                if header:
                    yield header
            if match:
                current_uid = match.group(1)
            if len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                blobs.append(bytes(item[1]))
        elif item in (b")", b" )") and current_uid and blobs:
            header = emit()
            blobs = []
            current_uid = None
            if header:
                yield header
    if current_uid and blobs:
        header = emit()
        if header:
            yield header
