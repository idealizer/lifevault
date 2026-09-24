"""Background queue for the step an executor confirms."""

from __future__ import annotations

import logging
import threading
import time

from app.db import claim_job, evidence_messages, finish_job, list_findings
from app.pipeline.letters import write_packet

log = logging.getLogger(__name__)
_started = False


def run_job(job: dict) -> None:
    finding = next((row for row in list_findings("all") if row["id"] == job["finding_id"]), None)
    if not finding:
        finish_job(job["id"], "error", "The asset is no longer in the vault.")
        return
    try:
        packet, note = write_packet(job["id"], finding, job["action"], _source_text(job["finding_id"]))
    except Exception:
        log.exception("job failed")
        finish_job(job["id"], "error", "The letter could not be prepared.")
        return
    finish_job(job["id"], "done", note, packet)


def _loop() -> None:
    while True:
        job = claim_job()
        if not job:
            time.sleep(1)
            continue
        run_job(job)


def _source_text(finding_id: int) -> str:
    chunks = []
    for row in evidence_messages(finding_id):
        chunks.append(row.get("subject") or row.get("evidence_subject") or "")
        chunks.append(row.get("body") or row.get("snippet") or row.get("excerpt") or row.get("evidence_excerpt") or "")
    return "\n".join(chunks)


def start_queue() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="lifevault-queue", daemon=True).start()
