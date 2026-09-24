"""OpenAI-compatible client for Apertus and Grok."""

from __future__ import annotations

import time

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from app.config import (
    APERTUS_BASE_URL,
    APERTUS_MODEL,
    XAI_BASE_URL,
    XAI_MODEL,
    env,
)
from app.db import setting
from app.pipeline.extract import SYSTEM_PROMPT, estimate_tokens


class ModelError(Exception):
    """Safe model error without request contents."""


def resolve_llm() -> dict[str, str]:
    provider = (setting("llm_provider") or env("LIFE_LLM_PROVIDER", "apertus") or "apertus").lower()
    if provider == "grok":
        return {
            "provider": "grok",
            "api_key": setting("xai_api_key") or env("XAI_API_KEY"),
            "base_url": setting("xai_base_url") or env("XAI_BASE_URL", XAI_BASE_URL) or XAI_BASE_URL,
            "model": setting("xai_model") or env("XAI_MODEL", XAI_MODEL) or XAI_MODEL,
        }
    return {
        "provider": "apertus",
        "api_key": setting("apertus_api_key") or env("APERTUS_API_KEY"),
        "base_url": setting("apertus_base_url") or env("APERTUS_BASE_URL", APERTUS_BASE_URL) or APERTUS_BASE_URL,
        "model": setting("apertus_model") or env("APERTUS_MODEL", APERTUS_MODEL) or APERTUS_MODEL,
    }


def complete(user_text: str, system: str | None = None) -> tuple[str, int]:
    config = resolve_llm()
    if not config["api_key"]:
        raise ModelError("Add an API key in settings.")
    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    messages = [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
            )
            text = ""
            if response.choices and response.choices[0].message:
                text = response.choices[0].message.content or ""
            used = 0
            if response.usage and response.usage.total_tokens:
                used = int(response.usage.total_tokens)
            if not used:
                used = estimate_tokens(user_text + text)
            time.sleep(0.25)
            return text, used
        except (RateLimitError, APIConnectionError) as exc:
            last_error = exc
            time.sleep(2)
        except APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status == 429 and attempt == 0:
                time.sleep(2)
                last_error = exc
                continue
            raise ModelError(f"Model request failed ({status or 'error'}).") from exc
    raise ModelError("Model request failed (connection).") from last_error
