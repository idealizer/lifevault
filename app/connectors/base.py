"""Mailbox connector types."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


class ConnectorError(Exception):
    """Safe, user-facing mailbox error. Do not attach message contents."""


@dataclass
class MailHeader:
    external_id: str
    message_date: str
    from_addr: str
    subject: str
    snippet: str


class MailConnector:
    def iter_headers(self, since_ymd: str, limit: int) -> Iterator[MailHeader]:
        raise NotImplementedError

    def fetch_body(self, external_id: str) -> str:
        raise NotImplementedError

    def close(self) -> None:
        return None
