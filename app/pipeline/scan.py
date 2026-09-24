"""Background discovery scan. Message bodies are kept in memory for the model call only."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.config import batch_size, body_chars
from app.connectors.base import ConnectorError
from app.db import (
    assign_run,
    get_run,
    get_source,
    load_finding_row,
    mark_extracted,
    messages_to_extract,
    list_messages,
    save_finding,
    save_message_body,
    update_run,
    update_source_secret,
    upsert_message,
)
from app.llm.client import ModelError, complete, resolve_llm
from app.pipeline.extract import batch_prompt, estimate_tokens, parse_findings
from app.pipeline.merge import collapse_findings, merge_finding_records
from app.pipeline.screen import screen_message
from app.pipeline.signals import signals_for_message
from app.textutil import truncate_text

log = logging.getLogger(__name__)


def window_start(years: int) -> str:
    years = min(15, max(1, years))
    return (date.today() - timedelta(days=365 * years)).isoformat()


def execute_scan(run_id: int, years: int, max_messages: int, force: bool) -> None:
    run = get_run(run_id)
    if not run:
        return
    if not resolve_llm()["api_key"]:
        update_run(run_id, status="error", error="Add an API key in settings.")
        return
    source = get_source(int(run["source_id"]), with_secret=True)
    if not source:
        update_run(run_id, status="error", error="Mailbox no longer exists.")
        return
    update_run(run_id, status="running", note="Reading headers")
    if source.get("kind") == "file":
        _scan_file(run_id, source, max_messages, force)
        return
    connector = None
    try:
        connector = _open_connector(source)
        since = run["window_start"]
        seen = 0
        screened = 0
        for header in connector.iter_headers(since, max_messages):
            if _stopped(run_id):
                update_run(run_id, status="stopped", note="Stopped", messages_seen=seen, messages_screened=screened)
                return
            hit = screen_message(header.from_addr, header.subject, header.snippet)
            message_id = upsert_message(
                source["id"],
                header.external_id,
                header.message_date,
                header.from_addr,
                header.subject,
                header.snippet,
                hit,
                run_id,
            )
            _store_batch(
                [
                    {
                        "id": message_id,
                        "source_id": source["id"],
                        "external_id": header.external_id,
                        "message_date": header.message_date,
                        "subject": header.subject,
                        "excerpt": header.snippet,
                    }
                ],
                signals_for_message(
                    {
                        "id": message_id,
                        "from_addr": header.from_addr,
                        "subject": header.subject,
                        "snippet": header.snippet,
                    }
                ),
            )
            seen += 1
            screened += 1 if hit else 0
            if seen % 50 == 0:
                update_run(run_id, messages_seen=seen, messages_screened=screened, note="Reading headers")
        update_run(run_id, messages_seen=seen, messages_screened=screened, note="Reading matched messages")
        pending = messages_to_extract(source["id"], run_id, force)
        _extract_batches(run_id, connector, pending, int(run["token_budget"]))
    except ConnectorError as exc:
        update_run(run_id, status="error", error=str(exc))
    except ModelError as exc:
        update_run(run_id, status="error", error=str(exc))
    except Exception:
        log.exception("scan failed")
        update_run(run_id, status="error", error="Scan failed.")
    finally:
        if connector is not None:
            connector.close()
        if source.get("kind") == "gmail" and connector is not None and getattr(connector, "secret", None):
            update_source_secret(source["id"], connector.secret)


def _scan_file(run_id: int, source: dict, max_messages: int, force: bool) -> None:
    try:
        seen = assign_run(source["id"], run_id, max_messages)
        update_run(run_id, messages_seen=seen, messages_screened=seen, note="Reading imported messages")
        pending = messages_to_extract(source["id"], run_id, force)
        for message in pending:
            _store_batch(
                [message],
                signals_for_message(
                    {
                        "id": message["id"],
                        "from_addr": message.get("from_addr") or "",
                        "subject": message.get("subject") or "",
                        "snippet": message.get("body") or message.get("snippet") or "",
                    }
                ),
            )
        _extract_batches(run_id, None, pending, int(get_run(run_id)["token_budget"]))
    except ModelError as exc:
        update_run(run_id, status="error", error=str(exc))
    except Exception:
        log.exception("file scan failed")
        update_run(run_id, status="error", error="Scan failed.")


def _open_connector(source: dict):
    if source["kind"] == "gmail":
        from app.connectors.gmail import GmailConnector

        return GmailConnector(source["secret"])
    from app.connectors.imap import ImapConnector

    config = source["config"]
    secret = source["secret"]
    connector = ImapConnector(
        config["host"],
        int(config.get("port") or 993),
        config["username"],
        secret["password"],
        config.get("mailbox") or "INBOX",
    )
    return connector.open()


def _stopped(run_id: int) -> bool:
    run = get_run(run_id)
    return bool(run and run["status"] == "stopping")


def _extract_batches(run_id: int, connector, pending: list[dict], budget: int) -> None:
    run = get_run(run_id) or {}
    tokens_used = int(run.get("tokens_used") or 0)
    size = batch_size()
    limit = body_chars()
    batches = 0
    budget_hit = False
    for offset in range(0, len(pending), size):
        if _stopped(run_id):
            update_run(run_id, status="stopped", note="Stopped", tokens_used=tokens_used, batches_done=batches)
            return
        chunk = pending[offset : offset + size]
        prepared = []
        for message in chunk:
            stored = message.get("body") or ""
            if stored:
                body = truncate_text(stored, limit)
            elif connector is not None:
                body = truncate_text(connector.fetch_body(message["external_id"]), limit)
            else:
                body = truncate_text(message.get("snippet") or "", limit)
            prepared.append({**message, "body": body, "excerpt": truncate_text(body, 500)})
        prompt = batch_prompt(prepared)
        estimate = estimate_tokens(prompt)
        if tokens_used + estimate > budget:
            budget_hit = True
            break
        local = []
        for message in prepared:
            local.extend(signals_for_message(message))
        _store_batch(prepared, local)
        update_run(run_id, note=f"Analysing batch {batches + 1}", tokens_used=tokens_used)
        text, used = complete(prompt)
        tokens_used += used
        batches += 1
        parsed = parse_findings(text)
        _store_batch(prepared, parsed)
        if not parsed:
            update_run(run_id, note="Model returned no extra rows. Local signals were saved.")
        for message in prepared:
            mark_extracted(int(message["id"]), message["excerpt"], message.get("body") or "")
        update_run(run_id, tokens_used=tokens_used, batches_done=batches, note=f"Analysed batch {batches}")
    note = "Stopped at the token budget. Raise the budget to analyse more mail." if budget_hit else "Scan finished"
    update_run(run_id, status="done", note=note, tokens_used=tokens_used, batches_done=batches)


def _store_batch(messages: list[dict], findings: list[dict]) -> None:
    by_ref = {}
    for message in messages:
        by_ref[str(message["id"])] = message
        by_ref[str(message["external_id"])] = message
    for finding in collapse_findings(findings):
        matched = []
        for ref in finding.get("evidence_ids") or []:
            message = by_ref.get(str(ref))
            if message and message not in matched:
                matched.append(message)
        if not matched:
            continue
        existing = load_finding_row(finding["merge_key"])
        if existing:
            existing["evidence_ids"] = []
        record = merge_finding_records(existing, finding)
        evidence = [
            {
                "message_id": message["id"],
                "source_id": message["source_id"],
                "external_id": message["external_id"],
                "message_date": message.get("message_date") or "",
                "subject": message.get("subject") or "",
                "excerpt": finding.get("excerpt") or message.get("excerpt") or "",
            }
            for message in matched
        ]
        save_finding(record, evidence)


def message_body(message: dict) -> str:
    stored = (message.get("body") or "").strip()
    if stored:
        return stored
    source_id = message.get("source_id")
    external_id = message.get("external_id") or ""
    if not source_id or not external_id:
        return (message.get("excerpt") or message.get("snippet") or message.get("evidence_excerpt") or "").strip()
    source = get_source(int(source_id), with_secret=True)
    if not source or source.get("kind") not in {"imap", "gmail"}:
        return (message.get("excerpt") or message.get("snippet") or "").strip()
    connector = None
    try:
        connector = _open_connector(source)
        body = connector.fetch_body(external_id)
    except ConnectorError:
        body = ""
    finally:
        if connector is not None:
            connector.close()
    if body.strip() and message.get("id"):
        save_message_body(int(message["id"]), body)
        return body.strip()
    return (message.get("excerpt") or message.get("snippet") or message.get("evidence_excerpt") or "").strip()


def backfill_signals() -> int:
    saved = 0
    for message in list_messages():
        found = signals_for_message(message)
        if not found:
            continue
        _store_batch([message], found)
        saved += len(found)
    return saved
