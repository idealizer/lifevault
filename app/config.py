"""Environment settings. Process env wins over the local .env file."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APERTUS_BASE_URL = "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1"
APERTUS_MODEL = "swiss-ai/Apertus-v1.5-70B"
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_MODEL = "grok-4"


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def host() -> str:
    return env("LIFE_HOST", "127.0.0.1") or "127.0.0.1"


def port() -> int:
    try:
        return int(env("LIFE_PORT", "8765") or "8765")
    except ValueError:
        return 8765


def db_path() -> Path:
    raw = env("LIFE_DB", "data/lifevault.db") or "data/lifevault.db"
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def data_dir() -> Path:
    return db_path().parent


def google_secret_path() -> Path:
    raw = env("GOOGLE_CLIENT_SECRET", "data/google_client_secret.json")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def oauth_redirect_uri() -> str:
    return f"http://127.0.0.1:{port()}/oauth/google/callback"


def batch_size() -> int:
    try:
        value = int(env("LIFE_BATCH_SIZE", "20") or "20")
    except ValueError:
        value = 20
    return min(25, max(5, value))


def body_chars() -> int:
    try:
        value = int(env("LIFE_BODY_CHARS", "6000") or "6000")
    except ValueError:
        value = 6000
    return min(20000, max(500, value))


def access_password() -> str:
    return env("LIFE_ACCESS_PASSWORD")


def default_token_budget() -> int:
    try:
        value = int(env("LIFE_TOKEN_BUDGET", "2000000") or "2000000")
    except ValueError:
        value = 2_000_000
    return min(10_000_000, max(10_000, value))
