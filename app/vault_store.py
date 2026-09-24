"""Credentials vault. The key stays in memory. SQLite stores AES-256-GCM ciphertext."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.db import connect, set_setting, setting, utc_now

ITERATIONS = 200_000
_VERIFIER = b"lifevault-ok"
_lock = threading.RLock()
_key: bytes | None = None

KINDS: list[dict[str, Any]] = [
    {
        "key": "logins",
        "label": "Logins",
        "hint": "url",
        "secret": "password",
        "fields": [
            {"name": "title", "label": "Name"},
            {"name": "url", "label": "Website"},
            {"name": "username", "label": "Username"},
            {"name": "password", "label": "Password", "secret": True},
            {"name": "notes", "label": "Notes", "area": True},
        ],
    },
    {
        "key": "social",
        "label": "Social",
        "hint": "network",
        "secret": "password",
        "fields": [
            {"name": "title", "label": "Name"},
            {"name": "network", "label": "Network"},
            {"name": "username", "label": "Username"},
            {"name": "password", "label": "Password", "secret": True},
            {"name": "notes", "label": "Notes", "area": True},
        ],
    },
    {
        "key": "ebanking",
        "label": "E-banking",
        "hint": "bank",
        "secret": "password",
        "fields": [
            {"name": "title", "label": "Name"},
            {"name": "bank", "label": "Bank"},
            {"name": "user_id", "label": "User id"},
            {"name": "password", "label": "Password", "secret": True},
            {"name": "notes", "label": "Notes", "area": True},
        ],
    },
    {
        "key": "crypto",
        "label": "Crypto",
        "hint": "holder",
        "secret": "secret",
        "fields": [
            {"name": "title", "label": "Name"},
            {"name": "holder", "label": "Wallet or exchange"},
            {"name": "address", "label": "Address"},
            {"name": "secret", "label": "Seed or key", "secret": True, "area": True},
            {"name": "notes", "label": "Notes", "area": True},
        ],
    },
]
KIND_KEYS = {row["key"] for row in KINDS}


class VaultError(Exception):
    pass


def vault_ready() -> bool:
    return bool(setting("vault_kdf_salt") and setting("vault_verifier"))


def unlocked() -> bool:
    with _lock:
        return _key is not None


def lock() -> None:
    global _key
    with _lock:
        _key = None


def setup(password: str, confirm: str) -> None:
    if vault_ready():
        raise VaultError("A master password is already set.")
    _check_pair(password, confirm)
    salt = os.urandom(16)
    key = _derive(password, salt)
    set_setting("vault_kdf_salt", base64.b64encode(salt).decode())
    set_setting("vault_verifier", _pack(_encrypt(key, _VERIFIER)))
    global _key
    with _lock:
        _key = key


def unlock(password: str) -> bool:
    global _key
    if not vault_ready():
        return False
    salt = base64.b64decode(setting("vault_kdf_salt"))
    key = _derive(password, salt)
    try:
        plain = _decrypt(key, setting("vault_verifier"))
    except Exception:
        return False
    if plain != _VERIFIER:
        return False
    with _lock:
        _key = key
    return True


def list_entries(kind: str = "") -> list[dict[str, Any]]:
    key = _require()
    sql = "SELECT id, kind, nonce, ciphertext, updated_at FROM credentials"
    params: tuple = ()
    if kind in KIND_KEYS:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY id DESC"
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    entries = []
    for row in rows:
        payload = json.loads(_decrypt(key, f"{row['nonce']}.{row['ciphertext']}").decode())
        entries.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "updated": (row["updated_at"] or "")[:16].replace("T", " "),
                "fields": payload,
            }
        )
    return entries


def counts() -> dict[str, int]:
    _require()
    with _lock:
        conn = connect()
        try:
            rows = conn.execute("SELECT kind, COUNT(*) AS n FROM credentials GROUP BY kind").fetchall()
        finally:
            conn.close()
    found = {row["kind"]: row["n"] for row in rows}
    return {kind: int(found.get(kind, 0)) for kind in KIND_KEYS}


def save_entry(kind: str, fields: dict[str, str], entry_id: int | None = None) -> int:
    if kind not in KIND_KEYS:
        raise VaultError("Choose a kind.")
    title = (fields.get("title") or "").strip()
    if not title:
        raise VaultError("Give the entry a name.")
    clean = {name: (fields.get(name) or "").strip()[:4000] for name in _field_names(kind)}
    clean["title"] = title[:200]
    key = _require()
    packed = _pack(_encrypt(key, json.dumps(clean).encode()))
    nonce, ciphertext = packed.split(".", 1)
    now = utc_now()
    with _lock:
        conn = connect()
        try:
            if entry_id:
                cur = conn.execute(
                    """
                    UPDATE credentials
                    SET kind = ?, nonce = ?, ciphertext = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (kind, nonce, ciphertext, now, entry_id),
                )
                if cur.rowcount != 1:
                    raise VaultError("That entry is no longer in the vault.")
                conn.commit()
                return entry_id
            cur = conn.execute(
                """
                INSERT INTO credentials(kind, nonce, ciphertext, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (kind, nonce, ciphertext, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def delete_entry(entry_id: int) -> None:
    _require()
    with _lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM credentials WHERE id = ?", (entry_id,))
            conn.commit()
        finally:
            conn.close()


def _field_names(kind: str) -> list[str]:
    for row in KINDS:
        if row["key"] == kind:
            return [field["name"] for field in row["fields"]]
    return []


def _check_pair(password: str, confirm: str) -> None:
    if len(password) < 8:
        raise VaultError("Use at least 8 characters.")
    if password != confirm:
        raise VaultError("The two passwords do not match.")


def _require() -> bytes:
    with _lock:
        if _key is None:
            raise VaultError("Unlock the vault first.")
        return _key


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, dklen=32)


def _encrypt(key: bytes, plain: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plain, None)


def _decrypt(key: bytes, packed: str) -> bytes:
    nonce_b64, cipher_b64 = packed.split(".", 1)
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(cipher_b64)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _pack(blob: tuple[bytes, bytes]) -> str:
    nonce, ciphertext = blob
    return base64.b64encode(nonce).decode() + "." + base64.b64encode(ciphertext).decode()
