"""SQLite storage. Secrets stay in this local database and are never logged."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from app.config import db_path

_lock = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _lock:
        conn = connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    secret_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    window_start TEXT,
                    token_budget INTEGER NOT NULL DEFAULT 0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    messages_seen INTEGER NOT NULL DEFAULT 0,
                    messages_screened INTEGER NOT NULL DEFAULT 0,
                    batches_done INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL,
                    external_id TEXT NOT NULL,
                    message_date TEXT NOT NULL DEFAULT '',
                    from_addr TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    snippet TEXT NOT NULL DEFAULT '',
                    excerpt TEXT NOT NULL DEFAULT '',
                    screened INTEGER NOT NULL DEFAULT 0,
                    extracted_at TEXT,
                    last_run_id INTEGER,
                    UNIQUE(source_id, external_id)
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY,
                    category TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    asset_kind TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    identifiers_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    merge_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY,
                    finding_id INTEGER NOT NULL,
                    message_id INTEGER,
                    source_id INTEGER,
                    external_id TEXT NOT NULL DEFAULT '',
                    message_date TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    excerpt TEXT NOT NULL DEFAULT '',
                    UNIQUE(finding_id, source_id, external_id),
                    FOREIGN KEY(finding_id) REFERENCES findings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_run
                    ON messages(source_id, last_run_id, screened);
                """
            )
            _ensure_message_columns(conn)
            conn.commit()
        finally:
            conn.close()


def _ensure_message_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "recipient" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
    if "body" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN body TEXT NOT NULL DEFAULT ''")
    finding_columns = {row[1] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
    for name in ("proposed_action", "proposed_reason", "chosen_action", "action_note"):
        if name not in finding_columns:
            conn.execute(f"ALTER TABLE findings ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    if "action_status" not in finding_columns:
        conn.execute("ALTER TABLE findings ADD COLUMN action_status TEXT NOT NULL DEFAULT ''")
    if "guide_json" not in finding_columns:
        conn.execute("ALTER TABLE findings ADD COLUMN guide_json TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            finding_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            note TEXT NOT NULL DEFAULT '',
            packet_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "reply_status" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN reply_status TEXT NOT NULL DEFAULT 'awaiting'")
    if "reply_note" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN reply_note TEXT NOT NULL DEFAULT ''")
    if "reply_file" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN reply_file TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            nonce TEXT NOT NULL,
            ciphertext TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    credential_columns = {row[1] for row in conn.execute("PRAGMA table_info(credentials)").fetchall()}
    if "finding_id" not in credential_columns:
        conn.execute("ALTER TABLE credentials ADD COLUMN finding_id INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_logs (
            id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            endpoint TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '',
            response_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def setting(key: str, default: str = "") -> str:
    with _lock:
        row = _one("SELECT value FROM settings WHERE key = ?", (key,))
    if not row:
        return default
    return str(row["value"])


def set_setting(key: str, value: str) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()


def settings_map() -> dict[str, str]:
    with _lock:
        rows = _rows("SELECT key, value FROM settings")
    return {row["key"]: row["value"] for row in rows}


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def save_api_log(provider: str, model: str, endpoint: str, status: str, request: str, response: str) -> None:
    now = utc_now()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO api_logs(provider, model, endpoint, status, request_json, response_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider[:40],
                    model[:120],
                    endpoint[:300],
                    status[:40],
                    request[:400000],
                    response[:400000],
                    now,
                ),
            )
            conn.execute(
                """
                DELETE FROM api_logs
                WHERE id NOT IN (SELECT id FROM api_logs ORDER BY id DESC LIMIT 80)
                """
            )
            conn.commit()
        finally:
            conn.close()


def list_api_logs(limit: int = 80) -> list[dict[str, Any]]:
    with _lock:
        return _rows(
            """
            SELECT id, provider, model, endpoint, status, request_json, response_json, created_at
            FROM api_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )


def list_sources() -> list[dict[str, Any]]:
    with _lock:
        rows = _rows(
            "SELECT id, kind, label, config_json, created_at FROM sources ORDER BY id DESC"
        )
    for row in rows:
        row["config"] = json.loads(row.pop("config_json") or "{}")
    return rows


def get_source(source_id: int, with_secret: bool = False) -> dict[str, Any] | None:
    with _lock:
        row = _one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not row:
        return None
    row["config"] = json.loads(row.pop("config_json") or "{}")
    secret = json.loads(row.pop("secret_json") or "{}")
    if with_secret:
        row["secret"] = secret
    return row


def create_source(kind: str, label: str, config: dict[str, Any], secret: dict[str, Any]) -> int:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO sources(kind, label, config_json, secret_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (kind, label, json.dumps(config), json.dumps(secret), utc_now()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_source_secret(source_id: int, secret: dict[str, Any]) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE sources SET secret_json = ? WHERE id = ?",
                (json.dumps(secret), source_id),
            )
            conn.commit()
        finally:
            conn.close()


def analysed_counts() -> dict[str, int]:
    with _lock:
        messages = _one("SELECT COUNT(*) AS n FROM messages")
        findings = _one("SELECT COUNT(*) AS n FROM findings")
        files = _one("SELECT COUNT(*) AS n FROM sources WHERE kind = 'file'")
    return {
        "messages": int(messages["n"]) if messages else 0,
        "findings": int(findings["n"]) if findings else 0,
        "files": int(files["n"]) if files else 0,
    }


def drop_analysed_mail() -> dict[str, int]:
    """Clear scanned mail and inventory. Keep mailbox logins and model settings."""
    with _lock:
        conn = connect()
        try:
            counts = {
                "messages": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
                "findings": int(conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]),
            }
            conn.execute("DELETE FROM evidence")
            conn.execute("DELETE FROM findings")
            conn.execute("DELETE FROM jobs")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM runs")
            conn.execute("DELETE FROM sources WHERE kind = 'file'")
            conn.commit()
            return counts
        finally:
            conn.close()


def delete_source(source_id: int) -> None:
    with _lock:
        conn = connect()
        try:
            message_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM messages WHERE source_id = ?", (source_id,)
                ).fetchall()
            ]
            conn.execute("DELETE FROM evidence WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM messages WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM runs WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.execute(
                """
                DELETE FROM findings
                WHERE id NOT IN (SELECT finding_id FROM evidence)
                """
            )
            conn.commit()
        finally:
            conn.close()
        _ = message_ids


def upsert_message(
    source_id: int,
    external_id: str,
    message_date: str,
    from_addr: str,
    subject: str,
    snippet: str,
    screened: bool,
    run_id: int,
    recipient: str = "",
    body: str = "",
) -> int:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO messages(
                    source_id, external_id, message_date, from_addr, recipient, subject,
                    snippet, body, screened, last_run_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, external_id) DO UPDATE SET
                    message_date = excluded.message_date,
                    from_addr = excluded.from_addr,
                    recipient = excluded.recipient,
                    subject = excluded.subject,
                    snippet = excluded.snippet,
                    body = excluded.body,
                    screened = excluded.screened,
                    last_run_id = excluded.last_run_id
                """,
                (
                    source_id,
                    external_id,
                    message_date,
                    from_addr,
                    recipient[:300],
                    subject,
                    snippet[:1000],
                    body[:100000],
                    1 if screened else 0,
                    run_id,
                ),
            )
            row = conn.execute(
                "SELECT id FROM messages WHERE source_id = ? AND external_id = ?",
                (source_id, external_id),
            ).fetchone()
            conn.commit()
            return int(row["id"])
        finally:
            conn.close()


def messages_to_extract(source_id: int, run_id: int, force: bool) -> list[dict[str, Any]]:
    with _lock:
        if force:
            return _rows(
                """
                SELECT * FROM messages
                WHERE source_id = ? AND last_run_id = ? AND screened = 1
                ORDER BY message_date, id
                """,
                (source_id, run_id),
            )
        return _rows(
            """
            SELECT * FROM messages
            WHERE source_id = ? AND last_run_id = ? AND screened = 1
              AND extracted_at IS NULL
            ORDER BY message_date, id
            """,
            (source_id, run_id),
        )


def mark_extracted(message_id: int, excerpt: str, body: str = "") -> None:
    with _lock:
        conn = connect()
        try:
            if body:
                conn.execute(
                    """
                    UPDATE messages
                    SET extracted_at = ?, excerpt = ?, body = ?
                    WHERE id = ?
                    """,
                    (utc_now(), excerpt[:500], body[:100000], message_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE messages
                    SET extracted_at = ?, excerpt = ?
                    WHERE id = ?
                    """,
                    (utc_now(), excerpt[:500], message_id),
                )
            conn.commit()
        finally:
            conn.close()


def save_message_body(message_id: int, body: str) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE messages SET body = ? WHERE id = ?",
                (body[:100000], message_id),
            )
            conn.commit()
        finally:
            conn.close()


def evidence_messages(finding_id: int) -> list[dict[str, Any]]:
    with _lock:
        return _rows(
            """
            SELECT
                m.id, m.source_id, m.external_id, m.message_date, m.from_addr,
                m.recipient, m.subject, m.snippet, m.body, m.excerpt,
                e.subject AS evidence_subject, e.excerpt AS evidence_excerpt,
                e.message_date AS evidence_date
            FROM evidence e
            LEFT JOIN messages m ON m.id = e.message_id
            WHERE e.finding_id = ?
            ORDER BY COALESCE(m.message_date, e.message_date) DESC, e.id DESC
            """,
            (finding_id,),
        )


def create_run(source_id: int, window_start: str, token_budget: int) -> int:
    now = utc_now()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO runs(
                    source_id, status, window_start, token_budget,
                    created_at, updated_at
                ) VALUES(?, 'queued', ?, ?, ?, ?)
                """,
                (source_id, window_start, token_budget, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [run_id]
    with _lock:
        conn = connect()
        try:
            conn.execute(f"UPDATE runs SET {columns} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()


def get_run(run_id: int) -> dict[str, Any] | None:
    with _lock:
        return _one("SELECT * FROM runs WHERE id = ?", (run_id,))


def list_runs(limit: int = 8) -> list[dict[str, Any]]:
    with _lock:
        return _rows(
            """
            SELECT runs.*, sources.label AS source_label
            FROM runs
            LEFT JOIN sources ON sources.id = runs.source_id
            ORDER BY runs.id DESC
            LIMIT ?
            """,
            (limit,),
        )


def interrupt_stale_runs() -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE runs
                SET status = 'error', error = 'Scan interrupted', note = 'Scan interrupted', updated_at = ?
                WHERE status IN ('queued', 'running', 'stopping')
                """,
                (utc_now(),),
            )
            conn.commit()
        finally:
            conn.close()


def assign_run(source_id: int, run_id: int, limit: int) -> int:
    with _lock:
        conn = connect()
        try:
            ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT id FROM messages
                    WHERE source_id = ?
                    ORDER BY message_date, id
                    LIMIT ?
                    """,
                    (source_id, limit),
                ).fetchall()
            ]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE messages SET last_run_id = ? WHERE id IN ({marks})",
                    [run_id, *ids],
                )
            conn.commit()
            return len(ids)
        finally:
            conn.close()


def list_messages() -> list[dict[str, Any]]:
    with _lock:
        return _rows(
            """
            SELECT id, source_id, external_id, message_date, from_addr, subject, snippet, excerpt
            FROM messages
            ORDER BY id
            """
        )


def has_active_run() -> bool:
    with _lock:
        row = _one(
            "SELECT id FROM runs WHERE status IN ('queued', 'running') LIMIT 1"
        )
    return row is not None


def save_finding(record: dict[str, Any], evidence_rows: list[dict[str, Any]]) -> int:
    now = utc_now()
    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                "SELECT * FROM findings WHERE merge_key = ?",
                (record["merge_key"],),
            ).fetchone()
            if existing:
                finding_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE findings SET
                        category = ?,
                        provider = ?,
                        asset_kind = ?,
                        label = ?,
                        identifiers_json = ?,
                        confidence = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        record["category"],
                        record["provider"],
                        record["asset_kind"],
                        record["label"],
                        json.dumps(record["identifiers"]),
                        record["confidence"],
                        record["status"],
                        now,
                        finding_id,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO findings(
                        category, provider, asset_kind, label, identifiers_json,
                        confidence, status, merge_key, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["category"],
                        record["provider"],
                        record["asset_kind"],
                        record["label"],
                        json.dumps(record["identifiers"]),
                        record["confidence"],
                        record.get("status") or "candidate",
                        record["merge_key"],
                        now,
                        now,
                    ),
                )
                finding_id = int(cur.lastrowid)
            for item in evidence_rows:
                conn.execute(
                    """
                    INSERT INTO evidence(
                        finding_id, message_id, source_id, external_id,
                        message_date, subject, excerpt
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(finding_id, source_id, external_id) DO UPDATE SET
                        message_date = excluded.message_date,
                        subject = excluded.subject,
                        excerpt = excluded.excerpt
                    """,
                    (
                        finding_id,
                        item.get("message_id"),
                        item.get("source_id"),
                        item.get("external_id") or "",
                        item.get("message_date") or "",
                        (item.get("subject") or "")[:300],
                        (item.get("excerpt") or "")[:500],
                    ),
                )
            conn.commit()
            return finding_id
        finally:
            conn.close()


def list_findings(status_filter: str = "active") -> list[dict[str, Any]]:
    sql = "SELECT * FROM findings"
    params: tuple[Any, ...] = ()
    if status_filter == "active":
        sql += " WHERE status IN ('candidate', 'confirmed')"
    elif status_filter in {"candidate", "confirmed", "dismissed"}:
        sql += " WHERE status = ?"
        params = (status_filter,)
    sql += " ORDER BY confidence DESC, provider COLLATE NOCASE"
    with _lock:
        rows = _rows(sql, params)
        evidence = _rows(
            "SELECT * FROM evidence ORDER BY message_date DESC, id DESC"
        )
    by_finding: dict[int, list[dict[str, Any]]] = {}
    for item in evidence:
        by_finding.setdefault(int(item["finding_id"]), []).append(item)
    for row in rows:
        row["identifiers"] = json.loads(row.pop("identifiers_json") or "[]")
        row["evidence"] = by_finding.get(int(row["id"]), [])
    return rows


def finding_counts() -> dict[str, int]:
    with _lock:
        rows = _rows("SELECT status, COUNT(*) AS n FROM findings GROUP BY status")
    counts = {"candidate": 0, "confirmed": 0, "dismissed": 0}
    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    counts["active"] = counts["candidate"] + counts["confirmed"]
    counts["all"] = counts["active"] + counts["dismissed"]
    return counts


def save_proposal(finding_id: int, action: str, reason: str) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE findings
                SET proposed_action = ?, proposed_reason = ?, action_status = 'proposed', updated_at = ?
                WHERE id = ? AND action_status != 'accepted'
                """,
                (action[:240], reason[:400], utc_now(), finding_id),
            )
            conn.commit()
        finally:
            conn.close()


def save_action_choice(finding_id: int, chosen: str, note: str) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE findings
                SET chosen_action = ?, action_note = ?, action_status = 'accepted', updated_at = ?
                WHERE id = ?
                """,
                (chosen[:240], note[:500], utc_now(), finding_id),
            )
            conn.commit()
        finally:
            conn.close()


def enqueue_job(finding_id: int, action: str) -> int:
    now = utc_now()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO jobs(finding_id, action, status, note, packet_path, created_at, updated_at)
                VALUES(?, ?, 'queued', '', '', ?, ?)
                """,
                (finding_id, action[:500], now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def claim_job() -> dict[str, Any] | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ? AND status = 'queued'",
                (utc_now(), job["id"]),
            )
            conn.commit()
            return job
        finally:
            conn.close()


def finish_job(job_id: int, status: str, note: str, packet_path: str = "") -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, note = ?, packet_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, note[:500], packet_path, utc_now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_job_reply(job_id: int, reply_status: str, reply_note: str, reply_file: str | None = None) -> None:
    with _lock:
        conn = connect()
        try:
            if reply_file is None:
                conn.execute(
                    "UPDATE jobs SET reply_status = ?, reply_note = ?, updated_at = ? WHERE id = ?",
                    (reply_status, reply_note[:8000], utc_now(), job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET reply_status = ?, reply_note = ?, reply_file = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (reply_status, reply_note[:8000], reply_file, utc_now(), job_id),
                )
            conn.commit()
        finally:
            conn.close()


def list_jobs(limit: int = 200) -> list[dict[str, Any]]:
    with _lock:
        return _rows(
            """
            SELECT jobs.*, findings.label, findings.provider
            FROM jobs
            LEFT JOIN findings ON findings.id = jobs.finding_id
            ORDER BY jobs.id DESC
            LIMIT ?
            """,
            (limit,),
        )


def get_job(job_id: int) -> dict[str, Any] | None:
    with _lock:
        return _one(
            """
            SELECT jobs.*, findings.label, findings.provider
            FROM jobs
            LEFT JOIN findings ON findings.id = jobs.finding_id
            WHERE jobs.id = ?
            """,
            (job_id,),
        )


def save_finding_guide(finding_id: int, guide: dict) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE findings SET guide_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(guide, ensure_ascii=False)[:200000], utc_now(), finding_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_finding_status(finding_id: int, status: str) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE findings SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), finding_id),
            )
            conn.commit()
        finally:
            conn.close()


def load_finding_row(merge_key: str) -> dict[str, Any] | None:
    with _lock:
        row = _one("SELECT * FROM findings WHERE merge_key = ?", (merge_key,))
    if not row:
        return None
    row["identifiers"] = json.loads(row.pop("identifiers_json") or "[]")
    return row
