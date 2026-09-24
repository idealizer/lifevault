"""Local signals for domains and impersonation. These do not depend on the model."""

from __future__ import annotations

import re

from app.pipeline.extract import normalize_finding

_DOMAIN_OFFER = re.compile(r"domain offer:\s*([a-z0-9][a-z0-9.-]+\.[a-z0-9-]{2,})", re.I)
_DOMAIN_LINE = re.compile(r"(?:^|\n)\s*domain:\s*([a-z0-9][a-z0-9.-]+\.[a-z0-9-]{2,})", re.I)
_EMAIL = re.compile(r"<([^>]+)>|([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.I)

_BRANDS = (
    ("raiffeisen", ("raiffeisen.ch", "raiffeisen.com"), "Raiffeisen"),
    ("postfinance", ("postfinance.ch",), "PostFinance"),
    ("ubs", ("ubs.com", "ubs.ch"), "UBS"),
    ("e-tax", ("nta.go.jp",), "e-Tax"),
    ("tax agency", ("nta.go.jp",), "Tax agency"),
    ("国税庁", ("nta.go.jp",), "Tax agency"),
)


def _domains(text: str) -> list[str]:
    found: list[str] = []
    for match in list(_DOMAIN_OFFER.findall(text)) + list(_DOMAIN_LINE.findall(text)):
        host = match.strip(" .,").lower()
        if host and host not in found and ".." not in host:
            found.append(host)
    return found


def _from_domain(from_addr: str) -> str:
    match = _EMAIL.search(from_addr or "")
    email = ""
    if match:
        email = (match.group(1) or match.group(2) or "").lower()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1]


def signals_for_message(message: dict) -> list[dict]:
    text = "\n".join(
        [
            message.get("subject") or "",
            message.get("snippet") or "",
            message.get("excerpt") or "",
        ]
    )
    evidence = [str(message.get("id") or "")]
    findings: list[dict] = []
    for host in _domains(f"{message.get('subject') or ''}\n{text}"):
        finding = normalize_finding(
            {
                "category": "domains_hosting",
                "provider": host,
                "asset_kind": "domain",
                "label": host,
                "identifiers": [{"type": "domain", "value": host}],
                "confidence": 0.92,
                "evidence_ids": evidence,
                "excerpt": (message.get("subject") or "")[:240],
            }
        )
        if finding:
            findings.append(finding)
    blob = f"{message.get('from_addr') or ''}\n{message.get('subject') or ''}".lower()
    sender = _from_domain(message.get("from_addr") or "")
    for needle, official, label in _BRANDS:
        if len(needle) <= 4 and needle.isascii():
            if not re.search(rf"\b{re.escape(needle)}\b", blob):
                continue
        elif needle not in blob:
            continue
        if sender and any(sender == domain or sender.endswith("." + domain) for domain in official):
            continue
        finding = normalize_finding(
            {
                "category": "risks",
                "provider": label,
                "asset_kind": "impersonation",
                "label": f"Possible {label} impersonation",
                "identifiers": [{"type": "sender", "value": sender or "unknown"}],
                "confidence": 0.74,
                "evidence_ids": evidence,
                "excerpt": (message.get("subject") or "")[:240],
            }
        )
        if finding:
            findings.append(finding)
            break
    return findings
