"""Close-account guides from OpenAI web search. The key is never logged."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from openai import OpenAI

from app.db import save_api_log, setting
from app.llm.client import ModelError
from app.pipeline.estate_actions import actions_for
from app.pipeline.letter_copy import compose, detect_language
from app.pipeline.letters import executor_contact, needs_letter

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PROMPT = """You help an estate executor close, cancel, or transfer one asset of a deceased person.
Use web search. Prefer the organisation's own help page.
Return JSON only:
{"summary":"one sentence","steps":[{"title":"short","detail":"one or two sentences","url":"https://... or empty","email":"organisation@example.com or empty","needs_letter":false,"letter_action":""}]}
Set email when the organisation accepts the request by email. Use an address published by that organisation.
Set needs_letter true only when the organisation requires a posted letter, death certificate, or written authority.
When needs_letter is true, letter_action must be copied exactly from the allowed list.
Do not invent a login. Do not ask for passwords."""


def openai_ready() -> bool:
    return bool(setting("openai_api_key"))


def build_guide(finding: dict) -> dict:
    key = setting("openai_api_key")
    if not key:
        raise ModelError("Add an OpenAI API key in Settings.")
    model = setting("openai_model") or "gpt-4.1"
    allowed = actions_for(finding.get("category") or "other")
    identifiers = []
    for item in finding.get("identifiers") or []:
        if isinstance(item, dict) and item.get("value"):
            identifiers.append(f"{item.get('type') or 'reference'}: {item.get('value')}")
    user = "\n".join(
        [
            f"Provider: {finding.get('provider') or ''}",
            f"Asset: {finding.get('label') or ''}",
            f"Kind: {finding.get('asset_kind') or ''}",
            "Identifiers: " + (", ".join(identifiers) or "none"),
            "Allowed letter actions:",
            "\n".join(f"- {action}" for action in allowed),
        ]
    )
    payload = {"model": model, "tools": [{"type": "web_search"}], "instructions": _PROMPT, "input": user}
    client = OpenAI(api_key=key)
    try:
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            instructions=_PROMPT,
            input=user,
        )
    except Exception as exc:
        text = str(exc).replace(key, "[redacted]")[:4000]
        save_api_log("openai", model, "https://api.openai.com/v1/responses", "error", _dump(payload), _dump({"error": text}))
        raise ModelError("The close guide could not be prepared.") from exc
    body = response.model_dump() if hasattr(response, "model_dump") else {"output_text": getattr(response, "output_text", "")}
    save_api_log("openai", model, "https://api.openai.com/v1/responses", "ok", _dump(payload), _dump(body))
    guide = apply_mailto(parse_guide(getattr(response, "output_text", "") or "", allowed), finding)
    if not guide["steps"]:
        raise ModelError("The close guide did not include any steps.")
    return guide


def parse_guide(text: str, allowed: list[str]) -> dict:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {"summary": "", "steps": []}
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {"summary": "", "steps": []}
    steps = []
    for row in payload.get("steps") or []:
        if not isinstance(row, dict):
            continue
        title = _clean(row.get("title"), 120)
        detail = _clean(row.get("detail"), 600)
        if not title and not detail:
            continue
        url = str(row.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            url = ""
        action = str(row.get("letter_action") or "").strip()
        letter = bool(row.get("needs_letter")) and action in allowed and needs_letter(action)
        email = str(row.get("email") or "").strip()
        if not _EMAIL.match(email):
            email = ""
        steps.append(
            {
                "title": title or "Next",
                "detail": detail,
                "url": url,
                "email": email,
                "mailto": "",
                "needs_letter": letter,
                "letter_action": action if letter else "",
            }
        )
    return {"summary": _clean(payload.get("summary"), 300), "steps": steps[:8]}


def apply_mailto(guide: dict, finding: dict) -> dict:
    source = []
    for row in finding.get("evidence") or []:
        source.append(str(row.get("subject") or ""))
        source.append(str(row.get("body") or row.get("excerpt") or ""))
    lang = detect_language("\n".join(source))
    ctx = {
        "deceased": setting("deceased_name"),
        "died": setting("date_of_death"),
        "provider": finding.get("provider") or "the organisation",
        "asset": finding.get("label") or finding.get("provider") or "the relationship",
        "identifiers": finding.get("identifiers") or [],
        "estate_bank": setting("estate_bank"),
        "estate_iban": setting("estate_iban"),
        "estate_swift": setting("estate_swift"),
    }
    for step in guide.get("steps") or []:
        email = step.get("email") or ""
        action = step.get("letter_action") or ""
        subject = ""
        body = ""
        if email and action:
            letter = compose(action, lang, ctx)
            contact = executor_contact()
            subject = letter["subject"]
            body = "\n\n".join(
                [letter["salutation"], *letter["paragraphs"], letter["closing"], contact["signature"]]
            )
        step["mailto"] = _mailto(email, subject, body) if email else ""
    return guide


def _mailto(email: str, subject: str, body: str) -> str:
    query = []
    if subject:
        query.append("subject=" + quote(subject))
    if body:
        query.append("body=" + quote(body))
    suffix = ("?" + "&".join(query)) if query else ""
    return "mailto:" + email + suffix


def _clean(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _dump(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:400000]
