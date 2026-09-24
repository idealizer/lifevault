"""Dedupe findings by provider, category, and identifier."""

from __future__ import annotations

import re

_SUFFIX = re.compile(
    r"\b(ag|sa|ltd|gmbh|inc|llc|sarl|sagl|se|plc|nv|bv)\b",
    re.IGNORECASE,
)


def normalize_provider(name: str) -> str:
    text = _SUFFIX.sub(" ", name or "")
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", text)


def _ident_key(identifiers: list[dict] | None) -> str:
    if not identifiers:
        return ""
    first = identifiers[0]
    return re.sub(r"[^a-z0-9]+", "", str(first.get("value") or "").lower())


def make_merge_key(category: str, provider: str, identifiers: list[dict] | None) -> str:
    return f"{category}|{normalize_provider(provider)}|{_ident_key(identifiers)}"


def _union_identifiers(left: list[dict], right: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for item in list(left or []) + list(right or []):
        kind = str(item.get("type") or "id")
        value = str(item.get("value") or "")
        key = (kind, value.lower())
        if not value or key in seen:
            continue
        seen.add(key)
        merged.append({"type": kind, "value": value})
    return merged[:8]


def _union_ids(left: list[str] | None, right: list[str] | None) -> list[str]:
    merged: list[str] = []
    for item in list(left or []) + list(right or []):
        text = str(item)
        if text and text not in merged:
            merged.append(text)
    return merged


def merge_finding_records(base: dict | None, incoming: dict) -> dict:
    if base is None:
        record = dict(incoming)
        record["identifiers"] = _union_identifiers([], incoming.get("identifiers") or [])
        record["evidence_ids"] = _union_ids([], incoming.get("evidence_ids"))
        record["status"] = base_status(None)
        record["merge_key"] = incoming.get("merge_key") or make_merge_key(
            record["category"], record["provider"], record["identifiers"]
        )
        return record
    keep_existing = float(base.get("confidence") or 0) >= float(incoming.get("confidence") or 0)
    provider = base["provider"] if keep_existing else incoming["provider"]
    label = base.get("label") if keep_existing and base.get("label") else incoming.get("label")
    asset_kind = (
        base.get("asset_kind")
        if keep_existing and base.get("asset_kind")
        else incoming.get("asset_kind") or base.get("asset_kind") or ""
    )
    identifiers = _union_identifiers(base.get("identifiers") or [], incoming.get("identifiers") or [])
    status = base.get("status") or "candidate"
    if status not in {"confirmed", "dismissed"}:
        status = "candidate"
    return {
        "category": base.get("category") or incoming.get("category"),
        "provider": provider,
        "asset_kind": asset_kind,
        "label": label or provider,
        "identifiers": identifiers,
        "confidence": max(float(base.get("confidence") or 0), float(incoming.get("confidence") or 0)),
        "evidence_ids": _union_ids(base.get("evidence_ids"), incoming.get("evidence_ids")),
        "excerpt": incoming.get("excerpt") or base.get("excerpt") or "",
        "merge_key": base.get("merge_key") or incoming.get("merge_key"),
        "status": status,
    }


def base_status(existing: dict | None) -> str:
    if not existing:
        return "candidate"
    status = existing.get("status") or "candidate"
    if status in {"confirmed", "dismissed"}:
        return status
    return "candidate"


def collapse_findings(findings: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for finding in findings:
        key = finding["merge_key"]
        merged[key] = merge_finding_records(merged.get(key), finding)
    return list(merged.values())
